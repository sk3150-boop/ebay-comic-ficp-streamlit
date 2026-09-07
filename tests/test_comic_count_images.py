import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import comic_ficp_streamlit_app as app


class BookCountEvidenceTests(unittest.TestCase):
    def test_unicode_ranges(self):
        for dash in "−‐‑‒﹣–—－〜～":
            self.assertEqual(8, app.detect_book_count(f'「スプリガン」文庫１{dash}８巻')[0])
        self.assertEqual(6, app.detect_book_count('文庫３−８巻')[0])
        self.assertIsNone(app.detect_book_count('文庫 全巻')[0])

    def config(self, key="test"):
        return SimpleNamespace(enable_ai_enrichment=True, ai_api_key=key, ai_provider="gemini", ai_model="gemini-2.5-flash-lite")

    def test_no_key_does_not_download_or_call(self):
        with patch('comic_review_images.archive_review_image') as download, patch.object(app, 'call_gemini_generate_content') as api:
            count, status, usage = app.infer_book_count_from_images(self.config(''), ['https://static.mercdn.net/x.jpg'], '')
        self.assertIsNone(count)
        self.assertIn('APIキー未設定', status)
        self.assertEqual(0, usage.calls)
        download.assert_not_called()
        api.assert_not_called()

    def test_multimodal_count_and_usage(self):
        usage = app.APIUsage(provider='gemini', calls=1, total_tokens=100)
        answer = {'count': 8, 'confidence': 'high', 'evidence': '背表紙1から8を確認', 'conflict': False}
        with patch('comic_review_images.archive_review_image', return_value={'data': b'image'}) as download, patch.object(app, 'call_gemini_generate_content', return_value=app.AIAPIResponse(text=json.dumps(answer), usage=usage)) as api:
            count, evidence, result_usage = app.infer_book_count_from_images(self.config(), ['a', 'a', 'b', 'c', 'd'], '商品説明')
        self.assertEqual(8, count)
        self.assertEqual(3, download.call_count)
        self.assertIs(usage, result_usage)
        self.assertIn('inline_data', api.call_args.args[2]['contents'][0]['parts'][1])

    def test_uncertain_conflicting_invalid_responses_preserve_usage(self):
        for answer in ({'count': True}, {'count': 8, 'confidence': 'low'}, {'count': 8, 'confidence': 'high', 'conflict': True, 'evidence': '不一致'}, 'not json'):
            usage = app.APIUsage(calls=1)
            with patch('comic_review_images.archive_review_image', return_value={'data': b'image'}), patch.object(app, 'call_gemini_generate_content', return_value=app.AIAPIResponse(text=json.dumps(answer) if isinstance(answer, dict) else answer, usage=usage)):
                count, _, result_usage = app.infer_book_count_from_images(self.config(), ['a'], '')
            self.assertIsNone(count)
            self.assertEqual(1, result_usage.calls)
