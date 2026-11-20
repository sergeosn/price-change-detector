"""Test doubles and builders shared by test modules."""

import json
import math
import random
from collections.abc import Sequence
from pathlib import Path

from tracker.models import PriceChange, Product
from tracker.services.fetcher import FetchError

URL = "https://shop.example/item/1"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "html"


def load_fixture(name: str) -> str:
    """Sample page from tests/fixtures/html."""
    return (FIXTURES / name).read_text(encoding="utf-8")


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


class FakeEmbedder:
    """Embedder double: a repeatable unit vector per text, records the texts it was given."""

    def __init__(self, model_name: str = "fake-embedder", dimensions: int = 384):
        self.model_name = model_name
        self.dimensions = dimensions
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [self.vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return self.vector(text)

    def vector(self, text: str) -> list[float]:
        """The same text always gets the same vector, as a query and as a document."""
        rng = random.Random(text)
        values = [rng.uniform(-1, 1) for _ in range(self.dimensions)]
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]


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
