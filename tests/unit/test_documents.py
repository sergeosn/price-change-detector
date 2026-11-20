from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import URL, FakeFetcher, load_fixture, make_product
from tracker.models import Chunk, ProductDocument
from tracker.services.content import chunk_text, extract_content
from tracker.services.documents import IndexSummary, index_products, sync_document
from tracker.services.fetcher import FetchError

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(days=1)
UK_PAGE = load_fixture("content_uk.html")
EN_PAGE = load_fixture("content_en.html")
EMPTY_PAGE = load_fixture("no_price.html")


def test_first_sync_stores_the_document_and_its_chunks():
    product = make_product()
    content = extract_content(UK_PAGE)

    assert sync_document(product, UK_PAGE, NOW) is True

    document = ProductDocument.objects.get(product=product)
    assert (document.title, document.text, document.fetched_at) == (
        "Кавомолка Arabella G55",
        content.text,
        NOW,
    )
    assert len(document.content_hash) == 64
    chunks = list(document.chunks.values_list("ordinal", "text"))
    assert chunks == list(enumerate(chunk_text(content.text)))
    assert len(chunks) == 2


def test_unchanged_content_keeps_the_chunks_and_updates_the_fetch_time():
    product = make_product()
    sync_document(product, UK_PAGE, NOW)
    document = ProductDocument.objects.get()
    chunk_ids = list(Chunk.objects.values_list("pk", flat=True))

    # Different markup, same title and text.
    assert sync_document(product, UK_PAGE.replace("<h2>", "<h3>"), LATER) is False

    assert list(Chunk.objects.values_list("pk", flat=True)) == chunk_ids
    unchanged = ProductDocument.objects.get()
    assert (unchanged.pk, unchanged.content_hash) == (document.pk, document.content_hash)
    assert unchanged.fetched_at == LATER


def test_changed_content_rebuilds_the_document_in_place():
    product = make_product()
    sync_document(product, UK_PAGE, NOW)
    old_document = ProductDocument.objects.get()
    old_chunk_ids = set(Chunk.objects.values_list("pk", flat=True))

    assert sync_document(product, EN_PAGE, LATER) is True

    document = ProductDocument.objects.get()
    assert document.pk == old_document.pk
    assert document.content_hash != old_document.content_hash
    assert (document.title, document.fetched_at) == ("Northpeak Trailhead 2 Tent", LATER)
    chunks = Chunk.objects.filter(document=document)
    assert [chunk.text for chunk in chunks] == chunk_text(extract_content(EN_PAGE).text)
    assert old_chunk_ids.isdisjoint(chunk.pk for chunk in chunks)
    assert Chunk.objects.count() == len(chunks)


def test_changed_title_alone_counts_as_changed_content():
    product = make_product()
    sync_document(product, EN_PAGE, NOW)

    renamed = EN_PAGE.replace("Northpeak Trailhead 2 Tent", "Northpeak Trailhead 2")
    assert sync_document(product, renamed, LATER) is True

    assert ProductDocument.objects.get().title == "Northpeak Trailhead 2"


def test_page_without_text_stores_nothing_and_keeps_an_existing_document():
    product = make_product()

    assert sync_document(product, EMPTY_PAGE, NOW) is False
    assert not ProductDocument.objects.exists()

    sync_document(product, EN_PAGE, NOW)
    assert sync_document(product, EMPTY_PAGE, LATER) is False
    document = ProductDocument.objects.get()
    assert (document.title, document.fetched_at) == ("Northpeak Trailhead 2 Tent", NOW)
    assert document.chunks.count() == 1


def test_documents_of_different_products_are_independent():
    first = make_product()
    second = make_product(url="https://shop.example/item/2")

    sync_document(first, UK_PAGE, NOW)
    sync_document(second, UK_PAGE, NOW)

    assert ProductDocument.objects.count() == 2
    assert Chunk.objects.count() == 4


def test_deleting_a_product_deletes_its_document_and_chunks():
    product = make_product()
    sync_document(product, UK_PAGE, NOW)

    product.delete()

    assert not ProductDocument.objects.exists()
    assert not Chunk.objects.exists()


def test_models_have_readable_names():
    product = make_product(name="Grinder")
    sync_document(product, EN_PAGE, NOW)
    document = ProductDocument.objects.get()

    assert str(document) == "Northpeak Trailhead 2 Tent"
    assert str(document.chunks.get()) == "Northpeak Trailhead 2 Tent #0"
    document.title = ""
    assert str(document) == "Grinder"


# --- index_products ------------------------------------------------------------------


def test_index_products_stores_documents_only_for_products_without_one():
    indexed = make_product()
    sync_document(indexed, EN_PAGE, NOW)
    missing = make_product(url="https://shop.example/item/2")
    fetcher = FakeFetcher({URL: UK_PAGE, missing.url: UK_PAGE})

    summary = index_products(fetcher=fetcher, now=LATER)

    assert summary == IndexSummary(fetched=1, rebuilt=1, errors=0)
    assert fetcher.calls == [missing.url]
    assert ProductDocument.objects.get(product=missing).fetched_at == LATER
    assert ProductDocument.objects.get(product=indexed).title == "Northpeak Trailhead 2 Tent"


def test_index_products_can_refetch_every_product():
    changed = make_product()
    sync_document(changed, EN_PAGE, NOW)
    unchanged = make_product(url="https://shop.example/item/2")
    sync_document(unchanged, EN_PAGE, NOW)
    inactive = make_product(url="https://shop.example/item/3", is_active=False)
    fetcher = FakeFetcher({URL: UK_PAGE, unchanged.url: EN_PAGE, inactive.url: EMPTY_PAGE})

    summary = index_products(fetcher=fetcher, reindex_all=True, now=LATER)

    assert summary == IndexSummary(fetched=3, rebuilt=1, errors=0)
    assert fetcher.calls == [URL, unchanged.url, inactive.url]
    assert ProductDocument.objects.get(product=changed).title == "Кавомолка Arabella G55"
    assert not ProductDocument.objects.filter(product=inactive).exists()


def test_index_products_counts_failures_and_goes_on():
    make_product()
    broken = make_product(url="https://shop.example/item/2")
    last = make_product(url="https://shop.example/item/3")

    class PartlyBrokenFetcher(FakeFetcher):
        def fetch(self, url: str) -> str:
            if url == broken.url:
                self.calls.append(url)
                raise RuntimeError("bug")
            return super().fetch(url)

    fetcher = PartlyBrokenFetcher({last.url: EN_PAGE})  # the first URL is a 404

    summary = index_products(fetcher=fetcher, now=NOW)

    assert summary == IndexSummary(fetched=1, rebuilt=1, errors=2)
    assert fetcher.calls == [URL, broken.url, last.url]
    assert ProductDocument.objects.get().product == last


def test_index_products_pauses_between_requests(settings):
    settings.REQUEST_DELAY_MIN = settings.REQUEST_DELAY_MAX = 2.0
    for index in range(3):
        make_product(url=f"https://shop.example/item/{index}")
    sleeps: list[float] = []

    index_products(fetcher=FakeFetcher(error=FetchError("HTTP 500")), sleep=sleeps.append)

    assert sleeps == [2.0, 2.0]
