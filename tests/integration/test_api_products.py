from decimal import Decimal

import pytest
from django.utils import timezone

from tests.helpers import URL, jsonld_page, make_product
from tracker.models import CheckStatus, DomainRule, PriceChange, Product

pytestmark = pytest.mark.django_db(transaction=True)

BASE = "/api/v1/products"


def test_requires_api_key(anon_client):
    assert anon_client.get(BASE).status_code == 401


def test_create_checks_the_price_immediately(api_client, fake_fetcher, fake_notifier):
    fake_fetcher.pages[URL] = jsonld_page("37999", "UAH", name="Apple iPhone 15")

    response = api_client.post(BASE, json={"url": URL, "target_price": "35000"})

    assert response.status_code == 201
    body = response.json()
    assert body["url"] == URL
    assert body["domain"] == "shop.example"
    assert body["name"] == "Apple iPhone 15"
    assert body["current_price"] == "37999.00"
    assert body["target_price"] == "35000.00"
    assert body["currency"] == "UAH"
    assert body["last_check_status"] == "ok"
    assert body["last_error"] == ""
    assert PriceChange.objects.filter(product_id=body["id"]).count() == 1
    assert len(fake_notifier.calls) == 1


def test_create_without_check(api_client, fake_fetcher):
    response = api_client.post(BASE, json={"url": URL, "check_now": False})
    assert response.status_code == 201
    body = response.json()
    assert (body["last_check_status"], body["current_price"], body["currency"]) == (
        "never",
        None,
        None,
    )
    assert fake_fetcher.calls == []


def test_failed_first_check_still_creates_the_product(api_client):
    response = api_client.post(BASE, json={"url": URL})
    assert response.status_code == 201
    body = response.json()
    assert (body["last_check_status"], body["last_error"]) == ("error", "HTTP 404")


def test_duplicate_url_is_409(api_client):
    make_product()
    response = api_client.post(BASE, json={"url": URL, "check_now": False})
    assert response.status_code == 409
    assert response.json() == {"detail": f"Product with URL {URL} already exists"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": "ftp://shop.example/file"},
        {"url": "not a url"},
        {"url": URL, "target_price": "0"},
        {"url": URL, "target_price": "-1"},
        {"url": URL, "target_price": "10.999"},
        {"url": URL, "unknown": 1},
    ],
)
def test_create_validation_errors(api_client, payload):
    assert api_client.post(BASE, json=payload).status_code == 422


def test_list_filters_and_paginates(api_client):
    first = make_product(url="https://shop.example/a", last_check_status=CheckStatus.OK)
    second = make_product(
        url="https://shop.example/b", is_active=False, last_check_status=CheckStatus.ERROR
    )
    third = make_product(url="https://shop.example/c")

    body = api_client.get(BASE).json()
    assert [item["id"] for item in body["items"]] == [third.pk, second.pk, first.pk]
    assert (body["total"], body["limit"], body["offset"]) == (3, 50, 0)

    inactive = api_client.get(BASE, params={"is_active": "false"}).json()
    assert [item["id"] for item in inactive["items"]] == [second.pk]

    failed = api_client.get(BASE, params={"status": "error"}).json()
    assert [item["id"] for item in failed["items"]] == [second.pk]

    page = api_client.get(BASE, params={"limit": 1, "offset": 1}).json()
    assert ([item["id"] for item in page["items"]], page["total"]) == ([second.pk], 3)


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"status": "weird"}]
)
def test_list_rejects_bad_query(api_client, params):
    assert api_client.get(BASE, params=params).status_code == 422


def test_get_takes_currency_from_domain_rule(api_client):
    DomainRule.objects.create(domain="shop.example", currency="CAD")
    product = make_product(current_price=Decimal("139.99"))
    body = api_client.get(f"{BASE}/{product.pk}").json()
    assert (body["currency"], body["current_price"]) == ("CAD", "139.99")


def test_missing_product_is_404(api_client):
    response = api_client.get(f"{BASE}/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Product 999 not found"}
    assert api_client.patch(f"{BASE}/999", json={"name": "x"}).status_code == 404
    assert api_client.delete(f"{BASE}/999").status_code == 404


def test_patch_updates_fields(api_client):
    product = make_product()
    response = api_client.patch(
        f"{BASE}/{product.pk}",
        json={
            "name": "New name",
            "price_selector": ".price",
            "target_price": "99.5",
            "is_active": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["price_selector"], body["target_price"], body["is_active"]) == (
        "New name",
        ".price",
        "99.50",
        False,
    )
    product.refresh_from_db()
    assert product.target_price == Decimal("99.50")
    assert product.is_active is False


def test_patch_can_clear_target_price(api_client):
    product = make_product(target_price=Decimal("10.00"))
    body = api_client.patch(f"{BASE}/{product.pk}", json={"target_price": None}).json()
    assert body["target_price"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"url": "https://other.example/"},
        {"name": None},
        {"price_selector": None},
        {"is_active": None},
        {"target_price": "-1"},
    ],
)
def test_patch_validation_errors(api_client, payload):
    product = make_product()
    assert api_client.patch(f"{BASE}/{product.pk}", json=payload).status_code == 422


def test_delete_removes_product_and_history(api_client):
    product = make_product()
    PriceChange.objects.create(
        product=product, new_price=Decimal("10.00"), detected_at=timezone.now()
    )
    response = api_client.delete(f"{BASE}/{product.pk}")
    assert response.status_code == 204
    assert response.content == b""
    assert (Product.objects.count(), PriceChange.objects.count()) == (0, 0)
