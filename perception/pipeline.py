"""识别管线：多模态识别 → JSON → 位置/生熟/余量校验 → 置信度阈值。

R2 负责：卢妙音。契约见 docs/contracts.md 第 2 节。
"""

from __future__ import annotations

from contracts.enums import ItemState
from contracts.items import EvidenceList

CONFIDENCE_THRESHOLD = 0.7


def recognize(photo: bytes, content_type: str) -> EvidenceList:
    """把一张厨房照片转成证物清单。

    R2 实现：调用多模态模型，输出必须通过 EvidenceList 校验；
    识别不准没关系，低置信度项由 apply_confidence_gate 标成 review。
    """
    raise NotImplementedError("R2：接入多模态识别，返回 EvidenceList")


def apply_confidence_gate(
    evidence: EvidenceList, threshold: float = CONFIDENCE_THRESHOLD
) -> EvidenceList:
    """置信度低于阈值的证物一律回到 review，等待人工确认。"""
    for item in evidence.items:
        if item.confidence < threshold:
            item.state = ItemState.REVIEW
    return evidence
