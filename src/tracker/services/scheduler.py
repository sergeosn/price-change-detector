"""One scheduler pass: check every product that is due."""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from notifications.base import Notifier
from tracker.services.checker import check_product, select_due_products
from tracker.services.fetcher import PageFetcher

logger = logging.getLogger(__name__)


@dataclass
class PassSummary:
    checked: int = 0
    ok: int = 0
    errors: int = 0


def run_due_checks(
    *,
    fetcher: PageFetcher,
    notifier: Notifier,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
) -> PassSummary:
    close_old_connections()
    products = list(select_due_products(now or timezone.now()))
    logger.info("Scheduler pass started: %d product(s) due", len(products))
    summary = PassSummary()
    for index, product in enumerate(products):
        if should_stop():
            logger.info("Stop requested, ending the pass early")
            break
        if index:
            sleep(random.uniform(settings.REQUEST_DELAY_MIN, settings.REQUEST_DELAY_MAX))
        summary.checked += 1
        try:
            result = check_product(product, fetcher, notifier)
        except Exception:
            summary.errors += 1
            logger.exception("Check of product %s crashed", product.pk)
            continue
        if result.status == "ok":
            summary.ok += 1
            logger.info("Product %s: %s (changed=%s)", product.pk, result.price, result.changed)
        else:
            summary.errors += 1
            logger.warning("Product %s: %s", product.pk, result.error)
    logger.info(
        "Scheduler pass finished: %d checked, %d ok, %d errors",
        summary.checked,
        summary.ok,
        summary.errors,
    )
    return summary
