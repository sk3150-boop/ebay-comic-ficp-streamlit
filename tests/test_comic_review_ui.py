import unittest
import tempfile
from pathlib import Path

from comic_review_ui import (
    display_timestamp, filter_review_records, image_data_url,
    review_display_frame, safe_image_url, selected_record_id, status_summary,
)


class ReviewListTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"id": "run-b:0", "position": 0, "title": "Cells at Work", "source_title": "はたらく細胞", "status": "注意あり", "file_name": "B.csv", "shipping": "$5"},
            {"id": "run-a:0", "position": 0, "title": "Saltiness", "source_title": "サルチネス", "status": "出力可能", "file_name": "A.csv", "shipping": "$7"},
            {"id": "run-a:1", "position": 1, "title": "Missing", "status": "除外"},
        ]

    def test_search_matches_native_english_and_csv(self):
        for query in ("cells AT", "細胞", "b.CSV"):
            self.assertEqual(["run-b:0"], [row["id"] for row in filter_review_records(self.rows, query)])

    def test_low_confidence_is_not_held_or_excluded(self):
        self.assertEqual(["run-b:0"], [row["id"] for row in filter_review_records(self.rows, status="注意あり")])
        self.assertEqual(1, status_summary(self.rows)["注意あり"])
        self.assertEqual(0, status_summary(self.rows)["要確認"])

    def test_selection_uses_visible_stable_id_not_csv_position(self):
        filtered = filter_review_records(self.rows, "Saltiness")
        self.assertEqual("run-a:0", selected_record_id(filtered, [(0, "タイトル")]))
        self.assertEqual("run-a:0", selected_record_id(list(reversed(self.rows)), [1]))

    def test_invalid_selection_does_not_open_different_record(self):
        for event in ([], [()], [-1], [99], [True], ["abc"], None):
            self.assertIsNone(selected_record_id(self.rows, event))

    def test_display_does_not_mutate_or_expose_ids(self):
        display = review_display_frame(self.rows)
        self.assertEqual("Cells at Work", display.iloc[0]["タイトル"])
        self.assertNotIn("id", display.columns)
        self.assertEqual("run-b:0", self.rows[0]["id"])

    def test_only_supported_images_render(self):
        for value in ("javascript:alert(1)", "file:///C:/secret", "data:image/svg+xml,<svg>", "https://[broken/photo.jpg", "https://secret:password@example.com/photo.jpg"):
            self.assertEqual("", safe_image_url(value))
        self.assertEqual("https://example.com/image.jpg", safe_image_url("https://example.com/image.jpg"))
        self.assertEqual("data:image/jpeg;base64,YWJj", image_data_url({"mime": "image/jpeg", "data": b"abc"}))
        self.assertEqual("", image_data_url({"mime": "text/html", "data": b"abc"}))

    def test_timestamp_is_explicit_japan_time(self):
        self.assertEqual("2026/09/07 09:00", display_timestamp("2026-09-07T00:00:00Z"))
        self.assertEqual("2026/09/07 09:00", display_timestamp("2026-09-07T09:00:00+09:00"))


def _history_test_app(database_url):
    import streamlit as st
    from types import SimpleNamespace
    from comic_review_history import ReviewHistoryStore
    from comic_review_ui import render_history_page

    def preview(st, row, row_index, title_col, price_col, image_col, url_col, **options):
        assert options["readonly"] is True
        assert options["original_row"]["Title"] == "before"
        assert title_col == "MyTitle"
        st.text("READONLY: " + row[title_col])

    adapter = SimpleNamespace(render_selected_preview=preview)
    render_history_page(st, ReviewHistoryStore(database_url), "1", adapter)


def _list_navigation_test_app():
    import streamlit as st
    from comic_review_ui import render_unified_review_list
    view = st.radio("View", ["list", "detail"], key="view")
    if "test_list_cards" not in st.session_state and "test_list_cards__saved" not in st.session_state:
        st.session_state["test_list_cards"] = False
    if view == "list":
        records = [{"id": f"run:{index}", "title": f"Match {index}", "status": "出力可能"} for index in range(52)]
        render_unified_review_list(st, records, key="test_list")
    else:
        st.text("Detail with hidden list widgets")


def _public_tab_navigation_test_app():
    """Use the real public gate, including its once-per-session cookie iframe."""
    import streamlit as st
    from unittest.mock import patch
    import comic_ficp_streamlit_app as app
    import comic_review_workflow as workflow

    def history(st, store, workspace_id, adapter):
        st.toggle("History cards", key="test_history_cards")

    with patch.object(app, "is_public_mode", return_value=True), \
         patch.object(app, "public_auth_config_status", return_value=(True, "")), \
         patch.object(app, "public_auth_required", return_value=False), \
         patch.object(app, "public_database_url", return_value="sqlite:///:memory:"), \
         patch.object(app, "ensure_public_single_workspace_user", return_value=(True, {"id": 1, "username": "workspace"}, "")), \
         patch.object(app, "render_global_styles"), \
         patch.object(app, "render_app_header"), \
         patch.object(app, "render_history_page", side_effect=history), \
         patch.object(app, "render_work_page", side_effect=lambda st, store, workspace: st.text("Work page")), \
         patch.object(workflow, "open_history", return_value=(object(), "1")):
        app.main()


def _transient_gate_tab_test_app(contained):
    import streamlit as st
    from unittest.mock import patch
    import comic_ficp_streamlit_app as app

    with patch.object(app, "is_public_mode", return_value=True), \
         patch.object(app, "public_auth_config_status", return_value=(True, "")), \
         patch.object(app, "public_auth_required", return_value=False), \
         patch.object(app, "public_database_url", return_value="sqlite:///:memory:"), \
         patch.object(app, "ensure_public_single_workspace_user", return_value=(True, {"id": 1, "username": "workspace"}, "")):
        if contained:
            with st.container(key="fixed_gate"):
                app.render_public_login_gate(st)
        else:
            app.render_public_login_gate(st)
    work, history = st.tabs(["Work", "History"])
    with history:
        st.toggle("Cards", key="cards")


def _block_paths(node, wanted_type, path=()):
    found = [path] if getattr(node, "type", None) == wanted_type else []
    for index, child in getattr(node, "children", {}).items():
        found.extend(_block_paths(child, wanted_type, (*path, index)))
    return found


def _grid_test_app():
    import streamlit as st
    from comic_review_ui import render_unified_review_list
    records = [{"id": f"stable:{i}", "title": f"Manga {i}", "status": "要確認"} for i in range(5)]
    selected = render_unified_review_list(st, records, key="grid_test", show_filters=False, paginated=False)
    if selected:
        st.text("SELECTED " + selected)


class GridLayoutTests(unittest.TestCase):
    def test_default_grid_uses_four_columns_and_preserves_last_item_id(self):
        from streamlit.testing.v1 import AppTest
        screen = AppTest.from_function(_grid_test_app).run()
        self.assertFalse(screen.exception)
        self.assertTrue(screen.toggle(key="grid_test_cards").value)
        self.assertEqual(8, len(screen.columns))
        self.assertEqual(5, len(screen.button))
        css = "\n".join(element.value for element in screen.markdown)
        self.assertIn("repeat(4, minmax(0, 1fr))", css)
        self.assertIn("repeat(2, minmax(0, 1fr))", css)
        screen.button(key="grid_test_card_stable:4").click().run()
        self.assertFalse(screen.exception)
        self.assertIn("SELECTED stable:4", [element.value for element in screen.text])


class PublicTabIdentityTests(unittest.TestCase):
    def test_uncontained_once_only_cookie_iframe_moves_tab_delta_path(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_function(_transient_gate_tab_test_app, args=(False,)).run()
        initial = _block_paths(app._tree, "tab_container")
        app.toggle(key="cards").set_value(True).run()
        self.assertFalse(app.exception)
        self.assertNotEqual(initial, _block_paths(app._tree, "tab_container"))

    def test_fixed_gate_keeps_tab_delta_path_when_cookie_iframe_disappears(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_function(_transient_gate_tab_test_app, args=(True,)).run()
        initial = _block_paths(app._tree, "tab_container")
        self.assertEqual(1, len(initial))
        app.toggle(key="cards").set_value(True).run()
        self.assertFalse(app.exception)
        self.assertEqual(initial, _block_paths(app._tree, "tab_container"))

    def test_real_main_keeps_tab_identity_on_first_public_history_interaction(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_function(_public_tab_navigation_test_app).run()
        initial = _block_paths(app._tree, "tab_container")
        self.assertEqual(1, len(initial))
        app.toggle(key="test_history_cards").set_value(True).run()
        self.assertFalse(app.exception)
        self.assertEqual(initial, _block_paths(app._tree, "tab_container"))
        self.assertTrue(app.toggle(key="test_history_cards").value)


class HistoryPageTests(unittest.TestCase):
    def setUp(self):
        from comic_review_history import ReviewHistoryStore, ReviewRun
        self.temp = tempfile.TemporaryDirectory()
        self.db_url = f"sqlite:///{Path(self.temp.name) / 'history.sqlite'}"
        self.store = ReviewHistoryStore(self.db_url)
        self.run_id = self.store.save_run(ReviewRun("1", "example.csv", "trial", settings={"processing": {"title_col": "MyTitle"}}))
        self.item_id = self.store.save_item("1", self.run_id, "0", {"Title": "before"}, {"MyTitle": "After title"}, {"title": "After title", "source_title": "元タイトル", "status": "注意あり", "shipping_usd": "5.00"})
        self.store.finish_run("1", self.run_id, cost_summary={"total_cost_jpy": 1.25, "grounding_list_cost_jpy": 0})
        self.store.save_export("1", self.run_id, b"Title\r\nAfter title\r\n", "prepared.csv", {}, ["0"])

    def tearDown(self):
        self.temp.cleanup()

    def app(self):
        from streamlit.testing.v1 import AppTest
        screen = AppTest.from_function(_history_test_app, args=(self.db_url,)).run(timeout=10)
        return screen.toggle(key="comic_review_history_list_cards").set_value(False).run()

    def test_history_lists_stored_exports_without_processing(self):
        app = self.app()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(1, len(app.dataframe))
        self.assertEqual("After title", app.dataframe[0].value.iloc[0]["タイトル"])
        self.assertEqual(1, len(self.store.list_exports("1", self.run_id)))
        self.assertEqual(1, self.store.list_items("1")[1])

    def test_detail_is_readonly_and_return_preserves_search(self):
        app = self.app()
        app.text_input(key="comic_review_history_search").set_value("After").run()
        app.session_state["comic_review_history_selected_item"] = self.item_id
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertIn("READONLY: After title", [element.value for element in app.text])
        self.assertEqual(0, len(app.text_input))
        self.assertEqual(0, len(app.date_input))
        self.assertNotIn("CSVごとの処理情報・再ダウンロード", [element.label for element in app.expander])
        app.button(key="comic_review_history_back").click().run()
        self.assertFalse(app.exception)
        self.assertEqual("After", app.text_input(key="comic_review_history_search").value)
        self.assertEqual(1, len(app.dataframe))

    def test_detail_hides_list_controls_and_restores_all_filters_and_page(self):
        from datetime import datetime
        from comic_review_ui import JST
        for index in range(1, 52):
            self.store.save_item("1", self.run_id, str(index), {"Title": "before"},
                                 {"MyTitle": f"After title {index}"},
                                 {"title": f"After title {index}", "status": "注意あり"})
        app = self.app()
        today = datetime.now(JST).date()
        app.text_input(key="comic_review_history_search").set_value("After").run()
        app.selectbox(key="comic_review_history_status").set_value("注意あり").run()
        app.selectbox(key="comic_review_history_file").set_value("example.csv").run()
        app.date_input(key="comic_review_history_dates").set_value((today, today)).run()
        app.selectbox(key="comic_review_history_page").set_value(2).run()
        app.session_state["comic_review_history_selected_item"] = self.item_id
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual(0, len(app.text_input))
        self.assertEqual(0, len(app.selectbox))
        self.assertEqual(0, len(app.date_input))
        self.assertEqual("← 精査一覧に戻る", app.button[0].label)
        app.button(key="comic_review_history_back").click().run()
        self.assertFalse(app.exception)
        self.assertFalse(app.error)
        self.assertEqual("After", app.text_input(key="comic_review_history_search").value)
        self.assertEqual("注意あり", app.selectbox(key="comic_review_history_status").value)
        self.assertEqual("example.csv", app.selectbox(key="comic_review_history_file").value)
        self.assertEqual((today, today), app.date_input(key="comic_review_history_dates").value)
        self.assertEqual(2, app.selectbox(key="comic_review_history_page").value)
        self.assertEqual(2, len(app.dataframe[0].value))

    def test_delete_requires_explicit_checkbox(self):
        app = self.app()
        button_key = f"comic_review_history_delete_{self.run_id}"
        self.assertTrue(app.button(key=button_key).disabled)
        app.checkbox(key=f"comic_review_history_confirm_delete_{self.run_id}").check().run()
        self.assertFalse(app.button(key=button_key).disabled)
        app.button(key=button_key).click().run()
        self.assertFalse(app.exception)
        self.assertIsNone(self.store.get_run("1", self.run_id))

    def test_hidden_list_widgets_restore_filter_and_page(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_function(_list_navigation_test_app).run()
        app.text_input(key="test_list_search").set_value("match").run()
        app.selectbox(key="test_list_page").set_value(2).run()
        self.assertEqual(2, len(app.dataframe[0].value))
        app.radio(key="view").set_value("detail").run()
        app.radio(key="view").set_value("list").run()
        self.assertFalse(app.exception)
        self.assertEqual("match", app.text_input(key="test_list_search").value)
        self.assertEqual(2, app.selectbox(key="test_list_page").value)
        self.assertEqual("Match 50", app.dataframe[0].value.iloc[0]["タイトル"])


if __name__ == "__main__":
    unittest.main()
