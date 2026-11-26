# 料理劫案现场 · AI 侦探会诊

照片在本机预览，食材由人填写并确认。默认用本地规则生成做饭计划。真实的主厨和管家接入按 [项目交接说明](项目交接.md) 继续。

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
.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v
pnpm.cmd --dir frontend run build
```

- [项目交接说明](项目交接.md)
- [AgentArts 主厨与管家工作流](参赛资料/AgentArts/主厨与管家工作流.md)
- [参赛资料索引](参赛资料/索引.md)
- [Flash 安装说明](tools/flash-executor/安装说明.md)
