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


def _fmt_yi_from_raw(value: Optional[float]) -> str:
    """原始金额（元）→ 亿，无正负号（用于融资余额/融资买入等非方向性金额）。"""
    if value is None:
        return "—"
    return f"{value / 1e8:.2f}亿"


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
        "finance": "ROE、毛利率、资产负债率取最近公开财报（优先最近年报）；近 5 年分红缺失时直接展示“—”。",
        "quality": "ROE、毛利率、资产负债率取最近公开财报；排雷项综合公开披露与财报勾稽校验。",
        "dividend": "股息率(TTM) = 近12个月除权除息日内的每股分红之和 ÷ 收盘价（与行情软件 TTM 口径一致）；分红明细缺失时直接展示“—”。",
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


def _render_page_script() -> str:
    return """<script>
(function () {
  let syncingFromHistory = false;
  const nav = document.querySelector('.site-nav');

  function getModalToggles() {
    return Array.from(document.querySelectorAll('.modal-toggle'));
  }

  function getOpenToggle() {
    return getModalToggles().find(function (toggle) { return toggle.checked; }) || null;
  }

  function syncBottomNav() {
    if (!nav) return;
    nav.classList.toggle('is-locked-hidden', !!getOpenToggle());
  }

  function applyModalState(state) {
    const modalId = state && state.stocktrendModalId ? state.stocktrendModalId : '';
    syncingFromHistory = true;
    getModalToggles().forEach(function (toggle) {
      toggle.checked = modalId !== '' && toggle.id === modalId;
    });
    syncingFromHistory = false;
    syncBottomNav();
  }

  document.addEventListener('click', function (event) {
    const closer = event.target.closest('.modal-return, .modal-close, .modal-backdrop');
    if (!closer) return;

    const modalId = closer.getAttribute('for');
    const openToggle = getOpenToggle();
    if (!modalId || !openToggle || openToggle.id !== modalId) return;

    if (history.state && history.state.stocktrendModalId === modalId) {
      event.preventDefault();
      history.back();
    }
  });

  document.addEventListener('change', function (event) {
    const toggle = event.target.closest('.modal-toggle');
    if (!toggle || syncingFromHistory) return;

    if (toggle.checked) {
      if (!history.state || history.state.stocktrendModalId !== toggle.id) {
        history.pushState({ stocktrendModalId: toggle.id }, '', window.location.href);
      }
      syncBottomNav();
      return;
    }

    if (history.state && history.state.stocktrendModalId === toggle.id) {
      history.back();
      return;
    }

    syncBottomNav();
  });

  window.addEventListener('popstate', function (event) {
    applyModalState(event.state || null);
  });

  applyModalState(history.state || null);
})();
</script>"""


def _render_card(stock: Dict[str, Any], market_code: str, snap_iso: str = "") -> str:
    modal_id = f"m-{market_code}-{stock['code']}"
    pe_text = "亏损/缺失" if stock.get("pe") in (None, 0) or (stock.get("pe") or 0) < 0 else f"{stock['pe']:.2f}"
    div_text = "—" if stock.get("div") is None else f"{stock['div']:.2f}%"
    basis_text = _signal_basis_text(stock, market_code)
    rp_year = stock.get("financial_report_year")
    rp = (f"{rp_year}年报" if rp_year else (stock.get("financial_report_period") or ""))
    sw_l1 = stock.get("sw_l1") or ""
    l2 = stock.get("l2") or ""
    ind_text = f"{sw_l1}-{l2}" if (sw_l1 and l2 and sw_l1 != l2) else (sw_l1 or l2)
    return f'''<div class="stock-item">
  <input type="checkbox" id="{modal_id}" class="modal-toggle">
  <label class="stock-card border-{stock.get("border", "gray")}" for="{modal_id}">
    <div class="industry">{ind_text}</div>
    <div class="name">{stock.get("zh", stock["code"])} {stock["code"]}</div>
    <div class="data">ROE <b>{("—" if stock.get("roe") is None else f"{stock['roe']:.1f}%")}</b>{('<i class="rp" style="font-size:11px;color:#8b949e;font-style:normal;margin-left:3px;font-weight:400">'+rp+'</i>') if rp else ''} | PE <b>{pe_text}</b> | 股息 <span class="good">{div_text}</span></div>
    <div class="yt" style="color:{SIGNAL_COLOR[stock.get("signal", 1)]}">{SIGNAL_EMOJI[stock.get("signal", 1)]} {SIGNAL_TEXT[stock.get("signal", 1)]}</div>
    <div class="scoremark">巴菲特评分 {("—" if stock.get("score") is None else stock['score'])}</div>
  </label>
  {_render_modal(stock, market_code, snap_iso)}
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


def _render_fin3_table(fin3: List[Dict[str, Any]]) -> str:
    if not fin3:
        return '<div class="reason">近3年财报暂缺，无法展示跨年趋势。</div>'
    rows = []
    for f in fin3:
        roe = f.get("roe")
        margin = f.get("margin")
        liab = f.get("liab")
        roe_cls = "good" if (roe is not None and roe >= 15) else ("warn" if (roe is not None and roe < 10) else "")
        liab_cls = "bad" if (liab is not None and liab > 70) else ""
        rows.append(
            f'<tr><td>{f.get("year", "—")}</td>'
            f'<td class="v {roe_cls}">{"—" if roe is None else f"{roe:.2f}%"}</td>'
            f'<td class="v">{"—" if margin is None else f"{margin:.2f}%"}</td>'
            f'<td class="v {liab_cls}">{"—" if liab is None else f"{liab:.2f}%"}</td></tr>'
        )
    return f'''<table class="hist-table">
  <thead><tr><th>年度</th><th>ROE</th><th>毛利率</th><th>资产负债率</th></tr></thead>
  <tbody>{''.join(rows)}</tbody>
</table>'''


def _render_defense(defense: Dict[str, Any]) -> str:
    level = (defense or {}).get("level", "关注")
    reasons = (defense or {}).get("reasons") or []
    cls = "ok" if level == "通过" else ("bad" if level == "不通过" else "warn")
    box = f'<div class="mine-box {cls}">排雷{level}</div>'
    if not reasons:
        return f'<h3 class="sub-h">排雷结论</h3>\n      {box}\n      <div class="reason">各项指标稳健，未见明显排雷信号。</div>'
    items = "".join(
        f'<div class="risk" style="color:#c9d1d9;border-bottom:1px dashed #30363d;padding:6px 0">{r}</div>'
        for r in reasons
    )
    return f'''<h3 class="sub-h">排雷结论</h3>
      {box}
      {items}'''


def _render_fin3_transposed(fin3: List[Dict[str, Any]]) -> str:
    """盈利质量跨年对比：指标为行、年份为列（与外部「盈利质量与排雷」一致）。"""
    if not fin3:
        return '<div class="reason">近3年财报暂缺，无法展示跨年趋势。</div>'
    years_sorted = sorted({f["year"] for f in fin3}, reverse=False)[-3:]

    def col(field):
        out = []
        for y in years_sorted:
            f = next((x for x in fin3 if x["year"] == y), None)
            v = f.get(field) if f else None
            out.append("—" if v is None else f"{v:.2f}")
        return out

    def row(label, vals, unit=""):
        cells = "".join(f'<td class="v">{v}{unit}</td>' for v in vals)
        return f'<tr><td>{label}</td>{cells}</tr>'

    liab = col("liab")
    roe = col("roe")
    ocf = col("ocfps")
    margin = col("margin")
    head = "".join(f'<th>{y}</th>' for y in years_sorted)
    return f'''<table class="hist-table">
  <thead><tr><th>指标</th>{head}</tr></thead>
  <tbody>
    {row("资产负债率", liab, "%")}
    {row("ROE（加权）", roe, "%")}
    {row("每股经营现金流", ocf, "元")}
    {row("销售毛利率", margin, "%")}
  </tbody>
</table>'''


TREASURY_10Y = 1.68  # 中债10年期国债收益率（东方财富宏观口径，2026-09-01 附近）


def _last_ttm_div(div5: List[Optional[float]]) -> Optional[float]:
    for v in reversed(div5 or []):
        if v is not None:
            return v
    return None


def _compute_dividend_score(div5, div_years, eps_by_year, ocfps_latest, div_ttm_ps, roes):
    import statistics
    n_paid = sum(1 for d in (div5 or []) if d not in (None, 0))
    payouts = []
    for y, d in zip(div_years or [], div5 or []):
        eps = eps_by_year.get(y)
        if d and eps:
            payouts.append(d / eps * 100)
    avg_payout = sum(payouts) / len(payouts) if payouts else None
    cov = (ocfps_latest / div_ttm_ps) if (ocfps_latest and div_ttm_ps) else None
    score = 50
    if n_paid >= 5:
        score += 20
    elif n_paid >= 3:
        score += 12
    else:
        score += 4
    if avg_payout is not None:
        if 30 <= avg_payout <= 80:
            score += 15
        elif avg_payout > 100:
            score -= 10
        else:
            score += 5
    if cov is not None:
        if cov >= 2:
            score += 15
        elif cov >= 1:
            score += 8
        else:
            score -= 8
    if roes:
        sd = statistics.pstdev(roes)
        if sd < 5:
            score += 5
        elif min(roes) < 5:
            score -= 5
    score = int(max(0, min(100, score)))
    stars = ("★★★★★" if score >= 85 else "★★★★☆" if score >= 70 else
             "★★★☆☆" if score >= 55 else "★★☆☆☆" if score >= 40 else "★☆☆☆☆")
    return score, stars, n_paid, avg_payout, cov


def _render_dividend_panorama(stock: Dict[str, Any], fin3: List[Dict[str, Any]], currency_unit: str) -> str:
    div5 = stock.get("div5") or []
    div_years = stock.get("div_years") or []
    if not div5 or all(v is None for v in div5):
        return '<div class="reason">公开分红明细暂缺，页面不补造分红历史。</div>'
    eps_by_year = {f["year"]: f.get("eps") for f in fin3 if f.get("eps") is not None}
    ocfps_latest = fin3[0].get("ocfps") if fin3 else None
    div_ttm_ps = stock.get("div_ttm") or _last_ttm_div(div5)
    price = _to_float(stock.get("price"))
    div_yield_ttm = _to_float(stock.get("div"))

    # 5年分红表（指标×年份）
    head = "".join(f'<th>{y}</th>' for y in div_years)
    div_cells = "".join(
        f'<td class="v {"good" if v not in (None, 0) else ""}">{("—" if v is None else f"{v:.2f}")}</td>'
        for v in div5
    )
    eps_cells = "".join(
        f'<td class="v">{("—" if eps_by_year.get(y) is None else f"{eps_by_year.get(y):.2f}")}</td>'
        for y in div_years
    )
    payout_cells = "".join(
        (
            '<td class="v">—</td>'
            if (v is None or eps_by_year.get(y) is None)
            else f'<td class="v">{v / eps_by_year.get(y) * 100:.1f}%</td>'
        )
        for y, v in zip(div_years, div5)
    )
    table = f'''<table class="hist-table">
  <thead><tr><th>财年</th>{head}</tr></thead>
  <tbody>
    <tr><td>每股分红（{currency_unit}）</td>{div_cells}</tr>
    <tr><td>每股收益</td>{eps_cells}</tr>
    <tr><td>分红率</td>{payout_cells}</tr>
  </tbody>
</table>'''

    # 经营现金流覆盖分红
    cov = (ocfps_latest / div_ttm_ps) if (ocfps_latest and div_ttm_ps) else None
    cov_block = (
        f'<div class="mine-box">'
        f'<div class="cover-num">{("—" if cov is None else f"{cov:.2f} 倍")}</div>'
        f'<div class="cover-txt">经营现金流覆盖分红：每股经营现金流 '
        f'{("—" if ocfps_latest is None else f"{ocfps_latest:.2f} 元")} '
        f'vs TTM 每股分红 {("—" if div_ttm_ps is None else f"{div_ttm_ps:.2f} 元")}。</div>'
        f'</div>'
    )

    # 分红可持续性评分
    roes = [f["roe"] for f in fin3 if f.get("roe") is not None]
    score, stars, n_paid, avg_payout, _ = _compute_dividend_score(
        div5, div_years, eps_by_year, ocfps_latest, div_ttm_ps, roes
    )
    score_cls = "ok" if score >= 85 else ("bad" if score < 55 else "mid")
    score_block = f'''<h3 class="sub-h">分红可持续性评分</h3>
      <div class="sustain-score {score_cls}">
        <div class="ss-num">{score}<span class="ss-den">/100</span></div>
        <div class="ss-star">{stars}</div>
      </div>
      <ul class="ss-reasons">
        <li>连续分红≥{n_paid}年，分配纪律{"稳定" if n_paid >= 5 else "一般"}</li>
        <li>经营现金流覆盖分红{("—" if cov is None else f"{cov:.2f}倍")}，安全垫{"厚" if (cov or 0) >= 2 else "适中" if (cov or 0) >= 1 else "偏薄"}</li>
      </ul>
      <div class="note">评分基于近5年每股分红增长、分红率趋势、经营现金流覆盖倍数、ROE稳定性与分红连续性，仅供参考。</div>'''

    # 10万元分红收益测算
    if price and price > 0 and div_ttm_ps:
        shares = 100000 / price
        annual = shares * div_ttm_ps
        yld = div_ttm_ps / price * 100
        calc_block = f'''<h3 class="sub-h">10万元分红收益测算</h3>
      <div class="income-box">
        <div class="ib-num">≈ {annual:,.0f} 元<span class="ib-u">/年（税前）</span></div>
        <div class="ib-txt">以现价 {price:.2f} 元买入 10 万元，约得 {shares:,.0f} 股，按 TTM 每股分红 {div_ttm_ps:.2f} 元测算，年化税前分红约 {annual:,.0f} 元（股息率 {yld:.2f}%）。</div>
      </div>'''
    else:
        calc_block = '<h3 class="sub-h">10万元分红收益测算</h3>\n      <div class="reason">价格或分红数据暂缺，无法测算。</div>'

    # 股息率 vs 无风险利率
    spread = (div_yield_ttm - TREASURY_10Y) if div_yield_ttm is not None else None
    spread_cls = "good" if (spread or 0) > 0 else "bad"
    spread_txt = "—" if spread is None else f"{spread:+.2f}pct"
    rate_block = f'''<h3 class="sub-h">股息率 vs 无风险利率</h3>
      <div class="yield-vs">
        <div class="yv-item"><div class="yv-k">股息率(TTM)</div><div class="yv-v {('good' if div_yield_ttm is not None else '')}">{("—" if div_yield_ttm is None else f"{div_yield_ttm:.2f}%")}</div></div>
        <div class="yv-item"><div class="yv-k">10Y国债收益率</div><div class="yv-v">{TREASURY_10Y:.2f}%</div></div>
        <div class="yv-item"><div class="yv-k">利差（性价比）</div><div class="yv-v {spread_cls}">{spread_txt}</div></div>
      </div>
      <div class="note">无风险利率取中债10年期国债收益率 {TREASURY_10Y:.2f}%（东方财富宏观口径，9月1日附近）。{("利差为正且较大，说明分红性价比相对国债突出。" if (spread or 0) > 0 else "利差为负或持平，分红性价比相对国债不占优。")}</div>'''

    note = '<div class="note">数据来源：东方财富；分红率 = 每股分红 / 每股收益。每股分红为同年（含中期）分红公告合计；TTM 股息率为「近12个月除权除息日内的每股分红之和 ÷ 收盘价」，与行情软件 TTM 股息率口径一致。</div>'
    return table + cov_block + note + score_block + calc_block + rate_block


def _render_build_module(section_prefix: str, build: Optional[Dict[str, Any]], signal: int,
                        pe: Optional[float] = None, w52l=None, w52h=None, pos=None,
                        trend: str = "") -> str:
    if not build:
        return f'''<div class="module" id="{section_prefix}-build">
          <h2><span class="num">2</span>买卖决策与建仓</h2>
          <div class="reason">价格或 52 周区间暂缺，无法测算建仓区间，页面不补造价位。</div>
        </div>'''
    view = build.get("view", "—")
    tiers = build.get("tiers") or []
    target = build.get("target")
    fair_pe = build.get("fair_pe")
    buy_pe = build.get("buy_pe")
    dist_to_buy = build.get("dist_to_buy")
    pe_show = "—" if pe is None else f"{pe:.2f} 倍"
    fair_show = "—" if fair_pe is None else f"{fair_pe} 倍"
    buy_show = "—" if buy_pe is None else f"{buy_pe} 倍（安全边际15%）"
    dist_show = "—" if dist_to_buy is None else f"需再下探约 {dist_to_buy:.1f}%"
    if view == "✅ 已处于低估区":
        vcls, vtxt = "ok", "✅ 估值偏低，具备安全边际"
    elif view == "🟡 估值合理":
        vcls, vtxt = "mid", "🟡 估值合理，可分批布局"
    else:
        vcls, vtxt = "wait", "⚠️ 估值偏高，等待回调"
    tier_rows = "".join(
        f'<tr><td>{t["name"]}</td><td class="v">{_fmt_price(t["price"])}</td>'
        f'<td class="v {"good" if t["dy"] else ""}>{"—" if t["dy"] is None else f"{t["dy"]:.2f}%"}</td></tr>'
        for t in tiers
    )
    w52l_text = _fmt_price(_to_float(w52l))
    w52h_text = _fmt_price(_to_float(w52h))
    pos_text = "—" if pos is None else f"{pos:.0f}%"
    trend_text = trend or "趋势描述暂缺"
    return f'''<div class="module" id="{section_prefix}-build">
          <h2><span class="num">2</span>买卖决策与建仓</h2>
          <h3 class="sub-h">是否推荐入手</h3>
          <div class="conclusion-bar {CONCL_CLASS[signal]}"><span class="cb-tag">{SIGNAL_EMOJI[signal]} {SIGNAL_TEXT[signal]}</span><span class="cb-reason">{view}</span></div>
          <div class="reason">综合巴菲特评分与估值位置判断。</div>
          <h3 class="sub-h">是否处于低点（估值视角）</h3>
          <div class="verdict {vcls}">{vtxt}</div>
          <div class="reason">{trend_text}</div>
          <div class="kv" style="margin-top:10px">
            {_render_kv("52周低点", w52l_text)}
            {_render_kv("52周高点", w52h_text)}
            {_render_kv("当前位置", pos_text)}
            {_render_kv("当前 PE", pe_show)}
            {_render_kv("合理 PE 中枢", fair_show)}
            {_render_kv("建议买入 PE", buy_show)}
            {_render_kv("距击球区", dist_show)}
          </div>
          <h3 class="sub-h">估值目标价（PE 视角）</h3>
          <div class="reason">当前 PE {pe_show}；以合理 PE 中枢 {fair_show} 与每股收益测算，估值目标价约 <b>{("—" if target is None else f"{target:.2f}")}</b> 元。模型估算，请结合自身风险承受力。</div>
          <h3 class="sub-h">建议买入价位（三档建仓）</h3>
          <table class="tier-table">
            <thead><tr><th>档位</th><th>对应价</th><th>对应股息率</th></tr></thead>
            <tbody>{tier_rows}</tbody>
          </table>
          <div class="note">三档为「越跌越买」的分批参考，非预测底部；建仓价位为基于 52 周区间的模型测算，仅供参考，非投资建议。</div>
        </div>'''


def _render_score_module(section_prefix: str, score: Optional[int], score_parts: Dict[str, int], stock: Dict[str, Any]) -> str:
    total = "—" if score is None else score
    parts = score_parts or {}
    labels = [("roe", "ROE盈利能力"), ("val", "估值合理性(PE)"), ("div", "分红回报"), ("fin", "财务稳健/资产质量"), ("moat", "护城河/现金流")]
    maxmap = {"roe": 30, "val": 25, "div": 15, "fin": 15, "moat": 15}
    subs = {
        "roe": ("—" if stock.get("roe") is None else f"ROE {stock['roe']:.1f}%"),
        "val": ("—" if stock.get("pe") is None else f"PE {stock['pe']:.2f}倍"),
        "div": ("—" if stock.get("div") is None else f"股息率 {stock['div']:.2f}%"),
        "fin": ("—" if stock.get("liab") is None else f"负债率 {stock['liab']:.0f}%"),
        "moat": ("—" if stock.get("margin") is None else f"毛利率 {stock['margin']:.1f}%"),
    }
    gauge_width = 0 if score is None else int(round(score / 100 * 100))
    bars = []
    for key, label in labels:
        val = parts.get(key, 0)
        width = int(round(val / maxmap[key] * 100))
        bars.append(f'''<div class="factor">
          <div class="fl"><span>{label}</span><b>{val} / {maxmap[key]}</b></div>
          <div class="bar"><div style="width:{width}%"></div></div>
          <div class="fl" style="color:#6e7681"><span>{subs.get(key, "")}</span><span></span></div>
        </div>''')
    return f'''<div class="module" id="{section_prefix}-score">
          <h2><span class="num">6</span>巴菲特模型评分</h2>
          <div class="gauge"><div style="width:{gauge_width}%;background:#d29922"></div></div>
          <div class="reason">综合评分 <b style="color:#d29922">{total} / 100</b>（模型估算，仅供参考）。</div>
          {''.join(bars)}
          <div class="note">评分逻辑：ROE盈利能力(30) + 估值合理性(25) + 分红回报(15) + 财务稳健/资产质量(15) + 护城河/现金流(15)。含主观假设，不构成投资建议。</div>
          <div style="margin-top:14px;padding:12px 14px;border:1px solid #30363d;border-radius:8px;background:#0d1117;">
            <div style="font-weight:600;color:#e6edf3;margin-bottom:6px;">各指标分值区间说明</div>
            <div style="color:#8b949e;font-size:12px;margin-bottom:8px;">综合评分 = 五维加权（满分 100），各维度按以下区间计分：</div>
            <div style="color:#c9d1d9;font-size:12.5px;line-height:1.95;">
              <div><b style="color:#58a6ff">ROE盈利能力（权重30）</b>：ROE ≥ 20% → 30分；15% ≤ ROE &lt; 20% → 24分；10% ≤ ROE &lt; 15% → 18分；5% ≤ ROE &lt; 10% → 12分；ROE &lt; 5% 或未披露 → 6分。</div>
              <div><b style="color:#58a6ff">估值合理性 PE（权重25）</b>：PE ≤ 15 → 22分；15 &lt; PE ≤ 20 → 17分；20 &lt; PE ≤ 25 → 13分；25 &lt; PE ≤ 30 → 9分；PE &gt; 30 或未披露 → 5分。※ 若处 52 周估值低位（分位 ≤ 40%），额外 +3 分（封顶 25）。</div>
              <div><b style="color:#58a6ff">分红回报（权重15）</b>：股息率 ≥ 4% → 15分；3% ≤ 股息率 &lt; 4% → 12分；2% ≤ &lt; 3% → 9分；1% ≤ &lt; 2% → 6分；&lt; 1% 或未披露 → 3分。</div>
              <div><b style="color:#58a6ff">财务稳健/资产质量（权重15）</b>：资产负债率 &lt; 40% → 15分；40% ≤ &lt; 50% → 12分；50% ≤ &lt; 60% → 9分；60% ≤ &lt; 70% → 6分；≥ 70% 或未披露 → 3分。</div>
              <div><b style="color:#58a6ff">护城河/现金流（权重15）</b>：毛利率 ≥ 60% → 15分；40% ≤ &lt; 60% → 12分；25% ≤ &lt; 40% → 9分；15% ≤ &lt; 25% → 6分；&lt; 15% 或未披露 → 3分。</div>
            </div>
            <div class="note" style="margin-top:8px;">含主观假设，模型估算，仅供研究参考，不构成投资建议。</div>
          </div>
        </div>'''


def _render_modal(stock: Dict[str, Any], market_code: str, snap_iso: str = "") -> str:
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
    pos_text = "—" if stock.get("pos") is None else f"{stock['pos']:.0f}%"
    pe_text = "—" if stock.get("pe") is None else f"{stock['pe']:.2f}"
    pb_text = "—" if stock.get("pb") is None else f"{stock['pb']:.2f}"
    rp_year = stock.get("financial_report_year")
    rp_modal = (f"{rp_year}年报" if rp_year else (stock.get("financial_report_period") or ""))
    roe_text = "—" if stock.get("roe") is None else (f"{stock['roe']:.2f}%（{rp_modal}）" if rp_modal else f"{stock['roe']:.2f}%")
    margin_text = "—" if stock.get("margin") is None else f"{stock['margin']:.2f}%"
    liab_text = "—" if stock.get("liab") is None else f"{stock['liab']:.2f}%"
    div_text = "—" if stock.get("div") is None else f"{stock['div']:.2f}%"
    basis_text = _signal_basis_text(stock, market_code)
    score = stock.get("score")
    score_parts = stock.get("score_parts") or {}
    build = stock.get("build")
    defense = stock.get("defense") or {}
    fin3 = stock.get("fin3") or []
    fin3_annual = stock.get("fin3_annual") or fin3
    financial_period = str(stock.get("financial_report_year") or "—")
    holding_date = str(stock.get("north_date") or stock.get("south_date") or "—")
    history_date = str(stock.get("history_as_of") or "—")
    sw_l1 = stock.get("sw_l1") or ""
    l2 = stock.get("l2") or ""
    ind_text = f"{sw_l1}-{l2}" if (sw_l1 and l2 and sw_l1 != l2) else (sw_l1 or l2)
    en_text = stock.get("en")
    if market_code == "ashare":
        capital_tags = (
            f'<span class="tag">北向(陆股通)：{_fmt_pct(stock.get("north_pct"))}'
            f'（{_fmt_shares(_to_float(stock.get("north_shares")))}）</span>'
            f'<span class="tag">主力净流入({snap_iso})：{_fmt_signed_yi_from_raw(stock.get("main_inflow"))}</span>'
            f'<span class="tag">融资余额：{_fmt_yi_from_raw(_to_float(stock.get("margin_balance")))}</span>'
            f'<span class="tag">融资买入({snap_iso})：{_fmt_yi_from_raw(_to_float(stock.get("margin_buy")))}</span>'
        )
        capital_note = (
            f"资金面数据截至 <b>{snap_iso} 收盘后</b>（收盘口径）：北向来自公开披露（T-1）；"
            "主力净流入来自东方财富；融资余额/融资买入引用沪深交易所融资融券明细（最近可得交易日）。"
        )
    else:
        capital_tags = (
            f'<span class="tag">{market_meta["holding_line"]}</span>'
            f'<span class="tag">{market_meta["holding_shares"]}</span>'
            f'<span class="tag">{market_meta["flow_line"]}</span>'
        )
        capital_note = (
            f"资金面数据截至 <b>{snap_iso} 收盘后</b>（收盘口径）：南向持股来自公开披露（T-1）；成交额为收盘口径。"
        )
    en_html = f'<div class="en">{en_text}</div>' if (en_text and en_text != stock.get("zh")) else ''
    snap_md = ""
    if snap_iso:
        try:
            _y, _m, _d = snap_iso[:10].split("-")
            snap_md = f"{int(_m)}月{int(_d)}日"
        except Exception:
            snap_md = ""
    return f'''<div class="modal-overlay">
    <label class="modal-backdrop" for="{modal_id}"></label>
    <div class="modal">
      <div class="modal-x">
        <span class="hint">点击空白处或 ✕ 关闭</span>
        <label class="modal-close" for="{modal_id}">✕ 关闭</label>
      </div>
      <div class="modal-body">
        <div class="databadge">⚠️ 数据口径：本页为 <b>{snap_iso} 收盘后静态快照</b>，行情为收盘口径（非盘中实时）。收盘价 / 涨跌幅 / 成交额 / 换手率 / PB / 总市值 / PE(TTM) / 股息率来自 AKShare 与东方财富；北向持股来自公开披露；ROE / 毛利率 / 负债率 / 合理 PE 中枢为基于公开财报的模型估算，仅用于评分与估值判断。</div>
        <div class="stock-head">
          <div class="code">{market_meta["code_suffix"]}</div>
          <h1>{stock.get("zh", stock["code"])}</h1>
          {en_html}
          <div class="ind">📌 {ind_text}</div>
          <div class="scorepill" style="background:#388bfd">巴菲特评分 {("—" if score is None else score)}</div>
        </div>
        <div class="module" id="{section_prefix}-snapshot">
          <h2><span class="num">1</span>行情快照（{snap_md}收盘后）</h2>
          <div class="metric-cards">
            <div class="metric-card"><div class="mc-k">最新价</div><div class="mc-v">{_fmt_price(_to_float(stock.get("price")))}<span class="mc-u">{market_meta["currency_unit"]}</span></div><div class="mc-s {_pct_class(stock.get("chg"))}">{_fmt_signed_pct(stock.get("chg"))}</div></div>
            <div class="metric-card"><div class="mc-k">股息率(TTM)</div><div class="mc-v {"good" if stock.get("div") not in (None, 0) else ""}">{div_text}</div><div class="mc-s">收息性价比</div></div>
            <div class="metric-card"><div class="mc-k">总市值</div><div class="mc-v">{_fmt_mkt(stock.get("mkt"))}</div><div class="mc-s">PB {pb_text}</div></div>
            <div class="metric-card"><div class="mc-k">PE(TTM)</div><div class="mc-v">{pe_text}</div><div class="mc-s">ROE {roe_text}</div></div>
          </div>
          <div class="kv">
            {_render_kv("今开 / 昨收", f"{_fmt_price(_to_float(stock.get('open')))} / {_fmt_price(_to_float(stock.get('prev')))}")}
            {_render_kv("成交额", _fmt_amount(stock.get("amount")))}
            {_render_kv("换手率", _fmt_pct(_to_float(stock.get("turn"))))}
            {_render_kv("PB（市净率）", pb_text)}
          </div>
          <div class="note">本模块为 <b>{snap_iso} 收盘后真实快照</b>（收盘口径，非盘中实时）。价格 / 成交额 / 换手率 / PB / 总市值 / PE(TTM) / 股息率(TTM) 来自 AKShare 与东方财富；ROE 取最近年报口径。股息率(TTM) = 近12个月除权除息日内的每股分红之和 ÷ 收盘价。</div>
        </div>
        {_render_build_module(section_prefix, build, signal, _to_float(stock.get("pe")),
                              _to_float(stock.get("w52l")), _to_float(stock.get("w52h")),
                              stock.get("pos"), stock.get("trend"))}
        <div class="module" id="{section_prefix}-capital">
          <h2><span class="num">3</span>资金面动态</h2>
          <div class="summary">{stock.get("capital", "资金面描述暂缺")}</div>
          <div class="tag-row">
            {capital_tags}
          </div>
          <div class="note">{capital_note}</div>
        </div>
        <div class="module" id="{section_prefix}-quality">
          <h2><span class="num">4</span>盈利质量与排雷</h2>
          <div class="section-hint">近3年盈利与资产质量（年报口径，2023-2025）</div>
          {_render_fin3_transposed(fin3_annual)}
          <div class="note">数据来源：东方财富 年报口径；制造业中资产负债率 60%-65% 属中等杠杆，ROE 保持在 15% 以上为较优水平。毛利率栏显示"—"表示该行业（银行/保险）不适用毛利率口径。</div>
          {_render_defense(defense)}
        </div>
        <div class="module" id="{section_prefix}-dividend">
          <h2><span class="num">5</span>分红回报全景</h2>
          <div class="section-hint">近5年现金分红（元/股，含中期，全年合计）</div>
          {_render_dividend_panorama(stock, fin3_annual, market_meta["currency_unit"])}
        </div>
        {_render_score_module(section_prefix, score, score_parts, stock)}
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
  <div class="databadge"><b>这不是实时行情页面。</b> 当前页面只展示收盘后的静态结果，适合盘后复盘和清单式跟踪，不展示盘中实时跳动数据。</div>
</div>
'''
    )
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
        for stock in by_sector.get(sector["key"], []):
            html.append(_render_card(stock, market_code, meta.get("snap_iso")))
        html.append("</div>\n</div>\n")
    html.append(_render_roster(data))
    notes = []
    notes.append(f'<div class="date">{_public_date_text(meta)}</div>')
    notes.append(f'<div class="databadge">{_public_databadge(meta)}</div>')
    for warning in meta.get("fetch_warnings") or []:
        notes.append(f'<div class="databadge">⚠️ 数据抓取提示：{warning}</div>')
    html.append(
        f'''<div class="page-notes">{''.join(notes)}</div>
<div class="disclaimer"><p>{meta.get("disclaimer", "")}</p></div>
<div class="footer">{_public_footer(meta)}</div>
</div>
{render_site_nav(nav_active)}
{_render_page_script()}
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
