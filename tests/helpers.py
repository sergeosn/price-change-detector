"""Test doubles and builders shared by test modules."""

import itertools
import json
import math
import random
from collections.abc import Mapping, Sequence
from pathlib import Path

from django.utils import timezone

from tracker.models import Chunk, PriceChange, Product, ProductDocument
from tracker.services.answerer import ContextChunk, Generation, SubmittedAnswer, TokenUsage
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
    """Embedder double: a repeatable unit vector per text, records the texts it was given.

    `vectors` fixes the direction of chosen texts (the leading coordinates, the rest are 0),
    so a test decides which texts are close to each other.
    """

    def __init__(
        self,
        model_name: str = "fake-embedder",
        dimensions: int = 384,
        vectors: dict[str, Sequence[float]] | None = None,
    ):
        self.model_name = model_name
        self.dimensions = dimensions
        self.vectors = dict(vectors or {})
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
        if text in self.vectors:
            values = [*self.vectors[text]] + [0.0] * (self.dimensions - len(self.vectors[text]))
        else:
            rng = random.Random(text)
            values = [rng.uniform(-1, 1) for _ in range(self.dimensions)]
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]


class FakeAnswerer:
    """Answerer double: gives `reply` with `usage` and records what it was asked.

    Without a `reply` it answers "Fake answer" and cites the first chunk it was given.
    `replies` sets the reply to chosen questions; an exception there is raised instead.
    """

    def __init__(
        self,
        reply: SubmittedAnswer | None = None,
        usage: TokenUsage | None = None,
        error: Exception | None = None,
        replies: Mapping[str, SubmittedAnswer | Exception] | None = None,
    ):
        self.reply = reply
        self.replies = dict(replies or {})
        self.usage = usage or TokenUsage(prompt_tokens=120, completion_tokens=30, total_tokens=150)
        self.error = error
        self.calls: list[tuple[str, list[ContextChunk]]] = []

    def answer(self, question: str, chunks: Sequence[ContextChunk]) -> Generation:
        self.calls.append((question, list(chunks)))
        if self.error is not None:
            raise self.error
        reply = self.replies.get(question, self.reply) or SubmittedAnswer(
            answerable=True, answer="Fake answer", source_chunk_ids=[chunks[0].chunk_id]
        )
        if isinstance(reply, Exception):
            raise reply
        return Generation(answer=reply, usage=self.usage)


class FakeClock:
    """Clock double for code that reads the time before and after a call it measures.

    Every second reading is the next of `durations` (in seconds, repeated) later than the
    one before it, as if the measured call took that long. `advance` moves the time by hand.
    """

    def __init__(self, durations: Sequence[float]):
        self._durations = itertools.cycle(durations)
        self._now = 0.0
        self._measuring = False

    def __call__(self) -> float:
        if self._measuring:
            self._now += next(self._durations)
        self._measuring = not self._measuring
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


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


# --- Search corpus -----------------------------------------------------------------
# Five products. The fake vectors live on five axes, one per product (headphones, grinder,
# kettle, tent, backpack), so the cosine similarity of every query and chunk is known.

HEADPHONES = "Sony WH-1000XM5"
GRINDER = "Burr coffee grinder"
KETTLE = "Bosch TWK 7203"
TENT = "Two-person tent"
BACKPACK = "Hiking backpack 40 l"

HEADPHONES_INTRO = "Wireless over-ear headphones with active noise cancelling."
HEADPHONES_SPECS = "Model WH-1000XM5: 30 hours of battery life, USB-C charging."
GRINDER_TEXT = "Coffee grinder with steel burrs for espresso and filter."
KETTLE_TEXT = "Electric kettle, 1.7 litres, stainless steel."
TENT_TEXT = "Lightweight waterproof tent for two people."
BACKPACK_TEXT = "Backpack with a rain cover and a hip belt."

SEARCH_CORPUS: dict[str, dict[str, Sequence[float]]] = {
    HEADPHONES: {HEADPHONES_INTRO: [1, 0, 0, 0, 0], HEADPHONES_SPECS: [1, 0, 0, 0.1, 0]},
    GRINDER: {GRINDER_TEXT: [0, 1, 0, 0, 0]},
    KETTLE: {KETTLE_TEXT: [0, 0, 1, 0, 0]},
    TENT: {TENT_TEXT: [0, 0, 0, 1, 0]},
    BACKPACK: {BACKPACK_TEXT: [0, 0, 0, 0, 1]},
}

# Only the headphones contain these words, but the fake vector points at the camping gear:
# by cosine similarity the headphones chunks come last.
MODEL_QUERY = "WH-1000XM5"
# Shares no word with any text or name, but its fake vector points at the grinder.
PARAPHRASE_QUERY = "млинок для кави"
# Points at the headphones, a little closer to the intro chunk than to the specs chunk.
HEADPHONES_QUERY = "something to listen to music"

SEARCH_QUERY_VECTORS: dict[str, Sequence[float]] = {
    MODEL_QUERY: [0, 0.1, 0.3, 0.8, 0.5],
    PARAPHRASE_QUERY: [0, 1, 0, 0, 0],
    HEADPHONES_QUERY: [1, 0, 0, 0, 0],
}


def seed_search_corpus() -> FakeEmbedder:
    """Store the corpus with embedded chunks; returns the embedder that knows the queries."""
    chunk_vectors = {
        text: vector for chunks in SEARCH_CORPUS.values() for text, vector in chunks.items()
    }
    embedder = FakeEmbedder(vectors={**chunk_vectors, **SEARCH_QUERY_VECTORS})
    for number, (name, chunks) in enumerate(SEARCH_CORPUS.items(), start=1):
        document = ProductDocument.objects.create(
            product=make_product(url=f"https://shop.example/item/{number}", name=name),
            title=name,
            text="\n".join(chunks),
            content_hash=f"hash-{number}",
            fetched_at=timezone.now(),
        )
        Chunk.objects.bulk_create(
            Chunk(
                document=document,
                ordinal=ordinal,
                text=text,
                embedding=embedder.vector(text),
                embedding_model=embedder.model_name,
            )
            for ordinal, text in enumerate(chunks)
        )
    return embedder
