import json
from pathlib import Path

import pytest

from tests.helpers import (
    GRINDER_TEXT,
    HEADPHONES_SPECS,
    MODEL_QUERY,
    PARAPHRASE_QUERY,
    TENT_TEXT,
    FakeAnswerer,
    FakeClock,
    FakeEmbedder,
    seed_search_corpus,
)
from tracker.models import Chunk
from tracker.services.answer_evaluation import (
    EvalQuestion,
    Share,
    evaluate_answers,
    load_questions,
    unknown_source_urls,
)
from tracker.services.answerer import AnswerError, SubmittedAnswer, TokenUsage

pytestmark = pytest.mark.django_db

# Products of the search corpus by number: 1 headphones, 2 grinder, 4 tent.
HEADPHONES_URL = "https://shop.example/item/1"
GRINDER_URL = "https://shop.example/item/2"
TENT_URL = "https://shop.example/item/4"
WARRANTY_QUESTION = "How long is the warranty on the tent?"

BATTERY = EvalQuestion(MODEL_QUERY, True, HEADPHONES_URL, ("30 hours", "USB-C"))
BURRS = EvalQuestion(PARAPHRASE_QUERY, True, GRINDER_URL, ("steel burrs",))
WARRANTY = EvalQuestion(WARRANTY_QUESTION, False)

NOT_ANSWERABLE = SubmittedAnswer(answerable=False, answer="", source_chunk_ids=[])


@pytest.fixture
def embedder() -> FakeEmbedder:
    return seed_search_corpus()


def reply(answer: str, *source_texts: str) -> SubmittedAnswer:
    """An answer that cites the chunks with these texts."""
    return SubmittedAnswer(
        answerable=True,
        answer=answer,
        source_chunk_ids=[Chunk.objects.get(text=text).pk for text in source_texts],
    )


def checks(report) -> dict[str, tuple[int, int]]:
    return {name: (share.correct, share.total) for name, share in report.checks.items()}


def test_a_right_answer_passes_every_check(embedder):
    answerer = FakeAnswerer(
        replies={
            MODEL_QUERY: reply("30 hours, charged over USB-C.", HEADPHONES_SPECS),
            WARRANTY_QUESTION: NOT_ANSWERABLE,
        }
    )

    report = evaluate_answers([BATTERY, WARRANTY], embedder=embedder, answerer=answerer)

    assert report.questions == 2
    # The sources and the facts are checked only where there is something to cite.
    assert checks(report) == {"answerable": (2, 2), "sources": (1, 1), "must_contain": (1, 1)}
    assert report.failed == 0


def test_answering_what_the_corpus_cannot_answer_is_a_wrong_answerable_flag(embedder):
    answerer = FakeAnswerer(reply("Two years.", TENT_TEXT))

    report = evaluate_answers([WARRANTY], embedder=embedder, answerer=answerer)

    assert checks(report) == {"answerable": (0, 1), "sources": (0, 0), "must_contain": (0, 0)}


def test_giving_no_answer_to_an_answerable_question_fails_all_three_checks(embedder):
    report = evaluate_answers(
        [BATTERY, BURRS], embedder=embedder, answerer=FakeAnswerer(NOT_ANSWERABLE)
    )

    assert checks(report) == {"answerable": (0, 2), "sources": (0, 2), "must_contain": (0, 2)}


def test_the_source_url_has_to_be_among_the_cited_products(embedder):
    answerer = FakeAnswerer(
        replies={
            # Cites the tent and the headphones: the expected product is one of the two.
            MODEL_QUERY: reply("30 hours, USB-C.", TENT_TEXT, HEADPHONES_SPECS),
            # The facts are right, but the answer cites only the tent.
            PARAPHRASE_QUERY: reply("It has steel burrs.", TENT_TEXT),
        }
    )

    report = evaluate_answers([BATTERY, BURRS], embedder=embedder, answerer=answerer)

    assert checks(report) == {"answerable": (2, 2), "sources": (1, 2), "must_contain": (2, 2)}
    assert [outcome.checks["sources"] for outcome in report.outcomes] == [True, False]


@pytest.mark.parametrize(
    ("answer", "passed"),
    [
        ("30 HOURS; charges over usb-c.", 1),
        ("30 hours.", 0),
        ("It charges over USB-C.", 0),
    ],
)
def test_must_contain_ignores_case_and_needs_every_string(embedder, answer: str, passed: int):
    answerer = FakeAnswerer(reply(answer, HEADPHONES_SPECS))

    report = evaluate_answers([BATTERY], embedder=embedder, answerer=answerer)

    assert checks(report) == {"answerable": (1, 1), "sources": (1, 1), "must_contain": (passed, 1)}


def test_a_question_the_llm_fails_on_fails_its_checks_and_the_run_goes_on(embedder):
    answerer = FakeAnswerer(
        replies={
            MODEL_QUERY: AnswerError("LLM API returned HTTP 500"),
            WARRANTY_QUESTION: AnswerError("LLM did not call submit_answer"),
            PARAPHRASE_QUERY: reply("Steel burrs.", GRINDER_TEXT),
        }
    )

    report = evaluate_answers([BATTERY, WARRANTY, BURRS], embedder=embedder, answerer=answerer)

    assert checks(report) == {"answerable": (1, 3), "sources": (1, 2), "must_contain": (1, 2)}
    assert report.failed == 2
    assert [outcome.error for outcome in report.outcomes] == [
        "LLM API returned HTTP 500",
        "LLM did not call submit_answer",
        "",
    ]


def test_an_answer_that_cites_a_chunk_that_was_not_retrieved_counts_as_failed(embedder):
    made_up = SubmittedAnswer(answerable=True, answer="30 hours, USB-C.", source_chunk_ids=[999])

    report = evaluate_answers([BATTERY], embedder=embedder, answerer=FakeAnswerer(made_up))

    assert checks(report) == {"answerable": (0, 1), "sources": (0, 1), "must_contain": (0, 1)}
    assert report.failed == 1


def test_latency_percentiles_cover_the_whole_ask_call(embedder):
    # The three questions take 100, 200 and 400 ms from the question to the answer.
    clock = FakeClock([0.1, 0.2, 0.4])

    report = evaluate_answers(
        [BATTERY, BURRS, WARRANTY], embedder=embedder, answerer=FakeAnswerer(), clock=clock
    )

    assert (report.latency_p50_ms, report.latency_p95_ms) == pytest.approx((200, 380))


def test_questions_the_llm_failed_on_are_left_out_of_the_latency(embedder):
    clock = FakeClock([0.1, 60, 0.3])
    answerer = FakeAnswerer(replies={PARAPHRASE_QUERY: AnswerError("LLM API request failed")})

    report = evaluate_answers(
        [BATTERY, BURRS, WARRANTY], embedder=embedder, answerer=answerer, clock=clock
    )

    assert (report.latency_p50_ms, report.latency_p95_ms) == pytest.approx((200, 290))


def test_without_a_single_answer_the_latency_is_zero(embedder):
    answerer = FakeAnswerer(error=AnswerError("LLM API returned HTTP 401"))

    report = evaluate_answers([BATTERY], embedder=embedder, answerer=answerer)

    assert (report.latency_p50_ms, report.latency_p95_ms) == (0, 0)


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


def test_loading_the_embedding_model_is_not_measured_and_costs_no_llm_call(embedder):
    clock = FakeClock([0.1])
    answerer = FakeAnswerer()

    report = evaluate_answers(
        [BATTERY, BURRS], embedder=SlowToLoad(embedder, clock), answerer=answerer, clock=clock
    )

    assert report.latency_p95_ms == pytest.approx(100)
    assert [question for question, _ in answerer.calls] == [MODEL_QUERY, PARAPHRASE_QUERY]


def test_tokens_are_summed_over_the_questions(embedder):
    answerer = FakeAnswerer(
        usage=TokenUsage(prompt_tokens=600, completion_tokens=40, total_tokens=640)
    )

    report = evaluate_answers([BATTERY, BURRS, WARRANTY], embedder=embedder, answerer=answerer)

    assert report.usage == TokenUsage(prompt_tokens=1800, completion_tokens=120, total_tokens=1920)


def test_the_llm_sees_as_many_chunks_as_ask_retrieves_by_default(embedder):
    answerer = FakeAnswerer()

    evaluate_answers([BATTERY], embedder=embedder, answerer=answerer)

    [(_, chunks)] = answerer.calls
    assert len(chunks) == 5


def test_no_questions_cannot_be_evaluated(embedder):
    with pytest.raises(ValueError, match="no questions"):
        evaluate_answers([], embedder=embedder, answerer=FakeAnswerer())


@pytest.mark.parametrize(
    ("share", "value"), [(Share(3, 4), 0.75), (Share(0, 6), 0.0), (Share(0, 0), None)]
)
def test_a_share_of_nothing_has_no_value(share: Share, value: float | None):
    assert share.value == value


def test_unknown_source_urls_are_the_source_urls_that_are_not_products(embedder):
    gone = "https://shop.example/gone"
    questions = [
        BATTERY,
        EvalQuestion("a", True, gone, ("x",)),
        EvalQuestion("b", True, gone, ("y",)),
        WARRANTY,
    ]

    assert unknown_source_urls(questions) == [gone]


def write_lines(path: Path, *lines: str) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_load_questions_reads_one_question_per_line_and_skips_blank_lines(tmp_path: Path):
    path = write_lines(
        tmp_path / "qa.jsonl",
        json.dumps(
            {
                "question": " How long does the battery last? ",
                "answerable": True,
                "source_url": HEADPHONES_URL,
                "must_contain": ["30 hours", "USB-C"],
            }
        ),
        "",
        # Answerable unless it says otherwise.
        json.dumps(
            {"question": "Які жорна?", "source_url": GRINDER_URL, "must_contain": ["сталеві"]},
            ensure_ascii=False,
        ),
        json.dumps({"question": WARRANTY_QUESTION, "answerable": False}),
    )

    assert load_questions(path) == [
        EvalQuestion(
            "How long does the battery last?", True, HEADPHONES_URL, ("30 hours", "USB-C")
        ),
        EvalQuestion("Які жорна?", True, GRINDER_URL, ("сталеві",)),
        EvalQuestion(WARRANTY_QUESTION, False),
    ]


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("{not json", "line 2: not valid JSON"),
        ('["a list"]', "line 2: expected an object"),
        ('{"source_url": "https://a.example/1", "must_contain": ["x"]}', 'line 2: "question"'),
        ('{"question": " ", "answerable": false}', 'line 2: "question"'),
        ('{"question": "q", "answerable": "no"}', 'line 2: "answerable"'),
        ('{"question": "q", "must_contain": ["x"]}', 'line 2: "source_url"'),
        ('{"question": "q", "source_url": "", "must_contain": ["x"]}', 'line 2: "source_url"'),
        ('{"question": "q", "source_url": "https://a.example/1"}', 'line 2: "must_contain"'),
        (
            '{"question": "q", "source_url": "https://a.example/1", "must_contain": []}',
            'line 2: "must_contain"',
        ),
        (
            '{"question": "q", "source_url": "https://a.example/1", "must_contain": "x"}',
            'line 2: "must_contain"',
        ),
        (
            '{"question": "q", "source_url": "https://a.example/1", "must_contain": [" "]}',
            'line 2: "must_contain"',
        ),
        (
            '{"question": "q", "answerable": false, "source_url": "https://a.example/1"}',
            "line 2: a question that is not answerable",
        ),
        (
            '{"question": "q", "answerable": false, "must_contain": ["x"]}',
            "line 2: a question that is not answerable",
        ),
    ],
)
def test_load_questions_names_the_line_that_is_wrong(tmp_path: Path, line: str, message: str):
    valid = json.dumps({"question": "q", "answerable": False})
    path = write_lines(tmp_path / "qa.jsonl", valid, line)

    with pytest.raises(ValueError, match=message):
        load_questions(path)
