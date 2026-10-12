from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import FakeFetcher, FakeNotifier, jsonld_page, make_product
from tracker.services.scheduler import PassSummary, run_due_checks

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


def run(fetcher, **kwargs):
    kwargs.setdefault("sleep", lambda seconds: None)
    return run_due_checks(fetcher=fetcher, notifier=FakeNotifier(), now=NOW, **kwargs)


def test_checks_only_due_products():
    due = make_product(url="https://shop.example/due")
    fresh = make_product(url="https://shop.example/fresh", last_checked_at=NOW - timedelta(hours=1))
    fetcher = FakeFetcher({due.url: jsonld_page("10"), fresh.url: jsonld_page("10")})

    assert run(fetcher) == PassSummary(checked=1, ok=1, errors=0)
    assert fetcher.calls == [due.url]


def test_counts_failed_checks():
    ok = make_product(url="https://shop.example/ok")
    make_product(url="https://shop.example/missing")
    assert run(FakeFetcher({ok.url: jsonld_page("10")})) == PassSummary(checked=2, ok=1, errors=1)


def test_sleeps_between_requests_but_not_before_the_first(settings):
    settings.REQUEST_DELAY_MIN = 1
    settings.REQUEST_DELAY_MAX = 3
    products = [make_product(url=f"https://shop.example/{i}") for i in range(3)]
    fetcher = FakeFetcher({product.url: jsonld_page("10") for product in products})
    delays: list[float] = []

    run(fetcher, sleep=delays.append)

    assert len(delays) == 2
    assert all(1 <= delay <= 3 for delay in delays)


def test_stop_request_ends_the_pass_early():
    products = [make_product(url=f"https://shop.example/{i}") for i in range(3)]
    fetcher = FakeFetcher({product.url: jsonld_page("10") for product in products})

    summary = run(fetcher, should_stop=lambda: len(fetcher.calls) >= 1)

    assert summary.checked == 1


def test_crashing_check_does_not_stop_the_pass(monkeypatch):
    make_product(url="https://shop.example/a")
    make_product(url="https://shop.example/b")

    def crash(product, fetcher, notifier):
        raise RuntimeError("database is locked")

    monkeypatch.setattr("tracker.services.scheduler.check_product", crash)
    assert run(FakeFetcher()) == PassSummary(checked=2, ok=0, errors=2)
