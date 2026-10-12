from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tests.helpers import URL, FakeFetcher, FakeNotifier, jsonld_page, make_product
from tracker.models import CheckStatus, DomainRule, PriceChange

pytestmark = pytest.mark.django_db

PRODUCTS = reverse("admin:tracker_product_changelist")


@pytest.mark.parametrize("model", ["product", "domainrule", "pricechange"])
def test_changelist_opens(admin_client, model):
    response = admin_client.get(reverse(f"admin:tracker_{model}_changelist"))
    assert response.status_code == 200


def test_product_list_shows_price_with_shop_currency_and_status_badge(admin_client):
    DomainRule.objects.create(domain="shop.example", currency="CAD")
    make_product(current_price=Decimal("139.99"), last_check_status=CheckStatus.ERROR)

    content = admin_client.get(PRODUCTS).content.decode()

    assert "139.99 CAD" in content
    assert 'class="status-badge status-error"' in content


def test_product_list_query_count_does_not_grow_with_products(admin_client):
    make_product(url="https://a.example/1")
    with CaptureQueriesContext(connection) as one_product:
        admin_client.get(PRODUCTS)
    for index in range(5):
        make_product(url=f"https://shop{index}.example/item")
    with CaptureQueriesContext(connection) as six_products:
        admin_client.get(PRODUCTS)
    assert len(six_products) == len(one_product)


def test_url_is_editable_only_when_adding(admin_client):
    product = make_product()
    add_page = admin_client.get(reverse("admin:tracker_product_add")).content.decode()
    change_page = admin_client.get(
        reverse("admin:tracker_product_change", args=[product.pk])
    ).content.decode()
    assert 'name="url"' in add_page
    assert 'name="url"' not in change_page


def test_change_page_shows_price_history(admin_client):
    product = make_product()
    PriceChange.objects.create(
        product=product,
        old_price=Decimal("37999.00"),
        new_price=Decimal("34999.00"),
        detected_at=datetime(2026, 10, 15, tzinfo=UTC),
    )
    response = admin_client.get(reverse("admin:tracker_product_change", args=[product.pk]))
    assert response.status_code == 200
    assert "34999.00" in response.content.decode()


def test_check_now_action_checks_selected_products(admin_client, monkeypatch):
    product = make_product()
    fetcher = FakeFetcher({URL: jsonld_page("100", "UAH")})
    monkeypatch.setattr("tracker.admin.get_fetcher", lambda: fetcher)
    monkeypatch.setattr("tracker.admin.get_notifier", FakeNotifier)

    response = admin_client.post(
        PRODUCTS, {"action": "check_now", "_selected_action": [product.pk]}, follow=True
    )

    assert [str(message) for message in response.context["messages"]] == [
        "Checked: 1 succeeded, 0 failed."
    ]
    product.refresh_from_db()
    assert product.current_price == Decimal("100.00")


def test_check_now_action_reports_failures(admin_client, monkeypatch):
    product = make_product()
    monkeypatch.setattr("tracker.admin.get_fetcher", FakeFetcher)
    monkeypatch.setattr("tracker.admin.get_notifier", FakeNotifier)

    response = admin_client.post(
        PRODUCTS, {"action": "check_now", "_selected_action": [product.pk]}, follow=True
    )

    assert [str(message) for message in response.context["messages"]] == [
        "Checked: 0 succeeded, 1 failed."
    ]


def test_disable_and_enable_tracking_actions(admin_client):
    product = make_product()
    admin_client.post(PRODUCTS, {"action": "disable_tracking", "_selected_action": [product.pk]})
    product.refresh_from_db()
    assert product.is_active is False
    admin_client.post(PRODUCTS, {"action": "enable_tracking", "_selected_action": [product.pk]})
    product.refresh_from_db()
    assert product.is_active is True


def test_domain_rule_form_normalizes_input(admin_client):
    response = admin_client.post(
        reverse("admin:tracker_domainrule_add"),
        {"domain": "WWW.Shop.Example", "currency": "cad", "price_selector": ""},
    )
    assert response.status_code == 302
    rule = DomainRule.objects.get()
    assert (rule.domain, rule.currency) == ("shop.example", "CAD")


def test_domain_rule_form_rejects_unknown_currency(admin_client):
    response = admin_client.post(
        reverse("admin:tracker_domainrule_add"),
        {"domain": "shop.example", "currency": "XYZ", "price_selector": ""},
    )
    assert response.status_code == 200
    assert "Unknown ISO 4217 currency code" in response.content.decode()
    assert DomainRule.objects.count() == 0


def test_price_changes_cannot_be_added_by_hand(admin_client):
    assert admin_client.get(reverse("admin:tracker_pricechange_add")).status_code == 403
