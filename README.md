# link-monitor —— 自建资源检测 + 发布流程

照着 `awesome-zhuiju-free` 的机制搭的通用版：**数据驱动 → 每天自动检测 → 生成静态导航页 → 发布**。资源内容完全由你自己放（合法网站、自建服务、订阅源都行），项目只提供"检测+发布"的工程框架，零第三方依赖。

## 一、它做了什么

```
resources/resources.json   ← 你维护的资源清单（唯一数据源）
        │
        ▼  每天定时
scripts/check.py           ← 并发检测可用性 → reports/availability.json
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
│   └── publish.py          # 发布页生成脚本
├── .github/workflows/
│   └── daily.yml           # GitHub Actions 每天 01:00 定时
├── run_daily.sh            # 飞牛 NAS 本地定时入口
├── index.html              # 生成的静态发布页
└── README.md
```

## 三、资源数据格式

`resources/resources.json` 每条资源：

```json
{
  "id": "唯一英文标识",
  "name": "显示名称",
  "url": "https://...",
  "category": "tools | dev | media | learn | other",
  "summary": "一句话简介",
  "enabled": true,
  "featured": true
}
```

- `enabled: false` 的资源不参与检测和发布（相当于原项目的失效停用）
- `category` 的中文名在 `publish.py` 顶部的 `CATEGORY_NAMES` 里改
- 样例数据里放了一个 `.invalid` 失效域名和几个正常站，方便你验证检测效果

## 四、两套部署方式

### 方式 A：GitHub Actions（推荐，零运维）

1. 把整个目录推到一个新 GitHub 仓库
2. Settings → Pages → Source 选 `gh-pages` 分支
3. Workflow 已配置每天 UTC 01:00（北京时间 09:00）自动跑：检测 → 生成 → 提交 → 发布
4. 也可以随时在 Actions 页面手动点 `Run workflow`

访问地址：`https://<用户名>.github.io/<仓库名>/`

### 方式 B：飞牛 NAS 本地定时

1. 把目录放到 NAS，例如 `/vol1/1000/docker/link-monitor`
2. 加 crontab（用 root 或该目录属主）：

```bash
# 每天 08:30 执行
30 8 * * * /bin/bash /vol1/1000/docker/link-monitor/run_daily.sh >> /vol1/1000/docker/link-monitor/reports/cron.log 2>&1
```

3. 用 NAS 自带的 Web 服务器/Nginx 把目录根指向 `link-monitor/`，`index.html` 就是发布页
4. 或装个轻量静态服务器：`python3 -m http.server 8899 -d /vol1/1000/docker/link-monitor`

## 五、可调参数（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `CHECK_TIMEOUT` | 12 | 单个请求超时秒数 |
| `CHECK_WORKERS` | 6 | 并发线程数 |
| `CHECK_RETRIES` | 2 | 失败重试次数 |

## 六、状态说明

发布页上每个资源卡片会显示检测状态和响应时间：
- **可访问**（绿）：HTTP 2xx/3xx
- **访问受限**（黄）：401/403/405/429，可能是反爬或需登录
- **无法访问**（红）：连接失败、超时、4xx/5xx

## 七、和原项目的差异

| 项 | 原项目 | 本方案 |
|---|---|---|
| 检测脚本 | Node.js `.mjs` | Python（零依赖） |
| 运行时 | GitHub Actions | GitHub Actions 或 NAS cron |
| 发布 | Typecho 站点 | GitHub Pages / 任意静态服务器 |
| 数据字段 | 20+（含评分/风险/验证） | 精简 7 个，够用可扩展 |
| 资源内容 | 影视站导航 | 由你自行填充合法来源 |

## 八、合规提示

本框架只做"链接可用性检测 + 静态展示"，不提供任何资源内容。请只填入你有权使用或公开的合法链接，通过正规渠道获取内容。
