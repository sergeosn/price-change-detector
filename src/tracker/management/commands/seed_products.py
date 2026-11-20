"""manage.py seed_products <file> — create products from a file with one URL per line."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tracker.services.seeding import seed_products


class Command(BaseCommand):
    help = (
        "Create a product for every URL in the file (one per line). URLs that already "
        "exist and invalid lines are skipped. Nothing is fetched: the scheduler checks "
        "the new products on its next pass."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path, help="Text file with one product URL per line.")

    def handle(self, *args, **options):
        path: Path = options["file"]
        try:
            # utf-8-sig: a byte order mark must not become part of the first URL.
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError) as exc:
            raise CommandError(f"Cannot read {path}: {exc}") from None
        summary = seed_products(lines)
        for number, line in summary.invalid_lines:
            self.stderr.write(f"Line {number}: {line}")
        self.stdout.write(
            f"Created {summary.created} product(s), skipped {summary.skipped} existing, "
            f"{summary.invalid} invalid line(s)"
        )
