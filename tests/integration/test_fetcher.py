import httpx
import pytest
import respx

from tracker.services import fetcher as fetcher_module
from tracker.services.fetcher import FetchError, HttpxPageFetcher, get_fetcher

URL = "https://shop.example/item/1"


@respx.mock
def test_returns_page_html():
    respx.get(URL).mock(return_value=httpx.Response(200, html="<html>ok</html>"))
    assert HttpxPageFetcher(timeout=5).fetch(URL) == "<html>ok</html>"


@respx.mock
def test_sends_browser_like_headers():
    route = respx.get(URL).mock(return_value=httpx.Response(200, html="ok"))
    HttpxPageFetcher(timeout=5, accept_language="uk").fetch(URL)
    request = route.calls.last.request
    assert request.headers["User-Agent"].startswith("Mozilla/5.0")
    assert request.headers["Accept-Language"] == "uk"


@pytest.mark.parametrize("status", [404, 500])
@respx.mock
def test_non_success_status_raises(status):
    respx.get(URL).mock(return_value=httpx.Response(status, html="error"))
    with pytest.raises(FetchError, match=f"^HTTP {status}$"):
        HttpxPageFetcher(timeout=5).fetch(URL)


@respx.mock
def test_timeout_raises():
    respx.get(URL).mock(side_effect=httpx.ConnectTimeout("timed out"))
    with pytest.raises(FetchError, match=r"^Timeout after 5s$"):
        HttpxPageFetcher(timeout=5).fetch(URL)


@respx.mock
def test_network_error_raises():
    respx.get(URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(FetchError, match="^Request failed: connection refused$"):
        HttpxPageFetcher(timeout=5).fetch(URL)


@respx.mock
def test_follows_redirects():
    new_url = "https://shop.example/item/1-new"
    respx.get(URL).mock(return_value=httpx.Response(301, headers={"Location": new_url}))
    respx.get(new_url).mock(return_value=httpx.Response(200, html="moved"))
    assert HttpxPageFetcher(timeout=5).fetch(URL) == "moved"


@respx.mock
def test_non_html_content_type_is_rejected():
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, content=b"%PDF-1.7", headers={"Content-Type": "application/pdf"}
        )
    )
    with pytest.raises(FetchError, match="^Unsupported content type: application/pdf$"):
        HttpxPageFetcher(timeout=5).fetch(URL)


@respx.mock
def test_oversized_page_is_rejected(monkeypatch):
    monkeypatch.setattr(fetcher_module, "MAX_PAGE_BYTES", 10)
    respx.get(URL).mock(return_value=httpx.Response(200, html="<html>" + "x" * 50))
    with pytest.raises(FetchError, match="too large"):
        HttpxPageFetcher(timeout=5).fetch(URL)


@respx.mock
def test_charset_is_detected_from_meta_tag():
    page = '<html><head><meta charset="windows-1252"><title>Café crème</title></head></html>'
    respx.get(URL).mock(
        return_value=httpx.Response(
            200, content=page.encode("cp1252"), headers={"Content-Type": "text/html"}
        )
    )
    assert "Café crème" in HttpxPageFetcher(timeout=5).fetch(URL)


def test_defaults_come_from_settings(settings):
    settings.FETCH_TIMEOUT_SECONDS = 7.0
    settings.FETCH_ACCEPT_LANGUAGE = "en"
    fetcher = get_fetcher()
    assert isinstance(fetcher, HttpxPageFetcher)
    assert (fetcher.timeout, fetcher.accept_language) == (7.0, "en")
