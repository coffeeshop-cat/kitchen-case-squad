"""会诊状态机。

INTAKE → RECALL → DELIBERATE(≤3) → VERDICT → EXECUTE → [RESCUE] → CLOSE
"""

from __future__ import annotations

from contracts.enums import CaseState

MAX_DELIBERATION_ROUNDS = 3
MAX_RESCUE_TIMES = 2

ALLOWED_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.INTAKE: {CaseState.RECALL},
    CaseState.RECALL: {CaseState.DELIBERATE},
    CaseState.DELIBERATE: {CaseState.DELIBERATE, CaseState.VERDICT},
    CaseState.VERDICT: {CaseState.EXECUTE},
    CaseState.EXECUTE: {CaseState.RESCUE, CaseState.CLOSE},
    CaseState.RESCUE: {CaseState.EXECUTE, CaseState.CLOSE},
    CaseState.CLOSE: set(),
}


def can_transition(source: CaseState, target: CaseState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(source, set())


def assert_transition(source: CaseState, target: CaseState) -> None:
    if not can_transition(source, target):
        raise ValueError(f"非法状态跳转：{source.value} → {target.value}")
