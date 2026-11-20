"""Answer quality on labelled questions: code-only checks of what `ask` returns."""

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tracker.models import Product
from tracker.services.answerer import Answerer, AnswerError, TokenUsage
from tracker.services.ask import DEFAULT_LIMIT, AskResult, ask
from tracker.services.embedder import Embedder
from tracker.services.evaluation import percentile
from tracker.services.search import SearchMode, search

# The checks, in the order they are reported. The last two apply to answerable questions only.
CHECKS = ("answerable", "sources", "must_contain")


@dataclass(frozen=True)
class EvalQuestion:
    """A question with what a right answer looks like.

    An answerable question names the product whose page holds the answer and the facts
    the answer has to state. A question the corpus cannot answer has neither.
    """

    question: str
    answerable: bool
    source_url: str = ""
    must_contain: tuple[str, ...] = ()


@dataclass(frozen=True)
class Share:
    correct: int
    total: int

    @property
    def value(self) -> float | None:
        """The share correct, or None when the check applied to no question."""
        return self.correct / self.total if self.total else None


@dataclass(frozen=True)
class Outcome:
    """How one question went: the checks that apply to it and whether each passed."""

    question: EvalQuestion
    checks: dict[str, bool]
    latency_ms: float
    usage: TokenUsage
    # Why there was no answer to check; empty when `ask` returned one.
    error: str = ""


@dataclass(frozen=True)
class AnswerReport:
    questions: int
    # By check, in the order of CHECKS.
    checks: dict[str, Share]
    # Questions without a usable answer from the LLM: they fail every check they have.
    failed: int
    # Of the whole `ask` call, over the questions that got an answer.
    latency_p50_ms: float
    latency_p95_ms: float
    usage: TokenUsage
    outcomes: list[Outcome]


def load_questions(path: Path) -> list[EvalQuestion]:
    """Read a JSON Lines file of questions; blank lines are skipped.

    A line is {"question", "source_url", "must_contain": [strings]} for a question the
    corpus answers, or {"question", "answerable": false} for one it cannot.
    Raises ValueError naming the first line that is neither.
    """
    questions = []
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            if line.strip():
                try:
                    questions.append(_parse_question(line))
                except ValueError as exc:
                    raise ValueError(f"line {number}: {exc}") from None
    return questions


def _parse_question(line: str) -> EvalQuestion:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        raise ValueError("not valid JSON") from None
    if not isinstance(record, dict):
        raise ValueError("expected an object")
    question = record.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError('"question" must be a non-empty string')
    answerable = record.get("answerable", True)
    if not isinstance(answerable, bool):
        raise ValueError('"answerable" must be true or false')
    if not answerable:
        if "source_url" in record or "must_contain" in record:
            raise ValueError(
                "a question that is not answerable takes no source_url or must_contain"
            )
        return EvalQuestion(question.strip(), False)
    source_url = record.get("source_url")
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError('"source_url" must be a non-empty string')
    facts = record.get("must_contain")
    if (
        not isinstance(facts, list)
        or not facts
        or not all(isinstance(fact, str) and fact.strip() for fact in facts)
    ):
        raise ValueError('"must_contain" must be a non-empty list of non-empty strings')
    return EvalQuestion(
        question.strip(), True, source_url.strip(), tuple(fact.strip() for fact in facts)
    )


def unknown_source_urls(questions: Sequence[EvalQuestion]) -> list[str]:
    """Source URLs that are not products in the database: no answer can cite them."""
    urls = {question.source_url for question in questions if question.answerable}
    known = set(Product.objects.filter(url__in=urls).values_list("url", flat=True))
    return sorted(urls - known)


def evaluate_answers(
    questions: Sequence[EvalQuestion],
    *,
    embedder: Embedder,
    answerer: Answerer,
    clock: Callable[[], float] = time.perf_counter,
) -> AnswerReport:
    """Put every question to `ask`, as POST /ask does by default, and check the answers.

    - answerable: the answer says the question is answerable exactly when it is.
    - sources: the cited products include the one with the question's source_url.
    - must_contain: the answer text has every expected string, whatever the case.

    A question whose answer `ask` rejects (AnswerError) fails its checks and is counted
    in `failed`; its time is not part of the latency.
    """
    if not questions:
        raise ValueError("no questions to evaluate")
    # The first search loads the embedding model and opens the database connection:
    # that is paid once per process, not per question, so it is not measured.
    search(questions[0].question, SearchMode.HYBRID, DEFAULT_LIMIT, embedder=embedder)
    outcomes = [_run(question, embedder, answerer, clock) for question in questions]
    answered = [outcome for outcome in outcomes if not outcome.error]
    latencies = sorted(outcome.latency_ms for outcome in answered)
    return AnswerReport(
        questions=len(outcomes),
        checks={check: _share(check, outcomes) for check in CHECKS},
        failed=len(outcomes) - len(answered),
        latency_p50_ms=percentile(latencies, 50) if latencies else 0.0,
        latency_p95_ms=percentile(latencies, 95) if latencies else 0.0,
        usage=TokenUsage(
            prompt_tokens=sum(outcome.usage.prompt_tokens for outcome in outcomes),
            completion_tokens=sum(outcome.usage.completion_tokens for outcome in outcomes),
            total_tokens=sum(outcome.usage.total_tokens for outcome in outcomes),
        ),
        outcomes=outcomes,
    )


def _run(
    question: EvalQuestion, embedder: Embedder, answerer: Answerer, clock: Callable[[], float]
) -> Outcome:
    started = clock()
    try:
        result = ask(question.question, embedder=embedder, answerer=answerer)
    except AnswerError as exc:
        result, error = None, str(exc)
    else:
        error = ""
    latency_ms = (clock() - started) * 1000
    return Outcome(
        question=question,
        checks=_checks(question, result),
        latency_ms=latency_ms,
        usage=result.usage if result else TokenUsage(),
        error=error,
    )


def _checks(question: EvalQuestion, result: AskResult | None) -> dict[str, bool]:
    """The checks of the question; without an answer none of them passes."""
    if result is None:
        return dict.fromkeys(CHECKS if question.answerable else CHECKS[:1], False)
    checks = {"answerable": result.answerable == question.answerable}
    if question.answerable:
        answer = result.answer.casefold()
        checks["sources"] = any(
            source.product.url == question.source_url for source in result.sources
        )
        checks["must_contain"] = all(fact.casefold() in answer for fact in question.must_contain)
    return checks


def _share(check: str, outcomes: Sequence[Outcome]) -> Share:
    results = [outcome.checks[check] for outcome in outcomes if check in outcome.checks]
    return Share(correct=sum(results), total=len(results))
