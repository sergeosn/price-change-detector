"""Search over chunks: by meaning (vectors), by words (full text and product names) or both."""

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from functools import reduce
from operator import or_
from typing import NamedTuple

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.db.models import F
from pgvector.django import CosineDistance

from tracker.models import Chunk, Product
from tracker.services.embedder import Embedder

# Reciprocal rank fusion: a chunk gets 1 / (RRF_K + rank) from every ranking that has it.
RRF_K = 60
# Chunks taken from each ranking before grouping by product: several chunks of one product
# may be at the top, so more than `limit` are needed.
CANDIDATES_PER_RESULT = 5
MIN_CANDIDATES = 50


class SearchMode(StrEnum):
    VECTOR = "vector"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class SearchResult:
    """A product with its best chunk. Scores of different modes are not comparable."""

    product: Product
    chunk: Chunk
    score: float


class _Hit(NamedTuple):
    chunk_id: int
    product_id: int
    score: float


def search(
    query: str,
    mode: SearchMode = SearchMode.HYBRID,
    limit: int = 10,
    *,
    embedder: Embedder,
) -> list[SearchResult]:
    """Find products by the text of their pages; best first, one result per product.

    The score is the cosine similarity in "vector" mode, the full-text rank plus the name
    similarity in "lexical" mode, and the reciprocal rank fusion of both in "hybrid" mode.
    """
    mode = SearchMode(mode)
    query = query.strip()
    if not query:
        return []
    depth = max(limit * CANDIDATES_PER_RESULT, MIN_CANDIDATES)
    if mode is SearchMode.VECTOR:
        ranking = _vector_ranking(query, embedder, depth)
    elif mode is SearchMode.LEXICAL:
        ranking = _lexical_ranking(query, depth)
    else:
        ranking = _fuse(_lexical_ranking(query, depth), _vector_ranking(query, embedder, depth))
    return _best_chunk_per_product(ranking, limit)


def _vector_ranking(query: str, embedder: Embedder, depth: int) -> list[_Hit]:
    """Chunks nearest to the query by cosine distance; the score is the cosine similarity."""
    rows = (
        # Vectors of another model live in another space and cannot be compared.
        Chunk.objects.filter(embedding__isnull=False, embedding_model=embedder.model_name)
        .annotate(distance=CosineDistance("embedding", embedder.embed_query(query)))
        .order_by("distance")
        .values_list("pk", "document__product_id", "distance")[:depth]
    )
    return [_Hit(chunk_id, product_id, 1 - distance) for chunk_id, product_id, distance in rows]


def _lexical_ranking(query: str, depth: int) -> list[_Hit]:
    """Chunks that contain a word of the query, and chunks of products named like it.

    The score is the full-text rank of the chunk plus the trigram similarity of the query
    to the product name. They are two queries, so that each can use its GIN index.
    """
    # Word similarity compares the query with the closest part of the name, so a model
    # number matches a long name; the lookup applies pg_trgm's threshold (0.6 by default).
    name_scores: dict[int, float] = dict(
        Product.objects.filter(name__trigram_word_similar=query)
        .annotate(similarity=TrigramWordSimilarity(query, "name"))
        .order_by("-similarity", "pk")
        .values_list("pk", "similarity")[:depth]
    )
    # Any word may match: the "simple" configuration keeps stop words, and a question
    # must not need all of its words in one chunk. The rank favours chunks with more of them.
    words = reduce(
        or_, (SearchQuery(word, config="simple", search_type="plain") for word in query.split())
    )
    text_rows = (
        Chunk.objects.filter(search_vector=words)
        .annotate(rank=SearchRank(F("search_vector"), words))
        .order_by("-rank", "pk")
        .values_list("pk", "document__product_id", "rank")[:depth]
    )
    hits = [
        _Hit(chunk_id, product_id, rank + name_scores.get(product_id, 0.0))
        for chunk_id, product_id, rank in text_rows
    ]
    # A product found by its name alone is shown with the first chunk of its page.
    name_only = name_scores.keys() - {hit.product_id for hit in hits}
    first_chunks = Chunk.objects.filter(document__product__in=name_only, ordinal=0)
    hits += [
        _Hit(chunk_id, product_id, name_scores[product_id])
        for chunk_id, product_id in first_chunks.values_list("pk", "document__product_id")
    ]
    return sorted(hits, key=_best_first)[:depth]


def _fuse(*rankings: list[_Hit]) -> list[_Hit]:
    """Reciprocal rank fusion: only the positions count, so the scores need no common scale."""
    scores: defaultdict[int, float] = defaultdict(float)
    products: dict[int, int] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.chunk_id] += 1 / (RRF_K + rank)
            products[hit.chunk_id] = hit.product_id
    fused = [_Hit(chunk_id, products[chunk_id], score) for chunk_id, score in scores.items()]
    return sorted(fused, key=_best_first)


def _best_first(hit: _Hit) -> tuple[float, int]:
    return -hit.score, hit.chunk_id


def _best_chunk_per_product(ranking: list[_Hit], limit: int) -> list[SearchResult]:
    best: dict[int, _Hit] = {}
    for hit in ranking:
        best.setdefault(hit.product_id, hit)
        if len(best) == limit:
            break
    chunks = Chunk.objects.select_related("document__product").in_bulk(
        [hit.chunk_id for hit in best.values()]
    )
    return [
        SearchResult(
            product=chunks[hit.chunk_id].document.product,
            chunk=chunks[hit.chunk_id],
            score=hit.score,
        )
        for hit in best.values()
        # A chunk deleted meanwhile (its document was rebuilt) is left out.
        if hit.chunk_id in chunks
    ]
