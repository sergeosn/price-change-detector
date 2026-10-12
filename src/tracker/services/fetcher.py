"""Downloading product pages."""

import contextlib
from typing import Protocol

import httpx
from bs4.dammit import UnicodeDammit
from django.conf import settings

MAX_PAGE_BYTES = 5 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


class FetchError(Exception):
    """The page could not be downloaded."""


class PageFetcher(Protocol):
    def fetch(self, url: str) -> str:
        """Return the page HTML or raise FetchError."""
        ...


class HttpxPageFetcher:
    """Plain HTTP download. JavaScript is not executed (SPA shops are out of scope)."""

    def __init__(self, timeout: float | None = None, accept_language: str | None = None) -> None:
        self.timeout = settings.FETCH_TIMEOUT_SECONDS if timeout is None else timeout
        self.accept_language = (
            settings.FETCH_ACCEPT_LANGUAGE if accept_language is None else accept_language
        )

    def fetch(self, url: str) -> str:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": self.accept_language,
        }
        try:
            with (
                httpx.Client(
                    timeout=self.timeout, follow_redirects=True, headers=headers
                ) as client,
                client.stream("GET", url) as response,
            ):
                if not response.is_success:
                    raise FetchError(f"HTTP {response.status_code}")
                _check_content_type(response.headers.get("content-type", ""))
                body = _read_limited(response)
                charset = response.charset_encoding
        except httpx.TimeoutException as exc:
            raise FetchError(f"Timeout after {self.timeout:g}s") from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise FetchError(f"Request failed: {exc}") from exc
        return _decode(body, charset)


def get_fetcher() -> PageFetcher:
    return HttpxPageFetcher()


def _check_content_type(content_type: str) -> None:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type and "html" not in media_type and "xml" not in media_type:
        raise FetchError(f"Unsupported content type: {media_type}")


def _read_limited(response: httpx.Response) -> bytes:
    body = bytearray()
    for chunk in response.iter_bytes():
        body.extend(chunk)
        if len(body) > MAX_PAGE_BYTES:
            raise FetchError(f"Page is too large (>{MAX_PAGE_BYTES} bytes)")
    return bytes(body)


def _decode(body: bytes, charset: str | None) -> str:
    """Use the charset from the HTTP header; otherwise sniff <meta charset> and the bytes."""
    if charset:
        with contextlib.suppress(LookupError):
            return body.decode(charset, errors="replace")
    return UnicodeDammit(body, is_html=True).unicode_markup or ""
