# AgentArts 工作流落地清单（R1 → R2）

> 代码侧适配器已完成：[app/agentarts.py](../app/agentarts.py) 支持 Bearer、会话头、超时、响应上限、不跟随重定向，以及 2–6 个角色的 `events` 校验。
> **工作流尚未发布**：发布需要在华为云 AgentArts 控制台操作，必须由有工作空间权限的同学完成。本文是照着做即可的施工单。

## 1. 目标：最小可评分形态

| 评分点 | 最小实现 |
|---|---|
| 智能体设计 | 3 个角色：证物官、主厨、红队 |
| 多 Agent 协作 | 证物官先筛食材 → 主厨出方案 → 红队驳回/放行 |
| 工具编排 | 1 个自定义工具：`inventory_check`（按 id/unit 查库存，防止超量） |
| 知识接入 | 1 个知识库：保质期规则 + 10–15 条真实判例 |
| 部署上线 | 发布工作流，拿到 HTTPS 调用地址，后端切 `agentarts` 模式 |

不要一开始做五个角色；先把 3 个角色跑通，再考虑加军师/管家。

## 2. 工作流节点

开始节点入参仍是一个字符串 `case_json`：

```json
{
  "items": [
    {"id": "i1", "name": "鸡蛋", "qty": 3, "unit": "个", "kind": "raw", "location": "fridge"}
  ],
  "constraints": {"people": 2, "minutes": 20, "gear": ["wok"], "dislikes": [], "must_use": []}
}
```

### 节点 1：证物官

- 输入：`case_json`
- 任务：逐项检查 `id/name/qty/unit/kind/location`；标出缺失字段、单位不一致、疑似过期。
- 输出：`evidence`（结构化 JSON）+ 一条 `events` 发言。
- 提示词要点：只报事实，不给菜谱；不臆造照片里没有的食材。

### 节点 2：主厨

- 输入：`case_json` + 证物官的 `evidence` + 知识库 top-3 判例
- 任务：输出 `proposal`，格式与现有 [主厨与管家工作流](主厨与管家工作流.md) 一致。
- 硬约束：只用清单里的食材；`used_items` 必须带原 `id`、原单位；不得超量；不写“去买 XX”。

### 节点 3：红队

- 输入：`proposal` + `case_json` + `evidence`
- 任务：只找能指到方案原文的破绽；输出 `audit`：
  - `status=pass`：放行；
  - `status=reject`：必须写 `reason`，且至少一条 `severity=3` 的致命问题。
- 输出：`audit` + 一条 `events` 发言（角色 `红队`）。

### 结束节点

把三份结果映射成：

```json
{
  "proposal": {"status": "ready", "title": "番茄炒蛋", "duration_min": 12, "servings": 2,
    "used_items": [{"id": "i1", "qty": 2, "unit": "个"}],
    "steps": [{"title": "备料", "detail": "打蛋切番茄", "minutes": 3}]},
  "audit": {"status": "pass", "reason": "用量都在库存内"},
  "events": [
    {"type": "agent_speak", "round": 1, "agent": "证物官", "text": "3 项食材，全部可用"},
    {"type": "agent_speak", "round": 2, "agent": "主厨", "text": "做番茄炒蛋"},
    {"type": "agent_speak", "round": 3, "agent": "红队", "text": "用量没有超过库存"}
  ]
}
```

`events` 是可选的；不返回时程序会自动生成主厨/管家两条兜底发言。返回时必须满足：

- `type` 只能是 `agent_speak`；
- `agent` 只能是 `证物官/主厨/军师/管家/红队/主持人`；
- `round` 是 1–3 的整数；
- `text` 非空且 ≤300 字。

## 3. 工具：`inventory_check`

在 AgentArts 里注册一个自定义工具（或 MCP），入参：

```json
{"items": [{"id": "i1", "qty": 2, "unit": "个"}], "stock": [{"id": "i1", "qty": 3, "unit": "个"}]}
```

出参：

```json
{"ok": true, "problems": []}
```

规则：id 必须存在、单位必须一致、`qty` 不得大于库存。主厨节点在输出 `proposal` 前调用一次；调用失败时按 `reject` 处理，不返回“假成功”。

## 4. 知识库

1. 把 `data/shelf_life.csv` 转成 3–5 段 Markdown（按小时级/天级/月级分组），上传为知识库文档。
2. 把团队真实做过的 10–15 顿饭写成判例（菜名、食材、时长、翻车点、是否空盘），一起上传。
3. 主厨节点开启检索，取 top-3，把命中的判例原文注入提示词。
4. 不要为了让检索“好看”而编判例；没有真实记录就少放。

## 5. 发布与联调

1. 控制台调试三组输入：
   - 鸡蛋 + 番茄（应出计划）；
   - 只有调料（应 `insufficient`）；
   - 主厨故意超量（红队应 `reject`）。
2. 发布工作流，复制 `https://.../runtimes/{runtime_name}/invocations`。
3. 本机设置：

```powershell
$env:MEAL_PLAN_PROVIDER="agentarts"
$env:AGENTARTS_WORKFLOW_URL="https://..."
$env:AGENTARTS_API_KEY="..."
```

4. 启动后端，验收：
   - `/health` 返回 `mode=agentarts`；
   - 确认食材后，SSE 至少出现证物官/主厨/红队三条发言；
   - 超量/单位错配返回 `502`，不能悄悄回退到本地计划；
   - 超时返回 `504`。

## 6. 当前阻塞

- 没有工作空间发布权限，无法替你们在控制台点“发布”；
- 没有 `AGENTARTS_API_KEY`，无法做真实调用；
- 因此当前只能验收本地 demo（`MEAL_PLAN_PROVIDER=demo`）。

把发布后的 URL 和 Key 放进本机环境变量（不要提交到仓库），即可切到真实 AgentArts 模式。
