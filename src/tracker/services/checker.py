"""Checking one product: download → extract → compare → record."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from django.conf import settings
from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from notifications.base import Notifier
from tracker.models import CheckStatus, DomainRule, PriceChange, Product
from tracker.services.extractor import ExtractedPrice, ExtractionError, extract_price
from tracker.services.fetcher import FetchError, PageFetcher

logger = logging.getLogger(__name__)


class CurrencyMismatchError(Exception):
    """The page states a currency different from the one configured for the shop."""


@dataclass(frozen=True)
class CheckResult:
    status: Literal["ok", "error"]
    price: Decimal | None
    changed: bool
    error: str | None


def check_product(
    product: Product,
    fetcher: PageFetcher,
    notifier: Notifier,
    now: datetime | None = None,
) -> CheckResult:
    """Check one product and record the outcome. Never raises for a failed check."""
    now = now or timezone.now()
    try:
        html = fetcher.fetch(product.url)
        extracted = extract_price(html, _selector_for(product))
        with transaction.atomic():
            _apply_currency(product.domain, extracted.currency)
            change = _record_price(product, extracted, now)
    except (FetchError, ExtractionError, CurrencyMismatchError, Product.DoesNotExist) as exc:
        return _record_error(product, str(exc), now)
    except Exception as exc:
        logger.exception("Unexpected error while checking product %s", product.pk)
        return _record_error(product, f"Unexpected error: {exc.__class__.__name__}: {exc}", now)

    if change is not None:
        _notify(notifier, product, change)
    return CheckResult(status="ok", price=extracted.amount, changed=change is not None, error=None)


def select_due_products(now: datetime) -> QuerySet[Product]:
    """Active products never checked or checked at least CHECK_INTERVAL_HOURS ago."""
    threshold = now - timedelta(hours=settings.CHECK_INTERVAL_HOURS)
    return (
        Product.objects.filter(is_active=True)
        .filter(Q(last_checked_at__isnull=True) | Q(last_checked_at__lte=threshold))
        .order_by(F("last_checked_at").asc(nulls_first=True), "pk")
    )


def _selector_for(product: Product) -> str | None:
    if product.price_selector:
        return product.price_selector
    rule_selector = (
        DomainRule.objects.filter(domain=product.domain)
        .values_list("price_selector", flat=True)
        .first()
    )
    return rule_selector or None


def _apply_currency(domain: str, code: str | None) -> None:
    """Learn the shop currency from the page, or reject a page in another currency."""
    if code is None:
        return
    rule, created = DomainRule.objects.get_or_create(domain=domain, defaults={"currency": code})
    if created:
        return
    if not rule.currency:
        rule.currency = code
        rule.save(update_fields=["currency", "updated_at"])
    elif rule.currency != code:
        raise CurrencyMismatchError(f"Currency mismatch: expected {rule.currency}, got {code}")


def _record_price(product: Product, extracted: ExtractedPrice, now: datetime) -> PriceChange | None:
    change = None
    if product.current_price != extracted.amount:
        change = PriceChange.objects.create(
            product=product,
            old_price=product.current_price,
            new_price=extracted.amount,
            detected_at=now,
        )
    fields = {
        "current_price": extracted.amount,
        "last_checked_at": now,
        "last_check_status": CheckStatus.OK,
        "last_error": "",
        "updated_at": now,
    }
    if not product.name and extracted.name:
        fields["name"] = extracted.name
    # update() instead of save(): concurrent edits of other fields (API/admin) survive,
    # and a product deleted meanwhile is detected instead of silently re-created.
    if Product.objects.filter(pk=product.pk).update(**fields) == 0:
        raise Product.DoesNotExist(f"Product {product.pk} was deleted during the check")
    for field, value in fields.items():
        setattr(product, field, value)
    return change


def _record_error(product: Product, message: str, now: datetime) -> CheckResult:
    fields = {
        "last_checked_at": now,
        "last_check_status": CheckStatus.ERROR,
        "last_error": message,
        "updated_at": now,
    }
    Product.objects.filter(pk=product.pk).update(**fields)
    for field, value in fields.items():
        setattr(product, field, value)
    return CheckResult(status="error", price=None, changed=False, error=message)


def _notify(notifier: Notifier, product: Product, change: PriceChange) -> None:
    try:
        notifier.price_changed(product, change)
    except Exception:
        logger.exception("Notification about product %s failed", product.pk)
