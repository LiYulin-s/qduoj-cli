"""Config and login session persistence."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

import typer

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "qduoj-cli"
CONFIG_FILE = CONFIG_DIR / "config.toml"
SESSION_FILE = CONFIG_DIR / "session.json"


def get_base_url(cli_url: str | None) -> str:
    """Resolve the server URL: CLI arg > QDUOJ_BASE_URL env > config.toml."""
    url = cli_url or os.environ.get("QDUOJ_BASE_URL")
    if not url:
        try:
            with open(CONFIG_FILE, "rb") as f:
                url = tomllib.load(f).get("base_url")
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            url = None
    if not url:
        raise typer.BadParameter(
            "no server URL configured; run: qduoj-cli config <BASE_URL>"
        )
    return url.rstrip("/")


def save_base_url(url: str) -> None:
    # Python's stdlib has no TOML writer, so emit the single-key file by hand.
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(f'base_url = "{url.rstrip("/")}"\n', encoding="utf-8")


def load_cookies() -> dict[str, str]:
    try:
        return {str(k): str(v) for k, v in json.loads(SESSION_FILE.read_text("utf-8")).items()}
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {}


def save_cookies(cookies: dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.write_text(json.dumps(cookies), encoding="utf-8")


def clear_session() -> None:
    SESSION_FILE.unlink(missing_ok=True)
