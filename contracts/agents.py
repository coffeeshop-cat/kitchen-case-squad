"""智能体输出契约（R2 冻结）。

五个角色 + 主持人共用 AgentUtterance；红队单独用 RedTeamOutput。
对应 docs/contracts.md 第 4、5 节。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import AgentRole


class UseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1)
    amount: str = Field(min_length=1)


class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: AgentRole
    reason: str = Field(min_length=1)


class AgentUtterance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: AgentRole
    claim: str = Field(min_length=1)
    uses: list[UseItem] = Field(default_factory=list)
    objections: list[Objection] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    needs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _objection_target_not_self(self) -> "AgentUtterance":
        for objection in self.objections:
            if objection.target == self.agent:
                raise ValueError("objections 不能指向自己")
        return self


class FailureMode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str = Field(min_length=1)
    what: str = Field(min_length=1)
    severity: int = Field(ge=1, le=3)
    evidence: str = Field(min_length=1)


class RedTeamOutput(BaseModel):
    """红队输出：只报能指到方案原文的问题，一案只驳一次。"""

    model_config = ConfigDict(extra="forbid")

    failure_modes: list[FailureMode] = Field(min_length=1)
    reject: bool = False
    required_change: str | None = None

    @model_validator(mode="after")
    def _reject_requires_fatal_and_change(self) -> "RedTeamOutput":
        if not self.reject:
            return self
        if not (self.required_change or "").strip():
            raise ValueError("reject=true 时必须给出 required_change")
        if not any(mode.severity == 3 for mode in self.failure_modes):
            raise ValueError("reject=true 时至少需要一条 severity=3 的致命问题")
        return self
