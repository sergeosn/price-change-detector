"""Bulk creation of products from a list of URLs."""

from collections.abc import Iterable
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError

from tracker.models import Product
from tracker.services.errors import DuplicateError
from tracker.services.products import create_product


@dataclass
class SeedSummary:
    created: int = 0
    skipped: int = 0
    # (line number starting at 1, the line without surrounding whitespace)
    invalid_lines: list[tuple[int, str]] = field(default_factory=list)

    @property
    def invalid(self) -> int:
        return len(self.invalid_lines)


def seed_products(lines: Iterable[str]) -> SeedSummary:
    """Create a product for every line that holds a new, valid URL.

    Blank lines are ignored. The products are only stored: the scheduler checks them on
    its next pass, like any product that was never checked.
    """
    url_field = Product._meta.get_field("url")
    summary = SeedSummary()
    for number, line in enumerate(lines, start=1):
        url = line.strip()
        if not url:
            continue
        try:
            # The model's own rules: an absolute http(s) URL that fits the column.
            url_field.clean(url, None)
        except ValidationError:
            summary.invalid_lines.append((number, url))
            continue
        try:
            create_product(url=url)
        except DuplicateError:
            summary.skipped += 1
        else:
            summary.created += 1
    return summary
