import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from comic_ficp_streamlit_app import (  # noqa: E402
    AIEnrichment,
    AUTOFILL_MARKER_START,
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
    ProcessingConfig,
    ReferenceBookCountResult,
    append_description,
    apply_item_specifics,
    build_description_append,
    build_description_append_display_text,
    build_ebay_preflight_table,
    build_exclusion_table,
    build_export_dataframe,
    build_processing_diagnostic_table,
    build_preview_image_urls,
    build_review_table,
    build_preview_metric_items,
    build_source_detail_preview,
    create_public_user,
    build_specifics_review_rows,
    build_specifics_summary_items,
    calculate_billable_weight_kg,
    calculate_dimensional_weight_kg,
    calculate_ficp_shipping,
    calculate_fuel_surcharge_jpy,
    calculate_shipping_total_with_fuel,
    clean_source_listing_description,
    contains_japanese_text,
    delete_saved_api_key,
    default_ai_model_for_provider,
    delete_public_saved_api_key,
    diagnose_processed_row,
    detect_book_count,
    detect_book_count_limit_issue,
    detect_book_count_with_references,
    detect_magazine_listing_issue,
    detect_unlistable_listing_issue,
    estimate_book_weight_g,
    estimate_packaging_weight_kg,
    extract_json_object,
    extract_buyer_relevant_listing_details,
    fetch_usd_jpy_exchange_rate,
    get_uploaded_or_cached_csv,
    guess_columns,
    infer_mercari_url_from_image_url,
    infer_specifics,
    infer_specifics_with_notes,
    is_likely_image_url,
    lookup_complete_set_book_count,
    load_saved_api_key,
    load_public_saved_api_key,
    parse_mercari_rendered_listing,
    parse_ai_enrichment_payload,
    process_dataframe,
    redact_sensitive_text,
    authenticate_public_user,
    public_saved_api_key_exists,
    save_api_key,
    save_public_api_key,
    load_processed_dataframe_cache,
    saved_api_key_exists,
    save_processed_dataframe_cache,
    save_uploaded_csv_cache,
    translate_description_added_text_to_japanese,
)


class FakeUpload:
    def __init__(self, raw: bytes, name: str = "input.csv"):
        self._raw = raw
        self.name = name

    def getvalue(self) -> bytes:
        return self._raw


class FakeStreamlit:
    def __init__(self, query_params=None):
        self.session_state = {}
        self.query_params = query_params or {}


class ComicFicpLogicTest(unittest.TestCase):
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
        self.assertEqual(DEFAULT_FREE_SHIPPING_MARKUP_PERCENT, 10.0)
        self.assertEqual(ProcessingConfig().max_book_count_for_export, 40)
        self.assertTrue(FreeShippingRollupOptions().enabled)
        self.assertEqual(FreeShippingRollupOptions().markup_percent, 10.0)

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

    def test_build_export_dataframe_sets_condition_id_to_very_good(self):
        frame = pd.DataFrame(
            [
                {
                    "Category": "259111",
                    "ConditionID": "3000",
                    "Title": "Manga set",
                },
                {
                    "Category": "259109",
                    "ConditionID": "1000",
                    "Title": "Single volume manga",
                },
                {
                    "Category": "12345",
                    "ConditionID": "4000",
                    "Title": "Other category",
                },
            ]
        )

        export = build_export_dataframe(frame, FreeShippingRollupOptions(enabled=False))

        self.assertEqual(export.loc[0, "ConditionID"], "4000")
        self.assertEqual(export.loc[0, "Original ConditionID"], "3000")
        self.assertEqual(export.loc[0, "Applied ConditionID"], "4000")
        self.assertIn("Very Good", export.loc[0, "ConditionID Fix Status"])
        self.assertEqual(export.loc[1, "ConditionID"], "4000")
        self.assertEqual(export.loc[1, "Original ConditionID"], "1000")
        self.assertIn("Very Good", export.loc[1, "ConditionID Fix Status"])
        self.assertEqual(export.loc[2, "ConditionID"], "4000")
        self.assertEqual(export.loc[2, "ConditionID Fix Status"], "kept: Very Good")

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
            '<div class="listing-template">'
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

        self.assertTrue(result.startswith("<![CDATA["))
        self.assertTrue(result.endswith("]]>"))
        self.assertLess(result.index("Template overview."), result.index(AUTOFILL_MARKER_START))
        self.assertLess(result.index(AUTOFILL_MARKER_START), result.index("Payment Details"))

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
        self.assertIn("商品の状態 未使用に近い", listing.details_text)

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
        frame = pd.DataFrame(
            [
                {
                    "PicURL": "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg?1782201200",
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
        preview_urls = build_preview_image_urls(result.loc[0], "PicURL")
        self.assertEqual(len(preview_urls), 3)

        export = build_export_dataframe(result, FreeShippingRollupOptions(enabled=False))
        self.assertEqual(export.loc[0, "Applied PicURL Image Count"], "3")
        self.assertIn("m12345678901_3.jpg", export.loc[0, "PicURL"])

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
        self.assertTrue(description.rstrip().endswith("]]>"))
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
