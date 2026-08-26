#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static site navigation helpers for the generated HTML pages."""
from __future__ import annotations

from html import escape
from typing import Iterable, Mapping


SITE_TABS = [
    {"key": "home", "label": "首页", "href": "index.html"},
    {"key": "fundflow", "label": "资金流", "href": "fundflow.html"},
    {"key": "stocktrend_ashare", "label": "A股走势", "href": "stocktrend_ashare.html"},
    {"key": "stocktrend_hk", "label": "港股走势", "href": "stocktrend_hk.html"},
]


def site_nav_css() -> str:
    return """
.site-shell-body { padding-bottom: 92px; }
.site-nav {
  position: fixed;
  left: 50%;
  bottom: max(14px, env(safe-area-inset-bottom));
  transform: translateX(-50%);
  width: min(720px, calc(100vw - 20px));
  z-index: 9999;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  padding: 10px;
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(13, 17, 23, 0.88);
  backdrop-filter: blur(16px);
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.32);
}
.site-nav-item {
  display: block;
  padding: 10px 8px;
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
  padding: 28px 16px 108px;
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
.site-hub-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
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
  .site-nav { gap: 6px; padding: 8px; }
  .site-nav-item { font-size: 12px; padding: 10px 6px; }
  .site-hub { padding: 18px 12px 108px; }
  .site-hub-hero { padding: 20px 18px; border-radius: 18px; }
  .site-hub h1 { font-size: 26px; }
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
      <div class="site-hub-grid">{cards}</div>
      <div class="site-hub-note">推荐组织方式：保留 3 个独立 HTML 作为真实内容页，首页只做入口，页内使用底部 tab 导航切换。这样最适合静态部署、分享单页链接和后续继续扩展。</div>
    </section>
  </div>
</main>
{nav}
</body>
</html>
""".format(
        title=escape(title),
        subtitle=escape(subtitle),
        date_text=escape(date_text),
        cards="".join(card_html),
        css=site_nav_css(),
        nav=render_site_nav("home"),
    )
