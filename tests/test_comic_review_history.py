"""The same persistence contract runs on SQLite and an optional PostgreSQL DB.

Set COMIC_REVIEW_TEST_DATABASE_URL to a dedicated/test-enabled PostgreSQL URL.
Only randomly-namespaced test workspace rows are created and removed.
"""
from dataclasses import asdict
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

from PIL import Image

from comic_review_history import ReviewHistoryStore, ReviewRun, sanitize_history_value, stable_item_id


def thumbnail(width=32, height=48):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), "purple").save(stream, format="JPEG")
    return {"data": stream.getvalue(), "mime": "image/jpeg"}


class HistoryContract:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database_url = getattr(self, "postgres_url", None) or "sqlite:///" + str(Path(self.temp.name) / "history.sqlite3")
        self.store = ReviewHistoryStore(self.database_url)
        self.store.init_schema()
        self.workspace = "review-test-" + uuid.uuid4().hex
        self.other = self.workspace + "-other"

    def tearDown(self):
        for workspace in (self.workspace, self.other):
            runs = self.store.list_runs(workspace, limit=1000)
            self.store.delete_runs(workspace, [run["run_id"] for run in runs])
        self.temp.cleanup()

    def run_record(self, run_id="run-1", workspace=None, file_name="books.csv", **kwargs):
        run = ReviewRun(workspace_id=workspace or self.workspace, file_name=file_name,
                        mode="trial", run_id=run_id, settings={"buffer_pct": 45.0, "exchange_rate": 162.0},
                        processing_version="test-v1", target_rows=[0, 1, 2, 3, 4])
        values = asdict(run)
        values.update(kwargs)
        return self.store.save_run(values)

    def item(self, run_id="run-1", row_id=0, workspace=None, title="Cells at Work", status="ready", image=None, **kwargs):
        return self.store.save_item(workspace or self.workspace, run_id, row_id,
                                   {"Title": "Original title", "Description": "Original <b>HTML</b>", "row": row_id},
                                   {"Title": title, "C:Series": title, "Price": 52.3},
                                   {"title": title, "source_title": "はたらく細菌", "status": status,
                                    "change_summary": "Title corrected", "shipping_usd": 23.4, **kwargs}, image=image)

    def test_schema_init_and_round_trip_persist_after_new_store(self):
        self.run_record()
        item_id = self.item()
        self.store.finish_run(self.workspace, "run-1", "complete", {"usd": 0.03, "search_calls": 2})
        other_store = ReviewHistoryStore(self.database_url)
        other_store.init_schema()
        record = other_store.get_item(self.workspace, item_id)
        self.assertEqual(record["original"]["Description"], "Original <b>HTML</b>")
        self.assertEqual(record["processed"]["Title"], "Cells at Work")
        self.assertEqual(record["automatic"], record["processed"])
        self.assertEqual(record["settings"]["buffer_pct"], 45.0)
        run = other_store.get_run(self.workspace, "run-1")
        self.assertEqual(run["cost_summary"]["search_calls"], 2)
        self.assertEqual(run["status_counts"], {"ready": 1})
        self.assertEqual(run["item_count"], 1)
        self.assertEqual(run["status"], "complete")

    def test_partial_run_is_visible_before_finish(self):
        self.run_record()
        self.item(row_id=0)
        self.item(row_id=1, status="excluded")
        run = self.store.get_run(self.workspace, "run-1")
        self.assertEqual(run["status"], "running")
        self.assertIsNone(run["finished_at"])
        self.assertEqual(run["item_count"], 2)
        self.assertEqual(len(self.store.list_run_items(self.workspace, "run-1")), 2)

    def test_idempotent_retry_and_reprocessing_are_distinct(self):
        self.run_record()
        first = self.item()
        self.assertEqual(first, stable_item_id(self.workspace, "run-1", 0))
        self.run_record()
        self.assertEqual(first, self.item())
        self.run_record("run-2")
        second = self.item("run-2")
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.list_items(self.workspace)[1], 2)
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.item(title="Different automatic result")
        self.assertEqual(self.store.get_item(self.workspace, first)["processed"]["Title"], "Cells at Work")

    def test_concurrent_save_retries_are_idempotent(self):
        self.run_record()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: self.item(image=thumbnail()), range(8)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.store.list_items(self.workspace)[1], 1)

    def test_manual_revisions_preserve_automatic_and_support_reverts(self):
        self.run_record()
        item_id = self.item()
        processed = self.store.get_item(self.workspace, item_id)["processed"]
        changed = {**processed, "Title": "Manual title", "C:Series": "Manual title"}
        rev1 = self.store.save_revision(self.workspace, item_id, changed, "manual", {"status": "attention"})
        self.assertEqual(rev1, self.store.save_revision(self.workspace, item_id, changed, "manual", {"status": "attention"}))
        self.store.save_revision(self.workspace, item_id, processed, "revert", {"status": "ready"})
        self.store.save_revision(self.workspace, item_id, changed, "manual", {"status": "attention"})
        record = self.store.get_item(self.workspace, item_id)
        self.assertEqual(record["automatic"]["Title"], "Cells at Work")
        self.assertEqual(record["original"]["Title"], "Original title")
        self.assertEqual(record["processed"]["Title"], "Manual title")
        self.assertEqual(record["title"], "Manual title")
        self.assertEqual(record["status"], "attention")
        self.assertEqual(len(self.store.get_revisions(self.workspace, item_id)), 3)
        self.assertEqual(self.store.list_items(self.workspace, search="Manual")[1], 1)

    def test_workspace_scope_every_read_write_delete(self):
        self.run_record()
        item_id = self.item(image=thumbnail())
        digest = self.store.get_item(self.workspace, item_id)["image_digest"]
        export_id = self.store.save_export(self.workspace, "run-1", b"Title\nCells\n", "output.csv", {}, [0])
        self.assertIsNone(self.store.get_item(self.other, item_id))
        self.assertIsNone(self.store.get_run(self.other, "run-1"))
        self.assertEqual(self.store.list_items(self.other), ([], 0))
        self.assertEqual(self.store.list_run_items(self.other, "run-1"), [])
        self.assertEqual(self.store.list_runs(self.other), [])
        self.assertEqual(self.store.list_file_names(self.other), [])
        self.assertEqual(self.store.get_revisions(self.other, item_id), [])
        self.assertIsNone(self.store.get_image(self.other, digest))
        self.assertIsNone(self.store.get_export(self.other, export_id))
        self.assertEqual(self.store.list_exports(self.other, "run-1"), [])
        with self.assertRaises(ValueError):
            self.store.save_revision(self.other, item_id, {"Title": "unauthorized"})
        with self.assertRaises(ValueError):
            self.store.finish_run(self.other, "run-1")
        with self.assertRaises(ValueError):
            self.item(workspace=self.other)
        with self.assertRaises(ValueError):
            self.store.save_export(self.other, "run-1", b"x", "x.csv", {}, [])
        self.assertEqual(self.store.delete_run(self.other, "run-1"), {"runs": 0, "items": 0, "images": 0})
        self.assertIsNotNone(self.store.get_item(self.workspace, item_id))

    def test_same_identifiers_different_workspace_do_not_collide(self):
        self.run_record()
        self.run_record(workspace=self.other)
        first = self.item(title="Mine")
        second = self.item(workspace=self.other, title="Other workspace")
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.list_items(self.workspace)[0][0]["title"], "Mine")
        self.store.delete_run(self.workspace, "run-1")
        self.assertEqual(self.store.get_item(self.other, second)["title"], "Other workspace")

    def test_page_search_status_file_and_stable_selection(self):
        self.run_record(file_name="first.csv")
        self.run_record("run-2", file_name="second.csv")
        ids = []
        for row_id in range(53):
            ids.append(self.item(row_id=row_id, title=f"Manga {row_id:02d}", status="attention" if row_id % 2 else "ready"))
        wanted = self.item("run-2", row_id=0, title="Different CSV same row")
        page1, total = self.store.list_items(self.workspace)
        page2, _ = self.store.list_items(self.workspace, offset=50)
        self.assertEqual(total, 54)
        self.assertEqual(len(page1), 50)
        self.assertEqual(len(page2), 4)
        self.assertFalse({r["item_id"] for r in page1} & {r["item_id"] for r in page2})
        self.assertEqual(self.store.list_items(self.workspace, status="attention")[1], 26)
        rows, _ = self.store.list_items(self.workspace, file_name="second.csv")
        self.assertEqual(rows[0]["item_id"], wanted)
        self.assertEqual(self.store.get_item(self.workspace, rows[0]["item_id"])["run_id"], "run-2")
        self.assertEqual(self.store.list_items(self.workspace, search="manga 12")[1], 1)
        self.assertEqual(self.store.list_items(self.workspace, search="はたらく細菌")[1], 54)
        self.assertEqual(self.store.list_file_names(self.workspace), ["first.csv", "second.csv"])

    def test_search_wildcards_are_literal_and_parameterized(self):
        self.run_record()
        self.item(title="100% Complete_Set")
        self.item(row_id=1, title="100 Something")
        self.assertEqual(self.store.list_items(self.workspace, search="100%")[1], 1)
        self.assertEqual(self.store.list_items(self.workspace, search="_")[1], 1)
        self.assertEqual(self.store.list_items(self.workspace, search="' OR 1=1 --")[1], 0)

    def test_date_range_includes_selected_calendar_day(self):
        self.run_record()
        with patch("comic_review_history._now", return_value="2026-09-07T01:00:00.000000+00:00"):
            self.item(row_id=0)
        with patch("comic_review_history._now", return_value="2026-09-08T01:00:00.000000+00:00"):
            self.item(row_id=1)
        self.assertEqual(self.store.list_items(self.workspace, date_from=date(2026, 9, 7), date_to=date(2026, 9, 7))[1], 1)
        self.assertEqual(self.store.list_items(self.workspace, date_to="2026-09-07")[1], 1)
        self.assertEqual(self.store.list_items(self.workspace, date_from=datetime(2026, 9, 8, tzinfo=timezone.utc))[1], 1)

    def test_export_bytes_and_settings_are_frozen_and_idempotent(self):
        self.run_record()
        self.item()
        data = b"\xef\xbb\xbfTitle,StartPrice\r\nCells,82.10\r\n"
        settings = {"buffer_pct": 45.0, "exchange_rate": 162.0, "fuel_pct": 30.0}
        first = self.store.save_export(self.workspace, "run-1", data, "trial.csv", settings, [0])
        self.assertEqual(first, self.store.save_export(self.workspace, "run-1", data, "trial.csv", settings, [0]))
        settings["buffer_pct"] = 99
        stored = self.store.get_export(self.workspace, first)
        self.assertEqual(stored["csv_bytes"], data)
        self.assertEqual(stored["settings"]["buffer_pct"], 45.0)
        self.assertEqual(stored["row_ids"], ["0"])
        self.assertEqual(stored["digest"], hashlib.sha256(data).hexdigest())
        self.assertNotIn("csv_bytes", self.store.list_exports(self.workspace, "run-1")[0])
        self.assertEqual(len(self.store.list_exports(self.workspace, "run-1")), 1)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.store.save_export(self.workspace, "run-1", data, "bad.csv", {}, [999])

    def test_image_attachment_after_text_preserves_manual_projection(self):
        self.run_record()
        item_id = self.item()
        self.assertIsNone(self.store.get_item(self.workspace, item_id)["image_digest"])
        self.store.save_revision(self.workspace, item_id, {"Title": "Manual"})
        self.assertEqual(self.item(image=thumbnail()), item_id)
        item = self.store.get_item(self.workspace, item_id)
        self.assertEqual(item["processed"]["Title"], "Manual")
        self.assertEqual(item["automatic"]["Title"], "Cells at Work")
        image = self.store.get_image(self.workspace, item["image_digest"])
        self.assertEqual(image["data"], thumbnail()["data"])
        self.assertEqual((image["width"], image["height"]), (32, 48))

    def test_cumulative_trial_export_tracks_scoped_source_items(self):
        self.run_record()
        self.run_record("run-2")
        first, second = self.item(row_id=0), self.item("run-2", row_id=1)
        export_id = self.store.save_export(self.workspace, "run-2", b"Title\nA\nB", "full.csv", {}, [0, 1], source_items=[first, second])
        self.assertEqual(self.store.get_export(self.workspace, export_id)["source_items"], [first, second])
        with self.assertRaises(ValueError):
            self.store.save_export(self.workspace, "run-2", b"x", "x.csv", {}, [0, 1], source_items=[second, first])
        self.run_record(workspace=self.other)
        other_item = self.item(workspace=self.other)
        with self.assertRaises(ValueError):
            self.store.save_export(self.workspace, "run-2", b"x", "x.csv", {}, [0], source_items=[other_item])
        self.store.delete_run(self.workspace, "run-1")
        self.assertIsNone(self.store.get_export(self.workspace, export_id))
        self.assertIsNotNone(self.store.get_item(self.workspace, second))

    def test_deletion_preview_includes_cross_run_exports_and_matches_deletion(self):
        self.run_record()
        self.run_record("run-2")
        self.run_record("run-3")
        first = self.item(row_id=0, image=thumbnail())
        second = self.item("run-2", row_id=1, image=thumbnail())
        third = self.item("run-3", row_id=2, image=thumbnail(40, 50))
        trial_export = self.store.save_export(self.workspace, "run-1", b"Title\nA", "trial.csv", {}, [0])
        full_export = self.store.save_export(self.workspace, "run-2", b"Title\nA\nB", "full.csv", {}, [0, 1], source_items=[first, second])
        retained_export = self.store.save_export(self.workspace, "run-2", b"Title\nB", "other.csv", {}, [1])
        scope = self.store.preview_delete_runs(self.workspace, ["run-1", "run-3"])
        self.assertEqual({key: scope[key] for key in ("runs", "items", "images", "exports")},
                         {"runs": 2, "items": 2, "images": 1, "exports": 2})
        self.assertEqual(set(scope["export_files"]), {"trial.csv", "full.csv"})
        self.assertEqual([record["export_id"] for record in scope["cross_run_exports"]], [full_export])
        self.assertEqual(scope["cross_run_exports"][0]["run_id"], "run-2")
        self.assertIsNotNone(self.store.get_item(self.workspace, first))  # preview is read-only
        counts = self.store.delete_runs(self.workspace, ["run-1", "run-3"])
        self.assertEqual(counts, {key: scope[key] for key in ("runs", "items", "images")})
        self.assertIsNone(self.store.get_export(self.workspace, trial_export))
        self.assertIsNone(self.store.get_export(self.workspace, full_export))
        self.assertIsNotNone(self.store.get_export(self.workspace, retained_export))
        self.assertIsNotNone(self.store.get_item(self.workspace, second))
        self.assertIsNone(self.store.get_item(self.workspace, third))
        self.assertEqual(self.store.preview_delete_runs(self.workspace, ["run-1"])["items"], 0)
        self.assertEqual(self.store.preview_delete_runs(self.other, ["run-2"])["exports"], 0)
        self.assertEqual(self.store.preview_delete_runs(self.workspace, [])["runs"], 0)

    def test_invalid_or_oversized_images_do_not_discard_text(self):
        self.run_record()
        images = [{"data": b"not an image"}, {"data": b"x" * (256 * 1024 + 1)},
                  thumbnail(481, 20), {**thumbnail(), "digest": "wrong"}, {"status": "fetch failed"}]
        for row_id, image in enumerate(images):
            item_id = self.item(row_id=row_id, image=image)
            record = self.store.get_item(self.workspace, item_id)
            self.assertEqual(record["processed"]["Title"], "Cells at Work")
            self.assertIsNone(record["image_digest"])
            self.assertNotEqual(record["image_status"], "saved")

    def test_delete_cascades_only_selected_runs_and_orphan_images(self):
        self.run_record()
        self.run_record("run-2")
        first, second = self.item(image=thumbnail()), self.item("run-2", image=thumbnail())
        digest = self.store.get_item(self.workspace, first)["image_digest"]
        self.store.save_revision(self.workspace, first, {"Title": "Edited"})
        export_id = self.store.save_export(self.workspace, "run-1", b"Title\nX", "x.csv", {}, [0])
        counts = self.store.delete_run(self.workspace, "run-1")
        self.assertEqual(counts, {"runs": 1, "items": 1, "images": 0})
        self.assertIsNone(self.store.get_item(self.workspace, first))
        self.assertEqual(self.store.get_revisions(self.workspace, first), [])
        self.assertIsNone(self.store.get_export(self.workspace, export_id))
        self.assertIsNotNone(self.store.get_image(self.workspace, digest))
        self.assertIsNotNone(self.store.get_item(self.workspace, second))
        self.assertEqual(self.store.delete_run(self.workspace, "run-2"), {"runs": 1, "items": 1, "images": 1})
        self.assertIsNone(self.store.get_image(self.workspace, digest))
        self.assertEqual(self.store.delete_runs(self.workspace, []), {"runs": 0, "items": 0, "images": 0})

    def test_secret_fields_are_removed_from_all_json_snapshots(self):
        secret_fields = {"api_key": "not-for-storage", "nested": [{"password": "private-password", "Authorization": "Bearer xyz", "safe": "okay"}],
                         "connection_url": "postgresql://someone:password@host/db", "token_usage": {"input_tokens": 120}}
        self.run_record(settings={**secret_fields, "buffer_pct": 45})
        item_id = self.store.save_item(self.workspace, "run-1", 0, secret_fields, {**secret_fields, "Title": "safe"}, secret_fields)
        self.store.save_revision(self.workspace, item_id, {**secret_fields, "Title": "edited"}, "manual")
        self.store.finish_run(self.workspace, "run-1", cost_summary=secret_fields)
        export_id = self.store.save_export(self.workspace, "run-1", b"safe csv", "safe.csv", secret_fields, [0])
        values = [self.store.get_item(self.workspace, item_id), self.store.get_run(self.workspace, "run-1"),
                  self.store.get_revisions(self.workspace, item_id), self.store.get_export(self.workspace, export_id)["settings"]]
        serialized = json.dumps(values)
        for secret in ("not-for-storage", "private-password", "postgresql://", "Bearer xyz"):
            self.assertNotIn(secret, serialized)
        self.assertIn("input_tokens", serialized)
        self.assertIn("okay", serialized)

    def test_missing_workspace_rejected(self):
        with self.assertRaises(ValueError):
            self.store.list_items("")
        with self.assertRaises(ValueError):
            self.store.save_run({"file_name": "x"})


class SQLiteHistoryTests(HistoryContract, unittest.TestCase):
    def test_additive_export_migration_preserves_existing_export(self):
        self.run_record()
        self.item()
        export_id = self.store.save_export(self.workspace, "run-1", b"Title\nX", "x.csv", {"buffer_pct": 45}, [0])
        with closing(sqlite3.connect(str(self.store.sqlite_path))) as conn:
            conn.execute("ALTER TABLE comic_review_exports DROP COLUMN source_items_json")
            conn.commit()
        migrated = ReviewHistoryStore(self.database_url)
        migrated.init_schema()
        record = migrated.get_export(self.workspace, export_id)
        self.assertEqual(record["csv_bytes"], b"Title\nX")
        self.assertEqual(record["source_items"], [])
        self.assertEqual(record["settings"]["buffer_pct"], 45)

    def test_existing_auth_table_survives_history_schema_and_deletion(self):
        with closing(sqlite3.connect(str(self.store.sqlite_path))) as conn:
            conn.execute("CREATE TABLE comic_ficp_users (id INTEGER PRIMARY KEY,username TEXT)")
            conn.execute("INSERT INTO comic_ficp_users VALUES (1,'existing')")
            conn.commit()
        self.run_record()
        self.item()
        self.store.delete_run(self.workspace, "run-1")
        with closing(sqlite3.connect(str(self.store.sqlite_path))) as conn:
            self.assertEqual(conn.execute("SELECT username FROM comic_ficp_users").fetchone()[0], "existing")


@unittest.skipUnless(os.environ.get("COMIC_REVIEW_TEST_DATABASE_URL"), "PostgreSQL test URL not configured")
class PostgreSQLHistoryTests(HistoryContract, unittest.TestCase):
    postgres_url = os.environ.get("COMIC_REVIEW_TEST_DATABASE_URL")


class SanitizationTests(unittest.TestCase):
    def test_credentials_in_urls_and_known_key_formats_are_redacted(self):
        value = {
            "link": "https://user:password@example.com/image?api_key=private&x=1",
            "normal_url": "https://example.com/image?a=a%20b&x=1",
            "signed": "https://example.com/image?X-Amz-Signature=signature-secret&X-Amz-Credential=credential-secret",
            "fragment": "https://example.com/callback#access_token=fragment-secret&expires_in=3600",
            "description": "postgresql://user:secret@host/db Bearer abcdef12345 " + "AIza" + "a" * 35,
            "nested": {"openai_api_key": "private", "cached_tokens": 5},
            "nan": float("nan"),
        }
        safe = sanitize_history_value(value)
        self.assertNotIn("private", json.dumps(safe))
        self.assertNotIn("user:password", safe["link"])
        self.assertNotIn("user:secret", safe["description"])
        self.assertNotIn("abcdef12345", safe["description"])
        self.assertNotIn("signature-secret", safe["signed"])
        self.assertNotIn("credential-secret", safe["signed"])
        self.assertNotIn("fragment-secret", safe["fragment"])
        self.assertEqual(safe["normal_url"], value["normal_url"])
        self.assertEqual(safe["nested"], {"cached_tokens": 5})
        self.assertIsNone(safe["nan"])


if __name__ == "__main__":
    unittest.main()
