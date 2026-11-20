from datetime import UTC, datetime

import pytest
from django.db import connection
from pgvector.django import CosineDistance

from tests.helpers import FakeEmbedder, make_product
from tracker.models import Chunk, ProductDocument
from tracker.services.embeddings import embed_chunks

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
TEXTS = ["Coffee grinder with steel burrs", "Кавомолка з жорнами", "Two-person tent"]


def make_chunks(texts: list[str] = TEXTS) -> list[Chunk]:
    document = ProductDocument.objects.create(
        product=make_product(), text="\n".join(texts), content_hash="hash", fetched_at=NOW
    )
    return Chunk.objects.bulk_create(
        Chunk(document=document, ordinal=ordinal, text=text) for ordinal, text in enumerate(texts)
    )


def test_new_chunks_have_no_embedding():
    chunk = make_chunks()[0]
    chunk.refresh_from_db()

    assert (chunk.embedding, chunk.embedding_model) == (None, "")


def test_chunks_without_an_embedding_are_embedded():
    make_chunks()
    embedder = FakeEmbedder()

    assert embed_chunks(embedder=embedder) == 3

    assert embedder.document_calls == [TEXTS]
    for chunk in Chunk.objects.all():
        assert chunk.embedding_model == "fake-embedder"
        assert list(chunk.embedding) == pytest.approx(embedder.vector(chunk.text), abs=1e-6)


def test_embedded_chunks_are_left_alone():
    make_chunks()
    embed_chunks(embedder=FakeEmbedder())
    embedder = FakeEmbedder()

    assert embed_chunks(embedder=embedder) == 0
    assert embedder.document_calls == []


def test_only_missing_embeddings_are_added():
    chunks = make_chunks()
    embed_chunks(embedder=FakeEmbedder())
    Chunk.objects.filter(pk=chunks[1].pk).update(embedding=None)
    embedder = FakeEmbedder()

    assert embed_chunks(embedder=embedder) == 1
    assert embedder.document_calls == [[TEXTS[1]]]


def test_chunks_embedded_by_another_model_are_embedded_again():
    make_chunks()
    embed_chunks(embedder=FakeEmbedder(model_name="old-model"))
    embedder = FakeEmbedder(model_name="new-model")

    assert embed_chunks(embedder=embedder) == 3

    assert set(Chunk.objects.values_list("embedding_model", flat=True)) == {"new-model"}


def test_chunks_are_embedded_in_batches():
    make_chunks()
    embedder = FakeEmbedder()

    assert embed_chunks(embedder=embedder, batch_size=2) == 3

    assert embedder.document_calls == [TEXTS[:2], TEXTS[2:]]
    assert not Chunk.objects.filter(embedding__isnull=True).exists()


def test_the_nearest_chunk_is_found_by_cosine_distance():
    make_chunks()
    embedder = FakeEmbedder()
    embed_chunks(embedder=embedder)

    query = embedder.embed_query(TEXTS[1])
    nearest = Chunk.objects.order_by(CosineDistance("embedding", query)).first()

    assert nearest.text == TEXTS[1]


def test_embeddings_have_an_hnsw_cosine_index():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", [Chunk._meta.db_table]
        )
        definitions = [row[0] for row in cursor.fetchall()]

    assert any("USING hnsw (embedding vector_cosine_ops)" in d for d in definitions)
