import pytest

from tests.helpers import URL, make_product
from tracker.models import Product
from tracker.services.seeding import seed_products

pytestmark = pytest.mark.django_db

OTHER_URL = "https://shop.example/item/2"


def test_creates_an_unchecked_product_for_every_url():
    summary = seed_products([f"{URL}\n", f"  {OTHER_URL}  \n"])

    assert (summary.created, summary.skipped, summary.invalid) == (2, 0, 0)
    products = Product.objects.order_by("pk").values_list(
        "url", "domain", "is_active", "last_check_status", "last_checked_at", "current_price"
    )
    assert list(products) == [
        (URL, "shop.example", True, "never", None, None),
        (OTHER_URL, "shop.example", True, "never", None, None),
    ]


def test_skips_urls_that_exist_in_the_database_or_earlier_in_the_file():
    existing = make_product(name="Kettle")

    summary = seed_products([URL, OTHER_URL, OTHER_URL])

    assert (summary.created, summary.skipped, summary.invalid) == (1, 2, 0)
    assert Product.objects.count() == 2
    existing.refresh_from_db()
    assert existing.name == "Kettle"


def test_lines_that_are_not_http_urls_are_invalid_and_create_nothing():
    too_long = "https://shop.example/" + "a" * 2048

    summary = seed_products(
        ["not a url", "ftp://shop.example/file", URL, "shop.example/item/3", "https://", too_long]
    )

    assert (summary.created, summary.skipped, summary.invalid) == (1, 0, 5)
    assert summary.invalid_lines == [
        (1, "not a url"),
        (2, "ftp://shop.example/file"),
        (4, "shop.example/item/3"),
        (5, "https://"),
        (6, too_long),
    ]
    assert list(Product.objects.values_list("url", flat=True)) == [URL]


def test_blank_lines_are_ignored():
    summary = seed_products(["\n", "   \n", f"{URL}\n", ""])

    assert (summary.created, summary.skipped, summary.invalid) == (1, 0, 0)
