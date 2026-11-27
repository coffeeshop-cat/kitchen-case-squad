"""跨线共用的枚举。

约定：JSON 一律使用这里的英文值；中文只用于 UI 展示（见 *_LABELS）。
新增枚举值必须同时更新 docs/contracts.md，并通知三条线。
"""

from __future__ import annotations

from enum import Enum


class AgentRole(str, Enum):
    EVIDENCE = "evidence"          # 证物官
    CHEF = "chef"                  # 主厨
    STRATEGIST = "strategist"      # 军师
    QUARTERMASTER = "quartermaster"  # 管家
    REDTEAM = "redteam"            # 红队
    HOST = "host"                  # 主持人


class ItemKind(str, Enum):
    RAW = "raw"                    # 生
    COOKED = "cooked"              # 熟
    STAPLE = "staple"              # 主食
    SEASONING = "seasoning"        # 调料
    UNKNOWN = "unknown"


class ItemLocation(str, Enum):
    FRIDGE = "fridge"              # 冷藏
    FREEZER = "freezer"            # 冷冻
    COUNTER = "counter"            # 台面
    CABINET = "cabinet"            # 橱柜
    RICE_BOX = "rice_box"          # 米箱
    RICE_COOKER = "rice_cooker"    # 电饭锅
    POT = "pot"                    # 锅里
    UNKNOWN = "unknown"


class ExpiryTier(str, Enum):
    HOURS = "hours"                # 小时级
    DAYS = "days"                  # 天级
    MONTHS = "months"              # 月级
    UNKNOWN = "unknown"


class ItemState(str, Enum):
    """人工确认态；落库时映射到 items.status。"""

    REVIEW = "review"              # 待确认
    USABLE = "usable"              # 可用
    DISCARD = "discard"            # 弃用


class InventoryStatus(str, Enum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    DISCARDED = "discarded"


class VerdictStatus(str, Enum):
    READY = "ready"
    INSUFFICIENT = "insufficient"


class CaseState(str, Enum):
    INTAKE = "intake"
    RECALL = "recall"
    DELIBERATE = "deliberate"
    VERDICT = "verdict"
    EXECUTE = "execute"
    RESCUE = "rescue"
    CLOSE = "close"


ROLE_LABELS = {
    AgentRole.EVIDENCE: "证物官",
    AgentRole.CHEF: "主厨",
    AgentRole.STRATEGIST: "军师",
    AgentRole.QUARTERMASTER: "管家",
    AgentRole.REDTEAM: "红队",
    AgentRole.HOST: "主持人",
}

KIND_LABELS = {
    ItemKind.RAW: "生",
    ItemKind.COOKED: "熟",
    ItemKind.STAPLE: "主食",
    ItemKind.SEASONING: "调料",
    ItemKind.UNKNOWN: "未知",
}

LOCATION_LABELS = {
    ItemLocation.FRIDGE: "冷藏",
    ItemLocation.FREEZER: "冷冻",
    ItemLocation.COUNTER: "台面",
    ItemLocation.CABINET: "橱柜",
    ItemLocation.RICE_BOX: "米箱",
    ItemLocation.RICE_COOKER: "电饭锅",
    ItemLocation.POT: "锅里",
    ItemLocation.UNKNOWN: "未知",
}

EXPIRY_TIER_LABELS = {
    ExpiryTier.HOURS: "小时级",
    ExpiryTier.DAYS: "天级",
    ExpiryTier.MONTHS: "月级",
    ExpiryTier.UNKNOWN: "未知",
}
