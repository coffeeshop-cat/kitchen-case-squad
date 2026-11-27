"""平台适配层：所有模型/智能体调用只从这里出去。

R2 实现。现有 `app/agentarts.py` 是工作流适配器；本文件负责把
“角色调用”统一成 complete() 一个出口，避免平台接口散落在业务代码里。
"""

from __future__ import annotations

import os
from typing import Any

SUPPORTED_PROVIDERS = ("agentarts", "local")


def current_provider() -> str:
    provider = os.environ.get("LLM_PROVIDER", "agentarts").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise RuntimeError(f"LLM_PROVIDER 仅支持 {SUPPORTED_PROVIDERS}，当前为 {provider!r}")
    return provider


def complete(
    agent_id: str,
    messages: list[dict[str, Any]],
    schema: dict[str, Any] | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """统一出口：内部走 AgentArts；本地调试可切到本地模型。

    R2 实现。返回必须已通过 contracts 中对应 schema 的校验。
    """
    raise NotImplementedError("R2：实现 AgentArts / local 双 provider")
