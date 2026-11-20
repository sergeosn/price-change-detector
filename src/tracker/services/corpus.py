"""Export of the stored product texts as a JSON Lines corpus."""

import json
from pathlib import Path

from django.db.models import Value
from django.db.models.functions import Coalesce, Left

from tracker.models import Product

# Characters of the document kept per product: enough to tell what the product is.
TEXT_LIMIT = 1500


def export_corpus(path: Path) -> int:
    """Write one JSON object per product to `path`; returns the number of products.

    A product without a document is exported with an empty text. An existing file is
    replaced.
    """
    records = (
        Product.objects.order_by("pk")
        # Cut in the database, so whole documents are not loaded just to be truncated.
        .annotate(text=Coalesce(Left("document__text", TEXT_LIMIT), Value("")))
        .values("url", "name", "domain", "text")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as file:
        for record in records.iterator():
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count
