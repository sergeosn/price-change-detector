"""manage.py export_corpus — write the stored product texts to data/corpus.jsonl."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from tracker.services.corpus import TEXT_LIMIT, export_corpus


class Command(BaseCommand):
    help = (
        "Write one JSON line per product: url, name, domain and the first "
        f"{TEXT_LIMIT} characters of its document (empty if it has none)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            type=Path,
            help="File to write (default: data/corpus.jsonl in the project directory).",
        )

    def handle(self, *args, **options):
        path: Path = options["output"] or settings.PROJECT_DIR / "data" / "corpus.jsonl"
        try:
            count = export_corpus(path)
        except OSError as exc:
            raise CommandError(f"Cannot write {path}: {exc}") from None
        self.stdout.write(f"Exported {count} product(s) to {path}")
