from io import StringIO

import pytest
from django.core.management import call_command

from tests.helpers import URL, FakeFetcher, load_fixture, make_product
from tracker.models import ProductDocument

pytestmark = pytest.mark.django_db

OTHER_URL = "https://shop.example/item/2"


@pytest.fixture(autouse=True)
def fetcher(monkeypatch) -> FakeFetcher:
    fetcher = FakeFetcher(
        {URL: load_fixture("content_uk.html"), OTHER_URL: load_fixture("content_en.html")}
    )
    monkeypatch.setattr("tracker.management.commands.index_content.get_fetcher", lambda: fetcher)
    return fetcher


def run(*args: str) -> str:
    out = StringIO()
    call_command("index_content", *args, stdout=out)
    return out.getvalue()


def test_indexes_products_that_have_no_document(fetcher):
    product = make_product()
    other = make_product(url=OTHER_URL)

    assert "Fetched 2 page(s): 2 document(s) rebuilt, 0 error(s)" in run()
    assert ProductDocument.objects.get(product=product).title == "Кавомолка Arabella G55"
    assert ProductDocument.objects.get(product=other).chunks.count() == 1

    fetcher.calls.clear()
    assert "Fetched 0 page(s): 0 document(s) rebuilt, 0 error(s)" in run()
    assert fetcher.calls == []


def test_all_refetches_indexed_products_and_rebuilds_changed_documents(fetcher):
    make_product()
    make_product(url=OTHER_URL)
    run()
    fetcher.calls.clear()
    fetcher.pages[OTHER_URL] = fetcher.pages[OTHER_URL].replace("2 people", "3 people")

    assert "Fetched 2 page(s): 1 document(s) rebuilt, 0 error(s)" in run("--all")
    assert fetcher.calls == [URL, OTHER_URL]
    assert "Capacity: 3 people" in ProductDocument.objects.get(product__url=OTHER_URL).text


def test_reports_pages_that_could_not_be_fetched():
    make_product()
    make_product(url="https://shop.example/gone")

    assert "Fetched 1 page(s): 1 document(s) rebuilt, 1 error(s)" in run()
    assert ProductDocument.objects.count() == 1
