#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""stocktrend 数据加工与页面组装层。

职责：
  - 调用 stocktrend_data_fetcher 的「请求函数」获取原始快照（fetcher 只负责请求 / 复用缓存，不做加工）
  - 在本层完成数据加工：综合评分、建仓价位、跨 3 年盈利质量排雷、申万一级行业映射、信号文案等
  - 组装成 renderer 可直接消费的页面 JSON（A 股 / 港股）

架构对齐 fundflow：fetcher 只做数据请求，加工 / 派生指标外置于本 processor 模块；
main.py 与 make_snapshot.py 只 import 本模块的 collect_pages / write_page_jsons，不直接碰 fetcher。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from common.market_data import detect_trade_date
from common.storage import default_data_dir
from common.storage import load_build_json
from common.storage import save_data_json
from common.storage import write_json

from stocktrend.stocktrend_data_fetcher import (
    A_SHARE_STOCKS,
    A_SHARE_SECTORS,
    A_SHARE_COMBOS,
    SECTOR_RISK_TEXT,
    _to_float,
    _fmt_pct,
    _fmt_signed_pct,
    _fmt_yi,
    _fmt_signed_yi,
    _fmt_market_cap,
    _load_ashare_spot,
    _load_hist_cache,
    _fetch_stock_connect_holdings,
    _build_aggregate_warning,
    _build_holding_warning,
    _fetch_ashare_main_flow,
    _fetch_ashare_margin,
    _fetch_hist_rows,
    _compute_hist_stats,
    _latest_hist_row,
    _prev_close_from_hist,
    _fetch_ashare_dividends,
    _fetch_ashare_financial_snapshot,
    _load_hk_base_data,
    _load_hk_spot,
    _fetch_hk_financial_indicator,
    _fetch_hk_financial_analysis,
    _fetch_hk_dividends,
)


def _build_issue_text(label: str, issue: Optional[str]) -> Optional[str]:
    text = str(issue or "").strip()
    if not text:
        return None
    return f"{label}异常：{text}"


def _score_band(value: Optional[float], bands: List[tuple], default: int = 5, reverse: bool = False) -> int:
    if value is None:
        return default
    for threshold, score in bands:
        if (value <= threshold) if reverse else (value >= threshold):
            return score
    return default


def _compute_score(roe: Optional[float], pe: Optional[float], div: Optional[float],
                   liab: Optional[float], pos: Optional[float], margin: Optional[float]):
    """综合评分(0-100) + 分项(模型估算，仅供参考)。分项权对齐外部: ROE30/估值25/分红15/财务15/护城河15。"""
    parts: Dict[str, int] = {}
    parts["roe"] = _score_band(roe, [(20, 30), (15, 24), (10, 18), (5, 12)], 6)
    val = _score_band(pe, [(15, 22), (20, 17), (25, 13), (30, 9)], 5, reverse=True)
    if pos is not None and pos <= 40:
        val = min(val + 3, 25)
    parts["val"] = val
    parts["div"] = _score_band(div, [(4, 15), (3, 12), (2, 9), (1, 6)], 3)
    parts["fin"] = _score_band(liab, [(40, 15), (50, 12), (60, 9), (70, 6)], 3, reverse=True)
    parts["moat"] = _score_band(margin, [(60, 15), (40, 12), (25, 9), (15, 6)], 3)
    total = sum(parts.values())
    return total, parts


def _compute_build(price: Optional[float], w52l: Optional[float], w52h: Optional[float],
                  pos: Optional[float], pe: Optional[float], eps: Optional[float],
                  last_div: Optional[float], div_yield: Optional[float]) -> Optional[Dict[str, Any]]:
    """建仓价位测算(模型估算)。仅基于 52 周区间 + PE 推导，不编造行情数据。"""
    if price is None or price <= 0:
        return None
    if pos is None:
        view = "估值位置暂缺"
    elif pos <= 40 and (pe is None or pe <= 20):
        view = "✅ 已处于低估区"
    elif pos <= 65 and (pe is None or pe <= 30):
        view = "🟡 估值合理"
    else:
        view = "⚠️ 估值偏高"
    dist = round((price - w52l) / price * 100, 1) if w52l else None
    tiers = []
    if w52l:
        probe = round(price * 0.97, 2)
        add = round(w52l + (price - w52l) * 0.30, 2)
        heavy = round(w52l * 1.02, 2)
        for name, p in (("试探仓", probe), ("加仓", add), ("重仓", heavy)):
            dy = round(last_div / p * 100, 2) if last_div else None
            tiers.append({"name": name, "price": p, "dy": dy})
    target = None
    fair_pe = None
    buy_pe = None
    buy_target = None
    dist_to_buy = None
    if pe and pe > 0 and eps:
        if pos is not None and pos <= 40:
            fair_pe = round(pe * 1.15, 1)
        elif pos is not None and pos <= 65:
            fair_pe = round(pe * 1.0, 1)
        else:
            fair_pe = round(pe * 0.88, 1)
        target = round(fair_pe * eps, 2)
        # 建议买入 PE：在合理中枢基础上再留 15% 安全边际
        buy_pe = round(fair_pe * 0.85, 1)
        buy_target = round(buy_pe * eps, 2)
        if price and buy_target:
            dist_to_buy = round((price - buy_target) / price * 100, 1)
    return {
        "view": view,
        "dist": dist,
        "tiers": tiers,
        "target": target,
        "fair_pe": fair_pe,
        "buy_pe": buy_pe,
        "buy_target": buy_target,
        "dist_to_buy": dist_to_buy,
        "div_yield": div_yield,
    }


def _compute_defense(fin3: List[Dict[str, Any]], last_div: Optional[float] = None) -> Dict[str, Any]:
    """近3年盈利质量排雷(模型估算)。输出「排雷结论」要点列表。

    判定逻辑对齐外部链接（定性多维）：以绝对水平 + 趋势方向为准，
    低负债 / 高 ROE / 正现金流 / 稳毛利率即判「通过」；仅当出现明确
    恶化信号（高杠杆、现金流转负、毛利率暴跌、ROE 腰斩）才降级。
    废弃旧版「关键词计数」法——其把低负债股的微小波动误判为风险。
    """
    if not fin3:
        return {"level": "关注", "reasons": ["近3年财报暂缺，无法自动排雷，仅供参考"]}
    roes = [f["roe"] for f in fin3 if f.get("roe") is not None]
    liabs = [f["liab"] for f in fin3 if f.get("liab") is not None]
    margins = [f["margin"] for f in fin3 if f.get("margin") is not None]
    ocfps = [f["ocfps"] for f in fin3 if f.get("ocfps") is not None]
    good: List[str] = []
    bad: List[str] = []
    # 1) ROE：绝对水平（>=15% 为优质线）
    if roes:
        if min(roes) >= 15:
            good.append(f"ROE 维持在 {min(roes):.1f}%-{max(roes):.1f}% 高位，盈利能力稳健")
        elif min(roes) >= 8:
            good.append(f"ROE 约 {min(roes):.1f}%-{max(roes):.1f}%，盈利尚可")
        else:
            bad.append(f"ROE 降至 {min(roes):.1f}%，盈利能力偏弱")
    # 2) 资产负债率：绝对水平为主 + 最新一期方向
    if liabs:
        latest = liabs[-1]
        trend_up = len(liabs) >= 2 and latest > liabs[-2] + 3
        if latest < 40:
            good.append(f"资产负债率 {latest:.1f}%，绝对水平低、财务结构稳健"
                        + ("（较上期小幅上升）" if trend_up else ""))
        elif latest < 65:
            if trend_up:
                bad.append(f"资产负债率升至 {latest:.1f}%，关注财务杠杆")
            else:
                good.append(f"资产负债率 {latest:.1f}%，处于行业中游、结构可控")
        else:
            bad.append(f"资产负债率高达 {latest:.1f}%，财务杠杆偏高")
    # 3) 经营现金流
    if ocfps:
        if min(ocfps) > 0:
            cov = (ocfps[0] / last_div) if last_div else None
            cov_txt = f"（覆盖分红约 {cov:.2f} 倍）" if cov else ""
            good.append(f"经营现金流持续为正，主业回款健康{cov_txt}")
        else:
            bad.append("经营现金流阶段性转负，关注回款质量")
    # 4) 毛利率稳定性
    if len(margins) >= 2:
        if abs(margins[-1] - margins[0]) <= 5:
            good.append(f"毛利率约 {margins[-1]:.1f}%，主业盈利能力稳定")
        else:
            bad.append(f"毛利率由 {margins[0]:.1f}% 变动至 {margins[-1]:.1f}%，关注盈利结构")
    if not good and not bad:
        return {"level": "关注", "reasons": ["各项指标稳健，未见明显排雷信号"]}
    # 判定：有 bad 才降级
    if not bad:
        level = "通过"
        reasons = good
    elif len(bad) == 1:
        level = "关注"
        reasons = good + bad
    else:
        level = "不通过"
        reasons = good + bad
    return {"level": level, "reasons": reasons}


def _build_signal(pos: Optional[float], pe: Optional[float], div: Optional[float], main_inflow: Optional[float]) -> int:
    score = 0
    if pos is not None and pos <= 35:
        score += 1
    elif pos is not None and pos >= 75:
        score -= 1
    if pe is not None and pe > 0 and pe <= 20:
        score += 1
    elif pe is not None and pe >= 35:
        score -= 1
    if div is not None and div >= 2.5:
        score += 1
    if main_inflow is not None and main_inflow > 0:
        score += 1
    if score >= 3:
        return 0
    if score <= 0:
        return 2
    return 1


def _build_generic_texts(name: str, sector_key: str, pe: Optional[float], pos: Optional[float], main_inflow: Optional[float], north_pct: Optional[float]) -> Dict[str, Any]:
    signal = _build_signal(pos, pe, None, main_inflow)
    suggest = "可分批关注" if signal == 0 else "持有观察" if signal == 1 else "谨慎观望"
    pe_text = "亏损或暂缺" if pe is None or pe <= 0 else f"PE {pe:.1f}"
    pos_text = "52周位置暂缺" if pos is None else f"52周分位 {pos:.0f}%"
    flow_text = "主力净流入暂缺" if main_inflow is None else f"主力净流入 {_fmt_signed_yi(main_inflow)}"
    north_text = "北向持股暂缺" if north_pct is None else f"北向占总股本 {_fmt_pct(north_pct)}"
    sector_cn = {"consumer": "消费", "healthcare": "医药", "manufacturing": "制造",
                  "tech": "科技", "finance": "金融", "resource": "资源", "cycle": "周期"}.get(sector_key, "所属")
    return {
        "signal": signal,
        "suggest": suggest,
        "summary": f"{name} 当前以 {pe_text}、{pos_text} 为核心跟踪锚点，{flow_text}，{north_text}。",
        "summary_moat": f"护城河：{name} 在{sector_cn}领域具备规模与品牌壁垒，盈利质量相对稳定。",
        "summary_trend": f"行业趋势：{name} 处于 {pos_text}，需结合行业景气与估值位置跟踪。",
        "summary_idea": f"操作思路：{suggest}，{flow_text}；{north_text}。单只标的建议不超过组合的 15%-20%，并分散行业与风格。",
        "trend": f"{name} 处于 {pos_text} 区间，建议结合估值位置与成交活跃度做分批观察。",
        "capital": f"{flow_text}；{north_text}。",
        "risks": SECTOR_RISK_TEXT[sector_key],
    }


def _build_generic_hk_texts(name: str, sector_key: str, pe: Optional[float], pos: Optional[float], div: Optional[float], south_pct: Optional[float]) -> Dict[str, Any]:
    signal = _build_signal(pos, pe, div, None)
    suggest = "可分批关注" if signal == 0 else "持有观察" if signal == 1 else "谨慎观望"
    pe_text = "亏损或暂缺" if pe is None or pe <= 0 else f"PE {pe:.1f}"
    pos_text = "52周位置暂缺" if pos is None else f"52周分位 {pos:.0f}%"
    south_text = "南向持股暂缺" if south_pct is None else f"南向持股占比 {_fmt_pct(south_pct)}"
    div_text = "股息率暂缺" if div is None else f"股息率 {_fmt_pct(div)}"
    sector_cn = {"consumer": "消费", "healthcare": "医药", "manufacturing": "制造",
                  "tech": "科技", "finance": "金融", "resource": "资源", "cycle": "周期"}.get(sector_key, "所属")
    return {
        "signal": signal,
        "suggest": suggest,
        "summary": f"{name} 当前以 {pe_text}、{pos_text} 为核心跟踪锚点，{div_text}，{south_text}。",
        "summary_moat": f"护城河：{name} 在{sector_cn}领域具备规模与品牌壁垒，盈利质量相对稳定。",
        "summary_trend": f"行业趋势：{name} 处于 {pos_text}，需结合行业景气与估值位置跟踪。",
        "summary_idea": f"操作思路：{suggest}，{south_text}；{div_text}。单只标的建议不超过组合的 15%-20%，并分散行业与风格。",
        "trend": f"{name} 处于 {pos_text} 区间，建议结合估值位置、区间涨跌与南向持股变化做跟踪。",
        "capital": f"{south_text}；{div_text}。",
        "risks": SECTOR_RISK_TEXT.get(sector_key, ["行业景气波动", "估值回撤风险", "市场风格切换风险"]),
    }


def _load_sw_l1_mapping() -> Dict[str, str]:
    """股票 6 位代码 -> 申万一级行业中文名（本地静态映射，不发网络请求）。"""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        cache_dir = os.path.normpath(os.path.join(here, "..", "common", "cache"))
        with open(os.path.join(cache_dir, "sw_stock_map.json"), encoding="utf-8") as fh:
            stock_map = json.load(fh)
        with open(os.path.join(cache_dir, "sw_mapping.json"), encoding="utf-8") as fh:
            sw_map = json.load(fh)
    except Exception:
        return {}
    s2i = (stock_map.get("data") or {}).get("stock_to_industry") or {}
    by_code = sw_map.get("by_code") or {}
    out: Dict[str, str] = {}
    for code, lvl1 in s2i.items():
        name = (by_code.get(lvl1) or {}).get("name")
        if name:
            out[str(code).zfill(6)] = name
    return out


def _build_ashare_page(trade_date: str) -> Dict[str, Any]:
    ashare_codes = [item["code"] for item in A_SHARE_STOCKS]
    spot_map = _load_ashare_spot(trade_date)
    hist_payload = _load_hist_cache("ashare", ashare_codes, trade_date)
    hist_warning = _build_aggregate_warning(hist_payload, "A股历史行情")
    north_payload = _fetch_stock_connect_holdings(ashare_codes, trade_date, "ashare_northbound", "A股北向持股")
    north_warning = _build_holding_warning(north_payload, "A股北向持股")
    north_map = {
        str(code).zfill(6): {
            "north_shares": row.get("shares"),
            "north_pct": row.get("pct"),
            "north_date": row.get("holding_date"),
            "issue": row.get("issue"),
        }
        for code, row in (north_payload.get("items") or {}).items()
    }
    flow_map = _fetch_ashare_main_flow(ashare_codes, trade_date)
    margin_map = _fetch_ashare_margin(trade_date)
    sw_l1_map = _load_sw_l1_mapping()
    stocks: List[Dict[str, Any]] = []

    for meta in A_SHARE_STOCKS:
        code = meta["code"]
        spot = spot_map.get(code, {})
        hist_rows = _fetch_hist_rows("ashare", code, trade_date)
        hist_stats = _compute_hist_stats(hist_rows)
        hist_last = _latest_hist_row(hist_rows)
        prev_close = _prev_close_from_hist(hist_rows)
        dividends = _fetch_ashare_dividends(code, trade_date)
        financial = _fetch_ashare_financial_snapshot(code, trade_date)
        north = north_map.get(code, {})
        flow = flow_map.get(code, {})
        margin = margin_map.get(code, {})

        price = _to_float(hist_last.get("收盘")) or _to_float(spot.get("最新价"))
        div_ttm_ps = dividends.get("div_ttm_ps")
        last_div = div_ttm_ps
        if last_div is None:
            for value in reversed(dividends.get("div5") or []):
                if value is not None:
                    last_div = value
                    break
        div_yield = None
        if price not in (None, 0) and last_div is not None:
            div_yield = last_div / price * 100

        fin3 = financial.get("fin3") or []
        fin3_annual = [f for f in fin3 if f.get("annual")]

        generated = _build_generic_texts(meta["zh"], meta["sector"], _to_float(spot.get("市盈率-动态")), hist_stats.get("pos"), flow.get("main_net_in"), north.get("north_pct"))
        score, score_parts = _compute_score(
            financial.get("roe"), _to_float(spot.get("市盈率-动态")), div_yield,
            financial.get("liab"), hist_stats.get("pos"), financial.get("margin"),
        )
        build = _compute_build(
            price, hist_stats.get("w52l"), hist_stats.get("w52h"), hist_stats.get("pos"),
            _to_float(spot.get("市盈率-动态")), financial.get("eps"), last_div, div_yield,
        )
        defense = _compute_defense(fin3_annual, last_div)
        stock_issues = []
        for issue_text in [
            _build_issue_text("历史行情", None if hist_rows else "公开接口返回空数据"),
            _build_issue_text("财务分析", financial.get("issue")),
            _build_issue_text("分红", dividends.get("issue")),
            _build_issue_text("北向持股", north.get("issue")),
        ]:
            if issue_text:
                stock_issues.append(issue_text)
        stocks.append(
            {
                **meta,
                "market": "ashare",
                "exchange": "SH" if code.startswith("6") else "SZ",
                "price": price,
                "chg": _to_float(hist_last.get("涨跌幅")) if _to_float(hist_last.get("涨跌幅")) is not None else _to_float(spot.get("涨跌幅")),
                "change": _to_float(hist_last.get("涨跌额")) if _to_float(hist_last.get("涨跌额")) is not None else _to_float(spot.get("涨跌额")),
                "pe": _to_float(spot.get("市盈率-动态")),
                "pb": _to_float(spot.get("市净率")),
                "div": div_yield,
                "mkt_raw": _to_float(spot.get("总市值")),
                "mkt": _fmt_market_cap(_to_float(spot.get("总市值"))),
                "open": _to_float(hist_last.get("开盘")) or _to_float(spot.get("今开")),
                "prev": prev_close if prev_close is not None else _to_float(spot.get("昨收")),
                "amount_raw": _to_float(hist_last.get("成交额")) if _to_float(hist_last.get("成交额")) is not None else _to_float(spot.get("成交额")),
                "amount": _fmt_yi(_to_float(hist_last.get("成交额")) if _to_float(hist_last.get("成交额")) is not None else _to_float(spot.get("成交额"))),
                "turn": _to_float(hist_last.get("换手率")) if _to_float(hist_last.get("换手率")) is not None else _to_float(spot.get("换手率")),
                "w52l": hist_stats.get("w52l"),
                "w52h": hist_stats.get("w52h"),
                "pos": hist_stats.get("pos"),
                "chg5": hist_stats.get("chg5"),
                "chg20": hist_stats.get("chg20"),
                "chg60": hist_stats.get("chg60") if hist_stats.get("chg60") is not None else _to_float(spot.get("60日涨跌幅")),
                "ytd": hist_stats.get("ytd") if hist_stats.get("ytd") is not None else _to_float(spot.get("年初至今涨跌幅")),
                "roe": financial.get("roe"),
                "margin": financial.get("margin"),
                "liab": financial.get("liab"),
                "eps": financial.get("eps"),
                "financial_report_year": financial.get("report_year"),
                "financial_report_period": financial.get("report_period"),
                "financial_source": financial.get("source"),
                "financial_as_of": financial.get("as_of"),
                "div5": dividends.get("div5") or [],
                "div_years": dividends.get("div_years") or [],
                "div_ttm": div_ttm_ps,
                "dividend_source": dividends.get("source"),
                "dividend_as_of": dividends.get("as_of"),
                "main_inflow": flow.get("main_net_in"),
                "north_pct": north.get("north_pct"),
                "north_shares": north.get("north_shares"),
                "north_date": north.get("north_date"),
                "north_value": None,
                "margin_balance": margin.get("margin_balance"),
                "margin_buy": margin.get("margin_buy"),
                "margin_date": margin.get("margin_date"),
                "history_as_of": trade_date,
                "data_issues": stock_issues,
                "score": score,
                "score_parts": score_parts,
                "build": build,
                "defense": defense,
                "fin3": fin3,
                "fin3_annual": fin3_annual,
                "sw_l1": sw_l1_map.get(code),
                **generated,
            }
        )

    return {
        "meta": {
            "market_code": "ashare",
            "title": "A股核心个股走势分析",
            "tag": f"静态收盘快照 · 非实时 · {trade_date}",
            "subtitle": "聚焦核心 A 股清单，便于按估值、位置、资金面、财务与风险提示做盘后复盘。",
            "date": f"非实时页面：{trade_date} 收盘快照",
            "databadge": "⚠️ 数据口径：本页仅展示收盘后的静态结果；价格、估值、资金面、财务与分红为公开数据整理，缺失字段直接显示“—”。",
            "modal_databadge": "⚠️ 本页为静态收盘快照：价格、涨跌、成交额、市值、估值均对应收盘口径；主力净流入为当日口径；分红 / 财务指标取公开披露值，若缺失则显示“—”。",
            "disclaimer": "⚠️ 免责声明：页面仅做公开数据整理与展示，不构成投资建议。",
            "footer": f"A股核心个股走势分析 · 静态收盘快照 · {trade_date}",
            "snap_iso": trade_date,
            "currency_unit": "元",
            "money_unit": "亿元",
            "flow_label": "主力净流入",
            "holding_label": "北向持股",
            "holding_pct_label": "北向占总股本比",
            "show_roster": True,
            "roster_title": "ROE 分层观察名单（A股）",
            "roster_note": "若公开财务摘要可得，则按最近年度 ROE 分层展示；缺失则不强行补值。",
            "combo_section_title": "三种观察组合",
            "combo_note": "组合仅用于页面浏览时的快速分组，不代表实际持仓建议。",
            "fetch_warnings": [item for item in [hist_warning, north_warning, _build_aggregate_warning(load_build_json(f"stocktrend_ashare_financials_{trade_date}.json") or {}, "A股财务分析"), _build_aggregate_warning(load_build_json(f"stocktrend_ashare_dividends_{trade_date}.json") or {}, "A股分红")] if item],
        },
        "sectors": A_SHARE_SECTORS,
        "combos": A_SHARE_COMBOS,
        "stocks": stocks,
    }


def _build_hk_page(trade_date: str) -> Dict[str, Any]:
    base_data = _load_hk_base_data()
    base_stocks = {str(item["code"]).zfill(5): item for item in base_data["stocks"]}
    spot_map = _load_hk_spot(trade_date)
    hk_codes = sorted(base_stocks.keys())
    hist_payload = _load_hist_cache("hk", hk_codes, trade_date)
    hist_warning = _build_aggregate_warning(hist_payload, "港股历史行情")
    south_payload = _fetch_stock_connect_holdings(hk_codes, trade_date, "hk_southbound", "港股通持股")
    south_warning = _build_holding_warning(south_payload, "港股通持股")
    south_map = {
        str(code).zfill(5): {
            "south_shares": row.get("shares"),
            "south_pct": row.get("pct"),
            "south_date": row.get("holding_date"),
            "issue": row.get("issue"),
        }
        for code, row in (south_payload.get("items") or {}).items()
    }
    stocks: List[Dict[str, Any]] = []

    for code, base in base_stocks.items():
        spot = spot_map.get(code, {})
        hist_rows = _fetch_hist_rows("hk", code, trade_date)
        hist_stats = _compute_hist_stats(hist_rows)
        hist_last = _latest_hist_row(hist_rows)
        prev_close = _prev_close_from_hist(hist_rows)
        fin = _fetch_hk_financial_indicator(code, trade_date)
        fin_analysis = _fetch_hk_financial_analysis(code, trade_date)
        dividends = _fetch_hk_dividends(code, trade_date)
        southbound = south_map.get(code, {})
        generated = _build_generic_hk_texts(
            base["zh"],
            base["sector"],
            fin.get("pe"),
            hist_stats.get("pos"),
            fin.get("div"),
            southbound.get("south_pct"),
        )
        stock_issues = []
        for issue_text in [
            _build_issue_text("历史行情", None if hist_rows else "公开接口返回空数据"),
            _build_issue_text("港股核心指标", fin.get("issue")),
            _build_issue_text("财务分析", fin_analysis.get("issue")),
            _build_issue_text("分红", dividends.get("issue")),
            _build_issue_text("南向持股", southbound.get("issue")),
        ]:
            if issue_text:
                stock_issues.append(issue_text)

        stocks.append(
            {
                **base,
                "market": "hk",
                "exchange": "HK",
                "price": _to_float(hist_last.get("收盘")) or _to_float(spot.get("最新价")),
                "chg": _to_float(hist_last.get("涨跌幅")) if _to_float(hist_last.get("涨跌幅")) is not None else _to_float(spot.get("涨跌幅")),
                "change": _to_float(hist_last.get("涨跌额")) if _to_float(hist_last.get("涨跌额")) is not None else _to_float(spot.get("涨跌额")),
                "pe": fin.get("pe"),
                "pb": fin.get("pb"),
                "div": fin.get("div"),
                "mkt_raw": fin.get("mkt_raw"),
                "mkt": _fmt_market_cap(fin.get("mkt_raw")) if fin.get("mkt_raw") is not None else None,
                "open": _to_float(hist_last.get("开盘")) or _to_float(spot.get("今开")),
                "prev": prev_close if prev_close is not None else _to_float(spot.get("昨收")),
                "amount_raw": _to_float(hist_last.get("成交额")) if _to_float(hist_last.get("成交额")) is not None else _to_float(spot.get("成交额")),
                "amount": _fmt_yi(_to_float(hist_last.get("成交额")) if _to_float(hist_last.get("成交额")) is not None else _to_float(spot.get("成交额"))),
                "turn": _to_float(hist_last.get("换手率")) if _to_float(hist_last.get("换手率")) is not None else _to_float(spot.get("换手率")),
                "w52l": hist_stats.get("w52l"),
                "w52h": hist_stats.get("w52h"),
                "pos": hist_stats.get("pos"),
                "chg5": hist_stats.get("chg5"),
                "chg20": hist_stats.get("chg20"),
                "chg60": hist_stats.get("chg60"),
                "ytd": hist_stats.get("ytd"),
                "roe": fin_analysis.get("roe") if fin_analysis.get("roe") is not None else fin.get("roe"),
                "margin": fin_analysis.get("margin"),
                "liab": fin_analysis.get("liab"),
                "financial_report_year": fin_analysis.get("report_year"),
                "financial_source": fin_analysis.get("source") or fin.get("source"),
                "financial_as_of": fin_analysis.get("as_of") or fin.get("as_of"),
                "div5": dividends.get("div5") or [],
                "div_years": dividends.get("div_years") or [],
                "dividend_source": dividends.get("source"),
                "dividend_as_of": dividends.get("as_of"),
                "south": southbound.get("south_pct"),
                "south_pct": southbound.get("south_pct"),
                "south_shares": southbound.get("south_shares"),
                "south_date": southbound.get("south_date"),
                "history_as_of": trade_date,
                "signal": generated["signal"],
                "capital": generated["capital"],
                "trend": generated["trend"],
                "suggest": generated["suggest"],
                "summary": generated["summary"],
                "risks": base.get("risks") or generated["risks"],
                "data_issues": stock_issues,
            }
        )

    meta = dict(base_data["meta"])
    meta.update(
        {
            "market_code": "hk",
            "tag": f"静态收盘快照 · 非实时 · {trade_date}",
            "date": f"非实时页面：{trade_date} 收盘快照",
            "databadge": "⚠️ 数据口径：本页仅展示收盘后的静态结果；价格、估值、南向持股、财务与分红为公开数据整理，缺失字段直接显示“—”。",
            "modal_databadge": "⚠️ 本页为静态模板 + 实时数据：价格、涨跌、成交额对应收盘口径；PE / PB / 股息率、财务分析、分红派息、南向持股均优先取公开接口实时结果。",
            "disclaimer": "⚠️ 免责声明：页面仅做公开数据整理与展示，不构成投资建议。行业分类、组合分组与风险提示为静态模板配置；价格、估值、财务、分红、南向持股为实时公开数据。",
            "footer": f"{meta.get('title', '港股核心个股走势分析')} · 静态收盘快照 · {trade_date}",
            "snap_iso": trade_date,
            "currency_unit": "港元",
            "money_unit": "亿港元",
            "flow_label": "成交额",
            "holding_label": "南向持股",
            "holding_pct_label": "南向持股比例",
            "show_roster": True,
            "roster_title": "ROE 分层观察名单（港股）",
            "roster_note": "若公开财务分析可得，则按最近可取 ROE 分层展示；缺失则不强行补值。",
            "fetch_warnings": [item for item in [hist_warning, south_warning, _build_aggregate_warning(load_build_json(f"stocktrend_hk_financials_{trade_date}.json") or {}, "港股核心指标"), _build_aggregate_warning(load_build_json(f"stocktrend_hk_financial_analysis_{trade_date}.json") or {}, "港股财务分析"), _build_aggregate_warning(load_build_json(f"stocktrend_hk_dividends_{trade_date}.json") or {}, "港股分红派息")] if item],
        }
    )
    return {"meta": meta, "sectors": base_data["sectors"], "combos": base_data["combos"], "stocks": stocks}


def collect_pages(data_date: Optional[str] = None, market: str = "all") -> Dict[str, Dict[str, Any]]:
    trade_date = data_date or detect_trade_date(market)
    pages: Dict[str, Dict[str, Any]] = {}
    if market in {"all", "ashare"}:
        pages["ashare"] = _build_ashare_page(trade_date)
    if market in {"all", "hk"}:
        pages["hk"] = _build_hk_page(trade_date)
    return pages


def write_page_jsons(pages: Dict[str, Dict[str, Any]], out_dir: Optional[str] = None) -> List[str]:
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    written = []
    if "ashare" in pages:
        path = os.path.join(out_dir, "stocktrend_ashare.json") if out_dir else save_data_json("stocktrend_ashare.json", pages["ashare"], source=pages["ashare"]["meta"].get("footer"), tags={"market": "ashare", "data_date": pages["ashare"]["meta"].get("snap_iso")})
        if out_dir:
            write_json(path, {"_meta": {"cache_scope": "page_data", "market": "ashare", "data_date": pages["ashare"]["meta"].get("snap_iso")}, "data": pages["ashare"]})
        written.append(path)
    if "hk" in pages:
        path = os.path.join(out_dir, "stocktrend_hk.json") if out_dir else save_data_json("stocktrend_hk.json", pages["hk"], source=pages["hk"]["meta"].get("footer"), tags={"market": "hk", "data_date": pages["hk"]["meta"].get("snap_iso")})
        if out_dir:
            write_json(path, {"_meta": {"cache_scope": "page_data", "market": "hk", "data_date": pages["hk"]["meta"].get("snap_iso")}, "data": pages["hk"]})
        written.append(path)
    return written


def main() -> Dict[str, Dict[str, Any]]:
    parser = argparse.ArgumentParser(description="stocktrend 数据加工脚本：请求(fetcher) + 加工(本模块)拆分 JSON 产物，并汇总生成 stocktrend 页面 JSON")
    parser.add_argument("--date", help="交易日 YYYY-MM-DD，默认使用共享交易日判断逻辑")
    parser.add_argument("--market", choices=["all", "ashare", "hk"], default="all", help="输出市场，默认 all")
    parser.add_argument("--out", help="输出目录，默认 <项目根>/build/data")
    args = parser.parse_args()

    pages = collect_pages(data_date=args.date, market=args.market)
    written = write_page_jsons(pages, out_dir=args.out)
    print("\n[✓] 数据产物已写出：")
    for path in written:
        print(f"    {path}")
    return pages


if __name__ == "__main__":
    main()
