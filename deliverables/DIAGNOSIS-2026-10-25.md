# 万物皆可查 · 本地检索质量诊断与项目指导

- 日期：2026-10-25（Asia/Shanghai）
- 代码基线：`d11f8c0`（main；排查开始时工作区 clean）；README 标注 v4.2
- 本次改动：**未修改业务代码**；新增 `scripts/diagnose_connections.py` 与本文档
- 排查对象：`http://127.0.0.1:8000`（现有实例）与 `http://127.0.0.1:8010`（本次新建的干净对照实例）
- 结论一句话：**前后端连接是通的；"检索无结果 / 质量不高"主要不是 SearchPro 不通，而是 LLM 结构化调用被推理 token 吃满后静默降级、8000 实例配置与 `.env` 不一致、引用只取全局 3 条，以及 Site 参数写法错误叠加造成的。**

> **实施状态（2026-10-25 11:40）**：用户已确认 D1–D8。本文档中的 P0/P1 方案已落地，实际改动与验收数据见
> [IMPLEMENTATION-2026-10-25.md](IMPLEMENTATION-2026-10-25.md)。本文件保留为排查记录；第 5 节的"可选方案"已不再是待决项。

---

## 0. 一页结论

### 0.1 前后端连接：正常

| 检查 | 结果 | 证据 |
|---|---|---|
| 页面与静态资源 | 200 | `/` 8316 B、`/static/app.js` 43266 B、LOGO 62513 B |
| `/api/health` | 200，字段齐全 | `search_ready=true`、`llm_ready=true` |
| `POST /api/research` | 200，81.4 s，返回完整报告 | `run_id=research-20261025-103259-998c3a` |
| `POST /api/runs` + SSE | 200，事件流完整 | `run.started → split.done → … → run.done`，19.9 s |
| `GET /api/report/{id}?format=md` | 200 | 559 字符 Markdown |
| 参数校验 | 符合契约 | 多余字段 422、空文本 422、不存在的 run 404 |
| 同源/CORS | 无问题 | 前端全部使用相对路径；页面由同一 FastAPI 提供 |

**结论：传输层、路由、请求体、SSE、静态资源都正常。** 不需要在"前后端连不上"方向继续排查。

### 0.2 真正的问题（按影响排序）

| 编号 | 问题 | 级别 | 一句话证据 |
|---|---|---|---|
| R1 | 8000 实例实际生效配置与 `.env` 不一致 | P0 | health 显示 `deepseek.base_url=https://lax.toklens.ai/v1`、`settings.llm_model=gpt-5.6-sol`；`.env` 是 `api.deepseek.com/v1` / `deepseek-flash`；DeepSeek key 在 Toklens 返回 401 |
| R2 | DeepSeek V4.1 Flash 的 reasoning token 吃满 `max_tokens` | P0 | 同一 decompose 调用 `max_tokens=1200` 仅 **1/4** 成功；关闭思考后 **4/4** 成功 |
| R3 | LLM 失败被静默吞掉，降级为 heuristic/rule | P0 | `decompose_requirements`、`build_queries_llm`、`match_evidence` 均 `except Exception` 后无日志回退 |
| R4 | 引用只取全局前 3 条，且不代表各需求 | P1 | 10:14 统计研究中 220 条原始页面（含重复）有 **100 条**含 `41314`（含官方公报），但引用 `[3]` 是"财政主要统计指标解释"，模型只能回答"没有找到出处" |
| R5 | 相关性过滤是字面 `search_terms` 匹配 | P1 | 10:24 的 heuristic 计划 `search_terms=["由来"]`，80 条去重结果被判 **0 条相关** |
| R6 | `Site` 必须与索引 host 完全一致 | P1 | `Site=www.xa.gov.cn` → 20 条；`Site=xa.gov.cn` / `Site=gov.cn` → **0 条**，HTTP 200 无错误 |
| R7 | 来源排序不看"是否切题" | P1 | 3 个需求各自 top 6 里的前 3 条完全相同（`slfjq.mwr.gov.cn`、`ncha.gov.cn`、`wlj.nanjing.gov.cn`） |
| R8 | 一句话查证把 22 条证据一次性塞给 1200 token 的匹配调用 | P0（查证） | 22 条时 `completion_tokens=1200` 全是 reasoning，`content` 为空 → 全部 `unrelated` → R5 |
| R9 | 健康检查只看 key 是否存在 | P1 | 8000 的 LLM 全 401，但 UI 仍显示绿色"deepseek / deepseek-flash" |
| R10 | 其他：`plan_id` 只由文本决定、双实例共享预算/日志、归档增长、截图环境、测试临时目录 | P2 | 见第 3 节 |

### 0.3 修复前后的实测对比（同一批数据）

| 指标 | 现状 | 关闭 thinking 后 | 说明 |
|---|---|---|---|
| decompose 返回有效 JSON | 1/4（其余截断/空） | 4/4 | 同一问题、同一模型、`max_tokens=1200` |
| decompose 单次耗时 | 5.8–8.2 s | 1.5–1.8 s | 快 3–5 倍 |
| 回答阶段 `engine` | `rule`（JSON 截断/空） | `llm` | 3 条 claim，引用校验通过 |
| 22 条证据匹配 | 0 support / 22 unrelated | 16 support / 6 unrelated | 同一批 22 个页面、同一断言 |
| 查证结论 | `R5 insufficient` | 具备 R2b `established` 条件 | 16 条 support，含 A/B 级 |
| 8000 的 LLM 调用 | 401（Toklens 地址） | — | 与 thinking 无关，是 R1 配置问题 |

### 0.4 建议先做的三件事

1. **重启 8000 的旧进程**（或先用 8010），让 `health` 的 `deepseek.base_url` 回到 `https://api.deepseek.com/v1`。
2. **对所有结构化 JSON 任务关闭 thinking**（`thinking: {"type": "disabled"}`），并保留 4096 的 answer 输出预算。
3. **把引用从全局 3 条改为"每需求 2–3 条、全局上限 8–9 条"**，并优先选命中需求关键词/数值的页面。

---

## 1. 项目现状与已解决内容

### 1.1 架构与请求链路

深度研究：

```
浏览器 web/app.js
  └─ POST /api/research {text}
       └─ claimlab/api.py:288 research()
            ├─ build_research_plan()            planning.py:68
            │    ├─ decompose_requirements()    skills/requirements.py:247   [LLM]
            │    └─ build_queries_llm()         skills/query.py:443          [LLM]
            ├─ run_research()                   research.py:174
            │    ├─ SearchGateway.search()      search/gateway.py:107
            │    │    └─ ApiSearchProvider      search/api.py:43 → POST /SearchPro
            │    ├─ cluster_pages()             skills/dedup.py:79
            │    ├─ is_relevant()/source_tier() skills/source_policy.py:14/22
            │    ├─ _top_sources()              research.py:55
            │    └─ build_answer()             skills/answer.py:345          [LLM]
            └─ JSON {report, metrics, answer, source_ledger, …}
  └─ renderReport() / researchReport()          app.js:668
```

一句话查证：

```
POST /api/runs {text} → claimlab/api.py:350
  └─ Pipeline.run()                    pipeline.py:141
       ├─ extract_claims()             skills/extraction.py              [LLM]
       ├─ plan_queries()               skills/query.py:108
       ├─ gateway.search()             search/gateway.py:107
       ├─ cluster_pages()              skills/dedup.py:79
       ├─ match_evidence()             skills/matching.py:190            [LLM]
       └─ judge_unit()                 skills/judging.py:257（R1–R5 确定性）
  └─ SSE /api/runs/{id}/events → app.js:554
```

### 1.2 已完成的能力（按版本）

| 版本 | 内容 |
|---|---|
| v3.0 | 深度研究/一句话查证双板块；`plan_id`；全局去重与来源分册；截图/vision；引用校验；R1–R5 UI；预算 4/28/400 |
| v3.1 | DeepSeek provider；key 隔离；重试/超时；`test_deepseek.py`；`configure_keys` |
| v3.2 | 修复 configure_keys 卡住；`restart_api.ps1`；研究并发/超时；前端 300 s 超时与连接诊断 |
| v3.5–v3.6 | 品牌/LOGO；极简 LLM 风格；动态背景；搜索框自适应 |
| v3.7 | 通用 Claim 抽取；question_not_claim；5 查询/需求；研究独立预算；内容节选 |
| v3.8 | 无结果明确话术；时间遍历；公开页正文抓取与降级 |
| v4.0 | LOGO-2；问句改写/多断言拆分/汇总；unknown 回退 general_fact |
| v4.1 | DeepSeek 散文答案兼容；answer `max_tokens=2400`（当前代码为 4096） |
| v4.2 | 时间归一化/时间优先排序；as-of/时效；claim–quote 校验；report 时间线 |

### 1.3 当前可运行性

- 依赖环境：`.Search` 虚拟环境，Python 3.13.5。
- 搜索：`SearchPro` 标准版（`Version=standard`），基线查询稳定返回 20 条。
- LLM：DeepSeek 官方 `/models` 返回 `deepseek-flash`、`deepseek-v4-pro`；key 在 `api.deepseek.com` 可用。
- 数据与状态：`state/platform.db` 为空库（0 runs）；`archive/` 49 个文件 82.4 MB；`cache/search` 237 个文件 56.1 MB；`logs/app-20261025.log` 0.9 MB。
- 当日预算：`state/budget-2026-10-25.json` 已用 288/400。

### 1.4 测试与仓库状态

- README 写"136 个测试通过"。
- 本次在 DSH 沙箱内运行：**105 passed，31 errors**。
- 31 个 error 全部发生在 pytest 的 `tmp_path` fixture setup，报错为
  `PermissionError: [WinError 5] ...\Temp\dsh-6JBWOa\pytest-of-Lenovo`。
- 这不是测试代码失败，是当前沙箱临时目录不可列目录。**需要在普通终端复跑确认 136 passed**（见 V5）。

---

## 2. 前后端链路排查（逐段）

### 2.1 浏览器 → API

| 前端调用 | 位置 | 后端路由 | 请求模型 | 实测 |
|---|---|---|---|---|
| `GET /api/health` | app.js:288 | api.py:158 | — | 200 |
| `POST /api/research {text}` | app.js:424 | api.py:288 | `ResearchRequest` | 200 |
| `POST /api/runs {text}` | app.js:446 | api.py:350 | `RunRequest` | 200 |
| `GET /api/runs/{id}/events` | app.js:554 | api.py:417 | — | 200，SSE 正常 |
| `GET /api/runs/{id}` | app.js:640 | api.py:404 | — | 200 |
| `GET /api/report/{id}?format=md` | — | api.py:441 | — | 200 |
| `POST /api/config/llm` | app.js:791 | api.py:184 | `LLMConfigRequest` | 未实测（会写 `.env`，避免污染） |
| `POST /api/config/search` | app.js:814 | api.py:217 | `SearchConfigRequest` | 未实测（同上） |
| `POST /api/config/screenshots` | app.js:836 | api.py:246 | `ScreenshotConfigRequest` | 未实测（同上） |

前端使用相对路径、同源，不存在 CORS。页面、JS、CSS、LOGO 均 200。

### 2.2 参数与配置一致性

| 项 | `.env` / 配置 | 8000 实例 health | 8010 实例 health | 判断 |
|---|---|---|---|---|
| `SEARCH_PROVIDER` | api | api | api | 一致 |
| `SEARCH_BASE_URL` | `https://api.wsa.cloud.tencent.com` | 同 | 同 | 一致 |
| `LLM_PROVIDER` | deepseek | deepseek | deepseek | 一致 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | **`https://lax.toklens.ai/v1`** | `https://api.deepseek.com/v1` | **8000 不一致** |
| `LLM_MODEL` | `deepseek-flash` | **`gpt-5.6-sol`** | `deepseek-flash` | **8000 不一致** |
| `llm.model`（解析后） | — | deepseek-flash | deepseek-flash | 解析回退掩盖了配置错误 |
| DeepSeek key | 35 字符 | 35 字符，但发往 Toklens → **401** | 35 字符，发往 DeepSeek → 200 | 8000 不可用 |
| GPT/Codex key | Toklens 67 字符 | `key_present=true` | 同 | key 已 `API_KEY_DISABLED`，健康检查仍显示存在 |

**为什么 8000 会这样（高置信推断）**：

- 日志有两次 `app.start`：10:18:10 与 10:23:47；`.env` 的修改时间是 10:23:22。
- 10:23:47 的后启动进程很可能因 8000 已被 10:18:10 的旧进程占用而绑定失败退出（我在 8010→8000 的尝试中复现了同样的
  `[Errno 10048] error while attempting to bind`）。因此现在服务 8000 的仍是 10:18:10 的旧进程，它加载的是修改前的 `.env`。
- 另一种可能是启动 shell 里有 `DEEPSEEK_BASE_URL` / `LLM_MODEL` 进程环境变量，`load_env_file` 的 `setdefault` 不会覆盖它们（config.py:37）。
- 两者都指向同一处理：**确认 8000 的 PID/启动方式，干净重启并核对 health**（V1/V2、D1）。

### 2.3 SearchPro 请求参数实测

请求体由 `SearchRequest.to_api_body()`（contracts.py:101）生成：`Query`、`Cnt`（字符串）、`Mode`、可选 `Site`/`Industry`/`Freshness`。

| 用例 | 结果 | 结论 |
|---|---|---|
| `Query=西安城墙 历史沿革` | 20 条 | 基线正常 |
| `Site=www.xa.gov.cn` + `Query=西安城墙` | 20 条，全部 `www.xa.gov.cn` | Site 精确 host 有效 |
| `Site=xa.gov.cn` | **0 条** | apex 静默失败 |
| `Site=gov.cn` | **0 条** | 不是内容 host，必失败 |
| `Site=stats.gov.cn` / `www.stats.gov.cn` | 0 / 20 | 同上 |
| `Site=163.com`（官方文档示例） | 4 条 | 精确 host 可用 |
| `Query=site:stats.gov.cn 西安城墙` | 20 条，混合域名 | `site:` 运算符不被识别，当普通文本 |
| `Industry=gov/acad/news` | 结果会变，但同一查询下三者可能完全相同（Jaccard=1.0） | 参数生效但过滤很弱 |
| `Freshness=y1` / `d30` | 与 baseline 交集 0 | 生效 |
| `Mode=1` | 0 条（通用查询） | VR 垂类，通用查询不该用 |
| `Mode=2` | 与 Mode 0 完全相同 | 混合结果对本查询无差异 |
| `Cnt=20`（整数） | 20 条 | 整数也被接受，README "必须字符串"已过时 |

归档统计：`archive/*.jsonl` 共 369 条 search 记录，45 条 0 结果（12.2%），**45 条全部带 `Site`**；0 结果响应只有 `RequestId/Query/Version`，没有 `Pages`，也没有 `Msg`。

### 2.4 LLM 请求参数实测

`OpenAICompatLLM.json()`（llm/client.py:258）按任务设置：

| 任务 | `max_tokens` | 实测 |
|---|---|---|
| `decompose_requirements` | 1200 | 4 次中 1 次有效；其余 reasoning 1000–1200，content 0–549，JSON 截断 |
| `build_queries` | 1200 | 同类风险 |
| `match_evidence` | 1200 | 22 条证据时 reasoning=1200、content=0 |
| `answer` | 4096 | 一次 reasoning=3850 + content=407，`finish_reason=length`，JSON 截断 |
| `advisory` | 1200 | 单条可完成 |

`response_format={"type":"json_object"}` 已设置，但 **JSON mode 不能阻止 reasoning 占用 completion 预算**。`finish_reason` 没有写入日志，也没有在应用层判断。

### 2.5 接口返回与错误

| 场景 | 实测 | 评价 |
|---|---|---|
| 多余字段 `subject` | 422 `extra_forbidden` | 符合 README |
| 空 `text` | 422 `string_too_short` | 符合 |
| 不存在的 run | 404 `run not found` | 符合 |
| SearchPro 0 结果 | HTTP 200，无 `Pages` 键 | 应用视为成功，只记 WARNING，不区分"查询无命中"与"参数错误" |
| LLM 401（8000） | Search 正常；plan 退 heuristic；answer 退 rule；UI 仍绿色 | **错误不暴露** |
| LLM `finish_reason=length` | content 空/截断；非 answer 任务抛"model did not return a JSON object"；answer 任务可能把截断 JSON 当文本 | **错误不暴露** |
| LLM 429/5xx | 客户端重试 3 次后抛错 | 有重试，但最终仍静默降级 |
| 503/504 | 代码存在（api.py:291/315），本次未触发 | 未验证 |
| SSE | 事件名、顺序、`run.done` 正常 | 符合前端监听 |

### 2.6 日志核对

- 日志里 **没有 ERROR 级**记录，只有 WARNING。
- 10:33:31 / 10:33:56：
  `answer.llm_error LLMError: model did not return a JSON object`
  `answer.compact_error LLMError: model did not return a JSON object`
- 09:54 / 10:12：`answer.no_valid_citation sources=1`。
- **没有** decompose / build_queries / match_evidence 的失败日志——这些异常被 `except Exception` 静默吞掉：
  - requirements.py:267
  - query.py:467
  - matching.py:212
- `search.zero` 只记录 query/pages/latency，不记录 `RequestId`、`Version`、请求参数、`Msg`，无法和腾讯侧对账。
- 8000 与 8010 两个进程写同一个 `logs/app-20261025.log`，存在轮转/交错风险。

### 2.7 配置与状态隔离

- `Sandbox` 每个进程持有自己的 `PlanStore`、`RunStore`、`SearchGateway`；8000 与 8010 的计划/run 不共享。
- 但 `state/budget-YYYY-MM-DD.json` 与 `logs/app-*.log` 是共享文件；并发写会丢计数/交错日志。
- `plan_id` 由 `make_id("plan", text, PROMPT_VERSION)` 生成（planning.py:120），**只与文本和版本有关**。
  同一个问题的 heuristic 计划与 LLM 计划会得到同一个 `plan_id`（实测 `plan-be8b8633e1` 两次分别对应 heuristic 和 llm）。
  UI 目前不传 `plan_id`，所以暂不影响主路径，但 `/api/plan` 预览与 `/api/research` 复用在语义上不可靠。

### 2.8 链路结论

- **连通性正常**。
- **参数层**：SearchPro 的 `Site` 语义与项目假设不一致；LLM 的 `max_tokens` 与推理模型不匹配。
- **配置层**：8000 实例与 `.env` 不一致，且 health/UI 检测不到。
- **错误处理层**：LLM 失败被静默降级，日志不足以定位。
- **质量层**：引用上限、排序和相关性过滤把"已经检索到的正确证据"丢掉了。

---

## 3. 根因分析

### R1（P0）8000 实例运行的是旧配置

- **现象**：`/api/plan` 929 ms 返回 `method=heuristic`，1 条需求，`focus`=整句话，`search_terms=["由来"]`。
- **时间线（推断链）**：

| 时间 | 事件 | 含义 |
|---|---|---|
| 10:12:46 | `config.llm` 保存 | `.env` 被写过一次 |
| 10:14:00 | `app.start` | 该进程 LLM 可用（10:14–10:15 研究 `engine=llm`） |
| 10:18:10 | `app.start` | 当前 8000 的疑似持有者，加载了 Toklens/gpt 配置 |
| 10:23:22 | `.env` 修改时间 | 有人把配置改回 `api.deepseek.com` / `deepseek-flash` |
| 10:23:47 | `app.start` | 很可能因 10048 绑定失败退出（旧进程仍占 8000） |
| 10:24:11 | `research.start` | 命中旧进程 → 401 → heuristic → 0 相关 |

- **证据**：health `deepseek.base_url=https://lax.toklens.ai/v1`、`settings.llm_model=gpt-5.6-sol`；`.env` 为 `api.deepseek.com/v1` / `deepseek-flash`；DeepSeek key 在 Toklens 返回 `401 INVALID_API_KEY`。
- **影响**：8000 上所有 LLM 调用必失败；plan 必 heuristic；answer/match 必降级。用户看到的"无结果"是确定性的。
- **代码位置**：config.py:24（`setdefault`）、runtime.py:102、api.py:158（health 只报 key 是否存在）。
- **附带的配置污染风险**：前端 `saveLlm()`（app.js:780-788）每次保存都会把预填的 `llmBase` 一起提交；而 `llmBase` 又来自
  `/api/health` 的 `current.base_url`（app.js:338）。如果 health 已经是 Toklens 地址，用户点一次"保存"就会把错误地址写进 `.env`，
  让临时问题变成持久问题。
- **修复方向**：干净重启；health 增加 live 探测或至少比对 `.env`；UI 显示实际 base_url/model，并在保存前做 host 校验。

### R2（P0）推理 token 吃满 `max_tokens`

- **现象**：LLM 返回空 content 或截断 JSON；`finish_reason=length`。
- **证据**：
  - decompose `max_tokens=1200`：1/4 有效；`thinking disabled`：4/4 有效，1.5–1.8 s。
  - match 22 条、`max_tokens=1200`：reasoning=1200，content=0。
  - answer `max_tokens=4096`：reasoning=3850，content=407，JSON 截断。
  - 同一 answer 在 `thinking disabled` 下：约 600–900 tokens、JSON 有效、`engine=llm`、3 claims 全部通过 quote 校验。
- **代码位置**：llm/client.py:294-300（`max_tokens` 硬编码 4096/1200）、llm/client.py:88（`_coerce_content`）。
- **影响**：随机性"无结果/质量差"；同一问题多次运行结果不一致；重试只会更慢。
- **修复方向**：结构化任务关闭 thinking；answer 保留 4096–8192；非 answer 2048；记录 `finish_reason`、`reasoning_tokens`。

### R3（P0）静默降级

- **现象**：LLM 失败后 UI 只看到"没有结果"或"规则摘要"，看不到失败原因。
- **证据**：requirements.py:267、query.py:467、matching.py:212 都是 `except Exception: 回退`，无日志；answer.py:389 只记 warning，但 API 响应没有 `error` 字段。
- **影响**：把"LLM 不可用"伪装成"没有检索到"；用户无法判断是搜索问题还是模型问题。
- **修复方向**：所有降级点记录 `task/model/finish_reason/http_status`；API 返回 `degraded`/`engine`/`fallback_reason`；UI 显式提示。

### R4（P1）引用全局只取 3 条

- **现象**：源分册有 18 条（3 需求 × 6），回答只看到 3 条；同一条 3 引用在 3 个需求里重复。
- **证据**：
  - `build_citations(rows, time_sensitive=time_sensitive)` 使用默认 `limit=3`（answer.py:47、:357）。
  - 清洁实例 10:33 运行：`citations=3`，3 个需求的 top 3 完全相同。
  - 10:14 统计运行：220 条结果 **100 条**含 `41314`，含官方公报；但回答的 `[3]` 是"财政主要统计指标解释"，模型据此说"没有找到出处"。
- **影响**：回答与源分册脱节；"检索到了但没引用"；用户感觉质量低。
- **修复方向**：每需求 2–3 条、全局 8–9 条；优先选命中需求关键词/数值的页面；引用去重后保证每个需求至少 1 条。

### R5（P1）相关性过滤是字面匹配

- **现象**：80 条去重结果被判 0 条相关；或 165 条里 154 条"相关"（过宽）。
- **证据**：
  - `is_relevant()`（source_policy.py:14）要求 `search_terms` 中任意一个字符串出现在标题+摘要+正文。
  - heuristic 计划对长句只提取到 `["由来"]` → 0/80。
  - LLM 计划给出 `["西安城墙","明代城墙",…]` → 154/165，几乎全过。
- **影响**：heuristic 路径必 0；LLM 路径几乎没有精度过滤。
- **修复方向**：0 条时放宽到 focus/任一词；排序加入"需求词命中数 + 数值命中"；必要时 LLM rerank 前 30 条。

### R6（P1）Site 写法错误

- **现象**：带 Site 的查询 0 结果；LLM 生成 `site=gov.cn`、`site=stats.gov.cn` 全部浪费。
- **证据**：45/45 归档 0 结果均带 Site；`www.xa.gov.cn` 20 条、`xa.gov.cn` 0 条；`gov.cn` 0 条；`site:` 运算符被当普通文本。
- **影响**：每个需求 5 条查询里可能浪费 1 条；query 数看似够，有效覆盖不足。
- **修复方向**：LLM 查询默认不生成 Site；如要 Site，使用精确 host 白名单；0 结果自动无 Site 重试一次。

### R7（P1）来源排序不看"是否切题"

- **现象**：3 个需求的前 3 条来源完全相同，其中一条是南京城墙申遗，与西安城墙城砖无关。
- **证据**：10:33 运行 ledger 的 3 个需求 top 3 均为 `slfjq.mwr.gov.cn`、`ncha.gov.cn`、`wlj.nanjing.gov.cn`。
- **原因**：`_rank()`（research.py:44）按 grade → score → 日期排序，没有需求词/主张词命中；`_top_sources` 只按 grade 过滤。
- **影响**：权威但离题；回答被无关 A 级页带偏。
- **修复方向**：排序键加入 `term_hits`（focus + search_terms + 数值）和标题命中；同需求内做域名/簇多样性。

### R8（P0，查证）匹配一次性 22 条

- **现象**：一句话查证 22 条证据全部 `unrelated`，R5。
- **证据**：
  - 22 条、1200 tokens：reasoning=1200、content=0。
  - 同一 22 条、关闭 thinking：22 个 match，16 support，含
    "现存城墙建于明洪武七年到十一年(1374-1378)"。
- **影响**：查证模式在 LLM 失败时必然"无法确定"，即使证据明确。
- **修复方向**：关闭 thinking + 每批 8–10 条；或提高 max_tokens 到 8192；heuristic 对非传统字段应给出"未判定"而不是"无关"。

### R9（P1）健康检查与 UI 状态过浅

- **现象**：8000 的 LLM 全 401，UI 仍绿色；截图 Chrome 实际失败，health 仍显示 `chrome=true`、`enabled=true`。
- **原因**：health 只检查 `key_present`、`chrome` 路径、`websockets` 是否安装，不做 live probe。
- **影响**：用户误判"已配置=可用"。
- **修复方向**：health 增加最近一次 LLM 成功/失败时间、last_error、last_finish_reason；UI 区分"已配置/最近失败"。

### R10（P2）其他

| 项 | 证据 | 影响 |
|---|---|---|
| `plan_id` 只由文本+版本决定 | 同一问题 heuristic 与 llm 计划同为 `plan-be8b8633e1` | 计划预览/复用语义不可靠 |
| `run_research` 返回 `plan_reused: True` 硬编码 | research.py:483；API 会覆盖 | CLI 结果字段错误 |
| 双实例共享预算/日志 | 8000 与 8010 写同一 `budget-*.json`、`app-*.log` | 计数丢失/日志交错 |
| 归档/缓存无保留策略 | archive 82.4 MB、cache 56.1 MB（一天） | 磁盘持续增长 |
| `Site` 0 结果不缓存 | gateway.py:182 只在有 pages 时缓存 | 失败查询反复消耗预算 |
| 截图在本会话不可用 | `chrome exited before DevTools started`；10:04/10:08 曾成功 | 证据图缺失；环境相关 |
| 测试临时目录 | 31 个 setup error | 无法在沙箱内确认 136 |
| README 与实现偏差 | Cnt 字符串、answer max_tokens 2400、Site 无 host 说明、plan 流程 | 误导排障 |

---

## 4. 未解决的难点与疑点

| 编号 | 疑点 | 目前掌握 | 还需要什么 |
|---|---|---|---|
| U1 | 8000 的旧进程是谁、何时启动 | PID 37668 对当前会话不可见；health 与 `.env` 不一致 | 你在自己的终端执行 `Get-Process -Id 37668`，或直接重启 |
| U2 | 启动 shell 是否有环境变量覆盖 | 本次会话的 shell 没有；旧进程无法读环境 | `Get-ChildItem Env: \| ? Name -match 'DEEPSEEK\|LLM_\|TOKLENS'`（V2） |
| U3 | Toklens key 是否还要保留 | `/models` 返回 `API_KEY_DISABLED` | 你决定删除 GPT/Codex 或换新 key |
| U4 | 截图失败是代码还是沙箱 | 本会话 Chrome 直接启动也无输出；正常实例 10:04 曾成功 2–3 张 | 在普通终端跑一次 capture（V4） |
| U5 | 136 tests 是否真的全过 | 沙箱内 105+31 setup error | 普通终端 `pytest -q`（V5） |
| U6 | SearchPro `score` 的取值范围 | 文档写 0–1，实测 4.4；排序/阈值不能直接按 0–1 假设 | 用 20 条样本统计分布，决定阈值 |
| U7 | 查询密度与质量的平衡 | 15 条/3 需求，A/B 33.8%；D 级 73 条 | 需要一轮基准题集对比（D8） |
| U8 | 是否保留 `/api/plan` 预览 | UI 从不调用；`plan_id` 有碰撞 | 你决定保留/删除/让 UI 调用 |

### 4.1 本次未验证（避免误判）

| 项 | 原因 | 建议 |
|---|---|---|
| `/api/config/*` 的写入往返 | 会改写 `.env`，本次避免污染；只读取了 health | 在备份 `.env` 后单独测试（V3/D10） |
| 503（未配置 Search）/ 504（研究超时） | 当前 key 存在，未构造超时 | 用临时实例/临时 env 验证 |
| 浏览器实际渲染与移动端布局 | 本会话无 GUI 截图能力 | 你打开 8000/8010 目视确认 |
| 每日预算 400 打满后的行为 | 当前 288/400，未打满 | 需要时用临时 state 目录验证 |
| 公网部署/鉴权/限流 | 超出本次本地排查范围 | 上线前单独做 |
| 136 全量测试 | 沙箱临时目录 ACL 阻止 31 个 setup | 普通终端复跑（V5） |

---

## 5. 项目指导：需要你验证和决策的事项

> 下面每一项都给出：**为什么需要你定 / 怎么验证 / 可选方案 / 推荐 / 风险**。
> 未确认前我不改代码、不写 `.env`、不动你的 8000 进程。

### 5.1 需要你验证的事项（V1–V6）

#### V1. 确认 8000 端口进程的归属与启动方式

- **为什么**：当前 8000 的 health 与 `.env` 不一致；需要确认是"旧进程未替换"还是"环境变量覆盖"。
- **验证方式**（在你自己的终端，不要用本会话的沙箱终端）：

```powershell
netstat -ano | findstr :8000
# 取最后一列 PID，然后
Get-Process -Id <PID> | Select-Object Id, ProcessName, StartTime, Path
Get-CimInstance Win32_Process -Filter "ProcessId=<PID>" | Select-Object CommandLine
```

- **预期/判读**：
  - 如果 `StartTime` 早于 `.env` 的修改时间（10:23:22），就是旧进程。
  - 如果命令行不是 `python -m claimlab.api`，先不要杀，确认是谁。
- **告诉我的信息**：PID、启动时间、命令行、你平时怎么启动服务（脚本/IDE/终端）。

#### V2. 确认启动 shell 的环境变量

- **为什么**：`load_env_file()` 使用 `os.environ.setdefault`，进程环境变量优先于 `.env`；这能解释 `LLM_MODEL=gpt-5.6-sol`。
- **验证方式**：

```powershell
Get-ChildItem Env: | Where-Object { $_.Name -match 'DEEPSEEK|LLM_|TOKLENS|GPT_|CODEX|SEARCH_' } |
  Sort-Object Name | Format-Table -AutoSize
```

- **预期**：只应看到你明确设置的值；如果出现 `DEEPSEEK_BASE_URL=https://lax.toklens.ai/v1` 或 `LLM_MODEL=gpt-5.6-sol`，就是它。
- **处理**：在启动服务的同一个窗口里 `Remove-Item Env:DEEPSEEK_BASE_URL`（以及 `LLM_MODEL`），或在新窗口启动。

#### V3. 确认 DeepSeek / Toklens 账号状态

- **为什么**：8000 的 DeepSeek key 被发往 Toklens，返回 401；Toklens key 本身返回 `API_KEY_DISABLED`。需要决定是否保留 GPT/Codex 供应商。
- **验证方式**：

```powershell
./.Search/Scripts/python.exe scripts/test_deepseek.py
./.Search/Scripts/python.exe scripts/diagnose_connections.py --base-url http://127.0.0.1:8000
```

- **预期**：
  - `test_deepseek.py` 输出 `OK model=deepseek-flash`。
  - `diagnose_connections.py` 的 `models @ server(health)` 若为 401，说明服务端地址错；`models @ resolved` 200 说明本机 `.env` 正确。
- **决策含义**：如果 GPT/Codex 不再使用，应从 `.env`/`llm_providers.json` 删除，避免 health 显示"有 key"。

#### V4. 在普通终端验证截图能力

- **为什么**：本会话 `capture()` 全部失败 `chrome exited before DevTools started`；10:04/10:08 的正常实例曾成功 2–3 张。需要确认是沙箱还是代码。
- **验证方式**（普通 PowerShell，不在 DSH 沙箱）：

```powershell
& 'C:\Program Files\Google\Chrome\Application\chrome.exe' --headless=new --disable-gpu --dump-dom about:blank
./.Search/Scripts/python.exe -c "import asyncio,sys; sys.path.insert(0,'.'); from claimlab.config import load_settings; from claimlab.evidence import ScreenshotCapturer; s=load_settings(); c=ScreenshotCapturer(s); print('chrome',c.chrome,'enabled',c.enabled,'reason',c.reason); shot=asyncio.run(c.capture('https://www.stats.gov.cn/','国家统计局')); print('error',shot.error,'bytes',len(shot.data),'matched',shot.matched)"
```

- **预期**：Chrome 输出 HTML；capture `error=None`、`bytes>0`。
- **如果不通过**：先把 `EVIDENCE_SCREENSHOTS=false`，不要让截图拖慢研究/查证。

#### V5. 在普通终端复跑完整测试

- **为什么**：沙箱内 31 个 setup error 是临时目录 ACL 导致，不能据此判断项目回归。
- **验证方式**：

```powershell
./.Search/Scripts/python.exe -m pytest -q
```

- **预期**：136 passed（README 基线）。
- **如果仍失败**：把失败用例和 traceback 发我；届时再区分测试问题与代码问题。
- **备选**：允许我把当前会话临时切到"完全权限"跑一次（只影响沙箱，不改项目文件）。

#### V6. 确认你实际打开的页面与端口

- **为什么**：8000 是旧配置，8010 是我启动的干净对照；需要确认你平时打开哪个 URL。
- **验证方式**：浏览器地址栏；打开开发者工具 Console/Network，看 `/api/health` 返回的 `settings.llm_model` 和 `deepseek.base_url`。
- **判读**：若 `settings.llm_model=gpt-5.6-sol`，就是旧进程；若 `deepseek-flash`，是干净实例。

---

### 5.2 需要你决策的事项（D1–D10）

#### D1（P0）8000 旧进程怎么处理

- **现状**：8000 的 LLM 必 401；8000 目前对当前会话不可见（PID 37668），我无法安全停止它。
- **可选方案**：
  - **A（推荐）**：你在自己的终端停止 8000 的 `claimlab.api`，用干净窗口 `./.Search/Scripts/python.exe -m claimlab.api` 重启，然后跑 V1/V2 的检查。
  - **B**：暂不碰 8000，先用 `http://127.0.0.1:8010` 验证（我已启动，配置正确；但它是沙箱进程，截图不可用，会话结束可能停止）。
  - **C**：改端口（如 8001）启动新实例，保留 8000 做对照。
- **验证**：`scripts/diagnose_connections.py --base-url http://127.0.0.1:8000 --plan` 期望
  `deepseek.base_url=api.deepseek.com`、`method=llm`、无 FAIL。
- **风险**：不处理则 8000 上的所有 LLM 功能不可用，"无结果"会持续。

#### D2（P0）LLM 结构化输出策略

- **现状**：推理 token 吃满 `max_tokens`；1/4 decompose 有效；match 22 条必空；answer 截断。
- **可选方案**：
  - **A（推荐，已实测）**：对所有结构化任务（decompose / build_queries / match_evidence / answer / advisory）发送
    `thinking: {"type": "disabled"}`；`max_tokens` 保持 answer 4096、其余 2048。
    实测：decompose 4/4、match 22 条有效、answer `engine=llm`，速度快 3–5 倍。
  - **B**：提高 `max_tokens`（answer/match 8192，decompose 4096），保留思考。
    实测：8192 时 match 可完成（reasoning 4574 + content 3284），但更慢、更贵。
  - **C**：换非推理模型。当前 `/models` 只有 `deepseek-flash`、`deepseek-v4-pro`，没有 `deepseek-chat`；需要你先确认账号是否可开。
  - **D**：A + B 混合（answer 保留思考 8192，其余关闭）。质量可能略高，复杂度和成本也高。
- **推荐**：**A**；如果某些问题需要更深推理，再对 `answer` 单独开 8192（D）。
- **验证**：
  1. `/api/plan` 连续 3 次，`method` 都应为 `llm`；
  2. `/api/research` 的 `answer.engine=llm`、`claims_count>=2`、`claims_with_valid_quote>=2`；
  3. `/api/runs` 的 `unit.verdict != insufficient`，`evidence` 中至少 1 条 `support/refute`；
  4. 日志出现 `finish_reason=stop`，不再出现空 content。
- **风险**：关闭思考可能降低极复杂问题的推理深度；但当前 JSON 任务的首要目标是"稳定产出可校验结构"，不是长推理。

#### D3（P1）引用广度与需求覆盖

- **现状**：全局 3 条；3 个需求共用同 3 条；10:14 统计研究检索到 100 条含 `41314` 的页面，但回答只看到 3 条，其中 `[3]` 还是无关的财政指标解释。
- **可选方案**：
  - **A**：全局 `limit=8`，简单。
  - **B（推荐）**：每需求 2–3 条、全局上限 9；按需求去重后合并；保证每个需求至少 1 条引用。
  - **C**：全部 top sources（最多 18 条）都传给模型；token 成本高，但关闭思考后可承受。
- **推荐**：**B**；先解决"覆盖"，再谈"更多"。
- **验证**：清洁研究运行后 `len(answer.citations)` 在 6–9；每个 ledger 需求至少有 1 个引用编号；10:14 那类统计问题应能引用到含数值的官方页。
- **风险**：引用越多，answer prompt 越大；需同时观察 token/延迟。

#### D4（P1）相关性与排序

- **现状**：`is_relevant` 字面匹配；heuristic 0/80；LLM 154/165 过宽；top 3 跨需求重复。
- **可选方案**：
  - **A（推荐）**：`is_relevant` 为 0 时放宽到 focus / 任一词；仍为 0 时用按 score 排序的前 N 条，并标记 `tier=insufficient`。
  - **B（推荐）**：排序键改为 `(grade, term_hits, -score, date)`，`term_hits` 统计 focus + search_terms + 数值在标题/摘要中的命中；同需求内限制同域名 2 条。
  - **C**：LLM rerank 前 30 条（成本高，后置）。
- **推荐**：**A+B**；C 作为下一阶段。
- **验证**：
  - 对长句 claim 跑 `/api/plan`（heuristic 场景可手动构造），`relevant_unique>0`；
  - 3 个需求的 top 3 不再完全相同；
  - 人工抽查 top 3 是否切题。
- **风险**：排序改动会影响所有字段；需要基准题集回归（D8）。

#### D5（P1）Site 参数策略

- **现状**：apex/`gov.cn` 静默 0；`site:` 运算符无效；LLM 会生成错误 Site。
- **可选方案**：
  - **A（推荐，快速）**：LLM 查询构造默认不生成 `site`；`coerce_llm_queries` 对非白名单 Site 置空。
  - **B（推荐）**：维护精确 host 白名单（`www.stats.gov.cn`、`www.xa.gov.cn`、`www.ncha.gov.cn`、`www.gov.cn`、`www.mohurd.gov.cn` 等），只允许白名单值。
  - **C**：带 Site 的查询 0 结果时，自动去掉 Site 重试一次（受预算约束）。
- **推荐**：**A+B**，C 作为兜底。
- **验证**：`scripts/diagnose_connections.py` 第 [5] 节；带 Site 的查询 `pages>0` 或不再生成 Site；`search.zero` 中不再出现 Site 查询。
- **风险**：放弃 Site 会降低"官方原文"定向能力；用 Industry + 精确查询词补偿。

#### D6（P0，查证）匹配分批

- **现状**：22 条一次性调用、1200 tokens；全部 unrelated；关闭思考后 16 support。
- **可选方案**：
  - **A（推荐）**：关闭 thinking + 每批 8–10 条，合并结果；保留 quote 校验。
  - **B**：只取 top 20 条，单次 8192 tokens。
  - **C**：A + 对非传统字段的 heuristic 改为"未判定"（`unknown`），不要一律 `unrelated`。
- **推荐**：**A+C**。
- **验证**：同一断言（"西安城墙现存主体是明代修建的"）应得到 `established` 或至少 `support>0`；不再全 `unrelated`。
- **风险**：分批增加 LLM 调用次数（但关闭思考后单次更快）。

#### D7（P1）可观测性与错误暴露

- **现状**：静默 fallback；日志缺 `request_id`/`finish_reason`；health 只查 key。
- **可选方案**：
  - **A（推荐）**：LLM client 记录 `task/model/finish_reason/http_status/reasoning_tokens`；skills 降级时 `logger.warning` 并带 `fallback_reason`。
  - **B（推荐）**：API 响应增加 `degraded`、`answer.engine`、`match_fallback`、`plan.method`；UI 在 `engine=rule` 或 `method=heuristic` 时显示黄色提示。
  - **C**：health 增加 `llm_last_ok_at`、`llm_last_error`、`search_last_zero_at`；可选 live probe。
- **推荐**：**A+B+C**（低风险，先做）。
- **验证**：临时把 DeepSeek base 改错，`/api/research` 应返回 `engine=rule` 且 `degraded_reason` 明确；日志出现 401/finish_reason。
- **风险**：响应字段增加，前端需同步；改动小。

#### D8（P1）质量基准题集

- **现状**：没有可重复的"前后对比"；每次只能凭感觉判断。
- **可选方案**：
  - **A（推荐）**：6 道题（3 研究 + 3 查证），记录 `engine/method/citations/claims/AB rate/relevant/zero/latency`；修复前后各跑一次。
  - **B**：只做人工验收。
- **推荐**：**A**；题目建议：西安城墙年代、2024 居民收入、电动自行车新规、一句话查证"明代修建"、统计口径、世界遗产身份。
- **验证**：对比表；关键指标应满足：`method=llm`、`engine=llm`、`claims>=2`、查证 `support>0`、`zero_requirements=0`。
- **风险**：需要花 6 次研究的预算（约 90 次搜索）；当前 288/400，需注意额度。

#### D9（P2）截图策略

- **现状**：本会话 Chrome 启动失败；正常实例曾成功；health 仍显示可用。
- **可选方案**：
  - **A**：暂时 `EVIDENCE_SCREENSHOTS=false`，UI 明确显示"截图不可用"。
  - **B（推荐）**：在普通终端排查 Chrome（临时 profile 放到 `state/tmp`、延长等待、检查 `DevToolsActivePort`）。
  - **C**：保留 best-effort，失败不阻塞。
- **推荐**：先 **A** 保证主流程，再做 **B**。
- **验证**：一次 capture 成功；研究 `metrics.screenshots>0`；`/api/evidence/{run_id}/{n}` 200。
- **风险**：关闭截图会少一类证据；不影响文字/引用。

#### D10（P2）配置、文档与运行卫生

- **现状**：`.env` 重复 `LLM_PROVIDER`、遗留 Toklens `LLM_API_KEY`、GPT/Codex 已禁用但仍显示；README 多处与实现不一致；双实例共享预算/日志；归档增长。
- **可选方案**：
  - **A（推荐）**：清理 `.env`（去重、删除禁用 key、`LLM_MODEL=deepseek-flash`），在 README 标注 Site host 规则、Cnt 整数/字符串、answer token、test 数、plan 流程。
  - **B（推荐）**：确保同一端口只有一个实例；日志按端口或 PID 分文件；预算文件加锁。
  - **C**：归档/缓存保留策略（如 7 天或 500 MB）。
- **推荐**：**A+B**；C 下一迭代。
- **验证**：`scripts/configure_keys.py show`；`/api/health` 字段一致；`netstat` 只有一个 8000 监听；`archive` 大小可控。
- **风险**：清理 `.env` 前备份；不要删除仍在用的 key。

---

## 6. 建议的修复顺序

| 步骤 | 改动 | 文件 | 验证 | 预计 |
|---|---|---|---|---|
| 1 | 干净重启 8000；确认 health 与 `.env` 一致 | 运维动作 | `diagnose_connections.py` FAIL=0 | 10 分钟 |
| 2 | 结构化任务关闭 thinking；记录 finish_reason | llm/client.py | plan 3/3 llm；answer engine=llm | 30 分钟 |
| 3 | 匹配分批 8–10 条 + 关闭 thinking | matching.py / llm client | 22 条 → support>0 | 30 分钟 |
| 4 | 引用每需求 2–3 条、全局 8–9 | answer.py / research.py | citations 6–9、覆盖 3 需求 | 30 分钟 |
| 5 | 相关性 0 条兜底 + 排序 term_hits | source_policy.py / research.py | relevant>0、top3 不重复 | 1–2 小时 |
| 6 | Site 白名单/去 Site 重试 | query.py / gateway.py | Site 查询 pages>0 | 1 小时 |
| 7 | 降级可见性 + health 细化 | api.py / 前端 | engine/method 提示 | 1 小时 |
| 8 | 基准题集回归 | scripts/ + fixtures | 指标对比表 | 半天 |

> 步骤 2 是"一改就见效"的杠杆点；步骤 1 是"不改就永远无效"的前提。

---

## 7. 附录

### A. 本次实测命令（可复现）

```powershell
# 1) 干净实例（如 8000 被占用，用 8010 对照）
$env:APP_PORT='8010'
./.Search/Scripts/python.exe -m claimlab.api

# 2) 配置/链路/LLM/SearchPro 一次性诊断
./.Search/Scripts/python.exe scripts/diagnose_connections.py --base-url http://127.0.0.1:8010
./.Search/Scripts/python.exe scripts/diagnose_connections.py --base-url http://127.0.0.1:8000 --plan

# 3) 计划（不消耗搜索预算）
curl.exe -X POST http://127.0.0.1:8010/api/plan -H "Content-Type: application/json" --data-raw '{"text":"西安城墙是全国唯一保存完整的唐代城墙，唐朝原汁原味，城砖都是唐代的，所以西安城墙是世界文化遗产。"}'

# 4) 研究 / 查证
./.Search/Scripts/python.exe scripts/run_research.py --text "西安城墙现存主体是什么年代修建的？" --report
./.Search/Scripts/python.exe scripts/run_verify.py --text "西安城墙现存主体是明代修建的。" --report

# 5) 测试（普通终端）
./.Search/Scripts/python.exe -m pytest -q
```

### B. 关键日志摘录

```
2026-10-25 10:18:10  app.start
2026-10-25 10:23:47  app.start
2026-10-25 10:24:11  research.start plan_id=plan-be8b8633e1 plan_reused=False
2026-10-25 10:24:15  research.ledger field=scenic_explanation tier=insufficient unique=0 ab=0
2026-10-25 10:24:15  research.done requirements=1 queries=11 pages_unique=80 relevant_unique=0
                      grade_counts={'A':0,'B':0,'C':0,'D':0,'E':0} claims_count=0 cache_hits=11
2026-10-25 10:33:31  WARNING claimlab.answer answer.llm_error LLMError: model did not return a JSON object
2026-10-25 10:33:56  WARNING claimlab.answer answer.compact_error LLMError: model did not return a JSON object
2026-10-25 10:33:56  research.done requirements=3 pages_unique=165 relevant_unique=154
                      grade_counts={'A':24,'B':28,'C':20,'D':73,'E':9} claims_count=0 screenshots=0
```

### C. 参数实测数据

**Site**：

| 请求 | pages | 结果域名 |
|---|---|---|
| `Site=www.xa.gov.cn` | 20 | 全部 `www.xa.gov.cn` |
| `Site=xa.gov.cn` | 0 | — |
| `Site=www.stats.gov.cn` | 20 | 全部 `www.stats.gov.cn` |
| `Site=stats.gov.cn` | 0 | — |
| `Site=gov.cn` | 0 | — |
| `Site=163.com` | 4 | 全部 `163.com` |
| `Query=site:stats.gov.cn …` | 20 | 混合域名（运算符无效） |

**Industry（同一查询）**：

| 查询 | none | gov | news | acad |
|---|---|---|---|---|
| 西安城墙 历史沿革 | 20（17 域名） | 20（14） | 20（14） | 20（14） |
| 电动自行车 新规 | gov 域名 14/20 | 18/20 | 10/20 | 7/20 |

同一查询下 gov/news/acad 三次结果的 URL 集合完全相同（Jaccard=1.0），说明该查询的 Industry 过滤很弱；换一个查询（电动自行车）才看出差异。

**LLM token**：

| 任务 | 设置 | finish | reasoning | content | 结果 |
|---|---|---|---|---|---|
| decompose | 1200 | stop/length | 559–1200 | 0–756 | 1/4 有效 |
| decompose | 1200 + no thinking | stop | 0 | 618–675 | 4/4 有效 |
| match 22 条 | 1200 | length | 1200 | 0 | 0 match |
| match 22 条 | 4096 + no thinking | stop | 0 | 3035 | 22 match |
| answer | 4096 | length | 3850 | 407 | JSON 截断 |
| answer | 4096 + no thinking | stop | 0 | 1228 | JSON 有效、3 claims |

### D. 文件索引（排障最常看）

| 文件 | 作用 |
|---|---|
| `claimlab/config.py` | `.env` 解析、Settings；`setdefault` 导致进程环境优先 |
| `claimlab/runtime.py` | Sandbox、fake 回退、provider 构建 |
| `claimlab/llm/client.py` | LLM 请求、模型选择、缓存、`max_tokens`、`_coerce_content` |
| `claimlab/skills/requirements.py` | decompose prompt、heuristic 回退、search_terms 提取 |
| `claimlab/skills/query.py` | 查询模板、LLM 查询构造、时间序列 |
| `claimlab/skills/source_policy.py` | `is_relevant`、`source_tier` |
| `claimlab/skills/grading.py` | A–E 域名/时效分级 |
| `claimlab/skills/answer.py` | 引用构建（`limit=3`）、LLM 回答、规则降级 |
| `claimlab/skills/matching.py` | 证据匹配、quote 校验、heuristic 回退 |
| `claimlab/research.py` | 研究主流程、ledger、top sources、metrics |
| `claimlab/pipeline.py` | 查证主流程、预算、轮次 |
| `claimlab/api.py` | 路由、health、配置端点、超时/并发 |
| `claimlab/search/gateway.py` | 缓存、预算、审计、zero 日志 |
| `claimlab/search/normalize.py` | Pages 字符串/数组归一化 |
| `claimlab/runs.py` | 内存 run、SSE |
| `web/app.js` | 前端请求、SSE、报告渲染、配置保存 |
| `scripts/diagnose_connections.py` | 本次新增的一键诊断脚本 |

### E. 术语

- **heuristic plan**：LLM 不可用时的规则拆分；`focus` 回退为整句，`search_terms` 可能只有字段词。
- **rule answer**：LLM 不可用时的来源要点摘要；`engine=rule`，不生成 claim。
- **thinking / reasoning**：DeepSeek V4.1 Flash 在 `content` 之外产生的推理 token，计入 `completion_tokens`。
- **Site**：SearchPro 的站内搜索参数，必须与索引 host 完全一致；apex 与 `www` 不是同一个 host。
- **R1–R5**：确定性判定规则；R5 为证据不足，不是"假"。

---

## 8. 一句话交付

连接没问题；**8000 的 LLM 配置是错的，所有结构化 LLM 调用的 token 预算又不够，失败还被静默吞掉**。
先把 8000 重启干净、把 JSON 任务的 thinking 关掉，再修引用上限和 Site 写法；
在确认这些之前，不要继续用 8000 的"无结果"来判断检索质量。
