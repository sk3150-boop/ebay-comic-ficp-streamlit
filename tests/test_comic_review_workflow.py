"""History integration and real main-screen smoke tests without paid/network I/O."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

import comic_ficp_streamlit_app as app
import comic_review_workflow as workflow
from comic_review_history import ReviewHistoryStore


IMAGE = "https://static.mercdn.net/item/detail/orig/photos/m22222222222_1.jpg"


def _config():
    return app.ProcessingConfig(
        title_col="Title", image_col="PicURL", url_col="商品URL", price_col="StartPrice",
        description_col="Description", enable_scrape=False, enable_browser_scrape=False,
        enable_reference_lookup=False, enable_ai_enrichment=False, enable_title_resolution=False,
        request_delay_seconds=0,
    )


def _reviewed(title="Reviewed title", **extra):
    return {"Title": title, "PicURL": IMAGE, "Main Image URL": IMAGE, "StartPrice": "20.00",
            "Description": "Manga set.", "Detected Book Count": "5", "Billable Weight kg": "1.5",
            "FICP Shipping USD": "10.00", "FICP Shipping JPY": "1500", "Listing Eligibility": "OK",
            "Image URL Validation Status": "ok: verified item", "Processing Result": "成功", "Needs Review": "No",
            "Scrape Status": "ok", **extra}


class ReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ReviewHistoryStore(str(Path(self.temp.name) / "history.sqlite"))
        self.st = SimpleNamespace(session_state={})
        self.config = _config()
        self.rollup = app.FreeShippingRollupOptions(markup_percent=45)
        self.image_patch = patch.object(workflow, "archive_review_image", return_value={"status": "test image unavailable", "data": b"", "mime": ""})
        self.image_mock = self.image_patch.start()

    def tearDown(self):
        self.image_patch.stop()
        self.temp.cleanup()

    def start(self, indices=(0,), store="default"):
        return workflow.start_run(self.st, self.store if store == "default" else store, "1", "file-key", "sample.csv", list(indices), self.config, self.rollup, app, mode="trial")

    def persist(self, run, index=0, store="default", title="Reviewed title"):
        workflow.persist_row(self.st, self.store if store == "default" else store, run, "file-key", index,
                             pd.Series(_reviewed(title)), pd.Series({"Title": "Before"}), self.config, app)

    def test_settings_never_include_credentials_or_override_registry(self):
        self.config.ai_api_key = "test-only-secret"
        self.config.title_overrides = {"private native": "private override"}
        saved = workflow.safe_settings(self.config, self.rollup)
        self.assertNotIn("ai_api_key", saved["processing"])
        self.assertNotIn("title_overrides", saved["processing"])
        self.assertEqual(45, saved["rollup"]["markup_percent"])

    def test_row_callback_is_invoked_once_for_success_and_early_exclusions(self):
        frame = pd.DataFrame([
            {"Title": "ONE PIECE Jump Comics Volumes 1-5 Set", "PicURL": IMAGE, "Description": "Manga set"},
            {"Title": "週刊少年ジャンプ 2024年12号", "PicURL": IMAGE, "Description": "Magazine"},
            {"Title": "ONE PIECE Volumes 1-60 Set", "PicURL": IMAGE, "Description": "Manga set"},
        ])
        callbacks = []
        with patch.object(app.requests.Session, "request", side_effect=AssertionError("Unexpected network")):
            result = app.process_dataframe(frame, self.config, row_callback=lambda index, row: callbacks.append((index, row.copy())))
        self.assertEqual([0, 1, 2], [index for index, _ in callbacks])
        self.assertEqual("Excluded", result.loc[1, "Listing Eligibility"])
        self.assertEqual("Excluded", result.loc[2, "Listing Eligibility"])
        for index, row in callbacks:
            pd.testing.assert_series_equal(result.loc[index].fillna(""), row.fillna(""), check_names=False)

    def test_store_outage_retries_saved_results_without_reprocessing_or_image_refetch(self):
        run = self.start(store=None)
        self.persist(run, store=None)
        workflow.finish_run(self.st, None, run, {"total_cost_jpy": 1.23})
        self.assertGreaterEqual(len(self.st.session_state[workflow.PENDING]), 3)
        calls = self.image_mock.call_count
        workflow.retry_pending(self.st, self.store)
        self.assertEqual({}, self.st.session_state[workflow.PENDING])
        self.assertEqual(calls, self.image_mock.call_count)
        self.assertEqual("Reviewed title", self.store.list_run_items("1", run["run_id"])[0]["processed"]["Title"])
        self.assertEqual(1.23, self.store.get_run("1", run["run_id"])["cost_summary"]["total_cost_jpy"])

    def test_manual_edit_during_database_outage_is_queued_and_keeps_automatic_snapshot(self):
        run = self.start()
        self.persist(run)
        before = pd.DataFrame([_reviewed()])
        after = before.copy()
        after.loc[0, "Title"] = "Manual title"
        workflow.record_manual_changes(self.st, None, "1", "file-key", before, after, self.config, app)
        self.assertTrue(any(key.startswith("revision:") for key in self.st.session_state[workflow.PENDING]))
        workflow.retry_pending(self.st, self.store)
        item = self.store.list_run_items("1", run["run_id"])[0]
        self.assertEqual("Reviewed title", item["automatic"]["Title"])
        self.assertEqual("Manual title", item["processed"]["Title"])
        self.assertEqual(1, len(self.store.get_revisions("1", item["item_id"])))

    def test_export_is_idempotent_and_different_settings_keep_separate_snapshot(self):
        run = self.start()
        self.persist(run)
        data = b"Title\r\nReviewed title\r\n"
        for _ in range(2):
            workflow.record_export(self.st, self.store, run, data, "saved.csv", [0], self.config, self.rollup, "file-key")
        self.assertEqual(1, len(self.store.list_exports("1", run["run_id"])))
        self.rollup.markup_percent = 30
        workflow.record_export(self.st, self.store, run, data, "saved.csv", [0], self.config, self.rollup, "file-key")
        exports = self.store.list_exports("1", run["run_id"])
        self.assertEqual({30, 45}, {export["settings"]["rollup"]["markup_percent"] for export in exports})
        for export in exports:
            self.assertEqual(data, self.store.get_export("1", export["export_id"])["csv_bytes"])

    def test_export_can_reference_completed_items_from_separate_trial_runs(self):
        first = self.start()
        self.persist(first)
        second = self.start(indices=(1,))
        self.persist(second, index=1, title="Second title")
        workflow.record_export(self.st, self.store, second, b"Title\nFirst\nSecond\n", "all.csv", [0, 1], self.config, self.rollup, "file-key")
        exports = self.store.list_exports("1", second["run_id"])
        self.assertEqual(1, len(exports))
        self.assertEqual(["0", "1"], exports[0]["row_ids"])
        self.assertEqual(2, len(set(exports[0]["source_items"])))
        self.assertNotEqual(first["run_id"], second["run_id"])

    def test_deleted_history_detaches_manual_and_export_saves_without_changing_active_csv(self):
        run = self.start()
        self.persist(run)
        item = self.store.list_run_items("1", run["run_id"])[0]
        before = pd.DataFrame([_reviewed()])
        active = before.copy()
        active.loc[0, "Title"] = "Manual title retained in current work"
        self.st.session_state["comic_ficp_processed_df"] = active
        self.st.session_state[app.LAST_TRIAL_ROW_INDICES_KEY] = [0]
        self.st.session_state[app.LAST_TRIAL_FILE_KEY] = "file-key"
        self.st.session_state["usd_jpy_exchange_rate"] = 150.0
        expected_active = active.copy(deep=True)
        # A failed save predating deletion must also be intentionally discarded.
        workflow.record_manual_changes(self.st, None, "1", "file-key", before, active, self.config, app)
        self.assertTrue(self.st.session_state[workflow.PENDING])
        self.store.delete_runs("1", [run["run_id"]])
        workflow.forget_deleted_runs(self.st, [run["run_id"]], [item["item_id"]])

        workflow.record_manual_changes(self.st, self.store, "1", "file-key", before, active, self.config, app)
        workflow.record_export(self.st, self.store, run, b"Title\nManual title\n", "current.csv",
                               [0], self.config, self.rollup, "file-key")
        workflow.retry_pending(self.st, self.store)

        self.assertEqual({}, self.st.session_state[workflow.PENDING])
        self.assertNotIn("file-key", self.st.session_state[workflow.RUNS])
        self.assertNotIn("0", self.st.session_state[workflow.ROW_RUNS]["file-key"])
        self.assertIsNone(self.store.get_run("1", run["run_id"]))
        self.assertEqual(0, self.store.list_items("1")[1])
        pd.testing.assert_frame_equal(expected_active, self.st.session_state["comic_ficp_processed_df"])
        self.assertEqual([0], self.st.session_state[app.LAST_TRIAL_ROW_INDICES_KEY])
        self.assertEqual("file-key", self.st.session_state[app.LAST_TRIAL_FILE_KEY])
        self.assertEqual(150.0, self.st.session_state["usd_jpy_exchange_rate"])

    def test_new_trial_after_history_deletion_skips_unrecordable_cumulative_export_without_pending(self):
        first = self.start()
        self.persist(first)
        first_item = self.store.list_run_items("1", first["run_id"])[0]
        second = self.start(indices=(1,))
        self.persist(second, index=1, title="Second title")
        self.store.delete_runs("1", [first["run_id"]])
        workflow.forget_deleted_runs(self.st, [first["run_id"]], [first_item["item_id"]])
        third = self.start(indices=(2,))
        self.persist(third, index=2, title="Third title")
        active = pd.DataFrame([_reviewed(), _reviewed("Second title"), _reviewed("Third title")])
        self.st.session_state["comic_ficp_processed_df"] = active.copy(deep=True)

        workflow.record_export(self.st, self.store, third, b"Title\nFirst\nSecond\nThird\n", "all.csv",
                               [0, 1, 2], self.config, self.rollup, "file-key")
        trial_bytes = b"Title\nThird title\n"
        workflow.record_export(self.st, self.store, third, trial_bytes, "trial.csv",
                               [2], self.config, self.rollup, "file-key")
        workflow.retry_pending(self.st, self.store)

        self.assertEqual({}, self.st.session_state[workflow.PENDING])
        exports = self.store.list_exports("1", third["run_id"])
        self.assertEqual(1, len(exports))
        self.assertEqual(["2"], exports[0]["row_ids"])
        self.assertEqual(trial_bytes, self.store.get_export("1", exports[0]["export_id"])["csv_bytes"])
        self.assertEqual(2, self.store.list_items("1")[1])
        self.assertIsNone(self.store.get_run("1", first["run_id"]))
        pd.testing.assert_frame_equal(active, self.st.session_state["comic_ficp_processed_df"])

    def test_forgetting_deleted_run_preserves_unrelated_pending_work(self):
        first = self.start()
        self.persist(first)
        first_item = self.store.list_run_items("1", first["run_id"])[0]
        second = self.start(indices=(1,))
        self.persist(second, index=1, title="Second title")
        workflow.finish_run(self.st, None, first, {})
        workflow.finish_run(self.st, None, second, {"total_cost_jpy": 2.5})
        self.store.delete_runs("1", [first["run_id"]])
        workflow.forget_deleted_runs(self.st, [first["run_id"]], [first_item["item_id"]])

        self.assertEqual(["finish:" + second["run_id"]], list(self.st.session_state[workflow.PENDING]))
        workflow.retry_pending(self.st, self.store)
        self.assertEqual({}, self.st.session_state[workflow.PENDING])
        self.assertEqual(second["run_id"], self.st.session_state[workflow.RUNS]["file-key"]["run_id"])
        self.assertEqual({"1": second["run_id"]}, self.st.session_state[workflow.ROW_RUNS]["file-key"])
        self.assertEqual(2.5, self.store.get_run("1", second["run_id"])["cost_summary"]["total_cost_jpy"])

    def test_public_workspace_switch_clears_review_session_but_keeps_database_history(self):
        run = self.start()
        self.persist(run)
        workflow.finish_run(self.st, None, run, {})
        self.st.session_state["comic_review_history_selected_item"] = "old-user-item"
        self.st.session_state["comic_review_saved_exports"] = {"old-user-export"}
        self.st.session_state["comic_ficp_processed_df"] = pd.DataFrame([_reviewed()])
        self.st.session_state["usd_jpy_exchange_rate"] = 150.0
        self.st.session_state["unrelated_preference"] = "preserve"

        app.clear_public_session_work_data(self.st)

        self.assertFalse(any(str(key).startswith(("comic_review_", "comic_ficp_", "usd_jpy_"))
                             for key in self.st.session_state))
        self.assertEqual("preserve", self.st.session_state["unrelated_preference"])
        self.assertEqual(1, self.store.list_items("1")[1])
        self.assertEqual(0, self.store.list_items("2")[1])


def _main_test_app(database_path, with_csv):
    import streamlit as st
    import pandas as pd
    from unittest.mock import patch
    import comic_ficp_streamlit_app as app
    import comic_review_workflow as workflow
    from comic_review_history import ReviewHistoryStore

    st.session_state.setdefault("enable_ai_enrichment_default_on", False)
    st.session_state.setdefault("usd_jpy_exchange_rate", 150.0)
    store = ReviewHistoryStore(database_path)
    store.init_schema()
    image = "https://static.mercdn.net/item/detail/orig/photos/m22222222222_1.jpg"
    source = pd.DataFrame([{"Title": f"Test Manga Volumes 1-5 Set {index}", "PicURL": image, "StartPrice": "20.00", "Description": "Manga set", "Category": "259109", "ConditionID": "4000", "ShippingProfileName": "Original"} for index in range(7)])
    raw = source.to_csv(index=False).encode("utf-8-sig") if with_csv else b""

    def fake_process(frame, config, row_indices=None, progress_callback=None, row_callback=None):
        assert config.enable_ai_enrichment is False
        st.session_state["test_processing_calls"] = st.session_state.get("test_processing_calls", 0) + 1
        result = frame.copy()
        indices = list(row_indices)
        for ordinal, index in enumerate(indices, start=1):
            values = {"Title": f"Reviewed manga {index}", "Main Image URL": image, "Detected Book Count": "5", "Billable Weight kg": "1.5", "FICP Shipping USD": "10.00", "FICP Shipping JPY": "1500", "Listing Eligibility": "OK", "Image URL Validation Status": "ok: verified item", "Processing Result": "成功", "Needs Review": "No", "Scrape Status": "ok"}
            for key, value in values.items():
                result.at[index, key] = value
            row_callback(index, result.loc[index].copy())
            progress_callback(ordinal, len(indices), values["Title"])
        return result.fillna("")

    with patch.object(app, "is_public_mode", return_value=False), \
         patch.object(app, "get_uploaded_or_cached_csv", return_value=(raw, "sample.csv", False)), \
         patch.object(app, "load_local_title_overrides", return_value={}), \
         patch.object(app, "save_processed_dataframe_cache"), \
         patch.object(app, "process_dataframe", side_effect=fake_process), \
         patch.object(app.requests.Session, "request", side_effect=AssertionError("Unexpected network")), \
         patch.object(workflow, "open_history", return_value=(store, "local")), \
         patch.object(workflow, "archive_review_image", return_value={"status": "test image unavailable", "data": b"", "mime": ""}):
        app.main()


class MainScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "history.sqlite")

    def tearDown(self):
        self.temp.cleanup()

    def make_app(self, with_csv):
        from streamlit.testing.v1 import AppTest
        return AppTest.from_function(_main_test_app, args=(self.db_path, with_csv)).run(timeout=30)

    def test_main_empty_screen_mounts_work_and_history_pages(self):
        screen = self.make_app(False)
        self.assertFalse(screen.exception)
        self.assertEqual(["CSVを精査", "精査履歴"], [tab.label for tab in screen.tabs])
        self.assertFalse(screen.error)

    def test_main_trial_creates_five_history_items_and_only_trial_download(self):
        screen = self.make_app(True)
        self.assertFalse(screen.exception)
        button = next(button for button in screen.button if button.label == "5件だけ試す")
        button.click().run(timeout=30)
        self.assertFalse(screen.exception)
        self.assertFalse(screen.error)
        self.assertEqual(1, screen.session_state["test_processing_calls"])
        store = ReviewHistoryStore(self.db_path)
        items, count = store.list_items("local")
        self.assertEqual(5, count)
        self.assertEqual({"0", "1", "2", "3", "4"}, {item["row_id"] for item in items})
        downloads = screen.get("download_button")
        trial = next(button for button in downloads if button.proto.id.endswith("-comic_ficp_download_trial"))
        full = next(button for button in downloads if button.proto.id.endswith("-comic_ficp_download_top"))
        self.assertFalse(trial.proto.disabled)
        self.assertTrue(full.proto.disabled)
        self.assertIn("処理済みの出力可能 5件 / 未処理 2件", "\n".join(item.value for item in screen.markdown))
        run = store.list_runs("local")[0]
        self.assertEqual(5, len(store.list_exports("local", run["run_id"])[0]["row_ids"]))
        # Reruns/history rendering are read-only and never repeat the mock AI run.
        screen.run()
        self.assertEqual(1, screen.session_state["test_processing_calls"])
        self.assertEqual(5, store.list_items("local")[1])
        screen.session_state["comic_review_history_selected_item"] = items[0]["item_id"]
        screen.run()
        self.assertFalse(screen.exception)
        self.assertFalse(screen.error)
        screen.button(key="comic_review_history_back").click().run()
        self.assertFalse(screen.exception)
        self.assertEqual(1, screen.session_state["test_processing_calls"])
        self.assertEqual([0, 1, 2, 3, 4], screen.session_state[app.LAST_TRIAL_ROW_INDICES_KEY])


if __name__ == "__main__":
    unittest.main()
