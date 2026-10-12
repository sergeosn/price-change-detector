import pytest
from django.core.exceptions import ValidationError

from tracker.currencies import ISO_4217_CODES, normalize_currency, validate_currency_code


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("usd", "USD"),
        (" CAD ", "CAD"),
        ("UAH", "UAH"),
        ("XYZ", None),
        ("US", None),
        ("", None),
        (None, None),
        (840, None),
        ("$", None),
    ],
)
def test_normalize_currency(value, expected):
    assert normalize_currency(value) == expected


def test_common_codes_are_known():
    assert {"UAH", "USD", "CAD", "EUR", "GBP", "PLN", "AUD"} <= ISO_4217_CODES


def test_validate_currency_code_accepts_lowercase_known_code():
    validate_currency_code("cad")


def test_validate_currency_code_rejects_unknown_code():
    with pytest.raises(ValidationError, match="XYZ"):
        validate_currency_code("XYZ")
