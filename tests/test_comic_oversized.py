import unittest
import pandas as pd
import comic_ficp_streamlit_app as app


class OversizedMangaTests(unittest.TestCase):
    def test_akira_and_magazine_size_excluded_even_one(self):
        for title in ('AKIRA volumes 1-4, 6 Japanese', 'ＡＫＩＲＡ 1巻', '漫画 B5判 1冊', '漫画 A4サイズ', '大判コミック', 'Oversized manga'):
            self.assertTrue(app.detect_magazine_listing_issue(title).excluded, title)

    def test_standard_formats_and_shipping_materials_not_excluded(self):
        for title in ('Dragon Ball by Akira Toriyama', '漫画 B6判', '文庫 A6', 'A4封筒で発送', '大判ではありません'):
            self.assertFalse(app.detect_oversized_manga_issue(title).excluded, title)

    def test_range_plus_individual_volume_counts_union(self):
        for title in ('AKIRA volumes 1-4, 6 Japanese', 'AKIRA 1巻～4巻、6巻', '1-4, 4, 6巻'):
            self.assertEqual(5, app.detect_book_count(title)[0], title)

    def test_export_guard_rejects_previously_eligible_oversized(self):
        frame = pd.DataFrame([{'Title':'AKIRA volumes 1-4, 6 Japanese', 'Listing Eligibility':'Eligible'},
                              {'Title':'Ordinary manga', 'Listing Eligibility':'Eligible'}])
        self.assertEqual([False, True], app.build_export_eligibility_mask(frame).tolist())
        self.assertEqual('Eligible', frame.iloc[0]['Listing Eligibility'])
