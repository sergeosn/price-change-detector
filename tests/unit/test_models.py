from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from tracker.models import CheckStatus, DomainRule, PriceChange, Product

pytestmark = pytest.mark.django_db


def test_domain_rule_normalizes_domain_and_currency_on_save():
    rule = DomainRule.objects.create(domain="https://WWW.Shop.Example/path", currency="cad")
    rule.refresh_from_db()
    assert rule.domain == "shop.example"
    assert rule.currency == "CAD"
    assert str(rule) == "shop.example"


def test_domain_rule_rejects_unknown_currency():
    with pytest.raises(ValidationError) as excinfo:
        DomainRule(domain="shop.example", currency="XYZ").full_clean()
    assert "currency" in excinfo.value.message_dict


def test_domain_rule_detects_duplicate_after_normalization():
    DomainRule.objects.create(domain="shop.example")
    with pytest.raises(ValidationError) as excinfo:
        DomainRule(domain="WWW.shop.example").full_clean()
    assert "domain" in excinfo.value.message_dict


def test_domain_rule_rejects_invalid_domain():
    with pytest.raises(ValidationError) as excinfo:
        DomainRule(domain="bad host").full_clean()
    assert "domain" in excinfo.value.message_dict


def test_product_stores_normalized_domain_and_defaults():
    product = Product.objects.create(url="https://www.Amazon.ca/dp/B0BXYZ1234")
    assert product.domain == "amazon.ca"
    assert product.last_check_status == CheckStatus.NEVER
    assert product.is_active is True
    assert product.current_price is None
    assert str(product) == "https://www.Amazon.ca/dp/B0BXYZ1234"


def test_product_rejects_non_http_url():
    with pytest.raises(ValidationError) as excinfo:
        Product(url="ftp://shop.example/file").full_clean()
    assert "url" in excinfo.value.message_dict


@pytest.mark.parametrize("price", [Decimal("0"), Decimal("0.00"), Decimal("-5.00")])
def test_product_rejects_non_positive_target_price(price):
    with pytest.raises(ValidationError) as excinfo:
        Product(url="https://shop.example/item", target_price=price).full_clean()
    assert "target_price" in excinfo.value.message_dict


def test_product_accepts_minimal_positive_and_empty_target_price():
    Product(url="https://shop.example/a", target_price=Decimal("0.01")).full_clean()
    Product(url="https://shop.example/b", target_price=None).full_clean()


def test_with_currency_takes_currency_from_domain_rule():
    DomainRule.objects.create(domain="shop.example", currency="UAH")
    with_rule = Product.objects.create(url="https://shop.example/a")
    without_rule = Product.objects.create(url="https://other.example/b")
    currencies = {product.pk: product.currency for product in Product.objects.with_currency()}
    assert currencies == {with_rule.pk: "UAH", without_rule.pk: ""}


def test_price_changes_are_newest_first_and_deleted_with_product():
    product = Product.objects.create(url="https://shop.example/a", name="Kindle")
    older = PriceChange.objects.create(
        product=product,
        old_price=None,
        new_price=Decimal("100.00"),
        detected_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    newer = PriceChange.objects.create(
        product=product,
        old_price=Decimal("100.00"),
        new_price=Decimal("90.00"),
        detected_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    assert list(product.price_changes.all()) == [newer, older]
    assert str(newer) == "Kindle: 100.00 → 90.00"
    assert str(older) == "Kindle: — → 100.00"
    product.delete()
    assert PriceChange.objects.count() == 0


def test_migrations_are_up_to_date():
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)


def test_new_product_creates_empty_domain_rule():
    Product.objects.create(url="https://www.Shop.example/a")
    rule = DomainRule.objects.get()
    assert (rule.domain, rule.currency, rule.price_selector) == ("shop.example", "", "")


def test_new_product_keeps_existing_domain_rule():
    DomainRule.objects.create(domain="shop.example", currency="CAD", price_selector=".p")
    Product.objects.create(url="https://shop.example/a")
    Product.objects.create(url="https://shop.example/b")
    rules = DomainRule.objects.values_list("domain", "currency", "price_selector")
    assert list(rules) == [("shop.example", "CAD", ".p")]
