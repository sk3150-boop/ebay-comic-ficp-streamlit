import hashlib
import ipaddress
import socket
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch

from PIL import Image

import comic_review_images as images


IMAGE_URL = "https://static.mercdn.net/item/detail/orig/photos/m12345678901_1.jpg"
PUBLIC_ADDRESS = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, ("8.8.8.8", 443))


def make_image(mode="RGB", size=(1000, 750), color="red", image_format="PNG"):
    output = BytesIO()
    Image.new(mode, size, color).save(output, format=image_format)
    return output.getvalue()


class FakeResponse:
    def __init__(self, data=b"", status=200, headers=None):
        self.data = BytesIO(data)
        self.status = status
        self.headers = {"Content-Type": "image/jpeg", **(headers or {})}

    def getheader(self, key, default=None):
        return self.headers.get(key, default)

    def read1(self, size):
        return self.data.read(size)


class ReviewImageTests(unittest.TestCase):
    def test_unverified_never_downloads(self):
        with patch.object(images, "_download_verified_image") as download:
            for flag in (False, None, "true", 1):
                self.assertEqual(images.archive_review_image(IMAGE_URL, flag)["status"], "not_verified")
            download.assert_not_called()

    def test_valid_archive_is_small_metadata_free_jpeg(self):
        source = make_image()
        with patch.object(images, "_download_verified_image", return_value=source):
            result = images.archive_review_image(IMAGE_URL, True)
        self.assertEqual(result["status"], "saved")
        self.assertEqual(result["mime"], "image/jpeg")
        self.assertEqual(result["digest"], hashlib.sha256(result["data"]).hexdigest())
        self.assertLessEqual(len(result["data"]), images.MAX_ARCHIVE_BYTES)
        with Image.open(BytesIO(result["data"])) as thumbnail:
            self.assertEqual(thumbnail.size, (480, 360))
            self.assertEqual(thumbnail.mode, "RGB")
            self.assertNotIn("exif", thumbnail.info)

    def test_transparency_becomes_white(self):
        source = make_image("RGBA", (20, 10), (0, 0, 0, 0))
        with Image.open(BytesIO(images._make_thumbnail(source))) as thumbnail:
            self.assertEqual(thumbnail.getpixel((0, 0)), (255, 255, 255))

    def test_exif_orientation_is_applied_and_metadata_removed(self):
        source = Image.new("RGB", (10, 30), "blue")
        exif = source.getexif()
        exif[274] = 6
        exif[270] = "private metadata"
        output = BytesIO()
        source.save(output, format="JPEG", exif=exif)
        with Image.open(BytesIO(images._make_thumbnail(output.getvalue()))) as thumbnail:
            self.assertEqual(thumbnail.size, (30, 10))
            self.assertFalse(thumbnail.getexif())

    def test_bad_urls_rejected_without_download(self):
        with patch.object(images, "_download_verified_image") as download:
            for url in (
                "http://static.mercdn.net/item.jpg", "https://static.mercdn.net:444/item.jpg",
                "https://user:secret@static.mercdn.net/item.jpg", "https://127.0.0.1/item.jpg",
                "https://static.mercdn.net.attacker.example/item.jpg", "https://evil.example/item.jpg",
                "https://static.mercdn.net/item.jpg\r\nHost: evil.example", "https://[broken/item.jpg",
            ):
                with self.subTest(url=url):
                    result = images.archive_review_image(url, True)
                    self.assertIsNone(result["data"])
                    self.assertNotIn("secret", str(result))
                    self.assertNotIn(url, str(result))
            download.assert_not_called()

    def test_both_exact_known_hosts_allowed(self):
        for host in ("static.mercdn.net", "i.ebayimg.com"):
            self.assertEqual(images._validated_url(f"https://{host}:443/image.jpg?x=1")[0], host)

    def test_private_loopback_linklocal_reserved_or_mixed_dns_rejected(self):
        for ip in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "0.0.0.0", "192.168.1.1",
                   "::1", "fc00::1", "fe80::1", "::ffff:8.8.8.8"):
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
                     (family, socket.SOCK_STREAM, 6, "", (ip, 443))]
            with self.subTest(ip=ip), patch.object(images.socket, "getaddrinfo", return_value=infos):
                with self.assertRaisesRegex(images.ImageArchiveError, "address_not_public"):
                    images._resolve_public_addresses("static.mercdn.net")

    def test_public_dns_results_are_deduplicated(self):
        info = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
        with patch.object(images.socket, "getaddrinfo", return_value=[info, info]):
            self.assertEqual(images._resolve_public_addresses("static.mercdn.net"), [PUBLIC_ADDRESS])

    def test_connection_pins_ip_and_keeps_host_for_tls(self):
        context = MagicMock()
        raw = MagicMock()
        with patch.object(images.ssl, "create_default_context", return_value=context), \
                patch.object(images.socket, "socket", return_value=raw), \
                patch.object(images.socket, "getaddrinfo") as resolve:
            connection = images._PinnedHTTPSConnection("static.mercdn.net", PUBLIC_ADDRESS)
            connection.connect()
        raw.connect.assert_called_once_with(("8.8.8.8", 443))
        context.wrap_socket.assert_called_once_with(raw, server_hostname="static.mercdn.net")
        resolve.assert_not_called()

    def _download_with_responses(self, responses):
        connections = []
        for response in responses:
            connection = MagicMock()
            connection.getresponse.return_value = response
            connections.append(connection)
        resolver = patch.object(images, "_resolve_public_addresses", return_value=[PUBLIC_ADDRESS])
        transport = patch.object(images, "_PinnedHTTPSConnection", side_effect=connections)
        return resolver, transport, connections

    def test_oversized_content_length_rejected_before_body(self):
        response = FakeResponse(headers={"Content-Length": str(images.MAX_DOWNLOAD_BYTES + 1)})
        response.read1 = MagicMock()
        resolver, transport, connections = self._download_with_responses([response])
        with resolver, transport:
            with self.assertRaisesRegex(images.ImageArchiveError, "download_too_large"):
                images._download_verified_image(IMAGE_URL)
        response.read1.assert_not_called()
        connections[0].close.assert_called_once()

    def test_stream_size_limit_without_content_length(self):
        response = FakeResponse(b"x" * 200)
        resolver, transport, _ = self._download_with_responses([response])
        with resolver, transport, patch.object(images, "MAX_DOWNLOAD_BYTES", 100):
            with self.assertRaisesRegex(images.ImageArchiveError, "download_too_large"):
                images._download_verified_image(IMAGE_URL)

    def test_wrong_mime_and_compressed_response_rejected(self):
        for headers, expected in (({"Content-Type": "text/html"}, "unsupported_content_type"),
                                  ({"Content-Encoding": "gzip"}, "unsupported_content_encoding")):
            resolver, transport, _ = self._download_with_responses([FakeResponse(headers=headers)])
            with self.subTest(headers=headers), resolver, transport:
                with self.assertRaisesRegex(images.ImageArchiveError, expected):
                    images._download_verified_image(IMAGE_URL)

    def test_redirect_revalidated_before_contact(self):
        for target in ("https://127.0.0.1/image.jpg", "https://evil.example/image.jpg",
                       "http://static.mercdn.net/image.jpg"):
            response = FakeResponse(status=302, headers={"Location": target})
            resolver, transport, connections = self._download_with_responses([response])
            with self.subTest(target=target), resolver as resolve, transport as connect:
                with self.assertRaises(images.ImageArchiveError):
                    images._download_verified_image(IMAGE_URL)
                self.assertEqual(resolve.call_count, 1)
                self.assertEqual(connect.call_count, 1)
                connections[0].close.assert_called_once()

    def test_redirect_to_allowed_host_rechecks_dns(self):
        redirects = [FakeResponse(status=302, headers={"Location": "https://i.ebayimg.com/image.jpg"}),
                     FakeResponse(b"abc")]
        resolver, transport, connections = self._download_with_responses(redirects)
        with resolver as resolve, transport:
            self.assertEqual(images._download_verified_image(IMAGE_URL), b"abc")
        self.assertEqual(resolve.call_args_list[1].args, ("i.ebayimg.com",))
        for connection in connections:
            connection.close.assert_called_once()

    def test_redirect_limit(self):
        responses = [FakeResponse(status=302, headers={"Location": "/next.jpg"})] * 4
        resolver, transport, connections = self._download_with_responses(responses)
        with resolver, transport:
            with self.assertRaisesRegex(images.ImageArchiveError, "redirect_limit"):
                images._download_verified_image(IMAGE_URL)
        self.assertEqual(len(connections), 4)

    def test_invalid_and_oversized_images_return_nonfatal_status(self):
        for content in (b"not an image", b"GIF89a"):
            with patch.object(images, "_download_verified_image", return_value=content):
                result = images.archive_review_image(IMAGE_URL, True)
                self.assertIsNone(result["data"])
                self.assertEqual(result["status"], "image_unavailable")
        with patch.object(images, "_download_verified_image", return_value=make_image()), \
                patch.object(images, "MAX_IMAGE_PIXELS", 100):
            result = images.archive_review_image(IMAGE_URL, True)
            self.assertEqual(result["status"], "image_dimensions_too_large")

    def test_pillow_decompression_bomb_is_nonfatal(self):
        with patch.object(images, "_download_verified_image", return_value=b"test"), \
                patch.object(images.Image, "open", side_effect=Image.DecompressionBombError("private URL")):
            result = images.archive_review_image(IMAGE_URL, True)
        self.assertEqual(result["status"], "image_dimensions_too_large")
        self.assertNotIn("private", str(result))

    def test_network_error_does_not_expose_exception_or_url(self):
        with patch.object(images, "_download_verified_image", side_effect=OSError("password=hidden https://secret")):
            result = images.archive_review_image(IMAGE_URL, True)
        self.assertEqual(result["status"], "image_unavailable")
        self.assertNotIn("hidden", str(result))
        self.assertNotIn("https", str(result))


if __name__ == "__main__":
    unittest.main()
