"""agentarts 云端工作流适配器（Python 标准库 HTTPS）。

契约（已核实）：
- POST {WORKFLOW_URL}（项目配置的完整 https URL），Bearer key，
  必填头 x-hw-agentarts-session-id（uuid hex）。
- body JSON：{"inputs": {"case_json": "<JSON 字符串>"}}，
  case_json 内仅带用户确认 usable 食材的 id/name/qty/unit 四字段。
- 响应：HTTP 200；业务体为根 JSON，或 'output'/'result_json'/
  'outputs.result_json' 包装（字符串 JSON 严格解码）。

安全：证书校验（默认验证）、25s 超时、响应体上限、不跟随重定向、
无自动重试。密钥与上游原文不入日志/异常详情。
业务校验失败/未识别体/HTTP 异常 -> AgentArtsError。
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
import uuid
from typing import Any, Dict, List, Optional, Tuple

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB
TIMEOUT_SECONDS = 25
MAX_NAME_LEN = 40
MAX_STEP_TEXT = 200
MAX_STEPS = 20
MAX_USED_ITEMS = 50
MINUTES_MIN, MINUTES_MAX = 1, 480
SERVINGS_MIN, SERVINGS_MAX = 1, 20
ALLOWED_STATUS = ("ready", "insufficient")
ALLOWED_AUDIT = ("pass", "reject")
ALLOWED_UNITS_LIMIT = 40  # 单位字符串长度上限

NOTE_BASE = "基础调味料（盐、油、酱油）按厨房常备假定，不计入采购；用量为云端工作流给出的计划值。"


class AgentArtsError(RuntimeError):
    """云端规划失败（配置/网络/契约校验）。详情不含密钥与上游原文。"""


def _err(msg: str) -> AgentArtsError:
    return AgentArtsError(f"agentarts: {msg}")


def _finite_number(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _nonempty_str(v: Any, limit: int) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or len(s) > limit:
        return None
    return s


class AgentArtsPlanner:
    def __init__(self, url: str, api_key: str):
        from urllib.parse import urlsplit

        try:
            endpoint = urlsplit(url)
            parts = endpoint.path.split("/")
            valid = (
                endpoint.scheme == "https"
                and endpoint.hostname
                and endpoint.username is None
                and endpoint.password is None
                and not endpoint.fragment
                and len(parts) == 4
                and parts[1] == "runtimes"
                and bool(parts[2])
                and parts[3] == "invocations"
            )
        except ValueError:
            valid = False
        if not valid:
            raise _err("请配置 AgentArts 发布后的 HTTPS 调用地址")
        if not api_key or any(char in api_key for char in "\r\n"):
            raise _err("缺少有效的 AGENTARTS_API_KEY")
        self._url = url
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "AgentArtsPlanner":
        url = os.environ.get("AGENTARTS_WORKFLOW_URL", "").strip()
        key = os.environ.get("AGENTARTS_API_KEY", "").strip()
        return cls(url, key)

    # ------------------------------------------------------------------
    # 请求构造
    # ------------------------------------------------------------------

    def _build_case_json(self, items: List[dict]) -> str:
        payload: List[dict] = []
        for it in items:
            if it.get("state") != "usable":
                continue
            iid = _nonempty_str(it.get("id"), 64)
            name = _nonempty_str(it.get("name"), MAX_NAME_LEN)
            qty = _finite_number(it.get("qty"))
            unit = _nonempty_str(it.get("unit"), ALLOWED_UNITS_LIMIT)
            if iid is None or name is None or qty is None or qty <= 0 or unit is None:
                raise _err("usable 食材缺少合法的 id/name/qty/unit")
            payload.append({"id": iid, "name": name, "qty": qty, "unit": unit})
        return json.dumps({"items": payload}, ensure_ascii=False)

    def _post(self, case_json: str) -> dict:
        body = json.dumps(
            {"inputs": {"case_json": case_json}}, ensure_ascii=False
        ).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer " + self._api_key,
                "x-hw-agentarts-session-id": uuid.uuid4().hex,
            },
        )
        # 不跟随重定向
        no_redirect = _NoRedirect()
        try:
            with urllib.request.urlopen(
                req, timeout=TIMEOUT_SECONDS, context=None
            ) as resp:
                if getattr(resp, "status", 200) != 200:
                    raise _err(f"云端返回非 200 状态: {resp.status}")
                length = resp.headers.get("Content-Length")
                if length and int(length) > MAX_BODY_BYTES:
                    raise _err("响应体超过上限")
                raw = resp.read(MAX_BODY_BYTES + 1)
                if len(raw) > MAX_BODY_BYTES:
                    raise _err("响应体超过上限")
        except urllib.error.HTTPError as e:
            e.close()
            raise _err(f"HTTP 调用失败: {e.code}") from None
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise TimeoutError("AgentArts 会诊超时") from None
            raise _err("暂时连不上 AgentArts") from None
        except TimeoutError:
            raise TimeoutError("AgentArts 会诊超时") from None
        except AgentArtsError:
            raise
        except Exception as e:
            raise _err(f"调用失败: {type(e).__name__}") from None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise _err("响应不是合法 JSON") from None
        if not isinstance(data, dict):
            raise _err("响应 JSON 根不是对象")
        return data

    # ------------------------------------------------------------------
    # 响应解包与业务校验
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap(data: dict) -> dict:
        candidates = [
            data,
            data.get("output"),
            data.get("result_json"),
            (data.get("outputs") or {}).get("result_json")
            if isinstance(data.get("outputs"), dict)
            else None,
        ]
        for c in candidates:
            if isinstance(c, dict):
                if "proposal" in c:
                    return c
            elif isinstance(c, str) and c.strip():
                try:
                    inner = json.loads(c)
                except ValueError:
                    continue
                if isinstance(inner, dict) and "proposal" in inner:
                    return inner
        raise _err("未识别的响应体结构")

    @staticmethod
    def _validate_business(biz: dict, stock: dict[tuple[str, str], dict]) -> Tuple[dict, str]:
        proposal = biz.get("proposal")
        audit = biz.get("audit")
        if not isinstance(proposal, dict) or not isinstance(audit, dict):
            raise _err("缺少 proposal/audit 对象")

        reason = _nonempty_str(audit.get("reason"), 300) or ""
        if audit.get("status") not in ALLOWED_AUDIT:
            raise _err("audit.status 非法")

        status = proposal.get("status")
        if status not in ALLOWED_STATUS:
            raise _err("proposal.status 非法")

        if status == "insufficient":
            return {
                "status": "insufficient",
                "title": "食材不足",
                "duration_min": None,
                "servings": None,
                "purchase_count": 0,
                "used_items": [],
                "steps": [],
                "note": "云端判定当前食材不足，未假定缺失食材。" + NOTE_BASE,
            }, reason or "云端判定食材不足"

        # status == ready：audit 必须真实 pass
        if audit.get("status") != "pass":
            # audit reject -> 空计划不足
            return {
                "status": "insufficient",
                "title": "食材不足",
                "duration_min": None,
                "servings": None,
                "purchase_count": 0,
                "used_items": [],
                "steps": [],
                "note": "云端审计未通过，不产出计划。" + NOTE_BASE,
            }, reason or "云端审计未通过"

        title = _nonempty_str(proposal.get("title"), MAX_NAME_LEN)
        if title is None:
            raise _err("菜名非法")
        duration = _finite_number(proposal.get("duration_min"))
        servings = _finite_number(proposal.get("servings"))
        if (
            duration is None
            or not duration.is_integer()
            or not (MINUTES_MIN <= duration <= MINUTES_MAX)
        ):
            raise _err("用时非法")
        if (
            servings is None
            or not servings.is_integer()
            or not (SERVINGS_MIN <= servings <= SERVINGS_MAX)
        ):
            raise _err("份数非法")

        used_raw = proposal.get("used_items")
        if not isinstance(used_raw, list) or not (1 <= len(used_raw) <= MAX_USED_ITEMS):
            raise _err("used_items 非法")
        used: List[dict] = []
        seen_ids = set()
        for u in used_raw:
            if not isinstance(u, dict):
                raise _err("used_items 项非法")
            iid = _nonempty_str(u.get("id"), 64)
            qty = _finite_number(u.get("qty"))
            unit = _nonempty_str(u.get("unit"), ALLOWED_UNITS_LIMIT)
            if iid is None or qty is None or qty <= 0 or unit is None:
                raise _err("用量字段非法")
            if iid in seen_ids:
                raise _err("used_items 含重复项")
            seen_ids.add(iid)
            key = (iid, unit)
            if key not in stock:
                raise _err("用量食材不在确认清单")
            if qty > stock[key]["qty"]:
                raise _err("用量超过库存")
            used.append({"id": iid, "name": stock[key]["name"], "qty": qty, "unit": unit})

        steps_raw = proposal.get("steps")
        if not isinstance(steps_raw, list) or not (1 <= len(steps_raw) <= MAX_STEPS):
            raise _err("步骤非法")
        steps: List[dict] = []
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                raise _err("步骤项非法")
            st = _nonempty_str(s.get("title"), 60)
            sd = _nonempty_str(s.get("detail"), MAX_STEP_TEXT)
            sm = _finite_number(s.get("minutes"))
            if st is None or sd is None or sm is None or not sm.is_integer() or not (
                1 <= sm <= MINUTES_MAX
            ):
                raise _err("步骤字段非法")
            steps.append({"n": i + 1, "title": st, "detail": sd, "minutes": int(sm)})

        verdict = {
            "status": "ready",
            "title": title,
            "duration_min": int(duration),
            "servings": int(servings),
            "purchase_count": 0,
            "used_items": used,
            "steps": steps,
            "note": NOTE_BASE,
        }
        return verdict, ""

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def plan(self, items: List[dict]) -> Tuple[dict, List[dict]]:
        usable = [it for it in items if it.get("state") == "usable"]
        if not usable:
            return {
                "status": "insufficient",
                "title": "食材不足",
                "duration_min": None,
                "servings": None,
                "purchase_count": None,
                "used_items": [],
                "steps": [],
                "note": "清单里没有确认可用的食材。换一组食材后再试。",
            }, []
        data = self._post(self._build_case_json(usable))
        stock = {(it["id"], it["unit"]): it for it in usable}
        verdict, reason = self._validate_business(self._unwrap(data), stock)

        chef = (
            f"按计划制作「{verdict['title']}」，用时约 {verdict['duration_min']} 分钟。"
            if verdict["status"] == "ready"
            else f"「{reason}」，本次不出菜谱。"
        )
        butler = (
            f"计划 {verdict['servings']} 人份，涉及 {len(verdict['used_items'])} 项食材。"
            if verdict["status"] == "ready"
            else "请人工补充食材后再试。"
        )
        events = [
            {"type": "agent_speak", "round": 1, "agent": "主厨", "text": chef},
            {"type": "agent_speak", "round": 2, "agent": "管家", "text": butler},
        ]
        return verdict, events


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()
        raise _err("云端返回重定向，已拒绝跟随")

    http_error_301 = http_error_303 = http_error_307 = http_error_302
