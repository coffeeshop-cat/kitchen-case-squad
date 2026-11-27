"""会诊主持人：并发对辩、聚合冲突、三轮收敛、裁决带 tradeoff。

R2/R3 负责：刘彬彬。
"""

from __future__ import annotations

from contracts.enums import AgentRole, CaseState
from contracts.items import EvidenceList
from contracts.verdict import Constraints, Verdict

from .state_machine import MAX_DELIBERATION_ROUNDS


def recall_cases(evidence: EvidenceList, constraints: Constraints, limit: int = 3) -> list[dict]:
    """按 Jaccard + 器具 + 时长检索判例，取 score ≥0.5 的 top-3。R3 实现。"""
    raise NotImplementedError("R3：实现判例检索，见 docs/contracts.md 第 9 节")


def deliberate(
    evidence: EvidenceList,
    constraints: Constraints,
    cases: list[dict] | None = None,
    max_rounds: int = MAX_DELIBERATION_ROUNDS,
) -> Verdict:
    """跑五角色会诊并收敛成剧本。R2 先返回假数据，R3 接真主持人。"""
    raise NotImplementedError("R2：五角色并发对辩；R3：接判例与裁决")


def run_case(evidence: EvidenceList, constraints: Constraints) -> Verdict:
    """完整会审：INTAKE → RECALL → DELIBERATE → VERDICT。R3 实现。"""
    raise NotImplementedError("R3：串起 recall_cases 与 deliberate")


def next_state(current: CaseState, action: str) -> CaseState:
    """把用户/系统动作映射到下一状态。R2 实现。"""
    raise NotImplementedError("R2：实现动作到状态的映射")
