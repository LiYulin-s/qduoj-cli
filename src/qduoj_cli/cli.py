"""qduoj-cli command-line application."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import typer

from .api import OJAPIError, OJClient
from .config import clear_session, get_base_url, save_base_url
from .models import Contest, Problem, SubmissionListItem, is_final
from .render import (
    html_to_text,
    new_testcases,
    print_problem,
    print_submission,
    testcase_text,
    verdict_text,
)

app = typer.Typer(
    name="qduoj-cli",
    help="Command-line client for QingdaoU OnlineJudge.",
    no_args_is_help=True,
)

_state = SimpleNamespace(base_url=None)

CONTEST_PWD_ERROR = "Wrong password or password expired"
CONTEST_STATUS = {"1": "Not started", "0": "Running", "-1": "Ended"}
LANG_BY_EXT = {
    ".c": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".java": "Java",
    ".py": "Python3",
    ".go": "Golang",
}


def _version_cb(value: bool) -> None:
    if value:
        try:
            from importlib.metadata import version

            v = version("qduoj-cli")
        except Exception:
            v = "0.1.0"
        typer.echo(f"qduoj-cli {v}")
        raise typer.Exit()


@app.callback()
def main_callback(
    base_url: str | None = typer.Option(
        None, "--base-url", help="Server URL (one-shot override of the config)"
    ),
    version: bool = typer.Option(
        False, "--version", callback=_version_cb, is_eager=True, help="Show version"
    ),
) -> None:
    _state.base_url = base_url


def run(make_coro) -> None:
    """Run an async command body with an OJClient.

    OJAPIError is reported in red on stderr with exit code 1.
    """
    base_url = get_base_url(_state.base_url)

    async def _inner() -> None:
        async with OJClient(base_url) as client:
            await make_coro(client)

    try:
        asyncio.run(_inner())
    except OJAPIError as e:
        typer.secho(f"Error: {e.message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from None


async def require_login(client: OJClient):
    profile = await client.get_profile()
    if profile is None:
        raise OJAPIError("not logged in; run: qduoj-cli login")
    return profile


async def get_problem_with_password(
    client: OJClient, display_id: str, contest_id: int | None
) -> Problem:
    """Fetch a problem; prompt for the contest password and retry once if needed."""
    try:
        if contest_id is None:
            return await client.get_problem(display_id)
        return await client.get_contest_problem(contest_id, display_id)
    except OJAPIError as e:
        if contest_id is not None and CONTEST_PWD_ERROR in e.message:
            password = typer.prompt("Contest password", hide_input=True)
            await client.verify_contest_password(contest_id, password)
            return await client.get_contest_problem(contest_id, display_id)
        raise


async def poll_submission(
    client: OJClient, submission_id: str, timeout: float = 300.0
) -> None:
    """Poll until judging finishes, streaming testcase results as they arrive."""
    deadline = asyncio.get_event_loop().time() + timeout
    printed = 0
    while True:
        detail = await client.get_submission(submission_id)
        for idx, result in new_testcases(detail, printed):
            typer.echo(testcase_text(idx, result))
            printed = idx
        if is_final(detail.result):
            print_submission(detail, include_cases=printed == 0)
            return
        if asyncio.get_event_loop().time() >= deadline:
            typer.secho(
                f"Judging not finished, current status: {verdict_text(detail.result)}; "
                f"run 'qduoj-cli status {submission_id} --wait' later",
                fg=typer.colors.YELLOW,
                err=True,
            )
            raise typer.Exit(1)
        await asyncio.sleep(2)


# ---- commands ----


@app.command()
def config(
    base_url: str = typer.Argument(..., help="OJ server URL, e.g. https://oj.example.com"),
) -> None:
    """Save the server URL and check reachability."""
    save_base_url(base_url)
    _state.base_url = None  # force reading the just-saved config

    async def body(client: OJClient) -> None:
        await client.get_profile()

    run(body)
    typer.secho("Server is reachable", fg=typer.colors.GREEN)


@app.command()
def login() -> None:
    """Log in and save the session."""
    username = typer.prompt("Username")
    password = typer.prompt("Password", hide_input=True)

    async def body(client: OJClient) -> None:
        try:
            await client.login(username, password)
        except OJAPIError as e:
            if e.message != "tfa_required":
                raise
            tfa_code = typer.prompt("2FA code")
            await client.login(username, password, tfa_code=tfa_code)
        profile = await client.get_profile()
        if profile:
            typer.secho(f"Logged in as: {profile.user.username}", fg=typer.colors.GREEN)
        else:
            typer.secho("Login succeeded but failed to fetch profile", fg=typer.colors.YELLOW)

    run(body)


@app.command()
def logout() -> None:
    """Log out and clear the local session."""

    async def body(client: OJClient) -> None:
        try:
            await client.logout()
        except OJAPIError:
            clear_session()
            raise
        typer.secho("Logged out", fg=typer.colors.GREEN)

    run(body)


@app.command()
def whoami() -> None:
    """Show the current logged-in user."""

    async def body(client: OJClient) -> None:
        profile = await client.get_profile()
        if profile is None:
            typer.echo("Not logged in")
            return
        user = profile.user
        typer.echo(f"Username: {user.username}")
        if user.email:
            typer.echo(f"Email: {user.email}")
        if user.admin_type:
            typer.echo(f"Role: {user.admin_type}")

    run(body)


@app.command()
def contests(
    page: int = typer.Option(1, "--page", help="Page number, 20 per page"),
) -> None:
    """List contests."""

    async def body(client: OJClient) -> None:
        items = await client.list_contests(page)
        if not items:
            typer.echo("No contests")
            return
        for c in items:
            status = CONTEST_STATUS.get(c.status or "", "-")
            typer.echo(
                f"{c.id:>6}  {status}  {c.start_time or '-'} ~ {c.end_time or '-'}  {c.title}"
            )

    run(body)


@app.command()
def contest(
    contest_id: int = typer.Argument(..., help="Contest ID"),
    password: str | None = typer.Option(
        None, "--password", help="Access password for password-protected contests"
    ),
) -> None:
    """Show contest details, or unlock it with --password."""

    async def body(client: OJClient) -> None:
        if password:
            await client.verify_contest_password(contest_id, password)
            typer.secho("Contest password accepted", fg=typer.colors.GREEN)
        data = await client.get_contest(contest_id)
        c = Contest.model_validate(data)
        typer.secho(f"{c.id}: {c.title}", fg=typer.colors.GREEN, bold=True)
        typer.echo(
            f"Status: {CONTEST_STATUS.get(c.status or '', '-')}  "
            f"Rule: {c.rule_type or '-'}  Type: {c.contest_type or '-'}"
        )
        typer.echo(f"Time: {c.start_time or '-'} ~ {c.end_time or '-'}")
        if data.get("description"):
            typer.echo()
            typer.echo(html_to_text(data["description"]))

    run(body)


@app.command()
def problem(
    problem_id: str = typer.Argument(..., help="Problem display ID"),
    contest: int | None = typer.Option(None, "--contest", help="Contest ID"),
    json_out: bool = typer.Option(False, "--json", help="Output raw JSON"),
) -> None:
    """Show a problem (description and samples)."""

    async def body(client: OJClient) -> None:
        p = await get_problem_with_password(client, problem_id, contest)
        if json_out:
            typer.echo(
                json.dumps(p.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2)
            )
        else:
            print_problem(p)

    run(body)


@app.command()
def submit(
    problem_id: str = typer.Argument(..., help="Problem display ID"),
    file: Path = typer.Argument(..., help="Source file"),
    contest: int | None = typer.Option(None, "--contest", help="Contest ID"),
    language: str | None = typer.Option(None, "--language", help="Language, e.g. C / C++ / Python3"),
    no_wait: bool = typer.Option(False, "--no-wait", help="Do not wait for the judge result"),
) -> None:
    """Submit code and wait for the judge result."""

    async def body(client: OJClient) -> None:
        await require_login(client)
        p = await get_problem_with_password(client, problem_id, contest)

        lang = language or LANG_BY_EXT.get(file.suffix.lower())
        if lang is None:
            raise OJAPIError(
                f"cannot infer language from extension '{file.suffix or '(none)'}'; specify --language"
            )
        if p.languages and lang not in p.languages:
            raise OJAPIError(f"{lang} is not allowed for this problem; allowed: {', '.join(p.languages)}")

        try:
            code = file.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise OJAPIError(f"file not found: {file}") from None
        except UnicodeDecodeError as e:
            raise OJAPIError(f"file is not valid UTF-8 text: {file} ({e})") from None
        if not code.strip():
            raise OJAPIError(f"file is empty: {file}")

        lines = code.count("\n") + (0 if code.endswith("\n") else 1)
        typer.echo(f"Submitting {p.display_id} ({lang}, {lines} lines)")

        submission_id = await client.submit(p.id, lang, code, contest)
        if submission_id is None:
            typer.secho("Submitted (this contest does not return a submission id)", fg=typer.colors.YELLOW)
            return
        typer.secho(f"Submission ID: {submission_id}", fg=typer.colors.GREEN, bold=True)
        if not no_wait:
            await poll_submission(client, submission_id)

    run(body)


@app.command()
def status(
    submission_id: str = typer.Argument(..., help="Submission ID"),
    wait: bool = typer.Option(False, "--wait", help="Poll until judging finishes"),
) -> None:
    """Show the judge result of a submission."""

    async def body(client: OJClient) -> None:
        await require_login(client)
        if wait:
            await poll_submission(client, submission_id)
        else:
            print_submission(await client.get_submission(submission_id))

    run(body)


@app.command()
def submissions(
    contest: int | None = typer.Option(None, "--contest", help="Contest ID"),
    limit: int = typer.Option(20, "--limit", help="Maximum number of entries"),
) -> None:
    """List my submissions."""

    async def body(client: OJClient) -> None:
        await require_login(client)
        items = await client.list_my_submissions(contest, limit)
        if not items:
            typer.echo("No submissions")
            return
        for item in items:
            m = SubmissionListItem.model_validate(item)
            time_cost = m.statistic_info.get("time_cost", "-")
            typer.echo(
                f"{m.id}  {m.problem or '-'}  {verdict_text(m.result)}  "
                f"{m.language or '-'}  {time_cost} ms  {m.create_time or '-'}"
            )

    run(body)
