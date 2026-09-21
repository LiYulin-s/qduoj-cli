"""qduoj-cli command-line application."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import typer
from rich.prompt import Prompt
from rich.text import Text

from .api import OJAPIError, OJClient
from .config import clear_session, get_base_url, save_base_url
from .models import Contest, Problem, SubmissionListItem, is_final
from .render import (
    console,
    new_testcases,
    print_contest,
    print_contests,
    print_error,
    print_ok,
    print_problem,
    print_problems,
    print_submissions,
    print_user,
    print_warning,
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
        print_error(e.message)
        raise typer.Exit(1) from None


async def require_login(client: OJClient):
    profile = await client.get_profile()
    if profile is None:
        raise OJAPIError("not logged in; run: qduoj-cli login")
    return profile


async def with_contest_password(coro_factory, client: OJClient, contest_id: int):
    """Run coro_factory(); on a contest-password error, prompt, verify, retry once."""
    try:
        return await coro_factory()
    except OJAPIError as e:
        if CONTEST_PWD_ERROR not in e.message:
            raise
        password = Prompt.ask("Contest password", password=True)
        await client.verify_contest_password(contest_id, password)
        return await coro_factory()


async def get_problem_with_password(
    client: OJClient, display_id: str, contest_id: int | None
) -> Problem:
    """Fetch a problem; prompt for the contest password and retry once if needed."""
    if contest_id is None:
        return await client.get_problem(display_id)
    return await with_contest_password(
        lambda: client.get_contest_problem(contest_id, display_id), client, contest_id
    )


async def poll_submission(
    client: OJClient, submission_id: str, timeout: float = 300.0
) -> None:
    """Poll until judging finishes, streaming testcase results as they arrive."""
    deadline = asyncio.get_event_loop().time() + timeout
    printed = 0
    while True:
        detail = await client.get_submission(submission_id)
        for idx, result in new_testcases(detail, printed):
            console.print(testcase_text(idx, result))
            printed = idx
        if is_final(detail.result):
            print_submission(detail, include_cases=printed == 0)
            return
        if asyncio.get_event_loop().time() >= deadline:
            print_warning(
                f"judging not finished, current status: {verdict_text(detail.result).plain}; "
                f"run 'qduoj-cli status {submission_id} --wait' later"
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
    print_ok("Server is reachable")


@app.command()
def login() -> None:
    """Log in and save the session."""
    username = Prompt.ask("Username")
    password = Prompt.ask("Password", password=True)

    async def body(client: OJClient) -> None:
        try:
            await client.login(username, password)
        except OJAPIError as e:
            if e.message != "tfa_required":
                raise
            tfa_code = Prompt.ask("2FA code")
            await client.login(username, password, tfa_code=tfa_code)
        profile = await client.get_profile()
        if profile:
            console.print(
                Text.assemble(("Logged in as ", ""), (profile.user.username, "bold green"))
            )
        else:
            print_warning("login succeeded but failed to fetch profile")

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
        print_ok("Logged out")

    run(body)


@app.command()
def whoami() -> None:
    """Show the current logged-in user."""

    async def body(client: OJClient) -> None:
        profile = await client.get_profile()
        if profile is None:
            console.print(Text("Not logged in", style="dim"))
        else:
            print_user(profile.user)

    run(body)


@app.command()
def contests(
    page: int = typer.Option(1, "--page", help="Page number, 20 per page"),
) -> None:
    """List contests."""

    async def body(client: OJClient) -> None:
        items = await client.list_contests(page)
        if not items:
            console.print(Text("No contests", style="dim"))
            return
        print_contests(items)

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
            print_ok("Contest password accepted")
        data = await client.get_contest(contest_id)
        print_contest(Contest.model_validate(data), data.get("description"))

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
            console.print_json(
                json.dumps(p.model_dump(mode="json", exclude_none=True), ensure_ascii=False)
            )
        else:
            print_problem(p)

    run(body)

@app.command()
def problems(
    contest: int | None = typer.Option(None, "--contest", help="List this contest's problems"),
    page: int = typer.Option(1, "--page", help="Page number, 20 per page (public list)"),
    keyword: str | None = typer.Option(None, "--keyword", help="Search by title or ID (public list)"),
) -> None:
    """List problems: a contest's problem set (--contest) or public problems."""

    async def body(client: OJClient) -> None:
        if contest is not None:
            items = await with_contest_password(
                lambda: client.list_contest_problems(contest), client, contest
            )
        else:
            data = await client.list_problems(page, keyword)
            items = [Problem.model_validate(item) for item in data.get("results", [])]
        if not items:
            console.print(Text("No problems", style="dim"))
            return
        print_problems(items)

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
        console.print(Text(f"Submitting {p.display_id} ({lang}, {lines} lines)", style="dim"))

        submission_id = await client.submit(p.id, lang, code, contest)
        if submission_id is None:
            print_warning("submitted (this contest does not return a submission id)")
            return
        console.print(Text.assemble(("Submission ID: ", ""), (submission_id, "bold green")))
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
        items = [
            SubmissionListItem.model_validate(item)
            for item in await client.list_my_submissions(contest, limit)
        ]
        if not items:
            console.print(Text("No submissions", style="dim"))
            return
        print_submissions(items)

    run(body)
