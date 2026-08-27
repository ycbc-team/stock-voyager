#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stocktrend UI 渲染脚本
=====================

职责：
  1. 读取 stocktrend 数据收集脚本生成的 JSON 中间产物
  2. 基于独立 CSS 模板生成两个静态页面

默认产物：
  - build/site/stocktrend_ashare.html
  - build/site/stocktrend_hk.html
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from common.storage import default_data_dir
from common.storage import default_site_dir
from common.site_navigation import render_site_nav
from common.site_navigation import site_nav_css


SIGNAL_TEXT = ["可分批关注", "持有观察", "谨慎观望"]
SIGNAL_EMOJI = ["🟢", "🟡", "🔴"]
SIGNAL_COLOR = ["#3fb950", "#d29922", "#f85149"]
CONCL_CLASS = ["ok", "mid", "wait"]


def default_input_dir() -> str:
    return default_data_dir()


def default_output_dir() -> str:
    return default_site_dir()


def _load_css() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(script_dir, "stocktrend_style.css")
    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except Exception:
        pass
    return ""


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _fmt_signed_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"


def _fmt_amount(value: Any, unit: str = "") -> str:
    if value in (None, "", "—"):
        return "—"
    return f"{value}{unit}"


def _fmt_price(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _fmt_mkt(value: Any) -> str:
    if value in (None, "", "—"):
        return "—"
    return str(value)


def _fmt_shares(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1e8:
        return f"{value / 1e8:.2f}亿股"
    if abs(value) >= 1e4:
        return f"{value / 1e4:.2f}万股"
    return f"{value:.0f}股"


def _fmt_signed_yi_from_raw(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value / 1e8:.2f}亿"


def _pct_class(value: Optional[float]) -> str:
    if value is None:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _fmt_chg_html(value: Optional[float]) -> str:
    cls = _pct_class(value)
    if value is None:
        return '<span class="flat">—</span>'
    sign = "+" if value > 0 else ""
    return f'<span class="{cls}">{sign}{value:.2f}%</span>'


def _signal_basis_text(stock: Dict[str, Any], market_code: str) -> str:
    reasons: List[str] = []
    pos = _to_float(stock.get("pos"))
    pe = _to_float(stock.get("pe"))
    div = _to_float(stock.get("div"))
    main_inflow = _to_float(stock.get("main_inflow"))

    if pos is not None:
        if pos <= 35:
            reasons.append("52w低位")
        elif pos >= 75:
            reasons.append("52w高位")
    if pe is not None:
        if pe <= 0:
            reasons.append("PE亏损")
        elif pe <= 20:
            reasons.append("PE偏低")
        elif pe >= 35:
            reasons.append("PE偏高")
    if div is not None and div >= 2.5:
        reasons.append("股息率较高")
    if market_code == "ashare" and main_inflow is not None:
        if main_inflow > 0:
            reasons.append("主力流入")
        elif main_inflow < 0:
            reasons.append("主力流出")

    if not reasons:
        return "依据：52周位置、估值与资金面综合判断"
    return "依据：" + " / ".join(reasons[:3])


def _module_hint(section: str, market_code: str) -> str:
    hints = {
        "snapshot": "价格、涨跌、成交额均为收盘口径；PE / PB 取最近可得公开指标。",
        "capital_ashare": "主力净流入为当日口径；北向持股按最近公开披露日展示。",
        "capital_hk": "成交额为收盘口径；南向持股按最近公开披露日展示。",
        "finance": "ROE、毛利率、资产负债率取最近公开财报；近 5 年分红缺失时直接展示“—”。",
    }
    if section == "capital":
        key = "capital_ashare" if market_code == "ashare" else "capital_hk"
        return hints[key]
    return hints.get(section, "")


def _public_subtitle(meta: Dict[str, Any]) -> str:
    market_code = meta.get("market_code", "hk")
    if market_code == "ashare":
        return "聚焦核心 A 股清单，便于按估值、位置、资金面、财务与风险提示做盘后复盘。"
    return "聚焦港股代表标的，便于按估值、位置、南向持股、分红与风险提示做盘后复盘。"


def _public_date_text(meta: Dict[str, Any]) -> str:
    return f"非实时页面：{meta.get('snap_iso', '最新交易日')} 收盘快照"


def _public_databadge(meta: Dict[str, Any]) -> str:
    market_code = meta.get("market_code", "hk")
    if market_code == "ashare":
        return "⚠️ 数据口径：本页仅展示收盘后的静态结果；价格、估值、资金面、财务与分红为公开数据整理，缺失字段直接显示“—”。"
    return "⚠️ 数据口径：本页仅展示收盘后的静态结果；价格、估值、南向持股、财务与分红为公开数据整理，缺失字段直接显示“—”。"


def _public_footer(meta: Dict[str, Any]) -> str:
    return f"{meta.get('title', '')} · 静态收盘快照 · {meta.get('snap_iso', '最新交易日')}"


def _render_card(stock: Dict[str, Any], market_code: str) -> str:
    modal_id = f"m-{market_code}-{stock['code']}"
    pe_text = "亏损/缺失" if stock.get("pe") in (None, 0) or (stock.get("pe") or 0) < 0 else f"{stock['pe']:.2f}"
    div_text = "—" if stock.get("div") is None else f"{stock['div']:.2f}%"
    basis_text = _signal_basis_text(stock, market_code)
    return f'''<div class="stock-item">
  <input type="checkbox" id="{modal_id}" class="modal-toggle">
  <label class="stock-card border-{stock.get("border", "gray")}" for="{modal_id}">
    <div class="industry">{stock.get("l2_code", "")} {stock.get("l2", "")}</div>
    <div class="name">{stock.get("zh", stock["code"])} {stock["code"]}</div>
    <div class="data">涨跌 {_fmt_chg_html(stock.get("chg"))} | PE <b>{pe_text}</b> | <span class="good">{div_text}</span></div>
    <div class="yt" style="color:{SIGNAL_COLOR[stock.get("signal", 1)]}">{SIGNAL_EMOJI[stock.get("signal", 1)]} {SIGNAL_TEXT[stock.get("signal", 1)]}</div>
    <div class="basisline">{basis_text}</div>
    <div class="scoremark">市值 {_fmt_mkt(stock.get("mkt"))} · 52w位 {("—" if stock.get("pos") is None else f"{stock['pos']:.0f}%")}</div>
    <div class="card-cta">点击查看详情 <span>→</span></div>
  </label>
  {_render_modal(stock, market_code)}
</div>'''


def _render_kv(key: str, value: str, cls: str = "") -> str:
    cls_text = f" {cls}" if cls else ""
    return f'<div><span class="k">{key}</span><br><span class="v{cls_text}">{value}</span></div>'


def _render_dividend_table(stock: Dict[str, Any], currency_unit: str) -> str:
    div5 = stock.get("div5") or []
    years = stock.get("div_years") or []
    if not div5:
        return '<div class="reason">公开分红明细暂缺，页面不补造分红历史。</div>'
    if not years:
        years = list(range(max(2021, 2026 - len(div5)), 2026))
    rows = []
    for year, value in zip(years, div5):
        rows.append(
            f'<tr><td>{year}</td><td class="v {"good" if value not in (None, 0) else ""}">{("—" if value is None else f"{value:.4f}")}</td></tr>'
        )
    return f'''<table class="hist-table">
  <thead><tr><th>年度</th><th>每股分红（{currency_unit}）</th></tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>'''


def _render_issue_notes(issues: List[str]) -> str:
    valid = [str(item).strip() for item in issues if str(item or "").strip()]
    if not valid:
        return ""
    return "".join(f'<div class="note">数据提示：{item}</div>' for item in valid)


def _render_modal(stock: Dict[str, Any], market_code: str) -> str:
    meta_map = {
        "ashare": {
            "currency_unit": "元",
            "code_suffix": f"{stock['code']}.{stock.get('exchange', '')}",
            "flow_line": f"主力净流入：{_fmt_signed_yi_from_raw(stock.get('main_inflow'))}",
            "holding_line": f"北向占总股本：{_fmt_pct(stock.get('north_pct'))}",
            "holding_shares": f"北向持股：{_fmt_shares(_to_float(stock.get('north_shares')))}",
            "badge": "A股收盘口径",
        },
        "hk": {
            "currency_unit": "港元",
            "code_suffix": f"{stock['code']}.HK",
            "flow_line": f"成交额：{_fmt_amount(stock.get('amount'))}",
            "holding_line": f"南向持股：{_fmt_pct(_to_float(stock.get('south')))}",
            "holding_shares": f"南向股数：{_fmt_shares(_to_float(stock.get('south_shares')))}",
            "badge": "港股收盘口径",
        },
    }
    market_meta = meta_map[market_code]
    signal = stock.get("signal", 1)
    modal_id = f"m-{market_code}-{stock['code']}"
    section_prefix = f"{market_code}-{stock['code']}"
    risks = stock.get("risks") or ["暂无风险备注"]
    risks_html = "".join(f'<div class="risk">{item}</div>' for item in risks[:3])
    pos_text = "—" if stock.get("pos") is None else f"{stock['pos']:.0f}%"
    pe_text = "—" if stock.get("pe") is None else f"{stock['pe']:.2f}"
    pb_text = "—" if stock.get("pb") is None else f"{stock['pb']:.2f}"
    roe_text = "—" if stock.get("roe") is None else f"{stock['roe']:.2f}%"
    margin_text = "—" if stock.get("margin") is None else f"{stock['margin']:.2f}%"
    liab_text = "—" if stock.get("liab") is None else f"{stock['liab']:.2f}%"
    div_text = "—" if stock.get("div") is None else f"{stock['div']:.2f}%"
    basis_text = _signal_basis_text(stock, market_code)
    financial_period = str(stock.get("financial_report_year") or "—")
    holding_date = str(stock.get("north_date") or stock.get("south_date") or "—")
    history_date = str(stock.get("history_as_of") or "—")
    return f'''<div class="modal-overlay">
    <label class="modal-backdrop" for="{modal_id}"></label>
    <div class="modal">
      <div class="modal-x">
        <div class="modal-actions">
          <label class="modal-return" for="{modal_id}">← 返回列表</label>
          <span class="hint">详情较长，建议先看估值与位置，再看资金和财务</span>
        </div>
        <label class="modal-close" for="{modal_id}">✕ 关闭</label>
      </div>
      <div class="modal-body">
        <div class="databadge">⚠️ {market_meta["badge"]}：这不是实时行情页面，当前仅展示静态收盘快照；缺失字段直接展示“—”，不做补值。</div>
        <div class="stock-head">
          <div class="code">{market_meta["code_suffix"]}</div>
          <h1>{stock.get("zh", stock["code"])}</h1>
          <div class="en">{stock.get("en", stock.get("zh", stock["code"]))}</div>
          <div class="ind">📌 {stock.get("l1", "")} · {stock.get("l2", "")}</div>
          <div class="scorepill" style="background:{SIGNAL_COLOR[signal]}">{SIGNAL_EMOJI[signal]} {SIGNAL_TEXT[signal]}</div>
          <div class="scorebasis">{basis_text}</div>
        </div>
        <div class="modal-anchor-nav">
          <a href="#{section_prefix}-snapshot">行情</a>
          <a href="#{section_prefix}-valuation">估值</a>
          <a href="#{section_prefix}-capital">资金</a>
          <a href="#{section_prefix}-finance">财务</a>
          <a href="#{section_prefix}-risk">风险</a>
          <a href="#{section_prefix}-summary">总结</a>
        </div>
        <div class="module" id="{section_prefix}-snapshot">
          <h2><span class="num">1</span>行情快照</h2>
          <div class="metric-cards">
            <div class="metric-card"><div class="mc-k">最新价</div><div class="mc-v">{_fmt_price(_to_float(stock.get("price")))}<span class="mc-u">{market_meta["currency_unit"]}</span></div><div class="mc-s {_pct_class(stock.get("chg"))}">{_fmt_signed_pct(stock.get("chg"))}</div></div>
            <div class="metric-card"><div class="mc-k">股息率</div><div class="mc-v {"good" if stock.get("div") not in (None, 0) else ""}">{div_text}</div><div class="mc-s">TTM / 最新可得</div></div>
            <div class="metric-card"><div class="mc-k">总市值</div><div class="mc-v">{_fmt_mkt(stock.get("mkt"))}</div><div class="mc-s">估值视角</div></div>
            <div class="metric-card"><div class="mc-k">PE / PB</div><div class="mc-v">{pe_text}</div><div class="mc-s">PB {pb_text}</div></div>
          </div>
          <div class="section-hint">{_module_hint("snapshot", market_code)}</div>
          <div class="kv">
            {_render_kv("今开 / 昨收", f"{_fmt_price(_to_float(stock.get('open')))} / {_fmt_price(_to_float(stock.get('prev')))}")}
            {_render_kv("成交额", _fmt_amount(stock.get("amount")))}
            {_render_kv("换手率", _fmt_pct(_to_float(stock.get("turn"))))}
            {_render_kv("52周分位", pos_text)}
          </div>
        </div>
        <div class="module" id="{section_prefix}-valuation">
          <h2><span class="num">2</span>估值与位置</h2>
          <div class="conclusion-bar {CONCL_CLASS[signal]}"><span class="cb-tag">{SIGNAL_EMOJI[signal]} {SIGNAL_TEXT[signal]}</span><span class="cb-reason">{stock.get("suggest", SIGNAL_TEXT[signal])}</span><span class="cb-basis">{basis_text}</span></div>
          <div class="kv">
            {_render_kv("52周低点", _fmt_price(_to_float(stock.get("w52l"))))}
            {_render_kv("52周高点", _fmt_price(_to_float(stock.get("w52h"))))}
            {_render_kv("当前位置", pos_text)}
            {_render_kv("PE / PB", f"{pe_text} / {pb_text}")}
          </div>
          <div class="note">{stock.get("trend", "趋势描述暂缺")}</div>
        </div>
        <div class="module" id="{section_prefix}-capital">
          <h2><span class="num">3</span>资金面动态</h2>
          <div class="summary">{stock.get("capital", "资金面描述暂缺")}</div>
          <div class="section-hint">{_module_hint("capital", market_code)}</div>
          <div class="kv">
            {_render_kv("资金面", market_meta["flow_line"])}
            {_render_kv("持股比例", market_meta["holding_line"])}
            {_render_kv("持股数量", market_meta["holding_shares"])}
            {_render_kv("成交额", _fmt_amount(stock.get("amount")))}
          </div>
          {_render_issue_notes(stock.get("data_issues") or [])}
        </div>
        <div class="module" id="{section_prefix}-finance">
          <h2><span class="num">4</span>财务与分红</h2>
          <div class="section-hint">{_module_hint("finance", market_code)}</div>
          <div class="kv">
            {_render_kv("ROE", roe_text)}
            {_render_kv("毛利率", margin_text)}
            {_render_kv("资产负债率", liab_text)}
            {_render_kv("股息率", div_text)}
          </div>
          <div class="kv">
            {_render_kv("财报年度", financial_period)}
            {_render_kv("持股日期", holding_date)}
            {_render_kv("行情日期", history_date)}
            {_render_kv("分红年度", " / ".join(str(year) for year in (stock.get("div_years") or [])) or "—")}
          </div>
          {_render_dividend_table(stock, market_meta["currency_unit"])}
        </div>
        <div class="module">
          <h2><span class="num">5</span>区间走势</h2>
          <div class="yield-vs">
            <div class="yv-item"><div class="yv-k">近5日</div><div class="yv-v {_pct_class(stock.get('chg5'))}">{_fmt_signed_pct(stock.get("chg5"))}</div></div>
            <div class="yv-item"><div class="yv-k">近20日</div><div class="yv-v {_pct_class(stock.get('chg20'))}">{_fmt_signed_pct(stock.get("chg20"))}</div></div>
            <div class="yv-item"><div class="yv-k">近60日</div><div class="yv-v {_pct_class(stock.get('chg60'))}">{_fmt_signed_pct(stock.get("chg60"))}</div></div>
            <div class="yv-item"><div class="yv-k">年初至今</div><div class="yv-v {_pct_class(stock.get('ytd'))}">{_fmt_signed_pct(stock.get("ytd"))}</div></div>
          </div>
        </div>
        <div class="module" id="{section_prefix}-risk">
          <h2><span class="num">6</span>风险提示</h2>
          {risks_html}
        </div>
        <div class="module" id="{section_prefix}-summary">
          <h2><span class="num">7</span>一句话总结</h2>
          <div class="summary">{stock.get("summary", "暂无总结")}</div>
        </div>
      </div>
    </div>
  </div>'''


def _render_roster(data: Dict[str, Any]) -> str:
    if not data["meta"].get("show_roster"):
        return ""
    stocks = [item for item in data["stocks"] if _to_float(item.get("roe")) is not None]
    if not stocks:
        return ""
    tiers = [
        ("超神 (>25%)", "#3fb950", []),
        ("优秀 (15-25%)", "#58a6ff", []),
        ("接近 (10-15%)", "#d29922", []),
        ("偏弱 (<10%)", "#8b949e", []),
    ]
    for stock in stocks:
        roe = _to_float(stock.get("roe")) or 0
        label = f"{stock.get('zh', stock['code'])} {stock['code']}"
        if roe > 25:
            tiers[0][2].append(label)
        elif roe >= 15:
            tiers[1][2].append(label)
        elif roe >= 10:
            tiers[2][2].append(label)
        else:
            tiers[3][2].append(label)
    rows = []
    for title, color, names in tiers:
        if not names:
            continue
        rows.append(
            f'<div class="roe-tier"><span class="roe-label" style="color:{color}">{title}</span><span class="roe-names">{" · ".join(names)}</span></div>'
        )
    if not rows:
        return ""
    return f'''<div class="roe-section">
  <h2>{data["meta"].get("roster_title", "ROE 分层观察")}</h2>
  {"".join(rows)}
  <div class="note" style="margin-top:10px">{data["meta"].get("roster_note", "")}</div>
</div>'''


def _render_combos(data: Dict[str, Any]) -> str:
    combos = data.get("combos") or []
    if not combos:
        return ""
    market_code = data.get("meta", {}).get("market_code", "hk")
    stock_map = {item["code"]: item for item in data["stocks"]}
    cards = []
    for combo in combos:
        labels = []
        for code in combo.get("codes", []):
            if code not in stock_map:
                continue
            labels.append(
                f'<label class="combo-stock" for="m-{market_code}-{code}">{stock_map[code]["zh"]} {code}</label>'
            )
        cards.append(f'''<div class="combo-card">
  <div class="combo-title {combo.get("cls", "")}">{combo.get("title", "")}</div>
  <div class="combo-stocks">{" ".join(labels)}</div>
  <div class="combo-desc">{combo.get("desc", "")}</div>
</div>''')
    return f'''<div class="combo-section">
  <h2>{data["meta"].get("combo_section_title", "组合观察")}</h2>
  {"".join(cards)}
  <div class="note" style="margin-top:6px">{data["meta"].get("combo_note", "")}</div>
</div>'''


def render_page(data: Dict[str, Any]) -> str:
    css = _load_css()
    meta = data["meta"]
    market_code = meta.get("market_code", "hk")
    nav_active = "stocktrend_ashare" if market_code == "ashare" else "stocktrend_hk"
    stocks = data["stocks"]
    by_sector = {}
    for stock in stocks:
        by_sector.setdefault(stock["sector"], []).append(stock)

    html: List[str] = []
    html.append(
        f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<title>{meta["title"]}</title>\n<style>{css}{site_nav_css()}</style>\n</head>\n<body class="site-shell-body">\n<div class="container">\n'
    )
    html.append(
        f'''<div class="header">
  <div class="tag">静态收盘快照 · 非实时 · {meta.get("snap_iso", meta.get("tag", ""))}</div>
  <h1>{meta.get("title", "")}</h1>
  <div class="subtitle">{_public_subtitle(meta)}</div>
  <div class="date">{_public_date_text(meta)}</div>
</div>
<div class="databadge"><b>这不是实时行情页面。</b> 当前页面只展示收盘后的静态结果，适合盘后复盘和清单式跟踪，不展示盘中实时跳动数据。</div>
<div class="databadge">{_public_databadge(meta)}</div>
'''
    )
    for warning in meta.get("fetch_warnings") or []:
        html.append(f'<div class="databadge">⚠️ 数据抓取提示：{warning}</div>\n')
    sector_class_map = {
        "consumer": "consumer",
        "healthcare": "finance",
        "manufacturing": "cycle",
        "resource": "cycle",
        "tech": "tech",
        "finance": "finance",
        "cycle": "cycle",
    }
    for sector in data.get("sectors", []):
        sector_class = sector_class_map.get(sector["key"], "finance")
        html.append(f'<div class="sector sector-{sector_class}">\n<h2>{sector["title"]}</h2>\n<div class="sector-grid">\n')
        last_l1 = None
        for stock in by_sector.get(sector["key"], []):
            if stock.get("l1") != last_l1:
                last_l1 = stock.get("l1")
                html.append(f'<div class="sub-group"><div class="sub-h">▍{last_l1}</div></div>\n')
            html.append(_render_card(stock, market_code))
        html.append("</div>\n</div>\n")
    html.append(_render_roster(data))
    html.append(_render_combos(data))
    html.append(
        f'''<div class="disclaimer"><p>{meta.get("disclaimer", "")}</p></div>
<div class="footer">{_public_footer(meta)}</div>
</div>
{render_site_nav(nav_active)}
</body>
</html>
'''
    )
    return "".join(html)


def load_result(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def write_html(path: str, html: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def _derive_output(input_path: str) -> str:
    base, _ = os.path.splitext(input_path)
    return f"{base}.html"


def main() -> None:
    ap = argparse.ArgumentParser(description="stocktrend UI 渲染脚本：基于 JSON 中间产物输出静态 HTML")
    ap.add_argument("--input", action="append", help="输入 JSON 路径；可重复传入多个。默认渲染 build/data/stocktrend_ashare.json 与 build/data/stocktrend_hk.json")
    ap.add_argument("--output", action="append", help="输出 HTML 路径；与 --input 一一对应")
    args = ap.parse_args()

    input_dir = default_input_dir()
    output_dir = default_output_dir()
    inputs = args.input or [
        os.path.join(input_dir, "stocktrend_ashare.json"),
        os.path.join(input_dir, "stocktrend_hk.json"),
    ]
    outputs = args.output or [
        os.path.join(output_dir, "stocktrend_ashare.html"),
        os.path.join(output_dir, "stocktrend_hk.html"),
    ]

    written: List[str] = []
    for idx, input_path in enumerate(inputs):
        if not os.path.exists(input_path):
            print(f"[!] 跳过不存在的输入：{input_path}")
            continue
        output_path = outputs[idx] if idx < len(outputs) else _derive_output(input_path)
        data = load_result(input_path)
        html = render_page(data)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        write_html(output_path, html)
        written.append(output_path)

    print("\n[✓] HTML 产物已写出：")
    for path in written:
        print(f"    {path}")


if __name__ == "__main__":
    main()
