"""料理劫案现场 · 后端（FastAPI）。

支持两种规划 provider（环境变量 MEAL_PLAN_PROVIDER）：demo（默认，本地规则）
与 agentarts（云端工作流，app/agentarts.py）。数据仅存于当前进程内，
用 threading.Lock 保护；重启即复位。确认流程为：锁内检查并占用 in-flight，
锁外调用规划（本地或云端），成功后在锁内一次提交，finally 始终清理占用。
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

ALLOWED_PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_PHOTO_BYTES = 5 * 1024 * 1024
ALLOWED_AGENT_NAMES = {"证物官", "主厨", "军师", "管家", "红队", "主持人"}

MEAL_PLAN_PROVIDER = os.environ.get("MEAL_PLAN_PROVIDER", "demo").strip().lower()
if MEAL_PLAN_PROVIDER not in ("demo", "agentarts"):
    raise RuntimeError(
        f"MEAL_PLAN_PROVIDER 仅支持 demo / agentarts，当前为 {MEAL_PLAN_PROVIDER!r}"
    )

# ---------------------------------------------------------------------------


@dataclass
class Store:
    lock: Any = field(default_factory=threading.Lock)
    cases: Dict[str, dict] = field(default_factory=dict)
    sse_queues: Dict[str, list] = field(default_factory=dict)  # case_id -> list[dict]
    in_flight: set = field(default_factory=set)  # 正在确认中的 case_id
    case_laws: List[dict] = field(default_factory=list)  # 结案后写入的判例


STORE = Store()


class ItemIn(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1)
    qty: float
    unit: str = Field(min_length=1)
    state: str = "review"  # review / usable / discard
    expiry: Optional[str] = None


class ItemPatch(BaseModel):
    name: Optional[str] = None
    qty: Optional[float] = None
    expiry: Optional[str] = None


class ConfirmIn(BaseModel):
    items: List[ItemIn]


class StepIn(BaseModel):
    done_at: Optional[str] = None
    note: Optional[str] = None


SAMPLE_ITEMS = [
    {"id": "i1", "name": "鸡蛋", "qty": 3, "unit": "个", "state": "usable", "expiry": None},
    {"id": "i2", "name": "番茄", "qty": 2, "unit": "个", "state": "usable", "expiry": None},
    {"id": "i3", "name": "隔夜米饭", "qty": 300, "unit": "克", "state": "usable", "expiry": None},
    {"id": "i4", "name": "奶油", "qty": 200, "unit": "克", "state": "discard", "expiry": "2025-01-01"},
]


def new_case(source: str, items_raw: List[dict], mode: str = MEAL_PLAN_PROVIDER) -> dict:
    cid = uuid.uuid4().hex[:12]
    case = {
        "id": cid,
        "status": "review",
        "source": source,
        "mode": mode,
        "items": [dict(x) for x in items_raw],
        "events": [],
        "verdict": None,
        "completed_steps": [],
        "rescue_count": 0,
        "rescue_history": [],
        "closed": False,
        "case_law_id": None,
    }
    with STORE.lock:
        STORE.cases[cid] = case
        STORE.sse_queues[cid] = []
    return case


# ---------------------------------------------------------------------------
# 输入规范化
# ---------------------------------------------------------------------------


def _parse_iso_date(s):
    try:
        return _dt.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


async def read_photo(photo: UploadFile) -> bytes:
    """校验照片类型/大小；Demo 阶段只做校验，不落盘、不外传。"""
    ctype = (photo.content_type or "").lower()
    if ctype not in ALLOWED_PHOTO_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 照片")
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="照片不能超过 5 MB")
    return data


def normalize_items(payload: List[ItemIn]) -> List[dict]:
    today = _dt.date.today()
    seen = set()
    normalized: List[dict] = []
    for it in payload:
        if it.state not in ("review", "usable", "discard"):
            raise HTTPException(status_code=400, detail=f"未知状态 {it.state}")
        name = it.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="食材名称不能为空")
        unit = it.unit.strip()
        if not unit:
            raise HTTPException(status_code=400, detail="食材单位不能为空")
        if not (it.qty > 0) or not math.isfinite(it.qty):
            raise HTTPException(status_code=400, detail="数量必须为正的有限数")
        iid = it.id or uuid.uuid4().hex[:8]
        if iid in seen:
            raise HTTPException(status_code=400, detail=f"重复的食材 ID: {iid}")
        seen.add(iid)
        if it.state == "review":
            raise HTTPException(status_code=400, detail="所有 review 状态食材必须人工选择可用或弃用")
        state = it.state
        if state == "usable" and it.expiry:
            d = _parse_iso_date(it.expiry)
            if d is None:
                raise HTTPException(status_code=400, detail=f"日期格式应为 YYYY-MM-DD: {it.expiry}")
            if d < today:
                state = "discard"  # 过期自动标为弃用，保留人选
        normalized.append(
            {"id": iid, "name": name, "qty": it.qty, "unit": unit, "state": state, "expiry": it.expiry}
        )
    return normalized


# ---------------------------------------------------------------------------
# 本地规则：零采购家常菜（演示估计）
# 名称与单位都需匹配；弃用/过期食材不入菜。
# ---------------------------------------------------------------------------

RECIPES = [
    {
        "title": "番茄炒蛋",
        "required": [
            {"name": "鸡蛋", "qty": 2, "unit": "个"},
            {"name": "番茄", "qty": 1, "unit": "个"},
        ],
        "steps": [
            ("备料", "鸡蛋打散，番茄切块。", 2),
            ("炒蛋", "热锅少油，下蛋液炒至半熟盛出。", 3),
            ("合炒", "下番茄炒出汁，回锅鸡蛋，加盐调味。", 4),
        ],
        "duration": 12,
        "servings": 2,
    },
    {
        "title": "酱油蛋炒饭",
        "required": [
            {"name": "隔夜米饭", "qty": 300, "unit": "克"},
            {"name": "鸡蛋", "qty": 1, "unit": "个"},
        ],
        "steps": [
            ("备料", "蛋液打散，米饭抓散。", 2),
            ("炒饭", "热锅下油，倒入蛋液，随即下米饭翻炒。", 5),
            ("调味", "加酱油和盐，翻炒均匀出锅。", 2),
        ],
        "duration": 12,
        "servings": 1,
    },
]

BASIC_NOTE = "油、盐和酱油按常备调料计算。用时为估计。"


def _speak(round_no: int, agent: str, text: str) -> dict:
    return {"type": "agent_speak", "round": round_no, "agent": agent, "text": text}


def pick_recipe(cooking_items: List[dict]):
    pool: dict[tuple[str, str], float] = {}
    for it in cooking_items:
        key = (it["name"], it["unit"])
        pool[key] = pool.get(key, 0) + it["qty"]
    for recipe in RECIPES:
        if all(pool.get((item["name"], item["unit"]), 0) >= item["qty"] for item in recipe["required"]):
            return recipe
    return None


def build_verdict(items: List[dict]):
    """本地 demo 规划；返回 (verdict, events)。发言仅可观察事实。"""
    today = _dt.date.today()
    expired_count = 0
    cooking: List[dict] = []
    for it in items:
        if it["state"] == "discard":
            expired_count += 1
            continue
        d = _parse_iso_date(it.get("expiry")) if it.get("expiry") else None
        if d is not None and d < today:
            expired_count += 1
            continue
        cooking.append(it)

    events = [_speak(1, "证物官", f"核对了 {len(items)} 项食材，弃用 {expired_count} 项。")]

    recipe = pick_recipe(cooking)
    if recipe is None:
        events.append(_speak(2, "管家", "当前食材不够完成任一零采购家常菜，需要人工补充。"))
        verdict = {
            "status": "insufficient",
            "title": "食材不足",
            "duration_min": None,
            "servings": None,
            "purchase_count": 0,
            "used_items": [],
            "steps": [],
            "note": "目前可用的食材还不够。换一组食材再试。",
        }
        return verdict, events

    # used_items：按实际需要数量分配到相应行，而不是把库存全部计入
    used = []
    for req in recipe["required"]:
        need = req["qty"]
        for it in cooking:
            if need <= 0:
                break
            if it["name"] == req["name"] and it["unit"] == req["unit"]:
                take = min(need, it["qty"])
                used.append({"id": it["id"], "name": it["name"], "qty": take, "unit": it["unit"]})
                need -= take

    step_order = "、".join(title for title, _, _ in recipe["steps"])
    events.extend([
        _speak(2, "主厨", f"这次做{recipe['title']}。"),
        _speak(2, "军师", f"按{step_order}的顺序做。"),
        _speak(3, "管家", "用料都在清单里，无需补购。"),
        _speak(3, "红队", "用量没有超过库存，弃用食材已排除。"),
    ])
    verdict = {
        "status": "ready",
        "title": recipe["title"],
        "duration_min": recipe["duration"],
        "servings": recipe["servings"],
        "purchase_count": 0,
        "used_items": used,
        "steps": [
            {"n": i + 1, "title": t, "detail": d, "minutes": m}
            for i, (t, d, m) in enumerate(recipe["steps"])
        ],
        "note": BASIC_NOTE,
    }
    return verdict, events


def decorate_verdict(verdict: dict) -> dict:
    """补齐 timetable / warnings / tradeoff，demo 与云端共用。"""
    verdict.setdefault("timetable", [])
    verdict.setdefault("warnings", [])
    verdict.setdefault("tradeoff", None)
    if verdict.get("status") != "ready":
        return verdict

    steps = verdict.get("steps") or []
    if not verdict["timetable"] and steps:
        cursor = _dt.datetime.now() + _dt.timedelta(minutes=7)
        timetable = []
        for index, step in enumerate(steps, start=1):
            timetable.append(
                {
                    "at": cursor.strftime("%H:%M"),
                    "action": step["title"],
                    "step_n": index,
                }
            )
            cursor += _dt.timedelta(minutes=float(step.get("minutes", 0)))
        verdict["timetable"] = timetable

    if not verdict["warnings"]:
        long_steps = [
            str(index)
            for index, step in enumerate(steps, start=1)
            if float(step.get("minutes", 0)) >= 5
        ]
        if long_steps:
            verdict["warnings"].append(
                {
                    "at": None,
                    "message": f"第 {'、'.join(long_steps)} 步耗时较长，先把下一步用料备好",
                    "severity": 1,
                }
            )

    if not verdict["tradeoff"]:
        verdict["tradeoff"] = (
            f"只做{verdict.get('title', '这一道菜')}，换取 {verdict.get('duration_min')} 分钟内上桌"
        )
    return verdict


# ---------------------------------------------------------------------------
# 云端 agentarts
# ---------------------------------------------------------------------------


def plan_with_agentarts(planner, items: List[dict]):
    """在锁外用固定 planner 调用云端工作流；返回 (verdict, events)。

    agentarts.plan 与本地 verdict/events 结构兼容。云端失败抛
    AgentArtsError / TimeoutError，由调用方转为 502/504；不把本地假
    结果当云端成功。
    """
    try:
        verdict, events = planner.plan(items)
    except TimeoutError:
        raise
    except Exception as e:
        if type(e).__name__ == "AgentArtsError":
            raise
        raise RuntimeError(f"云端规划调用失败: {e}") from e
    # 云端工作流可以返回 2–6 个角色；只保留白名单内的结构化发言
    events = [
        ev for ev in events
        if ev.get("type") == "agent_speak" and ev.get("agent") in ALLOWED_AGENT_NAMES
    ]
    return verdict, events


def queue_sse(cid: str, events: List[dict]) -> None:
    STORE.sse_queues[cid] = list(events)


# ---------------------------------------------------------------------------

DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def create_app(provider: str = MEAL_PLAN_PROVIDER) -> FastAPI:
    planner = None
    if provider == "agentarts":
        # 固定进程模式：启动即校验云端配置并保存 planner；缺配置给明确错误（不回显配置原文）
        try:
            from .agentarts import AgentArtsError, AgentArtsPlanner

            planner = AgentArtsPlanner.from_env()
        except ImportError:
            raise RuntimeError("agentarts 模块不可用，无法以 agentarts 模式启动")
        except Exception as e:
            raise RuntimeError("agentarts 配置不完整，无法启动：%s" % type(e).__name__)
    if provider not in ("demo", "agentarts"):
        raise RuntimeError("MEAL_PLAN_PROVIDER 仅支持 demo / agentarts")

    app = FastAPI(title="料理劫案现场 backend")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": provider}

    @app.post("/cases")
    async def create_case(photo: Optional[UploadFile] = File(default=None)):
        if photo is not None:
            await read_photo(photo)
            # 照片阶段仍在本地：不读取内容、不保存、不外传，仅生成一张空白待核对清单，
            # 由用户根据照片逐行添加食材。
            items_raw = []
            # 案例本身记录实际规划 provider；确认时才按 mode 调用（云端时本地仍不做图像识别）
            return new_case("photo", items_raw, mode=provider)
        return new_case("sample", SAMPLE_ITEMS, mode=provider)

    @app.get("/cases/{cid}")
    def get_case(cid: str):
        with STORE.lock:
            case = STORE.cases.get(cid)
            if case is None:
                raise HTTPException(status_code=404, detail="案例不存在")
            return dict(case)

    @app.patch("/items/{item_id}")
    def patch_item(item_id: str, patch: ItemPatch):
        """低置信度证物的人工纠正入口；只能在确认前改。"""
        with STORE.lock:
            found_case = None
            found_item = None
            for case in STORE.cases.values():
                for item in case["items"]:
                    if item.get("id") == item_id:
                        found_case, found_item = case, item
                        break
                if found_item is not None:
                    break

            if found_item is None:
                raise HTTPException(status_code=404, detail="证物不存在")
            if found_case["status"] != "review":
                raise HTTPException(status_code=409, detail="只能在确认前修改证物")

            if patch.name is not None:
                name = patch.name.strip()
                if not name:
                    raise HTTPException(status_code=400, detail="食材名称不能为空")
                found_item["name"] = name

            if patch.qty is not None:
                if not math.isfinite(patch.qty) or patch.qty <= 0:
                    raise HTTPException(status_code=400, detail="数量必须为正数")
                found_item["qty"] = patch.qty

            if patch.expiry is not None:
                if patch.expiry.strip() == "":
                    found_item["expiry"] = None
                else:
                    parsed = _parse_iso_date(patch.expiry.strip())
                    if parsed is None:
                        raise HTTPException(status_code=400, detail="到期日期格式应为 YYYY-MM-DD")
                    found_item["expiry"] = parsed.isoformat()
                    if parsed < _dt.date.today():
                        found_item["state"] = "discard"

            return dict(found_item)

    @app.post("/cases/{cid}/confirm")
    def confirm(cid: str, payload: ConfirmIn):
        normalized = normalize_items(payload.items)

        with STORE.lock:
            case = STORE.cases.get(cid)
            if case is None:
                raise HTTPException(status_code=404, detail="案例不存在")
            if case["status"] != "review":
                raise HTTPException(status_code=409, detail="案例已确认，不能重复确认")
            if cid in STORE.in_flight:
                raise HTTPException(status_code=409, detail="该案例正在确认中，请勿重复提交")
            STORE.in_flight.add(cid)

        try:
            if provider == "agentarts":
                try:
                    verdict, events = plan_with_agentarts(planner, normalized)
                except TimeoutError:
                    raise HTTPException(status_code=504, detail="云端规划超时，可稍后重试")
                except Exception as e:
                    if isinstance(e, HTTPException):
                        raise
                    if type(e).__name__ == "AgentArtsError":
                        raise HTTPException(status_code=502, detail="云端规划暂不可用，可稍后重试")
                    raise HTTPException(status_code=502, detail="云端规划暂不可用，可稍后重试")
            else:
                verdict, events = build_verdict(normalized)

            verdict = decorate_verdict(verdict)

            # 一次提交：items/status/verdict/events/SSE；成功前保持占用，云端失败时不落库
            with STORE.lock:
                case = STORE.cases.get(cid)
                if case is None or case["status"] != "review":
                    raise HTTPException(status_code=409, detail="案例状态已变化，请刷新后重试")
                case["items"] = normalized
                case["status"] = "insufficient" if verdict["status"] == "insufficient" else "planned"
                case["verdict"] = verdict
                case["events"] = events
                queue_sse(cid, events)
                result = dict(case)
        finally:
            with STORE.lock:
                STORE.in_flight.discard(cid)  # 始终取消 in-flight：失败释放可重试
        return result

    @app.post("/cases/{cid}/steps/{n}")
    def step_done(cid: str, n: int, payload: StepIn):
        with STORE.lock:
            case = STORE.cases.get(cid)
            if case is None:
                raise HTTPException(status_code=404, detail="案例不存在")
            if case["status"] != "planned" or case["verdict"] is None:
                raise HTTPException(status_code=409, detail="案例尚未形成计划")
            steps = case["verdict"]["steps"]
            if n < 1 or n > len(steps):
                raise HTTPException(status_code=404, detail="步骤编号不存在")
            if n not in case["completed_steps"]:
                case["completed_steps"].append(n)
                case["completed_steps"].sort()
            return dict(case)

    @app.post("/cases/{cid}/rescue")
    async def rescue(cid: str, photo: UploadFile = File(...)):
        """第二幕急救（Demo 版）：只做状态校验和规则建议，不解析照片内容。"""
        await read_photo(photo)
        with STORE.lock:
            case = STORE.cases.get(cid)
            if case is None:
                raise HTTPException(status_code=404, detail="案例不存在")
            if case["status"] != "planned" or case["verdict"] is None:
                raise HTTPException(status_code=409, detail="案例尚未形成计划")
            if case.get("closed"):
                raise HTTPException(status_code=409, detail="案例已结案")

            count = int(case.get("rescue_count", 0))
            if count >= 2:
                return {
                    "diagnosis": "已经急救两次，再救下去风险更高，建议止损。",
                    "options": [
                        {"id": "c", "action": "止损：盛出可吃部分，配现有小菜", "risk": "低"}
                    ],
                    "rescue_count": count,
                    "stoploss_only": True,
                }

            done = len(case.get("completed_steps") or [])
            if done == 0:
                diagnosis = "还没开火，先按第 1 步来，别急着改方案。"
                options = [
                    {"id": "a", "action": "先按第 1 步备料，确认火力和锅具", "risk": "低"},
                    {"id": "b", "action": "改做更简单的炒饭/盖饭", "risk": "中"},
                    {"id": "c", "action": "止损：盛出现有食材，配小菜", "risk": "低"},
                ]
            else:
                diagnosis = f"已做到第 {done} 步，先判断是火候、水量还是调味问题。"
                options = [
                    {"id": "a", "action": "补少量热水，盖盖焖 2–3 分钟", "risk": "低"},
                    {"id": "b", "action": "改做炒饭/盖饭，把当前食材重新组合", "risk": "中"},
                    {"id": "c", "action": "止损：盛出可吃部分，配现有小菜", "risk": "低"},
                ]

            case["rescue_count"] = count + 1
            case.setdefault("rescue_history", []).append(
                {"step_index": done, "diagnosis": diagnosis, "options": options}
            )
            event = _speak(3, "军师", f"急救：{diagnosis}")
            case["events"].append(event)
            STORE.sse_queues.setdefault(cid, []).append(event)
            return {
                "diagnosis": diagnosis,
                "options": options,
                "rescue_count": case["rescue_count"],
                "stoploss_only": False,
            }

    @app.post("/cases/{cid}/close")
    async def close_case(
        cid: str,
        empty_plate: UploadFile = File(...),
        actual_minutes: Optional[float] = Form(default=None),
        failures: Optional[str] = Form(default=None),
        empty: bool = Form(default=True),
    ):
        """第四幕结案（Demo 版）：写一条判例、把已用食材标为 consumed。"""
        await read_photo(empty_plate)
        if actual_minutes is not None and (
            not math.isfinite(actual_minutes) or actual_minutes <= 0
        ):
            raise HTTPException(status_code=400, detail="实际时长必须为正数")

        with STORE.lock:
            case = STORE.cases.get(cid)
            if case is None:
                raise HTTPException(status_code=404, detail="案例不存在")
            if case["status"] != "planned" or case["verdict"] is None:
                raise HTTPException(status_code=409, detail="案例尚未形成计划")
            if case.get("closed"):
                raise HTTPException(status_code=409, detail="案例已结案")

            verdict = case["verdict"]
            used_ids = {u.get("id") for u in verdict.get("used_items", [])}
            for item in case["items"]:
                if item.get("id") in used_ids:
                    item["state"] = "consumed"

            raw_failures = (failures or "").replace("；", ";")
            failure_list = [part.strip() for part in raw_failures.split(";") if part.strip()]
            if not empty and not failure_list:
                failure_list.append("未空盘")

            law_id = "law-" + uuid.uuid4().hex[:8]
            law = {
                "id": law_id,
                "created_at": _dt.datetime.now().isoformat(timespec="seconds"),
                "title": verdict.get("title"),
                "items": [
                    item["name"] for item in case["items"] if item.get("id") in used_ids
                ],
                "used_items": verdict.get("used_items", []),
                "duration_min": verdict.get("duration_min"),
                "actual_minutes": actual_minutes,
                "empty_plate": bool(empty),
                "failures": failure_list,
                "rescued": int(case.get("rescue_count", 0)) > 0,
                "human_verified": True,
            }
            STORE.case_laws.append(law)

            case["closed"] = True
            case["case_law_id"] = law_id
            case["status"] = "closed"
            changes = [
                {
                    "type": "inventory_change",
                    "item": item["name"],
                    "from": "usable",
                    "to": "consumed",
                }
                for item in case["items"]
                if item.get("id") in used_ids
            ]
            case["events"].extend(changes)
            STORE.sse_queues.setdefault(cid, []).extend(changes)
            return {"case_law_id": law_id, "case": dict(case)}

    @app.get("/case-laws")
    def list_case_laws():
        with STORE.lock:
            return {"items": list(STORE.case_laws)}

    @app.get("/cases/{cid}/events")
    async def sse(cid: str):
        with STORE.lock:
            case = STORE.cases.get(cid)
            if case is None:
                raise HTTPException(status_code=404, detail="案例不存在")
            if case["verdict"] is None:
                raise HTTPException(status_code=409, detail="尚未确认，无事件")
            pending = list(STORE.sse_queues.get(cid) or [])

        def gen():
            for ev in pending:
                ev_type = ev.get("type", "agent_speak")
                yield f"event: {ev_type}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
            v = case["verdict"]
            yield f"event: verdict\ndata: {json.dumps(v, ensure_ascii=False)}\n\n"
            yield "event: close\ndata: {}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.mount("/", StaticFiles(directory=DIST, html=True, check_dir=False), name="spa")
    return app


app = create_app()
