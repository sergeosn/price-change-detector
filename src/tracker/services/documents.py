"""Product documents: page text stored with its chunks, rebuilt only when it changes."""

import hashlib
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from tracker.models import Chunk, Product, ProductDocument
from tracker.services.content import ExtractedContent, chunk_text, extract_content
from tracker.services.fetcher import FetchError, PageFetcher

logger = logging.getLogger(__name__)


@dataclass
class IndexSummary:
    fetched: int = 0
    rebuilt: int = 0
    errors: int = 0


def sync_document(product: Product, html: str, now: datetime) -> bool:
    """Store the text of the product's page. Returns True when the document was (re)built.

    A page without text stores nothing and leaves an existing document as it is. Unchanged
    content only moves `fetched_at`; the chunks are kept.
    """
    content = extract_content(html)
    if not content.text:
        return False
    content_hash = _content_hash(content)
    # atomic(): a database error here must not break a transaction the caller has open.
    with transaction.atomic():
        unchanged = ProductDocument.objects.filter(
            product=product, content_hash=content_hash
        ).update(fetched_at=now)
        if unchanged:
            return False
        # update_or_create() locks the existing row, so concurrent rebuilds of one
        # document do not interleave their chunks.
        document, _ = ProductDocument.objects.update_or_create(
            product=product,
            defaults={
                "title": content.title,
                "text": content.text,
                "content_hash": content_hash,
                "fetched_at": now,
            },
        )
        document.chunks.all().delete()
        Chunk.objects.bulk_create(
            Chunk(document=document, ordinal=ordinal, text=text)
            for ordinal, text in enumerate(chunk_text(content.text))
        )
    return True


def index_products(
    *,
    fetcher: PageFetcher,
    reindex_all: bool = False,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> IndexSummary:
    """Download pages and store documents for products that have none (or for all of them)."""
    products = Product.objects.order_by("pk")
    if not reindex_all:
        products = products.filter(document__isnull=True)
    summary = IndexSummary()
    for index, product in enumerate(list(products)):
        if index:
            sleep(random.uniform(settings.REQUEST_DELAY_MIN, settings.REQUEST_DELAY_MAX))
        try:
            html = fetcher.fetch(product.url)
            rebuilt = sync_document(product, html, now or timezone.now())
        except FetchError as exc:
            summary.errors += 1
            logger.warning("Product %s: page not indexed: %s", product.pk, exc)
            continue
        except Exception:
            summary.errors += 1
            logger.exception("Indexing the page of product %s crashed", product.pk)
            continue
        summary.fetched += 1
        if rebuilt:
            summary.rebuilt += 1
    return summary


def _content_hash(content: ExtractedContent) -> str:
    return hashlib.sha256(f"{content.title}\n{content.text}".encode()).hexdigest()
