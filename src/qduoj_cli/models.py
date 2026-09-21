"""OnlineJudge API response models and judge status codes."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class APIEnvelope(BaseModel, Generic[T]):
    error: str | None = None
    data: T | None = None


class User(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    username: str
    email: str | None = None
    admin_type: str | None = None


class Profile(BaseModel):
    model_config = ConfigDict(extra="allow")

    user: User
    real_name: str | None = None


class Sample(BaseModel):
    model_config = ConfigDict(extra="allow")

    input: str = ""
    output: str = ""


class Problem(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int
    # The API field is "_id" (display id); pydantic forbids leading-underscore
    # field names, hence the alias.
    display_id: str = Field(alias="_id")
    title: str = ""
    description: str = ""
    input_description: str = ""
    output_description: str = ""
    samples: list[Sample] = []
    hint: str = ""
    time_limit: int = 0  # ms
    memory_limit: int = 0  # MB
    languages: list[str] = []
    template: dict[str, str] = {}
    rule_type: str | None = None
    tags: list[str] = []
    difficulty: str | None = None
    source: str | None = None


class Contest(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    title: str = ""
    status: str | None = None  # "1" not started, "0" running, "-1" ended
    rule_type: str | None = None
    contest_type: str | None = None
    start_time: str | None = None
    end_time: str | None = None


class SubmissionDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    result: int
    statistic_info: dict = {}
    info: dict | None = None
    language: str | None = None
    create_time: str | None = None
    code: str | None = None


class SubmissionListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    problem: str | None = None
    result: int
    language: str | None = None
    create_time: str | None = None
    statistic_info: dict = {}


# JudgeStatus values as defined in submission/models.py of QingdaoU/OnlineJudge.
RESULT_NAMES: dict[int, tuple[str, str]] = {
    -2: ("CE", "Compile Error"),
    -1: ("WA", "Wrong Answer"),
    0: ("AC", "Accepted"),
    1: ("TLE", "CPU Time Limit Exceeded"),
    2: ("TLE", "Time Limit Exceeded"),
    3: ("MLE", "Memory Limit Exceeded"),
    4: ("RE", "Runtime Error"),
    5: ("SE", "System Error"),
    6: ("Pending", "Pending"),
    7: ("Judging", "Judging"),
    8: ("PA", "Partially Accepted"),
}


def verdict_name(result: int) -> str:
    abbr, _desc = RESULT_NAMES.get(result, ("?", f"Unknown status {result}"))
    return abbr


def is_final(result: int) -> bool:
    return result not in (6, 7)
