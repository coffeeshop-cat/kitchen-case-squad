"""把多模态模型的自由 JSON 归一化成 EvidenceList。

这是感知层最容易被模型输出“污染”的一步，因此所有字段都在这里收口：
中文别名、数量单位、位置/生熟枚举、保质期推算、置信度阈值、重复项合并。
"""

from __future__ import annotations

import datetime as dt
import math
import re
from typing import Any

from contracts.enums import ExpiryTier, ItemKind, ItemLocation, ItemState
from contracts.items import EvidenceItem, EvidenceList

from .shelf_life import estimate_expiry, load_rules

MAX_ITEMS = 40

NAME_ALIASES = {
    "西红柿": "番茄",
    "蕃茄": "番茄",
    "马铃薯": "土豆",
    "洋芋": "土豆",
    "大白菜": "白菜",
    "小葱": "葱",
    "香葱": "葱",
    "蒜头": "蒜",
    "生姜": "姜",
    "老姜": "姜",
    "蛋": "鸡蛋",
    "鸡子": "鸡蛋",
}

QUANTITY_ALIASES = {
    "半": 0.5,
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

UNIT_ALIASES = {
    "颗": "个",
    "枚": "个",
    "只": "个",
    "毫升": "ml",
    "克": "g",
    "千克": "kg",
    "公斤": "kg",
}

KIND_MAP = {
    "生": ItemKind.RAW,
    "raw": ItemKind.RAW,
    "熟": ItemKind.COOKED,
    "cooked": ItemKind.COOKED,
    "主食": ItemKind.STAPLE,
    "staple": ItemKind.STAPLE,
    "调料": ItemKind.SEASONING,
    "seasoning": ItemKind.SEASONING,
    "未知": ItemKind.UNKNOWN,
    "unknown": ItemKind.UNKNOWN,
}

LOCATION_MAP = {
    "冷藏": ItemLocation.FRIDGE,
    "冰箱": ItemLocation.FRIDGE,
    "fridge": ItemLocation.FRIDGE,
    "冷冻": ItemLocation.FREEZER,
    "freezer": ItemLocation.FREEZER,
    "台面": ItemLocation.COUNTER,
    "常温": ItemLocation.COUNTER,
    "counter": ItemLocation.COUNTER,
    "橱柜": ItemLocation.CABINET,
    "柜子": ItemLocation.CABINET,
    "cabinet": ItemLocation.CABINET,
    "米箱": ItemLocation.RICE_BOX,
    "rice_box": ItemLocation.RICE_BOX,
    "电饭锅": ItemLocation.RICE_COOKER,
    "rice_cooker": ItemLocation.RICE_COOKER,
    "锅里": ItemLocation.POT,
    "锅": ItemLocation.POT,
    "pot": ItemLocation.POT,
    "未知": ItemLocation.UNKNOWN,
    "unknown": ItemLocation.UNKNOWN,
}

TIER_MAP = {
    "小时级": ExpiryTier.HOURS,
    "hours": ExpiryTier.HOURS,
    "天级": ExpiryTier.DAYS,
    "days": ExpiryTier.DAYS,
    "月级": ExpiryTier.MONTHS,
    "months": ExpiryTier.MONTHS,
    "未知": ExpiryTier.UNKNOWN,
    "unknown": ExpiryTier.UNKNOWN,
}

_QUANTITY_RE = re.compile(
    r"^(半|一|两|二|三|四|五|六|七|八|九|十|\d+(?:\.\d+)?)\s*"
    r"(个|颗|枚|块|棵|根|袋|盒|瓶|包|斤|克|千克|公斤|g|kg|ml|毫升)?\s*(.+)$",
    re.IGNORECASE,
)


class NormalizationError(ValueError):
    """一条或多条模型输出无法归一时抛出；problems 逐条可展示。"""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("；".join(problems))


def _pick(raw: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None and value != "":
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def parse_quantity(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("数量不能是布尔值")
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if text in QUANTITY_ALIASES:
            return QUANTITY_ALIASES[text]
        match = re.match(r"^(\d+(?:\.\d+)?)", text)
        if not match:
            raise ValueError(f"数量无法识别：{value}")
        number = float(match.group(1))
    if not math.isfinite(number) or number <= 0:
        raise ValueError("数量必须为正数")
    return number


def normalize_name(value: str) -> str:
    name = re.sub(r"\s+", "", value)
    return NAME_ALIASES.get(name, name)


def _map_enum(value: Any, mapping: dict, default):
    text = _text(value)
    if text is None:
        return default
    return mapping.get(text.lower(), mapping.get(text, default))


def normalize_item(
    raw: dict,
    index: int,
    rules: dict[str, dict[str, str]] | None = None,
    now: dt.datetime | None = None,
) -> EvidenceItem:
    if not isinstance(raw, dict):
        raise ValueError("证物必须是对象")

    name = _text(_pick(raw, ("name", "名称", "食材", "品名")))
    qty_value = _pick(raw, ("qty", "quantity", "数量", "余量", "分量"))
    unit = _text(_pick(raw, ("unit", "单位")))

    if name is None:
        raise ValueError("缺少食材名称")

    if qty_value is None or unit is None:
        match = _QUANTITY_RE.match(name)
        if match:
            if qty_value is None:
                qty_value = match.group(1)
            if unit is None:
                unit = match.group(2)
            name = match.group(3)

    if qty_value is None:
        raise ValueError(f"{name} 缺少数量")
    if unit is None:
        raise ValueError(f"{name} 缺少单位")

    qty = parse_quantity(qty_value)
    unit = UNIT_ALIASES.get(unit, unit)
    name = normalize_name(name)

    rule = (rules or load_rules()).get(name)
    raw_rule = rule or {}

    kind = _map_enum(_pick(raw, ("kind", "生熟")), KIND_MAP, None)
    if kind is None:
        kind = _map_enum(raw_rule.get("kind"), KIND_MAP, ItemKind.UNKNOWN)

    location = _map_enum(_pick(raw, ("location", "位置")), LOCATION_MAP, None)
    if location is None:
        location = _map_enum(
            raw_rule.get("default_location"), LOCATION_MAP, ItemLocation.UNKNOWN
        )

    tier = _map_enum(_pick(raw, ("expiry_tier", "时效档位")), TIER_MAP, None)
    if tier is None:
        tier = _map_enum(raw_rule.get("expiry_tier"), TIER_MAP, ExpiryTier.UNKNOWN)

    confidence_value = _pick(raw, ("confidence", "置信度"))
    try:
        confidence = 0.5 if confidence_value is None else float(confidence_value)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = min(1.0, max(0.0, confidence))

    expiry_text = _text(_pick(raw, ("expiry", "expiry_est", "到期", "保质期")))
    purchased_at = _text(_pick(raw, ("purchased_at", "购买时间", "购买日期")))
    opened_at = _text(_pick(raw, ("opened_at", "开封时间", "开封日期")))

    expiry_est = expiry_text
    expiry_src = "auto" if expiry_text else "rule"
    state = ItemState.REVIEW

    estimate = estimate_expiry(
        name, purchased_at=purchased_at, opened_at=opened_at, rules=rules, now=now
    )
    if expiry_est is None and estimate.get("expiry_est"):
        expiry_est = estimate["expiry_est"]
    if tier == ExpiryTier.UNKNOWN and estimate.get("expiry_tier"):
        tier = _map_enum(estimate["expiry_tier"], TIER_MAP, ExpiryTier.UNKNOWN)
    if estimate.get("safety_exceeded"):
        state = ItemState.DISCARD

    return EvidenceItem(
        id=_text(_pick(raw, ("id", "编号"))) or f"i{index}",
        name=name,
        category=_text(_pick(raw, ("category", "分类"))) or raw_rule.get("category"),
        kind=kind,
        qty=qty,
        unit=unit,
        location=location,
        shelf=_text(_pick(raw, ("shelf", "温区"))) or raw_rule.get("storage_temp"),
        purchased_at=purchased_at,
        opened_at=opened_at,
        expiry_est=expiry_est,
        expiry_tier=tier,
        expiry_src=expiry_src,
        confidence=confidence,
        state=state,
        last_seen_at=(now or dt.datetime.now()).isoformat(timespec="seconds"),
    )


def normalize_model_output(
    raw_items: Any,
    rules: dict[str, dict[str, str]] | None = None,
    strict: bool = False,
    now: dt.datetime | None = None,
) -> EvidenceList:
    """把模型输出归一化成 EvidenceList。

    - 单条不合法：非 strict 时丢弃并写进 notes；strict 时直接抛 NormalizationError。
    - 同名同单位重复项合并数量，置信度取更低值，任一条判死则整体判死。
    """
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("items")
    if not isinstance(raw_items, list):
        raise NormalizationError(["识别结果必须是数组"])
    if len(raw_items) > MAX_ITEMS:
        raise NormalizationError([f"识别结果超过 {MAX_ITEMS} 项，请拆图重拍"])

    rules = rules if rules is not None else load_rules()
    current = now or dt.datetime.now()
    problems: list[str] = []
    parsed: list[EvidenceItem] = []

    for index, raw in enumerate(raw_items, start=1):
        try:
            parsed.append(normalize_item(raw, index, rules=rules, now=current))
        except (ValueError, TypeError) as exc:
            problems.append(f"第 {index} 项：{exc}")

    if strict and problems:
        raise NormalizationError(problems)

    merged: dict[tuple[str, str], EvidenceItem] = {}
    for item in parsed:
        key = (item.name, item.unit)
        if key not in merged:
            merged[key] = item
            continue
        previous = merged[key]
        previous.qty = round(previous.qty + item.qty, 3)
        previous.confidence = min(previous.confidence, item.confidence)
        if item.state == ItemState.DISCARD:
            previous.state = ItemState.DISCARD
        if item.expiry_est and (
            previous.expiry_est is None or item.expiry_est < previous.expiry_est
        ):
            previous.expiry_est = item.expiry_est

    return EvidenceList(source="photo", items=list(merged.values()), notes=problems)
