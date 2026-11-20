"""Turning text into vectors for retrieval."""

import threading
from collections.abc import Callable, Sequence
from functools import cache
from typing import Any, Protocol

from django.conf import settings

# E5 models are trained with these prefixes; without them retrieval quality drops.
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "


class Embedder(Protocol):
    # Stored next to every vector, so vectors of another model can be found and replaced.
    model_name: str
    dimensions: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one unit vector per text that will be searched."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Return the unit vector of a search query."""
        ...


class SentenceTransformerEmbedder:
    """An E5 model run locally with sentence-transformers. The model is loaded on first use."""

    def __init__(
        self,
        model_name: str,
        dimensions: int,
        load_model: Callable[[str], Any] | None = None,
    ) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self._load_model = load_model or _load_sentence_transformer
        self._model: Any = None
        # API requests run in a thread pool: the first ones must not load the model twice.
        self._lock = threading.Lock()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([PASSAGE_PREFIX + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([QUERY_PREFIX + text])[0]

    def _encode(self, sentences: list[str]) -> list[list[float]]:
        vectors = self._get_model().encode(
            sentences, normalize_embeddings=True, show_progress_bar=False
        )
        if vectors.shape[1] != self.dimensions:
            raise ValueError(
                f"{self.model_name} returned {vectors.shape[1]} dimensions, "
                f"expected {self.dimensions} (EMBEDDING_DIMENSIONS)"
            )
        return vectors.tolist()

    def _get_model(self) -> Any:
        with self._lock:
            if self._model is None:
                self._model = self._load_model(self.model_name)
            return self._model


@cache
def get_embedder() -> Embedder:
    """The embedder of this process; it is shared so the model is loaded only once."""
    return SentenceTransformerEmbedder(settings.EMBEDDING_MODEL, settings.EMBEDDING_DIMENSIONS)


def _load_sentence_transformer(model_name: str) -> Any:
    # Imported here because importing torch takes seconds and only embedding needs it.
    # The first load downloads the model into the Hugging Face cache (HF_HOME).
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)
