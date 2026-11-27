"""契约骨架单测：字段约束、红队规则、状态机、事件别名。"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from contracts.agents import AgentUtterance, RedTeamOutput
from contracts.enums import (
    AgentRole,
    CaseState,
    ExpiryTier,
    ItemKind,
    ItemLocation,
    ItemState,
    VerdictStatus,
)
from contracts.events import InventoryChangeEvent
from contracts.items import EvidenceItem, EvidenceList
from contracts.verdict import PlanStep, Verdict
from orchestrator.state_machine import assert_transition, can_transition
from perception.pipeline import apply_confidence_gate


def make_item(**overrides) -> EvidenceItem:
    data = {
        "id": "i1",
        "name": "鸡蛋",
        "kind": ItemKind.RAW,
        "qty": 3,
        "unit": "个",
        "location": ItemLocation.FRIDGE,
        "expiry_tier": ExpiryTier.DAYS,
        "confidence": 0.9,
        "state": ItemState.USABLE,
    }
    data.update(overrides)
    return EvidenceItem(**data)


class ContractTests(unittest.TestCase):
    def test_item_rejects_non_positive_qty(self):
        with self.assertRaises(ValidationError):
            make_item(qty=0)

    def test_item_rejects_confidence_above_one(self):
        with self.assertRaises(ValidationError):
            make_item(confidence=1.2)

    def test_confidence_gate_marks_low_confidence_review(self):
        evidence = EvidenceList(
            items=[
                make_item(id="i1", confidence=0.4, state=ItemState.USABLE),
                make_item(id="i2", confidence=0.9, state=ItemState.USABLE),
            ]
        )
        apply_confidence_gate(evidence)
        self.assertEqual(evidence.items[0].state, ItemState.REVIEW)
        self.assertEqual(evidence.items[1].state, ItemState.USABLE)

    def test_redteam_reject_requires_fatal_and_change(self):
        with self.assertRaises(ValidationError):
            RedTeamOutput(
                failure_modes=[
                    {"where": "第 2 步", "what": "溢锅", "severity": 2, "evidence": "原文"}
                ],
                reject=True,
                required_change="分两次煎",
            )
        with self.assertRaises(ValidationError):
            RedTeamOutput(
                failure_modes=[
                    {"where": "第 2 步", "what": "溢锅", "severity": 3, "evidence": "原文"}
                ],
                reject=True,
            )
        output = RedTeamOutput(
            failure_modes=[
                {"where": "第 2 步", "what": "溢锅", "severity": 3, "evidence": "原文"}
            ],
            reject=True,
            required_change="分两次煎",
        )
        self.assertTrue(output.reject)

    def test_agent_cannot_object_to_self(self):
        with self.assertRaises(ValidationError):
            AgentUtterance(
                agent=AgentRole.CHEF,
                claim="做番茄炒蛋",
                objections=[{"target": AgentRole.CHEF, "reason": "自己否定自己"}],
                confidence=0.8,
            )

    def test_state_machine_transitions(self):
        self.assertTrue(can_transition(CaseState.INTAKE, CaseState.RECALL))
        self.assertFalse(can_transition(CaseState.INTAKE, CaseState.EXECUTE))
        self.assertTrue(can_transition(CaseState.EXECUTE, CaseState.RESCUE))
        self.assertTrue(can_transition(CaseState.RESCUE, CaseState.EXECUTE))
        self.assertTrue(can_transition(CaseState.RESCUE, CaseState.CLOSE))
        with self.assertRaises(ValueError):
            assert_transition(CaseState.CLOSE, CaseState.EXECUTE)

    def test_inventory_event_uses_from_alias(self):
        event = InventoryChangeEvent(item="豆腐", from_="半块", to="用完")
        dumped = event.model_dump(by_alias=True)
        self.assertEqual(dumped["from"], "半块")
        self.assertNotIn("from_", dumped)

    def test_ready_verdict_requires_steps(self):
        with self.assertRaises(ValidationError):
            Verdict(status=VerdictStatus.READY, title="番茄炒蛋", duration_min=12, servings=2)
        verdict = Verdict(
            status=VerdictStatus.READY,
            title="番茄炒蛋",
            duration_min=12,
            servings=2,
            steps=[PlanStep(n=1, title="备料", detail="打蛋", minutes=2)],
        )
        self.assertEqual(verdict.steps[0].n, 1)


if __name__ == "__main__":
    unittest.main()
