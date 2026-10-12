"""manage.py run_scheduler — checks due products every SCHEDULER_TICK_SECONDS."""

import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from notifications.factory import get_notifier
from tracker.services.fetcher import get_fetcher
from tracker.services.scheduler import run_due_checks

logger = logging.getLogger(__name__)

STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


class Command(BaseCommand):
    help = "Check prices of products that are due. Runs forever unless --once is given."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stop = False

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run a single pass and exit.")

    def handle(self, *args, **options):
        once = options.get("once", False)
        fetcher, notifier = get_fetcher(), get_notifier()
        previous_handlers = {sig: signal.signal(sig, self._request_stop) for sig in STOP_SIGNALS}
        try:
            while not self._stop:
                summary = run_due_checks(
                    fetcher=fetcher, notifier=notifier, should_stop=lambda: self._stop
                )
                self.stdout.write(
                    f"Checked {summary.checked}: {summary.ok} ok, {summary.errors} errors"
                )
                if once:
                    break
                self._sleep(settings.SCHEDULER_TICK_SECONDS)
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)

    def _request_stop(self, signum, frame) -> None:
        logger.info("Received signal %s, stopping after the current check", signum)
        self._stop = True

    def _sleep(self, seconds: float) -> None:
        """Sleep in short steps so a stop request is noticed quickly."""
        deadline = time.monotonic() + seconds
        while not self._stop:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.5, remaining))
