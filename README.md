# link-monitor —— 自建资源检测 + 发布流程

照着 `awesome-zhuiju-free` 的机制搭的通用版：**数据驱动 → 每天自动检测 → 生成静态导航页 → 发布**。资源内容完全由你自己放（合法网站、自建服务、订阅源都行），项目只提供"检测+发布"的工程框架，零第三方依赖。

> **推荐部署方式：飞牛 NAS 服务端（方式 A）**。管理员口令和 GitHub Token 都留在 NAS 上，管理页登录后一键保存，浏览器全程拿不到凭据。GitHub Pages 只用来给别人看。详见第五节。

## 一、它做了什么

```
resources/resources.json   ← 你维护的资源清单（唯一数据源）
        │
        ▼  每天定时
scripts/check.py           ← 刷新 GitHub Star → 自动算评分 → 并发检测可用性 → reports/availability.json
        │
        ▼
scripts/publish.py         ← 合并数据 + 检测结果 → index.html（静态导航页）
        │
        ▼
GitHub Pages / NAS 静态服务器 ← 对外发布
```

和原项目一样的设计：检测脚本纯标准库、并发请求、超时重试、状态分级（`reachable`/`restricted`/`unreachable`），报告回写 + 静态页重新生成。

## 二、目录结构

```
link-monitor/
├── resources/
│   ├── resources.json      # 资源数据（你要改的就是这个）
│   └── schema.json         # 字段结构定义
├── reports/
│   └── availability.json   # 每日检测报告（自动生成）
├── scripts/
│   ├── check.py            # 检测脚本
│   ├── publish.py          # 发布页生成脚本
│   └── set_admin_password.py  # 设置管理员口令（静态页 / 服务端）
├── server.py               # 服务端模式（NAS 部署，含登录与保存接口）
├── Dockerfile              # 容器镜像
├── docker-compose.yml      # 一键部署
├── .env.example            # 服务端配置模板（复制为 .env）
├── .github/workflows/
│   └── daily.yml           # GitHub Actions 每天 01:00 定时
├── run_daily.sh            # NAS 本地定时入口（不用容器时）
├── index.html              # 生成的静态发布页
├── admin.html              # 数据字段管理页（自动识别静态/服务端模式）
└── README.md
```

## 三、资源数据格式

`resources/resources.json` 每条资源：

```json
{
  "id": "唯一英文标识",
  "name": "显示名称",
  "url": "https://...",
  "category": "online_video | video_app | tvbox_config | magnet_search | cloud_search | subscription | subtitles | player | open_source",
  "summary": "一句话简介",
  "summary_short": "短简介",
  "tags": ["标签1", "标签2"],
  "access": { "requires_login": false, "free_level": "free", "regions": ["GLOBAL"] },
  "scores": { "more": 5, "speed": 5, "clean": 5, "stable": 5, "ease": 5 },
  "risks": { "copyright": "low", "safety": "low", "privacy": "low", "payment": "low" },
  "verification": { "status": "active", "last_checked": "2026-11-25", "method": "manual", "notes": "" },
  "source": { "submitted_by": "maintainer", "added_at": "2026-11-25" },
  "github": { "full_name": "owner/repo" },
  "featured": true,
  "enabled": true
}
```

- `enabled: false` 的资源不参与检测和发布（相当于原项目的失效停用）
- `category` 的中文名在 `publish.py` 顶部的 `CATEGORY_NAMES` 里改
- 只填必填字段（`id` / `name` / `url` / `category`）也能跑；其余字段可后补

## 四、自动评分（GitHub Star）

新增开源项目**不用手填 `scores`**：只要填 `github.full_name`，每天检测时脚本会：

1. 调 GitHub API 拉取最新 `stargazers_count` 和 `pushed_at`，写回 `github` 字段
2. 按 Star 数自动计算 1–5 分，写入 `scores` 的五个维度，并标记 `scores_source: "github-stars"`

换算公式（对数映射，保留 1 位小数）：

```
score = clamp(2.0 + log10(stars + 1) * 0.75, 1, 5)
```

| Star 数 | 0 | 100 | 1k | 10k | 100k+ |
|---|---|---|---|---|---|
| 分数 | 2.0 | 3.5 | 4.3 | 5.0 | 5.0 |

- 非 GitHub 资源（字幕站、播放器官网等）保留原有手填 `scores`
- 想强制保留自己的评分：给该资源加 `"scores_locked": true`，脚本会跳过并标记 `scores_source: "manual"`
- 发布页评分行会显示 `Star 自动` 小标记，方便区分自动 / 手填

## 五、部署方式（推荐 NAS 服务端）

三种方式可以单用，也可以组合：**NAS 管后台，Pages 管展示**。

| | 方式 A：NAS 服务端 | 方式 B：GitHub Actions | 方式 C：NAS 纯静态 |
|---|---|---|---|
| 管理页鉴权 | **服务端**，无法绕过 | 浏览器端，懂技术可绕 | 无 |
| GitHub Token | 只存服务端，浏览器拿不到 | 需在页面填写，等于公开 | — |
| 保存资源 | 点一下即写入并推送 | 需每次填 PAT | 手动改文件 |
| 访问范围 | 内网（可穿透/反代） | 公网所有人 | 内网 |
| 运维成本 | 一个容器 | 零 | 一条 cron |
| 适合 | **自己维护资源（推荐）** | 给别人看的展示页 | 临时试用 |

### 方式 A：飞牛 NAS 服务端

把管理员口令和 GitHub 凭据都放在 NAS 上，浏览器只拿到一个登录 Cookie。

```bash
# 1. 目录放到 NAS
cd /vol1/1000/docker
git clone https://github.com/<你>/link-monitor.git

# 2. 生成管理员口令（只写哈希，不存明文）
cd link-monitor
python3 scripts/set_admin_password.py --target env --password '你的密码'

# 3. 填 GitHub PAT（保存时自动推送用，可留空先只存本机）
vi .env

# 4. 启动
docker compose up -d
```

打开 `http://<NAS_IP>:8801/` 就是导航页，`/admin.html` 是管理页，登录后加完字段直接点「保存到仓库」即可——**不需要填任何 Token**。

想让首页也每天自动检测，加一条 cron：

```bash
# 每天 08:30 在容器内跑检测 + 重新生成页面
30 8 * * * docker exec link-monitor /bin/sh -c "cd /app && python3 scripts/check.py && python3 scripts/publish.py" >> /vol1/1000/docker/link-monitor/reports/cron.log 2>&1
```

`.env` 关键项：

| 变量 | 说明 |
|---|---|
| `PORT` / `HOST` | 监听地址，默认 `8801` / `0.0.0.0` |
| `ADMIN_USER` / `ADMIN_PASS_HASH` | 管理员账号；口令用上面的脚本生成，只存 PBKDF2 哈希 |
| `SESSION_HOURS` | 登录有效期，默认 12 小时 |
| `GITHUB_TOKEN` | 只用服务端，**建议 fine-grained token，只授权本仓库 Contents 读写** |
| `GITHUB_REPO` / `GITHUB_BRANCH` / `GITHUB_PATH` | 推送目标，默认本仓库 `main` 的 `resources/resources.json` |
| `GITHUB_PROXY` | NAS 访问 GitHub 需要代理时填，如 `http://192.168.10.7:7890` |
| `PUBLISH_ON_SAVE` | 保存后是否立即重生成 `index.html`，默认 1 |
| `PROTECT_ALL` | 1 = 首页也要登录；0 = 首页公开、仅管理页需登录（推荐） |
| `COOKIE_SECURE` | 前面挂了 HTTPS 反代时设为 1 |

**安全设计**：登录状态是 HttpOnly Cookie，脚本无法读取；连续输错 5 次锁 60 秒；密码用 `hmac.compare_digest` 常数时间比较；静态文件有路径穿越防护；`/api/save` 会校验 id 唯一、地址协议、必填字段。`.env` 已在 `.gitignore` 里，不会被提交。

### 方式 B：GitHub Actions + Pages（公网展示）

1. 把整个目录推到一个 GitHub 仓库
2. Settings → Pages → Source 选 `main` 分支根目录
3. Workflow 已配置每天 UTC 01:00（北京时间 09:00）自动跑：检测 → 生成 → 提交 → 发布
4. 也可以随时在 Actions 页面手动点 `Run workflow`

访问地址：`https://<用户名>.github.io/<仓库名>/`

> 这种方式下 `/admin.html` 会退化为前端校验模式（页面里只有口令哈希，保存需要手填 PAT）。适合"给别人看"，不适合当自己的后台。

### 方式 C：NAS 纯静态（不推荐）

1. 把目录放到 NAS，例如 `/vol1/1000/docker/link-monitor`
2. 加 crontab：

```bash
# 每天 08:30 执行
30 8 * * * /bin/bash /vol1/1000/docker/link-monitor/run_daily.sh >> /vol1/1000/docker/link-monitor/reports/cron.log 2>&1
```

3. 用 NAS 自带的 Web 服务器指到该目录，或 `python3 -m http.server 8899`

> 没有服务端鉴权，管理页的口令只是前端遮挡。仅建议在完全可信的内网临时使用。

## 六、可调参数（检测脚本）


| 变量 | 默认 | 说明 |
|---|---|---|
| `CHECK_TIMEOUT` | 12 | 单个请求超时秒数 |
| `CHECK_WORKERS` | 6 | 并发线程数 |
| `CHECK_RETRIES` | 2 | 失败重试次数 |
| `GH_TIMEOUT` | 10 | GitHub API 请求超时秒数 |
| `GH_WORKERS` | 4 | GitHub API 并发数 |
| `GITHUB_TOKEN` | 空 | 检测脚本与服务端保存共用；Actions 自动注入，自建服务端则在 `.env` 里填 |
| `SKIP_AVAILABILITY` | 0 | 设为 `1` 时只刷新 Star / 评分，不跑可用性检测，适合本地调试 |

## 七、状态说明

发布页上每个资源卡片会显示检测状态和响应时间：
- **可访问**（绿）：HTTP 2xx/3xx
- **访问受限**（黄）：401/403/405/429，可能是反爬或需登录
- **无法访问**（红）：连接失败、超时、4xx/5xx

## 八、和原项目的差异

| 项 | 原项目 | 本方案 |
|---|---|---|
| 检测脚本 | Node.js `.mjs` | Python（零依赖） |
| 运行时 | GitHub Actions | GitHub Actions 或 NAS cron |
| 发布 | Typecho 站点 | GitHub Pages / 任意静态服务器 |
| 数据字段 | 20+（含评分/风险/验证） | 采用源站完整字段结构，20+ |
| 评分来源 | 人工维护 | GitHub Star 自动计算（可锁定手填） |
| 管理页鉴权 | 无 | 静态哈希 → 或 NAS 服务端鉴权（推荐） |
| 保存资源 | 手改文件 | 网页增删，一键保存并推送 |
| 资源内容 | 影视站导航 | 由你自行填充合法来源 |

## 九、合规提示

本框架只做"链接可用性检测 + 静态展示"，不提供任何资源内容。请只填入你有权使用或公开的合法链接，通过正规渠道获取内容。

## 十、网页管理数据（管理员口令）

访问 `/admin.html` 可在线增删资源字段：只填 **名称 / 地址 / 类型**，保存时按源站完整字段结构写入 `resources/resources.json`。

页面会**自动识别运行环境**：

| 运行在 | 模式 | 登录校验 | 保存方式 |
|---|---|---|---|
| NAS（`server.py` / Docker） | 服务端 | `/api/login`，HttpOnly Cookie | 一键写入本机并推送 GitHub，**不填 Token** |
| GitHub Pages | 静态 | 页面内 PBKDF2 哈希比对 | 需手填 PAT，或下载 JSON 手动替换 |

**设置口令**

```bash
python3 scripts/set_admin_password.py --target env --password '你的密码'   # NAS 服务端（写 .env）
python3 scripts/set_admin_password.py --password '你的密码'                # 静态页（写 admin.html）
python3 scripts/set_admin_password.py --target both --password '你的密码'  # 两边都改
python3 scripts/set_admin_password.py --print-only                        # 只看配置，不改文件
```

两种方式都只保存 PBKDF2-SHA256 的盐与派生值，**不存明文密码**。默认用户名 `admin`。

**保存方式对比**

| 方式 | 说明 |
|---|---|
| 保存到仓库（服务端模式） | 后端用 `.env` 里的 PAT 提交，成功后会触发 Actions 自动检测发布 |
| 保存到仓库（静态模式） | 手填 PAT 调 Contents API，Token 存本机 `localStorage` |
| 下载 JSON | 下载完整 `resources.json`，手动替换到 `resources/` |
| 复制 JSON | 复制到剪贴板 |

> 静态模式的口令校验跑在浏览器里，能挡住随手访问，但**挡不住懂技术的人**——他们可以改 JS 直接调接口。真正的写权限在 PAT 上，所以静态模式务必用细粒度、仅本仓库可写的 token。想要真正安全的鉴权，用第五节的 NAS 服务端模式。

