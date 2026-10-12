"""Project wiring: settings helpers, SQLite options, Django system checks."""

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command

from config.settings import env_bool, env_list, env_str


def test_django_system_check_passes():
    call_command("check")


def test_sqlite_is_configured_for_two_processes():
    options = settings.DATABASES["default"]["OPTIONS"]
    assert options["init_command"] == "PRAGMA journal_mode=WAL;"
    assert options["timeout"] == 5
    assert options["transaction_mode"] == "IMMEDIATE"


def test_env_str_requires_value_without_default(monkeypatch):
    monkeypatch.delenv("PCD_MISSING", raising=False)
    with pytest.raises(ImproperlyConfigured, match="PCD_MISSING"):
        env_str("PCD_MISSING")


def test_env_str_treats_empty_value_as_missing(monkeypatch):
    monkeypatch.setenv("PCD_EMPTY", "")
    assert env_str("PCD_EMPTY", "fallback") == "fallback"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False)],
)
def test_env_bool(monkeypatch, raw, expected):
    monkeypatch.setenv("PCD_FLAG", raw)
    assert env_bool("PCD_FLAG", default=not expected) is expected


def test_env_list_splits_and_strips(monkeypatch):
    monkeypatch.setenv("PCD_LIST", " a.example , b.example ,")
    assert env_list("PCD_LIST", "") == ["a.example", "b.example"]


def test_tests_use_known_api_key():
    assert settings.API_KEY == "test-api-key"
