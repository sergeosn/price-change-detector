import pytest
from django.db import connection

from tests.helpers import (
    BACKPACK,
    GRINDER,
    GRINDER_TEXT,
    HEADPHONES,
    HEADPHONES_INTRO,
    HEADPHONES_QUERY,
    HEADPHONES_SPECS,
    KETTLE,
    KETTLE_TEXT,
    MODEL_QUERY,
    PARAPHRASE_QUERY,
    SEARCH_CORPUS,
    TENT,
    FakeEmbedder,
    seed_search_corpus,
)
from tracker.models import Chunk, Product
from tracker.services.search import SearchMode, SearchResult, search

pytestmark = pytest.mark.django_db


@pytest.fixture
def embedder() -> FakeEmbedder:
    return seed_search_corpus()


def names(results: list[SearchResult]) -> list[str]:
    return [result.product.name for result in results]


def index_definitions(model) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", [model._meta.db_table]
        )
        return [row[0] for row in cursor.fetchall()]


def test_lexical_finds_a_model_number_the_vector_search_misses(embedder):
    lexical = search(MODEL_QUERY, SearchMode.LEXICAL, 2, embedder=embedder)
    vector = search(MODEL_QUERY, SearchMode.VECTOR, 2, embedder=embedder)

    assert names(lexical) == [HEADPHONES]
    assert lexical[0].chunk.text == HEADPHONES_SPECS
    assert names(vector) == [TENT, BACKPACK]


def test_vector_finds_a_paraphrase_the_lexical_search_misses(embedder):
    lexical = search(PARAPHRASE_QUERY, SearchMode.LEXICAL, 2, embedder=embedder)
    vector = search(PARAPHRASE_QUERY, SearchMode.VECTOR, 1, embedder=embedder)

    assert lexical == []
    assert names(vector) == [GRINDER]
    assert vector[0].chunk.text == GRINDER_TEXT


@pytest.mark.parametrize(
    ("query", "name"), [(MODEL_QUERY, HEADPHONES), (PARAPHRASE_QUERY, GRINDER)]
)
def test_hybrid_finds_what_either_search_finds(embedder, query, name):
    assert names(search(query, SearchMode.HYBRID, 1, embedder=embedder)) == [name]


def test_hybrid_score_is_the_reciprocal_rank_fusion_of_both_rankings(embedder):
    results = search(MODEL_QUERY, SearchMode.HYBRID, 2, embedder=embedder)

    # The specs chunk is the only lexical hit (rank 1) and the fifth nearest vector;
    # the tent is the nearest vector and no lexical hit.
    assert names(results) == [HEADPHONES, TENT]
    assert results[0].score == pytest.approx(1 / 61 + 1 / 65)
    assert results[1].score == pytest.approx(1 / 61)


def test_vector_score_is_the_cosine_similarity(embedder):
    results = search(MODEL_QUERY, SearchMode.VECTOR, 5, embedder=embedder)

    # Similarities of the query vector (0, 0.1, 0.3, 0.8, 0.5), whose length is 0.995.
    assert names(results) == [TENT, BACKPACK, KETTLE, GRINDER, HEADPHONES]
    assert [result.score for result in results[:4]] == pytest.approx(
        [0.8 / 0.995, 0.5 / 0.995, 0.3 / 0.995, 0.1 / 0.995], abs=1e-3
    )


def test_a_product_is_returned_once_with_its_best_chunk(embedder):
    results = search(HEADPHONES_QUERY, SearchMode.VECTOR, 10, embedder=embedder)

    assert len(results) == len(SEARCH_CORPUS)
    assert names(results).count(HEADPHONES) == 1
    assert results[0].product.name == HEADPHONES
    assert results[0].chunk.text == HEADPHONES_INTRO
    assert results[0].score == pytest.approx(1.0)


def test_lexical_matches_a_model_number_in_the_product_name(embedder):
    # The page text of the kettle does not mention its model.
    results = search("TWK-7203", SearchMode.LEXICAL, 10, embedder=embedder)

    assert names(results) == [KETTLE]
    assert results[0].chunk.text == KETTLE_TEXT
    assert results[0].score == pytest.approx(1.0)


def test_a_match_in_the_name_and_in_the_text_scores_higher_than_either(embedder):
    Product.objects.filter(name=KETTLE).update(name="Sony WH-1000XM5 case")

    results = search(MODEL_QUERY, SearchMode.LEXICAL, 10, embedder=embedder)

    assert names(results) == [HEADPHONES, "Sony WH-1000XM5 case"]
    assert results[0].score > results[1].score == pytest.approx(1.0)


def test_lexical_matches_any_word_of_the_query(embedder):
    results = search("which grinder has steel burrs?", SearchMode.LEXICAL, 1, embedder=embedder)

    assert names(results) == [GRINDER]


def test_lexical_search_does_not_embed_the_query(embedder):
    search(MODEL_QUERY, SearchMode.LEXICAL, 10, embedder=embedder)

    assert embedder.query_calls == []


def test_vector_search_skips_chunks_embedded_by_another_model(embedder):
    Chunk.objects.filter(text=GRINDER_TEXT).update(embedding_model="old-model")

    results = search(PARAPHRASE_QUERY, SearchMode.VECTOR, 10, embedder=embedder)

    assert len(results) == len(SEARCH_CORPUS) - 1
    assert GRINDER not in names(results)


def test_vector_search_skips_chunks_without_an_embedding(embedder):
    Chunk.objects.filter(text=GRINDER_TEXT).update(embedding=None)

    assert GRINDER not in names(search(PARAPHRASE_QUERY, SearchMode.VECTOR, 10, embedder=embedder))


@pytest.mark.parametrize("mode", list(SearchMode))
def test_no_more_than_limit_products_are_returned(embedder, mode):
    assert len(search("tent backpack kettle", mode, 2, embedder=embedder)) == 2


@pytest.mark.parametrize("mode", list(SearchMode))
def test_a_blank_query_finds_nothing(embedder, mode):
    assert search("  ", mode, 10, embedder=embedder) == []
    assert embedder.query_calls == []


@pytest.mark.parametrize("query", ["!!!", "'", "x & | y:*", "\\", "%_"])
def test_punctuation_in_the_query_is_harmless(embedder, query):
    assert search(query, SearchMode.LEXICAL, 10, embedder=embedder) == []


def test_chunks_have_a_stored_search_vector_with_a_gin_index():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_generated, generation_expression FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = 'search_vector'",
            [Chunk._meta.db_table],
        )
        is_generated, expression = cursor.fetchone()

    assert is_generated == "ALWAYS"
    assert "to_tsvector('simple'" in expression
    assert any("USING gin (search_vector)" in d for d in index_definitions(Chunk))


def test_product_names_have_a_gin_trigram_index():
    assert any("USING gin (name gin_trgm_ops)" in d for d in index_definitions(Product))
