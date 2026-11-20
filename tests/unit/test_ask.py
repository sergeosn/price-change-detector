import pytest

from tests.helpers import (
    GRINDER_TEXT,
    HEADPHONES,
    HEADPHONES_SPECS,
    MODEL_QUERY,
    TENT,
    TENT_TEXT,
    FakeAnswerer,
    FakeClock,
    FakeEmbedder,
    seed_search_corpus,
)
from tracker.models import Chunk
from tracker.services.answerer import AnswerError, ContextChunk, SubmittedAnswer, TokenUsage
from tracker.services.ask import AskResult, ask

pytestmark = pytest.mark.django_db

# MODEL_QUERY retrieves the headphones (specs chunk) first and the tent second.


@pytest.fixture
def embedder() -> FakeEmbedder:
    return seed_search_corpus()


def chunk_id(text: str) -> int:
    return Chunk.objects.get(text=text).pk


def replying(answerable: bool, answer: str, *source_texts: str) -> FakeAnswerer:
    return FakeAnswerer(
        SubmittedAnswer(
            answerable=answerable,
            answer=answer,
            source_chunk_ids=[chunk_id(text) for text in source_texts],
        )
    )


def source_names(result: AskResult) -> list[str]:
    return [source.product.name for source in result.sources]


def test_the_answer_comes_with_the_products_it_cites_and_the_token_usage(embedder):
    answerer = replying(True, "30 hours.", HEADPHONES_SPECS)
    answerer.usage = TokenUsage(prompt_tokens=210, completion_tokens=25, total_tokens=235)

    result = ask(MODEL_QUERY, 3, embedder=embedder, answerer=answerer)

    assert (result.question, result.answerable, result.answer) == (MODEL_QUERY, True, "30 hours.")
    assert source_names(result) == [HEADPHONES]
    assert result.sources[0].chunk.text == HEADPHONES_SPECS
    assert result.usage == TokenUsage(prompt_tokens=210, completion_tokens=25, total_tokens=235)


def test_the_answerer_gets_the_question_and_the_chunks_of_the_hybrid_search(embedder):
    answerer = FakeAnswerer()

    ask(MODEL_QUERY, 2, embedder=embedder, answerer=answerer)

    assert answerer.calls == [
        (
            MODEL_QUERY,
            [
                ContextChunk(chunk_id(HEADPHONES_SPECS), HEADPHONES, HEADPHONES_SPECS),
                ContextChunk(chunk_id(TENT_TEXT), TENT, TENT_TEXT),
            ],
        )
    ]


def test_sources_follow_the_answer_and_are_not_repeated(embedder):
    answerer = replying(True, "Both.", TENT_TEXT, HEADPHONES_SPECS, TENT_TEXT)

    result = ask(MODEL_QUERY, 2, embedder=embedder, answerer=answerer)

    assert source_names(result) == [TENT, HEADPHONES]


def test_an_unanswerable_question_has_an_empty_answer_and_no_sources(embedder):
    answerer = replying(False, "The pages do not say.", HEADPHONES_SPECS)

    result = ask(MODEL_QUERY, 2, embedder=embedder, answerer=answerer)

    assert (result.answerable, result.answer, result.sources) == (False, "", [])
    assert result.usage == answerer.usage


def test_a_source_that_was_not_retrieved_is_rejected(embedder):
    # With limit 1 only the headphones are retrieved; the grinder chunk exists but was not.
    answerer = replying(True, "It grinds.", HEADPHONES_SPECS, GRINDER_TEXT)

    with pytest.raises(AnswerError) as excinfo:
        ask(MODEL_QUERY, 1, embedder=embedder, answerer=answerer)

    assert str(excinfo.value) == (
        f"LLM cited chunks that were not retrieved: {chunk_id(GRINDER_TEXT)}"
    )


def test_an_answer_without_sources_is_rejected(embedder):
    answerer = replying(True, "30 hours.")

    with pytest.raises(AnswerError, match="LLM gave an answer without sources"):
        ask(MODEL_QUERY, 2, embedder=embedder, answerer=answerer)


def test_an_answerable_question_with_a_blank_answer_is_rejected(embedder):
    answerer = replying(True, "  ", HEADPHONES_SPECS)

    with pytest.raises(AnswerError, match="LLM gave an empty answer"):
        ask(MODEL_QUERY, 2, embedder=embedder, answerer=answerer)


def test_nothing_retrieved_is_unanswerable_without_asking_the_llm():
    answerer = FakeAnswerer()

    result = ask("Is there anything?", embedder=FakeEmbedder(), answerer=answerer)

    assert answerer.calls == []
    assert (result.answerable, result.answer, result.sources) == (False, "", [])
    assert result.generation_ms == 0
    assert result.usage == TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def test_retrieval_and_generation_are_timed_separately(embedder):
    # The search takes 12 ms and the LLM call 800 ms.
    clock = FakeClock([0.012, 0.8])

    result = ask(MODEL_QUERY, embedder=embedder, answerer=FakeAnswerer(), clock=clock)

    assert result.retrieval_ms == pytest.approx(12)
    assert result.generation_ms == pytest.approx(800)
