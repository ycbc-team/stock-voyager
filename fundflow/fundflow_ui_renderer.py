#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股收盘 HTML 渲染脚本
=====================
职责：
  1. 读取 JSON 中间产物
  2. 基于 report.css 生成纯静态 HTML 页面

本脚本不负责行情抓取；数据生产由 fundflow_data_fetcher.py 完成。
"""
import argparse
import datetime
import json
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from common.storage import default_data_dir
from common.storage import default_site_dir
from common.site_navigation import render_site_nav
from common.site_navigation import site_nav_css


_WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def default_input_dir():
    return default_data_dir()


def default_output_dir():
    return default_site_dir()


def _weekday_cn(date_str):
    try:
        return _WEEK[datetime.datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except Exception:
        return ""


def idx_prefix(code):
    if code.startswith("399"):
        return "SZ"
    if code.startswith("932"):
        return "CSI"
    if code.startswith("899"):
        return "BJ"
    return "SH"


def h_pct(v):
    if v is None:
        return ("—", "flat")
    if v > 0:
        return (f"▲ +{v:.2f}%", "up")
    if v < 0:
        return (f"▼ {v:.2f}%", "down")
    return ("— 0.00%", "flat")


def h_yi(v):
    return None if v is None else v / 1e8


def h_yi_signed(v):
    if v is None:
        return "—"
    y = v / 1e8
    return f"+{y:.2f}" if y >= 0 else f"{y:.2f}"


def h_amount(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"{v / 1e12:.3f}万亿"
    if a >= 1e8:
        return f"{v / 1e8:.0f}亿"
    if a >= 1e4:
        return f"{v / 1e4:.0f}万"
    return f"{v:.0f}"


def heat_bg(pct):
    if pct is None:
        return "background:rgba(255,255,255,.03)"
    mag = min(abs(pct), 4.0) / 4.0
    a = 0.14 + 0.62 * mag
    if pct >= 0:
        return f"background:linear-gradient(135deg,rgba(246,70,93,{a:.2f}),rgba(246,70,93,{a * 0.55:.2f}))"
    return f"background:linear-gradient(135deg,rgba(14,203,129,{a:.2f}),rgba(14,203,129,{a * 0.55:.2f}))"


def _load_css(script_dir):
    p = os.path.join(script_dir, "report.css")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _panel(title, tag, body):
    return (
        f'  <div class="panel sec-gap">\n'
        f'    <div class="p-title"><span class="bar"></span>{title}\n'
        f'      <span class="tag">{tag}</span>\n'
        f'    </div>\n{body}  </div>\n'
    )


def _empty_body(msg):
    return (
        f'    <div class="style-note" style="border-left-color:var(--txt3)">'
        f'<b style="color:var(--txt2)">⚠ 数据暂缺</b> ｜ {msg}</div>\n'
    )


def product_source_text():
    return "公开数据整理"


def build_market_views(result):
    indices = {x["name"]: x for x in result.get("indices", [])}
    sw = result.get("sw_industry") or []
    nb = result.get("northbound") or {}
    style_proxy = result.get("style_proxy") or []

    sh = indices.get("上证指数")
    sz = indices.get("深证成指")
    cyb = indices.get("创业板指")
    up_n = sum(1 for x in sw if (x.get("pct") or 0) > 0)
    dn_n = sum(1 for x in sw if (x.get("pct") or 0) < 0)
    breadth_desc = f"行业上涨 {up_n} 个，下跌 {dn_n} 个" if sw else "行业广度数据暂缺"
    index_desc = "、".join(
        f"{name}{x['pct']:+.2f}%"
        for name, x in (("上证", sh), ("深成", sz), ("创业板", cyb))
        if x and x.get("pct") is not None
    ) or "核心指数数据暂缺"
    breadth_rating = "r1" if up_n > dn_n else ("r3" if dn_n > up_n else "r2")
    breadth_label = "偏强" if up_n > dn_n else ("偏弱" if dn_n > up_n else "均衡")

    net_vals = [x["main_net_in"] for x in sw if x.get("main_net_in") is not None]
    total_net = sum(net_vals) / 1e8 if net_vals else None
    top_in = sorted([x for x in sw if x.get("main_net_in")], key=lambda z: z["main_net_in"], reverse=True)[:2]
    top_out = sorted([x for x in sw if x.get("main_net_in")], key=lambda z: z["main_net_in"])[:2]
    in_desc = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in top_in) or "暂无明显流入主线"
    out_desc = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in top_out) or "暂无明显流出主线"
    flow_rating = "r1" if (total_net or 0) > 0 else ("r3" if (total_net or 0) < 0 else "r2")
    flow_label = "净流入" if (total_net or 0) > 0 else ("净流出" if (total_net or 0) < 0 else "分化")
    flow_brief = f"申万 31 行业合计 {total_net:+.1f} 亿" if total_net is not None else "行业主力净额暂缺"

    lead_style = None
    if style_proxy:
        lead_style = sorted(style_proxy, key=lambda x: x.get("pct") or 0, reverse=True)[0]
    nb_ratio = nb.get("turnover_ratio")
    nb_desc = f'北向成交占两市 {nb_ratio * 100:.2f}%' if nb_ratio else "北向占比数据暂缺"
    style_desc = f'领涨主题：{lead_style["name"]} {lead_style["pct"]:+.2f}%' if lead_style else "主题风格数据暂缺"
    style_rating = "r1" if lead_style and (lead_style.get("pct") or 0) > 0 else ("r3" if lead_style and (lead_style.get("pct") or 0) < 0 else "r2")
    style_label = "风格偏多" if lead_style and (lead_style.get("pct") or 0) > 0 else ("风格承压" if lead_style and (lead_style.get("pct") or 0) < 0 else "风格中性")

    cards = [
        (
            "v1",
            "市场概览",
            breadth_label,
            breadth_rating,
            f"<span class=\"k\">{index_desc}</span><br>{breadth_desc}",
            "聚焦核心指数与行业涨跌家数，适合先看整体强弱。",
        ),
        (
            "v2",
            "资金主线",
            flow_label,
            flow_rating,
            f"<span class=\"u\">流入：</span>{in_desc}<br><span class=\"d\">流出：</span>{out_desc}",
            flow_brief,
        ),
        (
            "v3",
            "风格偏好",
            style_label,
            style_rating,
            f"{style_desc}<br>{nb_desc}",
            "结合主题代理与北向成交占比，看盘后风格偏向。",
        ),
    ]

    html = ['    <div class="views">\n']
    for cls, title, rating_text, rating_cls, line_html, footer in cards:
        html.append(
            f'      <div class="view {cls}">\n'
            f'        <div class="vh"><div class="vn">{title}</div><span class="rating {rating_cls}">{rating_text}</span></div>\n'
            f'        <div class="vl">{line_html}</div>\n'
            f'        <div class="vr">{footer}</div>\n'
            f'      </div>\n'
        )
    html.append("    </div>\n")
    return "".join(html)


def load_result(path):
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def write_html(path, result):
    d = result["data_date"]
    wd = _weekday_cn(d)
    css = _load_css(os.path.dirname(os.path.abspath(__file__)))
    nb = result["northbound"]
    sw = result["sw_industry"]
    S = []
    S.append(
        f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f'<meta name="description" content="stock-voyager A股资金流日报，覆盖主要指数、行业资金流、北向资金、风格雷达与热点异动。">\n'
        f'<meta name="color-scheme" content="dark">\n'
        f'<title>stock-voyager · A股资金流日报 · {d}</title>\n<style>\n{css}\n{site_nav_css()}\n</style>\n'
        f'</head>\n<body class="site-shell-body">\n<div class="wrap">\n'
    )

    S.append(
        f'''  <div class="hdr">
    <div class="hdr-l">
      <div class="logo"><svg viewBox="0 0 24 24" fill="none"><path d="M4 17l5-6 4 3 7-9" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M15 5h5v5" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div>
        <h1>stock-voyager · <em>A股资金流日报</em></h1>
        <div class="sub">收盘快照 · 资金主线 · 风格雷达 · 北向跟踪</div>
      </div>
    </div>
    <div class="hdr-r">
      <span class="live-badge"><span class="dot"></span>数据日期 {d}（{wd}）· 收盘</span>
      <div class="src-line">更新于 <b>{result["generated_at"]}</b> ｜ {product_source_text()}</div>
      <div class="src-line">北向成交日 <b>{nb.get("trade_date") or "—"}</b> ｜ 行业数据 {len(sw)} / 31</div>
    </div>
  </div>
'''
    )
    S.append('  <div class="style-note"><b style="color:var(--amber)">⚠ 非实时页面</b> ｜ 当前仅展示收盘后的静态结果，适合盘后复盘与结构观察，不展示盘中实时跳动数据。</div>\n')
    for warning in result.get("fetch_warnings") or []:
        S.append(f'  <div class="style-note"><b style="color:var(--amber)">⚠ 数据抓取提示</b> ｜ {warning}</div>\n')

    mv = result.get("market_verdict") or {}
    if mv.get("headline"):
        tone = mv.get("tone", "flat")
        tone_word = mv.get("tone_word") or {"up": "整体偏强", "down": "整体偏弱", "flat": "整体震荡"}.get(tone, "—")
        S.append(
            '  <div class="panel sec-gap">\n'
            '    <div class="p-title"><span class="bar"></span>盘面定调\n'
            '      <span class="vb-meta vb-inline">\n'
            f'        <span class="vb-tone vb-tone-{tone}">{tone_word}</span>\n'
            '      </span>\n'
            '    </div>\n'
            '    <div class="vb-body">\n'
            f'      <div class="vb-text">{mv["headline"]}</div>\n'
            '    </div>\n'
            '  </div>\n'
        )

    S.append(_panel("今日解读", "盘后速览", build_market_views(result)))

    idx_rows = []
    for x in result["indices"]:
        pct_s, cls = h_pct(x["pct"])
        prev = (x["close"] - x["chg"]) if (x["close"] is not None and x["chg"] is not None) else None
        close_s = f'{x["close"]:,.2f}' if x["close"] is not None else "—"
        prev_s = f"{prev:,.2f}" if prev is not None else "—"
        chg_s = f'{x["chg"]:+,.2f}' if x["chg"] is not None else "—"
        amt_s = h_amount(x.get("turnover"))
        idx_rows.append(
            f'      <tr>\n'
            f'        <td>{x["name"]}<span class="code">{idx_prefix(x["code"])}{x["code"]}</span></td>\n'
            f'        <td style="color:var(--txt);font-weight:700">{close_s}</td>\n'
            f'        <td class="{cls}">{pct_s}</td>\n'
            f'        <td class="{cls}">{chg_s}</td>\n'
            f'        <td style="color:var(--txt3)">{prev_s}</td>\n'
            f'        <td style="color:var(--txt2)">{amt_s}</td>\n'
            f'      </tr>'
        )
    if idx_rows:
        body = (
            '    <table class="idx-table">\n      <thead>\n'
            '        <tr><th>指数</th><th>收盘点位</th><th>涨跌幅</th><th>涨跌点</th><th>昨收</th><th>成交额</th></tr>\n'
            '      </thead>\n      <tbody>\n' + "\n".join(idx_rows) + '\n      </tbody>\n    </table>\n'
        )
    else:
        body = _empty_body("主要指数模块暂未成功生成，请稍后刷新报告。")
    S.append(_panel("主要指数", f"{d} 收盘 · 涨红跌绿", body))

    idx_by_name = {x["name"]: x for x in result["indices"]}

    def kpi(name, code, val, val_cls, chg, chg_cls, sub, glow=None):
        glow_c = f'<div class="glow-{glow}"></div>' if glow else ""
        code_tag = f'<span class="k-code">{code}</span>' if code else ""
        return (
            f'      <div class="kpi">\n'
            f'        <div class="k-name">{name} {code_tag}</div>\n'
            f'        <div class="k-val {val_cls}">{val}</div>\n'
            f'        <div class="k-chg {chg_cls}">{chg}</div>\n'
            f'        <div class="k-sub">{sub}</div>\n        {glow_c}</div>'
        )

    kpis = []
    for nm, pref, glow in (
        ("上证指数", "SH000001", "up"),
        ("深证成指", "SZ399001", "dn"),
        ("创业板指", "SZ399006", "dn"),
        ("科创50", "SH000688", "up"),
    ):
        x = idx_by_name.get(nm)
        if x and x["close"] is not None:
            pct_s, cls = h_pct(x["pct"])
            prev = (x["close"] - x["chg"]) if x["chg"] is not None else None
            sub = f'{prev:,.2f}→{x["close"]:,.2f}' if prev is not None else "—"
            kpis.append(kpi(nm, pref, f'{x["close"]:,.2f}', cls, pct_s, cls, sub, glow))

    tm = result.get("two_market") or {}
    sh, sz = tm.get("sh"), tm.get("sz")
    if sh is not None or sz is not None:
        tot = (sh or 0) + (sz or 0)
        kpis.append(kpi("两市成交额", "", h_amount(tot), "cyan", f"沪 {h_amount(sh)} · 深 {h_amount(sz)}", "cyan", "收盘口径", "cy"))
    if nb.get("turnover_ratio"):
        kpis.append(kpi("北向成交占比", "", f'{nb["turnover_ratio"] * 100:.1f}%', "cyan", "净买入未披露", "flat", "通道成交额口径", "cy"))
    net_vals = [x["main_net_in"] for x in sw if x.get("main_net_in") is not None]
    if net_vals:
        total_net = sum(net_vals) / 1e8
        cls = "up" if total_net >= 0 else "down"
        kpis.append(kpi("申万主力净流入", "", f"{total_net:+.1f}亿", cls, "31行业汇总", cls, "涨红/跌绿口径", "up" if total_net >= 0 else "dn"))
    if sw:
        up_n = sum(1 for x in sw if (x.get("pct") or 0) > 0)
        dn_n = sum(1 for x in sw if (x.get("pct") or 0) < 0)
        kpis.append(kpi("涨跌行业数", "", f"{up_n}↑ / {dn_n}↓", "up", f"共 {len(sw)} 个行业", "flat", "涨多/跌少", "up"))

    kpi_html = '    <div class="kpis">\n' + "\n".join(kpis) + "\n    </div>\n" if kpis else _empty_body("市场 KPI 数据暂缺。")
    if sw:
        ins = sorted([x for x in sw if x.get("main_net_in")], key=lambda z: z["main_net_in"], reverse=True)[:2]
        outs = sorted([x for x in sw if x.get("main_net_in")], key=lambda z: z["main_net_in"])[:2]
        in_tx = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in ins) or "—"
        out_tx = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in outs) or "—"
        ml = (
            '    <div class="mainline"><div class="ml-label">\n'
            '      <svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4.5 13.5H11L9.5 22 19 9.5h-6.5L13 2z" fill="var(--cyan)" opacity=".85"/></svg>\n      今日资金主线\n'
            f'    </div><div class="ml-item"><span class="dot" style="background:var(--up);box-shadow:0 0 8px var(--up)"></span><b class="up">主力净流入居前</b> {in_tx}</div>'
            f'<div class="ml-item"><span class="dot" style="background:var(--down);box-shadow:0 0 8px var(--down)"></span><b class="down">主力净流出居前</b> {out_tx}</div></div>\n'
        )
    else:
        ml = (
            '    <div class="mainline"><div class="ml-label">\n'
            '      <svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4.5 13.5H11L9.5 22 19 9.5h-6.5L13 2z" fill="var(--cyan)" opacity=".85"/></svg>\n      今日资金主线\n'
            '    </div><div class="ml-item"><span class="arrow">申万行业数据暂缺，无法构造资金主线。</span></div></div>\n'
        )
    S.append(_panel("核心市场总览", "收盘口径", kpi_html + ml))

    if sw:
        in_sum = sum(h_yi(x["main_net_in"]) for x in sw if x.get("main_net_in") and x["main_net_in"] > 0)
        out_sum = sum(h_yi(x["main_net_in"]) for x in sw if x.get("main_net_in") and x["main_net_in"] < 0)
        tot_m = in_sum + abs(out_sum)
        in_p = in_sum / tot_m * 100 if tot_m else 0
        out_p = abs(out_sum) / tot_m * 100 if tot_m else 0
        in_top = sorted([x for x in sw if x.get("main_net_in") and x["main_net_in"] > 0], key=lambda z: z["main_net_in"], reverse=True)[:6]
        out_top = sorted([x for x in sw if x.get("main_net_in") and x["main_net_in"] < 0], key=lambda z: z["main_net_in"])[:6]
        in_nm = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in in_top) or "—"
        out_nm = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in out_top) or "—"
        body = (
            '    <div class="dist">\n    <div class="dist-bar">\n'
            f'      <div class="seg" style="width:{out_p:.1f}%;background:linear-gradient(90deg,rgba(14,203,129,.55),rgba(14,203,129,.9))" title="流出行业合计 {out_sum:.1f}亿">流出 {out_sum:.1f}亿</div>\n'
            f'      <div class="seg" style="width:{in_p:.1f}%;background:linear-gradient(90deg,rgba(246,70,93,.6),rgba(246,70,93,.95))" title="流入行业合计 {in_sum:.1f}亿">流入 {in_sum:.1f}亿</div>\n'
            f'    </div>\n    <div class="dist-legend"><div class="it"><span class="sw" style="background:rgba(246,70,93,.9)"></span>{in_nm}</div><div class="it"><span class="sw" style="background:rgba(14,203,129,.9)"></span>{out_nm}</div></div></div>\n'
        )
    else:
        body = _empty_body("申万行业数据暂缺，无法汇总主力资金分布。")
    S.append(_panel("全市场主力资金分布", "按申万31行业汇总", body))

    if sw:
        cells = []
        for x in sorted(sw, key=lambda z: (z.get("pct") or 0), reverse=True):
            cells.append(
                f'      <div class="hcell" style="{heat_bg(x["pct"])}">\n'
                f'        <div class="hn">{x["name"]}</div>\n'
                f'        <div class="hp">{x["pct"]:+.2f}%</div>\n'
                f'        <div class="hf">主力 {h_yi_signed(x["main_net_in"])}亿</div>\n'
                f'      </div>'
            )
        heat = '    <div class="heat">\n' + "\n".join(cells) + "\n    </div>\n"
        top = sorted([x for x in sw if x.get("main_net_in") is not None], key=lambda z: abs(z["main_net_in"]), reverse=True)[:12]
        maxv = max(abs(x["main_net_in"]) for x in top) if top else 1
        rows = []
        for x in top:
            v = x["main_net_in"]
            width = (abs(h_yi(v)) / h_yi(maxv) * 46) if maxv else 0
            if v >= 0:
                bar = f'<div class="bar in" style="width:{width:.1f}%"><span class="v">+{h_yi(v):.1f}亿</span></div>'
            else:
                bar = f'<div class="bar out" style="width:{width:.1f}%"><span class="v">{h_yi(v):.1f}亿</span></div>'
            rows.append(f'      <div class="flow-row"><div class="fn">{x["name"]}</div><div class="fb">{bar}</div><div class="fn"></div></div>')
        flow = (
            '    <div class="p-title" style="margin-top:14px;margin-bottom:8px"><span class="bar"></span>行业主力净流入 TOP（红=净流入 / 绿=净流出）</div>\n'
            '    <div class="flow-wrap"><div class="flow-axis"></div>\n' + "\n".join(rows) + "\n    </div>\n"
        )
        body = heat + flow
    else:
        body = _empty_body("申万行业数据暂缺，无法绘制热力图与资金流条形。")
    S.append(_panel("申万一级行业热力图", "31 行业 · 涨红跌绿", body))

    ti, to = result["stock_top_in"], result["stock_top_out"]
    if ti or to:
        def _rank_rows(items):
            rows = []
            for i, x in enumerate(items[:10], 1):
                net = h_yi(x.get("main_net_in"))
                net_s = f"+{net:.2f}亿" if net is not None and net >= 0 else (f"{net:.2f}亿" if net is not None else "—")
                cls = "up" if (net or 0) >= 0 else "down"
                pct_s, _ = h_pct(x.get("pct"))
                rows.append(
                    f'      <div class="rank-row"><div class="rk">{i}</div>'
                    f'<div class="nm">{x["name"]}<span class="cd">{x.get("code", "")}</span>'
                    f'<span class="cd" style="color:var(--txt2)">{pct_s}</span></div>'
                    f'<div class="vv {cls}">{net_s}</div></div>'
                )
            return "\n".join(rows)

        body = (
            '    <div class="g-1-1">\n'
            '      <div><div class="p-title" style="margin-bottom:8px"><span class="bar"></span>主力净流入 TOP</div>\n'
            f'        <div class="rank">\n{_rank_rows(ti)}\n        </div>\n      </div>\n'
            '      <div><div class="p-title" style="margin-bottom:8px"><span class="bar"></span>主力净流出 TOP</div>\n'
            f'        <div class="rank">\n{_rank_rows(to)}\n        </div>\n      </div>\n'
            '    </div>\n'
        )
    else:
        body = _empty_body("个股资金流数据暂缺。")
    S.append(_panel("个股资金流排行", "主力净额 · 收盘", body))

    si = result["style_indices"]
    sp = result["style_proxy"]
    if si or sp:
        parts = []
        if si:
            rws = []
            for x in si:
                pct_s, cls = h_pct(x["pct"])
                rws.append(f'      <tr><td>{x["name"]}</td><td style="color:var(--txt);font-weight:700">{x["close"]:,.2f}</td><td class="{cls}">{pct_s}</td></tr>')
            parts.append('    <table class="idx-table">\n      <thead><tr><th>风格指数</th><th>收盘</th><th>涨跌幅</th></tr></thead>\n      <tbody>\n' + "\n".join(rws) + '\n      </tbody>\n    </table>\n')
        if sp:
            bars = []
            for x in sp:
                pct_s, _ = h_pct(x["pct"])
                width = min(abs(x["pct"]) / 3 * 50, 50)
                if x["pct"] >= 0:
                    bar = f'<div class="sa-fill" style="left:50%;width:{width:.1f}%;background:linear-gradient(90deg,rgba(246,70,93,.4),rgba(246,70,93,.95))"></div>'
                else:
                    bar = f'<div class="sa-fill" style="right:50%;width:{width:.1f}%;background:linear-gradient(270deg,rgba(14,203,129,.4),rgba(14,203,129,.95))"></div>'
                bars.append(f'      <div class="sa-bar"><div class="mid"></div>{bar}<span style="position:absolute;{"left" if x["pct"] >= 0 else "right"}:8px;top:5px;font-family:var(--mono);font-size:10.5px;color:var(--txt2)">{x["name"]} {pct_s}</span></div>')
            parts.append('    <div class="style-axis"><div class="sa-title"><span>主题代理（申万行业聚合）</span><span>跌 ◀ 　 ▶ 涨</span></div>\n' + "\n".join(bars) + "\n    </div>\n")
        body = "\n".join(parts)
    else:
        body = _empty_body("风格指数数据暂缺。")
    S.append(_panel("风格与主题", "国证风格 + 主题聚合", body))

    if nb.get("available"):
        t_r = f'{nb["turnover_ratio"] * 100:.2f}%' if nb.get("turnover_ratio") else "—"
        body = (
            '    <div class="nkpis">\n'
            f'      <div class="nkpi"><div class="nl">沪股通成交额</div><div class="nv">{h_amount(nb["sh_connect_turnover"])}</div></div>\n'
            f'      <div class="nkpi"><div class="nl">深股通成交额</div><div class="nv">{h_amount(nb["sz_connect_turnover"])}</div></div>\n'
            f'      <div class="nkpi"><div class="nl">北向合计成交额</div><div class="nv">{h_amount(nb["total_turnover"])}</div></div>\n'
            f'      <div class="nkpi"><div class="nl">成交占比(占两市)</div><div class="nv">{t_r}</div></div>\n'
            '    </div>\n'
            '    <div class="n-note">⚠ 北向净买入自 2024-08-19 起不再实时披露，本页仅展示公开的【成交额】与【成交占比】，不展示/不编造净买入数字。</div>\n'
        )
    else:
        body = _empty_body(nb.get("source", "北向数据暂缺") + "（净买入不披露，不编造）。")
    S.append(_panel("北向资金跟踪", "仅成交额 / 占比", body))

    hs = result.get("hotspots") or {}
    hot = hs.get("hot", [])
    weak = hs.get("weak", [])
    if hot or weak:
        def hcol(title, items, color):
            cards = []
            for x in items:
                pct_s, _ = h_pct(x["pct"])
                cards.append(f'      <div class="hot-card"><div class="ic" style="background:rgba(255,255,255,.05);color:var(--{color})">{x["name"][:2]}</div><div><div class="ht">{x["name"]}</div><div class="hd">涨跌幅 {pct_s}</div></div></div>')
            return f'    <div class="hot-col"><h4>{title} <span class="pill" style="background:rgba(246,70,93,.12);color:var(--up-b)">TOP {len(items)}</span></h4>\n' + "\n".join(cards) + "\n    </div>"

        body = '    <div class="hot">\n' + hcol("今日热点（涨幅前）", hot, "up-b") + hcol("今日异动（跌幅前）", weak, "down-b") + "    </div>\n"
    else:
        body = _empty_body("热点/异动板块数据暂缺。")
    S.append(_panel("热点与异动板块", "申万行业涨跌 TOP", body))

    S.append(
        f'''  <div class="foot">
    <b>数据日期</b>：{d}（{wd}，收盘后口径）　｜　<b>更新时间</b>：{result["generated_at"]}<br>
    <b>数据来源</b>：{product_source_text()}；北向成交额为公开披露项，<b>净买入不披露、不编造</b>。<br>
    <b>明细来源</b>：{result["source"]}<br>
    <b>口径说明</b>：涨红跌绿（A股惯例）；成交额/净流入单位为元，展示折算为亿/万亿；行业与个股口径以公开行情数据为准。
  </div>
  <div class="disclaimer">本报告由 <a href="https://github.com/ycbc-team/stock-voyager" target="_blank" rel="noopener noreferrer" style="color:var(--amber);font-weight:600;text-decoration:none">stock-voyager</a> 生成 · 仅供研究参考，不构成投资建议</div>
'''
    )
    S.append(f"</div>\n{render_site_nav('fundflow')}\n</body>\n</html>\n")

    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(S))


def main():
    ap = argparse.ArgumentParser(description="A股收盘 HTML 渲染脚本（读取 build/data/fundflow.json，输出 build/site/fundflow.html）")
    input_dir = default_input_dir()
    output_dir = default_output_dir()
    ap.add_argument("--input", default=os.path.join(input_dir, "fundflow.json"), help="输入 JSON 路径")
    ap.add_argument("--output", default=os.path.join(output_dir, "fundflow.html"), help="输出 HTML 路径")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit(f"找不到输入 JSON：{args.input}")

    result = load_result(args.input)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    write_html(args.output, result)
    print(f"[✓] HTML 已写出：{args.output}")


if __name__ == "__main__":
    main()
