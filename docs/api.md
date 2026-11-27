# HTTP API v0.1（R1）

> 服务入口：`app/main.py`，默认端口 `8765`，本机地址 `http://127.0.0.1:8765`。
> 数据模型见 [contracts.md](contracts.md)；本文只描述 HTTP 行为。
>
> 状态标记：`已实现` 表示当前代码可用；`R2` / `R3` 表示按轮次计划预留。

## 0. 通用

- 请求/响应编码：UTF-8；JSON 用 `application/json`。
- 错误格式沿用 FastAPI：`{"detail": "中文错误说明"}`。
- 当前 Demo 不做鉴权；`AGENTARTS_API_KEY` 只放服务端环境变量，绝不下发前端。
- 案例数据存在进程内，重启即复位；R3 换 SQLite。

| 状态码 | 含义 |
|---|---|
| 400 | 参数不合法（照片类型/大小、食材字段、日期格式） |
| 404 | 案例或步骤不存在 |
| 409 | 状态冲突（重复确认、未形成计划、并发确认） |
| 422 | FastAPI 请求体校验失败（字段缺失/类型错误） |
| 502 | AgentArts 云端规划不可用 |
| 504 | AgentArts 云端规划超时 |

案例对象（`Case`）统一长这样：

```json
{
  "id": "a1b2c3d4e5f6",
  "status": "review",
  "source": "sample",
  "mode": "demo",
  "items": [],
  "events": [],
  "verdict": null,
  "completed_steps": [],
  "rescue_count": 0,
  "rescue_history": [],
  "closed": false,
  "case_law_id": null
}
```

`status`：`review` 待确认 / `planned` 已出剧本 / `insufficient` 食材不足 / `closed` 已结案。

---

## 1. 已实现接口

### 1.1 健康检查

```http
GET /health
```

响应：

```json
{"status": "ok", "mode": "demo"}
```

`mode` 取 `demo` 或 `agentarts`，由环境变量 `MEAL_PLAN_PROVIDER` 决定。

### 1.2 开案

```http
POST /cases
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `photo` | file | 否 | JPG/PNG/WebP，≤5 MB；不传则用示例食材 |

说明：R1 阶段照片只在本机预览，不上传内容、不做识别，返回一张空的待核对清单（`source=photo`）；不传照片返回 4 项示例食材（`source=sample`）。

响应：`Case`，`status=review`。

错误：

- `400 仅支持 JPG/PNG/WebP 照片`
- `400 照片不能超过 5 MB`

### 1.3 查案例

```http
GET /cases/{cid}
```

响应：`Case`。不存在返回 `404 案例不存在`。

### 1.4 确认证物

```http
POST /cases/{cid}/confirm
Content-Type: application/json
```

请求：

```json
{
  "items": [
    {
      "id": "i1",
      "name": "鸡蛋",
      "qty": 3,
      "unit": "个",
      "state": "usable",
      "expiry": "2026-11-28"
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 否 | 不传则自动生成 8 位 |
| `name` | string | 是 | 去空格后不能为空 |
| `qty` | number | 是 | 必须为正的有限数 |
| `unit` | string | 是 | 不能为空 |
| `state` | enum | 是 | `review` / `usable` / `discard`；`review` 一律拒绝 |
| `expiry` | string | 否 | `YYYY-MM-DD`；早于今天自动改为 `discard` |

行为：

- 所有 `review` 必须由人改成 `usable` 或 `discard`，否则 `400`；
- 同一请求内 `id` 重复返回 `400`；
- 锁内占用 `in-flight`，防止重复提交；成功前不落库，云端失败可重试；
- 返回确认后的 `Case`，`status` 为 `planned` 或 `insufficient`。

错误：

- `400`：未知状态、名称为空、单位为空、数量非正、日期格式错、重复 ID、仍有 `review`
- `404 案例不存在`
- `409 案例已确认，不能重复确认` / `该案例正在确认中，请勿重复提交`
- `502` / `504`：AgentArts 模式下云端失败/超时

### 1.5 步骤打勾

```http
POST /cases/{cid}/steps/{n}
Content-Type: application/json
```

```json
{"done_at": "2026-11-26T18:45:00+08:00", "note": "火有点大"}
```

- `n` 从 1 开始，必须落在 `verdict.steps` 范围内；
- 重复打勾幂等，不会重复写入 `completed_steps`；
- 返回更新后的 `Case`。

错误：`404 案例不存在` / `404 步骤编号不存在` / `409 案例尚未形成计划`。

### 1.6 事件流（SSE）

```http
GET /cases/{cid}/events
Accept: text/event-stream
```

- 案例尚未出剧本：`409 尚未确认，无事件`；
- 当前实现会先回放已产生的事件，再发 `verdict`，最后发 `close`；
- R3 改为实时推送（`timer_fire`、`inventory_change` 在执行过程中产生）。

事件格式：

```text
event: agent_speak
data: {"type":"agent_speak","agent":"chef","text":"这次做番茄炒蛋。","round":2}

event: verdict
data: {"status":"ready","title":"番茄炒蛋", "...": "..."}

event: close
data: {}
```

字段定义见 [contracts.md 第 7 节](contracts.md#7-事件流)。

---

## 2. 已实现接口（Demo 版）

### 2.1 急救

```http
POST /cases/{cid}/rescue
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `photo` | file | 是 | 锅里照片，限制同开案 |

响应：

```json
{
  "diagnosis": "已做到第 1 步，先判断是火候、水量还是调味问题。",
  "options": [
    {"id": "a", "action": "补少量热水，盖盖焖 2–3 分钟", "risk": "低"},
    {"id": "b", "action": "改做炒饭/盖饭，把当前食材重新组合", "risk": "中"},
    {"id": "c", "action": "止损：盛出可吃部分，配现有小菜", "risk": "低"}
  ],
  "rescue_count": 1,
  "stoploss_only": false
}
```

Demo 行为：只校验照片类型/大小，不解析内容；诊断根据 `completed_steps` 的数量给规则建议。`rescue_count` 达到 2 后只返回止损建议（`stoploss_only=true`）。`409` 表示案例尚未形成计划或已结案。

### 2.2 结案

```http
POST /cases/{cid}/close
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `empty_plate` | file | 是 | 空盘照 |
| `actual_minutes` | number | 否 | 实际总时长，必须为正 |
| `failures` | string | 否 | 分号分隔，如 `米饭偏硬;盐多了` |
| `empty` | bool | 否 | 默认 `true`；`false` 时自动记一条“未空盘” |

响应：

```json
{"case_law_id": "law-a1b2c3d4", "case": {"status": "closed", "...": "..."}}
```

行为：把 `used_items` 对应的食材标为 `consumed`，写一条 `human_verified=true` 的判例，案例状态改为 `closed`。重复结案返回 `409 案例已结案`。

### 2.3 判例列表

```http
GET /case-laws
```

返回：

```json
{"items": [{"id": "law-a1b2c3d4", "title": "番茄炒蛋", "empty_plate": true, "failures": []}]}
```

Demo 版只做内存列表，重启即清空；R3 换 SQLite。

---

## 3. 已实现接口（感知层）

### 3.1 修改单件证物

```http
PATCH /items/{item_id}
Content-Type: application/json
```

```json
{"name": "豆腐", "qty": 0.25, "expiry": "2026-11-27"}
```

用途：低置信度证物的一键纠正。规则：

- 只能改 `name` / `qty` / `expiry`，`id` 不可改；
- 只能在案例 `status=review` 时改，已确认/已结案返回 `409`；
- `qty` 必须为正数，`expiry` 必须是 `YYYY-MM-DD`；早于今天自动标 `discard`；
- 返回更新后的证物对象。

错误：`400` 名称为空/数量非正/日期格式错；`404 证物不存在`；`409 只能在确认前修改证物`。

---

## 4. 平台适配与降级

- `MEAL_PLAN_PROVIDER=demo`：本地规则，不触网；当前默认。
- `MEAL_PLAN_PROVIDER=agentarts`：启动时校验 `AGENTARTS_WORKFLOW_URL` 与 `AGENTARTS_API_KEY`，缺失直接拒绝启动。
- 云端失败不伪装成本地成功：`502` / `504` 原样返回，由前端提示重试。
- 外部 MCP（price / calendar）一律“有则用、无则降级”，降级只写日志，不报错。

## 5. 并发与幂等

| 操作 | 规则 |
|---|---|
| `confirm` | 同一案例同时只允许一个请求；后到者 `409` |
| `steps/{n}` | 重复调用幂等，`completed_steps` 不重复 |
| `rescue` | 同一案例最多 2 次，超出返回止损建议 |
| `close` | 只允许一次；重复调用 `409` |

## 6. 安全红线

- 不在 URL、日志、响应里出现 `AGENTARTS_API_KEY`；
- 照片只在内存中处理，R1 不落盘；后续落盘目录 `data/photos/` 已被 `.gitignore` 排除；
- 错误信息不回显完整配置或堆栈。
