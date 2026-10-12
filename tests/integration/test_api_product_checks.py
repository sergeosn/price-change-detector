from datetime import UTC, datetime
from decimal import Decimal

import pytest

from tests.helpers import URL, jsonld_page, make_product
from tracker.models import CheckStatus, PriceChange

pytestmark = pytest.mark.django_db(transaction=True)

BASE = "/api/v1/products"


def test_history_is_newest_first_and_paginated(api_client):
    product = make_product()
    PriceChange.objects.create(
        product=product,
        old_price=None,
        new_price=Decimal("100.00"),
        detected_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    PriceChange.objects.create(
        product=product,
        old_price=Decimal("100.00"),
        new_price=Decimal("90.00"),
        detected_at=datetime(2026, 10, 2, tzinfo=UTC),
    )

    body = api_client.get(f"{BASE}/{product.pk}/history").json()
    assert body["total"] == 2
    assert [(item["old_price"], item["new_price"]) for item in body["items"]] == [
        ("100.00", "90.00"),
        (None, "100.00"),
    ]
    assert {"id", "detected_at"} <= body["items"][0].keys()

    page = api_client.get(f"{BASE}/{product.pk}/history", params={"limit": 1}).json()
    assert [item["new_price"] for item in page["items"]] == ["90.00"]


def test_history_of_missing_product_is_404(api_client):
    assert api_client.get(f"{BASE}/999/history").status_code == 404


def test_check_records_a_price_change(api_client, fake_fetcher, fake_notifier):
    product = make_product(current_price=Decimal("37999.00"), last_check_status=CheckStatus.OK)
    fake_fetcher.pages[URL] = jsonld_page("34999", "UAH")

    response = api_client.post(f"{BASE}/{product.pk}/check")

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == {"status": "ok", "price": "34999.00", "changed": True, "error": None}
    assert (body["product"]["current_price"], body["product"]["currency"]) == ("34999.00", "UAH")
    assert len(fake_notifier.calls) == 1


def test_check_reports_errors(api_client):
    product = make_product()
    body = api_client.post(f"{BASE}/{product.pk}/check").json()
    assert body["result"] == {
        "status": "error",
        "price": None,
        "changed": False,
        "error": "HTTP 404",
    }
    assert body["product"]["last_check_status"] == "error"


def test_check_of_missing_product_is_404(api_client):
    assert api_client.post(f"{BASE}/999/check").status_code == 404
