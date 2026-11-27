"""四个核心数字的算法骨架。

指标定义见 docs/contracts.md 与开发方案 8.3；R4 负责：柳浩冉。
"""

from __future__ import annotations

from contracts.items import EvidenceItem
from contracts.verdict import CaseOutcome, Verdict


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def zero_purchase_rate(plans: list[Verdict]) -> float:
    """零采购率 = purchase_count == 0 的方案数 / 方案总数。R4 实现。"""
    raise NotImplementedError("R4：实现零采购率")


def empty_plate_rate(outcomes: list[CaseOutcome]) -> float:
    """空盘率 = empty_plate 为 true 的记录 / 总记录。R4 实现。"""
    raise NotImplementedError("R4：实现空盘率")


def promise_vs_actual(pairs: list[tuple[Verdict, CaseOutcome]]) -> dict:
    """承诺 vs 实际：返回平均值、最大偏差、超时次数。R4 实现。"""
    raise NotImplementedError("R4：实现承诺 vs 实际")


def overlap_rate(plans: list[Verdict], corpus: list[dict], threshold: float = 0.8) -> float:
    """重合率：必须带三把锁，见开发方案 8.3。R4 实现。"""
    raise NotImplementedError("R4：实现带三把锁的重合率")


def load_items(case_dir: str) -> list[EvidenceItem]:
    """读取某个案例的标注证物。R4 实现。"""
    raise NotImplementedError("R4：读取 ground_truth")
