"""三条线共用的数据与事件契约。

文档：docs/contracts.md
版本：v0.1-r1
"""

from .agents import AgentUtterance, FailureMode, Objection, RedTeamOutput, UseItem
from .enums import (
    EXPIRY_TIER_LABELS,
    KIND_LABELS,
    LOCATION_LABELS,
    ROLE_LABELS,
    AgentRole,
    CaseState,
    ExpiryTier,
    InventoryStatus,
    ItemKind,
    ItemLocation,
    ItemState,
    VerdictStatus,
)
from .events import (
    AgentSpeakEvent,
    CloseEvent,
    InventoryChangeEvent,
    TimerFireEvent,
)
from .items import EvidenceItem, EvidenceList
from .verdict import (
    CaseLaw,
    CaseOutcome,
    Constraints,
    PlanStep,
    RunStep,
    TimetableEntry,
    UsedItem,
    Verdict,
    Warning,
)

__all__ = [
    "AgentRole",
    "AgentSpeakEvent",
    "AgentUtterance",
    "CaseLaw",
    "CaseOutcome",
    "CaseState",
    "CloseEvent",
    "Constraints",
    "EvidenceItem",
    "EvidenceList",
    "ExpiryTier",
    "InventoryChangeEvent",
    "InventoryStatus",
    "ItemKind",
    "ItemLocation",
    "ItemState",
    "FailureMode",
    "Objection",
    "PlanStep",
    "RedTeamOutput",
    "RunStep",
    "TimerFireEvent",
    "TimetableEntry",
    "UsedItem",
    "UseItem",
    "Verdict",
    "VerdictStatus",
    "Warning",
    "ROLE_LABELS",
    "KIND_LABELS",
    "LOCATION_LABELS",
    "EXPIRY_TIER_LABELS",
]
