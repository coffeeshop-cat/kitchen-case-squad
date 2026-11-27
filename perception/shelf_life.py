"""保质期规则：读取 data/shelf_life.csv，按三档时效估算到期时间。

R1 先维护数据表，R2 接入规则推算。
"""

from __future__ import annotations

import csv
from pathlib import Path

SHELF_LIFE_PATH = Path(__file__).resolve().parent.parent / "data" / "shelf_life.csv"


def load_rules(path: Path | None = None) -> dict[str, dict[str, str]]:
    """以食材名为键读取规则表；文件不存在时返回空字典。"""
    target = path or SHELF_LIFE_PATH
    if not target.exists():
        return {}
    with target.open(encoding="utf-8-sig", newline="") as handle:
        return {row["name"]: row for row in csv.DictReader(handle)}


def estimate_expiry(name: str, purchased_at: str, opened_at: str | None = None) -> dict:
    """按规则表推算 expiry_est / expiry_tier / expiry_src。R2 实现。"""
    raise NotImplementedError("R2：按 shelf_life.csv 推算到期时间与档位")
