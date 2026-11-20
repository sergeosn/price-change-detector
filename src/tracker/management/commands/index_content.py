"""manage.py index_content — store page text for products that were added before it was kept."""

from django.core.management.base import BaseCommand

from tracker.services.documents import index_products
from tracker.services.fetcher import get_fetcher


class Command(BaseCommand):
    help = (
        "Download product pages and store their text for retrieval. By default only "
        "products without a document are fetched."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Fetch every product; documents whose content changed are rebuilt.",
        )

    def handle(self, *args, **options):
        summary = index_products(fetcher=get_fetcher(), reindex_all=options["all"])
        self.stdout.write(
            f"Fetched {summary.fetched} page(s): {summary.rebuilt} document(s) rebuilt, "
            f"{summary.errors} error(s)"
        )
