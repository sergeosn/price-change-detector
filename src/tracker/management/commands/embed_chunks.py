"""manage.py embed_chunks — compute embeddings for chunks that do not have a current one."""

from django.core.management.base import BaseCommand, CommandError

from tracker.services.embedder import get_embedder
from tracker.services.embeddings import DEFAULT_BATCH_SIZE, embed_chunks


class Command(BaseCommand):
    help = (
        "Embed chunks that have no embedding or were embedded by a model other than "
        "EMBEDDING_MODEL. The first run downloads the model."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Chunks embedded and saved at once (default: {DEFAULT_BATCH_SIZE}).",
        )

    def handle(self, *args, **options):
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")
        embedder = get_embedder()
        embedded = embed_chunks(embedder=embedder, batch_size=options["batch_size"])
        self.stdout.write(f"Embedded {embedded} chunk(s) with {embedder.model_name}")
