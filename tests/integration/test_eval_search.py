import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from tests.helpers import MODEL_QUERY, PARAPHRASE_QUERY, FakeEmbedder, seed_search_corpus

pytestmark = pytest.mark.django_db

HEADPHONES_URL = "https://shop.example/item/1"
GRINDER_URL = "https://shop.example/item/2"
# The lexical search finds the headphones by their model and nothing for the paraphrase;
# the vector search finds the grinder first and the headphones last of five.
QUERIES = [
    {"query": MODEL_QUERY, "kind": "model_number", "relevant": [HEADPHONES_URL]},
    {"query": PARAPHRASE_QUERY, "kind": "description", "relevant": [GRINDER_URL]},
]


@pytest.fixture(autouse=True)
def embedder(monkeypatch) -> FakeEmbedder:
    embedder = seed_search_corpus()
    monkeypatch.setattr("tracker.management.commands.eval_search.get_embedder", lambda: embedder)
    return embedder


@pytest.fixture
def queries_file(tmp_path: Path) -> Path:
    return write_queries(tmp_path / "queries.jsonl", QUERIES)


def write_queries(path: Path, queries: list[dict]) -> Path:
    lines = [json.dumps(query, ensure_ascii=False) for query in queries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(*args: object) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("eval_search", *map(str, args), stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def tables(out: str) -> dict[str, dict[str, list[str]]]:
    """The printed tables as {mode: {row name: cells}}.

    A table is the name of its mode on a line of its own and the rows up to a blank line.
    """
    parsed: dict[str, dict[str, list[str]]] = {}
    table: dict[str, list[str]] | None = None
    for line in out.splitlines():
        cells = line.split()
        if not cells:
            table = None
        elif table is not None:
            table[cells[0]] = cells[1:]
        elif len(cells) == 1:
            table = parsed[cells[0]] = {}
    return parsed


def test_prints_a_table_per_mode_with_overall_and_per_kind_rows(queries_file: Path):
    out, err = run(queries_file)

    printed = tables(out)
    assert list(printed) == ["vector", "lexical", "hybrid"]
    for table in printed.values():
        assert list(table) == ["kind", "overall", "model_number", "description"]
        assert table["kind"] == ["queries", "recall@1", "recall@5", "MRR", "p50", "ms", "p95", "ms"]
    # Queries, recall@1, recall@5 and MRR; the two latencies follow.
    assert printed["vector"]["overall"][:4] == ["2", "0.500", "1.000", "0.600"]
    assert printed["vector"]["model_number"][:4] == ["1", "0.000", "1.000", "0.200"]
    assert printed["lexical"]["overall"][:4] == ["2", "0.500", "0.500", "0.500"]
    assert printed["lexical"]["description"][:4] == ["1", "0.000", "0.000", "0.000"]
    assert printed["hybrid"]["overall"][:4] == ["2", "1.000", "1.000", "1.000"]
    assert all(float(cell) >= 0 for cell in printed["hybrid"]["overall"][4:])
    assert err == ""


def test_writes_the_numbers_as_json_next_to_the_input_file(queries_file: Path):
    out, _ = run(queries_file)

    path = queries_file.with_name("queries.results.json")
    assert f"Wrote the numbers to {path}" in out
    numbers = json.loads(path.read_text(encoding="utf-8"))
    assert numbers["queries"] == 2
    assert numbers["embedding_model"] == "fake-embedder"
    assert list(numbers["modes"]) == ["vector", "lexical", "hybrid"]
    vector = numbers["modes"]["vector"]
    assert list(vector["kinds"]) == ["model_number", "description"]
    assert vector["overall"].keys() == {
        "queries",
        "recall_at_1",
        "recall_at_5",
        "mrr",
        "latency_p50_ms",
        "latency_p95_ms",
    }
    assert (vector["overall"]["recall_at_1"], vector["overall"]["mrr"]) == (0.5, 0.6)
    assert vector["kinds"]["model_number"]["mrr"] == 0.2
    assert numbers["modes"]["lexical"]["kinds"]["model_number"]["recall_at_1"] == 1.0
    assert vector["overall"]["latency_p95_ms"] >= vector["overall"]["latency_p50_ms"] >= 0


def test_output_option_changes_the_file(queries_file: Path, tmp_path: Path):
    path = tmp_path / "elsewhere" / "numbers.json"

    out, _ = run(queries_file, "--output", path)

    assert f"Wrote the numbers to {path}" in out
    assert json.loads(path.read_text(encoding="utf-8"))["queries"] == 2
    assert not queries_file.with_name("queries.results.json").exists()


def test_output_that_cannot_be_written_is_a_command_error(queries_file: Path, tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(CommandError, match="Cannot write"):
        run(queries_file, "--output", blocker / "numbers.json")


def test_a_missing_file_is_a_command_error(tmp_path: Path):
    with pytest.raises(CommandError, match="Cannot read"):
        run(tmp_path / "missing.jsonl")


def test_an_invalid_line_is_a_command_error(tmp_path: Path):
    path = tmp_path / "queries.jsonl"
    path.write_text('{"query": "no kind"}\n', encoding="utf-8")

    with pytest.raises(CommandError, match='line 1: "kind"'):
        run(path)


def test_a_file_without_queries_is_a_command_error(tmp_path: Path):
    path = tmp_path / "queries.jsonl"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(CommandError, match="has no queries"):
        run(path)


def test_warns_about_relevant_urls_that_are_not_products(tmp_path: Path):
    gone = "https://shop.example/gone"
    path = write_queries(
        tmp_path / "queries.jsonl",
        [{"query": MODEL_QUERY, "kind": "model_number", "relevant": [HEADPHONES_URL, gone]}],
    )

    out, err = run(path)

    assert f"1 relevant URL(s) are not products in the database: {gone}" in err
    assert "vector" in out


def test_the_warning_lists_only_the_first_unknown_urls(tmp_path: Path):
    gone = [f"https://shop.example/gone/{number}" for number in range(1, 8)]
    path = write_queries(
        tmp_path / "queries.jsonl",
        [{"query": MODEL_QUERY, "kind": "model_number", "relevant": gone}],
    )

    _, err = run(path)

    assert "7 relevant URL(s) are not products in the database" in err
    assert f"{gone[4]} and 2 more" in err
    assert gone[5] not in err
