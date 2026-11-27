"""按角色调用模型，输出必须通过 contracts 中的 schema。

R2 负责：刘彬彬。提示词见 prompts/{role}.v{n}.md。
"""

from __future__ import annotations

from contracts.agents import AgentUtterance, RedTeamOutput
from contracts.enums import AgentRole
from contracts.items import EvidenceList
from contracts.verdict import Constraints, Verdict


def run_role(
    role: AgentRole,
    evidence: EvidenceList,
    constraints: Constraints,
    context: dict | None = None,
) -> AgentUtterance:
    """运行单个角色，返回结构化发言。R2 实现。"""
    raise NotImplementedError("R2：接 llm_gateway，按角色加载 prompts/{role}.v{n}.md")


def run_redteam(
    verdict: Verdict,
    evidence: EvidenceList,
    constraints: Constraints,
) -> RedTeamOutput:
    """红队独立入口：只找破绽，一案最多驳回一次。R2 实现。"""
    raise NotImplementedError("R2：实现红队，验收标准是真破绽率 ≥60%")
