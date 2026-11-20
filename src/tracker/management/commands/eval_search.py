"""manage.py eval_search — measure every search mode on a file of labelled queries."""

import json
from dataclasses import asdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tracker.services.embedder import get_embedder
from tracker.services.evaluation import (
    DEPTH,
    Metrics,
    ModeReport,
    evaluate,
    load_queries,
    unknown_urls,
)

# Unknown URLs listed in the warning before the rest is only counted.
LISTED_UNKNOWN_URLS = 5


class Command(BaseCommand):
    help = (
        "Run every query of a JSON Lines file ({query, kind, relevant: [urls]} per line) in "
        "the vector, lexical and hybrid modes and print recall@1, recall@5, MRR and the "
        "latency percentiles, overall and per kind. The numbers are also written as JSON."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path, help="JSON Lines file with the queries.")
        parser.add_argument(
            "--output",
            type=Path,
            help="File for the numbers (default: <file name>.results.json next to the input).",
        )

    def handle(self, *args, **options):
        path: Path = options["file"]
        output: Path = options["output"] or path.with_suffix(".results.json")
        try:
            queries = load_queries(path)
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read {path}: {exc}") from None
        if not queries:
            raise CommandError(f"{path} has no queries")
        self._warn_about_unknown_urls(unknown_urls(queries))

        embedder = get_embedder()
        report = evaluate(queries, embedder=embedder)
        for mode, mode_report in report.items():
            self.stdout.write(_table(mode.value, mode_report))
            self.stdout.write("")

        numbers = {
            "queries": len(queries),
            "depth": DEPTH,
            "embedding_model": embedder.model_name,
            "modes": {
                mode.value: {
                    "overall": _numbers(mode_report.overall),
                    "kinds": {kind: _numbers(m) for kind, m in mode_report.kinds.items()},
                }
                for mode, mode_report in report.items()
            },
        }
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(numbers, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise CommandError(
                f"Cannot write {output}: {exc} (--output writes to another file)"
            ) from None
        self.stdout.write(f"Wrote the numbers to {output}")

    def _warn_about_unknown_urls(self, urls: list[str]) -> None:
        if not urls:
            return
        listed = ", ".join(urls[:LISTED_UNKNOWN_URLS])
        if len(urls) > LISTED_UNKNOWN_URLS:
            listed += f" and {len(urls) - LISTED_UNKNOWN_URLS} more"
        self.stderr.write(
            self.style.WARNING(
                f"{len(urls)} relevant URL(s) are not products in the database: {listed}"
            )
        )


def _table(title: str, report: ModeReport) -> str:
    rows = {"overall": report.overall, **report.kinds}
    width = max(map(len, rows))
    lines = [
        title,
        f"{'kind':<{width}}  queries  recall@1  recall@5    MRR   p50 ms   p95 ms",
    ]
    lines += [
        f"{name:<{width}}  {m.queries:>7}  {m.recall_at_1:>8.3f}  {m.recall_at_5:>8.3f}"
        f"  {m.mrr:>5.3f}  {m.latency_p50_ms:>7.1f}  {m.latency_p95_ms:>7.1f}"
        for name, m in rows.items()
    ]
    return "\n".join(lines)


def _numbers(metrics: Metrics) -> dict[str, float]:
    return {name: round(value, 4) for name, value in asdict(metrics).items()}
