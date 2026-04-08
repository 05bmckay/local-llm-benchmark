from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RubricItem(BaseModel):
    weight: int = Field(ge=1, le=10)
    criterion: str


class Task(BaseModel):
    id: str
    category: str
    difficulty: int = Field(ge=1, le=5)
    tags: list[str] = []
    timeout_s: int = 180
    system: str | None = None
    prompt: str
    rubric: list[RubricItem]
    reference_solution: str | None = None
    pairwise_eligible: bool = True


class RunResult(BaseModel):
    sweep_id: str
    model: str
    task_id: str
    response: str
    ttft_ms: float | None
    duration_ms: float
    tokens_out: int
    tokens_per_sec: float
    peak_rss_mb: float | None
    error: str | None = None


class JudgeCriterion(BaseModel):
    name: str
    pass_: bool = Field(alias="pass")
    note: str = ""

    class Config:
        populate_by_name = True


class JudgeScore(BaseModel):
    score: int = Field(ge=1, le=5)
    criteria: list[JudgeCriterion] = []
    reasoning: str = ""


class PairwiseVerdict(BaseModel):
    winner: Literal["A", "B", "tie"]
    reasoning: str = ""
