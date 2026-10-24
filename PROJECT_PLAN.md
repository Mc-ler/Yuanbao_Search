# 元宝搜索 Research Agent · 项目规划（v2.6）

> 更新时间：2026-10-25（Asia/Shanghai）
> 当前基线：P0 已交付；**85 个测试通过**；本文件是唯一规划文档。

## 0. 结论

1. 项目已进入「可运行 + 可协作」阶段：文字输入、SearchPro API 单通道、LLM 需求拆分、LLM 自动查询、真实检索、带 [n] 引用的回答与调查报告、SQLite 索引。
2. **MCP 已彻底删除**；检索 100% 走 SearchPro API。
3. **LLM 自动查询**：自动判断查询字段（Query/Site/Industry/Freshness/Cnt），freshness 统一 d/m/y，Industry 仅 gov/news/acad；**subject/city 不注入查询**。
4. **演示快路径**：三个演示问题预生成到 demos/，精确匹配秒回、零额度；落地以真实查询为主。
5. **调查报告双入口**：终端 --report + Web「调查报告」标签页。
6. M5–M9 展示/汇报/录屏/提交由下游团队负责，不属于本模块。

---

## 1. 目标与现状

### 1.1 目标

| 层 | 目标 | 判据 |
|---|---|---|
| P0 · 可运行 MVP | 问题 → 需求 → 查询 → 检索 → 证据 → 回答/报告 | 已交付；85 测试 |
| P1 · Skills 包 | 9 个能力独立调用 | 未开始 |
| P2 · Research Agent | LLM 编排 verify/research | 未开始 |
| P3 · 部署 | 容器化研究服务 | 未开始 |
| 协作 | GitHub 自动推送 | push.config 已指向仓库 |

### 1.2 当前状态（已完成）

- 代码：claimlab/ + web/ + config/ + fixtures/ + examples/ + demos/ + scripts/ + tests/。
- 85 个测试通过；覆盖归一化、分级、去重、判定、预算、查询构造、Key/Bearer、模型选择、需求拆分、回答引用、SQLite、demo 匹配。
- SearchPro API 单通道；统一 SearchBatch；Cnt 字符串化（10/20/30/40/50）。
- LLM：config/llm_providers.json 管理 gpt/codex（Toklens /v1）；/models 自动选模型；当前 gpt-5.6-sol。
- S1 需求拆分（requirements.py）+ S2 LLM 查询构造（build_queries_llm，自动判断字段）。
- 检索网关（缓存/预算/审计）+ 时间序列查询 + broad_search 广泛搜索脚本。
- 回答引用（[n] + 不编造）+ 调查报告（research_report.py）。
- 演示快路径（demos.py + prepare_demos.py + match_demo 精确匹配）。
- SQLite 索引（store/db.py）+ /api/db/*。
- Web 极简 UI（研究 / 调查报告 tabs）。
- framework.html 重绘为 v3（archify，validate/deliver/check 通过）。

### 1.3 范围边界

- 只做文字输入；不做图片/OCR/视频。
- 主动范围：国家统计、历史/文化遗产、市政；旧餐厅/价格/营业时间字段仅 legacy verify_claim。
- 证据是检索摘要与链接，不做全文抓取。
- M5–M9 展示/汇报/录屏/提交由下游团队负责。

---

## 2. 架构与模块职责

```text
研究问题 / 文字说法
  → 演示快路径（match_demo 精确匹配 → demos/ 预置结果）
  → S1 需求拆分（Requirement，1–3 条）
  → S2 LLM 查询构造（自动判断 Query/Site/Industry/Freshness/Cnt）
  → S3 检索网关（SearchPro API，缓存/预算/审计）
  → S4–S7（去重/分级/匹配/判定）
  → 回答引用（[n] + 不编造）→ 调查报告（终端 + Web）
  → SQLite 索引（文件为权威）
```

| 模块 | 职责 | 代码 | 状态 |
|---|---|---|---|
| 入口层 | 研究/计划/报告/DB 接口 | claimlab/api.py、web/ | P0 完成 |
| S1 需求拆分 | 问题 → 1–3 个 Requirement | skills/requirements.py | 完成 |
| S2 查询构造 | LLM 自动判断字段 | skills/query.py | 完成 |
| S3 检索网关 | SearchPro API、缓存、预算、审计 | search/ | P0 完成 |
| S4–S8 | 去重/分级/匹配/判定/回答/报告 | skills/ | P0 完成 |
| 研究执行器 | 演示快路径 + 真实查询 + 报告 | claimlab/research.py | 完成 |
| 演示预置 | demos/ 预生成 + 精确匹配 | claimlab/demos.py、scripts/prepare_demos.py | 完成 |
| SQLite 索引 | 历史检索/统计/导出 | store/db.py、/api/db/* | 完成 |
| 旧断言路径 | verify_claim（legacy） | skills/extraction.py、/api/runs | legacy |

---

## 3. 已完成里程碑

| ID | 时间 | 目标 | 验收 |
|---|---|---|---|
| M0 | 10/24 | 真实通道确认 | health 真实；85 测试 |
| M1 | 10/24 | API/LLM 探针 | API pages；/models；LLM 选 gpt-5.6-sol |
| M2 | 10/24 | 三域范围 + 字段/目标词 + 回退/再查询 | 3/3 字段；无重复 |
| M3 | 10/25 | LLM 自动查询 + 无字段干扰 + demo 快路径 + 调查报告双入口 | 85 测试；demo 秒回；报告可看/打印 |

> M5–M9 展示/汇报/提交由下游团队负责。

---

## 4. 后续计划（P1/P2/P3）

- **P1 Skills 包**：skills/<name>/SKILL.md + schema + 入口 + 测试；registry；CLI skills list/run。
- **P2 Research Agent**：工具编排、function calling + JSON fallback、引用校验、Agent API/UI。
- **P3 部署**：Dockerfile + compose；SSE 重放；App Token；限流；日志脱敏。

---

## 5. 风险与降级

| 风险 | 处置 |
|---|---|
| LLM 模型不可用 | /models + preferred/default；model-not-found 换候选；仍失败走 heuristic |
| Site 命中率低 | 查询构造以 Industry=gov 为主，不单独依赖 Site |
| demo 结果过期 | prepare_demos.py --refresh 重跑 |
| framework 未浏览器目检 | 本机装 Chrome（ARCHIFY_CHROME）后重跑 browser-check |
| 查询扩量耗额度 | 预算 8/56/800，MAX_CALLS_* 可调 |

---

## 6. 需要你验证 / 决策的事项

| ID | 事项 | 验证方式 | 可选方案 |
|---|---|---|---|
| V1 | Web 空引用修复 | 启动 8000 后浏览器无「无法连接本地服务」报错；健康徽标正常 | A. 通过；B. 指出问题 |
| V2 | demo 快路径 | 浏览器跑 q1/q2/q3，应秒回并显示「演示 · 预置结果」 | A. 通过；B. 需调 |
| V3 | 自定义问题真实查询 | 输入一条新问题，应走真实检索（非秒回） | A. 通过；B. 需调 |
| V4 | 调查报告 tab | 检索后切到「调查报告」tab，可看结论+[n]引用+来源 | A. 通过；B. 需调 |
| D1 | framework 是否补 browser-check | 本机装 Chrome 后重跑 | A. 补；B. 跳过 |
| D2 | demo 快照刷新时机 | 每次演示前是否重跑 prepare_demos.py | A. 每次刷新；B. 固定快照 |

---

## 7. 变更记录

- v2.6（2026-10-25）：city/subject 彻底不注入查询；演示快路径（demos/ + match_demo 精确）；Web 极简标签页（研究/调查报告）；framework v3；85 测试。
- v2.5（2026-10-25）：LLM 查询构造自动判断字段 + 同步口径 + d/m/y freshness；互斥实测；调查报告双入口；83 测试。
- v2.4（2026-10-24）：MCP 删除；cnt 字符串化；预算 8/56/800；时间序列 + broad_search；SQLite 索引；回答引用；判定放松；82 测试。
- v2.3（2026-10-24）：本地 8000 旧进程重启；浏览器切 /api/research；前端简洁研究页；80 测试。
- v2.0–v2.2：范围收窄、需求拆分、目标词、回退/再查询、live 验证、GitHub 推送。
- v1.0（2026-10-23）：早期框架（已删除）。
