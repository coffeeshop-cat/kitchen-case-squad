"""SSE 事件契约。

约定：SSE 的 event 名即 type，data 为对应 payload。
`verdict` 事件的 payload 直接是 contracts.verdict.Verdict，不再套一层。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import AgentRole


class AgentSpeakEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["agent_speak"] = "agent_speak"
    agent: AgentRole
    text: str = Field(min_length=1)
    round: int = Field(ge=1, le=3)


class TimerFireEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["timer_fire"] = "timer_fire"
    text: str = Field(min_length=1)
    case_id: str | None = None
    at: str | None = None


class InventoryChangeEvent(BaseModel):
    """`from` 是 Python 关键字，代码里用 from_，序列化时 by_alias=True。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["inventory_change"] = "inventory_change"
    item: str = Field(min_length=1)
    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)


class CloseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["close"] = "close"
