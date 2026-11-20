"""manage.py eval_answers — check the answers to a file of labelled questions."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tracker.services.answer_evaluation import (
    AnswerReport,
    evaluate_answers,
    load_questions,
    unknown_source_urls,
)
from tracker.services.answerer import AnswererNotConfigured, get_answerer
from tracker.services.embedder import get_embedder

# Unknown URLs listed in the warning before the rest is only counted.
LISTED_UNKNOWN_URLS = 5


class Command(BaseCommand):
    help = (
        "Put every question of a JSON Lines file ({question, source_url, must_contain: "
        "[strings]}, or {question, answerable: false}, per line) to the code behind "
        "POST /ask and print the share of the answers that pass each check: the answerable "
        "flag is right, the sources include source_url, the answer has every must_contain "
        "string. Also prints the latency percentiles and the tokens used. "
        "--verbosity 2 lists the questions that missed a check."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", type=Path, help="JSON Lines file with the questions.")

    def handle(self, *args, **options):
        path: Path = options["file"]
        try:
            questions = load_questions(path)
        except (OSError, ValueError) as exc:
            raise CommandError(f"Cannot read {path}: {exc}") from None
        if not questions:
            raise CommandError(f"{path} has no questions")
        try:
            answerer = get_answerer()
        except AnswererNotConfigured as exc:
            raise CommandError(str(exc)) from None
        self._warn_about_unknown_urls(unknown_source_urls(questions))

        report = evaluate_answers(questions, embedder=get_embedder(), answerer=answerer)
        self.stdout.write(_summary(report))
        if report.failed:
            self.stderr.write(
                self.style.WARNING(
                    f"{report.failed} question(s) got no usable answer from the LLM: "
                    "they fail their checks and are left out of the latency"
                )
            )
        if options["verbosity"] >= 2:
            for line in _missed(report):
                self.stdout.write(line)

    def _warn_about_unknown_urls(self, urls: list[str]) -> None:
        if not urls:
            return
        listed = ", ".join(urls[:LISTED_UNKNOWN_URLS])
        if len(urls) > LISTED_UNKNOWN_URLS:
            listed += f" and {len(urls) - LISTED_UNKNOWN_URLS} more"
        self.stderr.write(
            self.style.WARNING(
                f"{len(urls)} source URL(s) are not products in the database: {listed}"
            )
        )


def _summary(report: AnswerReport) -> str:
    width = max(map(len, report.checks))
    lines = [f"{'check':<{width}}  correct  total  share"]
    for name, share in report.checks.items():
        value = "-" if share.value is None else f"{share.value:.3f}"
        lines.append(f"{name:<{width}}  {share.correct:>7}  {share.total:>5}  {value:>5}")
    usage = report.usage
    lines += [
        "",
        f"latency  p50 {report.latency_p50_ms:.1f} ms  p95 {report.latency_p95_ms:.1f} ms",
        f"tokens   {usage.total_tokens} total "
        f"({usage.prompt_tokens} prompt, {usage.completion_tokens} completion)",
    ]
    return "\n".join(lines)


def _missed(report: AnswerReport) -> list[str]:
    """A line per question that missed a check: the checks, or why there was no answer."""
    lines = []
    for outcome in report.outcomes:
        missed = [check for check, passed in outcome.checks.items() if not passed]
        if missed:
            reason = outcome.error or ", ".join(missed)
            lines.append(f"missed [{reason}] {outcome.question.question}")
    return lines
