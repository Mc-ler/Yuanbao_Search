# GitHub 推送与 GitHub Pages 上线指南（2026-10-25）

- 仓库：`https://github.com/Mc-ler/Yuanbao_Search`
- 默认分支：`main`
- Pages 站点目录：`docs/`
- 部署工作流：`.github/workflows/pages.yml`
- 线上地址：`https://mc-ler.github.io/Yuanbao_Search/`

## 0. 本次实际结果（已验证）

| 项目 | 结果 |
|---|---|
| 推送 | `main` 已推送；远端最新提交以 GitHub 仓库为准 |
| Pages | 已启用，`build_type=workflow`，`https_enforced=true`，无自定义域名 |
| Actions | 首次上线 run 成功：Configure Pages / Upload / Deploy 全部 success |
| 首页 | `200 text/html`，包含“万物皆可查” |
| 资源 | `assets/desktop.png` / `logo-light.png` 均为 `200 image/png` |
| 404 | 返回自定义 404（“这个页面不在项目介绍站里”） |
| HTTPS | `http://` 301 到 `https://` |
| 自定义域名 | 未配置（`cname=null`） |

> 第一次 `Configure Pages` 失败，是因为仓库当时尚未启用 Pages，`GITHUB_TOKEN` 没有管理员权限去创建站点；在 Settings → Pages（或用管理员 token 调用 `POST /repos/{owner}/{repo}/pages`，`build_type=workflow`）启用后，重新运行同一 workflow 即成功。以后新 fork/新仓库若未启用 Pages，同样需要先启用一次。

> **重要边界**：GitHub Pages 只能托管静态文件。本项目的完整检索/查证需要 Python FastAPI、SearchPro 与 DeepSeek 后端，**不能只靠 Pages 运行**。本 Pages 站点是项目介绍、截图与文档入口；完整应用请按 README 本地启动，或把后端部署到独立服务器后再让静态页指向它。

---

## 1. 本次已准备好的内容

| 文件 | 作用 |
|---|---|
| `docs/index.html` | Pages 项目介绍页（相对路径，适配 `/Yuanbao_Search/` 子路径） |
| `docs/assets/` | LOGO 与桌面/移动端截图 |
| `docs/.nojekyll` | 关闭 Jekyll，保证静态资源原样发布 |
| `docs/404.html` | 自定义 404 |
| `.github/workflows/pages.yml` | push main 后用 Actions 构建并发布 `docs/` |

工作流使用 GitHub 官方 Pages Actions：

```
checkout → configure-pages (enablement: true) → upload-pages-artifact(path: docs) → deploy-pages
```

`configure-pages` 的 `enablement: true` 会在仓库尚未启用 Pages 时尝试自动启用；如果组织策略禁止，需要仓库管理员在 Settings → Pages 手动启用。

---

## 2. 推送前检查（在本机普通 PowerShell 执行）

### 2.1 确认敏感文件未被跟踪

```powershell
cd D:\AI_projects\YuanBao_Search

git check-ignore -v .env push.config.json state cache logs archive output .Search
git ls-files | Select-String -Pattern '(^|/)(\.env$|push\.config|state/|cache/|logs/|archive/|output/|\.Search/)'
```

期望：
- 第一条输出显示这些路径命中 `.gitignore`；
- 第二条为空（只有 `push.config.example.json` 这类示例可以保留）。

如果 `.env` 已经被跟踪过（历史提交里），仅加入 `.gitignore` 不会删除历史记录：

```powershell
git rm --cached .env
git commit -m "chore: stop tracking local .env"
```

如果密钥曾经进入历史提交，**立即在 DeepSeek/SearchPro 控制台轮换 key**；不要只删除文件。

### 2.2 快速密钥扫描

```powershell
git grep -nE 'sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_|BEGIN .*PRIVATE KEY|Authorization: Bearer [A-Za-z0-9._-]{20,}' -- .
```

注意：
- `.env.example` 里的空占位、README 里的 `sk-你的密钥` 不是真实密钥；
- 真实 key 只应存在于本机 `.env`（已 gitignore）；
- 若输出包含真实值，先轮换 key，再清理历史。

### 2.3 查看待提交内容

```powershell
git status --short
git diff --stat
```

本次预期包含：
- 研究/查证、LLM、Site、rerank、匹配、截图、日志、预算等代码改动；
- 新增测试、`pytest.ini`、诊断/截图脚本；
- `docs/` 与 `.github/workflows/pages.yml`；
- README、`.env.example`、`config/llm_providers.json`。

---

## 3. 提交与推送

### 3.1 提交

```powershell
git add -A
git status --short
git commit -m "feat: harden research pipeline, natural-language reports, and add Pages site"
```

### 3.2 处理与远端的差异

本地 `main` 可能领先/落后远端。先同步：

```powershell
git fetch origin
git status -sb
```

如果提示 `behind`：

```powershell
# 推荐线性历史
git rebase origin/main
# 或保留合并历史
# git merge origin/main
```

如果 `web/index.html` 冲突（远端可能是旧 `?v=4.3`），保留本地 `?v=4.5`，然后：

```powershell
git add web/index.html
git rebase --continue
```

### 3.3 推送

```powershell
git push origin main
```

认证方式：
- Git Credential Manager 弹窗登录 GitHub；
- 或使用 Personal Access Token（至少 `repo` / `contents:write`，Pages 配置另需 `pages:write`）；
- 企业 SSO 组织需要额外授权。

如果当前环境网络无法访问 `github.com:443`，请在**普通交互式 PowerShell**里执行；不要让 CI/沙箱代推。

---

## 4. 配置 GitHub Pages

### 方案 A：GitHub Actions（推荐）

1. 打开仓库 → **Settings → Pages**。
2. **Build and deployment → Source** 选择 **GitHub Actions**。
3. push `main` 后，Actions 会自动运行 `Deploy GitHub Pages`。
4. 在 Actions 运行记录里确认：
   - `Configure Pages` 成功；
   - `Upload static site` 成功；
   - `Deploy to GitHub Pages` 成功，输出 `page_url`。
5. 打开 `https://mc-ler.github.io/Yuanbao_Search/`。

如果 `configure-pages` 报权限/未启用：
- 确认 Settings → Pages 已选择 GitHub Actions；
- 确认 workflow 权限包含 `pages: write`、`id-token: write`；
- 组织仓库可能禁止 Pages，需要管理员开启。

### 方案 B：从分支发布（不使用 Actions）

1. Settings → Pages → Source：**Deploy from a branch**。
2. Branch：`main`，Folder：`/docs`。
3. Save。
4. 等待 “Your site is live at …”。

`docs/.nojekyll` 已存在，避免 Jekyll 忽略 `_` 开头的静态文件。

> 两种方案不要同时用来发布不同内容；如果使用分支发布，可以禁用/删除 `pages.yml` 的触发，避免混淆。

---

## 5. 自定义域名与 HTTPS（可选）

当前没有配置自定义域名，默认使用：

```
https://mc-ler.github.io/Yuanbao_Search/
```

`*.github.io` 默认支持 HTTPS。

如需自定义域名：

### 5.1 子域名（推荐，例如 `search.example.com`）

DNS 添加：

```
CNAME  search  mc-ler.github.io.
```

### 5.2 根域名（例如 `example.com`）

在 DNS 添加 GitHub Pages 的 A 记录（以 GitHub 官方文档当前值为准）：

```
185.199.108.153
185.199.109.153
185.199.110.153
185.199.111.153
```

以及 AAAA：

```
2606:50c0:8000::153
2606:50c0:8001::153
2606:50c0:8002::153
2606:50c0:8003::153
```

### 5.3 在 Pages 设置里绑定

1. Settings → Pages → Custom domain → 输入域名 → Save。
2. 等待 DNS check 通过。
3. 勾选 **Enforce HTTPS**。
4. 证书签发可能几分钟到 24 小时；期间先用 `http://` 验证，再等 HTTPS。

如果使用 Actions 发布，添加 `docs/CNAME`（内容为域名）或在 `configure-pages` 里设置 `cname`，否则每次部署可能清掉自定义域名。**没有域名时不要创建 CNAME 文件。**

---

## 6. 上线验证

```powershell
# 首页
curl.exe -I https://mc-ler.github.io/Yuanbao_Search/

# 关键静态资源
curl.exe -I https://mc-ler.github.io/Yuanbao_Search/assets/desktop.png
curl.exe -I https://mc-ler.github.io/Yuanbao_Search/assets/logo-light.png

# 页面内容
curl.exe -s https://mc-ler.github.io/Yuanbao_Search/ | Select-String '万物皆可查'
```

期望：
- 首页 200，`content-type: text/html`；
- 资源 200，图片正常；
- 不出现仓库 README 的 404；
- 若配置了自定义域名，`http://` 自动 301 到 `https://`（Enforce HTTPS 后）。

Pages 首次发布可能有 1–2 分钟延迟；Actions 成功但页面仍旧 404 时，先看 Settings → Pages 的 “Your site is live at”。

---

## 7. 常见推送 / 部署问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `403 Permission denied` | token 权限不足/SSO 未授权/凭据过期 | 重新登录 GCM；PAT 勾选 `repo`；SSO 组织授权 |
| `non-fast-forward` | 远端有新提交 | `git fetch origin` → `git rebase origin/main` 或 merge |
| `protected branch` | main 受保护 | 新建分支 → PR → 通过检查后合并 |
| `secret scanning` 阻止 push | 提交里含真实 key | 轮换 key；从提交/历史移除；不要只改 `.env` |
| `file exceeds 100 MB` | 大文件进入 Git | 用 Git LFS 或从历史移除；不要提交 `output/`、`archive/` |
| 已跟踪文件无法被 ignore | `.gitignore` 只影响未跟踪文件 | `git rm --cached <path>` 后再提交 |
| Pages 404 | Source/分支/目录不对，或尚未发布 | Settings → Pages 选 Actions 或 main `/docs`；看 Actions 日志 |
| Pages 页面无样式 | 资源用了绝对 `/assets/...` 或 Jekyll 处理 | 使用相对路径；保留 `.nojekyll` |
| Actions 失败 `Resource not accessible by integration` | 缺少 `pages: write`/`id-token: write` | 修 workflow `permissions`；确认 Pages 已启用 |
| `configure-pages` 报未启用 | 组织策略/仓库设置 | 管理员在 Settings → Pages 手动启用 |
| 自定义域名 404/证书 pending | DNS 未生效/CNAME 冲突 | `dig`/`nslookup` 检查；删除冲突 CNAME；等证书 |
| Enforce HTTPS 灰色 | 证书未签发 | 等 DNS 生效与证书签发；先用 http 验证 |
| 私有仓库 Pages 不可用 | 账户计划限制 | 公开仓库或升级计划；企业策略另算 |
| 页面能开但功能不可用 | Pages 只有静态页，没有 FastAPI 后端 | 本地运行 8000，或单独部署后端并配置 API 地址/CORS |

---

## 8. 与完整应用的关系

- GitHub Pages：项目介绍、截图、文档入口（`docs/`）。
- 本地应用：`http://127.0.0.1:8000`，需要 SearchPro/DeepSeek key、Chrome/Edge。
- 如果以后要让 Pages 上的静态 UI 调用远程后端：
  1. 后端部署到可公网访问的 HTTPS 地址；
  2. 前端增加可配置 API base（当前使用相对 `/api`）；
  3. 后端启用 CORS（只允许 Pages 域名）；
  4. 不要把 SearchPro/LLM key 放进前端或 Pages。
