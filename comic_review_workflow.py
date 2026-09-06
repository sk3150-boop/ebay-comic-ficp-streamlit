"""Session-to-history integration. Never retains API credentials in snapshots."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import uuid

import pandas as pd

from comic_review_history import ReviewHistoryStore, stable_item_id
from comic_review_images import archive_review_image

PENDING = "comic_review_pending_saves"
RUNS = "comic_review_runs"
ROW_RUNS = "comic_review_row_runs"
ORIGINALS = "comic_review_original_rows"

# Processing uses "Excluded" both for actual listing exclusions and for
# uncertainty that must hold CSV output until reviewed. This is a presentation
# distinction only: never relax the application's existing export eligibility.
REVIEW_HOLD_REASONS = frozenset(reason.casefold() for reason in (
    "確認が必要なため出品除外",
    "海外タイトルを確認できません",
    "Book count unavailable and no complete-set claim",
    "Series title could not be identified",
    "Complete-set count reference not found",
    "Shipping could not be calculated",
))


def safe_settings(config, rollup) -> dict:
    processing = asdict(config)
    # Explicitly exclude credentials and the unrelated complete override registry.
    processing.pop("ai_api_key", None)
    processing.pop("title_overrides", None)
    return {"processing": processing, "rollup": asdict(rollup)}


def review_status(row, app, *, processed: bool | None = None) -> str:
    """Derive a consistent display status without modifying the saved decision.

    Genuine exclusions also carry ``Needs Review=Yes`` in existing diagnostics,
    so that flag alone must not turn missing volumes/magazines/limit violations
    into ordinary review holds. Conversely, a failed title lookup is a hold,
    even though its safe CSV decision is persisted as ``Excluded``.
    """
    clean_row = pd.Series(row, dtype=object).fillna("")
    diagnostics = app.diagnose_processed_row(clean_row)

    def value(column):
        return str(clean_row.get(column, "")).strip()

    stored_result = value("Processing Result")
    has_stored_decision = any(value(column) for column in (
        "Processing Result", "Listing Eligibility", "Needs Review", "Exclusion Reason",
    ))
    # Historical projections can intentionally contain only these decision
    # fields. Do not redo completeness checks on an incomplete presentation row.
    result = stored_result or ("" if has_stored_decision else diagnostics["result"])
    if processed is False or (processed is None and diagnostics["result"] == "未処理"):
        return "未処理"

    reason = value("Exclusion Reason").casefold()
    excluded = value("Listing Eligibility").casefold() == "excluded" or result == "出品除外"
    title_failed = value("Title Resolution Status").casefold() == "failed"
    needs_review = value("Needs Review").casefold() == "yes" or result == "確認必要"

    if excluded:
        if reason in REVIEW_HOLD_REASONS or (title_failed and not reason):
            return "要確認"
        return "除外"
    if reason in REVIEW_HOLD_REASONS or title_failed:
        return "要確認"
    if needs_review:
        return "要確認"
    if not has_stored_decision and str(diagnostics.get("needs_review", "")).casefold() == "yes":
        return "要確認"
    if value("Title Resolution Confidence").casefold() == "low" or value("Processing Severity").casefold() in {"warning", "warn", "注意"}:
        return "注意あり"
    return "出力可能"


def change_summary(original, processed, config) -> str:
    labels = [(config.title_col, "タイトル"), ("ConditionID", "商品状態"),
              ("C:Series", "作品名"), (config.description_col, "説明")]
    changes = [label for col, label in labels if col and str(original.get(col, "")) != str(processed.get(col, ""))]
    if processed.get("Rejected Source Image URL Count") not in (None, "", "0", 0):
        changes.append("別商品画像を除外")
    if processed.get("Detected Book Count"):
        changes.append(f"{processed['Detected Book Count']}冊")
    return " / ".join(changes) or "変更なし"


def review_record(row, original, config, app, item_id="", position=0) -> dict:
    row = dict(row)
    image_url = app.build_table_image_url(pd.Series(row), config.image_col)
    return {"id": str(item_id or position), "position": position,
            "title": str(row.get(config.title_col) or row.get("Source Listing Title") or "タイトルなし"),
            "source_title": str(row.get("Source Listing Title", "")),
            "status": review_status(row, app),
            "change_summary": change_summary(dict(original), row, config),
            "shipping_usd": str(row.get("FICP Shipping USD", "")),
            "sale_price": str(row.get(config.price_col, "")),
            "source_price": str(row.get("Source Listing Price", "")),
            "source_url": app.display_source_url(pd.Series(row), config.url_col),
            "shipping": f"${row['FICP Shipping USD']}" if row.get("FICP Shipping USD") else "—",
            "image_url": image_url}


def open_history(st, app):
    user = app.current_public_user(st) if app.is_public_mode() else None
    workspace = str(user["id"]) if user else "local"
    url = app.public_database_url() if app.is_public_mode() else str(app.API_KEY_STORE_PATH.with_name("review_history.sqlite3"))
    store = ReviewHistoryStore(url)
    store.init_schema()
    return store, workspace


def _attempt(st, store, key, operation, args):
    pending = st.session_state.setdefault(PENDING, {})
    pending[key] = (operation, args)
    if store is None:
        return False
    try:
        getattr(store, operation)(**args)
    except Exception:
        # Pending data contains sanitized settings, never exception URLs/secrets.
        return False
    pending.pop(key, None)
    return True


def retry_pending(st, store):
    for key, (operation, args) in list(st.session_state.get(PENDING, {}).items()):
        _attempt(st, store, key, operation, args)


def render_save_health(st, store):
    pending = st.session_state.get(PENDING, {})
    if pending:
        st.warning(f"履歴未保存のデータが {len(pending)} 件あります。この画面を閉じる前に保存を再試行してください。AIは再実行しません。")
        if st.button("履歴の保存だけ再試行", key="comic_review_retry", disabled=store is None):
            retry_pending(st, store)
            st.rerun()


def start_run(st, store, workspace, file_key, file_name, indices, config, rollup, app, *, mode):
    run_id = uuid.uuid4().hex
    run = {"run_id": run_id, "workspace_id": workspace, "file_name": Path(file_name).name,
           "mode": mode, "settings": safe_settings(config, rollup),
           "processing_version": app.PROCESSING_LOGIC_VERSION, "status": "running",
           "created_at": datetime.now(timezone.utc).isoformat(), "target_rows": [str(i) for i in indices]}
    st.session_state.setdefault(RUNS, {})[file_key] = run
    st.session_state.setdefault(ROW_RUNS, {}).setdefault(file_key, {})
    _attempt(st, store, "run:" + run_id, "save_run", {"run": run})
    return run


def persist_row(st, store, run, file_key, index, row, original, config, app):
    row_data = {str(k): app.redact_sensitive_text(str(v)) for k, v in pd.Series(row, dtype=object).fillna("").items()}
    original_data = {str(k): app.redact_sensitive_text(str(v)) for k, v in pd.Series(original, dtype=object).fillna("").items()}
    summary = review_record(row_data, original_data, config, app, position=int(index))
    args = {"workspace_id": run["workspace_id"], "run_id": run["run_id"], "row_id": str(index),
            "original": original_data, "processed": row_data, "summary": summary}
    key = f"item:{run['run_id']}:{index}"
    _attempt(st, store, key, "save_item", args)
    image_status = str(row.get("Image URL Validation Status", "")).lower()
    urls = app.build_preview_image_urls(pd.Series(row), config.image_col)
    if urls and image_status.startswith(("verified", "ok:")):
        image = archive_review_image(urls[0], verified=True)
    else:
        image = {"status": "検証済み代表画像なし", "data": b"", "mime": "", "digest": ""}
    args = dict(args, image=image)
    _attempt(st, store, key, "save_item", args)
    st.session_state[ROW_RUNS][file_key][str(index)] = run["run_id"]
    st.session_state.setdefault(ORIGINALS, {}).setdefault(file_key, {})[str(index)] = original_data


def finish_run(st, store, run, cost_summary, *, status="completed"):
    _attempt(st, store, "finish:" + run["run_id"], "finish_run",
             {"workspace_id": run["workspace_id"], "run_id": run["run_id"],
              "status": status, "cost_summary": cost_summary})


def record_export(st, store, run, data, filename, row_indices, config, rollup, file_key=None):
    if not run or not data:
        return
    settings = safe_settings(config, rollup)
    row_ids = [str(i) for i in row_indices]
    row_runs = st.session_state.get(ROW_RUNS, {}).get(file_key, {})
    if file_key is not None and any(i not in row_runs for i in row_ids):
        # A user-deleted history must not be silently resurrected by rendering CSV controls.
        return
    source_items = [stable_item_id(run["workspace_id"], row_runs.get(i, run["run_id"]), i) for i in row_ids]
    digest = hashlib.sha256(data + json.dumps([settings, row_ids, source_items, filename], sort_keys=True).encode()).hexdigest()
    key = f"export:{run['run_id']}:{digest}"
    # Don't create another export snapshot on every Streamlit rerun.
    completed = st.session_state.setdefault("comic_review_saved_exports", set())
    if key in completed:
        return
    if _attempt(st, store, key, "save_export", {
        "workspace_id": run["workspace_id"], "run_id": run["run_id"],
        "csv_bytes": data, "filename": filename, "settings": settings,
        "row_ids": row_ids, "source_items": source_items,
    }):
        completed.add(key)


def forget_deleted_runs(st, run_ids, item_ids):
    """Remove only history references; never reset the active CSV or settings."""
    removed_runs, removed_items = set(run_ids), set(item_ids)
    for file_key, run in list(st.session_state.get(RUNS, {}).items()):
        if run["run_id"] in removed_runs:
            st.session_state[RUNS].pop(file_key, None)
    for row_map in st.session_state.get(ROW_RUNS, {}).values():
        for row_id, run_id in list(row_map.items()):
            if run_id in removed_runs:
                row_map.pop(row_id, None)
    for key, (_, args) in list(st.session_state.get(PENDING, {}).items()):
        if (args.get("run_id") in removed_runs or args.get("item_id") in removed_items
                or args.get("run", {}).get("run_id") in removed_runs
                or removed_items.intersection(args.get("source_items") or [])):
            st.session_state[PENDING].pop(key, None)


def record_manual_changes(st, store, workspace, file_key, before, after, config, app):
    row_runs = st.session_state.get(ROW_RUNS, {}).get(file_key, {})
    for index, row in after.iterrows():
        if row.equals(before.loc[index]):
            continue
        run_id = row_runs.get(str(index))
        if not run_id:
            continue
        original = st.session_state.get(ORIGINALS, {}).get(file_key, {}).get(str(index), dict(before.loc[index]))
        item_id = stable_item_id(workspace, run_id, str(index))
        processed = {str(k): app.redact_sensitive_text(str(v)) for k, v in row.fillna("").items()}
        summary = review_record(row, original, config, app, position=int(index))
        digest = hashlib.sha256(str(processed).encode()).hexdigest()
        _attempt(st, store, f"revision:{item_id}:{digest}", "save_revision", {
            "workspace_id": workspace, "item_id": item_id, "processed": processed,
            "reason": "作業画面の手動タイトル補正", "summary": summary})
