from decimal import Decimal

import pytest

from tracker.services.extractor import parse_price


@pytest.mark.parametrize(
    ("text", "amount", "currency"),
    [
        ("1 299,00 ₴", "1299.00", None),
        ("$1,299.99", "1299.99", None),
        ("CAD 15.99", "15.99", "CAD"),
        ("1299 uah", "1299.00", "UAH"),
        ("15.99CAD", "15.99", "CAD"),
        ("1.299,00 €", "1299.00", None),
        ("1 299 zł", "1299.00", None),
        ("1 299 000 zł.", "1299000.00", None),
        ("1,299", "1299.00", None),
        ("12,50", "12.50", None),
        ("1,299,000", "1299000.00", None),
        ("1299 XYZ", "1299.00", None),
        ("Price: 49.999 USD", "49999.00", "USD"),
        # One separator followed by exactly 3 digits is a thousands separator (spec §4.1).
        ("0,995", "995.00", None),
        # Lowercase words are not taken for codes unless they touch the number.
        ("Price for all: 100", "100.00", None),
    ],
)
def test_parse_price(text, amount, currency):
    assert parse_price(text) == (Decimal(amount), currency)


@pytest.mark.parametrize("text", ["", "out of stock", "0", "0,00", "-5"])
def test_parse_price_rejects_non_prices(text):
    with pytest.raises(ValueError):
        parse_price(text)
