"""Search quality on labelled queries: recall, MRR and latency of every search mode."""

import json
import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tracker.models import Product
from tracker.services.embedder import Embedder
from tracker.services.search import SearchMode, search

# Results requested per query: the reciprocal rank looks no further than this.
DEPTH = 10


@dataclass(frozen=True)
class EvalQuery:
    """A query with the URLs of the products a search should find for it."""

    query: str
    kind: str
    relevant: frozenset[str]


@dataclass(frozen=True)
class Metrics:
    """Averages over a group of queries.

    recall@k is the share of the relevant products found in the top k, out of those that
    fit there: with three relevant products recall@1 is 1 when the first result is one of
    them. MRR averages 1 / rank of the first relevant result, 0 when there is none.
    """

    queries: int
    recall_at_1: float
    recall_at_5: float
    mrr: float
    latency_p50_ms: float
    latency_p95_ms: float


@dataclass(frozen=True)
class ModeReport:
    overall: Metrics
    # By kind, in the order the kinds first appear in the queries.
    kinds: dict[str, Metrics]


@dataclass(frozen=True)
class _Outcome:
    """What one search returned for one query."""

    query: EvalQuery
    urls: list[str]
    latency_ms: float


def load_queries(path: Path) -> list[EvalQuery]:
    """Read a JSON Lines file of {"query", "kind", "relevant": [urls]}; blank lines are skipped.

    Raises ValueError naming the first line that is not such an object.
    """
    queries = []
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            if line.strip():
                try:
                    queries.append(_parse_query(line))
                except ValueError as exc:
                    raise ValueError(f"line {number}: {exc}") from None
    return queries


def _parse_query(line: str) -> EvalQuery:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        raise ValueError("not valid JSON") from None
    if not isinstance(record, dict):
        raise ValueError("expected an object")
    for key in ("query", "kind"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f'"{key}" must be a non-empty string')
    relevant = record.get("relevant")
    if (
        not isinstance(relevant, list)
        or not relevant
        or not all(isinstance(url, str) for url in relevant)
    ):
        raise ValueError('"relevant" must be a non-empty list of URLs')
    return EvalQuery(record["query"].strip(), record["kind"].strip(), frozenset(relevant))


def unknown_urls(queries: Sequence[EvalQuery]) -> list[str]:
    """Relevant URLs that are not products in the database: no search can find them."""
    relevant = set().union(*(query.relevant for query in queries))
    known = set(Product.objects.filter(url__in=relevant).values_list("url", flat=True))
    return sorted(relevant - known)


def evaluate(
    queries: Sequence[EvalQuery],
    *,
    embedder: Embedder,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[SearchMode, ModeReport]:
    """Run every query in every search mode and measure what comes back.

    The latency is the time of the whole `search` call, the query embedding included.
    """
    if not queries:
        raise ValueError("no queries to evaluate")
    report = {}
    for mode in SearchMode:
        # The first search loads the embedding model and opens the database connection:
        # that is paid once per process, not per query, so it is not measured.
        search(queries[0].query, mode, DEPTH, embedder=embedder)
        outcomes = [_run(query, mode, embedder, clock) for query in queries]
        kinds = dict.fromkeys(query.kind for query in queries)
        report[mode] = ModeReport(
            overall=_summarize(outcomes),
            kinds={
                kind: _summarize([o for o in outcomes if o.query.kind == kind]) for kind in kinds
            },
        )
    return report


def _run(
    query: EvalQuery, mode: SearchMode, embedder: Embedder, clock: Callable[[], float]
) -> _Outcome:
    started = clock()
    results = search(query.query, mode, DEPTH, embedder=embedder)
    latency_ms = (clock() - started) * 1000
    return _Outcome(query, [result.product.url for result in results], latency_ms)


def _summarize(outcomes: Sequence[_Outcome]) -> Metrics:
    latencies = sorted(outcome.latency_ms for outcome in outcomes)
    return Metrics(
        queries=len(outcomes),
        recall_at_1=_mean([_recall(outcome, 1) for outcome in outcomes]),
        recall_at_5=_mean([_recall(outcome, 5) for outcome in outcomes]),
        mrr=_mean([_reciprocal_rank(outcome) for outcome in outcomes]),
        latency_p50_ms=_percentile(latencies, 50),
        latency_p95_ms=_percentile(latencies, 95),
    )


def _recall(outcome: _Outcome, k: int) -> float:
    relevant = outcome.query.relevant
    return len(relevant.intersection(outcome.urls[:k])) / min(k, len(relevant))


def _reciprocal_rank(outcome: _Outcome) -> float:
    ranks = (
        rank for rank, url in enumerate(outcome.urls, start=1) if url in outcome.query.relevant
    )
    return next((1 / rank for rank in ranks), 0.0)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _percentile(ordered: Sequence[float], percent: float) -> float:
    """Percentile of sorted values, interpolated linearly between the two nearest."""
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
