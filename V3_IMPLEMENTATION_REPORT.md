# v3.0 实施方案落地报告

> 日期：2026-10-25（Asia/Shanghai）
> 代码分支：refactor/v3-two-boards
> 基线：v2.6（2e9db87）→ v3.0
> 结论：四项修复与配套重构已落地；103 个测试通过；8000 实例运行 v3.0；framework.html 已由 archify 重绘并通过 validate/deliver/check/browser-check。

---

## 1. 实施概览

| 工作流 | 计划内容 | 状态 | 关键落点 |
|---|---|---|---|
| A | 删除预置示例、演示、DEMO、example_id | 完成 | demos/、examples/、demos.py、prepare_demos.py、run_example*.py、/api/examples、/api/fixtures 全部删除；请求字段 extra=forbid |
| B | 根治 subject/city；统一 /api/plan 与 /api/research | 完成 | ResearchTask/Requirement 删除字段；新增 focus；planning.py + PlanStore + plan_id |
| C | 深度研究板块 | 完成 | 3 查询/需求、全局去重、来源分册、指标 v2、不写 SQLite |
| D | 断言查证板块与 R1–R5 | 完成 | /api/runs + SSE + UI 进度/判定卡 + R5 advisory |
| E | 截图证据、vision、引用校验 | 完成 | claimlab/evidence/、LLM images、SSRF、内存图片、[n] 校验 |
| F | 安全/预算/口径/UI 清理 | 完成 | safety 入口、4/28/400、URL-less key、打印/宽度/CSV、死代码清理 |
| G | 文档与框架图 | 完成 | README/PROJECT_PLAN/rules/skills 同步；framework.html archify v3.0 |

---

## 2. 关键设计落地

### 2.1 双板块边界

- 深度研究（claimlab/research.py）：需求拆分 → 共享 planner → 检索 → 全局去重 → 来源分册 → 截图证据 → 研究综述/报告。不输出成立/不成立。
- 断言查证（claimlab/pipeline.py）：断言抽取 → 定向查询 → 检索 → 去重 → 分级 → 匹配（引文子串校验）→ R1–R5 → 判定报告。R5 时才附加模型参考意见，明确标注“非判定”。
- 共用：检索网关、来源分级、安全护栏、缓存/预算/审计。

### 2.2 查询与 subject/city

- 公共请求模型只保留 text/refresh/plan_id/search_off；subject、city、example_id、fixture_id 已删除，旧客户端传这些字段会得到 422。
- Requirement 新增 focus；LLM 返回 focus，启发式兜底为需求文本；查询模板只使用 focus 与 terms，不再存在 subject/city 占位符。
- /api/plan 与 /api/research 共用 claimlab/planning.py；PlanStore（TTL 15 分钟）保存 plan_id；/api/research 带 plan_id 时执行预览中的初始查询，并返回 plan_reused。
- 候选 fallback 查询明确“按检索结果条件触发”，避免预览与执行被误解为完全一致。

### 2.3 去重与指标

- 深度研究对所有查询结果做一次全局 URL + 5-gram Jaccard 聚簇；来源分册与引用以 cluster 为单位，同一转载簇只出现一次。
- 指标改为 metrics_version=2：pages_raw、pages_unique、duplicates_removed、clusters、relevant_unique、grade_counts、a_source_rate、ab_source_rate、c_source_rate、directed_query_rate、screenshots。
- 修复跨需求重复计数导致 ab_source_rate > 100% 的问题；全局 grade 计数按唯一页取最佳字段等级，sum(grade_counts)=relevant_unique。
- URL-less 页面 key 改为基于 title/domain/date/passage 的稳定哈希，pipeline 与 dedup 使用同一键。

### 2.4 回答阶段与截图

- build_answer 的模型输入只含 [n]、grade、title、domain、date、URL；passage/content 只用于 UI 展示与截图定位，不进入模型 payload（有测试断言）。
- claimlab/evidence/capture.py：无头 Chrome + CDP，打开公开页面、查找摘要、高亮滚动、JPEG 截图；SSRF 校验只允许公网 http/https；失败返回 error，不阻塞。
- claimlab/evidence/store.py：截图只存内存（TTL 30 分钟、最多 20 个 run）；GET /api/evidence/{run_id}/{n} 提供。
- LLM 客户端支持 images（OpenAI vision image_url）；vision 400/422 时禁用该 provider 的 vision 并纯文本重试。
- citations.py：越界 [n] 标记为 [n?]；无有效引用退回规则摘要；citation_issues 进入响应/UI/报告。

### 2.5 不持久化

- run_research 不再写 sandbox.store；answer/report 不落库；截图不落盘。
- /api/db/* 保留旧数据只读；README/PROJECT_PLAN 明确主路径不再写入。

### 2.6 UI

- 三个标签：深度研究 / 断言查证 / 报告。
- 深度研究：生成查询计划、开始研究、来源分册、截图缩略图、指标、引用校验提示。
- 断言查证：POST /api/runs + EventSource 进度；判定卡显示 verdict/rule_id/分层/簇计票/证据引文；R5 advisory 块。
- 报告：研究综述或断言报告；打印样式隐藏标签/按钮；宽度统一到 960px；notice/tabs 与内容对齐。
- 删除 DEMO 徽标/示例入口；无 Key 显示“未配置检索”。

---

## 3. 代码与文档变更

| 类型 | 内容 |
|---|---|
| 删除 | claimlab/demos.py；demos/；examples/；scripts/prepare_demos.py；scripts/run_example*.py；/api/examples；/api/fixtures；example_id/subject/city/fixture_id 公共字段 |
| 新增 | claimlab/planning.py；claimlab/evidence/；claimlab/skills/citations.py；claimlab/skills/advisory.py；scripts/run_research.py/run_verify.py/run_plan.py；8 个测试文件 |
| 重写 | claimlab/api.py；claimlab/research.py；claimlab/skills/answer.py；claimlab/skills/research_report.py；web/app.js/index.html/rules.html |
| 适配 | contracts/config/keys/llm client/pipeline/runs/runtime/requirements/query/dedup/extraction/safety/reporting/store；config/queries.json/llm_providers.json；.env.example；requirements.txt（+websockets） |
| 文档 | README、PROJECT_PLAN、logs/README、PROJECT_ANALYSIS（标注 v2.6 历史）；framework.html（archify v3.0） |

---

## 4. 验证方案设计

### 4.1 单元测试（确定性）

- 需求拆分与 focus 兜底；共享 planner 的 plan_id 复用/过期；查询模板不含 subject/city。
- 去重：转载聚簇、顺序无关、URL-less 稳定 key。
- 判定：R1/R2/R2b/R3/R4/R5/分层/计票。
- 回答：无 passage 进入 payload；[n] 越界/无引用回退；截图元数据不污染正文。
- 截图：公网 URL 白名单/私网拒绝；内存 store TTL；vision 消息形状。
- advisory：仅 R5 调用；不覆盖 verdict。
- 预算：单断言/单次/单日/缓存不扣费。

### 4.2 API 集成（TestClient + fake provider/LLM）

- /api/examples、/api/fixtures 已删除（404）。
- 旧字段 example_id/subject 返回 422。
- /api/plan → plan_id → /api/research 的 queries 完全一致，plan_reused=true。
- 无 Search Key 时 503；时政/超长输入 400/422。
- /api/runs 异步完成，/api/report 可取报告。
- 深度研究不触发 Store 写入。

### 4.3 真实 API 冒烟

- 用真实 SearchPro 跑一条深度研究（西安城墙问题）：6 次检索、60 原始结果、29 去重、31 重复、2 个需求；指标一致性检查。
- 截图：真实页面 1 张成功、1 张超时；失败降级。
- LLM：当前 .env 的 LLM Key 返回 HTTP 401 API_KEY_DISABLED；真实回答按设计退回规则摘要，未触发 vision。
- 缓存复用：同问题第二次 0 次扣费、3 次缓存命中。

### 4.4 UI 实测

- 无头 Chrome 实际操作：深度研究完成、来源分册显示 2 页/1 簇/2 条同源；断言查证产出 2 张判定卡（conflict/R3）；报告页可打印。
- 截图：v3-home、v3-research、v3-verify、v3-report、v3-framework。

### 4.5 框架图

- archify finalize workflow v3.0：validate/deliver/check/browser-check 全部 pass；13 节点、3 卡片、2 个 guided view；产物 774,178 bytes。
- 自动门禁通过但 visual review 提示 3 条绕行（input→decompose、input→extract、synthesis→ui）；已人工查看截图，布局可读，仍有可选的美化空间。

---

## 5. 实际验证结果

| 项目 | 结果 |
|---|---|
| pytest | 103 passed in 7.2s |
| 8000 实例 | 已重启 v3.0；/api/health 200，search_ready/llm_ready/screenshots_ready 均 true |
| /api/plan | 真实调用成功（LLM 401 时回退 heuristic/template），返回 plan_id + 3 条查询 |
| 真实深度研究 | 跑通；来源分册/指标/引用正常；因 LLM Key 禁用，answer.engine=rule |
| 截图 | Chrome CDP 成功生成 JPEG；真实 run 1 张成功、1 张 timeout；端点/内存存储可用 |
| UI | 深度研究/断言查证/报告三标签实测通过 |
| 框架图 | archify 四门禁通过，已替换 framework.html |
| 工作区 | 分支 refactor/v3-two-boards；无临时文件；主路径不写 DB |

---

## 6. 预期验证结果（LLM Key 可用时）

1. 深度研究生成带 [n] 的研究综述；截图作为 vision 输入，模型能引用截图中的页面内容；citation_issues 为空或仅含可解释标记。
2. 断言查证 R1–R5 正常；R5 时 advisory 文本出现且不改变 verdict/rule_id。
3. 截图失败/vision 不支持时，回答仍返回规则摘要或纯文本综述，不报 500。
4. 同问题 plan_id 复用时，执行查询与预览一致；不同 text 搭配旧 plan_id 返回 400。
5. 无 Search Key 时 503；旧字段 422；超长/时政 400/422。

---

## 7. 关键风险

| 等级 | 风险 | 处置/建议 |
|---|---|---|
| 高 | 当前 LLM Key 被禁用（401），模型综述/vision 未真实验证 | 换可用 Key 后重启，按第 6 节预期验收 |
| 中 | 截图受登录墙/反爬/动态页影响，可能超时 | best-effort + 降级；监控 screenshot_error 比例 |
| 中 | 截图会访问外部页面，存在隐私/合规边界 | 只抓公网 URL、SSRF 校验、不落盘、TTL；按站点政策使用 |
| 中 | 主路径不持久化，刷新/重启丢报告 | 明确产品边界；后续需要再加 archive/DB |
| 中 | 无鉴权/限流，APP_API_TOKEN 未启用 | P3 前只在本机使用，不要暴露 0.0.0.0 |
| 中 | plan_id 存内存，重启/过期后重规划 | 返回 plan_reused=false；可接受 |
| 低 | framework 图 3 条绕行，自动门禁通过但非最优 | 可选再调布局 |
| 低 | 旧 /api/db/* 历史数据与新主路径无关联 | README 已标注只读 legacy |
| 低 | websockets 依赖新增 | requirements 已更新；无 Chrome 时截图自动禁用 |

---

## 8. 后续建议

1. 立即：替换可用 LLM Key，重启 8000，按第 6 节跑三条验收（深度研究/断言查证/截图）。
2. 发布：review 分支 diff；合并 main、推送远端（当前未推送）；更新演示视频素材。
3. P1：把 skills 做成独立包/registry；把截图服务做成可配置的 provider。
4. P2：如需历史/复盘，恢复 answer/report 持久化（archive JSONL 或 DB），但需明确隐私与保留策略。
5. P3：APP_API_TOKEN、限流、并发上限、截图域名白名单、日志脱敏、缓存/archive 清理。
6. 质量：补充真实 LLM 的 vision 回归样例；监控截图成功率与回答引用有效率。

---

## 9. 交付物

- 分支：refactor/v3-two-boards（commit 见 git log）
- 代码：claimlab/、web/、scripts/、tests/
- 文档：README.md、PROJECT_PLAN.md、web/rules.html、framework.html
- 证明：deliverables/screenshots/v3-home.png、v3-research.png、v3-verify.png、v3-report.png、v3-framework.png
- 框架产物：.archify/workflow-two-board-v3-20261025-0218/（candidate.html/finalize/browser-check）

以上为 v3.0 实施方案的落地报告与验证设计。
