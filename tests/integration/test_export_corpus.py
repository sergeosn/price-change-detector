import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from tests.helpers import URL, load_fixture, make_product
from tracker.services.documents import sync_document

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
OTHER_URL = "https://shop.example/item/2"


def run(*args: str) -> str:
    out = StringIO()
    call_command("export_corpus", *args, stdout=out)
    return out.getvalue()


def test_writes_data_corpus_jsonl_in_the_project_directory(tmp_path: Path, settings):
    settings.PROJECT_DIR = tmp_path
    sync_document(make_product(name="Grinder"), load_fixture("content_uk.html"), NOW)
    make_product(url=OTHER_URL)

    out = run()

    path = tmp_path / "data" / "corpus.jsonl"
    assert f"Exported 2 product(s) to {path}" in out
    grinder, other = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert (grinder["url"], grinder["name"], grinder["domain"]) == (URL, "Grinder", "shop.example")
    assert 0 < len(grinder["text"]) <= 1500
    assert "Arabella G55" in grinder["text"]
    assert other == {"url": OTHER_URL, "name": "", "domain": "shop.example", "text": ""}


def test_output_option_changes_the_file(tmp_path: Path, settings):
    settings.PROJECT_DIR = tmp_path
    make_product()
    path = tmp_path / "elsewhere.jsonl"

    out = run("--output", str(path))

    assert f"Exported 1 product(s) to {path}" in out
    assert json.loads(path.read_text(encoding="utf-8"))["url"] == URL
    assert not (tmp_path / "data").exists()


def test_output_that_cannot_be_written_is_a_command_error(tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    with pytest.raises(CommandError, match="Cannot write"):
        run("--output", str(blocker / "corpus.jsonl"))
