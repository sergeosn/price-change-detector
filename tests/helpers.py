"""Test doubles and builders shared by test modules."""

import json

from tracker.models import PriceChange, Product
from tracker.services.fetcher import FetchError

URL = "https://shop.example/item/1"


class FakeFetcher:
    """PageFetcher double: serves HTML from `pages` by URL and records requested URLs."""

    def __init__(self, pages: dict[str, str] | None = None, error: Exception | None = None):
        self.pages = dict(pages or {})
        self.error = error
        self.calls: list[str] = []

    def fetch(self, url: str) -> str:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        if url not in self.pages:
            raise FetchError("HTTP 404")
        return self.pages[url]


class FakeNotifier:
    """Notifier double: records every notification, optionally fails."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[Product, PriceChange]] = []

    def price_changed(self, product: Product, change: PriceChange) -> None:
        self.calls.append((product, change))
        if self.error is not None:
            raise self.error


def jsonld_page(price: str, currency: str | None = "UAH", name: str = "Test product") -> str:
    offer: dict[str, str] = {"@type": "Offer", "price": price}
    if currency is not None:
        offer["priceCurrency"] = currency
    data = {"@context": "https://schema.org", "@type": "Product", "name": name, "offers": offer}
    return (
        "<html><head><title>Page title</title>"
        f'<script type="application/ld+json">{json.dumps(data)}</script>'
        "</head><body></body></html>"
    )


def css_page(text: str, css_class: str = "price") -> str:
    return (
        "<html><head><title>CSS page</title></head>"
        f'<body><div class="{css_class}">{text}</div></body></html>'
    )


def make_product(url: str = URL, **fields) -> Product:
    return Product.objects.create(url=url, **fields)
