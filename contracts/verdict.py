"""剧本、约束、执行记录与判例契约。

对应 docs/contracts.md 第 3、6、8、9 节。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import VerdictStatus
from .items import EvidenceItem


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    people: int = Field(ge=1)
    minutes: int = Field(gt=0)
    gear: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    must_use: list[str] = Field(default_factory=list)


class UsedItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    qty: float = Field(gt=0)
    unit: str = Field(min_length=1)


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=1)
    title: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    minutes: float = Field(gt=0)
    heat: str | None = None


class TimetableEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str = Field(min_length=1)  # HH:MM
    action: str = Field(min_length=1)
    step_n: int = Field(ge=1)


class Warning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: str | None = None
    message: str = Field(min_length=1)
    severity: int = Field(ge=1, le=3)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VerdictStatus
    title: str = Field(min_length=1)
    duration_min: float | None = Field(default=None, gt=0)
    servings: int | None = Field(default=None, ge=1)
    purchase_count: int = Field(default=0, ge=0)
    used_items: list[UsedItem] = Field(default_factory=list)
    steps: list[PlanStep] = Field(default_factory=list)
    timetable: list[TimetableEntry] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    tradeoff: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _ready_must_be_executable(self) -> "Verdict":
        if self.status == VerdictStatus.READY:
            if not self.steps:
                raise ValueError("status=ready 时 steps 不能为空")
            if self.duration_min is None or self.servings is None:
                raise ValueError("status=ready 时必须给出 duration_min 与 servings")
        return self


class CaseOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    empty_plate: bool
    actual_minutes: float | None = Field(default=None, gt=0)
    failures: list[str] = Field(default_factory=list)
    rescued: bool = False
    human_verified: bool = False


class RunStep(BaseModel):
    """runs 表：第三幕急救只读这张表。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    step_index: int = Field(ge=1)
    action: str = Field(min_length=1)
    done_at: str | None = None
    ingredients: list[dict] = Field(default_factory=list)
    heat: str | None = None
    note: str | None = None


class CaseLaw(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    household_id: str | None = None
    created_at: str = Field(min_length=1)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    constraints: Constraints
    verdict: Verdict
    outcome: CaseOutcome
    reuse_count: int = Field(default=0, ge=0)
    success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
