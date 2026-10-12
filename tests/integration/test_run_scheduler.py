import signal
from io import StringIO

import pytest
from django.core.management import call_command

from tests.helpers import URL, FakeFetcher, FakeNotifier, jsonld_page, make_product
from tracker.management.commands.run_scheduler import Command
from tracker.models import CheckStatus

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fake_dependencies(monkeypatch):
    fetcher = FakeFetcher({URL: jsonld_page("10")})
    monkeypatch.setattr("tracker.management.commands.run_scheduler.get_fetcher", lambda: fetcher)
    monkeypatch.setattr("tracker.management.commands.run_scheduler.get_notifier", FakeNotifier)
    return fetcher


def test_once_runs_a_single_pass():
    product = make_product()
    out = StringIO()

    call_command("run_scheduler", "--once", stdout=out)

    assert "Checked 1: 1 ok, 0 errors" in out.getvalue()
    product.refresh_from_db()
    assert product.last_check_status == CheckStatus.OK


def test_loop_sleeps_between_passes_until_stop_is_requested(monkeypatch, settings):
    settings.SCHEDULER_TICK_SECONDS = 60
    make_product()
    command = Command(stdout=StringIO())
    sleeps: list[float] = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        command._stop = True

    monkeypatch.setattr(command, "_sleep", fake_sleep)
    command.handle(once=False)

    assert sleeps == [60]


def test_signal_requests_stop_and_handlers_are_restored():
    previous = signal.getsignal(signal.SIGTERM)
    command = Command(stdout=StringIO())

    command.handle(once=True)

    assert signal.getsignal(signal.SIGTERM) is previous
    command._request_stop(signal.SIGTERM, None)
    assert command._stop is True
