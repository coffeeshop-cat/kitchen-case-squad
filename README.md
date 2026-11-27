# 料理劫案现场 · AI 侦探会诊

照片在本机预览，食材由人填写并确认。默认用本地规则生成做饭计划。真实的主厨和管家接入按 [项目交接说明](项目交接.md) 继续。

## 工程结构（R1 骨架）

现有 `app/` + `frontend/` 是可运行 Demo；下列目录是 R1–R5 的目标骨架，未实现处会显式抛 `NotImplementedError`，不会静默返回假数据。

| 目录 | 用途 | 轮次 | 状态 |
|---|---|---|---|
| `docs/contracts.md` | 主契约：证物、智能体、剧本、事件、状态机 | R1 冻结 | 已建 |
| `docs/api.md` | HTTP / SSE 接口契约 | R1 | 已建 |
| `contracts/` | 契约的 Pydantic 实现 | R1 | 已建 |
| `perception/` | 照片 → 证物清单、归一化、保质期规则 | R2 | 归一化 + 30 条规则已建 |
| `agents/` | 五角色运行器 | R2 | 骨架 |
| `orchestrator/` | 状态机、主持人、判例检索 | R2/R3 | 骨架 |
| `tools/` | timer / inventory / ledger | R3 | 骨架 |
| `eval/` | 四个核心数字、三配置跑数 | R4 | 骨架 |
| `prompts/` | 提示词版本目录 | R2 | 已建红队 v1 |
| `data/` | 案例表、保质期表、静态价表 | R1–R3 | 30 条保质期 + 表头 |

契约改动流程见 [docs/contracts.md](docs/contracts.md)；接口字段见 [docs/api.md](docs/api.md)。

## 本机运行（Windows）

本项目实测 Python 3.13.9、Node.js 24.15.0 和 pnpm 11.7.0。在 PowerShell 中进入项目根目录。首次安装 pnpm 时可以运行 `npm.cmd install --global pnpm@11.7.0`。

```powershell
python.exe -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt
pnpm.cmd --dir frontend install --frozen-lockfile
pnpm.cmd --dir frontend run build
$env:MEAL_PLAN_PROVIDER = "demo"
.\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

打开 [本地 Demo](http://127.0.0.1:8765/)，点「用示例试试」，核对食材、生成做饭计划并勾选步骤。案例存在后端进程内，重启后可重新开案。

开发前端时可以另开终端运行 `pnpm.cmd --dir frontend run dev`，打开 Vite 输出的地址。接口默认代理到本机 8765 端口。

## 验证与资料

```powershell
.\\.venv\\Scripts\\python.exe -m pip install -r requirements-dev.txt
.\\.venv\\Scripts\\python.exe -m pytest -q
pnpm.cmd --dir frontend run build
```

- [项目交接说明](项目交接.md)
- [主契约](docs/contracts.md)
- [接口契约](docs/api.md)
- [AgentArts 三智能体施工单](docs/agentarts-workflow.md)
- [AgentArts 主厨与管家工作流](参赛资料/AgentArts/主厨与管家工作流.md)
- [参赛资料索引](参赛资料/索引.md)
- [Flash 安装说明](tools/flash-executor/安装说明.md)
