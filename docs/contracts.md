# 主契约 v0.1（R1 冻结）

> 本文是三条线之间唯一的数据口径。文档与 `contracts/` 下的 Pydantic 模型必须同步修改；只改文档或只改代码都算契约违规。
>
> - 权威来源：`料理劫案现场-AI侦探会诊/开发方案.md`（子目录版）
> - 代码实现：`contracts/`
> - HTTP 接口：[api.md](api.md)
> - 赛题：华为 ICT 2026 · 赛题二（AgentArts 智能体设计及应用）

## 0. 版本与冻结规则

| 版本 | 冻结时间 | 冻结内容 | 负责人 |
|---|---|---|---|
| `v0.1-r1` | R1 合流（D3） | 证物清单字段、案例表字段 | 卢妙音 |
| `v0.2-r2` | R2 合流（D6） | 事件流四类事件、识别输出 | 卢妙音 / 刘彬彬 |
| `v0.3-r3` | R3 合流（D9） | `runs`、急救、结案、判例、库存/账本 | 刘彬彬 / 卢妙音 |
| `v0.4-r4` | R4 合流（D12） | 评测结果格式、三配置开关 | 柳浩冉 |
| `v1.0-rc` | R5 合流（D15） | 提审口径，冻结后只修 bug | 三人 |

变更流程：

1. 在 GitHub 提 issue，写清“改哪个字段、为什么、影响谁”；
2. 每轮合流时三人用 30 分钟确认，能加字段就不改字段；
3. 改动同时提 PR：`docs/contracts.md` + `contracts/*.py` + 受影响的调用方；
4. 破坏性改动必须升版本号，并在 PR 描述里列出需要同步修改的文件。

## 1. 通用约定

- JSON 字段一律 `snake_case`；枚举值用英文小写，中文只用于展示（见 `ROLE_LABELS` 等映射）。
- 时间：日期 `YYYY-MM-DD`，时刻 `HH:MM`，时间戳用 ISO 8601（`2026-11-26T18:30:00+08:00`）。
- 数量：`qty` 为正数，单位单独放 `unit`，禁止把“半块”写进 `qty`。
- 金额：人民币，保留一位小数。
- 所有智能体输出必须是 JSON，禁止自由文本；解析失败按一次失败计入评测。
- 所有模型输出都带 `confidence`，低于 `0.7` 的证物进入人工确认。

## 2. 证物清单 `EvidenceItem`

对应 `items` 表与 `contracts/items.py`。

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `id` | string | 是 | — | 案例内唯一，如 `i3` |
| `name` | string | 是 | — | 展示名，如“豆腐” |
| `category` | string\|null | 否 | null | 豆制品/叶菜/蛋/主食/调料 |
| `kind` | enum | 是 | — | `raw` 生 / `cooked` 熟 / `staple` 主食 / `seasoning` 调料 / `unknown` |
| `qty` | number | 是 | — | 必须 > 0 |
| `unit` | string | 是 | — | 块/棵/个/ml/半锅 |
| `location` | enum | 是 | — | `fridge` 冷藏 / `freezer` 冷冻 / `counter` 台面 / `cabinet` 橱柜 / `rice_box` 米箱 / `rice_cooker` 电饭锅 / `pot` 锅里 / `unknown` |
| `shelf` | string\|null | 否 | null | 存储温区，如 `冷藏4C`、`冷冻-18C`、`常温` |
| `purchased_at` | string\|null | 否 | null | 购买日期 |
| `opened_at` | string\|null | 否 | null | 开封时间 |
| `expiry_est` | string\|null | 否 | null | 预计到期，ISO 日期或时间戳 |
| `expiry_tier` | enum | 是 | — | `hours` 小时级 / `days` 天级 / `months` 月级 / `unknown` |
| `expiry_src` | enum | 否 | `auto` | `auto` 识别 / `user` 用户填 / `rule` 规则推 |
| `confidence` | number | 否 | 1.0 | 0–1，低于 0.7 需人工确认 |
| `state` | enum | 否 | `review` | `review` 待确认 / `usable` 可用 / `discard` 弃用 |
| `last_seen_at` | string\|null | 否 | null | 最近一次在照片中出现的时间 |

**确认态与落库状态的映射**：

| API `state` | `items.status` |
|---|---|
| `review` | 不落库，等待确认 |
| `usable` | `active` |
| `discard` | `discarded` |
| 结案后结转/吃完 | `consumed` |

**三条模型约束**（来自方案 3.1，代码里必须校验）：

1. 常备调料（盐、油、糖、醋、酱油）默认存在，不进照片、不入卷；用户标记“用完”才扣减。
2. 时效只对 `hours` / `days` 两档上倒计时；`months` 只进库存，不参与“先到期先消耗”排序。
3. 食安红线单独判定，命中即 `discard`，不允许“再热一下还能吃”的讨论。

示例：

```json
{
  "id": "i3",
  "name": "豆腐",
  "category": "豆制品",
  "kind": "cooked",
  "qty": 0.5,
  "unit": "块",
  "location": "fridge",
  "shelf": "冷藏4C",
  "purchased_at": "2026-11-25",
  "opened_at": null,
  "expiry_est": "2026-11-27",
  "expiry_tier": "days",
  "expiry_src": "rule",
  "confidence": 0.86,
  "state": "usable",
  "last_seen_at": "2026-11-26T18:30:00+08:00"
}
```

## 3. 厨房约束 `Constraints`

```json
{
  "people": 2,
  "minutes": 20,
  "gear": ["microwave", "rice_cooker"],
  "dislikes": ["香菜"],
  "must_use": ["i3"]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `people` | int | ≥1，用餐人数 |
| `minutes` | int | >0，承诺总时长 |
| `gear` | string[] | `wok` / `microwave` / `rice_cooker` / `oven` / `single_stove` |
| `dislikes` | string[] | 忌口，硬约束 |
| `must_use` | string[] | 必须消耗的 `item_id`，没有就空数组 |

## 4. 智能体统一输出 `AgentUtterance`

五个角色 + 主持人共用这个壳；字段含义见下表。

```json
{
  "agent": "chef",
  "claim": "可以做微波炉麻婆豆腐盖饭",
  "uses": [{"item_id": "i3", "amount": "半块"}],
  "objections": [{"target": "quartermaster", "reason": "微波炉路线不需要看火"}],
  "confidence": 0.78,
  "needs": ["确认豆腐是否还能用"]
}
```

| 角色 | `agent` | `claim` 是什么 | `objections` 指向 |
|---|---|---|---|
| 证物官 | `evidence` | 位置、生熟、哪些能用、哪些判死 | 主厨用了不该用的东西 |
| 主厨 | `chef` | 候选菜 + 替代方案 | 军师太保守、管家太抠 |
| 军师 | `strategist` | 时序可行性 | 主厨超时、管家增加工序 |
| 管家 | `quartermaster` | 碗数与结转 | 主厨方案洗不完 |
| 红队 | `redteam` | 会怎么失败 | 所有人的方案 |
| 主持人 | `host` | 收敛结论 + tradeoff | 不适用 |

规则：

- `uses[].item_id` 必须存在于当前证物清单；`amount` 用自然语言量词，但必须能映射回 `qty`。
- `objections[].target` 只能是其他角色，不能指向自己。
- `confidence` 必填；低于 0.5 的发言在 UI 上标灰。
- 红队不使用本壳，单独用第 5 节的结构。

## 5. 红队输出 `RedTeamOutput`

```json
{
  "failure_modes": [
    {"where": "第 2 步 / 26cm 锅", "what": "排骨装不下，会溢锅",
     "severity": 1, "evidence": "方案里写了『两斤排骨一次煎』"}
  ],
  "reject": true,
  "required_change": "分两次煎，或改刀成小块"
}
```

硬约束（代码在 `contracts/agents.py` 校验）：

- `reject=true` 必须同时满足：`required_change` 非空，且至少一条 `severity=3`；
- 一案只允许驳回一次；
- `required_change` 只能指方向，不许写“去买点 XX”；
- 只报能指到方案原文的问题，空话不计入评测。

## 6. 剧本 `Verdict`

对应 `contracts/verdict.py`，也是 `verdict` 事件的 payload。

```json
{
  "status": "ready",
  "title": "番茄炒蛋",
  "duration_min": 12,
  "servings": 2,
  "purchase_count": 0,
  "used_items": [{"id": "i1", "name": "鸡蛋", "qty": 2, "unit": "个"}],
  "steps": [
    {"n": 1, "title": "备料", "detail": "鸡蛋打散，番茄切块。", "minutes": 2, "heat": null}
  ],
  "timetable": [
    {"at": "18:37", "action": "备料", "step_n": 1}
  ],
  "warnings": [
    {"at": "18:45", "message": "番茄下锅后会出水，别加太多盐", "severity": 2}
  ],
  "tradeoff": "放弃了第二道菜，换取 20 分钟内上桌",
  "note": "油、盐和酱油按常备调料计算。"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | enum | `ready` / `insufficient` |
| `title` | string | 菜名；不足时写“食材不足” |
| `duration_min` | number\|null | 承诺总时长 |
| `servings` | int\|null | 份量 |
| `purchase_count` | int | 需要采购的食材数，零采购为 0 |
| `used_items` | object[] | 实际消耗，必须能对上 `items.id` |
| `steps` | object[] | 执行步骤，`n` 从 1 连续编号 |
| `timetable` | object[] | 分钟级时序，`at` 为 `HH:MM` |
| `warnings` | object[] | 翻车预警，`severity` 1–3 |
| `tradeoff` | string\|null | 主持人必须写“放弃了什么、换来了什么” |
| `note` | string\|null | 展示给用户的说明 |

`status=insufficient` 时允许 `steps`、`timetable`、`used_items` 为空，但 `title` 与 `note` 必填。

## 7. 事件流

SSE 的 `event:` 名就是事件类型，`data:` 是对应 payload。前端不得解析自然语言。

| 事件 | `data` 字段 | 触发时机 |
|---|---|---|
| `agent_speak` | `type, agent, text, round` | 任一角色发言；`round` 1–3 |
| `verdict` | `Verdict` | 收敛完成，剧本定稿 |
| `timer_fire` | `type, text, case_id, at` | 到达某个步骤的时间点 |
| `inventory_change` | `type, item, from, to` | 库存扣减/弃用/结转 |
| `close` | `{}` | SSE 流结束（传输层事件，不落库） |

示例：

```text
event: agent_speak
data: {"type":"agent_speak","agent":"chef","text":"这次做番茄炒蛋。","round":2}

event: verdict
data: {"status":"ready","title":"番茄炒蛋", "...": "..."}
```

`inventory_change` 的 `from` 是 Python 关键字，模型里用 `from_` + alias，序列化时必须 `by_alias=True`。

## 8. 执行、急救、结案

### 8.1 执行记录 `RunStep`

对应 `runs` 表，第三幕急救只读这张表。

| 字段 | 类型 | 说明 |
|---|---|---|
| `case_id` | string | 案例 ID |
| `step_index` | int | 第几步 |
| `action` | string | 下酱/翻面/关火 |
| `done_at` | string\|null | 完成时间 |
| `ingredients` | object[] | `[{"name": "豆腐", "amount": "半块"}]` |
| `heat` | string\|null | 火力 |
| `note` | string\|null | 用户备注 |

### 8.2 急救 `Rescue`

```json
{
  "case_id": "c1",
  "step_index": 2,
  "photo_ref": "rescue_c1_2.jpg",
  "diagnosis": "米饭偏硬，水加少了",
  "options": [
    {"id": "a", "action": "补 30ml 热水，盖盖焖 3 分钟", "risk": "低"},
    {"id": "b", "action": "改做炒饭", "risk": "中"},
    {"id": "c", "action": "止损：盛出可吃部分，配现有小菜", "risk": "低"}
  ],
  "chosen": null
}
```

`RESCUE` 最多进入 2 次；第三次只返回`止损建议`，不再给三选一。

### 8.3 结案 `Close`

```json
{
  "empty_plate": true,
  "actual_minutes": 26,
  "leftovers": [{"item_id": "i3", "qty": 0.25, "unit": "块"}],
  "failures": ["第 2 步米饭偏硬"],
  "rescued": true,
  "human_verified": true
}
```

`empty_plate` 的判定：按给定份量吃完，或剩菜全部结转，记 `true`；丢掉记 `false`。

## 9. 判例 `CaseLaw`

检索规则（不上向量库）：

```text
score(d, q) = 0.6 * jaccard(主料集合)
            + 0.2 * (器具完全一致 ? 1 : 0)
            + 0.2 * max(0, 1 - |时长差| / 10)
取 score >= 0.5 的 top-3；不足三条就有几条给几条，不许凑。
```

入库门槛：

- `human_verified = 1` 才参与检索；
- 冷启动回填团队真实做过的饭，目标 12–15 条，不硬凑 30 条；
- 判例里不得写真实地址、真实人名。

## 10. 状态机

```text
INTAKE → RECALL → DELIBERATE(≤3) → VERDICT → EXECUTE → [RESCUE] → CLOSE
```

| 状态 | 进入条件 | 产出 | 落库 |
|---|---|---|---|
| `intake` | 收到照片 | 证物清单 + 置信度 | `items` |
| `recall` | 清单确认 | 3 条判例 | — |
| `deliberate` | 判例就绪 | 各 agent JSON + 轮次 | — |
| `verdict` | 收敛 | 剧本 | `cases` 初版 |
| `execute` | 用户开始做 | 打勾、扣库存 | `runs`、`items` |
| `rescue` | 拍了锅里 | 归因 + 三选一 | `runs.note` |
| `close` | 空盘照 | 结转 + 判例终版 | `cases` 更新 |

允许的跳转以 `orchestrator/state_machine.py` 的 `ALLOWED_TRANSITIONS` 为准；`DELIBERATE` 自循环最多 3 次，`RESCUE` 最多 2 次。

## 11. 目录所有权与变更

| 目录 | 归属 | 其他人 |
|---|---|---|
| `perception/` `data/` | 卢妙音 | 只读、提 issue |
| `agents/` `prompts/` `orchestrator/` `tools/` `app/agentarts.py` | 刘彬彬 | 只读、提 issue |
| `frontend/` `eval/` | 柳浩冉 | 只读、提 issue |
| `contracts/` `docs/contracts.md` `docs/api.md` | 三人共同 | 改前先说一声 |

跨目录改动必须提 issue，不许直接改。提示词进版本控制，文件名格式 `{role}.v{n}.md`，文件头写一行变更原因。
