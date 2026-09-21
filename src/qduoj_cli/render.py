"""Terminal rendering with rich: HTML to plain text, problem and submission display."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import (
    RESULT_NAMES,
    Contest,
    Problem,
    SubmissionDetail,
    SubmissionListItem,
    User,
    is_final,
)

console = Console()
err_console = Console(stderr=True)

CONTEST_STATUS = {"1": "Not started", "0": "Running", "-1": "Ended"}
_STATUS_STYLES = {"Running": "green", "Not started": "yellow", "Ended": "dim"}

_VERDICT_STYLES = {
    "AC": "bold green",
    "WA": "bold red",
    "TLE": "yellow",
    "MLE": "yellow",
    "CE": "cyan",
    "RE": "magenta",
    "PA": "yellow",
    "Pending": "dim",
    "Judging": "dim",
}

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


def print_error(message: str) -> None:
    err_console.print(Text.assemble(("Error: ", "bold red"), (message, "red")))


def print_warning(message: str) -> None:
    err_console.print(Text.assemble(("Warning: ", "bold yellow"), (message, "yellow")))


def print_ok(message: str) -> None:
    console.print(Text(message, style="bold green"))


def verdict_text(result: int) -> Text:
    abbr, desc = RESULT_NAMES.get(result, ("?", f"Unknown status {result}"))
    style = _VERDICT_STYLES.get(abbr)
    return Text.assemble((abbr, style), (f" ({desc})", "dim"))


def testcase_text(index: int, result: int) -> Text:
    return Text.assemble((f"Case {index}: ", ""), verdict_text(result))


def print_problem(problem: Problem) -> None:
    header = Text()
    header.append(f"{problem.display_id}: {problem.title}", style="bold green")
    if problem.tags:
        header.append(f"  [{', '.join(problem.tags)}]", style="cyan")
    console.print(header)
    console.print(
        Text.assemble(
            ("Time limit ", "dim"), (f"{problem.time_limit} ms", "bold"),
            ("   Memory limit ", "dim"), (f"{problem.memory_limit} MB", "bold"),
            ("   Rule ", "dim"), (problem.rule_type or "-", "bold"),
        )
    )
    console.print(Text.assemble(("Languages: ", "dim"), (", ".join(problem.languages), "")))

    for title, content in (
        ("Description", problem.description),
        ("Input", problem.input_description),
        ("Output", problem.output_description),
        ("Hint", problem.hint),
    ):
        if not content:
            continue
        console.print()
        console.rule(Text(title, style="bold cyan"), style="dim")
        console.print(html_to_text(content))

    for idx, sample in enumerate(problem.samples, 1):
        console.print()
        console.print(
            Panel(sample.input.rstrip("\n") or " ", title=Text(f"Sample {idx} Input"), border_style="dim")
        )
        console.print(
            Panel(sample.output.rstrip("\n") or " ", title=Text(f"Sample {idx} Output"), border_style="dim")
        )


def print_submission(detail: SubmissionDetail, *, include_cases: bool = True) -> None:
    console.print(Text.assemble(("Result: ", "bold"), verdict_text(detail.result)))
    stat = detail.statistic_info or {}
    parts: list[Text] = []
    if stat.get("time_cost") is not None:
        parts.append(Text.assemble(("time ", "dim"), (f"{stat['time_cost']} ms", "bold")))
    if stat.get("memory_cost") is not None:
        parts.append(Text.assemble(("memory ", "dim"), (f"{stat['memory_cost']} KB", "bold")))
    if stat.get("score") is not None:
        parts.append(Text.assemble(("score ", "dim"), (str(stat["score"]), "bold")))
    if parts:
        console.print(Text("   ").join(parts))
    if detail.result == -2 and stat.get("err_info"):
        console.print(Panel(stat["err_info"], title=Text("Compiler output"), border_style="cyan"))
    if not include_cases:
        return
    info = detail.info or {}
    cases = info.get("data")
    if isinstance(cases, list):
        for idx, case in enumerate(cases, 1):
            console.print(testcase_text(idx, case.get("result")))


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


def _kv_table(rows: list[tuple[str, str | Text]]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    for key, value in rows:
        table.add_row(key, value)
    return table


def print_user(user: User) -> None:
    rows: list[tuple[str, str | Text]] = [("Username", user.username)]
    if user.email:
        rows.append(("Email", user.email))
    if user.admin_type:
        rows.append(("Role", user.admin_type))
    console.print(_kv_table(rows))


def status_text(status: str | None) -> Text:
    label = CONTEST_STATUS.get(status or "", "-")
    return Text(label, style=_STATUS_STYLES.get(label))


def print_contests(contests: list[Contest]) -> None:
    table = Table(box=None, pad_edge=False)
    table.add_column("ID", justify="right", style="bold")
    table.add_column("Status")
    table.add_column("Start", style="dim")
    table.add_column("End", style="dim")
    table.add_column("Title")
    for c in contests:
        table.add_row(str(c.id), status_text(c.status), c.start_time or "-", c.end_time or "-", c.title)
    console.print(table)


def print_contest(c: Contest, description: str | None = None) -> None:
    console.print(Text(f"{c.id}: {c.title}", style="bold green"))
    console.print(
        _kv_table(
            [
                ("Status", status_text(c.status)),
                ("Rule", c.rule_type or "-"),
                ("Type", c.contest_type or "-"),
                ("Time", f"{c.start_time or '-'} ~ {c.end_time or '-'}"),
            ]
        )
    )
    if description:
        console.print(Panel(html_to_text(description), border_style="dim"))

def print_submissions(items: list[SubmissionListItem]) -> None:
    table = Table(box=None, pad_edge=False)
    table.add_column("ID", style="dim")
    table.add_column("Problem", style="bold")
    table.add_column("Result")
    table.add_column("Language")
    table.add_column("Time", justify="right")
    table.add_column("Created", style="dim")
    for m in items:
        stat = m.statistic_info or {}
        time_cost = f"{stat['time_cost']} ms" if stat.get("time_cost") is not None else "-"
        table.add_row(
            m.id, m.problem or "-", verdict_text(m.result), m.language or "-",
            time_cost, m.create_time or "-",
        )
    console.print(table)


_DIFFICULTY_STYLES = {"Low": "green", "Mid": "yellow", "High": "red"}


def difficulty_text(difficulty: str | None) -> Text:
    if not difficulty:
        return Text("-", style="dim")
    return Text(difficulty, style=_DIFFICULTY_STYLES.get(difficulty))


def print_problems(problems: list[Problem]) -> None:
    table = Table(box=None, pad_edge=False)
    table.add_column("ID", style="bold")
    table.add_column("Title")
    table.add_column("Difficulty")
    table.add_column("Tags", style="dim")
    table.add_column("Done", justify="center")
    for p in problems:
        solved = Text("AC", style="bold green") if p.my_status == 0 else Text("-", style="dim")
        table.add_row(
            p.display_id, p.title, difficulty_text(p.difficulty),
            ", ".join(p.tags) or "-", solved,
        )
    console.print(table)
