# 说法鉴定所 / YuanBao Research Agent

> 文字输入 → 元宝 SearchPro → LLM 需求拆分/查询构造 → 去重与来源分级 → 深度研究综述或 R1–R5 断言判定。

本 README 是统一入口文档，整合了架构、环境、DeepSeek/SearchPro 配置、运行、API、验证、日志、安全与路线图。交互规则见 <a href="web/rules.html">rules.html</a>，架构图见 <a href="framework.html">framework.html</a>。

## 目录

1. 项目定位与当前状态
2. 快速开始
3. 环境要求
4. 配置总览
5. DeepSeek LLM 接入（推荐）
6. 元宝 SearchPro 接入
7. 运行与停止
8. 架构与目录
9. HTTP API
10. 命令行
11. 证据、截图与引用
12. 测试与验证
13. 日志与排障
14. 安全、边界与路线图
15. 变更记录

---

## 1. 项目定位与当前状态

- <strong>深度研究</strong>：问题 → 1–3 条需求（focus）→ 每需求最多 3 条查询 → 检索 → 全局去重 → 来源分册 → 截图 → 研究综述/报告。输出综述与来源，<strong>不输出成立/不成立</strong>。
- <strong>断言查证</strong>：说法 → 断言抽取 → 定向查询 → 检索 → 去重 → 分级 → 匹配（引文校验）→ <strong>R1–R5 确定性判定</strong> → 报告。R5 时附加“非判定”模型参考意见。
- 共用检索网关、来源分级、安全护栏、缓存/预算/审计。

当前基线：v3.1；<strong>107 个测试通过</strong>；检索 100% 走 SearchPro；无预置示例/演示；主路径不持久化（截图仅内存）；预算 4/28/400。

---

## 2. 快速开始

Windows PowerShell：

    Copy-Item .env.example .env
    ./.Search/Scripts/python.exe scripts/configure_keys.py yuanbao
    ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider deepseek
    ./.Search/Scripts/python.exe scripts/test_deepseek.py
    ./.Search/Scripts/python.exe -m claimlab.api
    # http://127.0.0.1:8000

macOS/Linux：

    cp .env.example .env
    python scripts/configure_keys.py yuanbao
    python scripts/configure_keys.py llm --provider deepseek
    python scripts/test_deepseek.py
    python -m claimlab.api

没有 Search Key：研究/查证返回 503，UI 提示“未配置检索”；不会进入本地示例模式。没有 LLM Key：仍可检索/分级/来源分册，但只输出规则摘要。

---

## 3. 环境要求

| 项 | 要求 |
|---|---|
| Python | 3.11–3.13（本机 3.13.5） |
| 依赖 | fastapi、uvicorn、httpx、websockets、pytest（requirements.txt） |
| 浏览器 | Chrome 或 Edge（截图用；SCREENSHOT_CHROME 可指定） |
| 网络 | api.wsa.cloud.tencent.com、api.deepseek.com |
| 系统 | Windows 10/11 已验证；Linux/macOS 需确认 Chrome 路径 |

项目自带虚拟环境 <code>.Search</code>。安装：

    uv pip install --python ./.Search/Scripts/python.exe -r requirements.txt

或：

    ./.Search/Scripts/python.exe -m pip install -r requirements.txt

---

## 4. 配置总览（.env）

应用由 claimlab/config.py 解析 .env：只认 KEY=VALUE，忽略空行/注释；不覆盖进程已有环境变量（环境变量优先）；.env 已 gitignore，禁止提交密钥。

| 变量 | 默认/示例 | 用途 |
|---|---|---|
| SEARCH_PROVIDER | api | api 或 fake（fake 仅测试） |
| SEARCH_API_KEY | 空 | SearchPro 服务 key，裸值 |
| SEARCH_BASE_URL | https://api.wsa.cloud.tencent.com | SearchPro 基址 |
| LLM_PROVIDER | deepseek | 默认 LLM 供应商 |
| DEEPSEEK_API_KEY | 空 | DeepSeek 官方 key |
| DEEPSEEK_BASE_URL | https://api.deepseek.com/v1 | DeepSeek OpenAI 兼容基址 |
| LLM_MODEL | 空 | 显式模型；空则按 preferred/default + /models |
| LLM_API_KEY | 空 | 旧版单供应商回退；DeepSeek 不复用 |
| TOKLENS/GPT/CODEX_API_KEY | 空 | 可选旧供应商 |
| APP_HOST / APP_PORT | 127.0.0.1 / 8000 | 监听 |
| APP_API_TOKEN | 空 | 预留鉴权，当前未启用 |
| MAX_CALLS_PER_ASSERTION / RUN / DAY | 4 / 28 / 400 | 预算 |
| RUN_WALL_SECONDS | 90 | 墙钟 |
| DEDUP_THRESHOLD | 0.65 | 5-gram 去重阈值 |
| CACHE_TTL_HOURS | 72 | 缓存 TTL |
| MAX_CONCURRENT_RESEARCH | 2 | 并发 |
| EVIDENCE_SCREENSHOTS | true | 截图开关 |
| SCREENSHOT_CHROME | 空 | Chrome 路径 |
| SCREENSHOT_MAX / TIMEOUT_MS | 3 / 8000 | 截图上限/超时 |
| LLM_ADVISORY | true | R5 参考意见 |
| ALLOW_FAKE_SEARCH | false | 仅测试 |
| OFFLINE | false | 只读缓存 |
| LOG_LEVEL / MAX_BYTES / BACKUP_COUNT | INFO / 5000000 / 5 | 日志 |

完整模板见 .env.example。安全：key 只写 .env；configure_keys 使用 getpass；日志不记录 Authorization/完整正文；默认只绑 127.0.0.1。

---

## 5. DeepSeek LLM 接入（推荐）

项目通过 OpenAI 兼容协议调用 DeepSeek，支持 deepseek-chat / deepseek-reasoner，默认 deepseek-chat。

### 5.1 配置

1. 在 DeepSeek 开放平台创建 API Key。
2. 运行（输入隐藏）：

       ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider deepseek

   写入：

       DEEPSEEK_API_KEY=sk-...
       DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
       LLM_PROVIDER=deepseek

3. 手动编辑 .env 也可以：

       LLM_PROVIDER=deepseek
       DEEPSEEK_API_KEY=sk-你的密钥
       DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
       # 可选固定模型
       LLM_MODEL=deepseek-chat

4. 验证：

       ./.Search/Scripts/python.exe scripts/test_deepseek.py
       ./.Search/Scripts/python.exe scripts/test_deepseek.py --model deepseek-reasoner

成功输出 OK model=... latency=...ms、content 和 usage；缺 key 以 2 退出；401/402/429/5xx 给出明确错误。

### 5.2 Provider 配置

config/llm_providers.json 的 deepseek 片段：

    "deepseek": {
      "label": "DeepSeek (official OpenAI-compatible)",
      "base_url": "https://api.deepseek.com/v1",
      "base_url_env": "DEEPSEEK_BASE_URL",
      "api_key_env": "DEEPSEEK_API_KEY",
      "preferred_models": ["deepseek-chat", "deepseek-reasoner"],
      "default_model": "deepseek-chat",
      "timeout_seconds": 90,
      "vision": false,
      "legacy_key": false
    }

legacy_key=false 很关键：DeepSeek 不会误用旧的 LLM_API_KEY/TOKLENS_API_KEY，避免把 Toklens key 发给 DeepSeek 造成 401。

### 5.3 稳定性

- 每个 provider 独立 timeout（DeepSeek 90 秒），连接超时 10 秒。
- 429/500/502/503/504/传输异常最多重试 3 次（指数退避）。
- 模型候选：LLM_MODEL → preferred_models → default_model → /models；模型不存在时尝试下一个。
- JSON mode 失败自动去掉 response_format 重试。
- 缺 key/401/402 明确报错；应用层退回规则摘要，不阻塞报告。
- 健康检查只显示 key 是否存在，不保证余额/权限；演示前必须跑 test_deepseek.py。

### 5.4 调用示例

Python（项目内）：

    import asyncio
    from claimlab.config import load_settings
    from claimlab.llm.client import build_llm

    async def main():
        llm = build_llm(load_settings())
        data = await llm.json(
            "answer",
            {"question": "西安城墙现存主体是什么年代修建的？"},
            "你是研究助手，只输出 JSON。",
        )
        print(data)

    asyncio.run(main())

curl（PowerShell）：

    $key = $env:DEEPSEEK_API_KEY
    curl.exe https://api.deepseek.com/v1/chat/completions ^
      -H "Content-Type: application/json" ^
      -H "Authorization: Bearer $key" ^
      -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"返回 JSON"}],"temperature":0}'

curl（bash）：

    curl https://api.deepseek.com/v1/chat/completions \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
      -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"返回 JSON"}],"temperature":0}'

### 5.5 稳定演示检查

1. configure_keys 写入 DeepSeek key。
2. test_deepseek.py 返回 OK。
3. 重启 python -m claimlab.api。
4. /api/health 确认 provider=deepseek、key_present=true。
5. 先跑短问题确认 answer.engine=llm，再跑断言查证确认 R1–R5。
6. 失败时看 HTTP 状态、logs/app-*.log、test_deepseek 输出；不要把 key 贴到聊天/日志。

---

## 6. 元宝 SearchPro 接入

- 基址 https://api.wsa.cloud.tencent.com，接口 POST /SearchPro。
- Header Authorization: Bearer <SEARCH_API_KEY>；应用只拼一次 Bearer。
- Body：Query、Cnt（字符串 10/20/30/40/50）、Mode，可选 Site/Industry/Freshness。
- 响应：Response.Pages（JSON 字符串/数组/双层编码，已归一化）、RequestId、Version。
- 配置：scripts/configure_keys.py yuanbao。
- 健康检查不发起真实检索；演示前先跑一条短问题。

---

## 7. 运行与停止

启动：

    ./.Search/Scripts/python.exe -m claimlab.api
    # 或
    ./.Search/Scripts/python.exe -m claimlab.cli serve --host 127.0.0.1 --port 8000

改端口：

    $env:APP_PORT=8010
    ./.Search/Scripts/python.exe -m claimlab.api

健康：

    curl.exe http://127.0.0.1:8000/api/health

关注 search_ready、llm_ready、screenshots_ready、llm.model/provider、store（旧数据只读）。

停止：前台 Ctrl+C；后台先查 PID 再 taskkill /F /PID。端口占用：

    netstat -ano | findstr :8000
    Get-NetTCPConnection -LocalPort 8000 -State Listen

UI：

- 深度研究：输入问题 → 生成查询计划（可选）→ 开始研究 → 综述/指标/来源分册/截图。
- 断言查证：输入说法 → 开始查证 → SSE 进度 → 判定卡。
- 报告：查看/打印最近报告。
- 无示例按钮；演示视频用真实问题。

---

## 8. 架构与目录

深度研究：

    问题 → S1 需求拆分（focus）→ S2 共享 planner（3 条/需求）→ S3 检索网关
      → S4 全局去重 → S5 分级/来源分册 → S8 综述（截图 + [n]）→ 报告

断言查证：

    说法 → S1 断言抽取 → S2 定向查询 → S3 检索 → S4 去重 → S5 分级
      → S6 匹配（引文校验）→ S7 R1–R5 → 报告；R5 附 advisory（非判定）

目录：

    claimlab/
      api.py            FastAPI：研究/计划/查证/报告/截图
      planning.py       共享 planner + PlanStore
      research.py       深度研究
      pipeline.py       断言查证 R1–R5
      runtime.py        Sandbox
      contracts.py      数据契约
      config.py         Settings/.env
      keys.py           Bearer + provider registry
      search/           api/gateway/normalize/cache/budget/archive/fake
      skills/           requirements/query/dedup/grading/matching/judging/answer/report/advisory/citations/safety
      evidence/         Chrome CDP 截图 + 内存图片
      store/            fixtures / 旧 DB 只读
      llm/              OpenAI 兼容客户端 + FakeLLM
    web/                index.html / app.js / styles.css / rules.html
    config/             domains / queries / lexicons / llm_providers.json
    fixtures/           测试夹具
    scripts/            configure_keys / test_deepseek / run_research / run_verify / run_plan / probes / git_push
    tests/              107 个测试
    framework.html      v3.0 双板块架构图
    README.md           本文件

---

## 9. HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | / | Web UI |
| GET | /api/health | 版本/key/模型/缓存/截图 |
| GET | /api/skills | 技能及适用板块 |
| POST | /api/plan | 共享 planner，返回 plan_id |
| POST | /api/research | 深度研究 |
| POST | /api/runs | 断言查证（异步） |
| GET | /api/runs/{run_id} | 快照 |
| POST | /api/runs/{run_id}/cancel | 取消 |
| GET | /api/runs/{run_id}/events | SSE |
| GET | /api/report/{run_id} | 报告（format=md） |
| GET | /api/evidence/{run_id}/{n} | 内存截图 |
| GET | /api/db/* | 旧版只读 |

请求模型 extra=forbid；subject/city/example_id/fixture_id 返回 422。

/api/plan 示例：

    POST /api/plan
    {"text": "西安城墙现存主体是什么年代修建的？"}

返回 plan_id、domain、method、requirements、queries、fallback_queries、requery_queries。

/api/research 示例：

    POST /api/research
    {"text": "西安城墙现存主体是什么年代修建的？", "plan_id": "plan-..."}

返回 run_id、plan_id、plan_reused、requirements、queries、source_ledger、metrics、answer、report、citation_issues、screenshots、budget、stop_reason。

/api/runs 示例：

    POST /api/runs
    {"text": "该店人均68元，周一闭店。"}

返回 run_id；用 /api/runs/{id}/events 接收 SSE，或轮询 /api/runs/{id}。

错误码：400 空/安全/plan_id 不匹配；422 字段/超长；503 未配置 Search；502 研究异常；404 不存在/过期。

Python 客户端：

    import httpx
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=120) as client:
        plan = client.post("/api/plan", json={"text": "..."}).json()
        result = client.post("/api/research", json={"text": "...", "plan_id": plan["plan_id"]}).json()
        print(result["metrics"], result["answer"]["text"])

---

## 10. 命令行

| 命令 | 用途 |
|---|---|
| scripts/configure_keys.py yuanbao | 写入 Search key |
| scripts/configure_keys.py llm --provider deepseek | 写入 DeepSeek key |
| scripts/configure_keys.py show | 查看 key/模型选择 |
| scripts/test_deepseek.py | 真实 DeepSeek 连接测试 |
| scripts/run_research.py --text "..." --report | 终端深度研究 |
| scripts/run_verify.py --text "..." --report | 终端断言查证 |
| scripts/run_plan.py --text "..." | 只生成计划 |
| scripts/broad_search.py --focus "..." --field ... | 时间序列扩展 |
| scripts/probe_search.py | SearchPro 探针 |
| scripts/git_push.py | 提交/推送辅助 |

---

## 11. 证据、截图与引用

- 回答阶段只传引用元数据（标题/域名/日期/URL）与截图，不传完整正文。
- 截图：无头 Chrome 打开公开页面 → 查找摘要 → 高亮滚动 → JPEG；SSRF 校验只允许公网 http/https。
- 截图存内存（TTL 30 分钟），通过 /api/evidence/{run_id}/{n} 提供；不落盘。
- 登录墙/反爬/动态页可能超时，失败标记并降级，不阻塞报告。
- [n] 由程序校验；越界标记 [n?]；无有效引用退回规则摘要。
- DeepSeek 当前未配置 vision（vision=false）：截图展示给用户，但不发送给 DeepSeek；仅 vision provider 会作为图片输入。

---

## 12. 测试与验证

    ./.Search/Scripts/python.exe -m pytest -q

当前 107 passed。覆盖：需求拆分/focus/plan_id、去重与指标、R1–R5、advisory、回答不含 passage、引用校验、截图白名单/TTL/vision 形状、API 422/503/400、深度研究不写 SQLite。

真实 DeepSeek 验证：配置 key → test_deepseek.py OK → 重启 → 深度研究 answer.engine=llm → 断言查证 R1–R5。没有 key 时 test_deepseek.py 明确提示；应用层回退规则摘要，不抛 500。

---

## 13. 日志与排障

日志在 logs/（gitignored）：app-YYYYMMDD.log、research-*.log、verify-*.log、probe-*.log；RotatingFileHandler（5MB×5）；默认 INFO；排障可 LOG_LEVEL=DEBUG。事件格式一行一个 event=...，含 query/pages/domains/latency，不记录 key。

| 现象 | 排查 |
|---|---|
| 503 | 检查 SEARCH_API_KEY、/api/health.search_ready |
| LLM 401/402 | 检查 DEEPSEEK_API_KEY、余额、base_url；跑 test_deepseek.py |
| LLM 429/5xx | 客户端已重试；降低并发/稍后；看 logs |
| engine=rule | LLM 不可用或无有效引用；看 test_deepseek/logs |
| 截图 404 | TTL 过期或 run_id 不对；重新研究 |
| 截图超时 | 登录墙/反爬；可 EVIDENCE_SCREENSHOTS=false |
| 旧客户端 422 | 删除 subject/city/example_id/fixture_id |
| 端口占用 | 查 PID 后停止旧进程 |
| 缓存旧结果 | 删除 cache/ 或用 refresh（CLI） |

---

## 14. 安全、边界与路线图

安全：不提交 .env/key/Authorization/原始正文；默认 127.0.0.1；公网前启用 APP_API_TOKEN、限流、HTTPS；截图 SSRF 防护；入口拦截时政/个人/超长；日志脱敏；不评价个人，不构成消费/法律建议。

边界：深度研究是综述不是判定；不抓全文；主路径不持久化（刷新/重启丢报告，/api/db/* 旧数据只读）；截图 best-effort；DeepSeek 当前未配置 vision；无鉴权限流；plan_id 存内存；仅文字输入，不做 OCR/持续盯梢/B 端后台/公网部署。

路线图：P1 Skills 包；P2 Research Agent；P3 部署（容器/SSE 重放/Token/限流/清理）；质量（真实 DeepSeek 回归、截图成功率、vision provider）；发布（review/推送/录制真实查询视频）。

---

## 15. 变更记录

- v3.1（2026-10-25）：DeepSeek provider（默认）、密钥隔离、重试/超时、test_deepseek.py、configure_keys deepseek、README 统一整合、清理冗余文档/运行产物。
- v3.0（2026-10-25）：双板块、删除预置、focus/plan_id、全局去重/来源分册、截图/vision、引用校验、R1–R5 UI、不持久化、预算 4/28/400。
- v2.6（2026-10-25）：极简 UI、demo 快路径（已删除）、subject/city 不注入、85 测试。
- v2.4（2026-10-24）：MCP 删除、cnt 字符串化、时间序列、SQLite、回答引用。

---

相关文件：.env.example、config/llm_providers.json、web/rules.html、framework.html、deliverables/screenshots/v3-*.png。
