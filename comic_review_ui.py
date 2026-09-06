"""Read-only history screens and reusable, stable-ID review list widgets.

This module deliberately has no import of the processing app or network client.
History views consume stored snapshots only; the app adapter is for presentation.
"""
from __future__ import annotations

import base64
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from math import ceil
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

import pandas as pd


PAGE_SIZE = 50
STATUSES = ("出力可能", "注意あり", "要確認", "除外", "未処理")
STATUS_ICONS = {"出力可能": "✓", "注意あり": "⚠", "要確認": "!", "除外": "×", "未処理": "…"}
JST = timezone(timedelta(hours=9))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def display_timestamp(value: Any) -> str:
    text = _text(value)
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(JST).strftime("%Y/%m/%d %H:%M")
    except ValueError:
        return text


def safe_image_url(value: Any) -> str:
    text = _text(value)
    if text.startswith(("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")):
        return text
    try:
        parsed = urlsplit(text)
        return text if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password else ""
    except ValueError:
        return ""


def image_data_url(image: Mapping[str, Any] | None) -> str:
    if not image or not isinstance(image.get("data"), bytes):
        return ""
    mime = _text(image.get("mime"))
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        return ""
    return f"data:{mime};base64,{base64.b64encode(image['data']).decode('ascii')}"


def status_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(_text(row.get("status")) for row in records)
    return {status: counts[status] for status in STATUSES}


def filter_review_records(
    records: Iterable[Mapping[str, Any]], search: str = "", status: str = "すべて"
) -> list[dict[str, Any]]:
    """Keep stable IDs and input ordering while filtering user-facing values."""
    query = search.strip().casefold()
    return [
        dict(row)
        for row in records
        if (status in {"", "すべて"} or _text(row.get("status")) == status)
        and (not query or query in " ".join(_text(row.get(key)) for key in ("title", "source_title", "file_name")).casefold())
    ]


def selected_record_id(records: list[Mapping[str, Any]], selection: Any) -> str | None:
    """Resolve a visible row/cell offset to the stored ID, never to a CSV row ID."""
    if not isinstance(selection, (list, tuple)) or not selection:
        return None
    first = selection[0]
    if isinstance(first, (list, tuple)):
        if not first:
            return None
        first = first[0]
    if isinstance(first, bool):
        return None
    try:
        position = int(first)
    except (TypeError, ValueError):
        return None
    if not 0 <= position < len(records):
        return None
    return _text(records[position].get("id")) or None


def review_display_frame(records: list[Mapping[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "画像": safe_image_url(row.get("image_url")),
            "タイトル": _text(row.get("title")) or "タイトル未取得",
            "判定": f"{STATUS_ICONS.get(_text(row.get('status')), '')} {_text(row.get('status'))}".strip(),
            "変更・確認ポイント": _text(row.get("change_summary")) or "-",
            "送料 USD": _text(row.get("shipping")) or "-",
            "商品元タイトル": _text(row.get("source_title")) or "-",
            **({"CSV名": _text(row.get("file_name")), "処理日時": display_timestamp(row.get("created_at"))} if row.get("created_at") else {}),
        }
        for row in records
    ])


def _restore_widget(st, key: str, default: Any) -> None:
    # Streamlit removes widget-owned state when the detail view hides a widget.
    # Keep its value in a non-widget key so returning to the list restores it.
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(f"{key}__saved", default)


def _remember_widget(st, key: str, value: Any) -> None:
    st.session_state[f"{key}__saved"] = value


def _page_selector(st, total: int, key: str) -> tuple[int, int]:
    pages = max(1, ceil(total / PAGE_SIZE))
    _restore_widget(st, key, 1)
    current = st.session_state.get(key, 1)
    if current not in range(1, pages + 1):
        st.session_state[key] = 1
    left, right = st.columns([3, 1])
    with right:
        page = st.selectbox("ページ", range(1, pages + 1), key=key, format_func=lambda number: f"{number} / {pages}")
        _remember_widget(st, key, page)
    with left:
        start = (page - 1) * PAGE_SIZE
        st.caption(f"{total:,}件中 {start + 1 if total else 0:,}–{min(start + PAGE_SIZE, total):,}件 · 1ページ50件")
    return page, (page - 1) * PAGE_SIZE


def render_unified_review_list(
    st, records: list[Mapping[str, Any]], *, key: str, paginated: bool = True, show_filters: bool = True
) -> str | None:
    """Render selectable products; return an immutable caller-supplied record ID.

    All filter/page widget keys survive opening a detail. The table key advances
    after a selection so returning to the list cannot reopen the stale selection.
    """
    visible = list(records)
    if show_filters:
        _restore_widget(st, f"{key}_search", "")
        _restore_widget(st, f"{key}_status", "すべて")
        search_col, status_col = st.columns([3, 2])
        with search_col:
            search = st.text_input("タイトルを検索", key=f"{key}_search", placeholder="英語タイトル・商品元タイトル・CSV名")
        with status_col:
            status = st.selectbox("判定で絞り込み", ["すべて", *STATUSES], key=f"{key}_status")
        _remember_widget(st, f"{key}_search", search)
        _remember_widget(st, f"{key}_status", status)
        visible = filter_review_records(visible, search, status)
        signature = (search, status)
        if st.session_state.get(f"{key}_filter_signature") != signature:
            st.session_state[f"{key}_page"] = 1
            st.session_state[f"{key}_filter_signature"] = signature
        counts = status_summary(records)
        st.caption(" · ".join(f"{status} {count:,}件" for status, count in counts.items() if count))
    if paginated:
        _, offset = _page_selector(st, len(visible), f"{key}_page")
        visible = visible[offset:offset + PAGE_SIZE]
    if not visible:
        st.info("この条件に該当する商品はありません。検索文字や判定を変更してください。")
        return None
    _restore_widget(st, f"{key}_cards", True)
    cards = st.toggle("画像グリッド表示", key=f"{key}_cards")
    _remember_widget(st, f"{key}_cards", cards)
    if cards:
        # Scope responsive columns to this list; other page columns are untouched.
        grid_key = f"{key}_grid"
        st.markdown(f"""<style>
        .st-key-{grid_key} [data-testid="stHorizontalBlock"] {{
            display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .75rem;
        }}
        .st-key-{grid_key} [data-testid="stColumn"] {{ width: 100%; min-width: 0; }}
        .st-key-{grid_key} [data-testid="stVerticalBlock"] {{ gap: .4rem; }}
        .st-key-{grid_key} [data-testid="stImage"] {{ width: 100%; }}
        .st-key-{grid_key} [data-testid="stImage"] img {{
            width: 100%; height: 170px; object-fit: contain; border-radius: 8px;
        }}
        .st-key-{grid_key} [data-testid="stButton"] button {{
            min-height: 4.3rem; width: 100%; padding: .35rem .5rem; text-align: left;
        }}
        .st-key-{grid_key} [data-testid="stButton"] button p {{
            display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;
            overflow: hidden; text-align: left; font-size: .85rem; line-height: 1.3;
        }}
        .st-key-{grid_key} [data-testid="stCaptionContainer"] p {{
            font-size: .75rem; margin-bottom: 0; overflow-wrap: anywhere;
        }}
        @media (max-width: 900px) {{
            .st-key-{grid_key} [data-testid="stHorizontalBlock"] {{
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }}
        }}
        @media (max-width: 540px) {{
            .st-key-{grid_key} [data-testid="stHorizontalBlock"] {{ gap: .5rem; }}
            .st-key-{grid_key} [data-testid="stImage"] img {{ height: 135px; }}
        }}
        </style>""", unsafe_allow_html=True)
        st.caption("画像を横並びで表示します。タイトルを選ぶと詳細を確認できます。")
        with st.container(key=grid_key):
            for offset in range(0, len(visible), 4):
                columns = st.columns(4, gap="small")
                for column, record in zip(columns, visible[offset:offset + 4]):
                    with column:
                        with st.container(border=True):
                            image_url = safe_image_url(record.get("image_url"))
                            if image_url:
                                st.image(image_url, use_container_width=True)
                            else:
                                st.markdown('<div style="height:170px;display:grid;place-items:center;color:#64748b">画像なし</div>', unsafe_allow_html=True)
                            st.caption(f"{_text(record.get('status'))} · 送料 {_text(record.get('shipping')) or '-'}")
                            title = _text(record.get("title")) or "商品詳細"
                            if st.button(title, key=f"{key}_card_{record['id']}", help=title, use_container_width=True):
                                return _text(record["id"])
                            st.caption(_text(record.get("change_summary")) or "変更なし")
                            if record.get("file_name"):
                                st.caption(f"{record['file_name']} · {display_timestamp(record.get('created_at'))}")
        return None
    st.caption("画像またはタイトルをクリックすると商品詳細が開きます。一覧に戻っても検索条件とページ位置は残ります。")
    generation_key = f"{key}_table_generation"
    generation = int(st.session_state.get(generation_key, 0))
    event = st.dataframe(
        review_display_frame(visible), hide_index=True, use_container_width=True,
        height=min(780, len(visible) * 170 + 44), row_height=170,
        on_select="rerun", selection_mode="single-cell", key=f"{key}_table_{generation}",
        column_config={
            "画像": st.column_config.ImageColumn("画像", width=190),
            "タイトル": st.column_config.TextColumn("タイトル・商品詳細", width=370),
            "判定": st.column_config.TextColumn("判定", width=110),
            "変更・確認ポイント": st.column_config.TextColumn("変更・確認ポイント", width=280),
            "送料 USD": st.column_config.TextColumn("送料 USD", width=95),
            "商品元タイトル": st.column_config.TextColumn("商品元タイトル", width=260),
            "CSV名": st.column_config.TextColumn("CSV名", width=200),
            "処理日時": st.column_config.TextColumn("処理日時（日本時間）", width=160),
        },
    )
    try:
        selected = event.selection.cells
    except AttributeError:
        selected = event.get("selection", {}).get("cells", []) if isinstance(event, dict) else []
    item_id = selected_record_id(visible, selected)
    if item_id:
        st.session_state[generation_key] = generation + 1
    return item_id


def _history_list_record(item: Mapping[str, Any], image: Mapping[str, Any] | None = None) -> dict[str, Any]:
    summary = item.get("summary") or {}
    shipping = _text(item.get("shipping_usd"))
    return {
        "id": item["item_id"], "position": item.get("row_id"),
        "title": item.get("title", ""), "source_title": item.get("source_title", ""),
        "status": item.get("status", ""), "change_summary": item.get("change_summary", ""),
        "shipping": f"${shipping}" if shipping and not shipping.startswith("$") else shipping,
        "image_url": image_data_url(image), "file_name": item.get("file_name", ""),
        "created_at": item.get("created_at", ""),
        "image_status": item.get("image_status", summary.get("image_status", "")),
    }


def _all_history_runs(store, workspace_id: Any) -> list[dict[str, Any]]:
    """Fetch only small run metadata; item snapshots stay database-paginated."""
    runs = []
    while True:
        page = store.list_runs(workspace_id, limit=200, offset=len(runs))
        runs.extend(page)
        if len(page) < 200:
            return runs


def _render_run_tools(st, store, workspace_id: Any, runs: list[dict[str, Any]]) -> None:
    if not runs:
        return
    with st.expander("CSVごとの処理情報・再ダウンロード", expanded=False):
        run_ids = [row["run_id"] for row in runs]
        runs_by_id = {row["run_id"]: row for row in runs}
        key = "comic_review_history_run"
        _restore_widget(st, key, run_ids[0])
        if st.session_state.get(key) not in run_ids:
            st.session_state[key] = run_ids[0]
        run_id = st.selectbox(
            "処理回を選択", run_ids, key=key,
            format_func=lambda value: f"{display_timestamp(runs_by_id[value].get('created_at'))} · {runs_by_id[value].get('file_name', '')} · {'5件試行' if runs_by_id[value].get('mode') == 'trial' else '全件処理'}",
        )
        _remember_widget(st, key, run_id)
        run = store.get_run(workspace_id, run_id)
        if not run:
            st.info("選択した処理回は削除されています。")
            return
        item_count = int(run.get("item_count") or 0)
        counts = run.get("status_counts") or {}
        st.caption(f"処理済み {item_count:,}件 · " + " / ".join(f"{status} {counts.get(status, 0):,}件" for status in STATUSES if counts.get(status)))
        if run.get("status") not in {"complete", "completed", "finished"}:
            st.info("この処理回は未完了、または途中保存された結果です。保存済みの商品だけを確認できます。")
        cost = run.get("cost_summary") or {}
        if cost:
            try:
                tokens_cost = float(cost.get("total_cost_jpy") or 0)
                search_cost = float(cost.get("grounding_list_cost_jpy") or 0)
                st.markdown(f"**当時のAPI料金（概算）**　トークン 約¥{tokens_cost:,.4f} ／ 検索連携 定価換算 約¥{search_cost:,.4f}")
                st.caption("無料枠や個別契約を反映した請求確定額ではありません。")
            except (TypeError, ValueError):
                st.caption("API料金の詳細は保存情報を確認してください。")
        exports = store.list_exports(workspace_id, run_id)
        if exports:
            by_id = {entry["export_id"]: entry for entry in exports}
            export_key = f"comic_review_history_export_{run_id}"
            export_id = st.selectbox(
                "保存された出力版", list(by_id), key=export_key,
                format_func=lambda value: f"{display_timestamp(by_id[value].get('created_at'))} · {len(by_id[value].get('row_ids') or []):,}件 · {by_id[value].get('filename', '')}",
            )
            export = store.get_export(workspace_id, export_id)
            if export:
                st.download_button(
                    f"保存時のCSVをダウンロード（{len(export.get('row_ids') or []):,}件）",
                    data=export["csv_bytes"], file_name=export["filename"], mime="text/csv",
                    key=f"comic_review_history_download_{export_id}", type="primary", use_container_width=True,
                )
                st.caption("出力を用意した時点の内容です。現在の為替・送料設定では再計算しません。")
        else:
            st.info("この処理回には保存されたCSVがありません。商品ごとの精査結果は一覧から確認できます。")
        with st.expander("当時の設定・API料金の詳細", expanded=False):
            st.json({"settings": run.get("settings") or {}, "api_cost": cost, "processing_version": run.get("processing_version"), "status": run.get("status")})
        st.divider()
        st.caption("履歴だけを削除します。現在の作業データやeBay上の商品は削除されません。")
        deletion = store.preview_delete_runs(workspace_id, [run_id])
        st.caption(f"削除対象：商品履歴 {deletion['items']}件 / 保存CSV {deletion['exports']}件 / 不要になる代表画像 {deletion['images']}枚")
        if deletion.get("cross_run_exports"):
            st.warning("削除する商品を含む合算CSVも削除対象です。他の処理回の商品履歴は残ります。")
            for related in deletion["cross_run_exports"]:
                st.text(related["filename"])
        checked = st.checkbox(
            f"この処理回の履歴 {item_count:,}件と上記の保存CSV {deletion['exports']}件を削除することを確認しました",
            key=f"comic_review_history_confirm_delete_{run_id}",
        )
        if st.button("この処理回の履歴を削除", disabled=not checked, key=f"comic_review_history_delete_{run_id}"):
            from comic_review_workflow import forget_deleted_runs
            deleted_item_ids = [item["item_id"] for item in store.list_run_items(workspace_id, run_id)]
            deleted = store.delete_runs(workspace_id, [run_id])
            forget_deleted_runs(st, [run_id], deleted_item_ids)
            st.session_state.pop("comic_review_history_selected_item", None)
            st.session_state["comic_review_history_notice"] = f"履歴を削除しました（{deleted.get('items', item_count):,}件）。現在のCSV作業は保持しています。削除した商品の履歴を再び残すには、新しく精査してください。"
            st.rerun()


def _render_history_detail(st, store, workspace_id: Any, item: dict[str, Any], app) -> None:
    if st.button("← 精査一覧に戻る", key="comic_review_history_back"):
        st.session_state.pop("comic_review_history_selected_item", None)
        st.rerun()
    st.caption(f"{item.get('file_name', '')} · {display_timestamp(item.get('created_at'))}（日本時間）")
    run = store.get_run(workspace_id, item["run_id"])
    if not run:
        st.warning("この商品の処理回は削除されています。")
        return
    settings = run.get("settings") or {}
    config = settings.get("processing") or settings.get("config") or settings.get("process_config") or settings
    revisions = store.get_revisions(workspace_id, item["item_id"])
    snapshots = {"現在の保存内容": item.get("processed") or {}}
    if revisions:
        snapshots["自動判定時（手動補正前）"] = item.get("automatic") or {}
        for index, revision in enumerate(revisions, start=1):
            label = f"手動補正 {index} · {display_timestamp(revision.get('created_at'))}"
            snapshots[label] = revision.get("processed") or {}
        choice = st.selectbox("変更履歴", list(snapshots), key=f"comic_review_history_revision_{item['item_id']}")
        row_dict = snapshots[choice]
    else:
        row_dict = snapshots["現在の保存内容"]
    archived_image = store.get_image(workspace_id, item["image_digest"]) if item.get("image_digest") else None
    if not archived_image:
        st.caption("代表画像は保存されていません。追加画像のURLは処理当時の情報です。")
    try:
        row_position = int(item.get("row_id") or 0)
    except (ValueError, TypeError):
        row_position = 0
    app.render_selected_preview(
        st, pd.Series(row_dict, dtype=object), row_position,
        _text(config.get("title_col")) or "Title", _text(config.get("price_col")) or "StartPrice",
        _text(config.get("image_col")) or "PicURL", _text(config.get("url_col")) or "PicURL",
        readonly=True, original_row=pd.Series(item.get("original") or {}, dtype=object),
        archived_image=archived_image["data"] if archived_image else None,
    )
    rollup = settings.get("rollup")
    if isinstance(rollup, dict) and rollup:
        with st.expander("当時の送料無料価格転嫁", expanded=False):
            app.render_free_shipping_rollup_preview(st, pd.Series(row_dict, dtype=object), app.FreeShippingRollupOptions(**rollup))


def render_history_page(st, store, workspace_id: Any, app) -> None:
    """Cross-CSV history. All data comes from ``store``; no processing calls."""
    st.subheader("精査履歴")
    st.caption("過去のCSVを横断して、どの商品をどう精査したか確認できます。表示は当時の判定であり、現在の在庫・状態を保証するものではありません。")
    if notice := st.session_state.pop("comic_review_history_notice", None):
        st.success(notice)
    try:
        _render_history_page_contents(st, store, workspace_id, app)
    except Exception as exc:
        # Never expose database URLs, credentials, or source response dumps.
        st.error("精査履歴を読み込めませんでした。現在の作業はそのまま続けられます。")
        st.caption(f"エラー種別: {type(exc).__name__}")
        if st.button("履歴を再読み込み", key="comic_review_history_retry_load"):
            st.rerun()


def _render_history_page_contents(st, store, workspace_id: Any, app) -> None:
    # A selected product is the primary content, not an appendix below the list
    # controls. Persistent shadow values restore those controls when returning.
    selected_id = st.session_state.get("comic_review_history_selected_item")
    if selected_id:
        selected = store.get_item(workspace_id, selected_id)
        if selected:
            _render_history_detail(st, store, workspace_id, selected, app)
            return
        st.session_state.pop("comic_review_history_selected_item", None)
        st.warning("選択した履歴は削除されたため、一覧を表示しています。")
    runs = _all_history_runs(store, workspace_id)
    if not runs:
        st.info("精査履歴はまだありません。「CSVを精査」で処理すると、完了した商品から自動保存されます。")
        st.caption("履歴保存機能の導入前に失われた作業セッションは復元できません。")
        return
    _render_run_tools(st, store, workspace_id, runs)
    for key, default in (("comic_review_history_search", ""),
                         ("comic_review_history_status", "すべて"),
                         ("comic_review_history_file", "すべてのCSV")):
        _restore_widget(st, key, default)
    col_search, col_status, col_file = st.columns([3, 2, 2])
    with col_search:
        search = st.text_input("履歴を検索", key="comic_review_history_search", placeholder="英語タイトル・商品元タイトル")
    with col_status:
        status = st.selectbox("履歴の判定", ["すべて", *STATUSES], key="comic_review_history_status")
    with col_file:
        files = ["すべてのCSV", *dict.fromkeys(_text(run.get("file_name")) for run in runs)]
        if st.session_state.get("comic_review_history_file", files[0]) not in files:
            st.session_state["comic_review_history_file"] = files[0]
        file_name = st.selectbox("CSV名", files, key="comic_review_history_file")
    with st.expander("処理日で絞り込む（日本時間）", expanded=False):
        date_range = st.date_input("処理日の範囲", value=st.session_state.get("comic_review_history_dates__saved", ()), key="comic_review_history_dates")
    for key, value in (("comic_review_history_search", search),
                       ("comic_review_history_status", status),
                       ("comic_review_history_file", file_name),
                       ("comic_review_history_dates", date_range)):
        _remember_widget(st, key, value)
    date_from = date_to = None
    if isinstance(date_range, (tuple, list)):
        if date_range:
            date_from = datetime.combine(date_range[0], datetime.min.time(), JST).astimezone(timezone.utc).isoformat()
        if len(date_range) == 2:
            date_to = (datetime.combine(date_range[1] + timedelta(days=1), datetime.min.time(), JST).astimezone(timezone.utc) - timedelta(microseconds=1)).isoformat()
    signature = (search, status, file_name, date_from, date_to)
    if st.session_state.get("comic_review_history_filter_signature") != signature:
        st.session_state["comic_review_history_page"] = 1
        st.session_state["comic_review_history_filter_signature"] = signature
    filters = dict(search=search, status="" if status == "すべて" else status,
                   file_name="" if file_name == "すべてのCSV" else file_name, date_from=date_from, date_to=date_to)
    _restore_widget(st, "comic_review_history_page", 1)
    current_page = max(1, int(st.session_state.get("comic_review_history_page", 1)))
    items, total = store.list_items(workspace_id, **filters, offset=(current_page - 1) * PAGE_SIZE, limit=PAGE_SIZE)
    page, offset = _page_selector(st, total, "comic_review_history_page")
    if page != current_page:
        items, total = store.list_items(workspace_id, **filters, offset=offset, limit=PAGE_SIZE)
    image_cache = {}
    for item in items:
        digest = item.get("image_digest")
        if digest and digest not in image_cache:
            image_cache[digest] = store.get_image(workspace_id, digest)
    records = [_history_list_record(item, image_cache.get(item.get("image_digest"))) for item in items]
    selected_id = render_unified_review_list(st, records, key="comic_review_history_list", paginated=False, show_filters=False)
    if selected_id:
        st.session_state["comic_review_history_selected_item"] = selected_id
        st.rerun()
