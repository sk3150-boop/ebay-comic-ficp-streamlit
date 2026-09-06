import unittest
from comic_review_gallery import build_gallery_html, gallery_sources


class GalleryTests(unittest.TestCase):
    def test_archive_is_first_and_extra_images_keep_order(self):
        urls = [f'https://static.mercdn.net/item/detail/orig/photos/m123_1.jpg', 'https://i.ebayimg.com/image2.jpg']
        self.assertEqual(urls[1], gallery_sources(urls, b'jpeg')[1])
        self.assertTrue(gallery_sources(urls, b'jpeg')[0].startswith('data:image/jpeg;base64,'))

    def test_dedup_and_reject_unsafe_sources(self):
        good = 'https://i.ebayimg.com/1.jpg'
        self.assertEqual([good], gallery_sources([good, good, 'javascript:alert(1)', 'http://127.0.0.1/a', 'https://user:pass@i.ebayimg.com/a', 'https://evil.example/a']))

    def test_thumbnail_controls_are_client_only_and_escaped(self):
        html, height = build_gallery_html(['https://i.ebayimg.com/1.jpg', 'https://i.ebayimg.com/a" onload="evil.jpg'])
        self.assertIn('aria-label="画像2を大きく表示"', html)
        self.assertIn('&quot;', html)
        self.assertNotIn('src="https://i.ebayimg.com/a" onload=', html)
        self.assertIn('main.src = image.src', html)
        self.assertNotIn('window.parent', html)
        self.assertNotIn('fetch(', html)
        self.assertEqual(550, height)

    def test_empty_and_archive_only(self):
        self.assertEqual(('', 0), build_gallery_html([]))
        html, _ = build_gallery_html([], b'jpeg')
        self.assertIn('1 / 1', html)


if __name__ == '__main__':
    unittest.main()
