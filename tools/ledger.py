"""ledger Skill：按静态价表算“这顿省了多少钱”。

R3 负责：卢妙音。价格表 data/price_static.csv，真实 MCP 属 P2。
"""

from __future__ import annotations

from contracts.verdict import UsedItem


def saved_yuan(used_items: list[UsedItem], price_table: str = "static_v1") -> dict:
    """返回 {"saved_yuan": 12.4, "detail": [...]}。R3 实现。"""
    raise NotImplementedError("R3：实现账本，静态价表即可")
