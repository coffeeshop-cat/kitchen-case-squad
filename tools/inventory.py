"""inventory Skill：库存扣减、弃用、补充、临期查询。

R3 负责：卢妙音。契约见 docs/contracts.md 第 2、8 节。
"""

from __future__ import annotations

from contracts.agents import UseItem
from contracts.items import EvidenceItem


def consume(items: list[EvidenceItem], uses: list[UseItem]) -> list[EvidenceItem]:
    """按 uses 扣减库存；扣完标 consumed。R3 实现。"""
    raise NotImplementedError("R3：实现库存扣减")


def discard(items: list[EvidenceItem], item_id: str, reason: str) -> list[EvidenceItem]:
    """弃用一件食材，记 reason。R3 实现。"""
    raise NotImplementedError("R3：实现弃用")


def upsert(items: list[EvidenceItem], item: EvidenceItem) -> list[EvidenceItem]:
    """新增或更新一件食材。R3 实现。"""
    raise NotImplementedError("R3：实现 upsert")


def expiring(items: list[EvidenceItem], within_days: int = 2) -> list[EvidenceItem]:
    """返回 within_days 天内到期的食材，只算小时级/天级。R3 实现。"""
    raise NotImplementedError("R3：实现临期查询")
