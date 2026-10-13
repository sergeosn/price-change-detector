import pytest
from django.utils import timezone
from fastapi.testclient import TestClient

from tests.helpers import make_product
from tracker.models import DomainRule

pytestmark = pytest.mark.django_db(transaction=True)

BASE = "/api/v1/domain-rules"


def test_requires_api_key(anon_client):
    assert anon_client.get(BASE).status_code == 401


def test_rejects_wrong_api_key(api_app):
    response = TestClient(api_app, headers={"X-API-Key": "wrong"}).get(BASE)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API key"}


def test_create_normalizes_domain_and_currency(api_client):
    response = api_client.post(
        BASE,
        json={
            "domain": "https://WWW.Shop.Example/path",
            "currency": "cad",
            "price_selector": ".price",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert (body["domain"], body["currency"], body["price_selector"]) == (
        "shop.example",
        "CAD",
        ".price",
    )
    assert DomainRule.objects.get(pk=body["id"]).currency == "CAD"


def test_currency_and_selector_are_optional(api_client):
    body = api_client.post(BASE, json={"domain": "shop.example"}).json()
    assert (body["currency"], body["price_selector"]) == ("", "")


def test_duplicate_domain_after_normalization_is_409(api_client):
    DomainRule.objects.create(domain="shop.example")
    response = api_client.post(BASE, json={"domain": "www.shop.example"})
    assert response.status_code == 409
    assert response.json() == {"detail": "Domain rule for shop.example already exists"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"domain": ""},
        {"domain": "bad host"},
        {"domain": "shop.example", "currency": "XYZ"},
        {"domain": "shop.example", "currency": "US"},
        {"domain": "shop.example", "unknown": 1},
    ],
)
def test_create_validation_errors(api_client, payload):
    assert api_client.post(BASE, json=payload).status_code == 422


def test_list_is_sorted_by_domain_and_paginated(api_client):
    DomainRule.objects.create(domain="b.example")
    DomainRule.objects.create(domain="a.example")

    body = api_client.get(BASE).json()
    assert [rule["domain"] for rule in body["items"]] == ["a.example", "b.example"]
    assert (body["total"], body["limit"], body["offset"]) == (2, 50, 0)

    page = api_client.get(BASE, params={"limit": 1, "offset": 1}).json()
    assert [rule["domain"] for rule in page["items"]] == ["b.example"]
    assert page["total"] == 2


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}])
def test_list_rejects_bad_pagination(api_client, params):
    assert api_client.get(BASE, params=params).status_code == 422


def test_get_rule(api_client):
    rule = DomainRule.objects.create(domain="shop.example", currency="UAH")
    body = api_client.get(f"{BASE}/{rule.pk}").json()
    assert (body["id"], body["domain"], body["currency"]) == (rule.pk, "shop.example", "UAH")
    assert {"created_at", "updated_at"} <= body.keys()


def test_missing_rule_is_404(api_client):
    assert api_client.get(f"{BASE}/999").json() == {"detail": "Domain rule 999 not found"}
    assert api_client.get(f"{BASE}/999").status_code == 404
    assert api_client.patch(f"{BASE}/999", json={"currency": "USD"}).status_code == 404
    assert api_client.delete(f"{BASE}/999").status_code == 404


def test_patch_updates_only_given_fields(api_client):
    rule = DomainRule.objects.create(domain="shop.example", currency="UAH", price_selector=".price")
    body = api_client.patch(f"{BASE}/{rule.pk}", json={"currency": "usd"}).json()
    assert (body["domain"], body["currency"], body["price_selector"]) == (
        "shop.example",
        "USD",
        ".price",
    )


def test_patch_can_clear_currency(api_client):
    rule = DomainRule.objects.create(domain="shop.example", currency="UAH")
    assert api_client.patch(f"{BASE}/{rule.pk}", json={"currency": ""}).json()["currency"] == ""


def test_patch_to_existing_domain_is_409(api_client):
    DomainRule.objects.create(domain="a.example")
    rule = DomainRule.objects.create(domain="b.example")
    assert api_client.patch(f"{BASE}/{rule.pk}", json={"domain": "a.example"}).status_code == 409


@pytest.mark.parametrize(
    "payload",
    [{"currency": None}, {"domain": None}, {"domain": "bad host"}, {"price_selector": None}],
)
def test_patch_validation_errors(api_client, payload):
    rule = DomainRule.objects.create(domain="shop.example")
    assert api_client.patch(f"{BASE}/{rule.pk}", json=payload).status_code == 422


def test_delete_rule(api_client):
    rule = DomainRule.objects.create(domain="shop.example")
    response = api_client.delete(f"{BASE}/{rule.pk}")
    assert response.status_code == 204
    assert response.content == b""
    assert DomainRule.objects.count() == 0


@pytest.mark.parametrize("payload", [{"price_selector": ".price"}, {"currency": "CAD"}])
def test_changing_selector_or_currency_marks_shop_products_due(api_client, payload):
    product = make_product(last_checked_at=timezone.now())
    rule = DomainRule.objects.get(domain="shop.example")

    assert api_client.patch(f"{BASE}/{rule.pk}", json=payload).status_code == 200

    product.refresh_from_db()
    assert product.last_checked_at is None


def test_unchanged_selector_does_not_mark_products_due(api_client):
    checked_at = timezone.now()
    product = make_product(last_checked_at=checked_at)
    rule = DomainRule.objects.get(domain="shop.example")

    api_client.patch(f"{BASE}/{rule.pk}", json={"price_selector": ""})

    product.refresh_from_db()
    assert product.last_checked_at == checked_at


def test_creating_a_rule_marks_existing_shop_products_due(api_client):
    product = make_product(last_checked_at=timezone.now())
    DomainRule.objects.all().delete()

    api_client.post(BASE, json={"domain": "shop.example", "price_selector": ".price"})

    product.refresh_from_db()
    assert product.last_checked_at is None
