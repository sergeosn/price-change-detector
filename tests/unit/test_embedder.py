import numpy as np
import pytest
from django.conf import settings

from tracker.services.embedder import SentenceTransformerEmbedder, get_embedder

MODEL_NAME = "test/model"


class FakeModel:
    """Stands in for a SentenceTransformer: one constant vector per text, records its input."""

    def __init__(self, dimensions: int = 4):
        self.dimensions = dimensions
        self.calls: list[tuple[list[str], dict]] = []

    def encode(self, sentences, **kwargs):
        self.calls.append((list(sentences), kwargs))
        return np.full((len(sentences), self.dimensions), 0.5, dtype=np.float32)


class FakeLoader:
    def __init__(self, model: FakeModel):
        self.model = model
        self.calls: list[str] = []

    def __call__(self, model_name: str) -> FakeModel:
        self.calls.append(model_name)
        return self.model


def make_embedder(model: FakeModel | None = None, dimensions: int = 4):
    loader = FakeLoader(model or FakeModel())
    embedder = SentenceTransformerEmbedder(MODEL_NAME, dimensions, load_model=loader)
    return embedder, loader


def test_documents_are_embedded_as_passages():
    embedder, loader = make_embedder()

    vectors = embedder.embed_documents(["Coffee grinder", "Кавомолка"])

    assert vectors == [[0.5] * 4, [0.5] * 4]
    assert all(type(value) is float for vector in vectors for value in vector)
    sentences, options = loader.model.calls[0]
    assert sentences == ["passage: Coffee grinder", "passage: Кавомолка"]
    # Cosine distance in the database expects unit vectors.
    assert options["normalize_embeddings"] is True


def test_a_query_is_embedded_with_the_query_prefix():
    embedder, loader = make_embedder()

    vector = embedder.embed_query("quiet grinder")

    assert vector == [0.5] * 4
    sentences, options = loader.model.calls[0]
    assert sentences == ["query: quiet grinder"]
    assert options["normalize_embeddings"] is True


def test_the_model_is_loaded_on_first_use_and_only_once():
    embedder, loader = make_embedder()
    assert loader.calls == []

    embedder.embed_query("one")
    embedder.embed_documents(["two"])

    assert loader.calls == [MODEL_NAME]


def test_a_model_with_other_dimensions_is_rejected():
    embedder, _ = make_embedder(FakeModel(dimensions=3), dimensions=4)

    with pytest.raises(ValueError, match="test/model returned 3 dimensions, expected 4"):
        embedder.embed_documents(["text"])


def test_get_embedder_is_configured_from_settings_and_shared():
    embedder = get_embedder()

    assert isinstance(embedder, SentenceTransformerEmbedder)
    assert embedder.model_name == settings.EMBEDDING_MODEL == "intfloat/multilingual-e5-small"
    assert embedder.dimensions == settings.EMBEDDING_DIMENSIONS == 384
    assert get_embedder() is embedder
