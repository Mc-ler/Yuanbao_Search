# 说法鉴定所 / YuanBao Research Agent

文字输入 → 元宝搜索（API / MCP 双通道）→ 可验证断言 → 带来源的结论 / 研究报告。

## 当前状态

- **P0 已可运行**：文字输入、三态用例、检索网关、去重/分级/匹配/判定、SSE UI、契约 C 报告。
- **73 个测试通过**（pytest 0.93s；含新增需求/示例/推送/LLM 诊断测试）。
- **S1 已改为「需求拆分」**：研究问题 → 1–3 条 `Requirement` → `plan_requirement_queries`，不再经过 Claim。
- **查询接口**：`POST /api/plan`、`GET /api/examples`、`scripts/run_example.py`；三个汇报问题在 `examples/`，q1 已填并跑通，q2/q3 待手动填。
- **Key 处理已集中**：Yuanbao Search 自动拼接一次 `Bearer `（已带前缀也不会重复）；GPT/Codex 走第三方 Toklens 供应商，按 provider 配置 Key 并自动选择模型。
- **团队协作**：`scripts/git_push.py` 首次配置 repo/remote，之后只填 commit 信息即可提交并推送 GitHub。
- **M5–M9 展示/汇报/录屏/提交由下游团队负责**，不属于本模块。
- P1 Skills 包、P2 Research Agent、P3 容器化部署尚未开始；下一阶段计划以 [PROJECT_PLAN.md](<PROJECT_PLAN.md>) 为准。

当前项目规划：[PROJECT_PLAN.md](<PROJECT_PLAN.md>) · 框架图：[framework.html](<framework.html>)

## 快速启动

```powershell
# 1. 依赖（本仓库使用 .Search venv）
uv pip install --python ./.Search/Scripts/python.exe -r requirements.txt
uv pip install --python ./.Search/Scripts/python.exe -r requirements-mcp.txt

# 2. 配置密钥（.env 已被 .gitignore 忽略）
Copy-Item .env.example .env
./.Search/Scripts/python.exe scripts/configure_keys.py yuanbao
./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider toklens
./.Search/Scripts/python.exe scripts/configure_keys.py show

# 3. 启动
./.Search/Scripts/python.exe -m claimlab.api
# 打开 http://127.0.0.1:8000

# 4. 测试
./.Search/Scripts/python.exe -m pytest -q

# 5. 离线跑一个 fixture
./.Search/Scripts/python.exe -m claimlab.cli run --fixture case_conflict --fake
```

没有 Key 时应用自动进入 DEMO（本地 fixtures + 启发式 LLM），UI 顶部有黄色提示。填入 Key 后重启，即切换真实元宝搜索；LLM 未配置时断言抽取/匹配仍走启发式规则。

## Key 与第三方供应商

### Yuanbao Search

- `.env` 的 `SEARCH_API_KEY` 存**纯 key**；`claimlab/keys.py` 在请求时统一拼 `Bearer <key>`。
- 即使值写成 `Bearer sk-...`，也会先剥掉再加，不会出现 `Bearer Bearer`。
- `scripts/configure_keys.py yuanbao` 会把 Key 写成纯值；`show` 只打印长度/是否存在，不打印 Key。

### GPT / Codex（Toklens 第三方供应商）

- `config/llm_providers.json` 定义了两个 provider，默认都指向 `https://lax.toklens.ai/v1`：
  - `gpt`：`GPT_BASE_URL` / `GPT_API_KEY`
  - `codex`：`CODEX_BASE_URL` / `CODEX_API_KEY`
  - 两者都可回退到共享的 `TOKLENS_API_KEY`。
- 选择顺序：`LLM_PROVIDER` / 任务路由（`extract_claims`、`match_evidence`、`report` → gpt；`code` → codex）→ 默认 provider。
- 模型选择顺序：显式 `LLM_MODEL` / 调用方 model hint → 任务模型 → provider 的 `preferred_models` 中在 `/models` 可用的第一项 → `default_model` → `/models` 的第一个；遇到 model not found 会自动尝试下一个候选。
- 写入 Key：
  ```powershell
  # 共享 Toklens Key（推荐，GPT/Codex 都用它）
  ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider toklens
  # 或者分别写
  ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider gpt
  ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider codex
  # 检查（不打印 Key）
  ./.Search/Scripts/python.exe scripts/configure_keys.py show
  ```
- 改完 `.env` 后重启服务；启动时 `/api/health` 会返回 provider、选中模型与 Key 布尔值（不含 Key）。

### 当前 Toklens 组模型（2026-10-24 实测）

- `gpt-4o` / `gpt-4o-mini` / `gpt-4.1` / `gpt-4.1-mini` 均返回 404 `model_not_found`：“not supported by any configured account in this group”。
- `/models` 目录包含 `gpt-5.5`、`gpt-5.6-sol/luna/terra`、`gpt-6-*`、`gpt-6.1-sol`、`codex-auto-review` 及 image 模型；**目录不等于 entitlement**。
- 当前可用且已选：`gpt-5.6-sol`；同组可用还包括 `gpt-5.6-luna`、`gpt-6.1-sol`、`gpt-6-sol`、`gpt-6-luna`、`codex-auto-review`。
- 当前 `.env`：`LLM_PROVIDER=gpt`、`LLM_MODEL=gpt-5.6-sol`、`LLM_BASE_URL=https://lax.toklens.ai/v1`。
- 诊断/修复脚本：`scripts/probe_llm.py` 会逐模型请求 `/chat/completions`，`--apply` 写入 `.env` 与 provider config；不要再把 `LLM_MODEL` 设为 `gpt-4.1`。

## 真实通道

- API：`POST https://api.wsa.cloud.tencent.com/SearchPro`，`Authorization: Bearer <SEARCH_API_KEY>`，`Pages` 为 JSON 字符串数组。
- MCP：`POST https://api.wsa.cloud.tencent.com/Mcp`，JSON-RPC 2.0 over Streamable HTTP，工具 `SearchPro`。
- 两通道统一归一化为 `SearchBatch`：`pics`/`images` 兼容、`Version`/`Msg`/空结果/错误码处理。
- 默认 `SEARCH_PROVIDER=api`；可设 `mcp` 或 `auto`（仅传输层故障降级，鉴权失败不降级）。
- LLM：OpenAI 兼容的 Toklens `/v1`，按 `config/llm_providers.json` 的 provider 配置路由与选模型。

### 真实通道探针

```powershell
./.Search/Scripts/python.exe scripts/probe_search.py --provider both
./.Search/Scripts/python.exe scripts/probe_llm.py
./.Search/Scripts/python.exe scripts/calibrate_dedup.py
```

`probe_search.py` 会把归一化结果与原始响应写到 `probe/raw/`，用于核对 API/MCP 字段差异与去重阈值；`probe/` 已在 `.gitignore` 中。

## 需求拆分与查询接口

S1 不再做断言抽取。研究问题先进入 `skills/requirements.py`，拆成 1–3 条 `Requirement`，再直接交给 `plan_requirement_queries`。

三个汇报示例在 `examples/`，`question` 留空，需手动填入具体地区/年份/主体：

```powershell
# 先编辑 examples/q1_statistics_bulletin.json 的 question
./.Search/Scripts/python.exe scripts/run_example.py --example q1_statistics_bulletin
./.Search/Scripts/python.exe scripts/run_example.py --example q2_scenic_history --json
./.Search/Scripts/python.exe scripts/run_example.py --example q3_vehicle_restriction --heuristic
```

HTTP 查询接口（不执行检索、不消耗检索预算）：

```text
GET  /api/examples
POST /api/plan   {"example_id": "q1_statistics_bulletin"}
POST /api/plan   {"text": "某市2025年统计公报中人均可支配收入的统计口径和数据来源是什么？", "city": "西安"}
```

## 团队协作 / GitHub 推送

```powershell
# 首次：提供 repo 路径与 remote，配置会写入 push.config.json（gitignored）
./.Search/Scripts/python.exe scripts/git_push.py `
  --repo "D:\AI_projects\YuanBao_Search" `
  --remote "https://github.com/Mc-ler/Yuanbao_Search.git"

# 之后：只填 commit title/body，脚本自动 add/commit/push
./.Search/Scripts/python.exe scripts/git_push.py
```

脚本拒绝提交 `.env`、`cache/`、`archive/`、`state/`、`probe/`、`.Search/`、`push.config.json`、`.push.json`；凭据交给 Git Credential Manager 或 SSH，脚本不保存 token。

## HTTP 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | Web UI |
| GET | `/rules` | 判定口径公开页 |
| GET | `/api/health` | 版本、通道、Key 布尔、模型、缓存、预算 |
| GET | `/api/fixtures` | 三个示例用例 |
| GET | `/api/skills` | 9 个 Skill 的静态清单（S1 为需求拆分） |
| GET | `/api/examples` | 三个汇报示例；显示 question 是否已填 |
| POST | `/api/plan` | `{text?, example_id?}` → Requirement + QueryPlan（不执行检索） |
| POST | `/api/runs` | `{text, subject, city, fixture_id, search_off}` → `{run_id}` |
| GET | `/api/runs/{id}/events` | SSE：run.started / split.done / query.planned / search.result / unit.verdict / run.done |
| GET | `/api/runs/{id}` | 状态 / 报告 |
| POST | `/api/runs/{id}/cancel` | 取消 |
| GET | `/api/report/{id}?format=json|md` | 报告导出 |

## 目录

```text
claimlab/
  api.py            FastAPI + SSE + 静态页
  pipeline.py       有界查证流水线（P0 固定序列）
  runtime.py        Sandbox：Provider / LLM / Cache / Archive
  keys.py           Bearer 归一化 + LLM provider/模型选择
  contracts.py      契约 A/B/C 与图数据
  search/           API / MCP / fake provider、归一化、缓存、预算、审计
  skills/           需求拆分（S1）、查询、去重、分级、匹配、判定、报告、安全；legacy Claim 抽取
  llm/              OpenAI 兼容客户端 + FakeLLM
  store/            fixtures / 报告
web/                UI、判定口径页、样式
config/             domains / queries / lexicons / llm_providers.json
fixtures/           成立 / 冲突 / 证据不足
examples/           三个汇报问题（q1 已填，q2/q3 手动填）
scripts/            configure_keys / probe_* / run_example / git_push
tests/              73 个测试
PROJECT_PLAN.md     当前项目规划（唯一规划文档）
framework.html      当前流程框架图
push.config.example.json
```

## 已知边界

- 当前只做文字输入；截图/OCR、持续盯梢、B 端后台、平台可信度打分都不在本轮。
- 示例来源 URL 是合成的，只用于验证链路与 UI；真实演示要用真实主体与可点开来源，并用录屏/报告留证。
- `research_topic` 的查询接口（`/api/plan`）已可用，但完整 Research Agent（工具编排、引用校验）仍在 P2。
- 存档是 JSONL 只写；运行时不读存档，复现靠 fixtures + 技术缓存。
- 公网部署尚未做（P3）；当前服务只绑定 `127.0.0.1`。
- M5–M9 展示/汇报/录屏/提交由下游团队负责，不属于本模块。

## 下一步

按 [PROJECT_PLAN.md](<PROJECT_PLAN.md>) 的 §3 执行：

1. **WP0 基线**：`configure_keys.py show` 确认真实通道；health `demo_mode=false`。
2. **WP1 真实检索**：API/MCP 探针、θ 标定、3 个真实展示用例、来源可点。
3. **WP2 查询接口**：填入三个 `examples/*.json` 的 question，跑 `/api/plan` / `run_example.py`。
4. **WP6 团队协作**：验证 `push.config.json` 指向当前仓库，完成首次 push；之后只填 commit；M5–M9 交给下游。
5. **WP3–WP5**：Skills 包 → Research Agent → 部署，按计划里程碑推进。
