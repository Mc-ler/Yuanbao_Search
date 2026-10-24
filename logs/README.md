# logs/ · 本地运行日志规范

日志只用于本地排障，不提交仓库，不作为业务数据源。日志中禁止出现 API Key、Authorization 头、`.env` 内容或完整原始响应正文。

## 目录与命名

| 文件 | 用途 | 示例 |
|---|---|---|
| `app-YYYYMMDD.log` | FastAPI 启动、`/api/plan`、run 异常 | `app-20261024.log` |
| `run-<run_id>.log` | 单次 run 的搜索与判定摘要（可选） | `run-7dce1ebe0f3f.log` |
| `probe-search-YYYYMMDD-HHMMSS.log` | `probe_search.py` 的 API/MCP 探针 | `probe-search-20261024-170512.log` |
| `probe-llm-YYYYMMDD-HHMMSS.log` | 模型矩阵/LLM 探针 | `probe-llm-20261024-170512.log` |
| `example-<id>-YYYYMMDD-HHMMSS.log` | `run_example.py` 的查询规划 | `example-q1_statistics_bulletin-20261024-170512.log` |
| `debug-search-YYYYMMDD-HHMMSS.log` | `debug_search.py` 的查询对照 | `debug-search-20261024-170512.log` |

原始响应另存到 `probe/raw/` 或 `probe/debug/`，不入 `logs/`，因为体积大且可能含页面正文。

## 分级

| 级别 | 用途 |
|---|---|
| `DEBUG` | 查询模板、request 参数、缓存 key、候选路由 |
| `INFO` | 一次搜索完成、页数、官方域名数、provider、延迟 |
| `WARNING` | 0 结果、预算/缓存/降级、MCP transport 重试 |
| `ERROR` | 鉴权失败、4xx/5xx、provider 异常、run 异常 |
| `CRITICAL` | 启动失败、配置无法加载 |

默认 `INFO`；排障时在 `.env` 设 `LOG_LEVEL=DEBUG`，复现后改回。

## 格式

```text
2026-10-24 17:05:12,123 INFO claimlab.search event=search.done query=国家统计局 统计口径 pages=10 official=9 latency_ms=1437.0 domains=stats.gov.cn,...
```

- 一行一个事件，`event=` 后为结构化 `key=value`。
- `query`、`domains`、`pages`、`official` 必记；不记 key。
- 同一 run 用 `run_id` 关联；`search.start`/`search.done` 成对。

## 轮转与保留

- `RotatingFileHandler`：单文件上限 `LOG_MAX_BYTES`（默认 5,000,000），保留 `LOG_BACKUP_COUNT`（默认 5）个备份。
- 建议本地保留 14 天；`logs/` 已被 `.gitignore` 忽略，删除不影响功能。
- 排查“无信源”时先看 `search.zero`/`search.done` 的 `pages`、`official`、`domains`，再看 `probe/debug` 的原始页面。

## 相关配置

`.env`：

```dotenv
LOG_LEVEL=INFO
LOG_MAX_BYTES=5000000
LOG_BACKUP_COUNT=5
```

代码入口：`claimlab/logging.py`；搜索事件：`claimlab/search/gateway.py`；服务事件：`claimlab/api.py`；对照查询：`scripts/debug_search.py`。
