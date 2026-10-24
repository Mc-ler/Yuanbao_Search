# 元宝搜索 Research Agent · 项目规划（v3.0）

> 更新时间：2026-10-25（Asia/Shanghai）
> 当前基线：v3.0 双板块；103 个测试通过；无预置示例/演示。

## 0. 结论

1. 项目从“单页研究 + 预置演示 + legacy 判定”重构为两个并列主路径：**深度研究**与**断言查证**。
2. **预置层已删除**：demos/、examples/、match_demo、example_id、prepare_demos、/api/examples、/api/fixtures；视频展示使用真实查询 + 剪辑。
3. **subject/city 已彻底移除**：公共 API 不再接受；查询只使用 Requirement.focus（LLM 派生，文本兜底）。
4. **/api/plan 与 /api/research 共用 planner**：plan_id 可把预览查询原样交给执行；候选回退按检索条件触发。
5. **深度研究**：3 条/需求查询 → 检索 → 全局去重 → 来源分册 → 截图证据 → 研究综述/报告；不输出成立/不成立。
6. **断言查证**：抽取 → 查询 → 去重 → 分级 → 匹配 → R1–R5 → 判定报告；R5 时可附加非约束性模型参考意见。
7. **回答阶段不传完整正文**：只传引用元数据和页面截图；截图 best-effort，失败降级。
8. **主路径不持久化**：不写 SQLite，answer/report 不落库，截图只存内存；/api/db/* 仅旧数据只读。

## 1. 目标与状态

| 层 | 目标 | 状态 |
|---|---|---|
| P0 · 可运行 MVP | 问题 → 需求 → 查询 → 检索 → 证据 → 研究/判定 | v3.0 完成 |
| P1 · Skills 包 | 技能独立调用 + registry | 未开始 |
| P2 · Research Agent | 工具编排、引用/截图校验 | 部分（截图/引用已入） |
| P3 · 部署 | 容器、SSE 重放、Token、限流、清理 | 未开始 |

## 2. 架构

    Web UI
      ├─ 深度研究 /api/research（同步）
      │   S1 需求拆分（focus）
      │   → S2 LLM 查询（3 条/需求，模板回退）
      │   → S3 检索网关（缓存/预算/审计）
      │   → S4 全局去重（URL + 5-gram 聚簇）
      │   → S5 来源分级 + 来源分册
      │   → S8 研究综述（截图证据 + [n] 校验）
      │   → 研究报告（来源分册/指标/证据缺口）
      │
      └─ 断言查证 /api/runs（SSE）
          S1 断言抽取 → S2 定向查询 → S3 检索
          → S4 去重 → S5 分级 → S6 匹配（引文校验）
          → S7 R1–R5 → 判定报告 → R5 advisory（非判定）

| 模块 | 职责 | 代码 |
|---|---|---|
| 入口 | 研究/计划/查证/报告/截图 | claimlab/api.py、web/ |
| 共享 planner | 需求 + 查询 + plan_id | claimlab/planning.py |
| 深度研究 | 去重/分册/截图/综述 | claimlab/research.py |
| 断言查证 | R1–R5 判定 | claimlab/pipeline.py |
| 检索 | SearchPro、缓存、预算、审计 | claimlab/search/ |
| 技能 | S1–S9 + citations + advisory | claimlab/skills/ |
| 截图 | Chrome CDP + 内存图片 | claimlab/evidence/ |
| 存储 | fixtures / 旧 DB 只读 | claimlab/store/ |

## 3. 关键决策

- R1–R5 只用于断言查证；深度研究不伪造单一 verdict。
- 预算 4/28/400（单断言/单次/单日），墙钟 90 秒；文档与环境变量统一。
- 无 Search Key → 503；无 LLM Key → 只出规则摘要；无 Chrome/vision → 纯文本降级。
- 删除公共 fixtures/examples 入口；fixtures 仅测试使用。
- 主路径不持久化；旧 DB 端点保留只读，不再新增。
- 先分支 refactor/v3-two-boards，验收后合并 main。

## 4. 里程碑

| ID | 时间 | 目标 | 验收 |
|---|---|---|---|
| M3 | 10/25 | v2.6 UI + demo 快路径 | 85 测试 |
| M4 | 10/25 | v3.0 双板块；删除预置；focus/planner；去重/分册；截图/引用；R1–R5 UI | 103 测试；无 demo/example；UI 实测 |

## 5. 风险与降级

| 风险 | 处置 |
|---|---|
| LLM 模型不可用 | /models + preferred/default；失败回退模板/规则 |
| vision 不支持 | 400 后禁用 vision，纯文本重试 |
| 截图被登录墙/反爬拦截 | best-effort；失败标记，不阻塞 |
| 截图 URL 私网/SSRF | 只允许公网 http/https，DNS 解析校验 |
| 查询扩量耗额度 | 4/28/400；单需求 4 次；可调 |
| 无 LLM | 研究只出来源分册/规则摘要；断言用启发式 |
| 不持久化 | 刷新/重启丢报告；旧 DB 只读 |
| 旧客户端字段 | 422；README 写迁移 |

## 6. 待验证 / 决策

| ID | 事项 | 方式 | 方案 |
|---|---|---|---|
| V1 | 深度研究真实查询 | 浏览器/CLI 跑一条真实问题 | A 通过；B 需调 |
| V2 | 断言查证 R1–R5 | 跑一条可证伪说法 | A 通过；B 需调 |
| V3 | 截图证据 | 检查来源缩略图与降级 | A 通过；B 需调 |
| V4 | plan_id 一致 | 预览后执行，查询一致 | A 通过；B 需调 |
| D1 | framework v3.0 | archify 重绘 | A 已完成；B 暂缓 |
| D2 | 是否启用 Token/限流 | P3 | A 启用；B 暂缓 |

## 7. 变更记录

- v3.0（2026-10-25）：删除 demos/examples/example_id；双板块；focus；共享 planner/plan_id；全局去重/来源分册；截图证据/vision；引用校验；R1–R5 主路径 UI；不持久化；预算 4/28/400。
- v2.6（2026-10-25）：极简 UI；demo 快路径；subject/city 不注入；85 测试。
- v2.4（2026-10-24）：MCP 删除；cnt 字符串化；时间序列；SQLite；回答引用；82 测试。
