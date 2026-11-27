"""timer Skill：到点提醒。

Demo 版由浏览器定时器 + 通知 API + 提示音实现；服务端只保留接口。
R3 实现，契约见 docs/contracts.md 第 7 节 timer_fire。
"""

from __future__ import annotations


def schedule(case_id: str, at: str, text: str) -> dict:
    """登记一个提醒，返回 {"ok": true, "job_id": "..."}。R3 实现。"""
    raise NotImplementedError("R3：实现 timer Skill")


def cancel(job_id: str) -> dict:
    """取消提醒。R3 实现。"""
    raise NotImplementedError("R3：实现 timer Skill")
