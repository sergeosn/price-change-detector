import pytest

from api.deps import get_question_answerer
from tests.helpers import (
    HEADPHONES,
    HEADPHONES_SPECS,
    MODEL_QUERY,
    SEARCH_CORPUS,
    TENT,
    FakeEmbedder,
    seed_search_corpus,
)
from tracker.models import Chunk, Product
from tracker.services.answerer import AnswerError, SubmittedAnswer, TokenUsage

# Endpoints run in worker threads, so test data must be committed to be visible there.
pytestmark = pytest.mark.django_db(transaction=True)

URL = "/api/v1/ask"


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    """Replaces the embedder of the API with the one that knows the corpus and its queries."""
    return seed_search_corpus()


@pytest.fixture
def unconfigured_client(api_app, api_client):
    """The API with the real answerer factory; the test settings configure no LLM."""
    del api_app.dependency_overrides[get_question_answerer]
    return api_client


def test_requires_api_key(anon_client):
    assert anon_client.post(URL, json={"question": MODEL_QUERY}).status_code == 401


def test_answer_with_cited_products_timings_and_usage(api_client, fake_answerer):
    specs = Chunk.objects.get(text=HEADPHONES_SPECS)
    fake_answerer.reply = SubmittedAnswer(
        answerable=True, answer="30 hours.", source_chunk_ids=[specs.pk]
    )
    fake_answerer.usage = TokenUsage(prompt_tokens=210, completion_tokens=25, total_tokens=235)

    response = api_client.post(URL, json={"question": MODEL_QUERY})

    assert response.status_code == 200
    body = response.json()
    timings = body.pop("timings_ms")
    headphones = Product.objects.get(name=HEADPHONES)
    assert body == {
        "question": MODEL_QUERY,
        "answerable": True,
        "answer": "30 hours.",
        "sources": [
            {
                "product_id": headphones.pk,
                "product_name": HEADPHONES,
                "product_url": headphones.url,
                "chunk_id": specs.pk,
            }
        ],
        "usage": {"prompt_tokens": 210, "completion_tokens": 25, "total_tokens": 235},
    }
    assert timings.keys() == {"retrieval", "generation"}
    assert all(isinstance(value, float) and value >= 0 for value in timings.values())


def test_unanswerable_question_has_an_empty_answer_and_no_sources(api_client, fake_answerer):
    fake_answerer.reply = SubmittedAnswer(answerable=False, answer="", source_chunk_ids=[])

    response = api_client.post(URL, json={"question": "What is the warranty period?"})

    assert response.status_code == 200
    body = response.json()
    assert (body["answerable"], body["answer"], body["sources"]) == (False, "", [])


def test_five_chunks_are_retrieved_by_default(api_client, fake_answerer):
    api_client.post(URL, json={"question": MODEL_QUERY})

    [(question, chunks)] = fake_answerer.calls
    assert question == MODEL_QUERY
    assert len(chunks) == len(SEARCH_CORPUS) == 5


def test_limit_sets_the_number_of_retrieved_chunks(api_client, fake_answerer):
    api_client.post(URL, json={"question": MODEL_QUERY, "limit": 2})

    [(_, chunks)] = fake_answerer.calls
    assert [chunk.product_name for chunk in chunks] == [HEADPHONES, TENT]


def test_the_question_is_stripped(api_client, fake_answerer):
    response = api_client.post(URL, json={"question": f"  {MODEL_QUERY}\n"})

    assert response.json()["question"] == MODEL_QUERY
    assert fake_answerer.calls[0][0] == MODEL_QUERY


def test_an_answer_that_cites_a_chunk_that_was_not_retrieved_is_a_bad_gateway(
    api_client, fake_answerer
):
    fake_answerer.reply = SubmittedAnswer(
        answerable=True, answer="Made up.", source_chunk_ids=[999_999]
    )

    response = api_client.post(URL, json={"question": MODEL_QUERY})

    assert response.status_code == 502
    assert response.json() == {"detail": "LLM cited chunks that were not retrieved: 999999"}


def test_a_failed_llm_call_is_a_bad_gateway(api_client, fake_answerer):
    fake_answerer.error = AnswerError("LLM API returned HTTP 500")

    response = api_client.post(URL, json={"question": MODEL_QUERY})

    assert response.status_code == 502
    assert response.json() == {"detail": "LLM API returned HTTP 500"}


def test_without_the_llm_settings_the_endpoint_is_unavailable(unconfigured_client, fake_embedder):
    response = unconfigured_client.post(URL, json={"question": MODEL_QUERY})

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "Question answering is not configured: "
            "set PCD_LLM_BASE_URL, PCD_LLM_AUTH_TOKEN, PCD_LLM_MODEL"
        )
    }
    # Nothing is searched for an answer that cannot be given.
    assert fake_embedder.query_calls == []


def test_the_api_key_is_checked_before_the_llm_settings(api_app, anon_client):
    del api_app.dependency_overrides[get_question_answerer]

    assert anon_client.post(URL, json={"question": MODEL_QUERY}).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 501},
        {"question": "tent", "limit": 0},
        {"question": "tent", "limit": 21},
        {"question": "tent", "mode": "vector"},
    ],
)
def test_invalid_bodies_are_rejected(api_client, fake_answerer, body):
    assert api_client.post(URL, json=body).status_code == 422
    assert fake_answerer.calls == []
