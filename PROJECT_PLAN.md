# 元宝搜索 Research Agent · 项目规划（v2.3）

> 更新时间：2026-10-24 22:10（Asia/Shanghai）
> 当前基线：P0 已可运行；**82 个测试通过**（pytest；含 cnt 字符串化、LLM 查询构造、回答引用、SQLite 索引、来源策略放松）。
> 本文件是项目唯一规划文档。历史调研、旧版最终报告与供应商 PDF 已删除，不保留备份；本文件与 `framework.html` 都位于仓库根目录。

## 0. 结论

1. 项目已从“设计阶段”进入“可运行 + 可协作”阶段：研究问题输入、SearchPro API（单通道）、需求拆分、真实来源、研究 UI、82 测试。
2. **S1 已从“断言抽取”改为“需求拆分”**：研究问题 → 1–3 个可检索需求 → 直接接入查询构造；不再经过 Claim。
3. **范围收窄**：主动只做国家统计、历史/文化遗产、市政三类；旧餐厅/价格/营业时间字段只保留给 legacy `verify_claim`。
4. **查询构造升级**：目标词、precise 优先、全局去重、A/B → B/C 回退 → 一次再查询；本轮不扩查询数量。
5. **本地端口已切到同一研究服务**：浏览器走 `/api/research`，终端走 `claimlab/research.py`，不再出现“UI 走旧 verify 路径、终端走新研究路径”的错位。
6. **MCP 已彻底删除**：运行时、健康检查、探针、前端均只走 SearchPro API；`mcp.py`、MCP 归一化函数、`requirements-mcp.txt` 均已移除，全仓无 MCP 引用。
7. **M5–M9 展示/汇报/录屏/提交由下游团队负责，不属于本模块**；本模块只交付代码、查询接口、示例、日志与推送工具。

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
- 82 个测试通过；覆盖归一化、分级、字段年龄策略、去重、R1–R5、预算、查询构造、安全、pipeline、Key/Bearer、provider/模型选择、需求拆分/示例/推送守卫、LLM 模型矩阵。
- Yuanbao Search：SearchPro API 单通道；统一 `SearchBatch`；MCP 已从活动链路移除。
- Key：`claimlab/keys.py` 自动归一化单个 `Bearer`；API 使用同一套 Key。
- LLM：`config/llm_providers.json` 管理 `gpt` / `codex`（Toklens `/v1`），按 provider 配 Key、`/models` 自动选模型；本组实测 `gpt-4o/gpt-4.1` 全部 404，已切 `gpt-5.6-sol`。
- **S1 需求拆分**：`claimlab/skills/requirements.py`；研究问题 → `Requirement` → `plan_requirement_queries`。
- **研究接口**：`POST /api/research`（真实检索）；`POST /api/plan`（只计划）；`GET /api/examples`；CLI `run_example_live.py`。
- **研究 UI**：q1/q2/q3 示例、计划面板、字段/来源结果卡、A/B/B-C 标签；旧 `verify_claim` 页面仅 legacy。
- **本地联调修复**：旧 8000 进程是 21:37 启动的旧代码（health 仍含 MCP），已重启为当前 API-only 进程；浏览器此前还走旧 `verify_claim`/fixture 路径，现已改走 `/api/research`。
- **来源策略/实时验证**：`skills/source_policy.py`、`claimlab/research.py`；A/B 优先，B/C 回退，一次再查询，4 次/字段上限。
- **运行日志**：`logs/README.md`、`claimlab/logging.py`、gateway/API/research/probe 日志；默认 INFO，5MB×5 轮转。
- **GitHub 推送**：`scripts/git_push.py` + `push.config.example.json`；首次配置 repo/remote，后续只填 commit。
- UI、API、CLI 共用 `claimlab/research.py`；框架图 [framework.html](<framework.html>)。

**待验证 / 待完成**

- **q2 49.2%**：达到当前 45% 验收线，但距更严的 50% 线还差 0.8 个点；要不要加一个官方站点定向查询，需你决定。
- **q2 解释字段**：当前问题不问“名称由来”，所以没有 `scenic_explanation`；要测解释字段需补问句。
- **q3 机动车限号**：当前问题只问电动自行车新规，所以没有 `traffic_restriction`；要测限号需补问句。
- **UI 验收**：需要你在浏览器用 q1/q2/q3 各跑一次，确认来源卡、A/B/C 标签和打印版式。
- **MCP 已彻底删除：`mcp.py`、MCP 归一化函数与相关测试均已移除。
- P1 Skills 包、P2 Research Agent、P3 部署。
- 团队 GitHub 首次推送（`push.config.json` 已指向当前仓库；待试推）。

### 1.3 范围边界

- 只做文字输入；不做图片/OCR/视频。
- 不做持续盯梢、B 端后台、平台可信度打分、加权总分。
- S1 是需求拆分，不是断言抽取；需求可以不是可证伪命题（历史解释、政策查询）。
- 主动范围只含国家统计、历史/文化遗产、市政；餐厅价格/营业时间/地址等旧字段只供 legacy `verify_claim`，不进入研究查询。
- 官方/统计/市政/历史优先 A/B；无 A/B 时允许 B/C 回退；仍不足才再查询；不接受无来源结论。
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
  → S3 检索网关（SearchPro API，缓存/预算/审计）
  → S4–S8（去重/分级/来源策略；来源闸门 A/B → B/C → 再查询）
  → 输出：查询计划 / 字段结果 / 来源卡
```

### 2.2 模块职责

| 模块 | 职责 | 代码 | 状态 |
|---|---|---|---|
| 入口层 | 研究问题输入、计划、真实检索结果、打印 | `claimlab/api.py`、`web/` | P0 完成 |
| S1 需求拆分 | 研究问题 → 1–3 个可检索 Requirement | `skills/requirements.py` | 完成 |
| S2 查询构造 | Requirement → 精准/模糊 QueryPlan | `skills/query.py` | 完成 |
| S3 检索网关 | SearchPro API、缓存、预算、审计 | `search/` | P0 完成 |
| S4–S8 | 去重/分级/来源策略/字段结果 | `skills/` | P0 完成 |
| 研究服务 | 需求→查询→真实检索→指标 | `claimlab/research.py` | 新增，完成 |
| 研究接口 | `POST /api/research`、`POST /api/plan` | `claimlab/api.py` | 新增，完成 |
| 旧断言路径 | 兼容 `verify_claim` 旧 UI/API | `skills/extraction.py`、`/api/runs` | legacy，非活动 UI |
| 示例 | q1/q2/q3；live 通过 | `examples/` | 完成 |
| 团队协作 | GitHub 提交/推送 | `scripts/git_push.py` | push.config 已指向当前仓库，待首次 push |
| Key/Provider | Bearer、provider、模型选择 | `keys.py`、`llm/client.py` | P0 完成 |

### 2.3 两种执行模式

- `research_topic`（活动 UI/API）：研究问题 → Requirement → API 查询 → A/B/B-C 来源；`/api/research` 与 CLI 共用 `claimlab/research.py`。
- `verify_claim`（legacy）：文字说法 → Claim → 查询 → 判定；只保留既有 `/api/runs`/三态演示兼容，不再是首页主路径。
- 两者共用 S2–S3 与 Provider；Research Agent（P2）再在 S1 前加任务规划/工具选择。

### 2.4 数据契约

- **A · 任务**：`ResearchTask(text, mode, subject, city, constraints)`。
- **S1 · Requirement**：`requirement_id / text / field / subject / city / time_window / source_preference / search_terms / rationale`。
- **S2 · QueryPlan**：`query / site / industry / freshness / precision / strategy`，并保留 `requirement_id`。
- **研究结果**：`field / tier / pages / relevant_pages / grades / executed / top_sources`。
- **B/C**：legacy `verify_claim` 继续使用 Claim；研究 UI 不依赖 Claim。

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
- `pytest -q` 保持 82 通过。
- 验收：health 真实；无 DEMO；测试通过。
- 依赖：本地 `.env` 已配置。

#### WP1 · 真实检索硬化（P0，今天）

- `probe_search.py --provider api`：8 条探针；API pages、version、content/pics、延迟、0 结果。
- `probe_llm.py`：`/models`、provider、选中模型、JSON probe。
- `calibrate_dedup.py`：真实 passage 的 θ 卡。
- 3 个真实研究问题（统计/历史/市政）；A/B 优先，来源可点；≤28 次。
- 研究 UI q1/q2/q3；计划/真实检索；跳过缓存；来源卡。
- 验收：3 例字段/来源可点；1 分钟内可演示；无红线。
- 依赖：WP0。

#### WP2 · 需求拆分 + 查询接口 + 三域构造（P0，已完成）

- S1：`skills/requirements.py`；LLM 拆分 + 关键词 fallback；1–3 条 Requirement；只输出三域字段。
- 字段：
  - 统计：`statistics_source`、`statistics_method`、`statistics_release`
  - 历史：`scenic_history`、`scenic_explanation`、`heritage_status`
  - 市政：`municipal_notice`、`traffic_restriction`、`ev_license`、`ev_restriction`、`municipal_effective`
- S2：`skills/query.py`；每个 Requirement 带 `search_terms`（年份/指标/数值/主体/文件类型）；去掉与 subject/模板重复的词。
- 初始查询 **precise 优先**（Industry/Site），再做目标词扩展；全局 `used` 去重，避免同字段重复查询。
- 无 A/B 时：先执行 1 条 B/C 回退；仍不足才执行 1 条不同策略再查询；每字段最多 4 次，不扩预算。
- 接口：`POST /api/plan` 返回 `queries`/`fallback_queries`/`requery_queries`；`GET /api/examples`；`scripts/run_example.py`/`run_example_live.py`。
- 示例：q1/q2/q3 均已填；q1 统计、q2 历史/世遗、q3 市政/电动车。
- 验收：q1 3/3 字段、q2 2/2 字段（3 条需求）、q3 3/3 字段；q1 79.7%、q2 49.2%、q3 81.4% 相关官方率；0 字段零结果；无重复查询。
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

- B 端“说法底稿”只读视图；A 级存证快照；Agent 接口；定时研究。均在 P3 后。

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
**查询数量留待后期**：当前每字段 2 条初始 + 1 条 B/C 回退 + 1 条再查询（上限 4）；本轮不扩查询数、不扩预算。待三域字段构造稳定、来源指标连续达标后，再单独评估是否把初始查询从 2 调到 3，或调整回退策略。

### 3.4 里程碑

| ID | 时间 | 目标 | 验收 | 归属 |
|---|---|---|---|---|
| M0 | 10/24 14:30 | 真实通道确认 | health 真实；82 测试 | 本模块 |
| M1 | 10/24 15:30 | API/LLM 探针 | API pages；`/models`；无 401/双 Bearer；LLM 矩阵选 gpt-5.6-sol | 本模块 |
| M2 | 10/24 17:45 | 三域范围 + 字段/目标词 + 回退/再查询 | 3/3 字段；无重复；`/api/plan` 三组查询 | 本模块 |
| M3 | 10/24 22:15 | 浏览器/API live 验证（跳过缓存） | q1 3/3 79.7%；q2 2/2（3 条需求）49.2%；q3 3/3 81.4%；0 零结果 | 本模块 |
| M4 | 10/24 22:20 | 研究 UI/API 端到端 | q1/q2/q3 可跑；来源可点；≤28 次；旧 8000 进程已重启 | 本模块 |
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
| 基线 | 82 测试通过；范围/字段/目标词/回退/来源策略已覆盖 |
| 真实检索 | API 8 条探针；字段/延迟/错误有记录 |
| 需求拆分 | 三域各 1–3 个 Requirement；字段命中；不答题；旧餐厅字段不进入研究查询 |
| 查询接口 | `/api/plan` 返回初始 + B/C 回退 + 再查询；`run_example.py` 同结果 |
| 示例 | q1/q2/q3 已填；live 跑通；q2 未问名称故无 explanation，q3 未问机动车故无 traffic |
| 来源 | A/B 优先；B/C 回退；四类查询/字段上限；q1 79.7%、q2 49.2%、q3 81.4% 相关官方率；验收线 q1≥70%、q2/q3≥45% |
| 零结果 | 三例 0 个字段零结果；单查询 0 页写入日志 |
| 日志 | `logs/README.md`；search/plan/live 日志可复现；不记 Key |
| 推送 | `.env` 不入库；首次配置后只填 commit；push 成功 |
| 红线 | 无时政/个人；无“水军/收钱/造假”定性；主语是内容 |

### 3.6 风险与降级

| 风险 | 处置 |
|---|---|
| API 字段差异 | API 归一化 + 8 条探针；字段差异只影响解析，不影响活动链路 |
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
examples/            三个汇报问题（q1/q2/q3 已填）
scripts/             configure_keys / probe_* / run_example / run_example_live / debug_search / analyze_results / git_push
tests/               82 个测试
logs/                logs/README.md + 本地 *.log（gitignored）
PROJECT_PLAN.md      本文件
framework.html       当前框架图
push.config.example.json
README.md
```

```powershell
# 查询接口：三例已填，默认走 LLM
./.Search/Scripts/python.exe scripts/run_example.py --example q1_statistics_bulletin --subject "国家统计局"
./.Search/Scripts/python.exe scripts/run_example.py --example q2_scenic_history
./.Search/Scripts/python.exe scripts/run_example.py --example q3_vehicle_restriction

# 真实来源验证（每字段最多 4 次，2 条初始 + 回退/再查询）
./.Search/Scripts/python.exe scripts/run_example_live.py --example q1_statistics_bulletin --subject "国家统计局" --json
./.Search/Scripts/python.exe scripts/run_example_live.py --example q2_scenic_history --json
./.Search/Scripts/python.exe scripts/run_example_live.py --example q3_vehicle_restriction --json

# HTTP 查询接口
# POST http://127.0.0.1:8000/api/plan  {"example_id":"q1_statistics_bulletin"}

# GitHub 首次配置；之后只填 commit
./.Search/Scripts/python.exe scripts/git_push.py --repo "D:\path\to\repo" --remote "git@github.com:org/repo.git"
./.Search/Scripts/python.exe scripts/git_push.py

# 真实检索/测试
./.Search/Scripts/python.exe scripts/probe_search.py --provider api
./.Search/Scripts/python.exe scripts/probe_llm.py
./.Search/Scripts/python.exe -m pytest -q
```

---

## 6. 项目指导：进度、疑点、待你验证与决策

### 6.1 已完成

| 项 | 状态 | 证据 |
|---|---|---|
| SearchPro API 单通道 + Key/Bearer | 完成 | health `provider=api`；MCP 不出现 |
| LLM provider/model | 完成 | `gpt / gpt-5.6-sol`；`/models` 选型 |
| S1 三域需求拆分 | 完成 | `statistics_*` / `scenic_*` / `heritage_status` / `municipal_*` / `ev_*` |
| 目标词 + precise 优先 + 全局去重 | 完成 | `/api/plan` 返回初始/回退/再查询三组；无重复 |
| A/B → B/C → 再查询 | 完成 | `source_policy.py`；每字段≤4 |
| 字段年龄策略 | 完成 | 历史 10 年、统计 2 年；q2 E→A/B |
| 研究接口/UI | 完成 | `/api/research`；q1/q2/q3 均成功 |
| 本地端口修复 | 完成 | 旧 21:37 进程已停；当前 8000 进程 API-only |
| 日志 | 完成 | `logs/README.md`；按天/按 run；不记 Key |
| 测试 | 完成 | 82 passed |

### 6.2 未解决 / 疑点

1. **q2 49.2%**：达到 45% 验收线，但距 50% 线 0.8 个点。q2 的两个 `scenic_history` 需求共用历史来源，`heritage_status` 的 A/B 较多但历史页仍有 D 级。
2. **字段与问题不匹配**：q2 没问“名称由来” → 无 `scenic_explanation`；q3 没问机动车限号 → 无 `traffic_restriction`。这不是拆分失败，是问题覆盖不足。
3. **q3 指标波动**：同一天不同 run 曾出现 50% 与 81.4%；LLM 措辞、缓存和排序会造成波动。需要固定问题后连续跑 3 次判断稳定性。
4. **UI 视觉验收**：静态页、API、来源卡字段已验证；尚未做人工浏览器视觉检查/打印预览。
5. **MCP 遗留代码**：活动链路已移除；`claimlab/search/mcp.py`、`test_normalize` 中 MCP 解析测试仍在仓库，是否删文件需决策。
6. **旧 verify_claim 路径**：`/api/runs`、旧 SSE/三态页面仍保留兼容，但首页已不用；是否删除/归档需决策。
7. **查询数量**：当前 2 条初始 + 回退/再查询≤4；扩量仍后置。
8. **GitHub 首次推送**：`push.config.json` 指向当前仓库；尚未在本轮试推。
9. **P1/P2/P3**：Skills 包、Research Agent 编排、容器化部署未开始。

### 6.3 需要你验证 / 决策的事项

| ID | 事项 | 验证方式 | 可选方案 |
|---|---|---|---|
| V1 | 浏览器端 q1/q2/q3 | 打开 `http://127.0.0.1:8000`，依次点三个示例 → 开始检索；看字段卡、A/B/C、来源链接、打印；F12 Network 确认 `/api/research` 200 | A. 通过；B. 指出布局/交互问题，我改 |
| V2 | 本地端口与终端一致性 | 终端跑 `run_example_live.py --example q1...`；浏览器跑 q1；比较字段数/来源域名；查 `logs/app-*.log` | A. 接受当前差异（LLM 措辞/缓存）；B. 要求固定温度/缓存键 |
| V3 | q2 官方率 | 连续跑 3 次 q2，记录 `relevant_official_rate`；看是否稳定 ≥45% | A. 接受 45% 线；B. 要求 ≥50%，加一个官方站点定向查询（不加查询总数） |
| D1 | q2 是否补“名称由来” | 在 q2 question 加“名称由来是什么”；看是否出现 `scenic_explanation` | A. 补问句并验收 3 字段；B. 保持当前 2 字段 |
| D2 | q3 是否补“机动车限号” | 在 q3 question 加“机动车尾号限行如何规定”；看是否出现 `traffic_restriction` | A. 补问句并验收 4 字段；B. 保持电动车 3 字段 |
| D3 | MCP 遗留文件 | 看 health 是否还有 mcp；`grep -R "McpSearchProvider"`；确认活动代码引用 | A. 只停用（现状）；B. 删除 `mcp.py`/相关测试/requirements-mcp |
| D4 | 旧 verify_claim 页面 | 访问 `/api/runs` 旧接口；确认是否还有下游依赖 | A. 保留 legacy；B. 删除旧 UI/接口，只留研究模式 |
| D5 | 查询数量扩量 | 看每字段 `executed` 次数；当前≤4；看来源率是否因 2 条初始不足 | A. 维持后置；B. 下轮把初始从 2 调到 3（需扩预算评估） |
| D6 | q3 指标波动 | 固定 q3 连续跑 3 次；记录 official rate/字段 | A. 接受波动并取中位数；B. 固定缓存/温度/查询模板 |
| D7 | GitHub 首次推送 | `git status` 确认无 `.env`/cache/archive；`git_push.py` 试推 | A. 现在推；B. 等最终材料再推 |
| D8 | 展示归属 | 确认 M5–M9 由下游负责；本模块只交查询/来源/日志 | A. 维持；B. 本模块补录屏/展示脚本（需另排期） |

> 建议先做 V1、V2、V3；V1 通过后再决定 D1/D2 是否补问句；D3/D4 可与最终清理一起做。

---

## 7. 变更记录

- **v2.4（2026-10-24）**：MCP 物理删除；cnt 字符串化（10/20/30/40/50）；预算 8/56/800；新增时间序列查询与 `scripts/broad_search.py`；LLM 构造请求字段（`build_queries_llm`，保留 subject/city 手动覆盖）；新增 SQLite 索引 `store/db.py` 与 `/api/db/*`；新增回答引用 `skills/answer.py`（带 [n] 引用 + 不编造 Prompt）；来源策略接受 B/C 为终态、判定 R5r 放松；修复固定示例干扰；82 passed。
- **v2.3（2026-10-24）**：本地 8000 旧进程重启；浏览器从旧 `verify_claim` 路径切到 `/api/research`；新增 `claimlab/research.py` 共用服务；MCP 从运行时/健康/探针/前端移除；前端改为简洁研究页；q1 79.7%、q2 49.2%、q3 81.4%；80 passed。
- **v2.2（2026-10-24）**：范围收窄到统计/历史/市政；新增目标词、precise 优先、全局去重、B/C 回退与一次再查询；新增 live 验证、字段年龄策略、运行日志；q1/q2/q3 live 字段覆盖 3/3；77 passed。
- **v2.1（2026-10-24）**：S1 改为需求拆分并直连查询构造；新增 `/api/plan`、三个示例与 runner；新增 GitHub 推送模块；M5–M9 明确划归下游团队；新增需求/示例/推送测试，73 passed。
- **v2.0（2026-10-24）**：基于已落地代码重写；62 测试基线；真实链路、Skills、Agent、部署四阶段；历史调研已删除。
- **v1.0（2026-10-23）**：早期框架与落地方案（已删除，不保留备份）。
