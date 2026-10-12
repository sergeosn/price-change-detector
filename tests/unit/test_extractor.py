import json
from decimal import Decimal
from pathlib import Path

import pytest

from tracker.services.extractor import ExtractedPrice, ExtractionError, extract_price

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "html"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def jsonld(data: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(data)}</script>'


@pytest.mark.parametrize(
    ("fixture", "amount", "currency", "name"),
    [
        ("jsonld_offer.html", "37999.00", "UAH", "Apple iPhone 15 128GB"),
        ("jsonld_graph.html", "1299.50", "USD", "Graph product"),
        ("jsonld_offers_list.html", "49.99", "CAD", "Kindle Paperwhite"),
        ("jsonld_aggregate.html", "1299.00", "EUR", "Aggregate product"),
        ("jsonld_broken.html", "10.00", "GBP", "Valid after broken"),
        ("microdata.html", "2450.00", "UAH", "Coffee grinder | Shop"),
        ("opengraph.html", "15.99", "CAD", "OG product"),
    ],
)
def test_structured_data_strategies(fixture, amount, currency, name):
    assert extract_price(load(fixture)) == ExtractedPrice(
        amount=Decimal(amount), currency=currency, name=name
    )


def test_json_ld_wins_over_other_strategies_and_selector():
    result = extract_price(load("priority.html"), selector=".price")
    assert result == ExtractedPrice(Decimal("100.00"), "USD", "Priority product")


def test_microdata_wins_over_opengraph():
    html = (
        '<html><head><meta property="product:price:amount" content="300"></head>'
        '<body><span itemprop="price" content="200"></span></body></html>'
    )
    assert extract_price(html) == ExtractedPrice(Decimal("200.00"), None, None)


def test_selector_is_the_fallback():
    result = extract_price(load("selector_only.html"), selector="div.product-price > b")
    assert result == ExtractedPrice(Decimal("1299.00"), None, "Selector product")


def test_product_without_offers_falls_through_to_microdata():
    html = (
        f"<html><head>{jsonld({'@type': 'Product', 'name': 'No offers'})}</head>"
        '<body><span itemprop="price" content="55"></span></body></html>'
    )
    assert extract_price(html).amount == Decimal("55.00")


def test_page_without_price_raises():
    with pytest.raises(ExtractionError, match="Price not found"):
        extract_price(load("no_price.html"), selector=".missing")


def test_selector_text_without_number_raises():
    html = '<html><body><div class="price">Out of stock</div></body></html>'
    with pytest.raises(ExtractionError, match="Price not found"):
        extract_price(html, selector=".price")


def test_invalid_selector_raises():
    with pytest.raises(ExtractionError, match=r"Invalid CSS selector: div\["):
        extract_price("<html></html>", selector="div[")


def test_zero_price_is_not_a_price():
    page = jsonld(
        {"@type": "Product", "name": "Sold out", "offers": {"price": "0", "priceCurrency": "UAH"}}
    )
    with pytest.raises(ExtractionError, match="Price not found"):
        extract_price(f"<html><head>{page}</head></html>")


@pytest.mark.parametrize("price", ["100000000000", "0.001"])
def test_structured_price_out_of_storable_range_is_not_a_price(price):
    page = jsonld({"@type": "Product", "name": "Odd", "offers": {"price": price}})
    with pytest.raises(ExtractionError, match="Price not found"):
        extract_price(f"<html><head>{page}</head></html>")


def test_unknown_currency_code_is_ignored():
    html = (
        '<html><head><meta property="product:price:amount" content="10">'
        '<meta property="product:price:currency" content="ABC"></head></html>'
    )
    assert extract_price(html).currency is None


def test_long_title_is_collapsed_and_truncated():
    title = "  Very\n   long " + "A" * 300
    html = (
        f"<html><head><title>{title}</title>"
        '<meta property="product:price:amount" content="10"></head></html>'
    )
    name = extract_price(html).name
    assert name is not None
    assert len(name) == 255
    assert name.startswith("Very long AAA")


def test_long_json_ld_name_is_truncated():
    page = jsonld({"@type": "Product", "name": "B" * 400, "offers": {"price": "10"}})
    assert len(extract_price(f"<html><head>{page}</head></html>").name) == 255
