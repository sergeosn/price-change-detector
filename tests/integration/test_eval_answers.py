import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from tests.helpers import (
    GRINDER_TEXT,
    HEADPHONES_SPECS,
    MODEL_QUERY,
    PARAPHRASE_QUERY,
    TENT_TEXT,
    FakeAnswerer,
    FakeEmbedder,
    seed_search_corpus,
)
from tracker.models import Chunk
from tracker.services.answerer import AnswerError, SubmittedAnswer, TokenUsage

pytestmark = pytest.mark.django_db

HEADPHONES_URL = "https://shop.example/item/1"
GRINDER_URL = "https://shop.example/item/2"
WARRANTY_QUESTION = "How long is the warranty on the tent?"
QUESTIONS = [
    {
        "question": MODEL_QUERY,
        "answerable": True,
        "source_url": HEADPHONES_URL,
        "must_contain": ["30 hours"],
    },
    {
        "question": PARAPHRASE_QUERY,
        "answerable": True,
        "source_url": GRINDER_URL,
        "must_contain": ["steel burrs"],
    },
    {"question": WARRANTY_QUESTION, "answerable": False},
]


@pytest.fixture(autouse=True)
def embedder(monkeypatch) -> FakeEmbedder:
    embedder = seed_search_corpus()
    monkeypatch.setattr("tracker.management.commands.eval_answers.get_embedder", lambda: embedder)
    return embedder


@pytest.fixture
def answerer(monkeypatch) -> FakeAnswerer:
    """The headphones are answered right; the grinder answer has the wrong fact and source."""
    answerer = FakeAnswerer(
        replies={
            MODEL_QUERY: reply("Up to 30 hours.", HEADPHONES_SPECS),
            PARAPHRASE_QUERY: reply("Ceramic burrs.", TENT_TEXT),
            WARRANTY_QUESTION: SubmittedAnswer(answerable=False, answer="", source_chunk_ids=[]),
        },
        usage=TokenUsage(prompt_tokens=600, completion_tokens=40, total_tokens=640),
    )
    monkeypatch.setattr("tracker.management.commands.eval_answers.get_answerer", lambda: answerer)
    return answerer


@pytest.fixture
def questions_file(tmp_path: Path) -> Path:
    return write_questions(tmp_path / "qa.jsonl", QUESTIONS)


def reply(answer: str, *source_texts: str) -> SubmittedAnswer:
    return SubmittedAnswer(
        answerable=True,
        answer=answer,
        source_chunk_ids=[Chunk.objects.get(text=text).pk for text in source_texts],
    )


def write_questions(path: Path, questions: list[dict]) -> Path:
    lines = [json.dumps(question, ensure_ascii=False) for question in questions]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run(*args: object) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("eval_answers", *map(str, args), stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def rows(out: str) -> dict[str, list[str]]:
    """The printed lines as {first word: the other words}."""
    return {cells[0]: cells[1:] for cells in map(str.split, out.splitlines()) if cells}


def test_prints_the_share_correct_per_check(questions_file: Path, answerer):
    out, err = run(questions_file)

    printed = rows(out)
    assert printed["check"] == ["correct", "total", "share"]
    assert printed["answerable"] == ["3", "3", "1.000"]
    # Of the two questions that have an answer in the corpus.
    assert printed["sources"] == ["1", "2", "0.500"]
    assert printed["must_contain"] == ["1", "2", "0.500"]
    assert err == ""


def test_prints_the_latency_percentiles_and_the_total_tokens(questions_file: Path, answerer):
    out, _ = run(questions_file)

    printed = rows(out)
    label_p50, p50, unit_p50, label_p95, p95, unit_p95 = printed["latency"]
    assert (label_p50, unit_p50, label_p95, unit_p95) == ("p50", "ms", "p95", "ms")
    assert float(p95) >= float(p50) >= 0
    assert printed["tokens"] == ["1920", "total", "(1800", "prompt,", "120", "completion)"]


def test_a_check_no_question_has_gets_no_share(tmp_path: Path, answerer):
    path = write_questions(tmp_path / "qa.jsonl", [QUESTIONS[2]])

    out, _ = run(path)

    printed = rows(out)
    assert printed["answerable"] == ["1", "1", "1.000"]
    assert printed["sources"] == ["0", "0", "-"]
    assert printed["must_contain"] == ["0", "0", "-"]


def test_questions_the_llm_failed_on_are_reported(questions_file: Path, answerer):
    answerer.replies[MODEL_QUERY] = AnswerError("LLM API returned HTTP 500")

    out, err = run(questions_file)

    assert rows(out)["answerable"] == ["2", "3", "0.667"]
    assert "1 question(s) got no usable answer from the LLM" in err


def test_the_questions_that_missed_a_check_are_listed_only_when_verbose(
    questions_file: Path, answerer
):
    answerer.replies[WARRANTY_QUESTION] = AnswerError("LLM API returned HTTP 500")
    quiet, _ = run(questions_file)

    verbose, _ = run(questions_file, "--verbosity", 2)

    assert f"missed [sources, must_contain] {PARAPHRASE_QUERY}" in verbose
    assert f"missed [LLM API returned HTTP 500] {WARRANTY_QUESTION}" in verbose
    # The headphones question passed every check.
    assert verbose.count("missed [") == 2
    assert "missed [" not in quiet


def test_the_questions_go_through_the_code_of_the_ask_endpoint(questions_file: Path, answerer):
    answerer.replies[PARAPHRASE_QUERY] = reply("Steel burrs.", GRINDER_TEXT)

    out, _ = run(questions_file)

    assert [question for question, _ in answerer.calls] == [
        MODEL_QUERY,
        PARAPHRASE_QUERY,
        WARRANTY_QUESTION,
    ]
    # Five chunks, one per product, as POST /ask retrieves by default.
    assert all(len(chunks) == 5 for _, chunks in answerer.calls)
    assert rows(out)["sources"] == ["2", "2", "1.000"]


def test_without_the_llm_settings_nothing_is_evaluated(questions_file: Path, embedder):
    # The real answerer factory: the test settings configure no LLM.
    with pytest.raises(CommandError, match="set PCD_LLM_BASE_URL, PCD_LLM_AUTH_TOKEN"):
        run(questions_file)

    assert embedder.query_calls == []


def test_a_missing_file_is_a_command_error(tmp_path: Path, answerer):
    with pytest.raises(CommandError, match="Cannot read"):
        run(tmp_path / "missing.jsonl")


def test_an_invalid_line_is_a_command_error(tmp_path: Path, answerer):
    path = tmp_path / "qa.jsonl"
    path.write_text('{"question": "no source", "must_contain": ["x"]}\n', encoding="utf-8")

    with pytest.raises(CommandError, match='line 1: "source_url"'):
        run(path)


def test_a_file_without_questions_is_a_command_error(tmp_path: Path, answerer):
    path = tmp_path / "qa.jsonl"
    path.write_text("\n", encoding="utf-8")

    with pytest.raises(CommandError, match="has no questions"):
        run(path)
    assert answerer.calls == []


def test_warns_about_source_urls_that_are_not_products(tmp_path: Path, answerer):
    gone = "https://shop.example/gone"
    path = write_questions(tmp_path / "qa.jsonl", [{**QUESTIONS[0], "source_url": gone}])

    out, err = run(path)

    assert f"1 source URL(s) are not products in the database: {gone}" in err
    assert rows(out)["sources"] == ["0", "1", "0.000"]


def test_the_warning_lists_only_the_first_unknown_urls(tmp_path: Path, answerer):
    gone = [f"https://shop.example/gone/{number}" for number in range(1, 8)]
    path = write_questions(
        tmp_path / "qa.jsonl", [{**QUESTIONS[0], "source_url": url} for url in gone]
    )

    _, err = run(path)

    assert "7 source URL(s) are not products in the database" in err
    assert f"{gone[4]} and 2 more" in err
    assert gone[5] not in err
