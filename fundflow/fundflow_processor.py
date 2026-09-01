#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股资金流 · 中间数据层（加工 / 装配）
===============================

与 fundflow_data_fetcher.py 严格分层：

  - fundflow_data_fetcher.py 只负责「抓取 + 适配器 + 缓存」：
      发起外部请求，把响应适配成可序列化结构（如 DataFrame → list），
      并写入 build/cache。不掺杂任何业务加工逻辑。
  - 本模块只负责「加工 / 装配」：
      编排 fetcher 的各路抓取结果，做纯本地计算与业务聚合
      （申万行业聚合、风格代理、热点/异动、盘面定调、涨停/跌停→申万映射等），
      产出 renderer 最终消费的 result 结构。全部为纯计算，不发起任何外部请求。
"""
from __future__ import annotations

import datetime
import os
import sys
from typing import Any, Dict, List, Optional, Tuple


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


from common.market_data import detect_trade_date
from common.market_data import get_request_count
from common.market_data import reset_request_count
from common.market_data import to_float
from common.storage import save_data_json
from common.storage import write_json
from common.storage import load_build_json

from fundflow.fundflow_data_fetcher import SOURCE_EM
from fundflow.fundflow_data_fetcher import STYLE_PROXY
from fundflow.fundflow_data_fetcher import _build_filename
from fundflow.fundflow_data_fetcher import fetch_market_breadth
from fundflow.fundflow_data_fetcher import fetch_sw_mapping
from fundflow.fundflow_data_fetcher import fetch_sw_stock_map
from fundflow.fundflow_data_fetcher import load_or_fetch_market_snapshot
from fundflow.fundflow_data_fetcher import load_or_fetch_northbound
from fundflow.fundflow_data_fetcher import load_or_fetch_stock_fundflow_build
from fundflow.fundflow_data_fetcher import load_or_fetch_sw_index_spot


SOURCE_SW = "AKShare 申万一级指数 + 东方财富个股资金流聚合"


def build_sw_industry(sw_spot: List[Dict[str, Any]], stock_rows: List[Dict[str, Any]], sw_mapping: Dict[str, Any], stock_to_industry: Dict[str, str]) -> List[Dict[str, Any]]:
    sw_map = (sw_mapping or {}).get("by_code") or {}
    sums: Dict[str, float] = {}
    for row in stock_rows:
        code = row["code"]
        industry_code = stock_to_industry.get(code)
        if industry_code not in sw_map:
            continue
        sums[industry_code] = sums.get(industry_code, 0.0) + (to_float(row.get("main_net_in")) or 0.0)
    out = []
    for row in sw_spot:
        code = row["code"]
        meta = sw_map.get(code) or {"code": code, "name": row["name"]}
        out.append(
            {
                "code": code,
                "name": meta["name"],
                "close": row.get("close"),
                "pct": row.get("pct"),
                "main_net_in": sums.get(code),
                "source": SOURCE_SW,
            }
        )
    return out


def compute_style_proxy(sw_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_code = {row["code"]: row for row in sw_list}
    out = []
    for name, codes in STYLE_PROXY.items():
        present = [by_code[c] for c in codes if c in by_code]
        pcts = [to_float(r["pct"]) for r in present if to_float(r.get("pct")) is not None]
        if not pcts:
            continue
        net_vals = [to_float(r.get("main_net_in")) for r in present if to_float(r.get("main_net_in")) is not None]
        out.append(
            {
                "name": name,
                "pct": sum(pcts) / len(pcts),
                "main_net_in": sum(net_vals) if net_vals else None,  # A3: 主题主力净流入(聚合申万行业)
                "members": [r["name"] for r in present],
                "constituents": [  # A4: 成分透明(聚合的申万行业及各自涨跌/资金)
                    {"name": r["name"], "pct": to_float(r.get("pct")), "main_net_in": to_float(r.get("main_net_in"))}
                    for r in present
                ],
            }
        )
    return out


def fetch_stock_fundflow_top(topn: int, stock_rows: List[Dict[str, Any]], stock_source: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    rows_in = [row for row in stock_rows if row.get("main_net_in") is not None]
    rows_in.sort(key=lambda row: row["main_net_in"], reverse=True)
    top_in = rows_in[:topn]
    rows_out = [row for row in stock_rows if row.get("main_net_in") is not None]
    rows_out.sort(key=lambda row: row["main_net_in"])
    top_out = rows_out[:topn]
    return top_in, top_out, (stock_source if (top_in or top_out) else "东方财富个股资金流排行接口暂不可用")


def compute_hotspots(sw_list: List[Dict[str, Any]], topn: int = 5) -> Dict[str, List[Dict[str, Any]]]:
    valid = [row for row in sw_list if to_float(row["pct"]) is not None]
    valid.sort(key=lambda row: row["pct"], reverse=True)
    return {"hot": valid[:topn], "weak": valid[-topn:][::-1]}


def _dedupe_texts(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def generate_market_verdict(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """根据已抓取的收盘数据，规则化生成一句话『盘面定调』。

    纯数据驱动、无外部依赖、不调用任何模型；输入全部来自 collect_report_data
    已产出的字段（指数/行业/主题/北向），输出确定性中文摘要 + 基调标签。
    """
    indices = report_data.get("indices") or []
    sw = report_data.get("sw_industry") or []
    sp = report_data.get("style_proxy") or []
    nb = report_data.get("northbound") or {}

    core_names = ("上证指数", "深证成指", "创业板指")
    core_pcts = [x["pct"] for x in indices if x.get("name") in core_names and x.get("pct") is not None]
    avg_pct = (sum(core_pcts) / len(core_pcts)) if core_pcts else None

    sp_sorted = sorted(sp, key=lambda x: x.get("pct") or 0)
    lead_theme = sp_sorted[-1] if sp_sorted else None
    weak_theme = sp_sorted[0] if sp_sorted else None

    sw_pct = sorted([x for x in sw if x.get("pct") is not None], key=lambda x: x["pct"], reverse=True)
    sw_net = sorted([x for x in sw if x.get("main_net_in") is not None], key=lambda x: x["main_net_in"], reverse=True)
    top_net = sw_net[:2] if sw_net else []

    nb_ratio = nb.get("turnover_ratio")

    clauses = []
    if lead_theme and lead_theme.get("pct") is not None:
        lt = lead_theme["pct"]
        verb = "领涨" if lt >= 0 else "相对抗跌"
        clauses.append(f"{lead_theme['name']}（{lt:+.2f}%）{verb}")
    if top_net:
        net_names = "、".join(x["name"] for x in top_net)
        clauses.append(f"{net_names}主力净流入居前")
    if weak_theme and weak_theme is not lead_theme and (weak_theme.get("pct") or 0) < 0:
        clauses.append(f"{weak_theme['name']}（{weak_theme['pct']:+.2f}%）承压")

    part1 = "，".join(clauses)

    if avg_pct is not None:
        if avg_pct > 0:
            idx_txt = f"主要指数收涨 {avg_pct:+.2f}%"
        elif avg_pct < 0:
            idx_txt = f"主要指数收跌 {avg_pct:+.2f}%"
        else:
            idx_txt = "主要指数持平"
    else:
        idx_txt = "主要指数数据暂缺"
    nb_txt = f"北向成交占比 {nb_ratio * 100:.1f}%" if nb_ratio is not None else "北向占比暂缺"

    if avg_pct is None:
        tone, tone_word = "flat", "方向不明"
    elif avg_pct > 0.15:
        tone, tone_word = "up", "偏强"
    elif avg_pct < -0.15:
        tone, tone_word = "down", "偏弱"
    else:
        tone, tone_word = "flat", "震荡"

    if part1:
        headline = f"{part1}；{idx_txt}，{nb_txt}，整体{tone_word}。"
    elif avg_pct is not None or nb_ratio is not None:
        headline = f"{idx_txt}，{nb_txt}，整体{tone_word}。"
    else:
        headline = "当日数据暂缺，无法生成盘面定调。"

    return {"headline": headline, "tone": tone, "tone_word": tone_word, "avg_pct": avg_pct}


def enrich_sw_with_limit_stocks(breadth: Dict[str, Any], sw_list: List[Dict[str, Any]], stock_to_industry: Dict[str, str]) -> None:
    """涨停/跌停股 → 申万一级行业 领涨/领跌映射（数据驱动，零编造）。

    纯本地映射，不发起请求。结果就地写入 sw_list[].zt / sw_list[].dt（每行业 top3）。
    """
    zt_by_ind: Dict[str, List[Dict[str, Any]]] = {}
    dt_by_ind: Dict[str, List[Dict[str, Any]]] = {}
    for pool_key, target in (("zt_list", zt_by_ind), ("dt_list", dt_by_ind)):
        for s in (breadth.get(pool_key) or []):
            ind_code = stock_to_industry.get(str(s.get("code", "")))
            if not ind_code:
                continue
            target.setdefault(ind_code, []).append({"name": s.get("name", ""), "pct": s.get("pct")})
    for it in sw_list:
        zt = sorted(zt_by_ind.get(it["code"], []), key=lambda z: (z.get("pct") or 0), reverse=True)[:3]
        dt = sorted(dt_by_ind.get(it["code"], []), key=lambda z: (z.get("pct") or 0))[:3]
        it["zt"] = zt
        it["dt"] = dt


def _enrich_northbound_pct_chg(nb: Dict[str, Any], data_date: str) -> None:
    """北向成交额环比（A3）：读 build/cache 前一日北向缓存，算成交额环比。纯本地读取，零请求。"""
    try:
        d = datetime.datetime.strptime(data_date, "%Y-%m-%d") - datetime.timedelta(days=1)
        prev_date = d.strftime("%Y-%m-%d")
    except Exception:
        return
    prev = load_build_json(_build_filename("fundflow_northbound", prev_date))
    if not isinstance(prev, dict):
        return
    prev_total = to_float(prev.get("total_turnover"))
    cur_total = to_float(nb.get("total_turnover"))
    if prev_total and cur_total:
        nb["prev_total_turnover"] = prev_total
        nb["turnover_pct_chg"] = (cur_total - prev_total) / prev_total * 100


def collect_report_data(data_date: Optional[str] = None, topn: int = 10, verbose: bool = True) -> Dict[str, Any]:
    reset_request_count()
    resolved_date = data_date or detect_trade_date("ashare")
    fetch_warnings: List[str] = []
    if verbose:
        print(f"[*] 数据日期: {resolved_date}")

    market_snapshot = load_or_fetch_market_snapshot(resolved_date)
    indices = market_snapshot.get("indices") or []
    idx_source = market_snapshot.get("source") or SOURCE_EM
    sh_amount = (market_snapshot.get("two_market") or {}).get("sh")
    sz_amount = (market_snapshot.get("two_market") or {}).get("sz")
    if verbose:
        print(f"[+] 指数 {len(indices)} 条（{idx_source}）")

    sw_mapping, sw_mapping_source = fetch_sw_mapping()
    if verbose:
        print(f"[+] 申万一级映射: {len((sw_mapping or {}).get('by_code', {}))}/31 条（{sw_mapping_source}）")

    sw_index_spot_payload = load_or_fetch_sw_index_spot(resolved_date)
    sw_spot = sw_index_spot_payload.get("rows") or []
    sw_spot_source = sw_index_spot_payload.get("source") or "申万一级指数接口暂不可用"
    if verbose:
        print(f"[+] 申万一级指数: {len(sw_spot)}/31 条（{sw_spot_source}）")

    stock_rows, stock_rows_source, stock_rows_artifact = load_or_fetch_stock_fundflow_build(
        resolved_date,
        scope="full",
    )
    if verbose:
        print(f"[+] 个股资金流全市场: {len(stock_rows)} 条（{stock_rows_source}）")

    stock_codes_today = [str(row.get("code") or "").zfill(6) for row in stock_rows if row.get("code")]
    stock_to_industry, stock_map_source = fetch_sw_stock_map(required_codes=stock_codes_today)
    if verbose:
        print(f"[+] 申万成分股映射: {len(stock_to_industry)} 条股票映射（{stock_map_source}）")
    missing_industry_codes = sorted(code for code in stock_codes_today if code not in stock_to_industry)
    if missing_industry_codes:
        fetch_warnings.append(f"仍有 {len(missing_industry_codes)} 只股票未匹配到申万行业，行业聚合时已跳过。")

    sw_list = build_sw_industry(sw_spot, stock_rows, sw_mapping, stock_to_industry)
    sw_source = f"{sw_spot_source} + {stock_rows_source}"
    if verbose:
        print(f"[+] 申万一级行业聚合: {len(sw_list)}/31 条（{sw_source}）")
    if not sw_spot:
        fetch_warnings.append(f"申万一级指数数据异常：{sw_spot_source}")

    northbound = load_or_fetch_northbound(resolved_date, sh_amount, sz_amount)
    if verbose:
        print(f"[+] 北向资金: {'可用' if northbound['available'] else '暂不可用'}（{northbound['source']}）")
    if not northbound["available"]:
        fetch_warnings.append(f"北向资金数据异常：{northbound['source']}")
    _enrich_northbound_pct_chg(northbound, resolved_date)  # A3: 北向成交额环比（读缓存，零请求）

    breadth = fetch_market_breadth(resolved_date)
    if verbose:
        print(f"[+] 个股涨跌家数: {'可用' if breadth['available'] else '暂不可用'}（{breadth['source'] or '—'}）")
    for w in breadth.get("warnings", []):
        fetch_warnings.append(w)

    # 涨停/跌停股 → 申万一级行业 领涨/领跌映射（数据驱动，零编造）
    enrich_sw_with_limit_stocks(breadth, sw_list, stock_to_industry)

    style_proxy = compute_style_proxy(sw_list)
    if verbose:
        print(f"[+] 风格代理: {len(style_proxy)} 条主题（金融防御/医药景气/科技成长/周期资源）")

    top_in, top_out, stock_source = fetch_stock_fundflow_top(topn, stock_rows=stock_rows, stock_source=stock_rows_source)
    hotspots = compute_hotspots(sw_list)

    overall_source = SOURCE_SW if (sw_list or northbound["available"] or top_in) else "腾讯gtimg(指数回退)+AKShare/东方财富(受限)"
    result = {
        "data_date": resolved_date,
        "source": overall_source,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note_northbound": "北向净买入自2024-08-19起不再披露，仅取成交额与成交占比，不编造净买入。",
        "indices": indices,
        "sw_industry": sw_list,
        "sw_industry_source": sw_source,
        "northbound": northbound,
        "breadth": breadth,
        "two_market": {"sh": sh_amount, "sz": sz_amount},
        "style_proxy": style_proxy,
        "stock_top_in": top_in,
        "stock_top_out": top_out,
        "stock_source": stock_source,
        "hotspots": hotspots,
        "request_count": get_request_count(),
        "fetch_warnings": _dedupe_texts(fetch_warnings),
        "artifacts": {
            "market_snapshot": _build_filename("fundflow_market_snapshot", resolved_date),
            "sw_index_spot": _build_filename("fundflow_sw_index_spot", resolved_date),
            "stock_fundflow": stock_rows_artifact,
            "northbound": _build_filename("fundflow_northbound", resolved_date),
        },
    }
    result["market_verdict"] = generate_market_verdict(result)
    return result


def write_report_json(result: Dict[str, Any], out_dir: Optional[str] = None) -> str:
    if out_dir:
        path = os.path.join(out_dir, "fundflow.json")
        payload = {
            "_meta": {
                "cache_scope": "page_data",
                "source": result.get("source"),
                "data_date": result.get("data_date"),
                "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "data": result,
        }
        write_json(path, payload)
        return path
    return save_data_json("fundflow.json", result, source=result.get("source"), tags={"data_date": result.get("data_date")})
