# 说法鉴定所 / YuanBao Research Agent

文字输入 → 元宝 SearchPro API（单通道）→ LLM 需求拆分 → LLM 自动查询 → 真实检索 → 带 [n] 引用的回答与调查报告。

## 当前状态

- **85 个测试通过**（pytest）。
- **检索 100% 走 SearchPro API**；MCP 已彻底删除（全仓无引用）。
- **LLM 查询构造**：自动判断每条查询所需字段（Query/Site/Industry/Freshness/Cnt），字段名与 QueryPlan 同步；freshness 统一 d/m/y 紧凑格式（d30/m3/m6/y1/y2/y5），Industry 仅 gov/news/acad；**subject/city 不注入查询**。
- **演示快路径**：三个演示问题由 prepare_demos.py 预生成完整方案+结果到 demos/，match_demo 精确匹配秒回、零额度；其余走真实查询。
- **调查报告双入口**：终端 run_example_live.py --report 输出 Markdown；Web「调查报告」标签页查看/打印；/api/research 返回 report 字段。
- **SQLite 索引**：store/db.py（文件为权威），/api/db/* 支持统计/历史检索/详情/CSV 导出。
- **Web 极简 UI**：「研究 / 调查报告」两个标签页，无示例、无主体/城市、无冗余。

## 快速启动

```powershell
# 1. 依赖（本仓库使用 .Search venv）
uv pip install --python ./.Search/Scripts/python.exe -r requirements.txt

# 2. 配置密钥（.env 已 gitignore）
Copy-Item .env.example .env
./.Search/Scripts/python.exe scripts/configure_keys.py yuanbao
./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider toklens

# 3. 预生成演示（可选，命中演示问题秒回）
./.Search/Scripts/python.exe scripts/prepare_demos.py

# 4. 启动
./.Search/Scripts/python.exe -m claimlab.api   # http://127.0.0.1:8000

# 5. 测试
./.Search/Scripts/python.exe -m pytest -q
```

没有 Key 时进入 DEMO（本地 fixtures + 启发式）；填入 Key 后重启即切真实检索。

## 端口操作（8000）

- **启动**：`.Search/Scripts/python.exe -m claimlab.api`（等价 `uvicorn claimlab.api:app --host 127.0.0.1 --port 8000`）。
  - 改端口：环境变量 `APP_HOST` / `APP_PORT`，或 `.Search/Scripts/python.exe -m claimlab.cli serve --host 0.0.0.0 --port 9000`。
- **停止**：前台进程 `Ctrl + C`；后台/静默进程用 `taskkill /F /PID <pid>`（先查 PID）。
- **确认端口**：
  - `netstat -ano | findstr :8000`（或 PowerShell `Get-NetTCPConnection -LocalPort 8000 -State Listen`）。
  - `curl http://127.0.0.1:8000/api/health` 返回 JSON 即在线。
  - 端口被旧进程占用：取 PID 后 `taskkill /F /PID <pid>` 再重启。

## Key 与供应商

- **元宝 SearchPro**：`.env` 存纯 key；keys.py 统一拼一次 Bearer；Cnt 以字符串发送并吸附 10/20/30/40/50。
- **Toklens LLM**：config/llm_providers.json 管理 gpt/codex；/models 自动选模型；当前可用 gpt-5.6-sol（gpt-4.x 均 404）。

## 查询构造（LLM 自动 + 无字段干扰）

- LLM 只收 requirement.text/field/search_terms，**不收 subject/city**，从问题自动抽主体/城市/年份/指标写进 query，并自动判断 site/industry/freshness/cnt 子集。
- 字段枚举：Industry ∈ {gov, news, acad}；freshness ∈ {d30, m3, m6, y1, y2, y5}。
- 互斥实测：Cnt 与 Industry/Freshness 可并用，无互斥报错；Site 命中率低，不作为唯一定向。
- 离线回退：无 LLM 时走模板（plan_requirement_queries）。

## 演示快路径

- `scripts/prepare_demos.py`：对 examples/ 三个已填问题各跑一次真实检索，固化 requirements/queries/results/metrics/answer/report 到 demos/<id>.json。
- `claimlab/demos.py` 的 match_demo：按 example_id 精确匹配，再按规范化文本精确匹配；命中直接返回预置 payload（demo=True），未命中走真实查询。
- 落地以真实查询为主：demo 只是快路径。

## 调查报告

- `claimlab/skills/research_report.py`：组装「结论 + [n] 引用 + 来源表 + 指标」。
- 终端：`run_example_live.py --example q1 --report [--report-file path]`。
- Web：「调查报告」标签页（检索完成后自动可看，可打印）。

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | / | Web UI |
| GET | /api/health | 版本、通道、Key 布尔、模型、缓存、DB |
| GET | /api/examples | 三个汇报示例 |
| POST | /api/plan | 计划（命中 demo 返回预置；否则 LLM 构造） |
| POST | /api/research | 真实检索（含 answer/report/demo 字段） |
| GET | /api/db/stats | SQLite 统计 |
| GET | /api/db/runs?q=&limit=&offset= | 历史运行检索 |
| GET | /api/db/runs/{run_id} | 单条运行详情 |
| GET | /api/db/export.csv?q= | CSV 导出 |

## 目录

```text
claimlab/
  api.py            FastAPI + 研究/计划/DB 接口
  research.py       研究执行器（演示快路径 + LLM 构造 + 报告）
  demos.py          演示预置 load/save/match
  runtime.py        Sandbox 装配
  contracts.py      契约 + VALID_CNT/normalize_cnt
  search/           api/gateway/normalize/cache/budget/archive/fake
  skills/           需求拆分、查询、去重、分级、匹配、判定、回答、报告、安全
  store/            fixtures / db.py（SQLite 索引）
  llm/              OpenAI 兼容客户端 + FakeLLM
web/                index.html / app.js / styles.css（研究+调查报告 tabs）
config/             domains / queries / lexicons / llm_providers.json
examples/           三个汇报问题；demos/ 预置结果
scripts/            configure_keys / probe_* / run_example* / broad_search / prepare_demos / debug_search / analyze_results / git_push
tests/              85 个测试
framework.html      当前框架图 v3
README.md / PROJECT_PLAN.md
```

## 已知边界

- framework.html 已由 archify 生成（validate/deliver/check 通过，browser-check 因本机无 Chrome 跳过，未做浏览器目检）。
- Site 站内过滤在 SearchPro 命中率低，查询构造以 Industry 为主。
- demo 结果是快照，需 prepare_demos.py --refresh 更新。
- 只做文字输入；截图/OCR、持续盯梢、B 端后台、公网部署不在本轮。

## 下一步

- P1 Skills 包、P2 Research Agent、P3 部署按 PROJECT_PLAN.md 推进。
- 浏览器人工验收 Web（demo 快路径 + 调查报告 tab + 自定义问题）。
