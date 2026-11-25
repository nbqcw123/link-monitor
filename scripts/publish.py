#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""静态发布页生成：读 resources.json + availability.json，生成响应式 index.html。
支持源站完整字段：标签 / 评分 / 风险 / 验证状态 / GitHub Star。
纯 Python 标准库。仿照 awesome-zhuiju-free 的数据驱动发布思路。
"""
import os
import json
import html
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES_PATH = os.path.join(ROOT, "resources", "resources.json")
REPORT_PATH = os.path.join(ROOT, "reports", "availability.json")
OUT_PATH = os.path.join(ROOT, "index.html")

CATEGORY_NAMES = {
    # 源站完整字段结构（线上线 9 分类）
    "online_video": "在线影视站",
    "video_app": "影视 App",
    "tvbox_config": "TVBox 配置",
    "magnet_search": "磁力搜索",
    "cloud_search": "网盘搜索",
    "subscription": "订阅服务",
    "subtitles": "字幕工具",
    "player": "播放器",
    "open_source": "开源项目",
    # 通用分类（兼容）
    "opensource": "开源项目",
    "subtitle": "字幕工具",
    "tools": "实用工具",
    "dev": "开发工具",
    "media": "影音媒体",
    "learn": "学习资源",
    "other": "其他",
}
STATUS_META = {
    "reachable": ("可访问", "#00a870", "#e8f8f2"),
    "restricted": ("访问受限", "#d89614", "#fff7e6"),
    "unreachable": ("无法访问", "#d54941", "#fef0ef"),
    "unknown": ("未检测", "#8c8c8c", "#f5f5f5"),
}
RISK_LABEL = {"high": "高风险", "medium": "中风险", "low": "低风险", "unknown": "未知"}
E = html.escape


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def stars(n):
    try:
        n = int(round(float(n)))
    except (TypeError, ValueError):
        return ""
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


def main():
    data = load_json(RES_PATH)
    report = load_json(REPORT_PATH, {"results": [], "generated_at": None, "summary": {}})
    if not data:
        raise SystemExit("缺少 resources/resources.json")

    status_by_id = {r["resource_id"]: r for r in report.get("results", [])}
    resources = [r for r in data["resources"] if r.get("enabled", True)]

    groups = {}
    for r in resources:
        groups.setdefault(r.get("category", "other"), []).append(r)

    gen = report.get("generated_at")
    if gen:
        try:
            gen_disp = datetime.fromisoformat(gen.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            gen_disp = gen
    else:
        gen_disp = "尚未检测"

    s = report.get("summary", {})
    total = s.get("total", len(resources))
    ok = s.get("reachable", 0)
    bad = s.get("unreachable", 0)

    parts = ["""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>我的资源导航</title>
<style>
:root{--bg:#f7f8fa;--card:#fff;--ink:#1f2329;--sub:#646a73;--line:#e5e6eb;--blue:#3370ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6}
.wrap{max-width:1040px;margin:0 auto;padding:32px 20px 60px}
header{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:26px;margin-bottom:24px}
h1{font-size:26px;margin:0 0 6px;font-weight:600}
.sub{color:var(--sub);font-size:13px}
.stats{display:flex;gap:18px;margin-top:16px;flex-wrap:wrap}
.stat{background:var(--bg);border-radius:8px;padding:8px 14px;font-size:13px}
.stat b{font-size:18px;margin-right:4px}
.c-g{color:#00a870}.c-r{color:#d54941}.c-b{color:var(--blue)}
h2{font-size:17px;margin:26px 0 12px;font-weight:600;border-left:4px solid var(--blue);padding-left:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;text-decoration:none;color:inherit;display:block;transition:border-color .15s,border-color .15s}
.card:hover{border-color:var(--blue)}
.card .name{font-size:15px;font-weight:600;margin-bottom:4px}
.card .desc{font-size:12.5px;color:var(--sub);min-height:20px}
.tags{margin-top:10px;display:flex;gap:5px;flex-wrap:wrap}
.tag{font-size:10.5px;color:var(--sub);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:1px 7px}
.scores{font-size:11px;color:#d89614;margin-top:8px;letter-spacing:1px}
.gh{font-size:11px;color:var(--sub);margin-top:6px}
.card .foot{display:flex;justify-content:space-between;align-items:center;margin-top:12px;border-top:1px solid var(--line);padding-top:10px}
.badge{font-size:11px;padding:2px 8px;border-radius:10px}
.badge.dim{opacity:.6}
.risk{font-size:10.5px;padding:1px 7px;border-radius:8px;margin-left:6px}
.ms{font-size:11px;color:var(--sub)}
footer{margin-top:30px;font-size:12px;color:var(--sub);text-align:center}
.tabs{position:sticky;top:0;z-index:20;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px;margin-bottom:20px;display:flex;gap:6px;overflow-x:auto;box-shadow:0 2px 8px rgba(0,0,0,.04)}
.tab{white-space:nowrap;cursor:pointer;border:0;background:transparent;color:var(--sub);font-size:13px;padding:7px 13px;border-radius:8px;font-weight:500;font-family:inherit}
.tab:hover{background:var(--bg)}
.tab.active{background:var(--blue);color:#fff}
.tab .n{opacity:.75;font-size:11px;margin-left:3px}
.cat-panel{display:none}
.cat-panel.active{display:block}
.cat-panel h2{margin-top:0}
</style></head><body><div class="wrap">
<header>
<h1>我的资源导航</h1>
<div class="sub">数据驱动 · 每日自动检测 · 静态发布　|　检测时间：__GEN__</div>
<div class="stats">
<div class="stat"><b class="c-b">__TOTAL__</b> 个资源</div>
<div class="stat"><b class="c-g">__OK__</b> 可访问</div>
<div class="stat"><b class="c-r">__BAD__</b> 无法访问</div>
</div>
</header>
"""]
    head = "\n".join(parts)
    head = head.replace("__GEN__", E(gen_disp)).replace("__TOTAL__", str(total)).replace("__OK__", str(ok)).replace("__BAD__", str(bad))

    cats_sorted = sorted(groups, key=lambda c: (-len(groups[c]), c))

    # 顶部分类标签栏：点击切换显示，默认第一个分类
    tabs = ['<nav class="tabs" aria-label="资源分类">']
    for i, cat in enumerate(cats_sorted):
        active = " active" if i == 0 else ""
        tabs.append(
            '<button class="tab%s" type="button" data-cat="%s">%s<span class="n">(%d)</span></button>'
            % (active, E(cat), E(CATEGORY_NAMES.get(cat, cat)), len(groups[cat]))
        )
    tabs.append('<button class="tab" type="button" data-cat="__ALL__">全部<span class="n">(%d)</span></button>' % len(resources))
    tabs.append("</nav>")

    body = ["\n".join(tabs)]
    for i, cat in enumerate(cats_sorted):
        cat_name = CATEGORY_NAMES.get(cat, cat)
        active = " active" if i == 0 else ""
        body.append('<section class="cat-panel%s" data-cat="%s">' % (active, E(cat)))
        body.append("<h2>%s（%d）</h2>" % (E(cat_name), len(groups[cat])))
        body.append('<div class="grid">')
        for r in groups[cat]:
            st = status_by_id.get(r["id"], {})
            status = st.get("status", "unknown")
            label, fg, bg = STATUS_META.get(status, STATUS_META["unknown"])
            ms = st.get("response_ms")
            ms_txt = "%dms" % ms if ms is not None else "-"
            dim = " dim" if status in ("unreachable", "unknown") else ""

            tags_html = ""
            if r.get("tags"):
                tags_html = '<div class="tags">%s</div>' % "".join(
                    '<span class="tag">%s</span>' % E(t) for t in r["tags"][:5]
                )
            score_html = ""
            sc = r.get("scores") or {}
            if sc:
                avg = sum(v for v in sc.values() if isinstance(v, (int, float))) / max(1, len(sc))
                src_tag = ""
                if r.get("scores_source") == "github-stars":
                    src_tag = ' <span style="color:#8c8c8c;font-size:10px">Star 自动</span>'
                score_html = '<div class="scores">%s <span style="color:#8c8c8c">%.1f</span>%s</div>' % (stars(avg), avg, src_tag)
            gh_html = ""
            gh = r.get("github") or {}
            if gh.get("full_name"):
                gh_txt = gh["full_name"] + (" · ★%s" % gh["stars"] if gh.get("stars") is not None else "")
                gh_html = '<div class="gh">⌘ %s</div>' % E(gh_txt)
            risk_html = ""
            risk = (r.get("risks") or {}).get("copyright")
            if risk and risk != "low":
                rc = {"high": "#d54941", "medium": "#d89614", "unknown": "#8c8c8c"}.get(risk, "#8c8c8c")
                risk_html = '<span class="risk" style="color:%s;background:#f5f5f5">%s</span>' % (rc, RISK_LABEL.get(risk, risk))

            body.append(
                '<a class="card" href="%s" target="_blank" rel="noopener">'
                '<div class="name">%s%s</div>'
                '<div class="desc">%s</div>'
                '%s%s%s'
                '<div class="foot"><span class="badge%s" style="color:%s;background:%s">%s</span>'
                '<span class="ms">%s</span></div></a>'
                % (E(r["url"]), E(r["name"]), risk_html, E(r.get("summary_short") or r.get("summary", "")),
                   tags_html, score_html, gh_html,
                   dim, fg, bg, label, ms_txt)
            )
        body.append("</div>")
        body.append("</section>")

    tail = """
<footer>由 link-monitor 自动生成 · 采用源站完整字段结构 · 资源可用性每日检测<br>仅供技术研究，请通过正规渠道获取内容</footer>
</div>
<script>
(function(){
  var tabs=[].slice.call(document.querySelectorAll('.tab'));
  var panels=[].slice.call(document.querySelectorAll('.cat-panel'));
  function show(key){
    var all=(key==='__ALL__');
    tabs.forEach(function(t){t.classList.toggle('active',t.getAttribute('data-cat')===key)});
    panels.forEach(function(p){p.classList.toggle('active',all||p.getAttribute('data-cat')===key)});
  }
  tabs.forEach(function(t){t.addEventListener('click',function(){show(t.getAttribute('data-cat'))})});
  var h=location.hash.replace(/^#/,'');
  var found=(h==='__ALL__')||panels.some(function(p){return p.getAttribute('data-cat')===h});
  if(found&&h)show(h);
})();
</script>
</body></html>
"""
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(body) + tail)
    print("已生成：%s" % OUT_PATH)
    print("资源 %d 个，分类 %d 个" % (len(resources), len(groups)))


if __name__ == "__main__":
    main()
