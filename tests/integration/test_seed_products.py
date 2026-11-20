from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from tests.helpers import URL, make_product
from tracker.models import Product

pytestmark = pytest.mark.django_db

OTHER_URL = "https://shop.example/item/2"
THIRD_URL = "https://other.example/p/3"


def run(*args: str) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("seed_products", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_creates_products_from_the_file_and_prints_the_summary(tmp_path: Path):
    make_product()
    path = tmp_path / "urls.txt"
    path.write_text(f"{URL}\n{OTHER_URL}\n\nnot a url\n{THIRD_URL}\n", encoding="utf-8")

    out, err = run(str(path))

    assert "Created 2 product(s), skipped 1 existing, 1 invalid line(s)" in out
    assert "Line 4: not a url" in err
    assert set(Product.objects.values_list("url", flat=True)) == {URL, OTHER_URL, THIRD_URL}
    assert not Product.objects.exclude(last_check_status="never").exists()


def test_second_run_creates_nothing(tmp_path: Path):
    path = tmp_path / "urls.txt"
    path.write_text(f"{URL}\n{OTHER_URL}\n", encoding="utf-8")
    run(str(path))

    out, _ = run(str(path))

    assert "Created 0 product(s), skipped 2 existing, 0 invalid line(s)" in out
    assert Product.objects.count() == 2


def test_byte_order_mark_does_not_spoil_the_first_url(tmp_path: Path):
    path = tmp_path / "urls.txt"
    path.write_bytes(b"\xef\xbb\xbf" + URL.encode() + b"\r\n")

    out, _ = run(str(path))

    assert "Created 1 product(s), skipped 0 existing, 0 invalid line(s)" in out
    assert Product.objects.get().url == URL


def test_file_that_cannot_be_read_is_a_command_error(tmp_path: Path):
    with pytest.raises(CommandError, match="Cannot read"):
        run(str(tmp_path / "missing.txt"))

    assert not Product.objects.exists()
