import pytest

from tracker.domains import normalize_domain


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("rozetka.com.ua", "rozetka.com.ua"),
        ("WWW.Rozetka.com.ua", "rozetka.com.ua"),
        ("https://www.amazon.ca/dp/B0BXYZ1234?ref=x", "amazon.ca"),
        ("http://shop.example:8080/item/42", "shop.example"),
        ("  Example.COM.  ", "example.com"),
        ("", ""),
        ("   ", ""),
        ("bad host.example", ""),
    ],
)
def test_normalize_domain(value, expected):
    assert normalize_domain(value) == expected
