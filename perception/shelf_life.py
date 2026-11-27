"""保质期规则：读取 data/shelf_life.csv，按三档时效估算到期时间。

R1 维护数据表，R2 接入规则推算。
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from typing import Any

SHELF_LIFE_PATH = Path(__file__).resolve().parent.parent / "data" / "shelf_life.csv"
ALLOWED_TIERS = {"hours", "days", "months", "unknown"}


def load_rules(path: Path | None = None) -> dict[str, dict[str, str]]:
    """以食材名为键读取规则表；文件不存在时返回空字典。"""
    target = path or SHELF_LIFE_PATH
    if not target.exists():
        return {}
    with target.open(encoding="utf-8-sig", newline="") as handle:
        return {row["name"]: row for row in csv.DictReader(handle)}


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    # 统一按本地朴素时间比较，避免 aware/naive 混用
    return parsed.replace(tzinfo=None)


def _infer_tier(hours: float) -> str:
    if hours <= 48:
        return "hours"
    if hours <= 90 * 24:
        return "days"
    return "months"


def _format_expiry(value: dt.datetime, tier: str) -> str:
    if tier == "hours":
        return value.strftime("%Y-%m-%dT%H:%M")
    return value.strftime("%Y-%m-%d")


def estimate_expiry(
    name: str,
    purchased_at: str | None = None,
    opened_at: str | None = None,
    rules: dict[str, dict[str, str]] | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """按规则表推算 expiry_est / expiry_tier / expiry_src。

    没有规则或没有基准时间时不编造日期，只返回档位。
    """
    rule = (rules or load_rules()).get(name)
    if not rule:
        return {
            "expiry_est": None,
            "expiry_tier": "unknown",
            "expiry_src": "rule",
            "safety_exceeded": False,
            "rule": None,
        }

    tier = (rule.get("expiry_tier") or "unknown").strip().lower()
    if tier not in ALLOWED_TIERS:
        tier = "unknown"

    base = _parse_datetime(opened_at) or _parse_datetime(purchased_at)
    if base is None:
        return {
            "expiry_est": None,
            "expiry_tier": tier,
            "expiry_src": "rule",
            "safety_exceeded": False,
            "rule": rule,
        }

    try:
        life_hours = float(rule.get("default_life_hours") or 0)
    except ValueError:
        life_hours = 0
    if life_hours <= 0:
        return {
            "expiry_est": None,
            "expiry_tier": tier,
            "expiry_src": "rule",
            "safety_exceeded": False,
            "rule": rule,
        }

    if tier == "unknown":
        tier = _infer_tier(life_hours)
    expiry = base + dt.timedelta(hours=life_hours)

    safety_exceeded = False
    try:
        safety_hours = float(rule.get("safety_limit_hours") or 0)
    except ValueError:
        safety_hours = 0
    if safety_hours > 0:
        current = now or dt.datetime.now()
        safety_exceeded = current > base + dt.timedelta(hours=safety_hours)

    return {
        "expiry_est": _format_expiry(expiry, tier),
        "expiry_tier": tier,
        "expiry_src": "rule",
        "safety_exceeded": safety_exceeded,
        "rule": rule,
    }
