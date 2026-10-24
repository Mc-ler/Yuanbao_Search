# 说法鉴定所 / YuanBao Research Agent

文字输入 → 元宝 SearchPro API（单通道）→ LLM 扩写查询 → 真实检索 → 去重/分级/来源分册 → 研究综述或 R1–R5 断言判定。

## 两个主路径

- **深度研究**：问题 → 需求拆分（1–3 条）→ LLM 构造 3 条/需求查询 → 检索 → 全局去重 → 来源分册 → 带截图证据的研究综述/报告。**不输出成立/不成立**。
- **断言查证**：说法 → 断言/情绪抽取 → 定向查询 → 检索 → 去重 → 匹配（引文校验）→ **R1–R5 确定性判定** → 判定报告。R5 时附加模型参考意见，但明确标注「非判定」。

两条路径共用检索网关、来源分级和安全护栏。

## 当前状态

- **103 个测试通过**（pytest；以实际运行结果为准）。
- **检索 100% 走 SearchPro API**；MCP 已彻底删除（全仓无引用）。
- **无预置示例/演示**：demos/、examples/、match_demo、example_id、/api/examples、/api/fixtures 均已删除；视频展示走真实查询 + 剪辑。
- **查询统一**：/api/plan 与 /api/research 共用 claimlab/planning.py；plan_id 可把预览中的查询原样交给研究执行。
- **无 subject/city 注入**：公共 API 不再接受 subject/city；每个需求有派生的 focus（LLM 或问题文本兜底），查询只用 focus/terms。
- **去重**：深度研究对所有查询结果做一次 URL + 5-gram 聚簇；来源分册和引用以簇为单位。
- **回答阶段不传完整正文**：只传标题/域名/日期/URL 和对应网页位置截图；截图失败自动降级。
- **不持久化**：研究结果不写 SQLite；answer/report 不落库；截图只存内存（TTL 30 分钟）。/api/db/* 仅保留旧数据只读。
- **预算统一**：单断言/需求 4 次、单次 28 次、单日 400 次、墙钟 90 秒。

## 快速启动

```powershell
# 1. 依赖（本仓库使用 .Search venv；含 websockets 用于截图 CDP）
uv pip install --python ./.Search/Scripts/python.exe -r requirements.txt

# 2. 配置密钥（.env 已 gitignore）
Copy-Item .env.example .env
./.Search/Scripts/python.exe scripts/configure_keys.py yuanbao
./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider toklens

# 3. 启动
./.Search/Scripts/python.exe -m claimlab.api   # http://127.0.0.1:8000

# 4. 测试
./.Search/Scripts/python.exe -m pytest -q
```

没有 Search Key 时服务会提示「未配置检索」，研究/查证接口返回 503；不会进入本地示例模式。无 LLM Key 时仍可检索/分级/来源分册，但只输出规则摘要。

截图证据依赖本机 Chrome/Edge；也可用 `SCREENSHOT_CHROME` 指定路径，或用 `EVIDENCE_SCREENSHOTS=false` 关闭。

## 端口操作（8000）

- 启动：`.Search/Scripts/python.exe -m claimlab.api`（等价 `uvicorn claimlab.api:app --host 127.0.0.1 --port 8000`）。
- 改端口：`APP_HOST` / `APP_PORT`，或 `python -m claimlab.cli serve --host 127.0.0.1 --port 9000`。
- 停止：前台 `Ctrl + C`；后台先查 PID 再 `taskkill /F /PID <pid>`。
- 健康：`curl http://127.0.0.1:8000/api/health`。

## 查询与计划

- `POST /api/plan`：拆需求 + 生成查询，返回 `plan_id`、`queries`、候选 `fallback_queries`。
- `POST /api/research`：可传 `plan_id` 执行预览中的查询；不传则重新规划。候选回退按检索结果条件触发。
- 查询字段：`Site` / `Industry`（gov/news/acad）/ `Freshness`（d30/m3/m6/y1/y2/y5）/ `Cnt`（10/20/30/40/50）。
- LLM 失败时回退模板；模板的 focus 兜底为需求文本，不再出现无主体查询。

## 证据与截图

- SearchPro 返回摘要；研究综述的模型输入只含引用元数据与截图，不含 passage/content。
- 截图流程：无头 Chrome 打开公开页面 → 查找摘要文本并高亮/滚动 → 截取 JPEG → 作为 vision 输入；失败则纯文本降级。
- 截图 URL 走 SSRF 校验（只允许公网 http/https）；截图存内存，`GET /api/evidence/{run_id}/{n}` 提供。
- 引用校验：模型输出的 `[n]` 必须在引用集合内，越界标记为 `[n?]`；无有效引用时退回规则摘要。

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | / | Web UI（深度研究 / 断言查证 / 报告） |
| GET | /api/health | 版本、Key 布尔、模型、缓存、截图/vision 状态 |
| GET | /api/skills | 技能清单及适用板块 |
| POST | /api/plan | 共享 planner；返回 plan_id + 查询 |
| POST | /api/research | 深度研究（含 source_ledger/answer/report/screenshots） |
| POST | /api/runs | 断言查证（异步） |
| GET | /api/runs/{run_id} | 查证快照 |
| POST | /api/runs/{run_id}/cancel | 取消 |
| GET | /api/runs/{run_id}/events | SSE 进度 |
| GET | /api/report/{run_id} | 断言报告（format=md 可输出 Markdown） |
| GET | /api/evidence/{run_id}/{n} | 内存截图 |
| GET | /api/db/* | 旧版只读历史（主路径不再写入） |

旧请求字段 `subject/city/example_id/fixture_id` 已删除；请求模型启用 `extra="forbid"`，继续传会返回 422。

## 目录

```text
claimlab/
  api.py            FastAPI：研究/计划/查证/报告/截图/旧 DB
  planning.py       共享 planner + PlanStore（plan_id）
  research.py       深度研究执行器（去重/来源分册/截图/综述）
  pipeline.py       断言查证（R1–R5 确定性判定）
  demos.py          已删除
  runtime.py        Sandbox 装配
  contracts.py      契约 + VALID_CNT/normalize_cnt
  search/           api/gateway/normalize/cache/budget/archive/fake
  skills/           需求拆分、查询、分级、去重、匹配、判定、回答、报告、引用校验、安全、advisory
  evidence/         无头 Chrome 截图 + 内存图片存储
  store/            fixtures / db.py（旧版只读）
  llm/              OpenAI 兼容客户端（支持 vision）+ FakeLLM
web/                index.html / app.js / styles.css / rules.html（三标签）
config/             domains / queries / lexicons / llm_providers.json
fixtures/           测试夹具（不对外暴露）
scripts/            configure_keys / probe_* / run_research / run_verify / run_plan / broad_search / debug_search / analyze_results / git_push
tests/              103 个测试
framework.html      v2.6 历史架构图（顶部有说明；v3.0 以 README/PROJECT_PLAN 为准）
README.md / PROJECT_PLAN.md / PROJECT_ANALYSIS.md（v2.6 历史分析）
```

## 已知边界

- 研究综述是模型综合，不是 R1–R5 判定；判定只在断言查证板块。
- 截图是 best-effort：登录墙、反爬、动态页可能截不到摘要，自动降级，不编造。
- 不抓取全文；证据是检索摘要、链接与页面截图。
- 主路径不持久化检索结果/报告；刷新或重启后不可恢复。
- `/api/db/*` 是旧版只读数据，不再新增。
- 只做文字输入；不做 OCR、持续盯梢、B 端后台、公网部署。

## 下一步

- 用真实查询 + 剪辑产出视频，不再依赖预置演示。
- 完成 framework.html v4 重绘。
- P1 Skills 包、P2 Research Agent、P3 部署（鉴权/限流/清理）按 PROJECT_PLAN.md 推进。
