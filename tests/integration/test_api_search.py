import pytest

from tests.helpers import (
    GRINDER,
    GRINDER_TEXT,
    HEADPHONES,
    HEADPHONES_SPECS,
    MODEL_QUERY,
    PARAPHRASE_QUERY,
    SEARCH_CORPUS,
    TENT,
    FakeEmbedder,
    seed_search_corpus,
)
from tracker.models import Chunk, Product

# Endpoints run in worker threads, so test data must be committed to be visible there.
pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/v1/search"


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """Replaces the embedder of the API with the one that knows the corpus and its queries."""
    return seed_search_corpus()


def names(response) -> list[str]:
    return [item["product_name"] for item in response.json()["items"]]


def test_requires_api_key(anon_client):
    assert anon_client.get(URL, params={"q": MODEL_QUERY}).status_code == 401


def test_search_is_hybrid_by_default(api_client):
    response = api_client.get(URL, params={"q": MODEL_QUERY})

    assert response.status_code == 200
    body = response.json()
    assert (body["query"], body["mode"]) == (MODEL_QUERY, "hybrid")
    assert len(body["items"]) == len(SEARCH_CORPUS)
    headphones = Product.objects.get(name=HEADPHONES)
    assert body["items"][0] == {
        "product_id": headphones.pk,
        "product_name": HEADPHONES,
        "product_url": headphones.url,
        "chunk_id": Chunk.objects.get(text=HEADPHONES_SPECS).pk,
        "score": pytest.approx(1 / 61 + 1 / 65),
        "text": HEADPHONES_SPECS,
    }


def test_hybrid_finds_what_the_lexical_and_the_vector_search_find(api_client):
    hybrid = api_client.get(URL, params={"q": MODEL_QUERY, "mode": "hybrid", "limit": 2})

    assert names(api_client.get(URL, params={"q": MODEL_QUERY, "mode": "lexical"})) == [HEADPHONES]
    assert names(api_client.get(URL, params={"q": MODEL_QUERY, "mode": "vector", "limit": 1})) == [
        TENT
    ]
    assert names(hybrid) == [HEADPHONES, TENT]


def test_vector_mode_finds_a_paraphrase(api_client):
    response = api_client.get(URL, params={"q": PARAPHRASE_QUERY, "mode": "vector", "limit": 1})

    assert response.status_code == 200
    assert names(response) == [GRINDER]
    assert response.json()["items"][0]["text"] == GRINDER_TEXT


def test_nothing_found_is_an_empty_list(api_client):
    response = api_client.get(URL, params={"q": PARAPHRASE_QUERY, "mode": "lexical"})

    assert response.status_code == 200
    assert response.json() == {"query": PARAPHRASE_QUERY, "mode": "lexical", "items": []}


def test_lexical_mode_does_not_use_the_embedder(api_client, fake_embedder):
    api_client.get(URL, params={"q": MODEL_QUERY, "mode": "lexical"})

    assert fake_embedder.query_calls == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "x" * 201},
        {"q": "tent", "mode": "fuzzy"},
        {"q": "tent", "limit": 0},
        {"q": "tent", "limit": 51},
    ],
)
def test_invalid_parameters_are_rejected(api_client, params):
    assert api_client.get(URL, params=params).status_code == 422
