import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.helpers import URL, make_product
from tracker.models import Product, ProductDocument
from tracker.services.corpus import export_corpus

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
OTHER_URL = "https://www.other.example/p/2"


def add_document(product: Product, text: str) -> None:
    ProductDocument.objects.create(
        product=product, title="Page title", text=text, content_hash="hash", fetched_at=NOW
    )


def read_records(path: Path) -> list[dict[str, str]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_writes_one_json_line_per_product_in_creation_order(tmp_path: Path):
    add_document(make_product(name="Kettle"), "Electric kettle, 1.7 litres.")
    add_document(make_product(url=OTHER_URL), "Lightweight tent.")
    path = tmp_path / "corpus.jsonl"

    assert export_corpus(path) == 2

    assert read_records(path) == [
        {
            "url": URL,
            "name": "Kettle",
            "domain": "shop.example",
            "text": "Electric kettle, 1.7 litres.",
        },
        {"url": OTHER_URL, "name": "", "domain": "other.example", "text": "Lightweight tent."},
    ]
    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_text_is_cut_to_the_first_1500_characters(tmp_path: Path):
    add_document(make_product(), "я" * 1499 + "бв")
    path = tmp_path / "corpus.jsonl"

    export_corpus(path)

    assert read_records(path)[0]["text"] == "я" * 1499 + "б"


def test_product_without_a_document_gets_an_empty_text(tmp_path: Path):
    make_product()
    path = tmp_path / "corpus.jsonl"

    assert export_corpus(path) == 1

    assert read_records(path) == [{"url": URL, "name": "", "domain": "shop.example", "text": ""}]


def test_non_ascii_text_is_not_escaped(tmp_path: Path):
    add_document(make_product(name="Кавомолка"), "Жорна зі сталі")
    path = tmp_path / "corpus.jsonl"

    export_corpus(path)

    content = path.read_text(encoding="utf-8")
    assert "Кавомолка" in content
    assert "Жорна зі сталі" in content


def test_creates_the_directory_and_replaces_an_earlier_export(tmp_path: Path):
    make_product()
    path = tmp_path / "data" / "corpus.jsonl"
    export_corpus(path)
    make_product(url=OTHER_URL)

    assert export_corpus(path) == 2

    assert [record["url"] for record in read_records(path)] == [URL, OTHER_URL]
