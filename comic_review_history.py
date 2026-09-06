"""Durable, workspace-scoped manga review history (no UI or network calls).

Snapshots are JSON, never executable pickle. Automatic results are immutable;
manual edits append revisions and only change the current projection. Every
public lookup and mutation requires a workspace identifier.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote
import uuid


MAX_IMAGE_BYTES = 256 * 1024
MAX_IMAGE_SIDE = 480


@dataclass
class ReviewRun:
    workspace_id: str
    file_name: str
    mode: str
    settings: dict = field(default_factory=dict)
    processing_version: str = ""
    target_rows: list = field(default_factory=list)
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "running"
    created_at: str = ""


@dataclass
class ReviewItem:
    workspace_id: str
    run_id: str
    row_id: str
    original: dict
    processed: dict
    summary: dict = field(default_factory=dict)


@dataclass
class ReviewImage:
    data: bytes
    mime: str = "image/jpeg"
    digest: str = ""
    status: str = "saved"


_SECRET_KEYS = {
    "apikey", "aikey", "password", "passwd", "passphrase", "cookie", "cookies",
    "authorization", "secret", "clientsecret", "accesstoken", "refreshtoken",
    "sessiontoken", "token", "databaseurl", "dburl", "connectionurl", "dsn",
    "encryptedvalue", "passwordhash", "privatekey", "encryptionsecret",
}
_SECRET_QUERY = _SECRET_KEYS | {"key", "signature", "credential", "auth", "jwt", "sig"}


def _key_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _secret_key(key: Any) -> bool:
    normalized = _key_name(key)
    return normalized in _SECRET_KEYS or any(
        normalized.endswith(suffix) for suffix in (
            "apikey", "password", "accesstoken", "refreshtoken", "privatekey",
            "encryptionsecret", "databaseurl", "connectionurl", "cookie", "cookies",
        )
    )


def _secret_query_key(key: Any) -> bool:
    normalized = _key_name(key)
    return normalized in _SECRET_QUERY or _secret_key(key) or normalized.endswith(("signature", "credential", "securitytoken"))


def _safe_text(value: str) -> str:
    value = re.sub(r"\b(?:postgres(?:ql)?|mysql|redis)://[^\s<>\"']+", "[redacted connection]", value, flags=re.I)
    value = re.sub(r"\bAIza[0-9A-Za-z_-]{30,}\b", "[redacted key]", value)
    value = re.sub(r"\bsk-(?:proj-)?[0-9A-Za-z_-]{20,}\b", "[redacted key]", value)
    value = re.sub(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]", value, flags=re.I)

    def clean_url(match):
        raw = match.group(0)
        try:
            parts = urlsplit(raw)
            netloc = parts.netloc.rsplit("@", 1)[-1]
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            fragment_pairs = parse_qsl(parts.fragment, keep_blank_values=True)
            if netloc == parts.netloc and not any(_secret_query_key(k) for k, _ in pairs + fragment_pairs):
                return raw
            query = [(k, "[redacted]" if _secret_query_key(k) else v) for k, v in pairs]
            fragment = parts.fragment
            if any(_secret_query_key(k) for k, _ in fragment_pairs):
                fragment = urlencode([(k, "[redacted]" if _secret_query_key(k) else v) for k, v in fragment_pairs])
            return urlunsplit((parts.scheme, netloc, parts.path, urlencode(query), fragment))
        except ValueError:
            return "[invalid URL]"

    return re.sub(r"https?://[^\s<>\"']+", clean_url, value)


def sanitize_history_value(value: Any) -> Any:
    """Convert to safe JSON data and omit credential fields recursively."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {str(k): sanitize_history_value(v) for k, v in value.items() if not _secret_key(k)}
    if isinstance(value, (list, tuple, set)):
        return [sanitize_history_value(v) for v in value]
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return "[binary omitted]"
    # pandas/numpy scalar values, without depending on either package.
    if hasattr(value, "item"):
        try:
            return sanitize_history_value(value.item())
        except (TypeError, ValueError):
            pass
    return _safe_text(str(value))


def _json(value: Any) -> str:
    return json.dumps(sanitize_history_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _timestamp(value=None) -> str:
    if not value:
        return _now()
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("Invalid review timestamp")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _identifier(value, label="identifier") -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"Review {label} is required")
    result = str(value).strip()
    if len(result) > 256:
        raise ValueError(f"Review {label} is too long")
    return result


def stable_item_id(workspace_id, run_id, row_id) -> str:
    """Resolve an item ID before a database write (e.g. a pending revision)."""
    identifiers = [_identifier(workspace_id, "workspace"), _identifier(run_id, "run"), _identifier(row_id, "row")]
    return hashlib.sha256(_json(identifiers).encode()).hexdigest()


class ReviewHistoryStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.is_postgres = database_url.startswith(("postgresql://", "postgres://"))
        if self.is_postgres:
            self.sqlite_path = None
        else:
            raw = database_url[len("sqlite:///"):] if database_url.startswith("sqlite:///") else database_url
            if not raw or raw == ":memory:":
                raise ValueError("History requires a durable database file, not an in-memory connection")
            if "://" in raw:
                raise ValueError("Unsupported review history database")
            self.sqlite_path = Path(unquote(raw)).expanduser()
        self._schema_ready = False

    @contextmanager
    def _connection(self, write=False):
        if self.is_postgres:
            import psycopg
            conn = psycopg.connect(self.database_url, connect_timeout=10)
        else:
            if write:
                self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.sqlite_path), timeout=30)
            conn.execute("PRAGMA foreign_keys = ON")
            if write:
                conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if write:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _execute(self, conn, sql: str, params=()):
        return conn.execute(sql.replace("?", "%s") if self.is_postgres else sql, params)

    @staticmethod
    def _rows(cursor):
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _one(self, conn, sql, params=()):
        rows = self._rows(self._execute(conn, sql, params))
        return rows[0] if rows else None

    def init_schema(self):
        if self._schema_ready:
            return
        binary = "BYTEA" if self.is_postgres else "BLOB"
        statements = [
            """CREATE TABLE IF NOT EXISTS comic_review_runs (
                workspace_id TEXT NOT NULL, run_id TEXT NOT NULL, file_name TEXT NOT NULL,
                mode TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                finished_at TEXT, settings_json TEXT NOT NULL, target_rows_json TEXT NOT NULL,
                processing_version TEXT NOT NULL, cost_summary_json TEXT NOT NULL,
                PRIMARY KEY (workspace_id, run_id))""",
            f"""CREATE TABLE IF NOT EXISTS comic_review_images (
                workspace_id TEXT NOT NULL, digest TEXT NOT NULL, data {binary} NOT NULL,
                mime TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY (workspace_id, digest))""",
            """CREATE TABLE IF NOT EXISTS comic_review_items (
                workspace_id TEXT NOT NULL, item_id TEXT NOT NULL, run_id TEXT NOT NULL,
                row_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                original_json TEXT NOT NULL, automatic_json TEXT NOT NULL, processed_json TEXT NOT NULL,
                summary_json TEXT NOT NULL, title TEXT NOT NULL, source_title TEXT NOT NULL,
                status TEXT NOT NULL, change_summary TEXT NOT NULL, shipping_usd REAL,
                image_digest TEXT, image_status TEXT NOT NULL,
                PRIMARY KEY (workspace_id, item_id), UNIQUE (workspace_id, run_id, row_id),
                FOREIGN KEY (workspace_id, run_id) REFERENCES comic_review_runs(workspace_id, run_id) ON DELETE CASCADE)""",
            """CREATE TABLE IF NOT EXISTS comic_review_revisions (
                workspace_id TEXT NOT NULL, revision_id TEXT NOT NULL, item_id TEXT NOT NULL,
                created_at TEXT NOT NULL, reason TEXT NOT NULL, processed_json TEXT NOT NULL,
                summary_json TEXT NOT NULL, PRIMARY KEY (workspace_id, revision_id),
                FOREIGN KEY (workspace_id, item_id) REFERENCES comic_review_items(workspace_id, item_id) ON DELETE CASCADE)""",
            f"""CREATE TABLE IF NOT EXISTS comic_review_exports (
                workspace_id TEXT NOT NULL, export_id TEXT NOT NULL, run_id TEXT NOT NULL,
                filename TEXT NOT NULL, created_at TEXT NOT NULL, digest TEXT NOT NULL,
                csv_bytes {binary} NOT NULL, settings_json TEXT NOT NULL, row_ids_json TEXT NOT NULL,
                source_items_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (workspace_id, export_id),
                FOREIGN KEY (workspace_id, run_id) REFERENCES comic_review_runs(workspace_id, run_id) ON DELETE CASCADE)""",
            "CREATE INDEX IF NOT EXISTS comic_review_items_recent ON comic_review_items(workspace_id, created_at, item_id)",
            "CREATE INDEX IF NOT EXISTS comic_review_items_status ON comic_review_items(workspace_id, status, created_at)",
            "CREATE INDEX IF NOT EXISTS comic_review_items_run ON comic_review_items(workspace_id, run_id)",
            "CREATE INDEX IF NOT EXISTS comic_review_runs_recent ON comic_review_runs(workspace_id, created_at)",
        ]
        with self._connection(write=True) as conn:
            for sql in statements:
                self._execute(conn, sql)
            if self.is_postgres:
                columns = {row[0] for row in self._execute(conn, "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='comic_review_exports'").fetchall()}
            else:
                columns = {row[1] for row in self._execute(conn, "PRAGMA table_info(comic_review_exports)").fetchall()}
            if "source_items_json" not in columns:
                self._execute(conn, "ALTER TABLE comic_review_exports ADD COLUMN source_items_json TEXT NOT NULL DEFAULT '[]'")
        self._schema_ready = True

    def save_run(self, run: Mapping | ReviewRun) -> str:
        run = asdict(run) if is_dataclass(run) else dict(run)
        workspace_id = _identifier(run.get("workspace_id"), "workspace")
        run_id = _identifier(run.get("run_id") or run.get("id") or uuid.uuid4().hex, "run")
        self.init_schema()
        values = (workspace_id, run_id, _safe_text(str(run.get("file_name", ""))),
                  str(run.get("mode", "full")), str(run.get("status", "running")),
                  _timestamp(run.get("created_at")), None, _json(run.get("settings", {})),
                  _json(run.get("target_rows", [])), str(run.get("processing_version", "")), _json(run.get("cost_summary", {})))
        with self._connection(write=True) as conn:
            self._execute(conn, """INSERT INTO comic_review_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT (workspace_id, run_id) DO NOTHING""", values)
        return run_id

    def _require_run(self, conn, workspace_id, run_id):
        if not self._one(conn, "SELECT run_id FROM comic_review_runs WHERE workspace_id=? AND run_id=?" + (" FOR UPDATE" if self.is_postgres else ""), (workspace_id, run_id)):
            raise ValueError("Review run was not found in this workspace")

    @staticmethod
    def _summary_fields(summary, processed):
        summary = sanitize_history_value(summary)
        title = str(summary.get("title", processed.get("Title", "")) or "")
        source_title = str(summary.get("source_title", "") or "")
        status = str(summary.get("status", "processed") or "processed")
        changes = summary.get("change_summary", "") or ""
        if isinstance(changes, list):
            changes = " / ".join(str(value) for value in changes)
        try:
            shipping = float(summary["shipping_usd"])
            if not math.isfinite(shipping):
                shipping = None
        except (KeyError, ValueError, TypeError):
            shipping = None
        return (title, source_title, status, str(changes), shipping)

    def _save_image(self, conn, workspace_id, image):
        if image is None:
            return None, "unavailable"
        image = asdict(image) if is_dataclass(image) else dict(image)
        if not image.get("data"):
            return None, _safe_text(str(image.get("status", "unavailable")))[:500]
        data = bytes(image["data"])
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Review image exceeds 256 KB")
        from PIL import Image
        with Image.open(io.BytesIO(data)) as opened:
            opened.verify()
            width, height, format_name = opened.width, opened.height, opened.format
        mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(format_name)
        if not mime or max(width, height) > MAX_IMAGE_SIDE or min(width, height) < 1:
            raise ValueError("Review image must be JPEG/PNG/WebP and at most 480 px")
        digest = hashlib.sha256(data).hexdigest()
        if image.get("digest") and image["digest"] != digest:
            raise ValueError("Review image hash mismatch")
        self._execute(conn, """INSERT INTO comic_review_images VALUES (?,?,?,?,?,?,?)
            ON CONFLICT (workspace_id, digest) DO NOTHING""", (workspace_id, digest, data, mime, width, height, _now()))
        return digest, "saved"

    def save_item(self, workspace_id, run_id, row_id, original, processed, summary, image=None) -> str:
        workspace_id, run_id, row_id = (_identifier(workspace_id, "workspace"), _identifier(run_id, "run"), _identifier(row_id, "row"))
        item_id = stable_item_id(workspace_id, run_id, row_id)
        original_json, processed_json = _json(original), _json(processed)
        summary_json = _json(summary)
        clean_processed = json.loads(processed_json)
        fields = self._summary_fields(summary, clean_processed)
        self.init_schema()
        with self._connection(write=True) as conn:
            self._require_run(conn, workspace_id, run_id)
            previous = self._one(conn, "SELECT original_json,automatic_json,image_digest FROM comic_review_items WHERE workspace_id=? AND item_id=?", (workspace_id, item_id))
            if previous:
                if previous["original_json"] != original_json or previous["automatic_json"] != processed_json:
                    raise ValueError("Automatic review snapshot is immutable; use a new run or a revision")
                if image is not None and not previous["image_digest"]:
                    try:
                        image_digest, image_status = self._save_image(conn, workspace_id, image)
                    except (ValueError, OSError, ImportError) as error:
                        image_digest, image_status = None, f"unavailable: {type(error).__name__}"
                    self._execute(conn, "UPDATE comic_review_items SET image_digest=?,image_status=? WHERE workspace_id=? AND item_id=?",
                                  (image_digest, image_status, workspace_id, item_id))
                return item_id
            # A failed thumbnail must never discard a completed textual review.
            try:
                image_digest, image_status = self._save_image(conn, workspace_id, image)
            except (ValueError, OSError, ImportError) as error:
                image_digest, image_status = None, f"unavailable: {type(error).__name__}"
            now = _now()
            self._execute(conn, "INSERT INTO comic_review_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                workspace_id, item_id, run_id, row_id, now, now, original_json, processed_json,
                processed_json, summary_json, *fields, image_digest, image_status))
        return item_id

    def finish_run(self, workspace_id, run_id, status="complete", cost_summary=None):
        workspace_id, run_id = _identifier(workspace_id, "workspace"), _identifier(run_id, "run")
        self.init_schema()
        with self._connection(write=True) as conn:
            self._require_run(conn, workspace_id, run_id)
            self._execute(conn, "UPDATE comic_review_runs SET status=?,finished_at=?,cost_summary_json=? WHERE workspace_id=? AND run_id=?",
                          (str(status), _now(), _json(cost_summary or {}), workspace_id, run_id))

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in list(result):
            if key.endswith("_json"):
                result[key[:-5]] = json.loads(result.pop(key))
        for key in ("data", "csv_bytes"):
            if key in result and result[key] is not None:
                result[key] = bytes(result[key])
        return result

    @staticmethod
    def _item_select():
        return "SELECT i.*,r.file_name,r.mode,r.processing_version,r.settings_json FROM comic_review_items i JOIN comic_review_runs r ON r.workspace_id=i.workspace_id AND r.run_id=i.run_id"

    def list_items(self, workspace_id, search="", status="", file_name="", date_from=None, date_to=None, offset=0, limit=50):
        workspace_id = _identifier(workspace_id, "workspace")
        clauses, params = ["i.workspace_id=?"], [workspace_id]
        if search:
            # User-entered wildcard characters are literal, not SQL search syntax.
            value = str(search).lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            clauses.append("(LOWER(i.title) LIKE ? ESCAPE '!' OR LOWER(i.source_title) LIKE ? ESCAPE '!')")
            params.extend([f"%{value}%", f"%{value}%"])
        if status:
            clauses.append("i.status=?")
            params.append(str(status))
        if file_name:
            clauses.append("r.file_name=?")
            params.append(str(file_name))
        if date_from:
            clauses.append("i.created_at>=?")
            params.append(_timestamp(date_from))
        if date_to:
            if isinstance(date_to, str) and len(date_to) == 10:
                date_to = date.fromisoformat(date_to)
            if isinstance(date_to, date) and not isinstance(date_to, datetime):
                clauses.append("i.created_at<?")
                params.append(_timestamp(date_to + timedelta(days=1)))
            else:
                clauses.append("i.created_at<=?")
                params.append(_timestamp(date_to))
        where = " WHERE " + " AND ".join(clauses)
        base = " FROM comic_review_items i JOIN comic_review_runs r ON r.workspace_id=i.workspace_id AND r.run_id=i.run_id"
        self.init_schema()
        with self._connection() as conn:
            total = self._execute(conn, "SELECT COUNT(*)" + base + where, params).fetchone()[0]
            rows = self._rows(self._execute(conn, self._item_select() + where + " ORDER BY i.created_at DESC,i.item_id DESC LIMIT ? OFFSET ?",
                                           [*params, max(1, min(200, int(limit))), max(0, int(offset))]))
        return [self._decode(row) for row in rows], total

    def get_item(self, workspace_id, item_id):
        self.init_schema()
        with self._connection() as conn:
            return self._decode(self._one(conn, self._item_select() + " WHERE i.workspace_id=? AND i.item_id=?",
                                         (_identifier(workspace_id, "workspace"), _identifier(item_id, "item"))))

    def list_run_items(self, workspace_id, run_id):
        self.init_schema()
        with self._connection() as conn:
            rows = self._rows(self._execute(conn, self._item_select() + " WHERE i.workspace_id=? AND i.run_id=? ORDER BY i.created_at,i.row_id",
                                           (_identifier(workspace_id, "workspace"), _identifier(run_id, "run"))))
        return [self._decode(row) for row in rows]

    def _run_counts(self, conn, row):
        result = self._decode(row)
        if result is not None:
            counts = self._execute(conn, "SELECT status,COUNT(*) FROM comic_review_items WHERE workspace_id=? AND run_id=? GROUP BY status",
                                   (result["workspace_id"], result["run_id"])).fetchall()
            result["status_counts"] = dict(counts)
            result["item_count"] = sum(count for _, count in counts)
        return result

    def get_run(self, workspace_id, run_id):
        self.init_schema()
        with self._connection() as conn:
            return self._run_counts(conn, self._one(conn, "SELECT * FROM comic_review_runs WHERE workspace_id=? AND run_id=?",
                                                   (_identifier(workspace_id, "workspace"), _identifier(run_id, "run"))))

    def list_runs(self, workspace_id, limit=200, offset=0):
        self.init_schema()
        with self._connection() as conn:
            rows = self._rows(self._execute(conn, "SELECT * FROM comic_review_runs WHERE workspace_id=? ORDER BY created_at DESC,run_id DESC LIMIT ? OFFSET ?",
                                           (_identifier(workspace_id, "workspace"), max(1, min(1000, int(limit))), max(0, int(offset)))))
            return [self._run_counts(conn, row) for row in rows]

    def list_file_names(self, workspace_id):
        self.init_schema()
        with self._connection() as conn:
            return [row[0] for row in self._execute(conn, "SELECT DISTINCT file_name FROM comic_review_runs WHERE workspace_id=? ORDER BY file_name", (_identifier(workspace_id, "workspace"),)).fetchall()]

    def save_revision(self, workspace_id, item_id, processed, reason="manual correction", summary=None):
        workspace_id, item_id = _identifier(workspace_id, "workspace"), _identifier(item_id, "item")
        self.init_schema()
        with self._connection(write=True) as conn:
            row = self._one(conn, "SELECT * FROM comic_review_items WHERE workspace_id=? AND item_id=?" + (" FOR UPDATE" if self.is_postgres else ""), (workspace_id, item_id))
            if not row:
                raise ValueError("Review item was not found in this workspace")
            processed_json = _json(processed)
            current_summary = json.loads(row["summary_json"])
            if summary is not None:
                current_summary.update(sanitize_history_value(summary))
            current_summary["title"] = sanitize_history_value(processed).get("Title", current_summary.get("title", ""))
            summary_json = _json(current_summary)
            reason = _safe_text(str(reason))
            if row["processed_json"] == processed_json and row["summary_json"] == summary_json:
                previous = self._one(conn, "SELECT revision_id,reason FROM comic_review_revisions WHERE workspace_id=? AND item_id=? ORDER BY created_at DESC,revision_id DESC LIMIT 1", (workspace_id, item_id))
                if previous and previous["reason"] == reason:
                    return previous["revision_id"]
            revision_id = uuid.uuid4().hex
            now = _now()
            cursor = self._execute(conn, """INSERT INTO comic_review_revisions VALUES (?,?,?,?,?,?,?)
                ON CONFLICT (workspace_id, revision_id) DO NOTHING""", (workspace_id, revision_id, item_id, now, reason, processed_json, summary_json))
            if cursor.rowcount:
                self._execute(conn, """UPDATE comic_review_items SET processed_json=?,summary_json=?,updated_at=?,title=?,source_title=?,status=?,change_summary=?,shipping_usd=?
                    WHERE workspace_id=? AND item_id=?""", (processed_json, summary_json, now, *self._summary_fields(current_summary, json.loads(processed_json)), workspace_id, item_id))
        return revision_id

    def get_revisions(self, workspace_id, item_id):
        self.init_schema()
        with self._connection() as conn:
            rows = self._rows(self._execute(conn, "SELECT * FROM comic_review_revisions WHERE workspace_id=? AND item_id=? ORDER BY created_at,revision_id",
                                           (_identifier(workspace_id, "workspace"), _identifier(item_id, "item"))))
        return [self._decode(row) for row in rows]

    def save_export(self, workspace_id, run_id, csv_bytes, filename, settings, row_ids, source_items=None):
        workspace_id, run_id = _identifier(workspace_id, "workspace"), _identifier(run_id, "run")
        data = bytes(csv_bytes)
        digest = hashlib.sha256(data).hexdigest()
        settings_json, row_ids_json = _json(settings), _json([str(row_id) for row_id in row_ids])
        source_items = [_identifier(item, "source item") for item in (source_items or [])]
        source_items_json = _json(source_items)
        filename = Path(str(filename)).name.replace("\\", "/").split("/")[-1]
        export_id = hashlib.sha256(_json([workspace_id, run_id, digest, filename, settings_json, row_ids_json, source_items_json]).encode()).hexdigest()
        self.init_schema()
        with self._connection(write=True) as conn:
            self._require_run(conn, workspace_id, run_id)
            if source_items:
                if len(source_items) != len(json.loads(row_ids_json)) or len(set(source_items)) != len(source_items):
                    raise ValueError("Export source items must match the exported rows exactly")
                for item_id, row_id in zip(source_items, json.loads(row_ids_json)):
                    source = self._one(conn, "SELECT row_id FROM comic_review_items WHERE workspace_id=? AND item_id=?", (workspace_id, item_id))
                    if not source or source["row_id"] != row_id:
                        raise ValueError("Export source item was not found in this workspace or row does not match")
            else:
                actual_rows = {row[0] for row in self._execute(conn, "SELECT row_id FROM comic_review_items WHERE workspace_id=? AND run_id=?", (workspace_id, run_id)).fetchall()}
                if not set(json.loads(row_ids_json)).issubset(actual_rows):
                    raise ValueError("Export includes rows outside the selected review run")
            self._execute(conn, """INSERT INTO comic_review_exports
                (workspace_id,export_id,run_id,filename,created_at,digest,csv_bytes,settings_json,row_ids_json,source_items_json)
                VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT (workspace_id, export_id) DO NOTHING""",
                          (workspace_id, export_id, run_id, filename, _now(), digest, data, settings_json, row_ids_json, source_items_json))
        return export_id

    def list_exports(self, workspace_id, run_id):
        self.init_schema()
        with self._connection() as conn:
            rows = self._rows(self._execute(conn, "SELECT workspace_id,export_id,run_id,filename,created_at,digest,settings_json,row_ids_json,source_items_json FROM comic_review_exports WHERE workspace_id=? AND run_id=? ORDER BY created_at DESC,export_id DESC",
                                           (_identifier(workspace_id, "workspace"), _identifier(run_id, "run"))))
        return [self._decode(row) for row in rows]

    def get_export(self, workspace_id, export_id):
        self.init_schema()
        with self._connection() as conn:
            return self._decode(self._one(conn, "SELECT * FROM comic_review_exports WHERE workspace_id=? AND export_id=?",
                                         (_identifier(workspace_id, "workspace"), _identifier(export_id, "export"))))

    def get_image(self, workspace_id, digest):
        self.init_schema()
        with self._connection() as conn:
            return self._decode(self._one(conn, "SELECT * FROM comic_review_images WHERE workspace_id=? AND digest=?",
                                         (_identifier(workspace_id, "workspace"), _identifier(digest, "image"))))

    def _deletion_scope(self, conn, workspace_id, run_ids):
        placeholders = ",".join("?" for _ in run_ids)
        params = [workspace_id, *run_ids]
        run_count = self._execute(conn, f"SELECT COUNT(*) FROM comic_review_runs WHERE workspace_id=? AND run_id IN ({placeholders})", params).fetchone()[0]
        deleted_items = {row[0] for row in self._execute(conn, f"SELECT item_id FROM comic_review_items WHERE workspace_id=? AND run_id IN ({placeholders})", params).fetchall()}
        image_count = self._execute(conn, f"""SELECT COUNT(*) FROM comic_review_images WHERE workspace_id=? AND NOT EXISTS (
            SELECT 1 FROM comic_review_items WHERE comic_review_items.workspace_id=comic_review_images.workspace_id
            AND comic_review_items.image_digest=comic_review_images.digest AND comic_review_items.run_id NOT IN ({placeholders}))""", params).fetchone()[0]
        export_details = []
        rows = self._execute(conn, "SELECT export_id,filename,run_id,source_items_json FROM comic_review_exports WHERE workspace_id=? ORDER BY created_at,export_id", (workspace_id,)).fetchall()
        for export_id, filename, attached_run, source_json in rows:
            if attached_run in run_ids or deleted_items.intersection(json.loads(source_json)):
                export_details.append({"export_id": export_id, "filename": filename, "run_id": attached_run, "cross_run": attached_run not in run_ids})
        return {"runs": run_count, "items": len(deleted_items), "images": image_count,
                "exports": len(export_details), "export_files": [item["filename"] for item in export_details],
                "export_details": export_details, "cross_run_exports": [item for item in export_details if item["cross_run"]]}

    def preview_delete_runs(self, workspace_id, run_ids):
        """Read the exact current deletion scope, including dependent full CSVs."""
        workspace_id = _identifier(workspace_id, "workspace")
        run_ids = list(dict.fromkeys(_identifier(value, "run") for value in run_ids))
        if not run_ids:
            return {"runs": 0, "items": 0, "images": 0, "exports": 0,
                    "export_files": [], "export_details": [], "cross_run_exports": []}
        self.init_schema()
        with self._connection() as conn:
            return self._deletion_scope(conn, workspace_id, run_ids)

    def delete_runs(self, workspace_id, run_ids):
        workspace_id = _identifier(workspace_id, "workspace")
        run_ids = list(dict.fromkeys(_identifier(value, "run") for value in run_ids))
        if not run_ids:
            return {"runs": 0, "items": 0, "images": 0}
        self.init_schema()
        placeholders = ",".join("?" for _ in run_ids)
        params = [workspace_id, *run_ids]
        with self._connection(write=True) as conn:
            if self.is_postgres:
                self._execute(conn, f"SELECT run_id FROM comic_review_runs WHERE workspace_id=? AND run_id IN ({placeholders}) ORDER BY run_id FOR UPDATE", params).fetchall()
            scope = self._deletion_scope(conn, workspace_id, run_ids)
            item_count = scope["items"]
            # Full exports can span several trial runs; do not retain a CSV copy
            # of deleted results through an export attached to a different run.
            for export in scope["export_details"]:
                self._execute(conn, "DELETE FROM comic_review_exports WHERE workspace_id=? AND export_id=?", (workspace_id, export["export_id"]))
            run_count = self._execute(conn, f"DELETE FROM comic_review_runs WHERE workspace_id=? AND run_id IN ({placeholders})", params).rowcount
            image_count = self._execute(conn, """DELETE FROM comic_review_images WHERE workspace_id=? AND NOT EXISTS (
                SELECT 1 FROM comic_review_items WHERE comic_review_items.workspace_id=comic_review_images.workspace_id
                AND comic_review_items.image_digest=comic_review_images.digest)""", (workspace_id,)).rowcount
        return {"runs": run_count, "items": item_count, "images": image_count}

    def delete_run(self, workspace_id, run_id):
        return self.delete_runs(workspace_id, [run_id])
