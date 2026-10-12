"""Product operations used by the API (the admin works through ModelAdmin)."""

from decimal import Decimal

from django.db import IntegrityError, transaction

from notifications.base import Notifier
from tracker.models import Product
from tracker.services.checker import CheckResult, check_product
from tracker.services.errors import DuplicateError, NotFoundError
from tracker.services.fetcher import PageFetcher


def list_products(
    *, is_active: bool | None = None, status: str | None = None, limit: int, offset: int
) -> tuple[list[Product], int]:
    products = Product.objects.with_currency()
    if is_active is not None:
        products = products.filter(is_active=is_active)
    if status is not None:
        products = products.filter(last_check_status=status)
    return list(products[offset : offset + limit]), products.count()


def get_product(product_id: int) -> Product:
    try:
        return Product.objects.with_currency().get(pk=product_id)
    except Product.DoesNotExist:
        raise NotFoundError(f"Product {product_id} not found") from None


def create_product(
    *,
    url: str,
    name: str = "",
    price_selector: str = "",
    target_price: Decimal | None = None,
    is_active: bool = True,
) -> Product:
    product = Product(
        url=url,
        name=name,
        price_selector=price_selector,
        target_price=target_price,
        is_active=is_active,
    )
    try:
        with transaction.atomic():
            product.save()
    except IntegrityError:
        raise DuplicateError(f"Product with URL {url} already exists") from None
    return get_product(product.pk)


def update_product(product_id: int, changes: dict[str, object]) -> Product:
    product = get_product(product_id)
    for field, value in changes.items():
        setattr(product, field, value)
    product.save(update_fields=[*changes, "updated_at"])
    return get_product(product_id)


def delete_product(product_id: int) -> None:
    get_product(product_id).delete()


def run_check(
    product_id: int, *, fetcher: PageFetcher, notifier: Notifier
) -> tuple[CheckResult, Product]:
    result = check_product(get_product(product_id), fetcher, notifier)
    return result, get_product(product_id)
