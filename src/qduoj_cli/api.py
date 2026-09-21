"""OnlineJudge REST API client: envelope parsing, CSRF, session cookie persistence."""

from __future__ import annotations

from typing import Any

import aiohttp
from yarl import URL

from . import config
from .models import Contest, Problem, Profile, SubmissionDetail

CSRF_COOKIE = "csrftoken"


class OJAPIError(Exception):
    """Non-empty error envelope from the server, or a network-level failure."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class OJClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._origin = URL(self.base_url)
        self._session: aiohttp.ClientSession | None = None
        self._jar: aiohttp.CookieJar | None = None

    async def __aenter__(self) -> "OJClient":
        # unsafe=True keeps cookies for http:// and bare-IP deployments.
        self._jar = aiohttp.CookieJar(unsafe=True)
        self._session = aiohttp.ClientSession(
            base_url=self._origin, cookie_jar=self._jar
        )
        self._jar.update_cookies(config.load_cookies(), response_url=self._origin)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._session:
            await self._session.close()

    # ---- internals ----

    def _csrf_token(self) -> str | None:
        assert self._jar is not None
        morsel = self._jar.filter_cookies(self._origin).get(CSRF_COOKIE)
        return morsel.value if morsel else None

    def _persist_cookies(self) -> None:
        assert self._jar is not None
        cookies = {
            name: morsel.value
            for name, morsel in self._jar.filter_cookies(self._origin).items()
        }
        if cookies:
            config.save_cookies(cookies)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        """Issue an API request and return the envelope's data field.

        Raises OJAPIError when the envelope carries an error, when the
        response is not JSON, or when the connection fails.
        """
        assert self._session is not None
        headers = {}
        if method == "POST":
            token = self._csrf_token()
            if token is None:
                # GET /api/profile is decorated with ensure_csrf_cookie and
                # therefore seeds the csrftoken cookie.
                await self._request("GET", "/profile")
                token = self._csrf_token()
            if token is None:
                raise OJAPIError(
                    "server did not set a csrftoken cookie; "
                    "the deployment may use custom cookie names"
                )
            headers["X-CSRFToken"] = token
        try:
            async with self._session.request(
                method,
                f"/api{path}",
                json=json_body,
                params=params,
                headers=headers,
            ) as resp:
                self._persist_cookies()
                try:
                    payload = await resp.json()
                except (aiohttp.ContentTypeError, ValueError):
                    body = (await resp.text())[:200]
                    raise OJAPIError(
                        f"non-JSON response from server (HTTP {resp.status}): {body!r}"
                    ) from None
        except aiohttp.ClientConnectionError as e:
            raise OJAPIError(f"cannot connect to {self.base_url}: {e}") from e

        if payload.get("error") is None:
            return payload.get("data")
        msg = payload["data"]
        raise OJAPIError(msg if isinstance(msg, str) else str(payload["error"]))

    # ---- account ----

    async def login(self, username: str, password: str, tfa_code: str | None = None) -> None:
        """Log in.

        If the account has 2FA enabled, the server replies error=tfa_required;
        the caller should prompt for a code and retry with tfa_code.
        """
        body: dict[str, str] = {"username": username, "password": password}
        if tfa_code:
            body["tfa_code"] = tfa_code
        await self._request("POST", "/login", json_body=body)
        self._persist_cookies()

    async def logout(self) -> None:
        await self._request("GET", "/logout")
        config.clear_session()

    async def get_profile(self) -> Profile | None:
        """Return the logged-in user's profile, or None when anonymous."""
        data = await self._request("GET", "/profile")
        if not data:
            return None
        return Profile.model_validate(data)

    # ---- problems ----

    async def get_problem(self, display_id: str) -> Problem:
        data = await self._request(
            "GET", "/problem", params={"problem_id": display_id}
        )
        return Problem.model_validate(data)

    async def list_problems(self, page: int = 1, keyword: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": 20, "offset": (page - 1) * 20}
        if keyword:
            params["keyword"] = keyword
        return await self._request("GET", "/problem", params=params)

    async def get_contest_problem(self, contest_id: int, display_id: str) -> Problem:
        data = await self._request(
            "GET",
            "/contest/problem",
            params={"contest_id": contest_id, "problem_id": display_id},
        )
        return Problem.model_validate(data)

    async def list_contest_problems(self, contest_id: int) -> list[Problem]:
        """List all problems of a contest (requires contest access)."""
        data = await self._request(
            "GET", "/contest/problem", params={"contest_id": contest_id}
        )
        return [Problem.model_validate(item) for item in data]

    # ---- contests ----

    async def list_contests(self, page: int = 1) -> list[Contest]:
        data = await self._request(
            "GET", "/contests", params={"limit": 20, "offset": (page - 1) * 20}
        )
        return [Contest.model_validate(item) for item in data.get("results", [])]

    async def get_contest(self, contest_id: int) -> dict:
        return await self._request("GET", "/contest", params={"id": contest_id})

    async def verify_contest_password(self, contest_id: int, password: str) -> None:
        await self._request(
            "POST",
            "/contest/password",
            json_body={"contest_id": contest_id, "password": password},
        )

    # ---- submissions ----

    async def submit(
        self,
        problem_id: int,
        language: str,
        code: str,
        contest_id: int | None = None,
    ) -> str | None:
        """Submit code and return the submission id.

        Returns None when the contest hides submission ids (empty data).
        """
        body: dict[str, Any] = {
            "problem_id": problem_id,
            "language": language,
            "code": code,
        }
        if contest_id is not None:
            body["contest_id"] = contest_id
        data = await self._request("POST", "/submission", json_body=body)
        if not data:
            return None
        return data["submission_id"]

    async def get_submission(self, submission_id: str) -> SubmissionDetail:
        data = await self._request(
            "GET", "/submission", params={"id": submission_id}
        )
        return SubmissionDetail.model_validate(data)

    async def list_my_submissions(
        self, contest_id: int | None = None, limit: int = 20
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": limit, "myself": "1"}
        path = "/submissions"
        if contest_id is not None:
            params["contest_id"] = contest_id
            path = "/contest_submissions"
        data = await self._request("GET", path, params=params)
        return data.get("results", [])
