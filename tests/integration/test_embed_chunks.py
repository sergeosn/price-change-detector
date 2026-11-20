from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from tests.helpers import FakeEmbedder, load_fixture, make_product
from tracker.models import Chunk
from tracker.services.documents import sync_document

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def embedder(monkeypatch) -> FakeEmbedder:
    embedder = FakeEmbedder()
    monkeypatch.setattr("tracker.management.commands.embed_chunks.get_embedder", lambda: embedder)
    return embedder


@pytest.fixture(autouse=True)
def chunks() -> list[Chunk]:
    sync_document(make_product(), load_fixture("content_uk.html"), NOW)
    return list(Chunk.objects.all())


def run(*args: str) -> str:
    out = StringIO()
    call_command("embed_chunks", *args, stdout=out)
    return out.getvalue()


def test_embeds_chunks_that_have_no_embedding(embedder, chunks):
    assert "Embedded 2 chunk(s) with fake-embedder" in run()
    assert embedder.document_calls == [[chunk.text for chunk in chunks]]
    assert not Chunk.objects.filter(embedding__isnull=True).exists()

    embedder.document_calls.clear()
    assert "Embedded 0 chunk(s) with fake-embedder" in run()
    assert embedder.document_calls == []


def test_batch_size_limits_how_many_chunks_are_embedded_at_once(embedder, chunks):
    assert "Embedded 2 chunk(s)" in run("--batch-size", "1")
    assert embedder.document_calls == [[chunks[0].text], [chunks[1].text]]


def test_batch_size_must_be_positive():
    with pytest.raises(CommandError, match="--batch-size must be at least 1"):
        run("--batch-size", "0")
