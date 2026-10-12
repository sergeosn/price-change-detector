"""Price extraction from HTML. Pure functions: no network, no database."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from tracker.currencies import normalize_currency

CENT = Decimal("0.01")
# Largest amount the price columns can store: DecimalField(max_digits=12, decimal_places=2).
MAX_AMOUNT = Decimal("9999999999.99")

# First number in the text: digits with spaces / separators between them.
_NUMBER_RE = re.compile(r"-?\d(?:[\d\s,.'   ]*\d)?")
_GROUPING_RE = re.compile(r"[\s'   ]")
# An explicit currency code right after or right before the number.
_CODE_AFTER_RE = re.compile(r"^\s*([A-Za-z]{3})(?![A-Za-z])")
_CODE_BEFORE_RE = re.compile(r"(?<![A-Za-z])([A-Za-z]{3})\s*$")


def parse_price(text: str) -> tuple[Decimal, str | None]:
    """Parse a human-written price such as '1 299,00 €' or 'CAD 15.99'.

    Returns the amount rounded to cents and the ISO 4217 code written next to the
    number, if any. Currency symbols are ambiguous ($ is USD, CAD, AUD...) and are
    ignored. Raises ValueError when the text holds no positive number.
    """
    match = _NUMBER_RE.search(text)
    if match is None:
        raise ValueError(f"No number in {text!r}")
    amount = _to_amount(_GROUPING_RE.sub("", match.group()))
    currency = _code(_CODE_AFTER_RE.match(text[match.end() :])) or _code(
        _CODE_BEFORE_RE.search(text[: match.start()])
    )
    return amount, currency


def _code(match: re.Match[str] | None) -> str | None:
    return normalize_currency(match.group(1)) if match else None


def _to_amount(token: str) -> Decimal:
    try:
        amount = Decimal(_normalize_separators(token))
        if not amount.is_finite() or amount <= 0:
            raise ValueError(f"Price must be positive, got {token!r}")
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        # quantize() fails for digit runs longer than the decimal context precision.
        raise ValueError(f"Not a number: {token!r}") from exc
    if amount > MAX_AMOUNT:
        raise ValueError(f"Price is too large: {token!r}")
    return amount


def _normalize_separators(token: str) -> str:
    """Turn '1.299,00' / '1,299.00' / '1,299' / '12,50' into a Decimal-friendly string."""
    has_comma, has_dot = "," in token, "." in token
    if has_comma and has_dot:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        return token.replace(thousands_sep, "").replace(decimal_sep, ".")
    if has_comma or has_dot:
        sep = "," if has_comma else "."
        parts = token.split(sep)
        if len(parts) > 2 or len(parts[-1]) == 3:
            return token.replace(sep, "")
        return token.replace(sep, ".")
    return token
