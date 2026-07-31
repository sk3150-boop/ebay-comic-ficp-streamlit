import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comic_ficp_streamlit_app import (  # noqa: E402
    AIEnrichment,
    APIUsage,
    AUTOFILL_MARKER_START,
    ExchangeRateEstimate,
    DEFAULT_BOOK_WEIGHT_G,
    DEFAULT_FICP_ZONE,
    DEFAULT_FREE_SHIPPING_PROFILE_NAME,
    DEFAULT_FREE_SHIPPING_MARKUP_PERCENT,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_MAX_BOOK_COUNT_FOR_EXPORT,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_PACKAGING_WEIGHT_KG,
    FREE_SHIPPING_PROFILE_OPTIONS,
    FreeShippingRollupOptions,
    GEMINI_MODEL_OPTIONS,
    ListingData,
    OPENAI_MODEL_OPTIONS,
    PREFLIGHT_PENDING_SELECTION_KEY,
    PUBLIC_ACTIVE_REMEMBER_TOKEN_HASH_KEY,
    PUBLIC_REMEMBER_COOKIE_NAME,
    PUBLIC_REMEMBER_RESTORE_BLOCKED_KEY,
    PUBLIC_SESSION_USER_KEY,
    ProcessingConfig,
    ReferenceBookCountResult,
    TRIAL_PROCESSING_BATCH_SIZE,
    append_description,
    append_unique_buyer_notes,
    apply_usd_jpy_exchange_rate_to_session_state,
    apply_query_selected_row,
    apply_item_specifics,
    build_description_append,
    build_description_append_display_text,
    build_public_remember_cookie_script,
    build_buyer_description_items,
    build_api_usage,
    build_ebay_preflight_table,
    build_exclusion_table,
    build_trial_export_dataframe,
    build_export_dataframe,
    build_processing_diagnostic_table,
    build_preview_image_urls,
    build_review_table,
    build_preview_metric_items,
    build_selected_decision_html,
    build_source_detail_preview,
    build_workflow_steps_html,
    create_public_user,
    create_public_remember_token,
    build_specifics_review_rows,
    build_specifics_summary_items,
    calculate_billable_weight_kg,
    calculate_dimensional_weight_kg,
    calculate_ficp_shipping,
    calculate_fuel_surcharge_jpy,
    calculate_shipping_total_with_fuel,
    call_gemini_ai_enrichment,
    call_openai_ai_enrichment,
    clean_source_listing_description,
    contains_japanese_text,
    delete_saved_api_key,
    default_ai_model_for_provider,
    decide_manga_export_condition,
    delete_public_saved_api_key,
    delete_public_remember_token,
    delete_public_remember_tokens_for_user,
    diagnose_processed_row,
    detect_book_count,
    detect_book_count_limit_issue,
    detect_book_count_with_references,
    detect_magazine_listing_issue,
    detect_unlistable_listing_issue,
    estimate_book_weight_g,
    estimate_api_cost_usd,
    estimate_packaging_weight_kg,
    estimate_ui_remaining_seconds,
    extract_json_object,
    extract_listing_payload,
    extract_buyer_relevant_listing_details,
    extract_mercari_condition_from_rendered_text,
    fetch_usd_jpy_exchange_rate,
    filter_listing_image_urls,
    format_ui_duration,
    get_api_pricing,
    get_uploaded_or_cached_csv,
    guess_columns,
    infer_mercari_url_from_image_url,
    infer_specifics,
    infer_specifics_with_notes,
    is_plausible_public_remember_token,
    is_likely_image_url,
    lookup_complete_set_book_count,
    load_saved_api_key,
    load_public_saved_api_key,
    parse_mercari_rendered_listing,
    parse_ai_enrichment_payload,
    process_dataframe,
    redact_sensitive_text,
    refresh_usd_jpy_exchange_rate_session_state,
    resolve_preflight_selected_position,
    render_product_selection_dataframe,
    render_public_remember_cookie_script,
    restore_public_user_from_remember_cookie,
    authenticate_public_remember_token,
    authenticate_public_user,
    public_saved_api_key_exists,
    save_api_key,
    save_public_api_key,
    load_processed_dataframe_cache,
    saved_api_key_exists,
    save_processed_dataframe_cache,
    save_uploaded_csv_cache,
    sanitize_description_html,
    select_trial_batch_indices,
    summarize_ui_rows,
    summarize_api_costs,
    translate_description_added_text_to_japanese,
    BeautifulSoup,
)


class FakeUpload:
    def __init__(self, raw: bytes, name: str = "input.csv"):
        self._raw = raw
        self.name = name

    def getvalue(self) -> bytes:
        return self._raw


class FakeStreamlit:
    def __init__(self, query_params=None, cookies=None):
        self.session_state = {}
        self.query_params = query_params or {}
        self.context = SimpleNamespace(cookies=cookies or {})


class ComicFicpLogicTest(unittest.TestCase):
    def test_workflow_steps_marks_completed_active_and_pending_states(self):
        markup = build_workflow_steps_html(3)

        self.assertEqual(markup.count('class="workflow-step '), 5)
        self.assertEqual(markup.count("is-complete"), 2)
        self.assertEqual(markup.count("is-active"), 1)
        self.assertEqual(markup.count("is-pending"), 2)
        self.assertIn('aria-current="step"', markup)
        self.assertIn("自動補完", markup)

    def test_processing_time_helpers_format_and_estimate_remaining(self):
        self.assertEqual(format_ui_duration(0), "0秒")
        self.assertEqual(format_ui_duration(65), "1分05秒")
        self.assertEqual(format_ui_duration(3660), "1時間01分")
        self.assertEqual(format_ui_duration(None), "計測中")
        self.assertEqual(estimate_ui_remaining_seconds(30, 2, 5), 45.0)
        self.assertEqual(estimate_ui_remaining_seconds(30, 5, 5), 0.0)
        self.assertIsNone(estimate_ui_remaining_seconds(30, 0, 5))

    def test_processing_ui_does_not_render_redundant_four_metric_cards(self):
        source = (ROOT / "comic_ficp_streamlit_app.py").read_text(encoding="utf-8")

        self.assertNotIn("progress_metrics", source)
        self.assertIn("progress_bar = st.progress", source)
        self.assertIn("render_api_cost_summary", source)

    def test_completed_csv_download_is_promoted_above_step_one(self):
        source = (ROOT / "comic_ficp_streamlit_app.py").read_text(encoding="utf-8")

        priority_slot = source.index("priority_download_slot = st.empty()")
        step_one = source.index('render_section_heading(st, "STEP 1", "CSVを読み込む"')
        self.assertLess(priority_slot, step_one)
        self.assertIn('key="comic_ficp_download_top"', source)
        self.assertIn('key="comic_ficp_download_step5"', source)
        self.assertIn("if all_rows_processed and not export_frame.empty:", source)
        self.assertIn("保存できる商品が0件です。", source)
        self.assertIn("with download_slot.container():", source)
        self.assertNotIn("with download_slot:\n", source)

    def test_download_slot_container_keeps_heading_button_and_caption(self):
        from streamlit.testing.v1 import AppTest

        script = '''
import streamlit as st

download_slot = st.empty()
with download_slot.container():
    st.markdown("STEP 5")
    st.download_button("Download CSV", data=b"Title\\nA\\n", file_name="out.csv")
    st.caption("export ready")
'''
        app = AppTest.from_string(script, default_timeout=30).run()

        self.assertEqual(0, len(app.exception))
        self.assertEqual(1, len(app.get("download_button")))
        self.assertIn("STEP 5", [item.value for item in app.markdown])
        self.assertIn("export ready", [item.value for item in app.caption])

    def test_ui_row_summary_separates_ready_review_excluded_and_unprocessed(self):
        frame = pd.DataFrame(
            [
                {"Scrape Status": "ok", "Listing Eligibility": "OK", "Needs Review": "No"},
                {"Scrape Status": "ok", "Listing Eligibility": "OK", "Needs Review": "Yes"},
                {"Scrape Status": "ok", "Listing Eligibility": "Excluded", "Needs Review": "Yes"},
                {
                    "Title": "Not processed",
                    "Scrape Status": "",
                    "Listing Eligibility": "",
                    "Needs Review": "",
                },
            ]
        )

        self.assertEqual(
            summarize_ui_rows(frame),
            {"total": 4, "processed": 3, "ready": 1, "review": 1, "excluded": 1, "remaining": 1},
        )

    def test_selected_decision_highlights_output_and_image_safety(self):
        row = pd.Series(
            {
                "Listing Eligibility": "OK",
                "Needs Review": "No",
                "Image URL Validation Status": "ok: 4 same-listing images; rejected 7 off-listing images",
                "Rejected Source Image URL Count": "7",
            }
        )

        markup = build_selected_decision_html(row, processed=True)

        self.assertIn("出力可能", markup)
        self.assertIn("画像検証済み", markup)
        self.assertIn("商品外画像 7件を除外", markup)
        self.assertIn("decision-success", markup)

    def test_uploaded_csv_is_cached_for_query_link_reruns(self):
        fake_st = FakeStreamlit()
        raw = b"Title,PicURL\nOne,https://example.com/image.jpg\n"

        first_raw, first_name, first_cached = get_uploaded_or_cached_csv(fake_st, FakeUpload(raw, "items.csv"), persist=False)
        second_raw, second_name, second_cached = get_uploaded_or_cached_csv(fake_st, None, persist=False)

        self.assertEqual(first_raw, raw)
        self.assertEqual(first_name, "items.csv")
        self.assertFalse(first_cached)
        self.assertEqual(second_raw, raw)
        self.assertEqual(second_name, "items.csv")
        self.assertTrue(second_cached)

    def test_uploaded_csv_is_restored_from_local_cache_for_query_link_reload(self):
        fake_st = FakeStreamlit(query_params={"comic_ficp_select": "2"})
        raw = b"Title,PicURL\nTwo,https://example.com/image2.jpg\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            raw_path = Path(tmp_dir) / "last_uploaded_csv.bin"
            meta_path = Path(tmp_dir) / "last_uploaded_csv.json"
            with patch("comic_ficp_streamlit_app.UPLOAD_CACHE_RAW_PATH", raw_path), patch(
                "comic_ficp_streamlit_app.UPLOAD_CACHE_META_PATH", meta_path
            ):
                save_uploaded_csv_cache(raw, "items.csv")
                restored_raw, restored_name, restored_cached = get_uploaded_or_cached_csv(fake_st, None)

        self.assertEqual(restored_raw, raw)
        self.assertEqual(restored_name, "items.csv")
        self.assertTrue(restored_cached)

    def test_processed_dataframe_cache_restores_processed_results_for_same_csv(self):
        processed = pd.DataFrame(
            [
                {
                    "Title": "Processed Manga Set",
                    "Detected Book Count": "12",
                    "FICP Shipping USD": "24.50",
                    "Scrape Status": "ok",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            df_path = Path(tmp_dir) / "last_processed_dataframe.pkl"
            meta_path = Path(tmp_dir) / "last_processed_dataframe.json"
            with patch("comic_ficp_streamlit_app.PROCESSED_CACHE_DF_PATH", df_path), patch(
                "comic_ficp_streamlit_app.PROCESSED_CACHE_META_PATH", meta_path
            ):
                save_processed_dataframe_cache(processed, "items.csv:abc123")
                restored = load_processed_dataframe_cache("items.csv:abc123")
                mismatched = load_processed_dataframe_cache("other.csv:abc123")

        self.assertIsNotNone(restored)
        self.assertEqual(restored.loc[0, "Detected Book Count"], "12")
        self.assertEqual(restored.loc[0, "FICP Shipping USD"], "24.50")
        self.assertIsNone(mismatched)

    def test_ai_model_option_lists_include_multiple_models_and_custom(self):
        gemini_ids = [model_id for model_id, _ in GEMINI_MODEL_OPTIONS]
        openai_ids = [model_id for model_id, _ in OPENAI_MODEL_OPTIONS]

        self.assertGreaterEqual(len(gemini_ids), 7)
        self.assertGreaterEqual(len(openai_ids), 6)
        self.assertIn("custom", gemini_ids)
        self.assertIn("custom", openai_ids)
        self.assertEqual(default_ai_model_for_provider("gemini"), DEFAULT_GEMINI_MODEL)
        self.assertEqual(default_ai_model_for_provider("openai"), DEFAULT_OPENAI_MODEL)

    def test_api_cost_estimates_use_cached_and_output_token_rates(self):
        gemini_cost, gemini_status = estimate_api_cost_usd(
            "gemini", "gemini-2.5-flash-lite", 1000, 200, 500
        )
        openai_cost, openai_status = estimate_api_cost_usd(
            "openai", "gpt-5.4-mini", 1000, 0, 500
        )

        self.assertAlmostEqual(gemini_cost, 0.000282, places=9)
        self.assertAlmostEqual(openai_cost, 0.003, places=9)
        self.assertIn("standard paid estimate", gemini_status)
        self.assertIn("standard paid estimate", openai_status)
        self.assertEqual(get_api_pricing("openai", "gpt-5.4-mini-2026-07-01")["output"], 4.50)

    def test_unknown_api_model_is_not_treated_as_known_zero_cost(self):
        cost, status = estimate_api_cost_usd("openai", "custom-private-model", 1000, 0, 500)
        missing_usage = build_api_usage("openai", "gpt-5.4-mini", 0, 0, 0, 0)

        self.assertEqual(cost, 0.0)
        self.assertEqual(status, "price unavailable")
        self.assertEqual(get_api_pricing("openai", "custom-private-model"), {})
        self.assertEqual(missing_usage.calls, 1)
        self.assertEqual(missing_usage.pricing_status, "usage unavailable")

    def test_openai_response_preserves_usage_tokens(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "output_text": '{"book_count": 2}',
            "usage": {
                "input_tokens": 500,
                "input_tokens_details": {"cached_tokens": 50},
                "output_tokens": 70,
                "total_tokens": 570,
            },
        }

        with patch("comic_ficp_streamlit_app.requests.post", return_value=response):
            result = call_openai_ai_enrichment("test-key", "gpt-5.4-mini", "prompt")

        self.assertIn("book_count", result.text)
        self.assertEqual(result.usage.calls, 1)
        self.assertEqual(result.usage.input_tokens, 500)
        self.assertEqual(result.usage.cached_input_tokens, 50)
        self.assertEqual(result.usage.output_tokens, 70)
        self.assertEqual(result.usage.total_tokens, 570)

    def test_empty_ai_text_still_preserves_billable_usage(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "output": [],
            "usage": {"input_tokens": 300, "output_tokens": 12, "total_tokens": 312},
        }

        with patch("comic_ficp_streamlit_app.requests.post", return_value=response):
            result = call_openai_ai_enrichment("test-key", "gpt-5.4-mini", "prompt")

        self.assertEqual(result.text, "")
        self.assertEqual(result.usage.calls, 1)
        self.assertEqual(result.usage.total_tokens, 312)
        self.assertGreater(result.usage.estimated_cost_usd, 0)

    def test_gemini_response_preserves_usage_tokens_including_thoughts(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": '{"book_count": 2}'}]}}],
            "usageMetadata": {
                "promptTokenCount": 400,
                "cachedContentTokenCount": 100,
                "candidatesTokenCount": 60,
                "thoughtsTokenCount": 20,
                "totalTokenCount": 480,
            },
        }

        with patch("comic_ficp_streamlit_app.requests.post", return_value=response):
            result = call_gemini_ai_enrichment("test-key", "gemini-2.5-flash-lite", "prompt")

        self.assertIn("book_count", result.text)
        self.assertEqual(result.usage.calls, 1)
        self.assertEqual(result.usage.input_tokens, 400)
        self.assertEqual(result.usage.cached_input_tokens, 100)
        self.assertEqual(result.usage.output_tokens, 80)
        self.assertEqual(result.usage.total_tokens, 480)

    def test_api_cost_summary_combines_usage_and_marks_unpriced_calls(self):
        frame = pd.DataFrame(
            [
                {
                    "AI Provider": "openai",
                    "AI Model": "gpt-5.4-mini",
                    "AI API Calls": "1",
                    "AI Input Tokens": "1000",
                    "AI Cached Input Tokens": "0",
                    "AI Output Tokens": "500",
                    "AI Total Tokens": "1500",
                    "AI Estimated Cost USD": "0.003",
                    "AI Pricing Status": "standard paid estimate (2026-07-14)",
                },
                {
                    "AI Provider": "gemini",
                    "AI Model": "custom-model",
                    "AI API Calls": "1",
                    "AI Input Tokens": "200",
                    "AI Output Tokens": "20",
                    "AI Total Tokens": "220",
                    "AI Estimated Cost USD": "0",
                    "AI Pricing Status": "price unavailable",
                },
            ]
        )

        summary = summarize_api_costs(frame, 155)

        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["priced_calls"], 1)
        self.assertEqual(summary["unpriced_calls"], 1)
        self.assertEqual(summary["total_tokens"], 1720)
        self.assertAlmostEqual(summary["total_cost_usd"], 0.003)
        self.assertAlmostEqual(summary["total_cost_jpy"], 0.465)
        self.assertFalse(summary["cost_complete"])
        self.assertEqual(summary["unknown_pricing_models"], ["gemini:custom-model"])

    def test_guess_columns_does_not_treat_shipping_profile_as_shipping_cost(self):
        guessed = guess_columns(["StartPrice", "ShippingProfileName", "Title"])
        self.assertEqual(guessed["price_col"], "StartPrice")
        self.assertEqual(guessed["shipping_profile_col"], "ShippingProfileName")
        self.assertEqual(guessed["shipping_col"], "")

    def test_default_free_shipping_policy_uses_fedex_policy_name(self):
        self.assertEqual(DEFAULT_FREE_SHIPPING_PROFILE_NAME, "Free Shipping Policy Fedex")
        self.assertEqual(FREE_SHIPPING_PROFILE_OPTIONS[0], DEFAULT_FREE_SHIPPING_PROFILE_NAME)
        self.assertIn("Free Shipping Policy", FREE_SHIPPING_PROFILE_OPTIONS)

    def test_default_export_safety_limits(self):
        self.assertEqual(DEFAULT_MAX_BOOK_COUNT_FOR_EXPORT, 40)
        self.assertEqual(DEFAULT_FREE_SHIPPING_MARKUP_PERCENT, 30.0)
        self.assertEqual(TRIAL_PROCESSING_BATCH_SIZE, 5)
        self.assertEqual(ProcessingConfig().max_book_count_for_export, 40)
        self.assertTrue(FreeShippingRollupOptions().enabled)
        self.assertEqual(FreeShippingRollupOptions().markup_percent, 30.0)

    def test_trial_batch_starts_with_selected_row_and_keeps_row_order(self):
        frame = pd.DataFrame(
            [{"Title": f"Book {position}"} for position in range(7)],
            index=[10, 20, 30, 40, 50, 60, 70],
        )

        self.assertEqual(select_trial_batch_indices(frame, 30), [30, 40, 50, 60, 70])
        self.assertEqual(select_trial_batch_indices(frame, 60), [60, 70])
        self.assertEqual(select_trial_batch_indices(frame, 999), [10, 20, 30, 40, 50])

    def test_detect_book_count_sums_multiple_complete_ranges(self):
        count, evidence = detect_book_count("浦安鉄筋家族1〜31全巻 元祖！浦安鉄筋家族1〜28全巻")

        self.assertEqual(count, 59)
        self.assertIn("1-31全巻", evidence)
        self.assertIn("1-28全巻", evidence)

    def test_detect_book_count_sums_english_multiple_complete_ranges(self):
        count, evidence = detect_book_count(
            "Gag Manga Biyori 1-31 Complete, Original Gag Manga Biyori 1-28 Complete"
        )

        self.assertEqual(count, 59)
        self.assertIn("1-31 Complete", evidence)
        self.assertIn("1-28 Complete", evidence)

    def test_detect_book_count_does_not_double_count_repeated_same_range(self):
        text = "Blue Lock Volumes 1-27 Set\nBlue Lock Volumes 1-27 Set"

        count, evidence = detect_book_count(text)

        self.assertEqual(count, 27)
        self.assertEqual(evidence.count("1-27"), 1)

    def test_detect_book_count_deduplicates_translated_ranges_and_nested_artifacts(self):
        text = "\n".join(
            [
                "浦安鉄筋家族11-31巻",
                "浦安鉄筋家族1-31全巻 元祖！浦安鉄筋家族1-28全巻",
                "Gag Manga Biyori 1-31 Complete, Original Gag Manga Biyori 1-28 Complete",
            ]
        )

        count, evidence = detect_book_count(text)

        self.assertEqual(count, 59)
        self.assertNotIn("11-31", evidence)
        self.assertEqual(evidence.count("1-31"), 1)
        self.assertEqual(evidence.count("1-28"), 1)

    def test_build_export_dataframe_rolls_shipping_into_price_and_free_policy(self):
        frame = pd.DataFrame(
            [
                {
                    "StartPrice": "100.00",
                    "ShippingProfileName": "200-300 eBay SpeedPAK Economy US",
                    "FICP Shipping USD": "25.57",
                    "Listing Eligibility": "",
                }
            ]
        )
        export = build_export_dataframe(
            frame,
            FreeShippingRollupOptions(
                enabled=True,
                price_col="StartPrice",
                shipping_profile_col="ShippingProfileName",
                free_shipping_profile_name="Free Shipping Policy",
                markup_percent=5.0,
            ),
        )
        self.assertEqual(export.loc[0, "StartPrice"], "126.85")
        self.assertEqual(export.loc[0, "ShippingProfileName"], "Free Shipping Policy")
        self.assertEqual(export.loc[0, "Original StartPrice"], "100.00")
        self.assertEqual(export.loc[0, "Shipping Transfer Markup USD"], "1.28")
        self.assertEqual(export.loc[0, "Shipping Transfer USD"], "26.85")
        self.assertEqual(export.loc[0, "Adjusted StartPrice"], "126.85")
        self.assertEqual(export.loc[0, "Original ShippingProfileName"], "200-300 eBay SpeedPAK Economy US")
        self.assertEqual(export.loc[0, "Applied ShippingProfileName"], "Free Shipping Policy")
        self.assertEqual(export.loc[0, "Free Shipping Rollup Status"], "applied")

    def test_build_export_dataframe_preserves_price_and_policy_when_rollup_disabled(self):
        frame = pd.DataFrame(
            [
                {
                    "StartPrice": "100.00",
                    "ShippingProfileName": "200-300 eBay SpeedPAK Economy US",
                    "FICP Shipping USD": "25.57",
                }
            ]
        )
        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))
        self.assertEqual(export.loc[0, "StartPrice"], "100.00")
        self.assertEqual(export.loc[0, "ShippingProfileName"], "200-300 eBay SpeedPAK Economy US")
        self.assertNotIn("Free Shipping Rollup Status", export.columns)

    def test_build_export_dataframe_maps_structured_source_condition(self):
        frame = pd.DataFrame(
            [
                {
                    "Category": "259109",
                    "ConditionID": "3000",
                    "Source Listing Condition": "新品、未使用",
                    "Title": "Brand-new manga set",
                },
                {
                    "Category": "259109",
                    "ConditionID": "3000",
                    "Source Listing Condition": "未使用に近い",
                    "Title": "Like-new manga",
                },
                {
                    "Category": "259111",
                    "ConditionID": "3000",
                    "Source Listing Condition": "やや傷や汚れあり",
                    "Title": "Used manga",
                },
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "ConditionID"], "1000")
        self.assertEqual(export.loc[0, "Original ConditionID"], "3000")
        self.assertEqual(export.loc[0, "Applied ConditionID"], "1000")
        self.assertEqual(export.loc[0, "Applied Condition Name"], "Brand New")
        self.assertIn("新品、未使用", export.loc[0, "ConditionID Fix Status"])
        self.assertEqual(export.loc[1, "ConditionID"], "2750")
        self.assertEqual(export.loc[1, "Applied Condition Name"], "Like New")
        self.assertEqual(export.loc[2, "ConditionID"], "5000")
        self.assertEqual(export.loc[2, "Applied Condition Name"], "Good")

    def test_build_export_dataframe_maps_all_supported_used_states(self):
        cases = [
            ("目立った傷や汚れなし", "4000", "Very Good"),
            ("傷や汚れあり", "6000", "Acceptable"),
            ("全体的に状態が悪い", "6000", "Acceptable"),
        ]
        for source_condition, expected_id, expected_name in cases:
            with self.subTest(source_condition=source_condition):
                frame = pd.DataFrame(
                    [
                        {
                            "Category": "259109",
                            "ConditionID": "3000",
                            "Source Listing Condition": source_condition,
                        }
                    ]
                )
                export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))
                self.assertEqual(export.loc[0, "ConditionID"], expected_id)
                self.assertEqual(export.loc[0, "Applied Condition Name"], expected_name)

    def test_condition_policy_uses_structured_state_not_new_words_in_description(self):
        frame = pd.DataFrame(
            [
                {
                    "Category": "259109",
                    "ConditionID": "3000",
                    "Source Listing Condition": "目立った傷や汚れなし",
                    "Source Listing Description": "新刊5巻です。届いたばかりです。",
                    "AI Description Notes": "Set is new and unused.",
                },
                {
                    "Category": "259109",
                    "ConditionID": "1000",
                    "Source Listing Description": "新品で購入した中古本です。",
                    "AI Description Notes": "Brand new.",
                },
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "ConditionID"], "4000")
        self.assertEqual(export.loc[1, "ConditionID"], "4000")
        self.assertIn("source condition unavailable", export.loc[1, "Source Condition Mapping Status"])

    def test_condition_policy_blocks_brand_new_when_source_details_show_use(self):
        decision = decide_manga_export_condition(
            category="259109",
            source_condition="新品、未使用",
            description="新品で購入後、一読しました。",
        )

        self.assertEqual(decision.condition_id, "4000")
        self.assertEqual(decision.condition_name, "Very Good")
        self.assertIn("safety override", decision.status)

    def test_condition_policy_does_not_downgrade_negated_damage_or_use(self):
        negative_descriptions = [
            "書き込みはありません。汚れはありません。",
            "折れ、欠品、日焼け、破れはありません。",
            "一読もしていません。",
            "開封済みではありません。",
            "No scratches, stains, damage, wear, yellowing, or missing pages.",
            "Not opened and never read.",
        ]
        for description in negative_descriptions:
            with self.subTest(description=description):
                decision = decide_manga_export_condition(
                    category="259109",
                    source_condition="新品、未使用",
                    description=description,
                )
                self.assertEqual(decision.condition_id, "1000")
                self.assertEqual(decision.condition_name, "Brand New")

    def test_condition_policy_only_maps_verified_manga_categories(self):
        frame = pd.DataFrame(
            [
                {
                    "Category": "12345",
                    "ConditionID": "1000",
                    "Source Listing Condition": "新品、未使用",
                }
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "ConditionID"], "4000")
        self.assertIn("outside verified manga", export.loc[0, "Source Condition Mapping Status"])

    def test_export_condition_policy_is_idempotent(self):
        frame = pd.DataFrame(
            [
                {
                    "Category": "259109",
                    "ConditionID": "3000",
                    "Source Listing Condition": "新品、未使用",
                }
            ]
        )

        first = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))
        second = build_export_dataframe(first, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(first.loc[0, "ConditionID"], "1000")
        self.assertEqual(second.loc[0, "ConditionID"], "1000")
        self.assertEqual(first.loc[0, "Original ConditionID"], "3000")
        self.assertEqual(second.loc[0, "Original ConditionID"], "3000")
        self.assertEqual(first.loc[0, "ConditionID Fix Status"], second.loc[0, "ConditionID Fix Status"])

    def test_build_export_dataframe_adds_condition_id_when_missing(self):
        frame = pd.DataFrame([{"Title": "Manga set"}])

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "ConditionID"], "4000")
        self.assertEqual(export.loc[0, "Applied ConditionID"], "4000")
        self.assertIn("Very Good", export.loc[0, "ConditionID Fix Status"])

    def test_build_export_dataframe_clears_unit_price_display_fields(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "Manga set",
                    "Detected Book Count": "17",
                    "C:Unit Quantity": "17",
                    "C:Unit Type": "NA",
                }
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "C:Unit Quantity"], "")
        self.assertEqual(export.loc[0, "C:Unit Type"], "")
        self.assertEqual(export.loc[0, "Original Unit Quantity"], "17")
        self.assertEqual(export.loc[0, "Original Unit Type"], "NA")
        self.assertIn("cleared", export.loc[0, "Unit Type Fix Status"])

    def test_build_export_dataframe_keeps_unit_price_fields_blank(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "Manga set",
                    "Detected Book Count": "8",
                    "C:Unit Quantity": "NA",
                    "C:Unit Type": "NA",
                }
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "C:Unit Quantity"], "")
        self.assertEqual(export.loc[0, "C:Unit Type"], "")
        self.assertIn("kept blank", export.loc[0, "Unit Type Fix Status"])

    def test_build_export_dataframe_writes_all_source_images_to_picurl(self):
        frame = pd.DataFrame(
            [
                {
                    "PicURL": "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg?aaa",
                    "Main Image URL": "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg?aaa",
                    "Source Image URLs": (
                        "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg?aaa|"
                        "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg?aaa|"
                        "https://static.mercdn.net/item/detail/orig/photos/m111_3.jpg?aaa"
                    ),
                }
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(
            export.loc[0, "PicURL"],
            (
                "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg?aaa|"
                "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg?aaa|"
                "https://static.mercdn.net/item/detail/orig/photos/m111_3.jpg?aaa"
            ),
        )
        self.assertEqual(export.loc[0, "Original PicURL"], "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg?aaa")
        self.assertEqual(export.loc[0, "Applied PicURL Image Count"], "3")
        self.assertEqual(export.loc[0, "PicURL Export Status"], "applied: 3 images")

    def test_build_export_dataframe_excludes_needs_review_rows(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "OK row",
                    "Listing Eligibility": "OK",
                    "Processing Result": "成功",
                    "Needs Review": "No",
                },
                {
                    "Title": "Needs review result",
                    "Listing Eligibility": "OK",
                    "Processing Result": "確認必要",
                    "Needs Review": "Yes",
                },
                {
                    "Title": "Needs review flag only",
                    "Listing Eligibility": "OK",
                    "Processing Result": "成功",
                    "Needs Review": "Yes",
                },
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(len(export), 1)
        self.assertEqual(export.iloc[0]["Title"], "OK row")

    def test_diagnose_processed_row_keeps_browser_fetch_warning_when_shipping_ready(self):
        row = pd.Series(
            {
                "Title": "Manga Set Volumes 1-10",
                "Listing Eligibility": "OK",
                "Scrape Status": "ok; browser fetch failed: Page.goto timeout",
                "Detected Book Count": "10",
                "Book Count Evidence": "Volumes 1-10",
                "Billable Weight kg": "2.100",
                "FICP Shipping USD": "26.69",
                "FICP Shipping JPY": "4319",
                "Main Image URL": "https://example.com/image.jpg",
                "AI Enrichment Status": "parse error: Extra data: line 2 column 1",
            }
        )

        diagnostics = diagnose_processed_row(row)

        self.assertEqual(diagnostics["result"], "成功")
        self.assertEqual(diagnostics["needs_review"], "No")
        self.assertIn("ブラウザ取得は失敗", diagnostics["diagnostics"])
        self.assertIn("AI補完は任意処理", diagnostics["diagnostics"])

    def test_extract_json_object_uses_first_balanced_object(self):
        raw = '{"description_notes":["ok"]}\n{"extra": true}'

        self.assertEqual(extract_json_object(raw), '{"description_notes":["ok"]}')

    def test_parse_ai_enrichment_payload_accepts_json_with_trailing_text(self):
        raw = (
            '{"book_count":null,"description_notes":["Unread condition."],'
            '"specifics":{"C:Genre":"Sports"},"notes":["genre evidence"]}'
            '\n{"unused": true}'
        )

        result = parse_ai_enrichment_payload(raw, "gemini", "gemini-test", ["C:Genre"])

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.description_notes, ["Unread condition."])
        self.assertEqual(result.specifics["C:Genre"], "Sports")

    def test_ebay_preflight_table_flags_common_upload_risks(self):
        source = pd.DataFrame(
            [
                {
                    "Title": "Good manga set",
                    "PicURL": "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg",
                    "Source Image URLs": (
                        "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg|"
                        "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg"
                    ),
                    "Category": "259109",
                    "ConditionID": "3000",
                    "StartPrice": "50.00",
                    "ShippingProfileName": "Free Shipping Policy Fedex",
                    "Description": "desc",
                    "C:Character": "Short",
                    "FICP Shipping USD": "20.00",
                },
                {
                    "Title": "X" * 81,
                    "PicURL": "",
                    "Category": "",
                    "ConditionID": "",
                    "StartPrice": "not price",
                    "ShippingProfileName": "",
                    "Description": "",
                    "C:Character": "A" * 66,
                    "FICP Shipping USD": "",
                },
                {
                    "Title": "Excluded item",
                    "Listing Eligibility": "Excluded",
                },
            ]
        )
        export = build_export_dataframe(source, FreeShippingRollupOptions(enabled=False))

        table = build_ebay_preflight_table(source, export, "Title")

        self.assertEqual(table.loc[0, "Status"], "OK")
        self.assertEqual(table.loc[0, "Images"], "2")
        self.assertEqual(table.loc[0, "ConditionID"], "4000")
        self.assertEqual(table.loc[1, "Status"], "要修正")
        self.assertIn("画像URLなし", table.loc[1, "Issues"])
        self.assertIn("Titleが80文字超過", table.loc[1, "Issues"])
        self.assertIn("Specifics 65文字超過", table.loc[1, "Issues"])
        self.assertEqual(table.iloc[-1]["Status"], "除外済み")

    def test_ebay_preflight_accepts_mapped_manga_condition_ids(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": f"Manga {index}",
                    "PicURL": (
                        "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg|"
                        "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg"
                    ),
                    "Category": "259109",
                    "ConditionID": "3000",
                    "Source Listing Condition": source_condition,
                    "StartPrice": "50.00",
                    "ShippingProfileName": "Free Shipping Policy Fedex",
                    "Description": "desc",
                }
                for index, source_condition in enumerate(
                    [
                        "新品、未使用",
                        "未使用に近い",
                        "目立った傷や汚れなし",
                        "やや傷や汚れあり",
                        "傷や汚れあり",
                    ],
                    start=1,
                )
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))
        table = build_ebay_preflight_table(frame, export, "Title")

        self.assertEqual(export["ConditionID"].tolist(), ["1000", "2750", "4000", "5000", "6000"])
        self.assertTrue((table["Issues"] == "-").all())
        self.assertEqual(table["Condition"].tolist(), ["Brand New", "Like New", "Very Good", "Good", "Acceptable"])

    def test_ebay_preflight_warns_for_poor_source_condition(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "Worn Manga Volumes 1-2 Set",
                    "PicURL": (
                        "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg|"
                        "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg"
                    ),
                    "Category": "259109",
                    "ConditionID": "3000",
                    "Source Listing Condition": "全体的に状態が悪い",
                    "StartPrice": "20.00",
                    "ShippingProfileName": "Free Shipping Policy Fedex",
                    "Description": "desc",
                }
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))
        table = build_ebay_preflight_table(frame, export, "Title")

        self.assertEqual(export.loc[0, "ConditionID"], "6000")
        self.assertEqual(table.loc[0, "Status"], "注意")
        self.assertIn("欠損ページ", table.loc[0, "Warnings"])

    def test_ebay_preflight_positions_keep_source_rows_after_exclusion(self):
        source = pd.DataFrame(
            [
                {
                    "Title": "First manga",
                    "PicURL": "https://example.com/first.jpg",
                    "Category": "259109",
                    "ConditionID": "4000",
                    "StartPrice": "40.00",
                    "ShippingProfileName": "Free Shipping Policy Fedex",
                    "Description": "desc",
                },
                {"Title": "Excluded manga", "Listing Eligibility": "Excluded"},
                {
                    "Title": "Third manga",
                    "PicURL": "https://example.com/third.jpg",
                    "Category": "259109",
                    "ConditionID": "4000",
                    "StartPrice": "60.00",
                    "ShippingProfileName": "Free Shipping Policy Fedex",
                    "Description": "desc",
                },
            ]
        )

        export = build_export_dataframe(source, FreeShippingRollupOptions(enabled=False))
        table = build_ebay_preflight_table(source, export, "Title")
        target_rows = table[table["Status"] != "除外済み"]

        self.assertEqual(target_rows["Position"].tolist(), ["0", "2"])
        self.assertEqual(target_rows["No"].tolist(), ["1", "3"])

    def test_preflight_native_selection_maps_visible_row_to_source_position(self):
        visible_table = pd.DataFrame(
            [
                {"Position": "0", "Title": "First"},
                {"Position": "2", "Title": "Third"},
            ]
        )

        self.assertEqual(resolve_preflight_selected_position(visible_table, [[0, "Image"]]), 0)
        self.assertEqual(resolve_preflight_selected_position(visible_table, [[1, "Title"]]), 2)
        self.assertIsNone(resolve_preflight_selected_position(visible_table, []))
        self.assertIsNone(resolve_preflight_selected_position(visible_table, [[2, "Title"]]))
        self.assertIsNone(resolve_preflight_selected_position(visible_table, [["invalid", "Title"]]))

    def test_preflight_native_selection_rejects_blank_source_position(self):
        table = pd.DataFrame([{"Position": "", "Title": "Summary"}])

        self.assertIsNone(resolve_preflight_selected_position(table, [[0, "Title"]]))

    def test_pending_preflight_selection_opens_selected_product_before_radio_render(self):
        fake_st = FakeStreamlit()
        fake_st.session_state[PREFLIGHT_PENDING_SELECTION_KEY] = 2
        fake_st.session_state["selected"] = 0
        fake_st.session_state["view"] = "投入前チェック"

        apply_query_selected_row(fake_st, [0, 1, 2], "selected", "view")

        self.assertEqual(fake_st.session_state["selected"], 2)
        self.assertEqual(fake_st.session_state["view"], "選択商品")
        self.assertNotIn(PREFLIGHT_PENDING_SELECTION_KEY, fake_st.session_state)

    def test_native_product_selection_uses_session_state_without_browser_navigation(self):
        fake_st = FakeStreamlit()
        fake_st.dataframe = Mock(return_value={"selection": {"cells": [[1, "Title"]]}})
        fake_st.rerun = Mock()
        mapping_table = pd.DataFrame(
            [
                {"Position": "0", "Title": "First"},
                {"Position": "2", "Title": "Third"},
            ]
        )

        render_product_selection_dataframe(
            fake_st,
            mapping_table,
            mapping_table[["Title"]],
            key="test_selector",
            column_config={},
        )

        self.assertEqual(fake_st.session_state[PREFLIGHT_PENDING_SELECTION_KEY], 2)
        fake_st.rerun.assert_called_once_with()
        self.assertEqual(fake_st.dataframe.call_args.kwargs["selection_mode"], "single-cell")
        self.assertEqual(fake_st.dataframe.call_args.kwargs["on_select"], "rerun")

    def test_native_product_selection_does_not_rerun_without_valid_selection(self):
        mapping_table = pd.DataFrame([{"Position": "0", "Title": "First"}])
        for selected_cells in ([], [[2, "Title"]], [["invalid", "Title"]]):
            with self.subTest(selected_cells=selected_cells):
                fake_st = FakeStreamlit()
                fake_st.dataframe = Mock(return_value={"selection": {"cells": selected_cells}})
                fake_st.rerun = Mock()

                render_product_selection_dataframe(
                    fake_st,
                    mapping_table,
                    mapping_table[["Title"]],
                    key="test_selector",
                    column_config={},
                )

                self.assertNotIn(PREFLIGHT_PENDING_SELECTION_KEY, fake_st.session_state)
                fake_st.rerun.assert_not_called()

    def test_preflight_uses_native_selection_and_large_rows_without_query_links(self):
        source = (ROOT / "comic_ficp_streamlit_app.py").read_text(encoding="utf-8")

        self.assertIn('selection_mode="single-cell"', source)
        self.assertIn("row_height=REVIEW_TABLE_ROW_HEIGHT_PX", source)
        self.assertIn('"画像（クリックで詳細）"', source)
        self.assertIn('"Title（クリックで商品詳細）"', source)
        self.assertNotIn("build_clickable_preflight_row_html", source)

    def test_all_product_lists_use_session_safe_native_selection(self):
        source = (ROOT / "comic_ficp_streamlit_app.py").read_text(encoding="utf-8")

        for widget_key in (
            "comic_ficp_preflight_selector",
            "comic_ficp_review_selector",
            "comic_ficp_diagnostic_selector_",
            "comic_ficp_exclusion_selector",
        ):
            self.assertIn(widget_key, source)
        self.assertNotIn("def build_select_product_href", source)
        self.assertNotIn("build_clickable_review_row_html", source)
        self.assertNotIn("build_clickable_diagnostic_row_html", source)
        self.assertNotIn("build_clickable_exclusion_row_html", source)
        self.assertNotIn('href="?comic_ficp_select=', source)

    def test_review_diagnostic_and_exclusion_tables_preserve_source_positions(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "First manga",
                    "Processing Result": "成功",
                    "Needs Review": "No",
                    "Listing Eligibility": "OK",
                },
                {
                    "Title": "Excluded manga",
                    "Processing Result": "出品除外",
                    "Needs Review": "Yes",
                    "Listing Eligibility": "Excluded",
                    "Exclusion Reason": "Missing volume",
                },
                {
                    "Title": "Third manga",
                    "Processing Result": "成功",
                    "Needs Review": "No",
                    "Listing Eligibility": "OK",
                },
            ],
            index=[10, 20, 30],
        )

        review_table = build_review_table(frame, "Title", "Product URL")
        diagnostic_table = build_processing_diagnostic_table(frame, "Title", "Product URL")
        exclusion_table = build_exclusion_table(frame, "Title", "Product URL")

        self.assertEqual(review_table["Position"].tolist(), ["0", "1", "2"])
        self.assertEqual(diagnostic_table["Position"].tolist(), ["0", "1", "2"])
        self.assertEqual(exclusion_table["Position"].tolist(), ["1"])
        self.assertEqual(resolve_preflight_selected_position(exclusion_table, [[0, "Title"]]), 1)

    def test_build_export_dataframe_rollup_skips_bad_price_or_missing_shipping(self):
        frame = pd.DataFrame(
            [
                {"StartPrice": "not a price", "ShippingProfileName": "Old", "FICP Shipping USD": "20.00"},
                {"StartPrice": "50.00", "ShippingProfileName": "Old", "FICP Shipping USD": ""},
            ]
        )
        export = build_export_dataframe(
            frame,
            FreeShippingRollupOptions(enabled=True, price_col="StartPrice", shipping_profile_col="ShippingProfileName"),
        )
        self.assertEqual(export.loc[0, "StartPrice"], "not a price")
        self.assertEqual(export.loc[0, "ShippingProfileName"], "Old")
        self.assertEqual(export.loc[0, "Free Shipping Rollup Status"], "skipped: StartPrice is not numeric")
        self.assertEqual(export.loc[1, "StartPrice"], "50.00")
        self.assertEqual(export.loc[1, "ShippingProfileName"], "Old")
        self.assertEqual(export.loc[1, "Free Shipping Rollup Status"], "skipped: FICP Shipping USD is missing")

    def test_trial_export_contains_only_the_processed_batch_and_keeps_safety_exclusions(self):
        frame = pd.DataFrame(
            [
                {"Title": "Trial ready", "Listing Eligibility": "OK", "Needs Review": "No"},
                {"Title": "Trial review", "Listing Eligibility": "OK", "Needs Review": "Yes"},
                {"Title": "Trial excluded", "Listing Eligibility": "Excluded", "Needs Review": "No"},
                {"Title": "Trial ready second", "Listing Eligibility": "OK", "Needs Review": "No"},
                {"Title": "Outside the trial", "Listing Eligibility": "OK", "Needs Review": "No"},
            ],
            index=[10, 20, 30, 40, 50],
        )

        export = build_trial_export_dataframe(
            frame,
            [10, 20, 30, 40],
            FreeShippingRollupOptions(enabled=False),
        )

        self.assertEqual(export["Title"].tolist(), ["Trial ready", "Trial ready second"])
        self.assertNotIn("Outside the trial", export["Title"].tolist())

    def test_trial_download_panel_exposes_a_csv_download_for_the_processed_batch(self):
        from streamlit.testing.v1 import AppTest

        script = '''
import pandas as pd
import streamlit as st
from comic_ficp_streamlit_app import render_trial_download_panel

render_trial_download_panel(
    st,
    pd.DataFrame([{"Title": "Trial ready"}]),
    b"Title\\nTrial ready\\n",
    "ebay-comic-ficp-trial-5items.csv",
    5,
)
'''
        app = AppTest.from_string(script, default_timeout=30).run()

        self.assertEqual(0, len(app.exception))
        self.assertEqual(1, len(app.get("download_button")))
        self.assertEqual(app.get("download_button")[0].label, "試した5件のeBay用CSVを保存する")

    @unittest.skipIf(os.name != "nt", "Windows DPAPI storage is only available on Windows")
    def test_saved_api_key_round_trip_uses_encrypted_local_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store_path = Path(temp_dir) / "api_keys.json"
            with patch("comic_ficp_streamlit_app.API_KEY_STORE_PATH", store_path):
                saved, message = save_api_key("Gemini", "test-secret-key")
                self.assertTrue(saved, message)
                self.assertTrue(saved_api_key_exists("gemini"))
                self.assertEqual(load_saved_api_key("gemini"), "test-secret-key")
                self.assertNotIn("test-secret-key", store_path.read_text(encoding="utf-8"))

                deleted, message = delete_saved_api_key("gemini")
                self.assertTrue(deleted, message)
                self.assertFalse(saved_api_key_exists("gemini"))
                self.assertEqual(load_saved_api_key("gemini"), "")

    def test_public_user_auth_and_api_key_storage_are_isolated_and_encrypted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_url = f"sqlite:///{Path(temp_dir) / 'public.sqlite3'}"
            secret = "unit-test-encryption-secret"

            created_a, message_a = create_public_user("seller_a", "password-one", db_url)
            created_b, message_b = create_public_user("seller_b", "password-two", db_url)
            self.assertTrue(created_a, message_a)
            self.assertTrue(created_b, message_b)

            authed_a, user_a, message = authenticate_public_user("seller_a", "password-one", db_url)
            authed_b, user_b, _ = authenticate_public_user("seller_b", "password-two", db_url)
            self.assertTrue(authed_a, message)
            self.assertTrue(authed_b)
            self.assertNotEqual(user_a["id"], user_b["id"])

            saved, save_message = save_public_api_key(user_a["id"], "Gemini", "test-public-secret-key", db_url, secret)
            self.assertTrue(saved, save_message)
            self.assertTrue(public_saved_api_key_exists(user_a["id"], "gemini", db_url))
            self.assertFalse(public_saved_api_key_exists(user_b["id"], "gemini", db_url))
            self.assertEqual(load_public_saved_api_key(user_a["id"], "gemini", db_url, secret), "test-public-secret-key")
            self.assertEqual(load_public_saved_api_key(user_b["id"], "gemini", db_url, secret), "")
            self.assertNotIn("test-public-secret-key", (Path(temp_dir) / "public.sqlite3").read_bytes().decode("latin1"))

            deleted, delete_message = delete_public_saved_api_key(user_a["id"], "gemini", db_url)
            self.assertTrue(deleted, delete_message)
            self.assertFalse(public_saved_api_key_exists(user_a["id"], "gemini", db_url))

    def test_public_remember_token_restores_user_without_storing_raw_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "public.sqlite3"
            db_url = f"sqlite:///{db_path}"
            created, message = create_public_user("seller_a", "password-one", db_url)
            self.assertTrue(created, message)
            authed, user, auth_message = authenticate_public_user("seller_a", "password-one", db_url)
            self.assertTrue(authed, auth_message)

            token = create_public_remember_token(user["id"], db_url, now=1000.0, days=30)
            self.assertTrue(is_plausible_public_remember_token(token))
            restored, restored_user, restored_message = authenticate_public_remember_token(token, db_url, now=1200.0)

            self.assertTrue(restored, restored_message)
            self.assertEqual(restored_user, user)
            self.assertNotIn(token.encode("utf-8"), db_path.read_bytes())

    def test_public_remember_token_expires_and_current_device_can_be_revoked_alone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_url = f"sqlite:///{Path(temp_dir) / 'public.sqlite3'}"
            created, message = create_public_user("seller_a", "password-one", db_url)
            self.assertTrue(created, message)
            authed, user, auth_message = authenticate_public_user("seller_a", "password-one", db_url)
            self.assertTrue(authed, auth_message)

            first_device = create_public_remember_token(user["id"], db_url, now=1000.0, days=30)
            second_device = create_public_remember_token(user["id"], db_url, now=1001.0, days=30)
            self.assertEqual(delete_public_remember_token(first_device, db_url), 1)
            self.assertFalse(authenticate_public_remember_token(first_device, db_url, now=1200.0)[0])
            self.assertTrue(authenticate_public_remember_token(second_device, db_url, now=1200.0)[0])

            expiring = create_public_remember_token(user["id"], db_url, now=2000.0, days=1)
            self.assertFalse(authenticate_public_remember_token(expiring, db_url, now=2000.0 + 24 * 60 * 60)[0])

    def test_public_logout_can_revoke_all_tokens_for_the_account(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_url = f"sqlite:///{Path(temp_dir) / 'public.sqlite3'}"
            self.assertTrue(create_public_user("seller_a", "password-one", db_url)[0])
            user = authenticate_public_user("seller_a", "password-one", db_url)[1]
            first_device = create_public_remember_token(user["id"], db_url, now=1000.0)
            second_device = create_public_remember_token(user["id"], db_url, now=1001.0)

            self.assertEqual(delete_public_remember_tokens_for_user(user["id"], db_url), 2)
            self.assertFalse(authenticate_public_remember_token(first_device, db_url, now=1002.0)[0])
            self.assertFalse(authenticate_public_remember_token(second_device, db_url, now=1002.0)[0])

    def test_public_remember_token_rejects_malformed_or_cross_account_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_url = f"sqlite:///{Path(temp_dir) / 'public.sqlite3'}"
            self.assertFalse(authenticate_public_remember_token("too-short", db_url)[0])
            self.assertFalse(authenticate_public_remember_token("!" * 64, db_url)[0])

            self.assertTrue(create_public_user("seller_a", "password-one", db_url)[0])
            self.assertTrue(create_public_user("seller_b", "password-two", db_url)[0])
            user_a = authenticate_public_user("seller_a", "password-one", db_url)[1]
            token_a = create_public_remember_token(user_a["id"], db_url, now=1000.0)
            restored, restored_user, restored_message = authenticate_public_remember_token(token_a, db_url, now=1001.0)
            self.assertTrue(restored, restored_message)
            self.assertEqual(restored_user["username"], "seller_a")
            self.assertNotEqual(restored_user["username"], "seller_b")

    def test_public_remember_cookie_uses_secure_attributes_without_query_parameter(self):
        token = "A" * 64
        script = build_public_remember_cookie_script(token)

        self.assertIn(PUBLIC_REMEMBER_COOKIE_NAME, script)
        self.assertIn("Max-Age=", script)
        self.assertIn("Path=/", script)
        self.assertIn("SameSite=Strict", script)
        self.assertIn("; Secure", script)
        self.assertNotIn("query", script.lower())
        self.assertNotIn("searchParams", script)
        self.assertNotIn("location.replace", script)

        clear_script = build_public_remember_cookie_script(clear_cookie=True)
        self.assertIn("Max-Age=0", clear_script)
        self.assertIn("Thu, 01 Jan 1970", clear_script)

    def test_public_remember_cookie_renderer_uses_positive_iframe_size(self):
        with patch("streamlit.iframe", create=True) as iframe:
            render_public_remember_cookie_script("A" * 64)

        iframe.assert_called_once()
        self.assertEqual(iframe.call_args.kwargs["height"], 1)
        self.assertEqual(iframe.call_args.kwargs["width"], 1)

    def test_public_remember_cookie_restores_user_and_clears_old_workspace_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_url = f"sqlite:///{Path(temp_dir) / 'public.sqlite3'}"
            self.assertTrue(create_public_user("seller_a", "password-one", db_url)[0])
            user = authenticate_public_user("seller_a", "password-one", db_url)[1]
            token = create_public_remember_token(user["id"], db_url)
            fake_st = FakeStreamlit(cookies={PUBLIC_REMEMBER_COOKIE_NAME: token})
            fake_st.session_state["comic_ficp_processed_df"] = pd.DataFrame([{"Title": "stale"}])
            fake_st.session_state["unrelated"] = "keep"

            restored_user = restore_public_user_from_remember_cookie(fake_st, db_url)

            self.assertEqual(restored_user, user)
            self.assertEqual(fake_st.session_state[PUBLIC_SESSION_USER_KEY], user)
            self.assertRegex(fake_st.session_state[PUBLIC_ACTIVE_REMEMBER_TOKEN_HASH_KEY], r"^[0-9a-f]{64}$")
            self.assertNotIn("comic_ficp_processed_df", fake_st.session_state)
            self.assertEqual(fake_st.session_state["unrelated"], "keep")

    def test_invalid_public_remember_cookie_is_blocked_and_scheduled_for_deletion(self):
        fake_st = FakeStreamlit(cookies={PUBLIC_REMEMBER_COOKIE_NAME: "invalid"})
        with patch("comic_ficp_streamlit_app.render_public_remember_cookie_script") as render_cookie:
            restored_user = restore_public_user_from_remember_cookie(fake_st, "sqlite:///:memory:")

        self.assertIsNone(restored_user)
        self.assertTrue(fake_st.session_state[PUBLIC_REMEMBER_RESTORE_BLOCKED_KEY])
        render_cookie.assert_called_once_with(clear_cookie=True)

    def test_public_mode_disables_disk_csv_and_processed_dataframe_cache(self):
        fake_st = FakeStreamlit(query_params={"comic_ficp_select": "1"})
        raw = b"Title,PicURL\nNo Disk,https://example.com/image.jpg\n"
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"COMIC_FICP_PUBLIC_MODE": "1"}):
            raw_path = Path(temp_dir) / "last_uploaded_csv.bin"
            meta_path = Path(temp_dir) / "last_uploaded_csv.json"
            df_path = Path(temp_dir) / "last_processed_dataframe.pkl"
            df_meta_path = Path(temp_dir) / "last_processed_dataframe.json"
            with patch("comic_ficp_streamlit_app.UPLOAD_CACHE_RAW_PATH", raw_path), patch(
                "comic_ficp_streamlit_app.UPLOAD_CACHE_META_PATH", meta_path
            ), patch("comic_ficp_streamlit_app.PROCESSED_CACHE_DF_PATH", df_path), patch(
                "comic_ficp_streamlit_app.PROCESSED_CACHE_META_PATH", df_meta_path
            ):
                save_uploaded_csv_cache(raw, "items.csv")
                self.assertFalse(raw_path.exists())
                restored_raw, restored_name, restored_cached = get_uploaded_or_cached_csv(fake_st, None)
                self.assertEqual(restored_raw, b"")
                self.assertEqual(restored_name, "")
                self.assertFalse(restored_cached)

                save_processed_dataframe_cache(pd.DataFrame([{"Title": "No Disk"}]), "items.csv:test")
                self.assertFalse(df_path.exists())
                self.assertIsNone(load_processed_dataframe_cache("items.csv:test"))

    def test_detect_book_count_patterns(self):
        cases = [
            ("1〜20巻セット", 20),
            ("1-20巻", 20),
            ("完結セット(全5巻)", 5),
            ("10冊セット", 10),
            ("コミック全23巻", 23),
            ("Volumes 1-16 Set", 16),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                count, evidence = detect_book_count(text)
                self.assertEqual(count, expected)
                self.assertTrue(evidence)

    def test_detect_book_count_unknown(self):
        count, evidence = detect_book_count("単巻 コミック")
        self.assertIsNone(count)
        self.assertEqual(evidence, "")

    def test_detect_book_count_uses_known_complete_series_reference(self):
        count, evidence = detect_book_count_with_references("Banana Fish Reprint Edition - Complete Set")
        self.assertEqual(count, 19)
        self.assertIn("Banana Fish", evidence)

    def test_detect_book_count_reference_does_not_guess_without_complete_claim(self):
        count, evidence = detect_book_count_with_references("BANANA FISH Reprint BOX vol.1 Banana Fish")
        self.assertIsNone(count)
        self.assertEqual(evidence, "")

    def test_detect_book_count_limit_issue(self):
        disabled = detect_book_count_limit_issue(60, 0)
        self.assertFalse(disabled.excluded)

        within_limit = detect_book_count_limit_issue(40, 40)
        self.assertFalse(within_limit.excluded)

        over_limit = detect_book_count_limit_issue(41, 40)
        self.assertTrue(over_limit.excluded)
        self.assertEqual(over_limit.reason, "Book count exceeds export limit")
        self.assertIn("41 books", over_limit.evidence)
        self.assertIn("40 books", over_limit.evidence)

    def test_detect_unlistable_listing_issue_for_missing_volume(self):
        issue = detect_unlistable_listing_issue(
            "累・かさね セット 1-14巻",
            "なぜか12かんだけありませんがその分お安くしております。",
        )
        self.assertTrue(issue.excluded)
        self.assertIn("欠巻", issue.reason)
        self.assertIn("12かんだけありません", issue.evidence)

    def test_detect_unlistable_listing_issue_ignores_accessory_absence(self):
        issue = detect_unlistable_listing_issue(
            "新品未読です。シュリンクは付いていません。帯なしです。応募券はありません。"
        )
        self.assertFalse(issue.excluded)

    def test_detect_unlistable_listing_issue_ignores_wrong_order_reason(self):
        issue = detect_unlistable_listing_issue(
            "横山光輝による歴史漫画「史記」の愛蔵版全5巻セットで、中国の歴史ドラマを重厚な筆致で描いた作品です。"
            "新品で購入したばかりで、一読もしておりません。誤発注してしまったため、こちらに出品させて頂きます。"
        )
        self.assertFalse(issue.excluded)

    def test_detect_unlistable_listing_issue_catches_explicit_missing_volume(self):
        issue = detect_unlistable_listing_issue("全14巻セットですが、12巻がありません。")
        self.assertTrue(issue.excluded)
        self.assertIn("12巻がありません", issue.evidence)

    def test_detect_magazine_listing_issue_excludes_clear_magazine_items(self):
        samples = [
            "週刊少年ジャンプ 2024年12号",
            "週刊ヤングマガジン 2023年 45号 セット",
            "ジャンプ本誌 合併号",
            "月刊少年ガンガン 5月号",
        ]

        for text in samples:
            with self.subTest(text=text):
                issue = detect_magazine_listing_issue(text)
                self.assertTrue(issue.excluded)
                self.assertEqual(issue.reason, "雑誌・本誌商品の可能性があるため出品除外")
                self.assertTrue(issue.evidence)

    def test_detect_magazine_listing_issue_allows_comic_imprint_context(self):
        samples = [
            "ONE PIECE Jump Comics Volumes 1-10 Set",
            "ヤングマガジン ヤンマガKC 全10巻セット",
            "週刊少年ジャンプ連載作品 鬼滅の刃 全巻セット",
            "本・雑誌・漫画 > 漫画 > 全巻セット",
        ]

        for text in samples:
            with self.subTest(text=text):
                self.assertFalse(detect_magazine_listing_issue(text).excluded)

    def test_book_weight_estimation_by_series_and_imprint(self):
        jump = estimate_book_weight_g("ONE PIECE Jump Comics Volumes 1-10 Set", 180)
        self.assertEqual(jump.weight_g, 180)
        self.assertIn("shonen", jump.evidence.lower())

        young_magazine = estimate_book_weight_g("ヤングマガジン ヤンマガKC 全10巻セット", 180)
        self.assertEqual(young_magazine.weight_g, 220)
        self.assertIn("seinen", young_magazine.evidence.lower())

        large = estimate_book_weight_g("DRAGON BALL 完全版 Complete Edition 全34巻", 180)
        self.assertEqual(large.weight_g, 320)
        self.assertIn("large", large.evidence)

        fallback = estimate_book_weight_g("Unknown manga set 全3巻", 190)
        self.assertEqual(fallback.weight_g, 190)
        self.assertIn("fallback", fallback.evidence)

    def test_packaging_weight_estimation_includes_materials(self):
        small = estimate_packaging_weight_kg(3, 22.2, 16.8, 8.8, 0.2)
        self.assertEqual(small.weight_kg, 0.18)
        self.assertIn("bubble wrap", small.materials)
        self.assertIn("cardboard", small.materials)
        self.assertIn("paper filler", small.materials)

        medium = estimate_packaging_weight_kg(12, 22.2, 16.8, 23.2, 0.2)
        self.assertEqual(medium.weight_kg, 0.35)
        self.assertIn("12 books", medium.evidence)

        heavy = estimate_packaging_weight_kg(45, 22.2, 16.8, 76.0, 0.2)
        self.assertGreaterEqual(heavy.weight_kg, 0.90)
        self.assertIn("reinforced cardboard", heavy.materials)

    def test_ficp_pdf_rates_and_boundaries(self):
        self.assertEqual(calculate_ficp_shipping(0.5, "A").shipping_jpy, 2587)
        self.assertEqual(calculate_ficp_shipping(0.5, "E").shipping_jpy, 2179)
        self.assertEqual(calculate_ficp_shipping(0.5, "F").shipping_jpy, 2206)
        self.assertEqual(calculate_ficp_shipping(0.5, "G").shipping_jpy, 3439)
        self.assertEqual(calculate_ficp_shipping(1.0, "F").shipping_jpy, 2493)
        self.assertEqual(calculate_ficp_shipping(3.5, "A").shipping_jpy, 5339)
        self.assertEqual(calculate_ficp_shipping(32.5, "A").shipping_jpy, 20422)

    def test_ficp_round_up_and_per_kg(self):
        self.assertEqual(calculate_ficp_shipping(0.51, "A").billed_weight_kg, 1.0)
        charge = calculate_ficp_shipping(33.0, "A")
        self.assertEqual(charge.rate_type, "per_kg")
        self.assertEqual(charge.per_kg_rate_jpy, 666)
        self.assertEqual(charge.shipping_jpy, 21978)

    def test_fuel_surcharge_is_added_to_ficp_base_shipping(self):
        self.assertEqual(calculate_fuel_surcharge_jpy(2206, 35.0), 773)
        total_jpy, fuel_jpy = calculate_shipping_total_with_fuel(2206, 35.0)
        self.assertEqual(fuel_jpy, 773)
        self.assertEqual(total_jpy, 2979)

    def test_dimensional_weight_and_billable_weight(self):
        dimensional = calculate_dimensional_weight_kg(50, 40, 30)
        self.assertEqual(dimensional, 12.0)
        billable, source = calculate_billable_weight_kg(actual_weight_kg=2.0, dimensional_weight_kg=12.0)
        self.assertEqual(billable, 12.0)
        self.assertEqual(source, "dimensional")
        billable, source = calculate_billable_weight_kg(actual_weight_kg=14.0, dimensional_weight_kg=12.0)
        self.assertEqual(billable, 14.0)
        self.assertEqual(source, "actual")

    def test_fetch_usd_jpy_exchange_rate_from_frankfurter(self):
        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return [{"date": "2026-06-26", "base": "USD", "quote": "JPY", "rate": 161.89}]

        with patch("comic_ficp_streamlit_app.requests.get", return_value=FakeResponse()) as mocked_get:
            result = fetch_usd_jpy_exchange_rate()

        self.assertEqual(result.rate, 161.89)
        self.assertEqual(result.source, "Frankfurter")
        self.assertEqual(result.date, "2026-06-26")
        self.assertEqual(result.status, "ok")
        mocked_get.assert_called_once()

    def test_refresh_usd_jpy_exchange_rate_updates_rate_and_audit_fields(self):
        session_state = {
            "usd_jpy_exchange_rate": 155.0,
            "usd_jpy_exchange_rate_source": "manual/default",
            "usd_jpy_exchange_rate_date": "",
            "usd_jpy_exchange_rate_status": "manual/default",
        }
        latest_rate = ExchangeRateEstimate(
            rate=162.84,
            source="Frankfurter",
            date="2026-07-31",
            status="ok",
        )

        with patch(
            "comic_ficp_streamlit_app.fetch_usd_jpy_exchange_rate",
            return_value=latest_rate,
        ):
            result = refresh_usd_jpy_exchange_rate_session_state(session_state)

        self.assertEqual(result, latest_rate)
        self.assertEqual(session_state["usd_jpy_exchange_rate"], 162.84)
        self.assertEqual(session_state["usd_jpy_exchange_rate_source"], "Frankfurter")
        self.assertEqual(session_state["usd_jpy_exchange_rate_date"], "2026-07-31")
        self.assertEqual(session_state["usd_jpy_exchange_rate_status"], "ok")

    def test_exchange_rate_refresh_callback_updates_widget_without_streamlit_exception(self):
        from streamlit.testing.v1 import AppTest

        script = '''
import streamlit as st
from comic_ficp_streamlit_app import ExchangeRateEstimate, apply_usd_jpy_exchange_rate_to_session_state

def refresh_rate():
    apply_usd_jpy_exchange_rate_to_session_state(
        st.session_state,
        ExchangeRateEstimate(162.84, "Frankfurter", "2026-07-31", "ok"),
    )

if "usd_jpy_exchange_rate" not in st.session_state:
    apply_usd_jpy_exchange_rate_to_session_state(
        st.session_state,
        ExchangeRateEstimate(155.0, "manual/default", "", "manual/default"),
    )

rate_col1, rate_col2 = st.columns([0.68, 0.32])
exchange_rate = rate_col1.number_input(
    "USD換算レート(JPY/USD)",
    min_value=1.0,
    max_value=500.0,
    step=0.1,
    key="usd_jpy_exchange_rate",
)
rate_col2.button("最新レート取得", on_click=refresh_rate)
st.caption(
    f"USD/JPY: {float(exchange_rate):.4f} / 取得元: "
    f"{st.session_state['usd_jpy_exchange_rate_source']} / "
    f"日付: {st.session_state['usd_jpy_exchange_rate_date']}"
)
'''
        app = AppTest.from_string(script, default_timeout=30).run()

        self.assertEqual(0, len(app.exception))
        self.assertEqual(155.0, app.number_input[0].value)

        app.button[0].click().run()

        self.assertEqual(0, len(app.exception))
        self.assertEqual(162.84, app.number_input[0].value)
        self.assertIn("取得元: Frankfurter", app.caption[0].value)
        self.assertIn("日付: 2026-07-31", app.caption[0].value)

    def test_mercari_image_url_inference(self):
        inferred = infer_mercari_url_from_image_url(
            "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"
        )
        self.assertEqual(inferred.url, "https://jp.mercari.com/item/m12345678901")
        self.assertEqual(inferred.confidence, "high")
        self.assertIn("m12345678901", inferred.evidence)

    def test_mercari_image_url_inference_none(self):
        inferred = infer_mercari_url_from_image_url("https://example.com/images/no-item-id.jpg")
        self.assertEqual(inferred.url, "")
        self.assertEqual(inferred.confidence, "none")

    def test_filter_listing_image_urls_keeps_only_current_mercari_item_photos(self):
        source_url = "https://jp.mercari.com/item/m12345678901"
        urls = filter_listing_image_urls(
            source_url,
            [
                "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?111",
                "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?111",
                "https://static.mercdn.net/thumb/item/webp/m99999999999_1.jpg?222",
                "https://static.mercdn.net/item/detail/orig/photos/m99999999999_1.jpg?222",
                "https://static.mercdn.net/thumb/members/webp/123456789.jpg?333",
                "https://assets.eisa.mercari.com/cdn-cgi/image/quality=85/site-asset.jpg",
                "https://a.imgvc.com/i/bf.png?v=1",
            ],
        )

        self.assertEqual(
            urls,
            [
                "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?111",
                "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?111",
            ],
        )

    def test_filter_listing_image_urls_keeps_generic_non_mercari_images(self):
        urls = filter_listing_image_urls(
            "https://example.com/products/123",
            "https://images.example.com/products/123-1.jpg|https://images.example.com/products/123-2.jpg",
        )
        self.assertEqual(len(urls), 2)

    def test_rendered_listing_rejects_related_product_and_site_images(self):
        own_1 = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?111"
        own_2 = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?111"
        listing = parse_mercari_rendered_listing(
            url="https://jp.mercari.com/item/m12345678901",
            page_title="Sample Manga Set - メルカリ",
            body_text="商品の説明\n全12巻セット\n商品の情報\n本・雑誌・漫画\n出品者",
            image_url=own_1,
            image_urls=[
                own_1,
                own_2,
                "https://static.mercdn.net/thumb/item/webp/m99999999999_1.jpg?222",
                "https://static.mercdn.net/thumb/members/webp/123456789.jpg?333",
                "https://a.imgvc.com/i/bf.png?v=1",
            ],
        )

        self.assertEqual(listing.image_url, own_1)
        self.assertEqual(listing.image_urls, [own_1, own_2])

    @unittest.skipIf(BeautifulSoup is None, "beautifulsoup4 is not installed")
    def test_static_listing_payload_rejects_related_product_images(self):
        own_1 = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?111"
        own_2 = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?111"
        html = f"""
        <html><head><meta property="og:image" content="{own_1}"></head><body>
          <img src="{own_2}">
          <img src="https://static.mercdn.net/thumb/item/webp/m99999999999_1.jpg?222">
          <img src="https://static.mercdn.net/thumb/members/webp/123456789.jpg?333">
          <img src="https://a.imgvc.com/i/bf.png?v=1">
        </body></html>
        """
        payload = extract_listing_payload(
            BeautifulSoup(html, "lxml"),
            html,
            source_url="https://jp.mercari.com/item/m12345678901",
        )

        self.assertEqual(payload.image_urls, [own_1, own_2])

    def test_build_preview_image_urls_deduplicates_main_and_extra_images(self):
        row = pd.Series(
            {
                "Main Image URL": "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg",
                "PicURL": (
                    "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg?123|"
                    "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg|"
                    "https://static.mercdn.net/item/detail/orig/photos/m111_3.jpg"
                ),
            }
        )
        urls = build_preview_image_urls(row, "PicURL")
        self.assertEqual(
            urls,
            [
                "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg",
                "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg",
                "https://static.mercdn.net/item/detail/orig/photos/m111_3.jpg",
            ],
        )

    def test_build_preview_image_urls_uses_preserved_source_images_after_processing(self):
        row = pd.Series(
            {
                "Main Image URL": "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg",
                "PicURL": "https://jp.mercari.com/item/m11111111111",
                "Source Image URLs": (
                    "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg|"
                    "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg|"
                    "https://static.mercdn.net/item/detail/orig/photos/m111_3.jpg"
                ),
            }
        )
        urls = build_preview_image_urls(row, "PicURL")
        self.assertEqual(
            urls,
            [
                "https://static.mercdn.net/item/detail/orig/photos/m111_1.jpg",
                "https://static.mercdn.net/item/detail/orig/photos/m111_2.jpg",
                "https://static.mercdn.net/item/detail/orig/photos/m111_3.jpg",
            ],
        )

    def test_image_url_detection_distinguishes_mercari_pages(self):
        self.assertTrue(
            is_likely_image_url("https://static.mercdn.net/item/detail/orig/photos/m3677344612_4.jpg?1782201200")
        )
        self.assertFalse(is_likely_image_url("https://jp.mercari.com/item/m3677344612"))

    def test_preview_metric_items_show_full_weight_and_shipping(self):
        items = build_preview_metric_items(
            price="19,800",
            book_count="27",
            weight_kg="6.050",
            shipping_jpy="8999",
            shipping_usd="58.06",
        )
        by_label = {item["label"]: item for item in items}
        self.assertEqual(by_label["価格"]["value"], "19,800")
        self.assertEqual(by_label["冊数"]["value"], "27冊")
        self.assertEqual(by_label["課金重量"]["value"], "6.050 kg")
        self.assertEqual(by_label["送料USD"]["value"], "$58.06")
        self.assertEqual(by_label["送料USD"]["sub"], "JPY 8,999円")

    def test_default_fallback_weights_are_conservative(self):
        self.assertEqual(DEFAULT_BOOK_WEIGHT_G, 200)
        self.assertEqual(DEFAULT_PACKAGING_WEIGHT_KG, 0.60)

    def test_default_us_ficp_zone_is_western_us_zone_e(self):
        self.assertEqual(DEFAULT_FICP_ZONE, "E")
        self.assertEqual(ProcessingConfig().zone, "E")

    def test_description_marker_is_replaced(self):
        first = append_description("Base", f"{AUTOFILL_MARKER_START}\nfirst\n<!-- /comic-ficp-autofill -->")
        second = append_description(first, f"{AUTOFILL_MARKER_START}\nsecond\n<!-- /comic-ficp-autofill -->")
        self.assertIn("Base", second)
        self.assertIn("second", second)
        self.assertNotIn("first", second)
        self.assertEqual(second.count(AUTOFILL_MARKER_START), 1)

    def test_product_overview_merges_matching_book_count_and_volume_range(self):
        addition = build_description_append(
            title="",
            book_count=5,
            evidence="",
            weight_kg=None,
            ficp_charge=None,
            shipping_usd=None,
            source_url="",
            buyer_detail_notes=["Set includes volumes 1-5."],
        )
        soup = BeautifulSoup(addition, "html.parser")
        items = [item.get_text(" ", strip=True) for item in soup.find_all("li")]

        self.assertEqual(items, ["This manga set includes 5 books (volumes 1-5)."])
        japanese = translate_description_added_text_to_japanese(
            build_description_append_display_text(addition)
        )
        self.assertIn("この漫画セットは1〜5巻の5冊です。", japanese)
        self.assertIsNone(re.search(r"[A-Za-z]{3,}", japanese))

    def test_generated_item_details_are_left_aligned(self):
        addition = build_description_append(
            title="",
            book_count=5,
            evidence="全5巻",
            weight_kg=None,
            ficp_charge=None,
            shipping_usd=None,
            source_url="",
            buyer_detail_notes=["Set includes volumes 1-5."],
        )

        soup = BeautifulSoup(addition, "html.parser")
        heading = soup.find("strong", string="Item details")
        self.assertIsNotNone(heading)
        details_container = heading.find_parent("div")
        self.assertIsNotNone(details_container)
        self.assertRegex(details_container.get("style", ""), r"(?i)text-align\s*:\s*left")

    def test_product_overview_marks_matching_complete_series_once(self):
        notes = ["Complete set of 15 volumes.", "Set includes volumes 1-15."]
        items = build_buyer_description_items(15, notes)
        reversed_items = build_buyer_description_items(15, reversed(notes))

        self.assertEqual(items, ["This complete manga set includes 15 books (volumes 1-15)."])
        self.assertEqual(reversed_items, items)

    def test_product_overview_keeps_mismatched_count_and_volume_range_separate(self):
        items = build_buyer_description_items(5, ["Set includes volumes 2-5."])

        self.assertEqual(
            items,
            ["This manga set includes 5 books.", "Set includes volumes 2-5."],
        )

    def test_product_overview_collapses_unused_condition_synonyms(self):
        notes = append_unique_buyer_notes(
            ["Set is new and unused."],
            [
                "Purchased new and never used.",
                "Brand new and never used.",
                "Condition: new/unused.",
            ],
        )

        self.assertEqual(notes, ["Set is new and unused."])

    def test_product_overview_removes_repeated_sentence_inside_distinct_notes(self):
        notes = append_unique_buyer_notes(
            ["Set is new and unused. Volume 5 is unopened."],
            ["Condition: new/unused. Obi band is included."],
        )

        self.assertEqual(
            notes,
            [
                "Set is new and unused. Volume 5 is unopened.",
                "Obi band is included.",
            ],
        )

    def test_product_overview_preserves_existing_long_buyer_note(self):
        long_note = "Condition details: " + ("carefully documented " * 13).strip() + "."
        self.assertGreater(len(long_note), 220)

        notes = append_unique_buyer_notes([long_note], [])

        self.assertEqual(notes, [long_note])

    def test_product_overview_keeps_more_informative_condition_note(self):
        shorter = (
            "Volume 6 may have the noted condition. "
            "Little to no page tanning or sun fading is mentioned. "
            "Affected area: page edges."
        )
        longer = f"{shorter} Condition: no noticeable scratches or stains."

        notes = append_unique_buyer_notes([shorter], [longer])

        self.assertEqual(notes, [longer])

    def test_product_overview_removes_subset_note_but_keeps_distinct_facts(self):
        detailed = (
            "Volume 1 is a first edition. Obi is included. "
            "Volumes 1-2 are unopened."
        )
        notes = append_unique_buyer_notes(
            [detailed],
            [
                "First edition with obi (band) included.",
                "Condition: no noticeable scratches or stains.",
            ],
        )

        self.assertEqual(
            notes,
            [detailed, "Condition: no noticeable scratches or stains."],
        )

    def test_cached_product_overview_is_compacted_by_export_final_guard(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "Cached manga row",
                    "Description": (
                        f"<div>{AUTOFILL_MARKER_START}<p><strong>Item details</strong></p><ul>"
                        "<li>This manga set includes 5 books.</li>"
                        "<li>Set includes volumes 1-5.</li>"
                        "<li>Set is new and unused.</li>"
                        "<li>Purchased new and never used.</li>"
                        "</ul><!-- /comic-ficp-autofill --></div>"
                    ),
                    "Listing Eligibility": "OK",
                }
            ]
        )

        first = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))
        second = build_export_dataframe(first, FreeShippingRollupOptions(enabled=False))
        description = first.loc[0, "Description"]
        items = [
            item.get_text(" ", strip=True)
            for item in BeautifulSoup(description, "html.parser").find_all("li")
        ]

        self.assertEqual(
            items,
            [
                "This manga set includes 5 books (volumes 1-5).",
                "Set is new and unused.",
            ],
        )
        self.assertEqual(second.loc[0, "Description"], description)

    def test_description_cleanup_does_not_rewrite_unmarked_item_details(self):
        source = (
            "<div><p><strong>Item details</strong></p><ul>"
            "<li>This manga set includes 5 books.</li>"
            "<li>Set includes volumes 1-5.</li>"
            "</ul></div>"
        )

        result = sanitize_description_html(source)
        items = [
            item.get_text(" ", strip=True)
            for item in BeautifulSoup(result, "html.parser").find_all("li")
        ]

        self.assertEqual(
            items,
            ["This manga set includes 5 books.", "Set includes volumes 1-5."],
        )

    def test_description_inserted_inside_existing_html(self):
        addition = build_description_append(
            title="",
            book_count=10,
            evidence="全10巻",
            weight_kg=None,
            ficp_charge=None,
            shipping_usd=None,
            source_url="",
            buyer_detail_notes=["Condition: no noticeable scratches or stains."],
        )
        result = append_description('<div style="max-width:720px;"><p>Template</p></div>', addition)
        self.assertLess(result.index(AUTOFILL_MARKER_START), result.rindex("</div>"))
        self.assertIn("Template", result)
        self.assertIn("This manga set includes 10 books.", result)
        self.assertNotIn("source listing", result.lower())
        self.assertNotIn("detected", result.lower())
        self.assertNotIn("全10巻", result)

    def test_description_inserted_inside_product_overview_section(self):
        addition = build_description_append(
            title="",
            book_count=22,
            evidence="全22巻",
            weight_kg=None,
            ficp_charge=None,
            shipping_usd=None,
            source_url="",
            buyer_detail_notes=["All volumes are first editions."],
        )
        template = (
            '<div class="listing-template" style="text-align:center;">'
            '<div class="section-heading">Product Overview</div>'
            '<div class="overview-body"><p>Authentic Japanese merchandise.</p></div>'
            '<div class="section-heading">Payment Details</div>'
            '<div class="payment-body"><p>Payments follow eBay policies.</p></div>'
            "</div>"
        )

        result = append_description(template, addition)

        self.assertIn("Authentic Japanese merchandise.", result)
        self.assertIn("This manga set includes 22 books.", result)
        self.assertLess(result.index("Authentic Japanese merchandise."), result.index(AUTOFILL_MARKER_START))
        self.assertLess(result.index(AUTOFILL_MARKER_START), result.index("Payment Details"))
        self.assertEqual(result.count(AUTOFILL_MARKER_START), 1)
        soup = BeautifulSoup(result, "html.parser")
        overview_heading = soup.find(string="Product Overview").parent
        self.assertRegex(overview_heading.parent.get("style", ""), r"(?i)text-align\s*:\s*center")
        details_heading = soup.find("strong", string="Item details")
        self.assertRegex(
            details_heading.find_parent("div").get("style", ""),
            r"(?i)text-align\s*:\s*left",
        )

    def test_description_inserted_inside_product_overview_with_cdata_wrapper(self):
        addition = build_description_append(
            title="",
            book_count=5,
            evidence="全5巻",
            weight_kg=None,
            ficp_charge=None,
            shipping_usd=None,
            source_url="",
            buyer_detail_notes=["Condition: clean/good condition."],
        )
        template = (
            "<![CDATA["
            '<div><div>Product Overview</div><div><p>Template overview.</p></div>'
            '<div>Payment Details</div><div><p>Payment template.</p></div></div>'
            "]]>"
        )

        result = append_description(template, addition)

        self.assertNotIn("<![CDATA[", result)
        self.assertNotIn("]]>", result)
        self.assertLess(result.index("Template overview."), result.index(AUTOFILL_MARKER_START))
        self.assertLess(result.index(AUTOFILL_MARKER_START), result.index("Payment Details"))

    def test_description_mojibake_template_is_sanitized_before_append(self):
        addition = build_description_append(
            title="",
            book_count=6,
            evidence="全6巻",
            weight_kg=None,
            ficp_charge=None,
            shipping_usd=None,
            source_url="",
            buyer_detail_notes=[],
        )
        template = (
            "<![CDATA["
            '<div class="listing-template">'
            '<div class="section-heading">Product Overview</div>'
            '<div class="subtitle">(陬ｽ蜩∵ｦりｦ・</div>'
            '<div class="overview-body"><p>笆ｺ 100% genuine products sourced directly from Japan.</p></div>'
            '<div class="section-heading">Payment Details</div>'
            '<div class="subtitle">(縺頑髪謇輔＞縺ｫ縺､縺・※)</div>'
            '<div>Thank you for your understanding!</div>'
            '<div>笆ｺ SIGNAL STATUS: ONLINE // END OF TRANSMISSION 笳・/div>'
            "</div>"
        )

        result = append_description(template, addition)

        self.assertIn("Product Overview", result)
        self.assertIn("100% genuine products sourced directly from Japan.", result)
        self.assertIn("This manga set includes 6 books.", result)
        self.assertIn("Payment Details", result)
        self.assertIn("SIGNAL STATUS: ONLINE // END OF TRANSMISSION", result)
        self.assertEqual(result.count(AUTOFILL_MARKER_START), 1)
        for corrupt_text in ("<![CDATA[", "]]>", "陬ｽ蜩", "縺頑", "笆ｺ", "笳・", "\uf8f0", "\ufffd"):
            self.assertNotIn(corrupt_text, result)
        self.assertIsNone(re.search(r"(?<!<)/div>", result))

    def test_description_cleanup_preserves_normal_japanese_and_single_legitimate_kanji(self):
        source = (
            "<![CDATA[<div><h2>商品説明</h2>"
            "<p>全6巻セット。日本限定版・講談社です。</p>"
            "<p>糸が縺れ、紐も縺れています。ﾏﾝｶﾞ本体は良好です。</p>"
            "<p>Authentic Japanese manga.</p></div>]]>"
        )

        result = sanitize_description_html(source)
        visible_text = BeautifulSoup(result, "html.parser").get_text(" ", strip=True)

        self.assertIn("商品説明", visible_text)
        self.assertIn("全6巻セット。日本限定版・講談社です。", visible_text)
        self.assertIn("糸が縺れ、紐も縺れています。ﾏﾝｶﾞ本体は良好です。", visible_text)
        self.assertIn("Authentic Japanese manga.", visible_text)
        self.assertNotIn("<![CDATA[", result)
        self.assertNotIn("]]>", result)

    def test_description_cleanup_is_idempotent(self):
        source = "<![CDATA[<div><p>笆ｺ Please review the photos carefully.</p><div>(陬ｽ蜩∵ｦりｦ・</div></div>]]>"

        first = sanitize_description_html(source)
        second = sanitize_description_html(first)

        self.assertEqual(second, first)
        self.assertIn("Please review the photos carefully.", second)
        self.assertNotIn("笆ｺ", second)

    def test_description_cleanup_treats_missing_values_as_empty(self):
        self.assertEqual(sanitize_description_html(float("nan")), "")
        self.assertEqual(sanitize_description_html(pd.NA), "")

        frame = pd.DataFrame(
            [
                {"Title": "NaN description", "Description": float("nan")},
                {"Title": "NA description", "Description": pd.NA},
            ],
            dtype=object,
        )
        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export["Description"].tolist(), ["", ""])

    def test_build_export_dataframe_sanitizes_description_as_final_guard(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "Cached manga row",
                    "Description": (
                        "<![CDATA[<div><div>Product Overview</div>"
                        "<div>(陬ｽ蜩∵ｦりｦ・</div>"
                        "<p>笆ｺ Please review photos for exact condition.</p>"
                        "<div>笆ｺ SIGNAL STATUS: ONLINE // END OF TRANSMISSION 笳・/div></div>"
                    ),
                    "Listing Eligibility": "OK",
                }
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))
        description = export.loc[0, "Description"]

        self.assertIn("Please review photos for exact condition.", description)
        self.assertIn("SIGNAL STATUS: ONLINE // END OF TRANSMISSION", description)
        for corrupt_text in ("<![CDATA[", "]]>", "陬ｽ蜩", "笆ｺ", "笳・"):
            self.assertNotIn(corrupt_text, description)
        self.assertIsNone(re.search(r"(?<!<)/div>", description))

    def test_description_append_display_text_matches_added_buyer_text(self):
        addition = build_description_append(
            title="",
            book_count=16,
            evidence="",
            weight_kg=None,
            ficp_charge=None,
            shipping_usd=None,
            source_url="",
            buyer_detail_notes=["Page tanning or sun fading may be present."],
        )
        display_text = build_description_append_display_text(addition)
        self.assertIn("Item details", display_text)
        self.assertIn("- This manga set includes 16 books.", display_text)
        self.assertIn("- Page tanning or sun fading may be present.", display_text)
        self.assertIn("Please review photos for exact condition.", display_text)
        self.assertNotIn("Added total book count to Description", display_text)
        self.assertNotIn("source listing", display_text.lower())
        self.assertNotIn("detected", display_text.lower())
        self.assertNotIn("<li>", display_text)

    def test_description_added_text_has_japanese_ui_translation(self):
        english = "\n".join(
            [
                "Item details",
                "- This manga set includes 32 books.",
                "- Volumes 31 and 32 are shrink-wrapped.",
                "- Condition: close to unused.",
                "- Page tanning or sun fading may be present.",
                "Please review photos for exact condition.",
            ]
        )
        japanese = translate_description_added_text_to_japanese(english)

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは32冊です。", japanese)
        self.assertIn("31巻と32巻はシュリンク付きです。", japanese)
        self.assertIn("状態: 未使用に近いです。", japanese)
        self.assertIn("日焼けや色あせがある可能性があります。", japanese)
        self.assertIn("正確な状態は写真で確認してください。", japanese)
        self.assertTrue(contains_japanese_text(japanese))

    def test_ai_description_notes_are_translated_for_ui_review(self):
        english = (
            "Item details - This manga set includes 27 books. - "
            "Volume 1, 22 may have the noted condition. Affected area: obi band. - "
            "Writing or markings may be present. - Includes volumes 1 through 27. - "
            "Volumes 1-22 have been read once. - Volumes 23-27 are unopened. - "
            "No folds or writing noted. - Original obi/bands are missing for volumes 1-22. "
            "Please review photos for exact condition."
        )
        japanese = translate_description_added_text_to_japanese(english)

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは27冊です。", japanese)
        self.assertIn("1巻と22巻に記載された状態がある可能性があります。", japanese)
        self.assertIn("該当箇所: 帯。", japanese)
        self.assertIn("書き込みやマーキングがある可能性があります。", japanese)
        self.assertIn("1〜27巻を含みます。", japanese)
        self.assertIn("1〜22巻は一度読まれています。", japanese)
        self.assertIn("23〜27巻は未開封です。", japanese)
        self.assertIn("折れや書き込みはないと説明されています。", japanese)
        self.assertIn("1〜22巻は元の帯が欠品しています。", japanese)
        self.assertNotIn("Includes volumes", japanese)
        self.assertNotIn("have been read once", japanese)
        self.assertNotIn("are unopened", japanese)
        self.assertNotIn("Original obi", japanese)

    def test_ai_description_notes_do_not_leave_untranslated_english_in_ui_review(self):
        english = (
            "Item details - This manga set includes 6 books. - "
            "Condition: close to unused. - "
            "Complete set of 6 volumes. - "
            "Volumes are unread and have been stored since purchase. - "
            "Minor imperfections may be present due to personal storage. "
            "Please review photos for exact condition."
        )
        japanese = translate_description_added_text_to_japanese(english)

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは6冊です。", japanese)
        self.assertIn("状態: 未使用に近いです。", japanese)
        self.assertIn("全6巻セットです。", japanese)
        self.assertIn("各巻は未読で、購入後に保管されていたと説明されています。", japanese)
        self.assertIn("個人保管品のため、軽微な傷みがある可能性があります。", japanese)
        self.assertIn("正確な状態は写真で確認してください。", japanese)
        self.assertIsNone(re.search(r"[A-Za-z]{3,}", japanese))

    def test_ai_description_notes_translate_set_range_and_near_unused_for_ui_review(self):
        english = (
            "Item details - This manga set includes 21 books. - "
            "Set includes volumes 1 through 21. - "
            "Appears to be in near-unused condition. - "
            "Shows minimal signs of use. Please review photos for exact condition."
        )
        japanese = translate_description_added_text_to_japanese(english)

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは21冊です。", japanese)
        self.assertIn("1〜21巻を含みます。", japanese)
        self.assertIn("未使用に近い状態です。", japanese)
        self.assertIn("使用感は少なめです。", japanese)
        self.assertIn("正確な状態は写真で確認してください。", japanese)
        self.assertNotIn("追加の状態説明があります", japanese)
        self.assertIsNone(re.search(r"[A-Za-z]{3,}", japanese))

    def test_ai_description_notes_translate_new_unread_purchase_phrases_for_ui_review(self):
        english = (
            "Item details - This manga set includes 5 books. - "
            "Complete 5-volume set of Mitsuteru Yokoyama's Rekishi Manga 'Shiki' Aizo-ban edition. - "
            "Brand new and unread. - "
            "Purchased new and never used. Please review photos for exact condition."
        )
        japanese = translate_description_added_text_to_japanese(english)

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは5冊です。", japanese)
        self.assertIn("全5巻セットです。", japanese)
        self.assertIn("新品・未読です。", japanese)
        self.assertIn("新品で購入後、未使用です。", japanese)
        self.assertIn("正確な状態は写真で確認してください。", japanese)
        self.assertNotIn("追加の状態説明があります", japanese)
        self.assertIsNone(re.search(r"[A-Za-z]{3,}", japanese))

    def test_ai_description_notes_translate_unread_near_new_storage_phrases_for_ui_review(self):
        english = (
            "Item details - This manga set includes 6 books. - "
            "Condition: close to unused. - "
            "Complete set of 6 volumes. - "
            "Unread condition. - "
            "Appears to be in near-new condition. - "
            "Minor imperfections due to storage may be present. "
            "Please review photos for exact condition."
        )
        japanese = translate_description_added_text_to_japanese(english)

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは6冊です。", japanese)
        self.assertIn("状態: 未使用に近いです。", japanese)
        self.assertIn("全6巻セットです。", japanese)
        self.assertIn("未読の状態です。", japanese)
        self.assertIn("新品に近い状態です。", japanese)
        self.assertIn("保管に伴う軽微な傷みがある可能性があります。", japanese)
        self.assertIn("正確な状態は写真で確認してください。", japanese)
        self.assertNotIn("追加の状態説明があります", japanese)
        self.assertIsNone(re.search(r"[A-Za-z]{3,}", japanese))

    def test_unknown_ai_description_english_uses_japanese_fallback_for_ui_review(self):
        japanese = translate_description_added_text_to_japanese(
            "Item details - This manga set includes 2 books. - Collector shelf note with uncommon English wording."
        )

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは2冊です。", japanese)
        self.assertIn("追加の商品状態説明があります。", japanese)
        self.assertNotIn("上の英語欄で確認", japanese)
        self.assertIsNone(re.search(r"[A-Za-z]{3,}", japanese))

    def test_description_translation_translates_honey_near_mint_ui_review(self):
        english = (
            "Item details - This manga set includes 8 books. - "
            "Complete 8-volume set of the manga \"Honey\". - "
            "Volumes show minimal signs of use. - "
            "Condition is 'Near Mint' with little feeling of use. "
            "Please review photos for exact condition."
        )
        japanese = translate_description_added_text_to_japanese(english)

        self.assertIn("商品詳細", japanese)
        self.assertIn("この漫画セットは8冊です。", japanese)
        self.assertIn("全8巻セットです。", japanese)
        self.assertIn("各巻の使用感は少なめです。", japanese)
        self.assertIn("使用感が少ない、未使用に近い状態です。", japanese)
        self.assertIn("正確な状態は写真で確認してください。", japanese)
        self.assertNotIn("上の英語欄で確認", japanese)
        self.assertIsNone(re.search(r"[A-Za-z]{3,}", japanese))

    def test_extract_description_details_filters_unneeded_information(self):
        details = extract_buyer_relevant_listing_details(
            "定価500円で購入しました。目立った傷や汚れなし。全10巻セットです。",
            "もらい物です。3巻カバーに折れがあります。発送はメルカリ便です。",
        )
        joined = " ".join(details)
        self.assertIn("no noticeable scratches or stains", joined)
        self.assertIn("Creases or folds may be present", joined)
        self.assertNotIn("定価", joined)
        self.assertNotIn("購入", joined)
        self.assertNotIn("もらい", joined)
        self.assertFalse(contains_japanese_text(joined))
        self.assertNotIn("Source listing note:", joined)
        self.assertNotIn("source listing", joined.lower())

    def test_extract_description_details_keeps_item_condition_not_packaging(self):
        details = extract_buyer_relevant_listing_details(
            "新品未読です。シュリンクは付いていません。13.14.15巻とスピンオフ1巻は応募券切り取り済みです。",
            "梱包は水濡れ防止で発送します。",
            max_items=6,
        )
        joined = " ".join(details)
        self.assertIn("new/unread", joined)
        self.assertIn("Shrink wrap is not included", joined)
        self.assertIn("Application/coupon ticket has been cut out or removed", joined)
        self.assertNotIn("Water exposure or water damage", joined)
        self.assertFalse(contains_japanese_text(joined))

    def test_extract_description_details_scopes_shrink_wrap_to_specific_volumes(self):
        details = extract_buyer_relevant_listing_details(
            "カッコウの許嫁1〜32巻一番最初から最新刊です。31.32巻はシュリンク付きです。",
            "状態がキレイだったため中古で購入し、31.32を買い足しましたが読む時間がないため出品いたします。",
            max_items=6,
        )
        joined = " ".join(details)
        self.assertIn("Volumes 31 and 32 are shrink-wrapped.", joined)
        self.assertNotIn("Shrink wrap is included.", joined)
        self.assertFalse(contains_japanese_text(joined))

    def test_extract_description_details_keeps_first_edition_and_low_tanning_details(self):
        details = extract_buyer_relevant_listing_details(
            "はじめてのあく 全16巻セット、すべて初版本になります。",
            "2回くらい読んで、あとは箱にしまっておきましたので、日焼け等もほとんどしてません。",
            max_items=6,
        )
        joined = " ".join(details)
        self.assertIn("All volumes are first editions.", joined)
        self.assertIn("Little to no page tanning or sun fading is mentioned.", joined)
        self.assertNotIn("Page tanning or sun fading may be present.", joined)
        self.assertFalse(contains_japanese_text(joined))

    def test_extract_description_details_does_not_append_japanese_marketplace_text(self):
        details = extract_buyer_relevant_listing_details(
            "【美品✨+番外編】ひるなかの流星 やまもり三香 少女漫画 by メルカリ",
            "新品/未使用も多数、支払いはクレジットカード・キャリア決済・コンビニ・銀行ATMが利用可能です。",
        )
        joined = " ".join(details)
        self.assertFalse(contains_japanese_text(joined))
        self.assertNotIn("Source listing note:", joined)
        self.assertNotIn("source listing", joined.lower())
        self.assertNotIn("メルカリ", joined)

    def test_source_listing_display_filters_generic_mercari_marketplace_text(self):
        generic_description = (
            "横山光輝 史記 愛蔵版 全5巻セットをメルカリでお得に通販、"
            "誰でも安心して簡単に売り買いが楽しめるフリマサービスです。"
        )
        generic_detail = (
            "新品/未使用も多数、支払いはクレジットカード・キャリア決済・コンビニ・銀行ATMが利用可能で、"
            "品物が届いてから出品者に入金される独自システムのため安心です。"
        )
        self.assertEqual(clean_source_listing_description(generic_description), "")
        self.assertEqual(build_source_detail_preview(generic_description, generic_detail), "")

    def test_parse_mercari_rendered_listing_extracts_real_description_and_condition(self):
        rendered_text = """
        ホーム
        SPY×FAMILY 1〜17巻セット
        ¥4,300
        商品の説明
        SPY×FAMILYの全巻セット売りになります。
        最新17巻までになります。
        私が購入してから1〜2回読んだ程度のほぼ新品未使用レベルの状態になります。

        5日前

        商品の情報
        カテゴリー
        本・雑誌・漫画
        漫画
        全巻セット
        少年漫画
        商品の状態
        未使用に近い
        数回使用し、あまり使用感がない
        配送料の負担
        送料込み(出品者負担)
        メルカリ安心への取り組み
        出品者
        """
        listing = parse_mercari_rendered_listing(
            url="https://jp.mercari.com/item/m58550840784",
            page_title="SPY×FAMILY 1〜17巻セット - メルカリ",
            body_text=rendered_text,
            image_url="https://example.com/image.jpg",
        )
        self.assertEqual(listing.status, "ok (browser rendered)")
        self.assertEqual(listing.title, "SPY×FAMILY 1〜17巻セット")
        self.assertEqual(listing.price, "4,300")
        self.assertIn("SPY×FAMILYの全巻セット売り", listing.description)
        self.assertNotIn("5日前", listing.description)
        self.assertEqual(listing.source_condition, "未使用に近い")
        self.assertIn("商品の状態 未使用に近い", listing.details_text)

    def test_extract_mercari_condition_returns_only_canonical_condition(self):
        rendered_text = """
        商品の状態
        新品、未使用
        新品で購入して保管していました
        カテゴリー
        本・雑誌・漫画
        配送料の負担
        送料込み
        """

        self.assertEqual(
            extract_mercari_condition_from_rendered_text(rendered_text),
            "新品、未使用",
        )

    def test_extract_mercari_condition_skips_description_phrase_before_structured_field(self):
        rendered_text = """
        商品の説明
        商品の状態は写真をご確認ください。
        商品の情報
        カテゴリー
        本・雑誌・漫画
        商品の状態
        未使用に近い
        数回使用し、あまり使用感がない
        配送料の負担
        送料込み
        """

        self.assertEqual(
            extract_mercari_condition_from_rendered_text(rendered_text),
            "未使用に近い",
        )

    def test_specifics_do_not_override_existing_values(self):
        row = pd.Series({"C:Language": "", "C:Type": "Graphic Novel"})
        updated = apply_item_specifics(row, {"C:Language": "Japanese", "C:Type": "Manga"})
        self.assertEqual(updated["C:Language"], "Japanese")
        self.assertEqual(updated["C:Type"], "Graphic Novel")

    def test_specifics_values_are_limited_to_ebay_character_limit(self):
        row = pd.Series({"C:Character": "", "C:Features": ""})
        updated = apply_item_specifics(
            row,
            {
                "C:Character": "Futaro Uesugi; Ichika Nakano; Nino Nakano; Miku Nakano; Yotsuba Nakano; Itsuki Nakano",
                "C:Features": "Set; Complete Series; First Edition; Full Color; Obi Included; Illustrated",
            },
        )

        self.assertLessEqual(len(updated["C:Character"]), 65)
        self.assertEqual(updated["C:Character"], "Futaro Uesugi; Ichika Nakano; Nino Nakano; Miku Nakano")
        self.assertLessEqual(len(updated["C:Features"]), 65)
        self.assertEqual(updated["C:Features"], "Set; Complete Series; First Edition; Full Color; Obi Included")

    def test_specifics_infer_publisher_author_series_and_genre(self):
        specifics = infer_specifics(
            "Jujutsu Kaisen Volumes 1-16 Set by Gege Akutami",
            "Publisher: Shueisha 少年ジャンプ",
        )
        self.assertEqual(specifics["C:Publisher"], "Shueisha")
        self.assertEqual(specifics["C:Brand"], "Shueisha")
        self.assertEqual(specifics["C:Author"], "Gege Akutami")
        self.assertEqual(specifics["C:Genre"], "Shonen")
        self.assertEqual(specifics["C:Series"], "Jujutsu Kaisen")
        self.assertEqual(specifics["C:Book Title"], "Jujutsu Kaisen")

    def test_specifics_translate_known_japanese_series_instead_of_full_mercari_title(self):
        specifics = infer_specifics(
            "【美品✨+番外編】ひるなかの流星 やまもり三香 少女漫画 by メルカリ",
            "日本語 全12巻",
        )
        self.assertEqual(specifics["C:Series"], "Daytime Shooting Star")
        self.assertEqual(specifics["C:Book Title"], "Daytime Shooting Star")
        self.assertEqual(specifics["C:Author"], "Mika Yamamori")
        self.assertFalse(contains_japanese_text(specifics["C:Series"]))

    def test_specifics_fill_spy_family_author_genre_and_grade_from_source(self):
        specifics = infer_specifics(
            "SPY×FAMILY 1〜17巻セット by メルカリ",
            "商品の状態 未使用に近い カテゴリー 本・雑誌・漫画 漫画 全巻セット 少年漫画",
        )
        self.assertEqual(specifics["C:Series"], "Spy x Family")
        self.assertEqual(specifics["C:Artist/Writer"], "Tatsuya Endo")
        self.assertEqual(specifics["C:Publisher"], "Shueisha")
        self.assertIn("Action", specifics["C:Genre"])
        self.assertIn("Shonen", specifics["C:Genre"])
        self.assertEqual(specifics["C:Grade"], "Near Mint")
        self.assertEqual(specifics["C:Intended Audience"], "Young Adults")

    def test_specifics_fill_known_csv_titles_and_english_condition_grade(self):
        specifics = infer_specifics(
            "Blue Lock, Volumes 1-38, Complete Set, Special Edition, Unopened",
            "",
        )
        self.assertEqual(specifics["C:Artist/Writer"], "Muneyuki Kaneshiro; Yusuke Nomura")
        self.assertEqual(specifics["C:Publisher"], "Kodansha")
        self.assertIn("Sports", specifics["C:Genre"])
        self.assertEqual(specifics["C:Grade"], "Near Mint")

    def test_specifics_fill_artist_writer_for_more_csv_reference_titles(self):
        samples = [
            ("Mozuya Gets Angry - All Volumes", "Mozuya-san Gets Angry", "Rokuro Shinofusa", "Kodansha"),
            ("The teacher is a vampire who is bad at kissing", "Li'l Miss Vampire Can't Suck Right", "Kyosuke Nishiki", "Fujimi Shobo"),
            ("Onijima-san and Yamada-san The Complete Series", "Kijima-san and Yamada-san", "Hoshimi SK", "Square Enix"),
            ("Megumu Seto, Just Kill Me Volumes 1-6, Complete Set", "You Might As Well Be the One", "Megumu Seto", "Kodansha"),
            ("Tamonten-kun, Which Way is He Going!? Volumes 1-15 Set Spin-off", "Tamon's B-Side", "Yuki Shiwasu", "Hakusensha"),
        ]
        for title, series, author, publisher in samples:
            with self.subTest(title=title):
                specifics = infer_specifics(title, "")
                self.assertEqual(specifics["C:Artist/Writer"], author)
                self.assertEqual(specifics["C:Publisher"], publisher)
                self.assertEqual(specifics["C:Series"], series)

    def test_specifics_fill_csv_title_column_when_present(self):
        specifics = infer_specifics_with_notes(
            "BANANA FISH Reprint BOX vol.1 Banana Fish",
            "",
            candidate_columns=["C:Title", "C:Artist/Writer", "C:Genre", "C:Publisher"],
        ).values
        self.assertEqual(specifics["C:Title"], "Banana Fish")
        self.assertEqual(specifics["C:Artist/Writer"], "Akimi Yoshida")
        self.assertEqual(specifics["C:Publisher"], "Shogakukan")
        self.assertIn("Drama", specifics["C:Genre"])

    def test_specifics_do_not_fill_unknown_japanese_title(self):
        specifics = infer_specifics(
            "【美品】未登録タイトル 山田太郎 少女漫画 by メルカリ",
            "日本語 全12巻",
        )
        self.assertNotIn("C:Series", specifics)
        self.assertNotIn("C:Book Title", specifics)

    def test_process_dataframe_preserves_rows_and_writes_shipping_usd(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "漫画セット 全5巻",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                    "C:Type": "Graphic Novel",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="A",
            book_weight_g=150,
            packaging_weight_kg=0,
            exchange_rate_jpy_per_usd=150,
            exchange_rate_source="test rate source",
            exchange_rate_date="2026-06-26",
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "Detected Book Count"], "5")
        self.assertEqual(result.loc[0, "Estimated Packaging Weight kg"], "0.250")
        self.assertIn("bubble wrap", result.loc[0, "Packaging Materials"])
        self.assertEqual(result.loc[0, "Estimated Weight kg"], "1.000")
        self.assertEqual(result.loc[0, "FICP Shipping JPY"], "3487")
        self.assertEqual(result.loc[0, "Shipping Cost"], "23.25")
        self.assertEqual(result.loc[0, "USDJPY Exchange Rate"], "150.0000")
        self.assertEqual(result.loc[0, "USDJPY Exchange Rate Source"], "test rate source")
        self.assertEqual(result.loc[0, "USDJPY Exchange Rate Date"], "2026-06-26")
        self.assertEqual(result.loc[0, "C:Language"], "Japanese")
        self.assertEqual(result.loc[0, "C:Type"], "Graphic Novel")
        self.assertIn("Existing description", result.loc[0, "Description"])
        self.assertEqual(result.loc[0, "Description"].count(AUTOFILL_MARKER_START), 1)
        self.assertIn("Description includes total book count: 5 books.", result.loc[0, "Description Detail Notes"])
        self.assertIn("No buyer-relevant condition details were added.", result.loc[0, "Description Detail Notes"])
        self.assertIn("C:Language=Japanese", result.loc[0, "Specifics Filled Fields"])
        self.assertIn("C:Type=Graphic Novel", result.loc[0, "Specifics Existing Fields"])
        self.assertIn("C:Publisher", result.loc[0, "Specifics Not Filled Fields"])

    def test_process_dataframe_replaces_product_page_in_picurl_with_image_url(self):
        frame = pd.DataFrame(
            [
                {
                    "PicURL": "https://jp.mercari.com/item/m12066712737",
                    "Title": "Sample Manga Volumes 1-5 Set",
                    "Description": "Existing description",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="PicURL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            exchange_rate_jpy_per_usd=150,
            enable_scrape=True,
        )
        listing = ListingData(
            title="Sample Manga Volumes 1-5 Set",
            price="1200",
            image_url="https://static.mercdn.net/item/detail/orig/photos/m12066712737_1.jpg?1781571628",
            description="全5巻セットです。目立った傷や汚れなし。",
            status="ok",
            source_url="https://jp.mercari.com/item/m12066712737",
        )

        with patch("comic_ficp_streamlit_app.scrape_listing", return_value=listing):
            result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "PicURL"], listing.image_url)
        self.assertEqual(result.loc[0, "Main Image URL"], listing.image_url)
        self.assertTrue(is_likely_image_url(result.loc[0, "PicURL"]))

    def test_process_dataframe_persists_source_condition_through_export(self):
        frame = pd.DataFrame(
            [
                {
                    "PicURL": "https://jp.mercari.com/item/m12066712737",
                    "Category": "259109",
                    "ConditionID": "3000",
                    "Title": "Sample Manga Volumes 1-5 Set",
                    "Description": "Existing description",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="PicURL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            exchange_rate_jpy_per_usd=150,
            enable_scrape=True,
        )
        listing = ListingData(
            title="Sample Manga Volumes 1-5 Set",
            price="1200",
            image_url="https://static.mercdn.net/item/detail/orig/photos/m12066712737_1.jpg",
            description="全5巻セットです。購入後一度も読んでいません。",
            source_condition="新品、未使用",
            status="ok",
            source_url="https://jp.mercari.com/item/m12066712737",
        )

        with patch("comic_ficp_streamlit_app.scrape_listing", return_value=listing):
            processed = process_dataframe(frame, config)
        export = build_export_dataframe(processed, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(processed.loc[0, "Source Listing Condition"], "新品、未使用")
        self.assertEqual(processed.loc[0, "Source ConditionID Decision"], "1000")
        self.assertEqual(processed.loc[0, "ConditionID"], "1000")
        self.assertEqual(export.loc[0, "ConditionID"], "1000")
        self.assertEqual(export.loc[0, "Original ConditionID"], "3000")
        self.assertEqual(export.loc[0, "Applied Condition Name"], "Brand New")

    def test_process_dataframe_preserves_captured_condition_when_scrape_is_disabled(self):
        frame = pd.DataFrame(
            [
                {
                    "Category": "259109",
                    "ConditionID": "1000",
                    "PicURL": (
                        "https://static.mercdn.net/item/detail/orig/photos/m12066712737_1.jpg|"
                        "https://static.mercdn.net/item/detail/orig/photos/m12066712737_2.jpg"
                    ),
                    "Title": "Saved Manga Volumes 1-5 Set",
                    "Description": "Existing description",
                    "Source Listing Title": "保存済み漫画 全5巻",
                    "Source Listing Description": "未読のまま保管しています。",
                    "Source Listing Condition": "新品、未使用",
                    "Source ConditionID Decision": "1000",
                    "Source Condition Name": "Brand New",
                    "Source Condition Mapping Status": "mapped: 新品、未使用 -> 1000 (Brand New)",
                    "Source Condition Evidence": "Structured source listing condition.",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="PicURL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            enable_scrape=False,
        )

        processed = process_dataframe(frame, config)
        export = build_export_dataframe(processed, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(processed.loc[0, "Source Listing Condition"], "新品、未使用")
        self.assertEqual(processed.loc[0, "Source Listing Title"], "保存済み漫画 全5巻")
        self.assertEqual(processed.loc[0, "Source Listing Description"], "未読のまま保管しています。")
        self.assertEqual(processed.loc[0, "ConditionID"], "1000")
        self.assertEqual(export.loc[0, "ConditionID"], "1000")

    def test_process_dataframe_uses_ai_enrichment_when_enabled(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "Manga Set Volumes 1-2",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                    "C:Genre": "NA",
                    "C:Author": "NA",
                    "C:Artist/Writer": "NA",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=True,
            ai_provider="gemini",
            ai_model="gemini-test",
            ai_api_key="test-key",
        )
        ai_result = AIEnrichment(
            provider="gemini",
            model="gemini-test",
            status="ok",
            description_notes=["All volumes are first editions."],
            specifics={
                "C:Genre": "Comedy",
                "C:Author": "Test Author",
                "C:Artist/Writer": "Test Author",
            },
            notes=["matched known title"],
            usage=APIUsage(
                provider="gemini",
                model="gemini-2.5-flash-lite",
                calls=1,
                input_tokens=1000,
                cached_input_tokens=200,
                output_tokens=500,
                total_tokens=1500,
                estimated_cost_usd=0.000282,
                pricing_status="standard paid estimate (2026-07-14)",
            ),
        )
        with patch("comic_ficp_streamlit_app.enrich_listing_with_ai", return_value=ai_result) as mocked:
            result = process_dataframe(frame, config)

        mocked.assert_called_once()
        self.assertEqual(result.loc[0, "AI Enrichment Status"], "ok")
        self.assertEqual(result.loc[0, "AI Provider"], "gemini")
        self.assertIn("All volumes are first editions.", result.loc[0, "Description Added Text"])
        self.assertIn("全巻初版です。", result.loc[0, "Description Added Japanese"])
        self.assertIn("All volumes are first editions.", result.loc[0, "Description"])
        self.assertEqual(result.loc[0, "C:Genre"], "Comedy")
        self.assertEqual(result.loc[0, "C:Author"], "Test Author")
        self.assertEqual(result.loc[0, "C:Artist/Writer"], "Test Author")
        self.assertIn("C:Genre=Comedy", result.loc[0, "AI Specifics Suggestions"])
        self.assertEqual(result.loc[0, "AI API Calls"], "1")
        self.assertEqual(result.loc[0, "AI Total Tokens"], "1500")
        self.assertEqual(result.loc[0, "AI Estimated Cost USD"], "0.000282000")
        self.assertEqual(result.loc[0, "AI Estimated Cost JPY"], "0.042300")

        export = build_export_dataframe(result)
        self.assertNotIn("AI Estimated Cost USD", export.columns)
        self.assertNotIn("AI Total Tokens", export.columns)

    def test_process_dataframe_consolidates_ai_product_overview_facts(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "Sample Manga Set Volumes 1-5",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=True,
            ai_provider="gemini",
            ai_model="gemini-test",
            ai_api_key="test-key",
        )
        ai_result = AIEnrichment(
            provider="gemini",
            model="gemini-test",
            status="ok",
            description_notes=[
                "Set includes volumes 1-5.",
                "Set is new and unused.",
                "Purchased new and never used.",
            ],
            specifics={},
        )

        with patch("comic_ficp_streamlit_app.enrich_listing_with_ai", return_value=ai_result):
            result = process_dataframe(frame, config)

        description = result.loc[0, "Description"]
        items = [
            item.get_text(" ", strip=True)
            for item in BeautifulSoup(description, "html.parser").find_all("li")
        ]
        self.assertEqual(
            items,
            [
                "This manga set includes 5 books (volumes 1-5).",
                "Set is new and unused.",
            ],
        )
        self.assertEqual(description.count("new and unused"), 1)
        self.assertNotIn("Purchased new", description)
        self.assertIn(
            "この漫画セットは1〜5巻の5冊です。",
            result.loc[0, "Description Added Japanese"],
        )

    def test_process_dataframe_does_not_use_ai_book_count_for_shipping(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "Unknown Manga Complete Set",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=True,
            ai_provider="gemini",
            ai_model="gemini-test",
            ai_api_key="test-key",
            enable_reference_lookup=False,
        )
        ai_result = AIEnrichment(
            provider="gemini",
            model="gemini-test",
            status="ok",
            book_count=5,
            book_count_evidence="AI: complete 5-volume set",
            description_notes=["Complete set of 5 volumes."],
            specifics={},
        )
        with patch("comic_ficp_streamlit_app.enrich_listing_with_ai", return_value=ai_result):
            result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "Detected Book Count"], "")
        self.assertEqual(result.loc[0, "FICP Shipping USD"], "")
        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertEqual(result.loc[0, "Exclusion Reason"], "Complete-set count reference not found")
        self.assertEqual(result.loc[0, "Reference Count Status"], "skipped: free reference lookup disabled")

    def test_process_dataframe_marks_missing_book_count_status(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "Unknown Manga Complete Set",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "Detected Book Count"], "")
        self.assertIn("冊数判定不能", result.loc[0, "Book Count Status"])
        self.assertEqual(result.loc[0, "FICP Shipping USD"], "")
        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertEqual(result.loc[0, "Exclusion Reason"], "Complete-set count reference not found")
        self.assertEqual(result.loc[0, "Processing Result"], "出品除外")
        self.assertEqual(result.loc[0, "Processing Severity"], "出品除外")
        self.assertEqual(result.loc[0, "Needs Review"], "Yes")
        self.assertIn("冊数判定不能", result.loc[0, "Needs Review Reason"])
        self.assertEqual(len(build_export_dataframe(result)), 0)

    def test_processing_diagnostic_table_summarizes_row_state(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "PicURL": "https://example.com/unknown.jpg",
                    "Title": "Unknown Manga Complete Set",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                },
                {
                    "Product URL": "",
                    "PicURL": "https://example.com/set.jpg",
                    "Title": "Manga Set Volumes 1-5",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                },
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=False,
        )
        result = process_dataframe(frame, config)
        table = build_processing_diagnostic_table(result, "Title", "Product URL")
        self.assertEqual(table.loc[0, "Result"], "出品除外")
        self.assertIn("Complete-set count reference not found", table.loc[0, "Review Reason"])
        self.assertIn("Reference Status", table.columns)
        self.assertEqual(table.loc[1, "Result"], "成功")
        self.assertEqual(table.loc[1, "Needs Review"], "No")
        self.assertTrue(table.loc[1, "Shipping USD"])

    def test_process_dataframe_uses_free_reference_book_count_for_shipping(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "PicURL": "https://example.com/images/manga-set.jpg",
                    "Title": "Reference Story Complete Set",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=False,
            enable_reference_lookup=True,
        )
        reference_result = ReferenceBookCountResult(
            status="AniList volume count found (FINISHED)",
            book_count=4,
            source="AniList",
            confidence="high",
            evidence="Reference Story: 4 volumes",
            query="Reference Story",
        )
        with patch("comic_ficp_streamlit_app.anilist_manga_volume_lookup", return_value=reference_result):
            result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "Detected Book Count"], "4")
        self.assertEqual(result.loc[0, "Reference Book Count"], "4")
        self.assertEqual(result.loc[0, "Reference Count Source"], "AniList")
        self.assertIn("Reference Story: 4 volumes", result.loc[0, "Book Count Evidence"])
        self.assertTrue(result.loc[0, "FICP Shipping USD"])
        self.assertEqual(result.loc[0, "Listing Eligibility"], "OK")
        self.assertEqual(result.loc[0, "Processing Result"], "成功")

    def test_process_dataframe_excludes_unknown_count_without_complete_claim(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "PicURL": "https://example.com/images/manga-set.jpg",
                    "Title": "Unknown manga lot",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=False,
            enable_reference_lookup=True,
        )
        result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "Detected Book Count"], "")
        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertEqual(result.loc[0, "Exclusion Reason"], "Book count unavailable and no complete-set claim")
        self.assertEqual(result.loc[0, "Reference Count Status"], "skipped: no complete-set claim")
        self.assertEqual(len(build_export_dataframe(result)), 0)

    def test_process_dataframe_excludes_reference_count_over_limit(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "Reference Epic Complete Set",
                    "Description": "",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            max_book_count_for_export=40,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_reference_lookup=True,
        )
        reference_result = ReferenceBookCountResult(
            status="AniList volume count found (FINISHED)",
            book_count=45,
            source="AniList",
            confidence="high",
            evidence="Reference Epic: 45 volumes",
            query="Reference Epic",
        )
        with patch("comic_ficp_streamlit_app.anilist_manga_volume_lookup", return_value=reference_result):
            result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "Detected Book Count"], "45")
        self.assertEqual(result.loc[0, "Reference Book Count"], "45")
        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertEqual(result.loc[0, "Exclusion Reason"], "Book count exceeds export limit")
        self.assertIn("45 books", result.loc[0, "Exclusion Evidence"])
        self.assertEqual(len(build_export_dataframe(result)), 0)

    def test_diagnose_processed_row_marks_excluded_as_reviewable(self):
        row = pd.Series(
            {
                "Listing Eligibility": "Excluded",
                "Exclusion Reason": "Book count exceeds the configured maximum",
                "Exclusion Evidence": "45 books > limit 40",
                "Scrape Status": "excluded: ok",
                "Detected Book Count": "45",
                "Billable Weight kg": "9.700",
                "FICP Shipping USD": "88.00",
                "Main Image URL": "https://example.com/image.jpg",
            }
        )
        diagnostics = diagnose_processed_row(row)
        self.assertEqual(diagnostics["result"], "出品除外")
        self.assertEqual(diagnostics["needs_review"], "Yes")
        self.assertIn("Book count exceeds", diagnostics["review_reason"])

    def test_ai_error_diagnostics_redact_api_key(self):
        secret = "AIzaSyDUMMYSECRETKEYVALUE123456789"
        raw_error = (
            "AI補完: error: 503 Server Error: Service Unavailable for url: "
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={secret}"
        )
        row = pd.Series(
            {
                "Scrape Status": "ok",
                "Detected Book Count": "4",
                "Billable Weight kg": "1.200",
                "FICP Shipping USD": "22.43",
                "Main Image URL": "https://example.com/image.jpg",
                "AI Enrichment Status": raw_error,
            }
        )

        diagnostics = diagnose_processed_row(row)

        self.assertNotIn(secret, diagnostics["review_reason"])
        self.assertNotIn(secret, diagnostics["diagnostics"])
        self.assertEqual(diagnostics["needs_review"], "No")
        self.assertIn("key=[redacted]", diagnostics["diagnostics"])

    def test_redact_sensitive_text_masks_common_api_key_forms(self):
        secret = "AIzaSyDUMMYSECRETKEYVALUE123456789"
        text = (
            f"https://example.com/path?key={secret}&x=1 "
            f"Bearer sk-test-secret-token {secret}"
        )
        redacted = redact_sensitive_text(text)

        self.assertNotIn(secret, redacted)
        self.assertNotIn("sk-test-secret-token", redacted)
        self.assertIn("key=[redacted]", redacted)
        self.assertIn("Bearer [redacted]", redacted)

    def test_process_dataframe_writes_shipping_total_with_fuel_surcharge(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "Manga Set Volumes 1-5",
                    "Description": "Existing description",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="A",
            book_weight_g=150,
            packaging_weight_kg=0,
            exchange_rate_jpy_per_usd=150,
            fuel_surcharge_percent=10.0,
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "FICP Base Shipping JPY"], "3487")
        self.assertEqual(result.loc[0, "FICP Fuel Surcharge Percent"], "10.00")
        self.assertEqual(result.loc[0, "FICP Fuel Surcharge JPY"], "349")
        self.assertEqual(result.loc[0, "FICP Shipping JPY"], "3836")
        self.assertEqual(result.loc[0, "FICP Shipping USD"], "25.57")
        self.assertEqual(result.loc[0, "Shipping Cost"], "25.57")
        self.assertEqual(result.loc[0, "FICP Shipping Includes Fuel Surcharge"], "Yes")

    def test_process_dataframe_uses_item_specific_book_weight_estimate(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "ヤングマガジン ヤンマガKC 漫画セット 全10巻",
                    "Description": "",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="F",
            book_weight_g=180,
            packaging_weight_kg=0.2,
            exchange_rate_jpy_per_usd=155,
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "Detected Book Count"], "10")
        self.assertEqual(result.loc[0, "Estimated Book Weight g"], "220")
        self.assertIn("seinen", result.loc[0, "Book Weight Evidence"].lower())
        self.assertEqual(result.loc[0, "Estimated Packaging Weight kg"], "0.350")
        self.assertIn("cardboard box", result.loc[0, "Packaging Materials"])
        self.assertEqual(result.loc[0, "Estimated Actual Weight kg"], "2.550")

    def test_process_dataframe_uses_dimensional_weight_for_shipping_when_larger(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "漫画セット 全5巻",
                    "Description": "",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="F",
            book_weight_g=150,
            packaging_weight_kg=0,
            exchange_rate_jpy_per_usd=150,
            package_length_cm=50,
            package_width_cm=40,
            package_height_cm=30,
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "Estimated Packaging Weight kg"], "0.450")
        self.assertEqual(result.loc[0, "Estimated Weight kg"], "1.200")
        self.assertEqual(result.loc[0, "Dimensional Weight kg"], "12.000")
        self.assertEqual(result.loc[0, "Billable Weight kg"], "12.000")
        self.assertEqual(result.loc[0, "Billable Weight Source"], "dimensional")
        self.assertEqual(result.loc[0, "FICP Billed Weight kg"], "12.000")
        self.assertEqual(result.loc[0, "FICP Shipping JPY"], "9353")
        self.assertEqual(result.loc[0, "Shipping Cost"], "62.35")

    def test_specifics_review_rows_show_status_per_field(self):
        row = pd.Series(
            {
                "C:Language": "Japanese",
                "C:Type": "Graphic Novel",
                "C:Publisher": "",
                "C:Original Language": "Japanese",
                "Specifics Filled Fields": "C:Language=Japanese",
                "Specifics Existing Fields": "C:Type=Graphic Novel",
                "Specifics Not Filled Fields": "C:Publisher; C:Original Language",
                "Specifics Fill Notes": "C:Language=Japanese (Japanese manga/source text evidence)",
            }
        )
        rows = build_specifics_review_rows(row, processed=True)
        by_column = {item["column"]: item for item in rows}
        self.assertEqual(by_column["C:Language"]["status"], "補完")
        self.assertIn("Japanese manga/source text evidence", by_column["C:Language"]["reason"])
        self.assertEqual(by_column["C:Type"]["status"], "既存値")
        self.assertEqual(by_column["C:Publisher"]["status"], "未補完")
        self.assertIn("C:Original Language", by_column)

    def test_specifics_summary_items_prioritize_important_filled_fields(self):
        row = pd.Series(
            {
                "C:Grade": "Near Mint",
                "C:Artist/Writer": "Tatsuya Endo",
                "C:Genre": "Action, Comedy, Slice of Life, Shonen",
                "C:Publisher": "Shueisha",
                "C:Format": "Paperback",
                "Specifics Filled Fields": (
                    "C:Format=Paperback; C:Grade=Near Mint; C:Artist/Writer=Tatsuya Endo; "
                    "C:Genre=Action, Comedy, Slice of Life, Shonen; C:Publisher=Shueisha"
                ),
                "Specifics Existing Fields": "",
                "Specifics Not Filled Fields": "C:Author",
                "Specifics Fill Notes": "C:Grade=Near Mint (Mercari/source condition: near unused)",
            }
        )
        items = build_specifics_summary_items(row, processed=True)
        labels = [item["label"] for item in items]
        values = {item["column"]: item["value"] for item in items}
        self.assertLess(labels.index("Grade"), labels.index("Format"))
        self.assertEqual(values["C:Grade"], "Near Mint")
        self.assertEqual(values["C:Artist/Writer"], "Tatsuya Endo")

    def test_process_dataframe_fills_dynamic_csv_specific_columns(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "Jujutsu Kaisen Volumes 1-16 Set by Gege Akutami",
                    "Description": "Publisher: Shueisha 少年ジャンプ",
                    "C:Brand": "NO BRAND",
                    "C:Original Language": "NA",
                    "C:Narrative Type": "NA",
                    "C:Signed": "NA",
                    "C:Personalized": "NA",
                    "C:Autograph Authentication": "NA",
                    "C:Autograph Authentication Number": "NA",
                    "C:California Prop 65 Warning": "NA",
                    "C:Certification Number": "NA",
                    "C:Character": "NA",
                    "C:Custom Bundle": "NA",
                    "C:Topic": "NA",
                    "C:Tradition": "NA",
                    "C:Unit of Sale": "NA",
                    "C:Unit Quantity": "NA",
                    "C:Unit Type": "NA",
                    "C:Number of Books": "NA",
                    "C:Item Weight": "NA",
                    "C:ISBN": "NA",
                    "C:Series Title": "NA",
                    "C:Artist/Writer": "NA",
                    "C:Features": "NA",
                    "C:Grade": "NA",
                    "C:Era": "NA",
                    "C:Vintage": "NA",
                    "C:Material": "NA",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            book_weight_g=180,
            packaging_weight_kg=0.2,
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "C:Brand"], "Shueisha")
        self.assertEqual(result.loc[0, "C:Original Language"], "Japanese")
        self.assertEqual(result.loc[0, "C:Narrative Type"], "Fiction")
        self.assertEqual(result.loc[0, "C:Signed"], "No")
        self.assertEqual(result.loc[0, "C:Personalized"], "No")
        self.assertEqual(result.loc[0, "C:Autograph Authentication"], "Not Applicable")
        self.assertEqual(result.loc[0, "C:Autograph Authentication Number"], "Not Applicable")
        self.assertEqual(result.loc[0, "C:California Prop 65 Warning"], "Not Applicable")
        self.assertEqual(result.loc[0, "C:Certification Number"], "Not Applicable")
        self.assertIn("Yuji Itadori", result.loc[0, "C:Character"])
        self.assertEqual(result.loc[0, "C:Custom Bundle"], "Yes")
        self.assertEqual(result.loc[0, "C:Topic"], "Manga")
        self.assertEqual(result.loc[0, "C:Tradition"], "Manga")
        self.assertEqual(result.loc[0, "C:Unit of Sale"], "Comic Book Lot")
        self.assertEqual(result.loc[0, "C:Unit Quantity"], "NA")
        self.assertEqual(result.loc[0, "C:Unit Type"], "NA")
        self.assertEqual(result.loc[0, "C:Number of Books"], "16")
        self.assertEqual(result.loc[0, "C:Item Weight"], "3.38 kg")
        self.assertEqual(result.loc[0, "C:ISBN"], "Does Not Apply")
        self.assertEqual(result.loc[0, "C:Series Title"], "Jujutsu Kaisen")
        self.assertEqual(result.loc[0, "C:Artist/Writer"], "Gege Akutami")
        self.assertIn("Set", result.loc[0, "C:Features"])
        self.assertEqual(result.loc[0, "C:Grade"], "NA")
        self.assertEqual(result.loc[0, "C:Era"], "Modern Age (1992-Now)")
        self.assertEqual(result.loc[0, "C:Vintage"], "No")
        self.assertEqual(result.loc[0, "C:Material"], "Paper")
        rows = build_specifics_review_rows(result.loc[0], processed=True)
        by_column = {item["column"]: item for item in rows}
        self.assertEqual(by_column["C:Brand"]["status"], "補完")
        self.assertEqual(by_column["C:Original Language"]["status"], "補完")
        self.assertEqual(by_column["C:Series Title"]["status"], "補完")
        self.assertEqual(by_column["C:Artist/Writer"]["status"], "補完")

    def test_process_dataframe_fills_grade_from_mercari_condition_text(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "SPY×FAMILY 1〜17巻セット by メルカリ",
                    "Description": "商品の状態 未使用に近い",
                    "C:Grade": "NA",
                    "C:Genre": "NA",
                    "C:Artist/Writer": "NA",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "C:Grade"], "Near Mint")
        self.assertEqual(result.loc[0, "C:Artist/Writer"], "Tatsuya Endo")
        self.assertIn("Action", result.loc[0, "C:Genre"])
        self.assertIn("Mercari/source condition", result.loc[0, "Specifics Fill Notes"])
        rows = build_specifics_review_rows(result.loc[0], processed=True)
        by_column = {item["column"]: item for item in rows}
        self.assertIn("near unused", by_column["C:Grade"]["reason"])

    def test_process_dataframe_does_not_use_ebay_template_good_condition_for_grade(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "SPY x FAMILY Volumes 1-17 Set",
                    "Description": '<![CDATA[<div style="max-width:720px;font-family:Arial">Good condition. Please review photos for exact condition.</div>]]>',
                    "C:Grade": "NA",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "C:Grade"], "NA")

    def test_process_dataframe_uses_free_reference_lookup_when_enabled(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "Reference Story Volumes 1-3 Set",
                    "Description": "",
                    "C:Publisher": "NA",
                    "C:Artist/Writer": "NA",
                    "C:Genre": "NA",
                    "C:Character": "NA",
                    "C:Publication Year": "NA",
                    "C:Era": "NA",
                    "C:Vintage": "NA",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            enable_scrape=False,
            enable_reference_lookup=True,
        )
        reference = {
            "status": "Wikidata QTEST: Reference Story",
            "values": {
                "author": "Reference Author",
                "publisher": "Reference Publisher",
                "genre": "Shojo",
                "characters": "Reference Hero; Reference Friend",
                "publication_year": "2020",
                "language": "Japanese",
                "country": "Japan",
            },
        }
        with patch("comic_ficp_streamlit_app.wikidata_reference_lookup", return_value=reference):
            result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "C:Publisher"], "Reference Publisher")
        self.assertEqual(result.loc[0, "C:Artist/Writer"], "Reference Author")
        self.assertEqual(result.loc[0, "C:Genre"], "Shojo")
        self.assertEqual(result.loc[0, "C:Character"], "Reference Hero; Reference Friend")
        self.assertEqual(result.loc[0, "C:Publication Year"], "2020")
        self.assertEqual(result.loc[0, "C:Era"], "Modern Age (1992-Now)")
        self.assertEqual(result.loc[0, "C:Vintage"], "No")
        self.assertIn("Wikidata QTEST", result.loc[0, "Specifics Fill Notes"])

    def test_process_dataframe_infers_url_from_image_when_url_blank(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "PicURL": "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg",
                    "Title": "漫画セット 全10巻",
                    "Description": "",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="F",
            book_weight_g=180,
            packaging_weight_kg=0.2,
            exchange_rate_jpy_per_usd=155,
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "商品URL"], "https://jp.mercari.com/item/m12345678901")
        self.assertEqual(result.loc[0, "Inferred Source URL"], "https://jp.mercari.com/item/m12345678901")
        self.assertEqual(result.loc[0, "Source URL Confidence"], "high")
        self.assertEqual(result.loc[0, "Detected Book Count"], "10")
        self.assertEqual(result.loc[0, "Estimated Packaging Weight kg"], "0.350")
        self.assertEqual(result.loc[0, "Estimated Weight kg"], "2.150")
        self.assertEqual(result.loc[0, "FICP US Zone"], "U.S. other / Canada / Puerto Rico (Zone F)")
        self.assertEqual(result.loc[0, "FICP Shipping JPY"], "3308")

    def test_process_dataframe_infers_url_when_product_url_column_contains_image_url(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "https://static.mercdn.net/item/detail/orig/photos/m3677344612_4.jpg?1782201200",
                    "Title": "Mint condition, 全12巻 extra volume",
                    "Description": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            zone="F",
            book_weight_g=200,
            packaging_weight_kg=0.65,
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "商品URL"], "https://jp.mercari.com/item/m3677344612")
        self.assertEqual(result.loc[0, "Inferred Source URL"], "https://jp.mercari.com/item/m3677344612")
        self.assertEqual(result.loc[0, "Source URL Confidence"], "high")
        self.assertIn("image URL", result.loc[0, "Source URL Evidence"])
        self.assertEqual(result.loc[0, "Detected Book Count"], "12")

    def test_process_dataframe_preserves_multiple_image_urls_when_picurl_is_url_column(self):
        frame = pd.DataFrame(
            [
                {
                    "PicURL": (
                        "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?1782201200|"
                        "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?1782201200|"
                        "https://static.mercdn.net/item/detail/orig/photos/m12345678901_3.jpg?1782201200"
                    ),
                    "Title": "Mint condition, 全12巻 extra volume",
                    "Description": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="PicURL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            zone="F",
            book_weight_g=200,
            packaging_weight_kg=0.65,
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "Inferred Source URL"], "https://jp.mercari.com/item/m12345678901")
        self.assertTrue(is_likely_image_url(result.loc[0, "PicURL"]))
        self.assertIn("m12345678901_2.jpg", result.loc[0, "Source Image URLs"])
        preview_urls = build_preview_image_urls(result.loc[0], "PicURL")
        self.assertEqual(len(preview_urls), 3)
        self.assertTrue(preview_urls[0].endswith("m12345678901_1.jpg?1782201200"))
        self.assertTrue(preview_urls[1].endswith("m12345678901_2.jpg?1782201200"))

    def test_process_dataframe_preserves_multiple_scraped_image_urls(self):
        original_picurl = (
            "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?1782201200|"
            "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?1782201200"
        )
        frame = pd.DataFrame(
            [
                {
                    "PicURL": original_picurl,
                    "Title": "Sample Manga Volumes 1-12 Set",
                    "Description": "",
                }
            ]
        )
        scraped = ListingData(
            title="Sample Manga Volumes 1-12 Set",
            image_url="https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?1782201200",
            image_urls=[
                "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?1782201200",
                "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?1782201200",
                "https://static.mercdn.net/item/detail/orig/photos/m12345678901_3.jpg?1782201200",
                "https://static.mercdn.net/thumb/item/webp/m99999999999_1.jpg?1782201200",
                "https://static.mercdn.net/item/detail/orig/photos/m99999999999_1.jpg?1782201200",
                "https://static.mercdn.net/thumb/members/webp/123456789.jpg?1782201200",
                "https://assets.eisa.mercari.com/cdn-cgi/image/quality=85/site-asset.jpg",
                "https://a.imgvc.com/i/bf.png?v=1",
            ],
            description="",
            details_text="",
            status="ok",
        )
        config = ProcessingConfig(
            url_col="PicURL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            zone="F",
            enable_scrape=True,
            enable_browser_scrape=False,
            request_delay_seconds=0,
        )

        with patch("comic_ficp_streamlit_app.scrape_listing", return_value=scraped):
            result = process_dataframe(frame, config)

        self.assertIn("m12345678901_2.jpg", result.loc[0, "Source Image URLs"])
        self.assertIn("m12345678901_3.jpg", result.loc[0, "Source Image URLs"])
        self.assertNotIn("m99999999999", result.loc[0, "Source Image URLs"])
        self.assertNotIn("thumb/members", result.loc[0, "Source Image URLs"])
        self.assertEqual(result.loc[0, "Rejected Source Image URL Count"], "5")
        self.assertEqual(result.loc[0, "PicURL"], original_picurl)
        preview_urls = build_preview_image_urls(result.loc[0], "PicURL")
        self.assertEqual(len(preview_urls), 3)

        export = build_export_dataframe(result, FreeShippingRollupOptions(enabled=False))
        self.assertEqual(export.loc[0, "Applied PicURL Image Count"], "3")
        self.assertIn("m12345678901_3.jpg", export.loc[0, "PicURL"])
        self.assertNotIn("m99999999999", export.loc[0, "PicURL"])
        self.assertEqual(export.loc[0, "Original PicURL"], original_picurl)

    def test_export_filters_polluted_cached_source_image_urls(self):
        own_1 = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?111"
        own_2 = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_2.jpg?111"
        frame = pd.DataFrame(
            [
                {
                    "PicURL": own_1,
                    "Main Image URL": own_1,
                    "Inferred Source URL": "https://jp.mercari.com/item/m12345678901",
                    "Source Image URLs": "|".join(
                        [
                            own_1,
                            own_2,
                            "https://static.mercdn.net/thumb/item/webp/m99999999999_1.jpg?222",
                            "https://static.mercdn.net/item/detail/orig/photos/m99999999999_1.jpg?222",
                            "https://static.mercdn.net/thumb/members/webp/123456789.jpg?333",
                            "https://a.imgvc.com/i/bf.png?v=1",
                        ]
                    ),
                }
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "PicURL"], f"{own_1}|{own_2}")
        self.assertEqual(export.loc[0, "Applied PicURL Image Count"], "2")
        self.assertEqual(export.loc[0, "Rejected PicURL Image Count"], "4")
        self.assertIn("rejected 4 off-listing images", export.loc[0, "PicURL Export Status"])

    def test_process_dataframe_keeps_existing_url_before_inferred_url(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "https://example.com/existing",
                    "PicURL": "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg",
                    "Title": "漫画セット 全10巻",
                    "Description": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            image_col="PicURL",
            title_col="Title",
            description_col="Description",
            zone="E",
            enable_scrape=False,
        )
        result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "商品URL"], "https://example.com/existing")
        self.assertEqual(result.loc[0, "Inferred Source URL"], "https://jp.mercari.com/item/m12345678901")
        self.assertEqual(result.loc[0, "Source URL Confidence"], "provided")
        self.assertEqual(result.loc[0, "FICP US Zone"], "U.S. western region (Zone E)")
        self.assertEqual(result.loc[0, "FICP Shipping JPY"], "3199")

    def test_process_dataframe_replaces_non_english_series_from_previous_autofill(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "https://jp.mercari.com/item/m12345678901",
                    "Title": "",
                    "Description": "",
                    "C:Series": "【美品✨+番外編】ひるなかの流星 やまもり三香 少女漫画 by メルカリ",
                    "C:Book Title": "【美品✨+番外編】ひるなかの流星 やまもり三香 少女漫画 by メルカリ",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            enable_scrape=True,
        )
        listing = ListingData(
            title="【美品✨+番外編】ひるなかの流星 やまもり三香 少女漫画 by メルカリ",
            description="目立った傷や汚れなし。全12巻セットです。",
            status="ok",
            source_url="https://jp.mercari.com/item/m12345678901",
        )
        with patch("comic_ficp_streamlit_app.scrape_listing", return_value=listing):
            result = process_dataframe(frame, config)
        self.assertEqual(result.loc[0, "C:Series"], "Daytime Shooting Star")
        self.assertEqual(result.loc[0, "C:Book Title"], "Daytime Shooting Star")
        self.assertFalse(contains_japanese_text(result.loc[0, "C:Series"]))
        self.assertIn("cleared C:Series", result.loc[0, "Specifics Fill Notes"])

    def test_process_dataframe_adds_only_relevant_mercari_details_to_description(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "https://jp.mercari.com/item/m12345678901",
                    "Title": "",
                    "Description": '<![CDATA[<div style="max-width:720px;"><p>Template text</p></div>]]>',
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="F",
            book_weight_g=180,
            packaging_weight_kg=0.2,
            exchange_rate_jpy_per_usd=155,
            enable_scrape=True,
        )
        listing = ListingData(
            title="Sample Manga Complete Set",
            description="定価500円で購入しました。目立った傷や汚れなし。全10巻セットです。",
            details_text="2巻にヤケがあります。もらい物です。発送はメルカリ便です。",
            status="ok",
            source_url="https://jp.mercari.com/item/m12345678901",
        )
        with patch("comic_ficp_streamlit_app.scrape_listing", return_value=listing):
            result = process_dataframe(frame, config)

        description = result.loc[0, "Description"]
        self.assertIn("Template text", description)
        self.assertIn("This manga set includes 10 books.", description)
        self.assertIn("no noticeable scratches or stains", description)
        self.assertIn("Page tanning or sun fading may be present", description)
        self.assertNotIn("定価", description)
        self.assertNotIn("購入", description)
        self.assertNotIn("もらい物", description)
        self.assertNotIn("source listing", description.lower())
        self.assertNotIn("detected", description.lower())
        self.assertFalse(contains_japanese_text(description))
        self.assertLess(description.index(AUTOFILL_MARKER_START), description.rindex("</div>"))
        self.assertNotIn("<![CDATA[", description)
        self.assertNotIn("]]>", description)
        self.assertIn("Description includes total book count: 10 books.", result.loc[0, "Description Detail Notes"])
        self.assertIn("no noticeable scratches or stains", result.loc[0, "Description Detail Notes"])
        self.assertFalse(contains_japanese_text(result.loc[0, "Description Detail Notes"]))
        self.assertIn("この漫画セットは10冊です。", result.loc[0, "Description Added Japanese"])
        self.assertIn("状態: 目立った傷や汚れはありません。", result.loc[0, "Description Added Japanese"])
        self.assertIn("日焼けや色あせがある可能性があります。", result.loc[0, "Description Added Japanese"])
        self.assertTrue(contains_japanese_text(result.loc[0, "Description Added Japanese"]))
        self.assertEqual(result.loc[0, "Source Listing Title"], "Sample Manga Complete Set")
        self.assertIn("目立った傷や汚れなし", result.loc[0, "Source Listing Description"])
        self.assertIn("2巻にヤケがあります", result.loc[0, "Source Listing Detail Preview"])

    def test_process_dataframe_excludes_missing_volume_listing_from_export_csv(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "https://jp.mercari.com/item/m12345678901",
                    "Title": "累・かさね セット 1-14巻",
                    "Description": '<![CDATA[<div>Template text</div>]]>',
                    "Shipping Cost": "",
                },
                {
                    "商品URL": "https://jp.mercari.com/item/m22222222222",
                    "Title": "Complete Manga Set 全5巻",
                    "Description": '<![CDATA[<div>Template text</div>]]>',
                    "Shipping Cost": "",
                },
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            enable_scrape=True,
        )
        listings = {
            "https://jp.mercari.com/item/m12345678901": ListingData(
                title="累・かさね セット 1-14巻",
                description="なぜか12かんだけありませんがその分お安くしております。",
                status="ok (browser rendered)",
                source_url="https://jp.mercari.com/item/m12345678901",
            ),
            "https://jp.mercari.com/item/m22222222222": ListingData(
                title="Complete Manga Set 全5巻",
                description="目立った傷や汚れなし。全5巻セットです。",
                image_url="https://static.mercdn.net/item/detail/orig/photos/m22222222222_1.jpg",
                status="ok (browser rendered)",
                source_url="https://jp.mercari.com/item/m22222222222",
            ),
        }

        def fake_scrape(url, **kwargs):
            return listings[url]

        with patch("comic_ficp_streamlit_app.scrape_listing", side_effect=fake_scrape):
            result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertIn("12かんだけありません", result.loc[0, "Exclusion Evidence"])
        self.assertIn("ダウンロードCSVから除外", result.loc[0, "Description Added Text"])
        self.assertIn("ダウンロードCSVから除外", result.loc[0, "Description Added Japanese"])

        export = build_export_dataframe(result)
        self.assertEqual(len(export), 1)
        self.assertEqual(export.iloc[0]["商品URL"], "https://jp.mercari.com/item/m22222222222")
        self.assertNotIn("m12345678901", "\n".join(export["商品URL"].astype(str).tolist()))

        exclusion_table = build_exclusion_table(result, "Title", "商品URL")
        self.assertEqual(len(exclusion_table), 1)
        self.assertEqual(exclusion_table.iloc[0]["Title"], "累・かさね セット 1-14巻")
        self.assertIn("12かんだけありません", exclusion_table.iloc[0]["Evidence"])
        self.assertIn("m12345678901", exclusion_table.iloc[0]["URL"])

    def test_process_dataframe_excludes_magazine_issue_from_export_csv(self):
        frame = pd.DataFrame(
            [
                {
                    "商品URL": "",
                    "Title": "週刊少年ジャンプ 2024年12号",
                    "Description": "表紙に小さな傷があります。",
                    "Shipping Cost": "",
                    "AI API Calls": "1",
                    "AI Total Tokens": "999",
                    "AI Estimated Cost USD": "0.123",
                    "AI Pricing Status": "standard paid estimate (old)",
                },
                {
                    "商品URL": "",
                    "Title": "ONE PIECE Jump Comics Volumes 1-10 Set",
                    "Description": "Complete manga set in good condition.",
                    "PicURL": "https://static.mercdn.net/item/detail/orig/photos/m22222222222_1.jpg",
                    "Shipping Cost": "",
                },
            ]
        )
        config = ProcessingConfig(
            url_col="商品URL",
            title_col="Title",
            description_col="Description",
            image_col="PicURL",
            shipping_col="Shipping Cost",
            enable_scrape=False,
        )

        result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertEqual(result.loc[0, "Exclusion Reason"], "雑誌・本誌商品の可能性があるため出品除外")
        self.assertIn("週刊少年ジャンプ", result.loc[0, "Exclusion Evidence"])
        self.assertIn("ダウンロードCSVから除外", result.loc[0, "Description Added Text"])
        self.assertEqual(result.loc[0, "AI API Calls"], "")
        self.assertEqual(result.loc[0, "AI Total Tokens"], "")
        self.assertEqual(result.loc[0, "AI Estimated Cost USD"], "")
        self.assertEqual(result.loc[1, "Listing Eligibility"], "OK")

        export = build_export_dataframe(result)
        self.assertEqual(len(export), 1)
        self.assertEqual(export.iloc[0]["Title"], "ONE PIECE Jump Comics Volumes 1-10 Set")


    def test_review_table_includes_image_thumbnail_url(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "Blue Lock Volumes 1-27 Set",
                    "商品URL": "https://jp.mercari.com/item/m11111111111",
                    "PicURL": "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.jpg",
                    "Detected Book Count": "27",
                }
            ]
        )

        table = build_review_table(frame, "Title", "商品URL", "PicURL")

        self.assertEqual(table.iloc[0]["Image"], "https://static.mercdn.net/item/detail/orig/photos/m11111111111_1.jpg")
        self.assertEqual(table.iloc[0]["Title"], "Blue Lock Volumes 1-27 Set")

    def test_exclusion_table_includes_image_thumbnail_url(self):
        frame = pd.DataFrame(
            [
                {
                    "Title": "Heavy Manga Set Volumes 1-60",
                    "Product URL": "https://jp.mercari.com/item/m22222222222",
                    "Main Image URL": "https://static.mercdn.net/item/detail/orig/photos/m22222222222_1.jpg",
                    "Listing Eligibility": "Excluded",
                    "Exclusion Reason": "Book count exceeds export limit",
                    "Exclusion Evidence": "60 books exceeds the configured maximum of 40 books.",
                }
            ]
        )

        table = build_exclusion_table(frame, "Title", "Product URL", "PicURL")

        self.assertEqual(table.iloc[0]["Image"], "https://static.mercdn.net/item/detail/orig/photos/m22222222222_1.jpg")
        self.assertEqual(table.iloc[0]["Reason"], "Book count exceeds export limit")


    def test_process_dataframe_excludes_rows_over_book_count_limit(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "Heavy Manga Set Volumes 1-60",
                    "Description": "Complete set in good condition.",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            max_book_count_for_export=40,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
            enable_ai_enrichment=True,
            ai_api_key="should-not-be-used",
        )

        with patch("comic_ficp_streamlit_app.enrich_listing_with_ai") as mocked_ai:
            result = process_dataframe(frame, config)

        mocked_ai.assert_not_called()
        self.assertEqual(result.loc[0, "Detected Book Count"], "60")
        self.assertEqual(result.loc[0, "Book Count Exclusion Limit"], "40")
        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertEqual(result.loc[0, "Exclusion Reason"], "Book count exceeds export limit")
        self.assertIn("60 books", result.loc[0, "Exclusion Evidence"])
        self.assertIn("40 books", result.loc[0, "Exclusion Evidence"])
        self.assertIn("exceeds the configured maximum", result.loc[0, "Description Added Text"])
        self.assertIn("最大冊数を超えている", result.loc[0, "Description Added Japanese"])
        self.assertTrue(result.loc[0, "Estimated Weight kg"])
        self.assertTrue(result.loc[0, "FICP Shipping USD"])

        export = build_export_dataframe(result)
        self.assertEqual(len(export), 0)

        exclusion_table = build_exclusion_table(result, "Title", "Product URL")
        self.assertEqual(len(exclusion_table), 1)
        self.assertEqual(exclusion_table.iloc[0]["Title"], "Heavy Manga Set Volumes 1-60")
        self.assertIn("60 books", exclusion_table.iloc[0]["Evidence"])

    def test_process_dataframe_sums_multiple_complete_ranges_then_excludes_if_over_limit(self):
        frame = pd.DataFrame(
            [
                {
                    "Product URL": "",
                    "Title": "浦安鉄筋家族1〜31全巻 元祖！浦安鉄筋家族1〜28全巻",
                    "Description": "2種類のタイトルの全巻セットです。",
                    "Shipping Cost": "",
                }
            ]
        )
        config = ProcessingConfig(
            url_col="Product URL",
            title_col="Title",
            description_col="Description",
            shipping_col="Shipping Cost",
            zone="E",
            book_weight_g=200,
            packaging_weight_kg=0.6,
            max_book_count_for_export=40,
            exchange_rate_jpy_per_usd=150,
            enable_scrape=False,
        )

        result = process_dataframe(frame, config)

        self.assertEqual(result.loc[0, "Detected Book Count"], "59")
        self.assertIn("1-31全巻", result.loc[0, "Book Count Evidence"])
        self.assertIn("1-28全巻", result.loc[0, "Book Count Evidence"])
        self.assertEqual(result.loc[0, "Listing Eligibility"], "Excluded")
        self.assertEqual(result.loc[0, "Exclusion Reason"], "Book count exceeds export limit")
        self.assertIn("59 books", result.loc[0, "Exclusion Evidence"])
        self.assertTrue(result.loc[0, "FICP Shipping USD"])
        self.assertEqual(len(build_export_dataframe(result)), 0)


if __name__ == "__main__":
    unittest.main()
