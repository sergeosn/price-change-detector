"""Chunk embeddings: vectors for chunks that have none or come from another model."""

from django.db.models import Q

from tracker.models import Chunk
from tracker.services.embedder import Embedder

DEFAULT_BATCH_SIZE = 32


def embed_chunks(*, embedder: Embedder, batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Embed every chunk whose vector is missing or was made by another model.

    Each batch is saved on its own, so an interrupted run keeps what it has done.
    Returns the number of chunks embedded.
    """
    pending = Chunk.objects.filter(
        Q(embedding__isnull=True) | ~Q(embedding_model=embedder.model_name)
    ).order_by("pk")
    embedded = 0
    last_pk = 0
    while batch := list(pending.filter(pk__gt=last_pk)[:batch_size]):
        vectors = embedder.embed_documents([chunk.text for chunk in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = embedder.model_name
        # A chunk deleted meanwhile (its document was rebuilt) is simply not updated.
        embedded += Chunk.objects.bulk_update(batch, ["embedding", "embedding_model"])
        last_pk = batch[-1].pk
    return embedded
