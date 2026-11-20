import contextlib
import json
import logging

import httpx2
import openai
import pytest

from tracker.services.answerer import (
    AnswererNotConfigured,
    AnswerError,
    ContextChunk,
    OpenAIAnswerer,
    SubmittedAnswer,
    TokenUsage,
    get_answerer,
)

BASE_URL = "https://litellm.example/v1"
TOKEN = "sk-litellm-secret-token"
MODEL = "test-model"
QUESTION = "How long does the battery last?"
CHUNKS = [
    ContextChunk(chunk_id=11, product_name="Sony WH-1000XM5", text="30 hours of battery life."),
    ContextChunk(chunk_id=12, product_name="Bosch TWK 7203", text="Electric kettle, 1.7 litres."),
]
ARGUMENTS = {"answerable": True, "answer": "30 hours.", "source_chunk_ids": [11]}


def tool_call(arguments, name: str = "submit_answer") -> dict:
    return {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
        },
    }


def completion(*tool_calls: dict, usage: dict | None = None) -> dict:
    """A chat completion as an OpenAI-compatible API returns it."""
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None, "tool_calls": list(tool_calls)},
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return body


class FakeLLM:
    """Stands in for the HTTP API: replies with `response` or raises `error`, keeps requests."""

    def __init__(self, response: httpx2.Response | None = None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response

    @property
    def payload(self) -> dict:
        return json.loads(self.requests[-1].content)


def llm_replying(*tool_calls: dict, usage: dict | None = None) -> FakeLLM:
    return FakeLLM(httpx2.Response(200, json=completion(*tool_calls, usage=usage)))


def make_answerer(llm: FakeLLM) -> OpenAIAnswerer:
    http_client = openai.DefaultHttpxClient(transport=httpx2.MockTransport(llm))
    return OpenAIAnswerer(BASE_URL, TOKEN, MODEL, http_client=http_client)


def test_the_tool_call_becomes_the_answer_with_token_usage():
    llm = llm_replying(
        tool_call(ARGUMENTS),
        usage={"prompt_tokens": 210, "completion_tokens": 25, "total_tokens": 235},
    )

    generation = make_answerer(llm).answer(QUESTION, CHUNKS)

    assert generation.answer == SubmittedAnswer(
        answerable=True, answer="30 hours.", source_chunk_ids=[11]
    )
    assert generation.usage == TokenUsage(prompt_tokens=210, completion_tokens=25, total_tokens=235)


def test_usage_is_zero_when_the_api_reports_none():
    generation = make_answerer(llm_replying(tool_call(ARGUMENTS))).answer(QUESTION, CHUNKS)

    assert generation.usage == TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)


def test_the_request_goes_to_the_configured_api_with_the_configured_model():
    llm = llm_replying(tool_call(ARGUMENTS))

    make_answerer(llm).answer(QUESTION, CHUNKS)

    request = llm.requests[0]
    assert (request.method, str(request.url)) == ("POST", f"{BASE_URL}/chat/completions")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert llm.payload["model"] == MODEL


def test_the_answer_is_forced_through_one_strict_function_tool():
    llm = llm_replying(tool_call(ARGUMENTS))

    make_answerer(llm).answer(QUESTION, CHUNKS)

    assert llm.payload["tool_choice"] == {"type": "function", "function": {"name": "submit_answer"}}
    [tool] = llm.payload["tools"]
    function = tool["function"]
    parameters = function["parameters"]
    assert (tool["type"], function["name"], function["strict"]) == (
        "function",
        "submit_answer",
        True,
    )
    assert parameters["type"] == "object"
    assert parameters["additionalProperties"] is False
    assert parameters["required"] == ["answerable", "answer", "source_chunk_ids"]
    assert parameters["properties"]["answerable"]["type"] == "boolean"
    assert parameters["properties"]["answer"]["type"] == "string"
    assert parameters["properties"]["source_chunk_ids"]["type"] == "array"
    assert parameters["properties"]["source_chunk_ids"]["items"] == {"type": "integer"}


def test_the_prompt_holds_the_question_and_every_chunk_with_its_id():
    llm = llm_replying(tool_call(ARGUMENTS))

    make_answerer(llm).answer(QUESTION, CHUNKS)

    system, user = llm.payload["messages"]
    assert (system["role"], user["role"]) == ("system", "user")
    assert QUESTION in user["content"]
    for chunk in CHUNKS:
        assert f'chunk_id="{chunk.chunk_id}"' in user["content"]
        assert chunk.product_name in user["content"]
        assert chunk.text in user["content"]


@pytest.mark.parametrize(
    "arguments",
    [
        "not json",
        {"answerable": True, "answer": "30 hours."},
        {"answerable": "yes", "answer": "30 hours.", "source_chunk_ids": [11]},
        {"answerable": True, "answer": "30 hours.", "source_chunk_ids": ["11"]},
        {"answerable": True, "answer": "30 hours.", "source_chunk_ids": [11], "confidence": 1},
    ],
    ids=["not-json", "missing-field", "bool-as-text", "id-as-text", "extra-field"],
)
def test_arguments_that_do_not_match_the_schema_are_rejected(arguments):
    answerer = make_answerer(llm_replying(tool_call(arguments)))

    with pytest.raises(AnswerError, match="invalid submit_answer arguments"):
        answerer.answer(QUESTION, CHUNKS)


@pytest.mark.parametrize(
    "tool_calls", [[], [tool_call(ARGUMENTS, name="search_web")]], ids=["no-call", "other-tool"]
)
def test_a_reply_without_the_submit_answer_call_is_rejected(tool_calls):
    answerer = make_answerer(llm_replying(*tool_calls))

    with pytest.raises(AnswerError, match="did not call submit_answer"):
        answerer.answer(QUESTION, CHUNKS)


def test_a_reply_without_choices_is_rejected():
    llm = FakeLLM(httpx2.Response(200, json={**completion(), "choices": []}))

    with pytest.raises(AnswerError, match="did not call submit_answer"):
        make_answerer(llm).answer(QUESTION, CHUNKS)


def test_an_api_error_is_reported_by_its_status_without_the_token():
    # A proxy may echo the key it was given in the error body.
    body = {"error": {"message": f"Invalid key: {TOKEN}"}}
    llm = FakeLLM(httpx2.Response(401, json=body))

    with pytest.raises(AnswerError) as excinfo:
        make_answerer(llm).answer(QUESTION, CHUNKS)

    assert str(excinfo.value) == "LLM API returned HTTP 401"
    assert excinfo.value.__suppress_context__ is True


def test_a_failed_request_is_not_retried():
    llm = FakeLLM(httpx2.Response(500, json={"error": {"message": "overloaded"}}))

    with pytest.raises(AnswerError, match="LLM API returned HTTP 500"):
        make_answerer(llm).answer(QUESTION, CHUNKS)

    assert len(llm.requests) == 1


def test_a_network_error_is_reported_without_the_token():
    llm = FakeLLM(error=httpx2.ConnectError(f"cannot reach the proxy with {TOKEN}"))

    with pytest.raises(AnswerError) as excinfo:
        make_answerer(llm).answer(QUESTION, CHUNKS)

    assert str(excinfo.value) == "LLM API request failed: APIConnectionError"
    assert excinfo.value.__suppress_context__ is True


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(200, json=completion(tool_call(ARGUMENTS))),
        httpx2.Response(401, json={"error": {"message": f"Invalid key: {TOKEN}"}}),
    ],
    ids=["success", "error"],
)
def test_the_token_is_never_logged(caplog, response):
    answerer = make_answerer(FakeLLM(response))

    with caplog.at_level(logging.DEBUG), contextlib.suppress(AnswerError):
        answerer.answer(QUESTION, CHUNKS)

    assert caplog.records  # the SDK did log something at this level
    assert TOKEN not in caplog.text


def test_openai_environment_variables_are_ignored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    monkeypatch.setenv("OPENAI_ADMIN_KEY", "ambient-admin-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.example/v1")
    monkeypatch.setenv("OPENAI_ORG_ID", "ambient-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "ambient-project")
    monkeypatch.setenv("OPENAI_WEBHOOK_SECRET", "ambient-webhook-secret")
    monkeypatch.setenv(
        "OPENAI_CUSTOM_HEADERS", "Authorization: Bearer ambient-header\nX-Extra: ambient-extra"
    )
    llm = llm_replying(tool_call(ARGUMENTS))

    make_answerer(llm).answer(QUESTION, CHUNKS)

    request = llm.requests[0]
    assert str(request.url) == f"{BASE_URL}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert "ambient" not in str(request.headers.multi_items())


def test_get_answerer_is_configured_from_settings_and_shared(settings):
    settings.LLM_BASE_URL = BASE_URL
    settings.LLM_AUTH_TOKEN = TOKEN
    settings.LLM_MODEL = MODEL

    answerer = get_answerer()

    assert isinstance(answerer, OpenAIAnswerer)
    assert answerer.model == MODEL
    assert get_answerer() is answerer


@pytest.mark.parametrize(
    ("setting", "variable"),
    [
        ("LLM_BASE_URL", "PCD_LLM_BASE_URL"),
        ("LLM_AUTH_TOKEN", "PCD_LLM_AUTH_TOKEN"),
        ("LLM_MODEL", "PCD_LLM_MODEL"),
    ],
)
def test_get_answerer_names_the_missing_variable(settings, setting, variable):
    settings.LLM_BASE_URL = BASE_URL
    settings.LLM_AUTH_TOKEN = TOKEN
    settings.LLM_MODEL = MODEL
    setattr(settings, setting, "")

    with pytest.raises(AnswererNotConfigured) as excinfo:
        get_answerer()

    assert str(excinfo.value) == f"Question answering is not configured: set {variable}"
    assert TOKEN not in str(excinfo.value)


def test_the_llm_is_not_configured_under_the_test_settings(settings):
    # A developer's own PCD_LLM_* variables must not let a test reach a real LLM.
    assert (settings.LLM_BASE_URL, settings.LLM_AUTH_TOKEN, settings.LLM_MODEL) == ("", "", "")
