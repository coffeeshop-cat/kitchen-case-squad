"""识别管线：多模态识别 → JSON → 位置/生熟/余量校验 → 置信度阈值。

R2 负责：卢妙音。契约见 docs/contracts.md 第 2 节。
"""

from __future__ import annotations

from typing import Any, Callable

from contracts.enums import ItemState
from contracts.items import EvidenceList

from .normalize import normalize_model_output

CONFIDENCE_THRESHOLD = 0.7

# 任意多模态实现都只需要满足这个签名：照片字节 + MIME → 模型原始 JSON。
Recognizer = Callable[[bytes, str], Any]


class PerceptionUnavailable(RuntimeError):
    """没有配置识别器；调用方应提示用户手填或切换模型。"""


def recognize(
    photo: bytes,
    content_type: str,
    recognizer: Recognizer | None = None,
) -> EvidenceList:
    """把一张厨房照片转成证物清单。

    识别器由外部注入（AgentArts / ModelArts / 任意 OpenAI 兼容视觉接口），
    本函数只负责把模型输出收口成契约并做置信度门控。
    """
    if recognizer is None:
        raise PerceptionUnavailable(
            "未配置多模态识别器：请注入 recognizer，或先使用人工清单"
        )
    raw = recognizer(photo, content_type)
    evidence = normalize_model_output(raw)
    return apply_confidence_gate(evidence)


def apply_confidence_gate(
    evidence: EvidenceList, threshold: float = CONFIDENCE_THRESHOLD
) -> EvidenceList:
    """高置信度直接可用，低置信度回到 review；食安判死不受影响。"""
    for item in evidence.items:
        if item.state == ItemState.DISCARD:
            continue
        item.state = ItemState.USABLE if item.confidence >= threshold else ItemState.REVIEW
    return evidence
