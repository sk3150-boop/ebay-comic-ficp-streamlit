"""Small, metadata-free copies of verified listing images for review history.

This deliberately does not accept arbitrary image hosts. Connections go directly
to a previously validated public IP while TLS still validates the original host;
environment proxy settings and a second DNS lookup cannot change the destination.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
import time
import warnings
from io import BytesIO
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError


ALLOWED_IMAGE_HOSTS = frozenset({"static.mercdn.net", "i.ebayimg.com"})
ALLOWED_IMAGE_MIMES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024
MAX_IMAGE_PIXELS = 36_000_000
MAX_IMAGE_DIMENSION = 16_000
MAX_REDIRECTS = 3
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 8
REQUEST_DEADLINE_SECONDS = 20


class ImageArchiveError(ValueError):
    """An intentionally short, URL-free failure code suitable for audit records."""


def _validated_url(url: str) -> tuple[str, str]:
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise ImageArchiveError("invalid_url")
    if any(ord(character) < 33 or ord(character) == 127 for character in url):
        raise ImageArchiveError("invalid_url")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        raise ImageArchiveError("invalid_url") from None
    if parsed.scheme != "https" or port not in (None, 443):
        raise ImageArchiveError("https_required")
    if parsed.username is not None or parsed.password is not None:
        raise ImageArchiveError("credentials_in_url")
    if host not in ALLOWED_IMAGE_HOSTS:
        raise ImageArchiveError("host_not_allowed")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    try:
        path.encode("ascii")
    except UnicodeEncodeError:
        raise ImageArchiveError("invalid_url") from None
    return host, path


def _resolve_public_addresses(host: str) -> list[tuple]:
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ImageArchiveError("dns_failed")
    unique = []
    seen = set()
    for family, socktype, proto, _canonname, sockaddr in addresses:
        if family not in (socket.AF_INET, socket.AF_INET6):
            raise ImageArchiveError("address_not_public")
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global or getattr(address, "ipv4_mapped", None):
            raise ImageArchiveError("address_not_public")
        key = (family, sockaddr)
        if key not in seen:
            seen.add(key)
            unique.append((family, socktype, proto, sockaddr))
    return unique


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: tuple):
        super().__init__(host, port=443, timeout=CONNECT_TIMEOUT_SECONDS,
                         context=ssl.create_default_context())
        self._validated_address = address

    def connect(self) -> None:
        family, socktype, proto, sockaddr = self._validated_address
        raw_socket = socket.socket(family, socktype, proto)
        try:
            raw_socket.settimeout(CONNECT_TIMEOUT_SECONDS)
            raw_socket.connect(sockaddr)
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
            self.sock.settimeout(READ_TIMEOUT_SECONDS)
        except BaseException:
            raw_socket.close()
            raise


def _read_response(response, connection: _PinnedHTTPSConnection, deadline: float) -> bytes:
    mime = str(response.getheader("Content-Type", "")).split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_IMAGE_MIMES:
        raise ImageArchiveError("unsupported_content_type")
    if str(response.getheader("Content-Encoding", "identity")).lower() not in ("", "identity"):
        raise ImageArchiveError("unsupported_content_encoding")
    declared_size = response.getheader("Content-Length")
    if declared_size is not None:
        try:
            size = int(declared_size)
        except (TypeError, ValueError):
            raise ImageArchiveError("invalid_content_length") from None
        if size < 0 or size > MAX_DOWNLOAD_BYTES:
            raise ImageArchiveError("download_too_large")
    chunks = []
    downloaded = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ImageArchiveError("download_timeout")
        if connection.sock is not None:
            connection.sock.settimeout(min(READ_TIMEOUT_SECONDS, remaining))
        chunk = response.read1(min(64 * 1024, MAX_DOWNLOAD_BYTES + 1 - downloaded))
        if not chunk:
            break
        chunks.append(chunk)
        downloaded += len(chunk)
        if downloaded > MAX_DOWNLOAD_BYTES:
            raise ImageArchiveError("download_too_large")
    if not downloaded:
        raise ImageArchiveError("empty_image")
    return b"".join(chunks)


def _download_verified_image(url: str) -> bytes:
    current_url = url
    deadline = time.monotonic() + REQUEST_DEADLINE_SECONDS
    for redirect_count in range(MAX_REDIRECTS + 1):
        host, path = _validated_url(current_url)
        addresses = _resolve_public_addresses(host)
        if time.monotonic() >= deadline:
            raise ImageArchiveError("download_timeout")
        # A single pinned address bounds retries and avoids duplicate requests.
        connection = _PinnedHTTPSConnection(host, addresses[0])
        try:
            connection.request("GET", path, headers={
                "Accept": "image/jpeg,image/png,image/webp,image/gif",
                "Accept-Encoding": "identity",
                "User-Agent": "ComicFICP-ReviewArchive/1.0",
                "Connection": "close",
            })
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location", "")
                if redirect_count == MAX_REDIRECTS or not location:
                    raise ImageArchiveError("redirect_limit")
                current_url = urljoin(current_url, location)
                # Validate before the next loop can resolve or contact its host.
                _validated_url(current_url)
                continue
            if response.status != 200:
                raise ImageArchiveError("http_error")
            return _read_response(response, connection, deadline)
        finally:
            connection.close()
    raise ImageArchiveError("redirect_limit")


def _make_thumbnail(data: bytes) -> bytes:
    if not data or len(data) > MAX_DOWNLOAD_BYTES:
        raise ImageArchiveError("download_too_large" if data else "empty_image")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as source:
            if source.format not in ("JPEG", "PNG", "WEBP", "GIF"):
                raise ImageArchiveError("unsupported_image_format")
            width, height = source.size
            if (width <= 0 or height <= 0 or max(width, height) > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS):
                raise ImageArchiveError("image_dimensions_too_large")
            source.seek(0)
            source.load()
            normalized = ImageOps.exif_transpose(source)
            normalized.thumbnail((480, 480), Image.Resampling.LANCZOS)
            # Create a new image so EXIF, comments, ICC, GPS and other metadata
            # cannot be copied into the archived file.
            thumbnail = Image.new("RGB", normalized.size, "white")
            if "A" in normalized.getbands() or "transparency" in normalized.info:
                rgba = normalized.convert("RGBA")
                thumbnail.paste(rgba, mask=rgba.getchannel("A"))
            else:
                thumbnail.paste(normalized.convert("RGB"))
    for quality in (85, 75, 65, 50, 35):
        output = BytesIO()
        thumbnail.save(output, format="JPEG", quality=quality, optimize=True)
        encoded = output.getvalue()
        if len(encoded) <= MAX_ARCHIVE_BYTES:
            return encoded
    raise ImageArchiveError("thumbnail_too_large")


def archive_review_image(url: str, verified: bool) -> dict:
    """Archive only a caller-verified representative image; failures are nonfatal.

    ``data`` is JPEG bytes, ``digest`` is their SHA-256, and ``mime`` is
    ``image/jpeg`` on success. Failure records never contain the input URL,
    exception text, credentials, response body or image bytes.
    """
    result = {"digest": "", "data": None, "mime": "", "status": "not_verified"}
    if verified is not True:
        return result
    if not url:
        result["status"] = "missing_url"
        return result
    try:
        _validated_url(url)
        thumbnail = _make_thumbnail(_download_verified_image(url))
        return {"digest": hashlib.sha256(thumbnail).hexdigest(), "data": thumbnail,
                "mime": "image/jpeg", "status": "saved"}
    except ImageArchiveError as exc:
        result["status"] = str(exc)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        result["status"] = "image_dimensions_too_large"
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        result["status"] = "image_unavailable"
    except (http.client.HTTPException, TimeoutError):
        result["status"] = "download_failed"
    except Exception:
        # A thumbnail must never abort saving a completed item's audit record.
        result["status"] = "archive_failed"
    return result
