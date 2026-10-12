from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tests.helpers import URL, FakeFetcher, FakeNotifier, css_page, jsonld_page, make_product
from tracker.models import CheckStatus, DomainRule, PriceChange, Product
from tracker.services.checker import CheckResult, check_product, select_due_products
from tracker.services.fetcher import FetchError

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
TWO_PRICES = (
    '<html><body><span class="product-price">100</span>'
    '<span class="rule-price">200</span></body></html>'
)


def check(product, html=None, *, fetcher=None, notifier=None):
    fetcher = fetcher or FakeFetcher({URL: html} if html is not None else {})
    return check_product(product, fetcher, notifier or FakeNotifier(), now=NOW)


def test_first_check_records_initial_price():
    product = make_product()
    notifier = FakeNotifier()

    result = check(product, jsonld_page("37999", "UAH"), notifier=notifier)

    assert result == CheckResult(status="ok", price=Decimal("37999.00"), changed=True, error=None)
    change = PriceChange.objects.get(product=product)
    assert (change.old_price, change.new_price, change.detected_at) == (
        None,
        Decimal("37999.00"),
        NOW,
    )
    product.refresh_from_db()
    assert product.current_price == Decimal("37999.00")
    assert product.last_checked_at == NOW
    assert product.last_check_status == CheckStatus.OK
    assert product.last_error == ""
    assert notifier.calls == [(product, change)]


def test_changed_price_appends_history():
    product = make_product(current_price=Decimal("37999.00"), last_check_status=CheckStatus.OK)

    result = check(product, jsonld_page("34999", "UAH"))

    assert result.changed is True
    change = PriceChange.objects.get(product=product)
    assert (change.old_price, change.new_price) == (Decimal("37999.00"), Decimal("34999.00"))


def test_unchanged_price_only_updates_check_time():
    product = make_product(current_price=Decimal("37999.00"))
    notifier = FakeNotifier()

    result = check(product, jsonld_page("37999.00", "UAH"), notifier=notifier)

    assert result == CheckResult(status="ok", price=Decimal("37999.00"), changed=False, error=None)
    assert PriceChange.objects.count() == 0
    assert notifier.calls == []
    product.refresh_from_db()
    assert product.last_checked_at == NOW


def test_fetch_error_is_recorded_and_price_kept():
    product = make_product(current_price=Decimal("100.00"))

    result = check(product, fetcher=FakeFetcher(error=FetchError("HTTP 404")))

    assert result == CheckResult(status="error", price=None, changed=False, error="HTTP 404")
    product.refresh_from_db()
    assert product.last_check_status == CheckStatus.ERROR
    assert product.last_error == "HTTP 404"
    assert product.last_checked_at == NOW
    assert product.current_price == Decimal("100.00")
    assert PriceChange.objects.count() == 0


def test_missing_price_is_an_error():
    result = check(make_product(), "<html><body>Out of stock</body></html>")
    assert result.error == "Price not found"


def test_successful_check_clears_previous_error():
    product = make_product(last_check_status=CheckStatus.ERROR, last_error="HTTP 500")
    check(product, jsonld_page("10"))
    product.refresh_from_db()
    assert (product.last_check_status, product.last_error) == (CheckStatus.OK, "")


def test_product_selector_wins_over_domain_rule_selector():
    DomainRule.objects.create(domain="shop.example", price_selector=".rule-price")
    product = make_product(price_selector=".product-price")
    assert check(product, TWO_PRICES).price == Decimal("100.00")


def test_domain_rule_selector_is_used_when_product_has_none():
    DomainRule.objects.create(domain="shop.example", price_selector=".rule-price")
    assert check(make_product(), TWO_PRICES).price == Decimal("200.00")


def test_empty_name_is_filled_from_page():
    product = make_product()
    check(product, jsonld_page("10", name="Apple iPhone 15"))
    product.refresh_from_db()
    assert product.name == "Apple iPhone 15"


def test_existing_name_is_kept():
    product = make_product(name="My iPhone")
    check(product, jsonld_page("10", name="Apple iPhone 15"))
    product.refresh_from_db()
    assert product.name == "My iPhone"


def test_stale_instance_does_not_duplicate_a_price_already_recorded():
    product = make_product(current_price=Decimal("100.00"))
    # Someone else (e.g. a manual check) recorded the new price after `product` was loaded.
    Product.objects.filter(pk=product.pk).update(current_price=Decimal("90.00"))
    notifier = FakeNotifier()

    result = check(product, jsonld_page("90", "UAH"), notifier=notifier)

    assert result == CheckResult(status="ok", price=Decimal("90.00"), changed=False, error=None)
    assert PriceChange.objects.count() == 0
    assert notifier.calls == []


def test_stale_instance_does_not_overwrite_a_name_set_meanwhile():
    product = make_product()
    assert product.name == ""
    Product.objects.filter(pk=product.pk).update(name="My iPhone")

    check(product, jsonld_page("10", name="Apple iPhone 15"))

    assert Product.objects.get(pk=product.pk).name == "My iPhone"


def test_currency_creates_domain_rule_when_missing():
    check(make_product(), jsonld_page("10", "UAH"))
    rule = DomainRule.objects.get(domain="shop.example")
    assert (rule.currency, rule.price_selector) == ("UAH", "")


def test_currency_fills_domain_rule_without_currency():
    DomainRule.objects.create(domain="shop.example", price_selector=".price")
    check(make_product(), jsonld_page("10", "CAD"))
    assert DomainRule.objects.get().currency == "CAD"


def test_matching_currency_passes():
    DomainRule.objects.create(domain="shop.example", currency="UAH")
    assert check(make_product(), jsonld_page("10", "UAH")).status == "ok"


def test_currency_mismatch_is_an_error_without_history():
    DomainRule.objects.create(domain="shop.example", currency="CAD")
    product = make_product(current_price=Decimal("139.99"))

    result = check(product, jsonld_page("99.99", "USD"))

    assert result.error == "Currency mismatch: expected CAD, got USD"
    assert PriceChange.objects.count() == 0
    product.refresh_from_db()
    assert product.current_price == Decimal("139.99")
    assert product.last_check_status == CheckStatus.ERROR


def test_page_without_currency_code_leaves_domain_rules_alone():
    result = check(make_product(price_selector=".price"), css_page("$139.99"))
    assert result.price == Decimal("139.99")
    assert DomainRule.objects.count() == 0


def test_notifier_failure_does_not_fail_the_check():
    product = make_product()
    result = check(product, jsonld_page("10"), notifier=FakeNotifier(error=RuntimeError("boom")))
    assert result.status == "ok"
    assert PriceChange.objects.filter(product=product).exists()


def test_unexpected_error_is_recorded():
    result = check(make_product(), fetcher=FakeFetcher(error=RuntimeError("bug")))
    assert result.status == "error"
    assert result.error == "Unexpected error: RuntimeError: bug"


def test_product_deleted_during_check_returns_error():
    product = make_product()
    Product.objects.filter(pk=product.pk).delete()

    result = check(product, jsonld_page("10", "UAH"))

    assert result.status == "error"
    assert result.error == f"Product {product.pk} was deleted during the check"
    assert PriceChange.objects.count() == 0
    assert DomainRule.objects.count() == 0


def test_check_time_defaults_to_now():
    product = make_product()
    check_product(product, FakeFetcher({URL: jsonld_page("10")}), FakeNotifier())
    product.refresh_from_db()
    assert product.last_checked_at is not None


def test_select_due_products(settings):
    settings.CHECK_INTERVAL_HOURS = 24
    never = make_product(url="https://shop.example/never")
    stale = make_product(
        url="https://shop.example/stale", last_checked_at=NOW - timedelta(hours=25)
    )
    boundary = make_product(
        url="https://shop.example/boundary", last_checked_at=NOW - timedelta(hours=24)
    )
    make_product(url="https://shop.example/fresh", last_checked_at=NOW - timedelta(hours=1))
    make_product(url="https://shop.example/inactive", is_active=False)

    assert list(select_due_products(NOW)) == [never, stale, boundary]
