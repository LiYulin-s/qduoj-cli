"""Terminal rendering: HTML to plain text, problem and submission display."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import typer

from .models import RESULT_NAMES, Problem, SubmissionDetail, is_final

_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "table", "blockquote", "ul", "ol", "hr", "section",
}


class _HTMLToText(HTMLParser):
    """Drop tags, keep text, and insert line breaks around block elements."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self._chunks.append("\n")
        elif tag in ("td", "th"):
            self._chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS or tag in ("td", "th"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def result(self) -> str:
        text = "".join(self._chunks)
        lines = [line.strip() for line in text.splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    parser = _HTMLToText()
    parser.feed(html)
    return parser.result()


def _section(title: str) -> None:
    typer.secho(f"\n-- {title} --", fg=typer.colors.CYAN, bold=True)


def print_problem(problem: Problem) -> None:
    tags = f"  [{', '.join(problem.tags)}]" if problem.tags else ""
    typer.secho(f"{problem.display_id}: {problem.title}", fg=typer.colors.GREEN, bold=True)
    typer.echo(
        f"Time limit: {problem.time_limit} ms  Memory limit: {problem.memory_limit} MB"
        f"  Rule: {problem.rule_type or '-'}{tags}"
    )
    typer.echo(f"Languages: {', '.join(problem.languages)}")

    for title, content in (
        ("Description", problem.description),
        ("Input", problem.input_description),
        ("Output", problem.output_description),
        ("Hint", problem.hint),
    ):
        if not content:
            continue
        _section(title)
        typer.echo(html_to_text(content))

    for idx, sample in enumerate(problem.samples, 1):
        _section(f"Sample {idx} Input")
        typer.echo(sample.input.rstrip("\n"))
        _section(f"Sample {idx} Output")
        typer.echo(sample.output.rstrip("\n"))


_VERDICT_COLORS = {
    "AC": typer.colors.GREEN,
    "WA": typer.colors.RED,
    "TLE": typer.colors.YELLOW,
    "MLE": typer.colors.YELLOW,
    "CE": typer.colors.CYAN,
    "RE": typer.colors.MAGENTA,
    "PA": typer.colors.YELLOW,
}


def verdict_text(result: int) -> str:
    abbr, desc = RESULT_NAMES.get(result, ("?", f"Unknown status {result}"))
    color = _VERDICT_COLORS.get(abbr)
    return typer.style(f"{abbr} ({desc})", fg=color) if color else f"{abbr} ({desc})"


def testcase_text(index: int, result: int) -> str:
    return f"Case {index}: {verdict_text(result)}"


def print_submission(detail: SubmissionDetail, *, include_cases: bool = True) -> None:
    typer.secho(f"Result: {verdict_text(detail.result)}", bold=True)
    stat = detail.statistic_info or {}
    parts = []
    if stat.get("time_cost") is not None:
        parts.append(f"time {stat['time_cost']} ms")
    if stat.get("memory_cost") is not None:
        parts.append(f"memory {stat['memory_cost']} KB")
    if stat.get("score") is not None:
        parts.append(f"score {stat['score']}")
    if parts:
        typer.echo("  ".join(parts))
    if detail.result == -2 and stat.get("err_info"):
        typer.secho("Compiler output:", fg=typer.colors.CYAN)
        typer.echo(stat["err_info"])
    if not include_cases:
        return
    info = detail.info or {}
    cases = info.get("data")
    if isinstance(cases, list):
        for idx, case in enumerate(cases, 1):
            typer.echo(testcase_text(idx, case.get("result")))


def new_testcases(detail: SubmissionDetail, printed: int) -> list[tuple[int, int]]:
    """Return (index, result) pairs for cases after `printed` that are final.

    Stops at the first non-final case so streamed output stays ordered.
    """
    info = detail.info or {}
    cases = info.get("data")
    if not isinstance(cases, list):
        return []
    out = []
    for idx, case in enumerate(cases[printed:], printed + 1):
        result = case.get("result")
        if isinstance(result, int) and is_final(result):
            out.append((idx, result))
        else:
            break
    return out
