"""Question answering: retrieve chunks with hybrid search, then let an LLM answer from them."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from tracker.services.answerer import (
    Answerer,
    AnswerError,
    ContextChunk,
    SubmittedAnswer,
    TokenUsage,
)
from tracker.services.embedder import Embedder
from tracker.services.search import SearchMode, SearchResult, search

DEFAULT_LIMIT = 5


@dataclass(frozen=True)
class AskResult:
    """The answer with the products it cites. Not answerable: no answer and no sources."""

    question: str
    answerable: bool
    answer: str
    sources: list[SearchResult]
    retrieval_ms: float
    generation_ms: float
    usage: TokenUsage


def ask(
    question: str,
    limit: int = DEFAULT_LIMIT,
    *,
    embedder: Embedder,
    answerer: Answerer,
    clock: Callable[[], float] = time.perf_counter,
) -> AskResult:
    """Answer the question from the `limit` best chunks of the hybrid search.

    Raises AnswerError when the LLM fails or its answer does not hold up: it cites a chunk
    it was not given, or answers without citing any.
    """
    started = clock()
    results = search(question, SearchMode.HYBRID, limit, embedder=embedder)
    retrieval_ms = (clock() - started) * 1000
    if not results:
        # Nothing to answer from, so the LLM is not asked: it could only guess.
        return AskResult(question, False, "", [], retrieval_ms, 0.0, TokenUsage())

    started = clock()
    generation = answerer.answer(
        question,
        [
            ContextChunk(
                chunk_id=result.chunk.pk, product_name=result.product.name, text=result.chunk.text
            )
            for result in results
        ],
    )
    generation_ms = (clock() - started) * 1000
    answer, sources = _grounded(generation.answer, results)
    return AskResult(
        question=question,
        answerable=generation.answer.answerable,
        answer=answer,
        sources=sources,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        usage=generation.usage,
    )


def _grounded(
    submitted: SubmittedAnswer, results: list[SearchResult]
) -> tuple[str, list[SearchResult]]:
    """The answer text and its sources, in the order the answer cites them."""
    if not submitted.answerable:
        return "", []
    retrieved = {result.chunk.pk: result for result in results}
    cited = list(dict.fromkeys(submitted.source_chunk_ids))
    unknown = [chunk_id for chunk_id in cited if chunk_id not in retrieved]
    if unknown:
        raise AnswerError(
            f"LLM cited chunks that were not retrieved: {', '.join(map(str, unknown))}"
        )
    if not cited:
        raise AnswerError("LLM gave an answer without sources")
    answer = submitted.answer.strip()
    if not answer:
        raise AnswerError("LLM gave an empty answer")
    return answer, [retrieved[chunk_id] for chunk_id in cited]
