"""Price extraction from HTML. Pure functions: no network, no database."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from bs4 import BeautifulSoup
from soupsieve import SelectorSyntaxError

from tracker.currencies import normalize_currency

CENT = Decimal("0.01")
# Largest amount the price columns can store: DecimalField(max_digits=12, decimal_places=2).
MAX_AMOUNT = Decimal("9999999999.99")
MAX_NAME_LENGTH = 255

# First number in the text: digits with spaces / separators between them.
_NUMBER_RE = re.compile(r"-?\d(?:[\d\s,.'   ]*\d)?")
_GROUPING_RE = re.compile(r"[\s'   ]")
# An explicit currency code right after or right before the number.
_CODE_AFTER_RE = re.compile(r"^\s*([A-Za-z]{3})(?![A-Za-z])")
_CODE_BEFORE_RE = re.compile(r"(?<![A-Za-z])([A-Za-z]{3})\s*$")


class ExtractionError(Exception):
    """The page holds no price we can recognise."""


@dataclass(frozen=True)
class ExtractedPrice:
    amount: Decimal
    currency: str | None  # ISO 4217 code, only when the page states it explicitly
    name: str | None


def extract_price(html: str, selector: str | None = None) -> ExtractedPrice:
    """Find the product price: JSON-LD → microdata → OpenGraph → CSS selector."""
    soup = BeautifulSoup(html, "lxml")
    found = _from_json_ld(soup) or _from_microdata(soup) or _from_opengraph(soup)
    if found is None and selector:
        found = _from_selector(soup, selector)
    if found is None:
        raise ExtractionError("Price not found")
    if found.name is None:
        found = replace(found, name=_clean_name(soup.title.get_text() if soup.title else None))
    return found


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


# --- strategies ------------------------------------------------------------------


def _from_json_ld(soup: BeautifulSoup) -> ExtractedPrice | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.get_text())
        except ValueError:
            continue
        for node in _walk_json_ld(data):
            if _is_product(node) and (found := _offer_price(node)):
                return found
    return None


def _walk_json_ld(data: object) -> Iterator[dict]:
    if isinstance(data, list):
        for item in data:
            yield from _walk_json_ld(item)
    elif isinstance(data, dict):
        yield data
        yield from _walk_json_ld(data.get("@graph", []))


def _is_product(node: dict) -> bool:
    node_type = node.get("@type")
    types = node_type if isinstance(node_type, list) else [node_type]
    return "Product" in types


def _offer_price(product: dict) -> ExtractedPrice | None:
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None
    amount = _structured_amount(offers.get("price"))
    if amount is None:
        amount = _structured_amount(offers.get("lowPrice"))
    if amount is None:
        return None
    return ExtractedPrice(
        amount=amount,
        currency=normalize_currency(offers.get("priceCurrency")),
        name=_clean_name(product.get("name")),
    )


def _from_microdata(soup: BeautifulSoup) -> ExtractedPrice | None:
    price_el = soup.find(attrs={"itemprop": "price"})
    if price_el is None:
        return None
    amount = _structured_amount(price_el.get("content") or price_el.get_text(" ", strip=True))
    if amount is None:
        return None
    currency_el = soup.find(attrs={"itemprop": "priceCurrency"})
    currency = None
    if currency_el is not None:
        currency = normalize_currency(
            currency_el.get("content") or currency_el.get_text(strip=True)
        )
    return ExtractedPrice(amount=amount, currency=currency, name=None)


def _from_opengraph(soup: BeautifulSoup) -> ExtractedPrice | None:
    amount_meta = soup.find("meta", attrs={"property": "product:price:amount"})
    if amount_meta is None:
        return None
    amount = _structured_amount(amount_meta.get("content"))
    if amount is None:
        return None
    currency_meta = soup.find("meta", attrs={"property": "product:price:currency"})
    currency = normalize_currency(currency_meta.get("content")) if currency_meta else None
    return ExtractedPrice(amount=amount, currency=currency, name=None)


def _from_selector(soup: BeautifulSoup, selector: str) -> ExtractedPrice | None:
    try:
        element = soup.select_one(selector)
    except SelectorSyntaxError as exc:
        raise ExtractionError(f"Invalid CSS selector: {selector}") from exc
    if element is None:
        return None
    try:
        amount, currency = parse_price(element.get_text(" ", strip=True))
    except ValueError:
        return None
    return ExtractedPrice(amount=amount, currency=currency, name=None)


# --- helpers ---------------------------------------------------------------------


def _structured_amount(value: object) -> Decimal | None:
    """Amount from structured data; None when missing, unparsable or not storable."""
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    text = str(value).strip()
    try:
        try:
            return _checked_amount(Decimal(text))
        except InvalidOperation:
            return parse_price(text)[0]
    except ValueError:
        return None


def _clean_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    name = " ".join(value.split())[:MAX_NAME_LENGTH]
    return name or None


def _code(match: re.Match[str] | None) -> str | None:
    return normalize_currency(match.group(1)) if match else None


def _to_amount(token: str) -> Decimal:
    try:
        amount = Decimal(_normalize_separators(token))
    except InvalidOperation as exc:
        raise ValueError(f"Not a number: {token!r}") from exc
    return _checked_amount(amount)


def _checked_amount(amount: Decimal) -> Decimal:
    """Round to cents and make sure the result is a storable, positive price.

    Raises ValueError otherwise; decimal.InvalidOperation never escapes.
    """
    if not amount.is_finite():
        raise ValueError(f"Not a finite number: {amount}")
    try:
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        # quantize() fails for digit runs longer than the decimal context precision.
        raise ValueError(f"Price is too large: {amount}") from exc
    # Checked after rounding so that a positive value below half a cent is rejected.
    if amount <= 0:
        raise ValueError(f"Price must be positive, got {amount}")
    if amount > MAX_AMOUNT:
        raise ValueError(f"Price is too large: {amount}")
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
