"""证物清单契约（R1 冻结）。

对应 items 表与 docs/contracts.md 第 2 节。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .enums import ExpiryTier, ItemKind, ItemLocation, ItemState


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str | None = None
    kind: ItemKind
    qty: float = Field(gt=0)
    unit: str = Field(min_length=1)
    location: ItemLocation
    shelf: str | None = None
    purchased_at: str | None = None
    opened_at: str | None = None
    expiry_est: str | None = None
    expiry_tier: ExpiryTier
    expiry_src: Literal["auto", "user", "rule"] = "auto"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    state: ItemState = ItemState.REVIEW
    last_seen_at: str | None = None


class EvidenceList(BaseModel):
    """一次识别/录入的完整证物清单。"""

    model_config = ConfigDict(extra="forbid")

    case_id: str | None = None
    source: Literal["photo", "manual", "sample"] = "photo"
    items: list[EvidenceItem]
    notes: list[str] = Field(default_factory=list)
