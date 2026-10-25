# 截图功能排查与启用指南（Windows）

- 适用版本：v4.3（`claimlab/evidence/capture.py`）
- 相关开关：`EVIDENCE_SCREENSHOTS`、`SCREENSHOT_CHROME`、`SCREENSHOT_MAX`、`SCREENSHOT_TIMEOUT_MS`
- 一键诊断：`scripts/test_capture.py`
- 结论先说：当前会话里 Chrome 能启动到一半，但 **crashpad 被宿主/安全软件拒绝 `OpenProcess`**，Chrome 自行退出；这是运行环境限制，不是研究/查证主链路的问题。截图是 best-effort，失败不应阻塞报告。

---

## 1. 截图是怎么工作的

```
研究/查证
  └─ ScreenshotCapturer.capture_many(sources[:SCREENSHOT_MAX])
       ├─ 公网 URL 校验（拒绝 localhost/私网/非 http(s)）
       ├─ 启动 Chrome：
       │    chrome --headless=new --disable-gpu ...
       │           --remote-debugging-port=0
       │           --user-data-dir=state/screenshot-profiles/shot-xxxx
       ├─ 等待 profile 下的 DevToolsActivePort
       ├─ 通过 CDP：Page.navigate → 等待 readyState → 高亮摘要 → Page.captureScreenshot(jpeg)
       └─ 成功：内存 EvidenceImageStore（TTL 30 分钟）→ /api/evidence/{run_id}/{n}
          失败：返回 error，降级为无截图报告；health 记录 last_error
```

- 只截公开页面；登录墙、反爬、动态页可能超时。
- 全局最多 2 个 Chrome 并发，单次研究最多 `SCREENSHOT_MAX`（默认 3）张。
- 截图不落盘（profile 除外）；报告只引用内存图片。
- Chrome 启动失败会自动重试一次；stderr 写入 profile 内 `chrome-stderr.log`，只把尾部放进 error。

---

## 2. 当前实测状态（2026-10-25）

```text
chrome       : C:\Program Files\Google\Chrome\Application\chrome.exe
websockets   : available
enabled      : True
reason       : -
profile_root : D:\AI_projects\YuanBao_Search\state\screenshot-profiles
error        : chrome exited before DevTools started:
               crashpad_client_win.cc:430 OpenProcess: 拒绝访问 (0x5)
               crash server failed to launch, self-terminating
bytes        : 0
```

**判读**：Chrome 进程已经创建，但在启动 crashpad（崩溃上报子进程）时被拒绝访问，Chrome 选择自杀；因此 `DevToolsActivePort` 永远不出现。常见于：
- DSH/受限令牌/沙箱/服务账户；
- 企业安全软件/EDR 阻止 Chrome 创建子进程或 `OpenProcess`；
- Windows AppContainer/Job Object 限制；
- 极少数 profile/临时目录 ACL 问题（本版已改到 `state/screenshot-profiles` 并用 `mkdir`，并把 stderr 留下来）。

补充：本会话用 Edge 替代也失败——默认超时报 `screenshot timeout`，放宽到 30s 后报 `ConnectionClosedError: no close frame received or sent`；直接 `msedge --headless=new --dump-dom about:blank` 同样无输出。说明是整个受限会话阻止了浏览器子进程，不是 Chrome 单一路径问题。普通交互式终端请再按第 2/3 步验证。

---

## 3. 建议的排查顺序（从最快到最彻底）

### 第 1 步：确认服务端认为截图可用

```powershell
$h = Invoke-RestMethod http://127.0.0.1:8000/api/health
$h.screenshots | Format-List
```

期望：
- `enabled=true`（`EVIDENCE_SCREENSHOTS=true` 且检测到 Chrome/Edge）
- `chrome=true`
- `reason` 为空
- `last_error` 为最近一次失败原因（成功后会清空）

如果 `enabled=false`：
- `reason=Chrome not found`：设置 `SCREENSHOT_CHROME` 或安装 Chrome/Edge。
- `reason=websockets not installed`：`./.Search/Scripts/python.exe -m pip install websockets`。
- `reason=EVIDENCE_SCREENSHOTS disabled`：把 `.env` 改成 `EVIDENCE_SCREENSHOTS=true` 并重启。

### 第 2 步：用独立脚本测试（普通 PowerShell）

```powershell
cd D:\AI_projects\YuanBao_Search
./.Search/Scripts/python.exe scripts/test_capture.py
./.Search/Scripts/python.exe scripts/test_capture.py --url https://www.stats.gov.cn/ --save state/shot.jpg
```

成功标准：
- `bytes > 0`
- `state/shot.jpg` 可打开
- `error` 为空

失败时把 `error` 最后 2–3 行发我；不要只发“截图失败”。

### 第 3 步：绕过应用，直接验证 Chrome headless

```powershell
& 'C:\Program Files\Google\Chrome\Application\chrome.exe' `
  --headless=new --disable-gpu --no-first-run `
  --dump-dom about:blank
```

- 有 HTML 输出、退出码 0：Chrome 本身可用，问题在应用参数/profile/CDP。
- 无输出、闪退、或同样 crashpad `OpenProcess`：Chrome 在当前会话/权限/安全策略下不可用，应用侧无解。

再试 Edge：

```powershell
& 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe' `
  --headless=new --disable-gpu --dump-dom about:blank
```

Edge 能跑而 Chrome 不能时，把 Edge 路径写进 `.env`：

```dotenv
SCREENSHOT_CHROME=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe
```

重启 8000 后再跑第 2 步。

### 第 4 步：确认 profile 目录可写

```powershell
$p = Join-Path (Get-Location) 'state\screenshot-profiles'
New-Item -ItemType Directory -Force -Path $p | Out-Null
"x" | Set-Content -LiteralPath (Join-Path $p 'write-test.txt') -Encoding ascii
Get-Content (Join-Path $p 'write-test.txt')
```

- 能写：profile 没问题，继续第 5 步。
- 拒绝访问：把 `state/screenshot-profiles` 的权限恢复给当前用户，或临时把 `state` 移到可写位置；不要给 `Everyone` 全盘权限。

### 第 5 步：安全软件/EDR/组策略

crashpad 的 `OpenProcess: 拒绝访问 (0x5)` 通常不是代码能修的。检查：
- 是否在 DSH 沙箱、CI、Windows 服务、受限令牌、AppContainer、Job Object 中运行；
- 360/火绒/Defender/EDR 是否拦截 Chrome 子进程；
- 企业组策略是否禁用 Chrome 崩溃上报/子进程；
- 临时在**普通交互式用户 PowerShell**（不是管理员也不是服务）中启动 8000，再试。

如果必须在受限环境运行：
- 申请把 `chrome.exe` 及其子进程加入白名单；
- 或换 Edge/Chromium 的可执行路径；
- 不要为了截图随便加 `--no-sandbox`：截图会打开不受信任的公网页面，关闭浏览器沙箱会扩大攻击面。若你明确接受风险，可在本地临时测试，但不建议作为默认配置。

### 第 6 步：仍然失败时关闭截图

截图不是核心链路；失败只会少证据图，不影响检索、引用、R1–R5。

在 `.env`：

```dotenv
EVIDENCE_SCREENSHOTS=false
```

或在 UI 顶部关闭“截图”开关，然后重启/刷新。研究/查证会跳过截图，速度更快。

---

## 4. 常见错误对照

| health/脚本错误 | 含义 | 处理 |
|---|---|---|
| `Chrome not found` | 未检测到浏览器 | 安装 Chrome/Edge，或 `SCREENSHOT_CHROME` 指到 exe |
| `websockets not installed` | 缺少 CDP 客户端 | `pip install websockets` |
| `blocked non-public URL` | SSRF 防护拒绝私网/localhost | 只能截公网 http(s) 页面 |
| `profile dir unavailable` | profile 目录不可写 | 修 `state/screenshot-profiles` 权限 |
| `chrome exited before DevTools started` + crashpad `OpenProcess` | Chrome 被安全策略/沙箱阻止 | 普通终端运行、白名单、换 Edge；否则关闭截图 |
| `chrome DevTools port not found` | Chrome 起来了但没写端口 | 检查 profile 权限/Chrome 参数/安全软件 |
| `screenshot timeout` | 页面加载慢/登录墙/反爬 | 换公开页；调大 `SCREENSHOT_TIMEOUT_MS`；关闭截图 |
| `empty screenshot` | CDP 返回空 | 重试；检查页面是否白屏 |
| `evidence image not found or expired` | 内存图 TTL 30 分钟过期 | 重新运行研究 |

---

## 5. 成功后的验收

```powershell
# 1) 独立 capture
./.Search/Scripts/python.exe scripts/test_capture.py --url https://www.stats.gov.cn/ --save state/shot.jpg

# 2) health
$h = Invoke-RestMethod http://127.0.0.1:8000/api/health
$h.screenshots | Format-List

# 3) 一次研究后
$r = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/research `
  -ContentType 'application/json' `
  -Body '{"text":"西安城墙现存主体是什么年代修建的？"}'
$r.metrics.screenshots
$r.answer.screenshots
```

期望：
- `screenshots.last_error` 为空；
- `metrics.screenshots > 0`；
- `answer.screenshots` 里有 `captured=true` 与 `/api/evidence/...` URL；
- 浏览器报告里出现截图缩略图。

---

## 6. 代码位置

- `claimlab/evidence/capture.py`：Chrome 检测、SSRF、profile、CDP、重试、stderr。
- `claimlab/research.py`：`capture_many(citations[:SCREENSHOT_MAX])`。
- `claimlab/evidence/store.py`：内存图片 TTL。
- `claimlab/api.py`：`/api/evidence/{run_id}/{n}`、`/api/config/screenshots`。
- `scripts/test_capture.py`：独立诊断脚本。
