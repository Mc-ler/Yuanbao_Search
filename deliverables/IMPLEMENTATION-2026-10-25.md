# 万物皆可查 · D1–D8 实施记录（2026-10-25）

- 对应决策：用户确认的 D1–D8 + 截图 B + Toklens key 删除
- 代码基线：`d11f8c0` + 本次工作区改动
- 运行实例：`http://127.0.0.1:8000`（已重启，8000 单实例；8010 已停止）
- 结论：**D1–D8 已落地并完成端到端实测；唯一未能在本会话验证的是 Chrome 截图（DSH 沙箱阻断 crashpad），代码已改为可在普通终端重试并输出 stderr 原因。**

---

## 1. 决策与落地对照

| 决策 | 落地内容 | 主要文件 |
|---|---|---|
| D1 清理 8010、重启 8000 | 停止 8010；8000 干净重启；`test_deepseek.py` OK（deepseek-flash 491ms）；health 为 `api.deepseek.com` / `deepseek-flash` | 运维 |
| D2 A+B 混合 | 结构化任务 `thinking disabled` + 4096；answer `thinking auto` + 8192；`finish_reason=length`/空 JSON/无效 JSON 自动无思考重试；模型候选仍可切换 | `claimlab/llm/client.py`、`claimlab/keys.py`、`config/llm_providers.json` |
| D3 C 级引用 | `build_citations` 默认保留全部 top sources（最多 18）；截图仍只取前 3 | `claimlab/skills/answer.py` |
| D4 C 级重排 | 每需求取 top 30，LLM 评分 0–1；并行 3 个需求；无结果时用阈值 0.5 兜底；失败回退确定性排序 | `claimlab/skills/rerank.py`、`claimlab/research.py`、`claimlab/config.py` |
| D5 A+B+C | LLM 查询默认不生成 Site；精确 host 白名单/`www.*.gov.cn`；剥离 `site:`；0 结果自动无 Site 重试一次 | `claimlab/skills/query.py`、`claimlab/search/fallback.py`、`research.py`、`pipeline.py` |
| D6 A+C | 匹配每批 8 条（22 条→3 批）；非传统字段 heuristic 返回 `unknown`（未判定），不再伪装 `unrelated`；R1–R5 忽略 unknown，不计数 | `claimlab/skills/matching.py`、`claimlab/contracts.py`、`judging.py`、`reporting.py` |
| D7 A+B+C | 日志增加 `llm.call/llm.retry/llm.error/matching.batch/rerank.done/search.site_fallback`；API 增加 `degraded`/`answer.degraded_reason`；health 增加 last_ok/last_error/last_finish_reason/calls/search last zero；UI 黄色降级条与 LLM 状态 | `llm/client.py`、`requirements.py`、`query.py`、`matching.py`、`answer.py`、`api.py`、`runtime.py`、`gateway.py`、`web/app.js`、`styles.css` |
| D8 Toklens key / 口径 | `.env` 删除 `LLM_API_KEY`/`LLM_BASE_URL`/`TOKLENS_API_KEY`，去重；GPT/Codex 定义保留在 provider JSON；日志按端口；预算文件跨进程锁；README/`.env.example` 更新为 v4.3 | `.env`、`.env.example`、`config/llm_providers.json`、`claimlab/search/budget.py`、`api.py`、`README.md` |
| 截图 B | profile 改为 `state/screenshot-profiles`（`mkdir` 而非 `mkdtemp`，规避 ACL）；Chrome stderr 落文件；等待 15s；失败重试一次；health 暴露 last_error | `claimlab/evidence/capture.py`、`runtime.py` |
| 附加 | `plan_id` 改为内容感知（method + requirements/queries），避免 heuristic/llm 计划撞 id；`plan_reused` 不再硬编码 | `claimlab/planning.py`、`research.py`、`api.py` |

---

## 2. 验收数据

### 2.1 D1 配置与 DeepSeek

```
GET /api/health
search_ready=True llm_ready=True
settings.llm_model=deepseek-flash  llm.model=deepseek-flash
deepseek.base_url=https://api.deepseek.com/v1
providers_keyed=deepseek          # GPT/Codex 已无 key
test_deepseek.py: deepseek-flash 200 491ms OK
```

### 2.2 D2 计划 / 回答

| 项目 | 结果 |
|---|---|
| `/api/plan`（长 claim） | 200，11.8s，`method=llm`，3 需求，15 查询 |
| 查询 Site | 仅 `www.shaanxi.gov.cn`，无 `gov.cn`/`site:` |
| 深度研究 | 200，42.1s，`method=llm`，`answer.engine=llm`，`degraded.reasons=[]` |
| answer 调用 | `thinking=auto`，`max_tokens=8192`，reasoning 1096，finish stop，13.6s |
| 结构化调用 | `thinking=disabled`，`max_tokens=4096` |

### 2.3 D3/D4 引用与重排

| 指标 | 结果 |
|---|---|
| citations | **11**（此前 3） |
| claims | **8**（valid quote 7） |
| rerank | 3 个需求并行，`rerank_scored=90`，`rerank_calls=3` |
| top sources | 三个需求不再使用同一组前 3：scenic_history 首条 `shaanxi.gov.cn`；scenic_explanation 首条 `xadfz.xa.gov.cn`；heritage_status 首条 `wlj.nanjing.gov.cn` |
| A/B | 45 A + 34 B / 177 relevant（44.6%），3/3 需求 A/B |

### 2.4 D5 Site

`scripts/diagnose_connections.py` 实测：

| 请求 | pages |
|---|---|
| baseline | 20 |
| `Site=www.xa.gov.cn` | 20 |
| `Site=xa.gov.cn` | 0 |
| `Site=gov.cn` | 0 |
| `Industry=gov` | 20 |
| `Freshness=y1` | 20 |

`test_search_fallback.py` 验证：首个 Site 查询 0 页 → 自动无 Site 重试 → 20 页，调用 2 次。

### 2.5 D6 查证

```
POST /api/runs {"text":"西安城墙现存主体是明代修建的。"}
status=done  elapsed=11.0s
verdict=established  rule=R2
evidence=22  relations={support:18, unrelated:4}
degraded={"extraction_method":"llm","unknown_evidence":0,"reasons":[]}
日志: matching.batch offset=0/8/16 batch=8/8/6
```

此前同一断言为 `R5 insufficient` / 全部 unrelated。

### 2.6 D7 可观测性

- 日志出现：`llm.call`（task/model/thinking/max_tokens/finish_reason/reasoning_tokens/content_chars/latency）、`llm.retry`、`llm.error`、`matching.batch`、`rerank.done`、`search.site_fallback`。
- `/api/health.llm` 出现：`last_task/last_model/last_finish_reason/last_error/last_error_at/last_ok_at/last_latency_ms/last_reasoning_tokens/calls/cache_hits`。
- `/api/health.search`：`at/query/provider`（最近一次 0 结果）。
- `/api/health.screenshots.last_error`：Chrome stderr 尾部。
- `/api/plan` 返回 `degraded.method/reason`；`/api/research` 返回 `degraded`；查证报告 `report.degraded`；UI 显示黄色降级条与 LLM 琥珀状态。

### 2.7 D8 配置/运行卫生

- `.env` 无 `LLM_API_KEY`/`LLM_BASE_URL`/`TOKLENS_API_KEY`，无重复 key；`providers_keyed=deepseek`。
- 预算锁：两个独立进程各 `charge` 20 次，最终 `calls=40`（修复前会丢计数）。
- 8000 单实例；8010 已停止；非 8000 端口日志名 `app-YYYYMMDD-<port>.log`。
- README/.env.example 更新：v4.3、157 tests、Site 规则、thinking/token、rerank、degraded、日志。

### 2.8 测试

```
157 tests collected
126 passed, 31 errors（全部是 pytest tmp_path 的 DSH 临时目录 ACL）
0 failed
```

31 个 error 与代码无关；在普通终端应得到 157 passed。`pytest.ini` 已限制 `testpaths=tests`，避免扫描 `state/` 的运行产物。

---

## 3. 截图 B 的当前状态

代码已按 B 落地，但本会话仍然失败，原因已可诊断：

```
chrome exited before DevTools started:
[ERROR:crashpad_client_win.cc:430] OpenProcess: 拒绝访问 (0x5)
[ERROR:crashpad_client_win.cc:144] crash server failed to launch, self-terminating
```

这是 DSH 沙箱阻止 Chrome crashpad 启动，不是 profile 路径问题（profile 已改为 `state/screenshot-profiles` 并用 `mkdir`）。
- 详细排查步骤见 [SCREENSHOT-GUIDE-2026-10-25.md](SCREENSHOT-GUIDE-2026-10-25.md)。
- 独立验证：`scripts/test_capture.py`（可 `--save` 保存 JPEG）。
- 在**普通 PowerShell**中按指南重试；若能启动，`screenshots.last_error` 会清空。
- 若仍失败，先 `EVIDENCE_SCREENSHOTS=false`，不要让截图影响研究主流程（当前失败会降级，不阻塞报告）。

---

## 4. 复验命令

```powershell
# 配置/链路/LLM/SearchPro/计划
./.Search/Scripts/python.exe scripts/diagnose_connections.py --base-url http://127.0.0.1:8000 --plan

# DeepSeek
./.Search/Scripts/python.exe scripts/test_deepseek.py

# 计划 / 研究 / 查证
curl.exe -X POST http://127.0.0.1:8000/api/plan -H "Content-Type: application/json" --data-raw '{"text":"西安城墙现存主体是什么年代修建的？"}'
./.Search/Scripts/python.exe scripts/run_research.py --text "西安城墙现存主体是什么年代修建的？" --report
./.Search/Scripts/python.exe scripts/run_verify.py --text "西安城墙现存主体是明代修建的。" --report

# 测试（普通终端；沙箱内 31 个 tmp_path setup error 可忽略）
./.Search/Scripts/python.exe -m pytest -q
```

期望：
- `diagnose_connections.py` `FAIL=0 WARN=0`；plan `method=llm`。
- research `answer.engine=llm`、`degraded.reasons=[]`、citations ≥6。
- verify `established/refuted` 或至少 `support>0`；不再全 `unrelated`。
- 普通终端 157 passed。

---

## 5. 已知限制（本次未处理）

- Chrome 截图在 DSH 沙箱内不可用（crashpad 拒绝访问）；需普通终端确认。
- 31 个 pytest 用例仍受 DSH 临时目录 ACL 影响；`pytest.ini` 已避免扫描 state，但 `tmp_path` 本身仍需普通权限。
- 研究结果仍不持久化；刷新/重启会丢报告。
- 重排/answer 会增加 token 与延迟（实测 42s/次），当前 `RESEARCH_TIMEOUT_SECONDS=180` 仍够用；若并发或长问题变慢，可调该值。
- GPT/Codex/Toklens 接入保留但默认无 key；如需启用，按 `configure_keys.py` 写入对应 key。

---

## 6. 变更文件

```
claimlab/api.py, config.py, contracts.py, keys.py, runtime.py,
claimlab/llm/client.py, planning.py, research.py, pipeline.py,
claimlab/skills/answer.py, judging.py, matching.py, query.py,
claimlab/skills/reporting.py, requirements.py, research_report.py,
claimlab/skills/rerank.py (new),
claimlab/search/budget.py, gateway.py, fallback.py (new),
claimlab/evidence/capture.py,
scripts/test_capture.py (new), scripts/diagnose_connections.py (new),
config/llm_providers.json, .env.example, README.md,
web/app.js, web/index.html, web/styles.css, pytest.ini,
tests/test_plan_optimizations.py + 8 new test files
```

截图排查全文：[SCREENSHOT-GUIDE-2026-10-25.md](SCREENSHOT-GUIDE-2026-10-25.md)。

---

## 7. 追加修复：一句话查证汇总改为自然语言

### 问题

一句话查证报告出现 `{"refuted":2,"suspect":1}`。来源不是模型输出，而是：
- `web/app.js` 的 `verificationReport()` 用 `JSON.stringify(report.aggregate.counts)` 渲染；
- `claimlab/skills/reporting.py` 的 `render_markdown()` 用 `str(report.aggregate.get("counts"))` 渲染。

### 改动

- `reporting.py` 新增 `aggregate_summary()`：输出“共 3 条断言：2 条不成立、1 条存疑。”；`aggregate` 增加 `summary`、`overall_label`，保留 `overall`/`counts` 供 API/机器读取。
- `render_markdown()` 改用 `aggregate.summary`，不再打印 counts dict。
- `web/app.js` 改用 `report.aggregate.summary`，并保留 `aggregateSummary()` 兼容旧数据；删除 `JSON.stringify(report.aggregate.counts)`。
- 提示词加约束：`answer.py` 的 `text` 与 `advisory.py` 的 `text/caveats` 必须是自然语言，禁止 JSON/对象字面量/统计字典。
- `index.html` 静态资源版本 `?v=4.5`，避免浏览器缓存旧 app.js。

### 验证

- 单元：`tests/test_report_summary.py` 4 passed；`aggregate_summary("mixed", {"refuted":2,"suspect":1})` 返回“共 3 条断言：2 条不成立、1 条存疑。”
- 真实多断言查证（3 条）：
  - units：`established / refuted / suspect`
  - aggregate：`{"overall":"mixed","overall_label":"结论混合","counts":{"established":1,"refuted":1,"suspect":1},"summary":"共 3 条断言：1 条成立、1 条不成立、1 条存疑。"}`
  - `/api/report?format=md`：`> 汇总：共 3 条断言：1 条成立、1 条不成立、1 条存疑。`，无 `{"refuted"`/`{"suspect"`。
- 服务端静态文件：`/` 引用 `app.js?v=4.5`；`/static/app.js` 中不再存在 `JSON.stringify(report.aggregate...)`，且包含 `aggregateSummary`。
- 测试总数：157 collected。

### 注意

浏览器若仍显示旧文案，请硬刷新（Ctrl+F5）或确认地址是 8000 且 `index.html` 已加载 `?v=4.5`。

---

## 8. 追加修复：深度研究 `uncertainty` 中的 `as_of`/`stale` 字段自然化

### 问题

深度研究报告中出现 `as_of 为 2026-10-25`、`stale=false`。这不是渲染层打印字典，而是 **LLM 把 prompt 里的内部字段名抄进了 `uncertainty`**：
- `answer.py` 原规则 7/8 直接使用 `as_of`、`time_context`、`stale=true` 这些词；
- 模型在 `uncertainty` 中复用，前端原样显示。

### 改动

- `answer.py` 重写规则 7/8：改用“给定当前日期/时效信息”，明确内部字段名不要出现在回答里；新增规则 10：`text/uncertainty/time_note` 禁止 `as_of/time_context/stale/time_sensitive/freshness_days/latest_source_date...`、JSON、对象字面量、键值对。
- 新增 `_naturalize_time_text()`：
  - `as_of 为 2026-10-25` → `截至 2026年10月25日`
  - `stale=false` → `来源仍在时效窗口内`
  - `time_sensitive=false` → `不涉及时效`
  - `freshness_days=31` → `时效窗口为 31 天`
  - 泄漏的 JSON/dict（引号、花括号、英文逗号）也做清理。
- 新增 `_join_clauses()`：避免 `uncertainty` 与 `time_note` 拼接产生 `。；`。
- 自然化范围：`text`、`claims[].text`、`uncertainty`、`time_note`；**quote 不改**。
- `advisory.py` 增加自然语言约束。

### 验证

- `tests/test_answer_naturalize.py` 3 passed（含泄漏 dict、拼接标点）。
- 真实深度研究（同一 claim）：
  - `answer.engine=llm`、citations 11、claims 7
  - `uncertainty` 已变为“最新来源为2026年7月31日发布，距当前日期2026年10月25日约86天……”，无 `as_of`、无 `stale`、无 `。；`
- 测试总数：157 collected。
