"""AgentArts 多角色事件校验。"""

from __future__ import annotations

import unittest

from app.agentarts import AgentArtsError, AgentArtsPlanner


class AgentArtsEventTests(unittest.TestCase):
    def test_accepts_three_roles(self):
        events = AgentArtsPlanner._validate_events(
            [
                {"type": "agent_speak", "round": 1, "agent": "证物官", "text": "9 项食材，1 项弃用"},
                {"type": "agent_speak", "round": 2, "agent": "主厨", "text": "做番茄炒蛋"},
                {"type": "agent_speak", "round": 3, "agent": "红队", "text": "用量没有超过库存"},
            ]
        )
        self.assertEqual([event["agent"] for event in events], ["证物官", "主厨", "红队"])

    def test_rejects_unknown_role_and_bad_round(self):
        with self.assertRaises(AgentArtsError):
            AgentArtsPlanner._validate_events(
                [{"type": "agent_speak", "round": 1, "agent": "采购员", "text": "买点肉"}]
            )
        with self.assertRaises(AgentArtsError):
            AgentArtsPlanner._validate_events(
                [{"type": "agent_speak", "round": 4, "agent": "主厨", "text": "做番茄炒蛋"}]
            )


if __name__ == "__main__":
    unittest.main()
