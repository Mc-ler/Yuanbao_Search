# 元宝搜索 Research Agent · 项目规划（v2.1）

> 更新时间：2026-10-24 15:30（Asia/Shanghai）
> 当前基线：P0 已可运行；**73 个测试通过**（pytest 0.93s；含新增需求/示例/推送/LLM 诊断测试）。
> 本文件是项目唯一规划文档。历史调研、旧版最终报告与供应商 PDF 已删除，不保留备份；本文件与 `framework.html` 都位于仓库根目录。

## 0. 结论

1. 项目已从“设计阶段”进入“可运行 + 可协作”阶段：文字输入、API/MCP 双通道、确定性判定、三态 UI、SSE、73 测试。
2. **S1 已从“断言抽取”改为“需求拆分”**：研究问题 → 1–3 个可检索需求 → 直接接入查询构造；不再经过 Claim。
3. 引入**团队协作模块**：`scripts/git_push.py` 一次配置 repo，之后只填 commit 信息即可提交并推送 GitHub。
4. **M5–M9 展示/汇报/录屏/提交由下游团队负责，不属于本模块**；本模块只交付代码、查询接口、示例与推送工具。
5. 优先级：**P0 Live/查询接口（阻塞）> P1 Skills/团队协作 > P2 Agent > P3 Deploy**。赛事时间线保持不变。

---

## 1. 目标与现状

### 1.1 目标

| 层 | 目标 | 判据 |
|---|---|---|
| P0 · 可运行 MVP | 研究问题/说法 → 需求拆分 → 查询 → 检索 → 证据 → 报告 | 三态/研究问题可跑；来源可点；预算内 |
| P1 · Skills 包 | 9 个能力可独立调用 | 每个 Skill 有 `SKILL.md` + schema + 入口 + 测试 |
| P2 · Research Agent | LLM 编排 `verify_claim` / `research_topic` | 4 个任务；引用可追溯 |
| P3 · 部署 | 容器化研究服务 | `docker compose up`、远端冒烟 |
| 协作 | GitHub 自动推送 | 只填 commit 信息即可 push；不泄露本地密钥 |

### 1.2 当前状态

**已完成**

- 代码：`claimlab/`、`web/`、`config/`、`fixtures/`、`scripts/`、`tests/`、`examples/`。
- 73 个测试通过；覆盖归一化、分级、去重、R1–R5、预算、查询构造、安全、pipeline、Key/Bearer、provider/模型选择、需求拆分/示例/推送守卫、LLM 模型矩阵。
- Yuanbao Search：API + MCP 适配器；MCP 2.3 SDK + JSON-RPC fallback；统一 `SearchBatch`。
- Key：`claimlab/keys.py` 自动归一化单个 `Bearer`；API 与 MCP 共用。
- LLM：`config/llm_providers.json` 管理 `gpt` / `codex`（Toklens `/v1`），按 provider 配 Key、`/models` 自动选模型；本组实测 `gpt-4o/gpt-4.1` 全部 404，已切 `gpt-5.6-sol`。
- **S1 需求拆分**：`claimlab/skills/requirements.py`；研究问题 → `Requirement` → `plan_requirement_queries`。
- **查询接口**：`POST /api/plan`（无检索、无预算消耗）；`GET /api/examples`；`scripts/run_example.py`。
- **三个示例包**：`examples/q1_statistics_bulletin.json`、`q2_scenic_history.json`、`q3_vehicle_restriction.json`；q1 已填并跑通，q2/q3 待手动填。
- **GitHub 推送**：`scripts/git_push.py` + `push.config.example.json`；首次配置 repo/remote，后续只填 commit。
- UI、SSE、三态、来源卡、搜索关闭演示；框架图 [framework.html](<framework.html>)。

**待验证 / 待完成**

- 真实 API/MCP/LLM 探针已完成（API/MCP parity；LLM 选中 gpt-5.6-sol）；真实响应上的 θ 标定待做。
- 三个真实汇报问题填入 `question` 后，跑 `/api/plan` / `run_example.py` 检查查询质量。
- 3 个真实展示用例（成立/冲突/不足）——下游团队负责展示，本模块只提供查询与来源。
- P1 Skills 包、P2 Research Agent、P3 部署。
- 团队 GitHub 首次推送（`push.config.json` 已指向当前仓库；待试推）。

### 1.3 范围边界

- 只做文字输入；不做图片/OCR/视频。
- 不做持续盯梢、B 端后台、平台可信度打分、加权总分。
- S1 是需求拆分，不是断言抽取；需求可以不是可证伪命题（历史解释、政策查询）。
- 证据是检索摘要与链接，不做全文抓取，不用截图冒充证据。
- **M5–M9 展示/汇报/录屏/提交不在本模块**，由下游团队负责；本模块不排这些任务的人力。

---

## 2. 架构与模块职责

### 2.1 总流程

```text
研究问题 / 文字说法
  → 入口层（Web / API / CLI / example runner）
  → S1 需求拆分（Requirement，1–3 条）
  → S2 查询构造（plan_requirement_queries）
  → S3 检索网关（API / MCP，缓存/预算/审计）
  → S4–S8（去重/分级/匹配/判定/报告；研究问题走证据摘要）
  → 输出：查询计划 / 鉴定书 / 研究报告
```

### 2.2 模块职责

| 模块 | 职责 | 代码 | 状态 |
|---|---|---|---|
| 入口层 | 文字输入、SSE、报告、查询规划接口 | `claimlab/api.py`、`web/` | P0 完成 |
| S1 需求拆分 | 研究问题 → 1–3 个可检索 Requirement | `skills/requirements.py` | 新增，完成 |
| S2 查询构造 | Requirement → 精准/模糊 QueryPlan | `skills/query.py` | 已改造，完成 |
| S3 检索网关 | API/MCP、缓存、预算、审计 | `search/` | P0 完成 |
| S4–S8 | 去重/分级/匹配/判定/报告 | `skills/` | P0 完成 |
| 旧断言路径 | 兼容 `verify_claim` UI | `skills/extraction.py` | 保留为 legacy，不是 S1 |
| 查询接口 | `POST /api/plan`、`GET /api/examples` | `claimlab/api.py` | 新增，完成 |
| 示例 | 三个汇报问题 + 空 question | `examples/` | 新增，待填 |
| 团队协作 | GitHub 提交/推送 | `scripts/git_push.py` | 新增，待首次配置 |
| Key/Provider | Bearer、provider、模型选择 | `keys.py`、`llm/client.py` | P0 完成 |

### 2.3 两种执行模式

- `verify_claim`（legacy UI）：文字说法 → Claim → 查询 → 判定；用于既有三态演示。
- `research_topic`（新查询接口）：研究问题 → Requirement → 查询；不强制判定，适合统计口径、景区历史、市政政策三类汇报问题。
- 两者共用 S2–S3 与 Provider；Research Agent（P2）再在 S1 前加任务规划/工具选择。

### 2.4 数据契约

- **A · 任务**：`ResearchTask(text, mode, subject, city, constraints)`。
- **S1 · Requirement**：`requirement_id / text / field / subject / city / time_window / source_preference / rationale`。
- **S2 · QueryPlan**：`query / site / industry / freshness / precision / strategy`，并保留 `requirement_id`。
- **B/C**：既有验证单位与报告契约不变；legacy `verify_claim` 继续使用 Claim。

### 2.5 Key / 鉴权 / 模型

- Yuanbao：`.env` 存纯 Key；`bearer_auth_header()` 只拼一次。
- LLM：`config/llm_providers.json`；`gpt` / `codex`；`GPT_API_KEY` / `CODEX_API_KEY` / `TOKLENS_API_KEY`；`/models` 自动选模型。
- 健康接口只返回 provider、模型、Key 布尔，不返回 Key。

---

## 3. 落地方案（重点）

### 3.1 执行原则

1. **先真实，再扩展**：探针、示例查询、三例没有验证前，不投入 Agent/部署。
2. **S1 不再抽 Claim**：研究问题直接拆成 Requirement；查询构造不依赖断言抽取。
3. **判定不交给模型**：去重、分级、预算、引用校验由代码完成。
4. **一份数据多种视图**：查询计划、鉴定书、研究报告共用 S2–S3。
5. **预算硬闸**：单断言 4 次、单次 28 次、Agent 12 步、墙钟 90 秒；重试必须换策略。
6. **展示归下游**：M5–M9 由下游团队负责；本模块按时交付代码/接口/工具，不接展示排期。

### 3.2 工作包

#### WP0 · 基线确认（P0，30 分钟）

- `configure_keys.py show` 确认真实 Key/provider/model。
- 重启 `claimlab.api`；`/api/health` 的 `demo_mode=false`。
- `pytest -q` 保持 73 通过。
- 验收：health 真实；无 DEMO；测试通过。
- 依赖：本地 `.env` 已配置。

#### WP1 · 真实检索硬化（P0，今天）

- `probe_search.py --provider both`：8 条探针；API/MCP pages、version、content/pics、延迟、0 结果。
- `probe_llm.py`：`/models`、provider、选中模型、JSON probe。
- `calibrate_dedup.py`：真实 passage 的 θ 卡。
- 3 个真实展示用例（成立/冲突/不足）；A 级优先，来源可点；≤28 次。
- UI 三例；缓存预热；搜索关闭演示。
- 验收：3 例可点来源；1 分钟内可演示；无红线。
- 依赖：WP0。

#### WP2 · 需求拆分 + 查询接口 + 三个示例（P0，今天）

- S1：`skills/requirements.py`；LLM 拆分 + 关键词 fallback；1–3 条 Requirement。
- S2：`skills/query.py` 接受 Requirement；`plan_requirement_queries`；字段 `statistics_source`、`statistics_method`、`scenic_history`、`scenic_explanation`、`traffic_restriction`、`ev_license`、`municipal_notice`。
- 接口：`POST /api/plan`、`GET /api/examples`、`scripts/run_example.py`。
- 示例：三个 JSON，`question` 留空；用户手动填；`question_suggestion` 给参考。
- 验收：三条示例填入问题后，`/api/plan` 返回 1–3 个 Requirement 和定向查询；不跑检索也不报错。
- 依赖：无（可与 WP1 并行）。

#### WP3 · Skills 包（P1，1–2 天）

- 包格式：`skills/<name>/SKILL.md`、`schema.json`、`skill.py`、`tests/`。
- S1 改为需求拆分；S2–S9 打包；`skills/registry.py`；CLI `skills list/run`。
- pipeline 改用 registry；旧 Claim 路径若无用则标 legacy。
- 验收：9 个 Skill 独立调用；schema 校验；pipeline 回归通过；文档齐全。
- 依赖：WP2 的 Requirement 契约稳定。

#### WP4 · Research Agent（P2）

- Runtime：状态、工具表、步数/预算/无进展停机、trace。
- `research-planning` Skill；function calling + JSON fallback。
- `verify_claim` / `research_topic`；引用校验；Agent API/UI。
- 评测：3 verify + 1 research；引用覆盖、调用数、耗时。
- 验收：4 任务通过；引用可追溯；预算内；无红线。
- 依赖：WP3。

#### WP5 · 部署（P3）

- Dockerfile + compose；SQLite run store；SSE 重放；App Token；限流；日志脱敏。
- 远端一次完整 run；回滚；Runbook。
- 验收：compose 健康；远端 run；重启可查；日志无 Key。
- 依赖：WP4。

#### WP6 · 团队协作 / GitHub 推送（P1，已交付）

- `scripts/git_push.py`：首次 `--repo/--remote` 写 `push.config.json`；之后只填 commit title/body。
- 安全：`.env`、`cache/`、`archive/`、`state/`、`probe/`、`.Search/`、`push.config.json`、`.push.json` 禁止入库；凭据交给 Git Credential Manager/SSH。
- 配置样例：`push.config.example.json`；实际配置 `push.config.json`（gitignored）。
- 验收：用户提供 repo 后，首次推送成功；第二次只填 commit 信息即可 push。
- 依赖：用户提供 repo 路径/remote。

#### WP7 · 可选增强（P4）

- B 端“说法底稿”只读视图；A 级存证快照；Agent-as-MCP；定时研究。均在 P3 后。

#### 外部 · M5–M9（下游团队，不计入本模块）

- 录屏、海报、社媒、展示、提交、现场汇报。
- 本模块只提供可运行的查询接口、示例、真实来源与报告导出；下游团队按赛事时间线执行。

### 3.3 优先级与关键路径

```text
P0  WP0 基线 → WP1 真实检索/三例
P0  WP2 需求拆分/查询接口/示例（可与 WP1 并行）
P1  WP3 Skills 包
P1  WP6 GitHub 推送（已交付，等 repo 配置）
P2  WP4 Research Agent
P3  WP5 部署
P4  WP7 可选
外部 M5–M9 展示/汇报（下游）
```

**关键路径**：WP1/WP2 完成前不启动 WP3；WP3 的 Skill 契约稳定前不启动 WP4；WP4 的 Agent API 稳定前不启动 WP5。
**砍单顺序**：WP7 → WP5 的监控/B 端 → WP4 的 report UI → WP3 的文档细化 → WP1 的 UI 打磨。
**不砍**：真实检索、三个示例查询、来源可点、证据不足、预算、GitHub 推送。

### 3.4 里程碑

| ID | 时间 | 目标 | 验收 | 归属 |
|---|---|---|---|---|
| M0 | 10/24 14:30 | 真实通道确认 | health 真实；73 测试 | 本模块 |
| M1 | 10/24 15:30 | API/MCP/LLM 探针 | parity + `/models`；无 401/双 Bearer；LLM 矩阵选 gpt-5.6-sol | 本模块 |
| M2 | 10/24 16:45 | 查询接口 + 三示例 + 推送脚本 | `/api/plan` 可返回查询；push.config 可用 | 本模块 |
| M3 | 10/24 17:30 | θ 与三例 | θ 卡；3 个真实展示用例 | 本模块 |
| M4 | 10/24 18:00 | UI 三例/缓存 | 来源可点；≤28 次；搜索关闭 | 本模块 |
| M5 | 10/24 18:00 | 进度演示 | 1 分钟真实查询 | 下游 |
| M6 | 10/24 22:00 | 录屏/报告初稿 | 3 段草稿 | 下游 |
| M7 | 10/25 10:30 | 冻结 | 最终版本 | 下游 |
| M8 | 10/25 12:00 | 最终材料 | 录屏、海报、社媒 | 下游 |
| M9 | 10/25 13:30 / 14:00 / 23:59 | 提交与社媒 | 保底/最终提交；4 话题 | 下游 |
| M10 | 10/26 | P1 Skills 包 | 9 Skill + registry + 测试 | 本模块 |
| M11 | 10/28 | P2 Research Agent | 4 任务 + 引用 + 评测 | 本模块 |
| M12 | 10/30 | P3 部署 | Docker + 远端冒烟 | 本模块 |

> M5–M9 只保留在总时间线上，方便对齐；**不属于本模块交付**。本模块交付到 M4，随后进入 M10–M12。

### 3.5 验收与测试

| 层 | 验收 |
|---|---|
| 基线 | 73 测试通过；需求/示例/推送测试已覆盖 |
| 真实检索 | API/MCP 各 8 条探针；字段/延迟/错误有记录 |
| 需求拆分 | 三个领域各 1–3 个 Requirement；字段命中；不答题 |
| 查询接口 | `/api/plan` 返回 Requirement + QueryPlan；`run_example.py` 同结果 |
| 示例 | q1 已填；q2/q3 填入后可跑；不报 schema 错 |
| 来源 | A 级优先；链接可点；≤28 次 |
| 推送 | `.env` 不入库；首次配置后只填 commit；push 成功 |
| 红线 | 无时政/个人；无“水军/收钱/造假”定性；主语是内容 |

### 3.6 风险与降级

| 风险 | 处置 |
|---|---|
| API/MCP 字段差异 | parity 文档；API 默认，MCP 异常不阻塞 |
| LLM 模型不可用 | `/models` + preferred/default；model-not-found 换候选；仍失败走 heuristic |
| 示例问题太泛 | `question_suggestion` 给具体地区/年份；下游填入后再跑 |
| 需求拆错字段 | `query_fields` 期望值 + 人工检查；fallback 到 unknown |
| 真实三例凑不齐 | 先做成立/不足；冲突用价格口径；不硬编 |
| 推送误传密钥 | `.env`/cache/archive 黑名单；脚本拒绝；`push.config.json` / `.push.json` gitignored |
| 时间不足 | 按 §3.3 砍单；M5–M9 已交下游 |

---

## 4. 下游团队交付（M5–M9，不在本模块）

| 时间 | 事项 | 产出 |
|---|---|---|
| 10/24 18:00 | 进度演示 | 1 分钟真实查询 |
| 10/24 22:00 | 录屏初稿 | 3 段 |
| 10/25 10:30 | 冻结 | 最终版本 |
| 10/25 12:00 | 最终材料 | 录屏、海报、社媒 |
| 10/25 13:30 / 14:00 | 提交 | 作品页 |
| 10/25 23:59 | 社媒 | 4 话题链接 |

本模块只负责：查询接口、示例、真实来源、报告导出、GitHub 推送；展示脚本、录屏、海报、现场汇报由下游团队负责。

---

## 5. 当前结构与命令

```text
claimlab/            应用包（API、pipeline、keys、search、skills、llm、store）
web/                 UI / 判定口径页 / 样式
config/              domains / queries / lexicons / llm_providers.json
fixtures/            成立 / 冲突 / 证据不足（合成样例）
examples/            三个汇报问题（q1 已填，q2/q3 待填）
scripts/             configure_keys / probe_search / probe_llm / calibrate_dedup / run_example / git_push
tests/               73 个测试
PROJECT_PLAN.md      本文件
framework.html       当前框架图
push.config.example.json
README.md
```

```powershell
# 查询接口：填好 examples/*.json 的 question 后
./.Search/Scripts/python.exe scripts/run_example.py --example q1_statistics_bulletin
./.Search/Scripts/python.exe scripts/run_example.py --example q2_scenic_history --json
./.Search/Scripts/python.exe scripts/run_example.py --example q3_vehicle_restriction --heuristic

# HTTP 查询接口
# POST http://127.0.0.1:8000/api/plan  {"example_id":"q1_statistics_bulletin"}

# GitHub 首次配置；之后只填 commit
./.Search/Scripts/python.exe scripts/git_push.py --repo "D:\path\to\repo" --remote "git@github.com:org/repo.git"
./.Search/Scripts/python.exe scripts/git_push.py

# 真实检索/测试
./.Search/Scripts/python.exe scripts/probe_search.py --provider both
./.Search/Scripts/python.exe scripts/probe_llm.py
./.Search/Scripts/python.exe -m pytest -q
```

---

## 6. 变更记录

- **v2.1（2026-10-24）**：S1 改为需求拆分并直连查询构造；新增 `/api/plan`、三个示例与 runner；新增 GitHub 推送模块；M5–M9 明确划归下游团队；新增需求/示例/推送测试，73 passed。
- **v2.0（2026-10-24）**：基于已落地代码重写；62 测试基线；真实链路、Skills、Agent、部署四阶段；历史调研已删除。
- **v1.0（2026-10-23）**：早期框架与落地方案（已删除，不保留备份）。
