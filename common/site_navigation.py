#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static site navigation helpers for the generated HTML pages."""
from __future__ import annotations

from html import escape
from typing import Iterable, Mapping


SITE_TABS = [
    {"key": "home", "label": "首页", "href": "index.html"},
    {"key": "fundflow", "label": "A股资金流", "href": "fundflow.html"},
    {"key": "stocktrend_ashare", "label": "A股个股", "href": "stocktrend_ashare.html"},
    {"key": "fundflow_hk", "label": "港股资金流", "href": "fundflow_hk.html"},
    {"key": "stocktrend_hk", "label": "港股个股", "href": "stocktrend_hk.html"},
    {"key": "fundflow_us", "label": "美股资金流", "href": "fundflow_us.html"},
    {"key": "stocktrend_us", "label": "美股个股", "href": "stocktrend_us.html"},
]


def site_nav_css() -> str:
    return """
html, body {
  margin: 0;
  padding: 0;
  background: #090c10;
}
.site-shell-body { padding-top: max(0px, env(safe-area-inset-top, 0px)); padding-bottom: 16px; }
.site-nav {
  position: -webkit-sticky;
  position: sticky;
  top: max(0px, env(safe-area-inset-top, 0px));
  left: 0;
  width: auto;
  max-width: calc(100vw - 8px);
  z-index: 9999;
  display: flex;
  flex-wrap: nowrap;
  gap: 8px;
  padding: 10px 14px 10px 0;
  border-radius: 18px;
  background: rgba(13, 17, 23, 0.88);
  backdrop-filter: blur(16px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.32);
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
.site-nav::-webkit-scrollbar { display: none; }
.wrap, .container { margin-top: 10px; }
.site-nav-item {
  flex: 0 0 auto;
  white-space: nowrap;
  display: block;
  padding: 10px 14px;
  border-radius: 12px;
  text-align: center;
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  color: #8b949e;
  background: rgba(255, 255, 255, 0.04);
}
.site-nav-item.is-active {
  color: #f0c040;
  background: rgba(240, 192, 64, 0.12);
  box-shadow: inset 0 0 0 1px rgba(240, 192, 64, 0.22);
}
.site-nav-item:hover {
  color: #e6edf3;
  background: rgba(255, 255, 255, 0.08);
}
.site-hub {
  min-height: 100vh;
  padding: 28px 16px 40px;
  background: radial-gradient(circle at top, #1b2230 0%, #0d1117 46%, #090c10 100%);
  color: #c9d1d9;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif;
}
.site-hub-inner {
  width: min(980px, 100%);
  margin: 0 auto;
}
.site-hub-hero {
  padding: 28px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: linear-gradient(135deg, rgba(22, 27, 34, 0.96), rgba(19, 28, 44, 0.92));
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.28);
}
.site-hub-tag {
  display: inline-block;
  padding: 5px 12px;
  border-radius: 999px;
  color: #58a6ff;
  background: rgba(88, 166, 255, 0.1);
  border: 1px solid rgba(88, 166, 255, 0.24);
  font-size: 12px;
}
.site-hub h1 {
  margin: 14px 0 10px;
  color: #f0c040;
  font-size: 34px;
  line-height: 1.2;
}
.site-hub-subtitle {
  color: #c9d1d9;
  font-size: 16px;
  line-height: 1.8;
}
.site-hub-date {
  margin-top: 12px;
  color: #8b949e;
  font-size: 13px;
}
.site-hub-alert {
  margin-top: 16px;
  padding: 14px 16px;
  border-radius: 14px;
  color: #f0c040;
  background: rgba(240, 192, 64, 0.1);
  border: 1px solid rgba(240, 192, 64, 0.22);
  font-size: 13px;
  line-height: 1.8;
}
.site-hub-alert b {
  color: #ffd86b;
}
.site-hub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
  margin-top: 20px;
}
.site-hub-card {
  display: block;
  padding: 20px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  text-decoration: none;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.02));
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.2);
}
.site-hub-card:hover {
  transform: translateY(-2px);
  border-color: rgba(240, 192, 64, 0.28);
}
.site-hub-card-title {
  color: #e6edf3;
  font-size: 19px;
  font-weight: 700;
}
.site-hub-card-badge {
  display: inline-block;
  margin-top: 10px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  color: #f0c040;
  background: rgba(240, 192, 64, 0.12);
}
.site-hub-card-desc {
  margin-top: 12px;
  color: #8b949e;
  font-size: 14px;
  line-height: 1.7;
}
.site-hub-card-link {
  margin-top: 14px;
  color: #58a6ff;
  font-size: 13px;
  font-weight: 600;
}
.site-hub-note {
  margin-top: 18px;
  padding: 14px 16px;
  border-radius: 14px;
  color: #d29922;
  background: rgba(210, 153, 34, 0.08);
  border: 1px solid rgba(210, 153, 34, 0.2);
  font-size: 13px;
  line-height: 1.8;
}
@media (max-width: 860px) {
  .site-hub-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .site-nav { gap: 5px; padding: 8px 12px 8px 0; }
  .site-nav-item { font-size: 11.5px; padding: 10px 12px; }
  .site-hub { padding: 18px 12px 40px; }
  .site-hub-hero { padding: 20px 18px; border-radius: 18px; }
  .site-hub h1 { font-size: 26px; }
}

/* ── 统一内页顶部模块（资金流 / 个股走势 共 6 页共用，对齐站点 GitHub 深色语言）── */
.page-hdr {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: 16px 24px; padding: 22px 24px; margin: 16px 0 16px; border-radius: 16px;
  border: 1px solid rgba(255,255,255,.08);
  background: linear-gradient(135deg, rgba(22,27,34,.96), rgba(19,28,44,.92));
  box-shadow: 0 10px 30px rgba(0,0,0,.28);
}
.page-hdr .ph-l { display: flex; align-items: center; gap: 14px; min-width: 0; }
.page-hdr .ph-logo {
  width: 44px; height: 44px; border-radius: 11px; flex: none;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1f6feb, #388bfd);
}
.page-hdr .ph-logo svg { width: 26px; height: 26px; }
.page-hdr .ph-title { min-width: 0; }
.page-hdr h1 { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: .3px; color: #f0c040; line-height: 1.2; }
.page-hdr .ph-sub { margin-top: 6px; font-size: 12px; color: #8b949e; line-height: 1.5; }
.page-hdr .ph-r { display: flex; flex-direction: column; align-items: flex-end; gap: 7px; }
.page-hdr .ph-meta { font-size: 11px; color: #8b949e; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; text-align: right; }
.page-hdr .ph-meta b { color: #c9d1d9; font-weight: 600; }
@media (max-width: 720px) {
  .page-hdr { flex-direction: column; align-items: flex-start; }
  .page-hdr .ph-r { align-items: flex-start; }
  .page-hdr .ph-meta { text-align: left; }
}
"""


def render_site_nav(active: str) -> str:
    items = []
    for tab in SITE_TABS:
        classes = "site-nav-item"
        if tab["key"] == active:
            classes += " is-active"
        items.append(
            f'<a class="{classes}" href="{escape(tab["href"])}">{escape(tab["label"])}</a>'
        )
    return '<nav class="site-nav" aria-label="站点导航">' + "".join(items) + "</nav>"


def render_page_header(
    *,
    title: str,
    subtitle: str,
    data_date: str = "",
    weekday: str = "",
    generated_at: str = "",
    source_text: str = "公开数据整理",
    scope_line: str = "",
) -> str:
    """统一的内页顶部模块（资金流 / 个股走势 共 6 页共用）。

    结构固定为「左：logo + 标题区（h1 / subtitle）｜右：数据日期 + 来源/更新 + 范围说明」，
    仅文案按页面变化。title / subtitle / scope_line 信任调用方（代码内常量，可含 <b> 等标签），
    其余字段做 HTML 转义。
    """
    scope = f'<div class="ph-meta">{scope_line}</div>' if scope_line else ""
    return (
        '<header class="page-hdr">\n'
        '  <div class="ph-l">\n'
        '    <div class="ph-logo"><svg viewBox="0 0 24 24" fill="none">'
        '<path d="M4 17l5-6 4 3 7-9" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        '<path d="M15 5h5v5" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>\n'
        '    <div class="ph-title">\n'
        f'      <h1>{title}</h1>\n'
        f'      <div class="ph-sub">{escape(subtitle)}</div>\n'
        '    </div>\n'
        '  </div>\n'
        '  <div class="ph-r">\n'
        f'    <div class="ph-meta">数据日期 <b>{escape(data_date)}</b>（<b>{escape(weekday)}</b>）· 收盘</div>\n'
        f'    <div class="ph-meta">更新于 <b>{escape(generated_at)}</b> ｜ {escape(source_text)}</div>\n'
        f'    {scope}'
        '  </div>\n'
        '</header>\n'
    )


def render_site_index(title: str, subtitle: str, date_text: str, cards: Iterable[Mapping[str, str]]) -> str:
    card_html = []
    for card in cards:
        badge = f'<div class="site-hub-card-badge">{escape(card.get("badge", ""))}</div>' if card.get("badge") else ""
        card_html.append(
            '<a class="site-hub-card" href="{href}">'
            '<div class="site-hub-card-title">{title}</div>'
            '{badge}'
            '<div class="site-hub-card-desc">{desc}</div>'
            '<div class="site-hub-card-link">进入页面</div>'
            '</a>'.format(
                href=escape(card["href"]),
                title=escape(card["title"]),
                badge=badge,
                desc=escape(card["description"]),
            )
        )

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{css}</style>
</head>
<body class="site-shell-body">
<main class="site-hub">
  <div class="site-hub-inner">
    <section class="site-hub-hero">
      <span class="site-hub-tag">静态导航首页</span>
      <h1>{title}</h1>
      <div class="site-hub-subtitle">{subtitle}</div>
      <div class="site-hub-date">{date_text}</div>
      <div class="site-hub-alert"><b>这不是实时行情页面。</b> 当前站点展示的是静态页面与收盘快照，适合盘后复盘、看结构和做清单式跟踪，不展示盘中实时跳动数据。</div>
      <div class="site-hub-grid">{cards}</div>
      <div class="site-hub-note">建议从“资金流日报”先看当天市场主线，再进入 A 股 / 港股 / 美股页面看个股细节，整体更适合盘后复盘和清单式跟踪。</div>
    </section>
  </div>
</main>
</body>
</html>
""".format(
        title=escape(title),
        subtitle=escape(subtitle),
        date_text=escape(date_text),
        cards="".join(card_html),
        css=site_nav_css(),
    )
