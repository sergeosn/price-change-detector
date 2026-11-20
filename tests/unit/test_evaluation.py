import json
from pathlib import Path

import pytest

from tests.helpers import (
    MODEL_QUERY,
    PARAPHRASE_QUERY,
    SEARCH_QUERY_VECTORS,
    FakeClock,
    FakeEmbedder,
    make_product,
    seed_search_corpus,
)
from tracker.services.evaluation import EvalQuery, evaluate, load_queries, unknown_urls
from tracker.services.search import SearchMode

pytestmark = pytest.mark.django_db

# Products of the search corpus by number: 1 headphones, 2 grinder, 3 kettle, 4 tent, 5 backpack.
HEADPHONES_URL, GRINDER_URL, KETTLE_URL, TENT_URL, BACKPACK_URL = (
    f"https://shop.example/item/{number}" for number in range(1, 6)
)
# A product without page text: no search can find it.
STOVE_URL = "https://shop.example/item/6"
# Shares no word with any text or name; the vector search ranks the products for it as
# tent, backpack, kettle, grinder, headphones.
CAMPING_QUERY = "спорядження для походу"

# What each search returns:
#   MODEL_QUERY       vector: headphones 5th      lexical: headphones 1st   hybrid: 1st
#   PARAPHRASE_QUERY  vector: grinder 1st         lexical: nothing          hybrid: 1st
#   CAMPING_QUERY     vector: backpack 2nd, the stove never; lexical: nothing; hybrid: as vector
QUERIES = [
    EvalQuery(MODEL_QUERY, "model_number", frozenset({HEADPHONES_URL})),
    EvalQuery(PARAPHRASE_QUERY, "description", frozenset({GRINDER_URL})),
    EvalQuery(CAMPING_QUERY, "description", frozenset({BACKPACK_URL, STOVE_URL})),
]


@pytest.fixture
def embedder() -> FakeEmbedder:
    embedder = seed_search_corpus()
    embedder.vectors[CAMPING_QUERY] = SEARCH_QUERY_VECTORS[MODEL_QUERY]
    make_product(url=STOVE_URL, name="Camping stove")
    return embedder


def quality(metrics) -> tuple[float, float, float]:
    return metrics.recall_at_1, metrics.recall_at_5, metrics.mrr


@pytest.mark.parametrize(
    ("mode", "overall", "model_number", "description"),
    [
        # Reciprocal ranks 1/5, 1 and 1/2; half of the camping gear is in the top five.
        (SearchMode.VECTOR, (1 / 3, 2.5 / 3, 1.7 / 3), (0, 1, 0.2), (0.5, 0.75, 0.75)),
        (SearchMode.LEXICAL, (1 / 3, 1 / 3, 1 / 3), (1, 1, 1), (0, 0, 0)),
        (SearchMode.HYBRID, (2 / 3, 2.5 / 3, 2.5 / 3), (1, 1, 1), (0.5, 0.75, 0.75)),
    ],
)
def test_recall_and_mrr_of_a_mode_overall_and_per_kind(
    embedder, mode, overall, model_number, description
):
    report = evaluate(QUERIES, embedder=embedder)[mode]

    assert quality(report.overall) == pytest.approx(overall)
    assert list(report.kinds) == ["model_number", "description"]
    assert quality(report.kinds["model_number"]) == pytest.approx(model_number)
    assert quality(report.kinds["description"]) == pytest.approx(description)
    assert report.overall.queries == 3
    assert report.kinds["model_number"].queries == 1
    assert report.kinds["description"].queries == 2


def test_every_mode_is_evaluated(embedder):
    assert list(evaluate(QUERIES, embedder=embedder)) == [
        SearchMode.VECTOR,
        SearchMode.LEXICAL,
        SearchMode.HYBRID,
    ]


def test_recall_counts_every_relevant_product_in_the_top_k(embedder):
    # The vector search returns the tent first, the backpack second and the kettle third.
    queries = [EvalQuery(CAMPING_QUERY, "description", frozenset({TENT_URL, KETTLE_URL}))]

    metrics = evaluate(queries, embedder=embedder)[SearchMode.VECTOR].overall

    # One result cannot hold both products: recall@1 is out of the one that fits.
    assert quality(metrics) == pytest.approx((1, 1, 1))


def test_recall_at_1_is_zero_when_the_first_result_is_not_relevant(embedder):
    queries = [EvalQuery(CAMPING_QUERY, "description", frozenset({BACKPACK_URL, KETTLE_URL}))]

    metrics = evaluate(queries, embedder=embedder)[SearchMode.VECTOR].overall

    assert quality(metrics) == pytest.approx((0, 1, 0.5))


def test_latency_percentiles_are_interpolated_between_the_measured_times(embedder):
    # The three queries take 10, 20 and 40 ms in every mode.
    clock = FakeClock([0.010, 0.020, 0.040])

    report = evaluate(QUERIES, embedder=embedder, clock=clock)

    for mode_report in report.values():
        overall, kinds = mode_report.overall, mode_report.kinds
        assert (overall.latency_p50_ms, overall.latency_p95_ms) == pytest.approx((20, 38))
        assert kinds["model_number"].latency_p50_ms == pytest.approx(10)
        assert kinds["model_number"].latency_p95_ms == pytest.approx(10)
        assert kinds["description"].latency_p50_ms == pytest.approx(30)
        assert kinds["description"].latency_p95_ms == pytest.approx(39)


class SlowToLoad:
    """Embedder whose first query takes five seconds, like a model loaded on first use."""

    def __init__(self, embedder: FakeEmbedder, clock: FakeClock):
        self.model_name = embedder.model_name
        self.dimensions = embedder.dimensions
        self.embed_documents = embedder.embed_documents
        self._embedder = embedder
        self._clock = clock
        self._loaded = False

    def embed_query(self, text: str) -> list[float]:
        if not self._loaded:
            self._clock.advance(5)
            self._loaded = True
        return self._embedder.embed_query(text)


def test_loading_the_embedding_model_is_not_measured(embedder):
    clock = FakeClock([0.010])

    report = evaluate(QUERIES, embedder=SlowToLoad(embedder, clock), clock=clock)

    assert report[SearchMode.VECTOR].overall.latency_p95_ms == pytest.approx(10)


def test_no_queries_cannot_be_evaluated(embedder):
    with pytest.raises(ValueError, match="no queries"):
        evaluate([], embedder=embedder)


def test_unknown_urls_are_the_relevant_urls_that_are_not_products(embedder):
    queries = [
        EvalQuery("a", "description", frozenset({TENT_URL, "https://shop.example/gone"})),
        EvalQuery("b", "description", frozenset({STOVE_URL, "https://shop.example/gone"})),
    ]

    assert unknown_urls(queries) == ["https://shop.example/gone"]


def write_lines(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_queries_reads_one_query_per_line_and_skips_blank_lines(tmp_path: Path):
    path = write_lines(
        tmp_path / "queries.jsonl",
        json.dumps({"query": " WH-1000XM5 ", "kind": "model_number", "relevant": [TENT_URL]}),
        "",
        json.dumps(
            {"query": "намет", "kind": "description", "relevant": [TENT_URL, STOVE_URL]},
            ensure_ascii=False,
        ),
    )

    assert load_queries(path) == [
        EvalQuery("WH-1000XM5", "model_number", frozenset({TENT_URL})),
        EvalQuery("намет", "description", frozenset({TENT_URL, STOVE_URL})),
    ]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("{not json", "line 2: not valid JSON"),
        ('["a list"]', "line 2: expected an object"),
        ('{"kind": "description", "relevant": ["https://a.example/1"]}', 'line 2: "query"'),
        ('{"query": " ", "kind": "x", "relevant": ["https://a.example/1"]}', 'line 2: "query"'),
        ('{"query": "q", "kind": 5, "relevant": ["https://a.example/1"]}', 'line 2: "kind"'),
        ('{"query": "q", "kind": "x", "relevant": []}', 'line 2: "relevant"'),
        ('{"query": "q", "kind": "x", "relevant": "https://a.example/1"}', 'line 2: "relevant"'),
        ('{"query": "q", "kind": "x", "relevant": [1]}', 'line 2: "relevant"'),
    ],
)
def test_load_queries_names_the_line_that_is_wrong(tmp_path: Path, line: str, message: str):
    valid = json.dumps({"query": "q", "kind": "description", "relevant": [TENT_URL]})
    path = write_lines(tmp_path / "queries.jsonl", valid, line)

    with pytest.raises(ValueError, match=message):
        load_queries(path)
