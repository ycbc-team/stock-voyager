#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股收盘数据生产脚本
===================

职责：
  1. 抓取 A 股收盘核心数据
  2. 每个请求模块单独写出 JSON 到 build/cache/
  3. 汇总生成 build/data/fundflow.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


from common.market_data import DC_HEADERS
from common.market_data import REQUEST_DELAY
from common.market_data import call_akshare_with_retry
from common.market_data import detect_trade_date
from common.market_data import diff_list
from common.market_data import em_get
from common.market_data import get_akshare
from common.market_data import get_request_count
from common.market_data import http_get
from common.market_data import load_or_fetch_stock_fundflow_build
from common.market_data import reset_request_count
from common.market_data import to_float
from common.storage import default_data_dir
from common.storage import load_build_json
from common.storage import load_cache_json
from common.storage import save_build_json
from common.storage import save_cache_json
from common.storage import save_data_json
from common.storage import write_json


INDICES = [
    ("上证指数", "1.000001"),
    ("深证成指", "0.399001"),
    ("创业板指", "0.399006"),
    ("科创50", "1.000688"),
    ("沪深300", "1.000300"),
    ("中证2000", "1.932000"),
    ("上证50", "1.000016"),
    ("中证500", "1.000905"),
    ("中证1000", "1.000852"),
]
SW_INDUSTRY = {
    "801010": "农林牧渔", "801030": "基础化工", "801040": "钢铁", "801050": "有色金属",
    "801080": "电子", "801110": "家用电器", "801120": "食品饮料", "801130": "纺织服饰",
    "801140": "轻工制造", "801150": "医药生物", "801160": "公用事业", "801170": "交通运输",
    "801180": "房地产", "801200": "商贸零售", "801210": "社会服务", "801230": "综合",
    "801710": "建筑材料", "801720": "建筑装饰", "801730": "电力设备", "801740": "国防军工",
    "801750": "计算机", "801760": "传媒", "801770": "通信", "801780": "银行",
    "801790": "非银金融", "801880": "汽车", "801890": "机械设备", "801950": "煤炭",
    "801960": "石油石化", "801970": "环保", "801980": "美容护理",
}
STYLE_INDEX = [
    ("大盘成长", "0.399372"),
    ("大盘价值", "0.399373"),
    ("中盘成长", "0.399374"),
    ("中盘价值", "0.399375"),
    ("小盘成长", "0.399376"),
    ("小盘价值", "0.399377"),
]
STYLE_PROXY = {
    "金融防御": ["801780", "801790"],
    "医药景气": ["801150"],
    "科技成长": ["801080", "801750", "801770", "801760", "801730"],
    "周期资源": ["801050", "801040", "801950", "801960", "801030", "801710", "801720", "801890", "801740", "801880", "801170"],
}

SOURCE_EM = "东方财富 East Money 公开行情接口（与证券时报·数据宝同源）"
SOURCE_GT = "腾讯财经 gtimg 接口（回退源）"
SOURCE_SW = "AKShare 申万一级指数 + 东方财富个股资金流聚合"
STATIC_CACHE_SCHEMA_VERSION = 1


def _pick_amount(row: Dict[str, Any], *fields: str) -> Optional[float]:
    for field in fields:
        value = to_float(row.get(field))
        if value is not None and 1e11 <= abs(value) <= 1e13:
            return value
    return None


def _load_or_fetch_static_cache(filename: str, loader, *, source: str, refresh_policy: str):
    cached = load_cache_json(filename)
    if cached is not None:
        return cached, "common/cache"
    payload = loader()
    save_cache_json(
        filename,
        payload,
        source=source,
        ttl_hours=None,
        tags={
            "cache_version": STATIC_CACHE_SCHEMA_VERSION,
            "refresh_policy": refresh_policy,
        },
    )
    return payload, "fresh"


def _build_filename(stem: str, data_date: str) -> str:
    return f"{stem}_{data_date}.json"


def _load_or_fetch_build(filename: str, loader):
    cached = load_build_json(filename)
    if cached is not None:
        return cached
    payload = loader()
    save_build_json(filename, payload)
    return payload


def _fetch_market_snapshot_payload(data_date: Optional[str] = None) -> Dict[str, Any]:
    indices: List[Dict[str, Any]] = []
    style_indices: List[Dict[str, Any]] = []
    sh_amount = None
    sz_amount = None
    prev_total: Optional[float] = None
    source = SOURCE_EM

    secids = ",".join(secid for _, secid in INDICES) + "," + ",".join(secid for _, secid in STYLE_INDEX)
    data = em_get("/api/qt/ulist.np/get", {"fields": "f12,f14,f2,f3,f4,f6,f62", "secids": secids})
    if data:
        rows = {row.get("f12"): row for row in diff_list(data.get("data", {}))}
        for name, secid in INDICES:
            code = secid.split(".")[1]
            row = rows.get(code)
            if not row:
                continue
            close = to_float(row.get("f2"))
            pct = to_float(row.get("f3"))
            chg = to_float(row.get("f4"))
            indices.append(
                {
                    "name": name,
                    "code": code,
                    "close": close / 100 if close is not None else None,
                    "pct": pct / 100 if pct is not None else None,
                    "chg": chg / 100 if chg is not None else None,
                    "main_net_in": to_float(row.get("f62")),
                    "turnover": to_float(row.get("f6")),
                    "source": SOURCE_EM,
                }
            )
        for name, secid in STYLE_INDEX:
            code = secid.split(".")[1]
            row = rows.get(code)
            if not row:
                continue
            close = to_float(row.get("f2"))
            pct = to_float(row.get("f3"))
            style_indices.append(
                {
                    "name": name,
                    "code": code,
                    "close": close / 100 if close is not None else None,
                    "pct": pct / 100 if pct is not None else None,
                    "source": SOURCE_EM,
                }
            )
        if rows.get("000001"):
            sh_amount = _pick_amount(rows["000001"], "f6", "f7", "f8", "f67")
        if rows.get("399001"):
            sz_amount = _pick_amount(rows["399001"], "f6", "f7", "f8", "f67")

    if data_date:
        try:
            ak = get_akshare()
            sh_df = call_akshare_with_retry("上证指数日K(取前一日成交额)", ak.stock_zh_index_daily_em, symbol="sh000001")
            sz_df = call_akshare_with_retry("深证成指日K(取前一日成交额)", ak.stock_zh_index_daily_em, symbol="sz399001")
            if (
                sh_df is not None and sz_df is not None
                and not sh_df.empty and not sz_df.empty
                and "成交额" in sh_df.columns and "成交额" in sz_df.columns
            ):
                sh_df = sh_df.tail(60)
                sz_df = sz_df.tail(60)
                sh_mask = sh_df["日期"].astype(str) < data_date
                sz_mask = sz_df["日期"].astype(str) < data_date
                if sh_mask.any() and sz_mask.any():
                    prev_total = float(sh_df.loc[sh_mask].iloc[-1]["成交额"]) + float(sz_df.loc[sz_mask].iloc[-1]["成交额"])
        except Exception:
            prev_total = None

    if not indices:
        source = SOURCE_GT
        want = {secid.split(".")[1]: name for name, secid in INDICES}
        codes = ",".join(
            f"sh{secid.split('.')[1]}" if secid.startswith("1.") else f"sz{secid.split('.')[1]}"
            for _, secid in INDICES
        )
        text = http_get(f"https://qt.gtimg.cn/q={codes}", {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}, timeout=15, retries=3)
        if text:
            for segment in text.split(";"):
                segment = segment.strip()
                if not segment.startswith("v_"):
                    continue
                name = segment.split("~")[1]
                parts = segment.split("~")
                code = None
                for code_candidate, expected_name in want.items():
                    if expected_name == name:
                        code = code_candidate
                        break
                if code is None:
                    continue
                indices.append(
                    {
                        "name": name,
                        "code": code,
                        "close": to_float(parts[3]),
                        "pct": to_float(parts[32]),
                        "chg": to_float(parts[31]),
                        "main_net_in": None,
                        "turnover": None,
                        "source": SOURCE_GT,
                    }
                )

    return {
        "indices": indices,
        "style_indices": style_indices,
        "two_market": {"sh": sh_amount, "sz": sz_amount, "prev_total": prev_total},
        "source": source,
    }


def load_or_fetch_market_snapshot(data_date: str) -> Dict[str, Any]:
    return _load_or_fetch_build(_build_filename("fundflow_market_snapshot", data_date), lambda: _fetch_market_snapshot_payload(data_date))


def _fetch_sw_mapping_payload() -> Dict[str, Any]:
    by_code = {code: {"code": code, "name": name} for code, name in SW_INDUSTRY.items()}
    return {
        "by_code": by_code,
        "mutable": False,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_sw_mapping() -> Tuple[Dict[str, Any], str]:
    payload, source = _load_or_fetch_static_cache(
        "sw_mapping.json",
        _fetch_sw_mapping_payload,
        source="内置申万一级常量映射",
        refresh_policy="immutable_reference_data",
    )
    source_text = "common/cache" if source == "common/cache" else "内置申万一级常量"
    return payload, source_text


def _fetch_sw_stock_map_payload() -> Dict[str, Any]:
    ak = get_akshare()
    stock_to_industry: Dict[str, str] = {}
    industry_sizes: Dict[str, int] = {}
    failed_industries: List[str] = []
    for code in SW_INDUSTRY:
        try:
            df = call_akshare_with_retry(f"申万成分股 {code}", ak.index_component_sw, symbol=code)
        except Exception:
            failed_industries.append(code)
            continue
        count = 0
        for row in df.to_dict("records"):
            stock_code = str(row.get("证券代码") or "").zfill(6)
            if stock_code:
                stock_to_industry[stock_code] = code
                count += 1
        industry_sizes[code] = count
    return {
        "stock_to_industry": stock_to_industry,
        "industry_sizes": industry_sizes,
        "failed_industries": failed_industries,
        "is_complete": len(failed_industries) == 0,
        "mutable": True,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_sw_stock_map(required_codes: Optional[List[str]] = None) -> Tuple[Dict[str, str], str]:
    cached = load_cache_json("sw_stock_map.json")
    cached_map = dict((cached or {}).get("stock_to_industry") or {})
    required = {str(code).zfill(6) for code in (required_codes or []) if code}
    missing_codes = sorted(code for code in required if code not in cached_map)
    if cached_map and not missing_codes:
        return cached_map, "common/cache"

    refresh_reason = "cold_start"
    if cached_map and missing_codes:
        refresh_reason = f"missing_codes:{','.join(missing_codes[:20])}"
    payload = _fetch_sw_stock_map_payload()
    refreshed_map = dict(payload.get("stock_to_industry") or {})
    failed_industries = list(payload.get("failed_industries") or [])
    is_complete = bool(payload.get("is_complete"))
    source = "AKShare 申万成分股"

    if is_complete:
        save_cache_json(
            "sw_stock_map.json",
            payload,
            source="AKShare 申万成分股",
            ttl_hours=None,
            tags={
                "cache_version": STATIC_CACHE_SCHEMA_VERSION,
                "refresh_policy": "refresh_when_required_codes_are_missing",
                "refresh_reason": refresh_reason,
                "missing_codes_refreshed": missing_codes,
            },
        )
    elif cached_map:
        preserved_map = {
            stock_code: industry_code
            for stock_code, industry_code in cached_map.items()
            if industry_code in failed_industries
        }
        merged_map = dict(refreshed_map)
        merged_map.update(preserved_map)
        payload = {
            **payload,
            "stock_to_industry": merged_map,
            "is_complete": False,
            "merged_with_existing_cache": True,
        }
        save_cache_json(
            "sw_stock_map.json",
            payload,
            source="AKShare 申万成分股（失败行业沿用旧缓存）",
            ttl_hours=None,
            tags={
                "cache_version": STATIC_CACHE_SCHEMA_VERSION,
                "refresh_policy": "refresh_when_required_codes_are_missing",
                "refresh_reason": refresh_reason,
                "missing_codes_refreshed": missing_codes,
                "failed_industries": failed_industries,
                "merged_with_existing_cache": True,
            },
        )
        refreshed_map = merged_map
        source = f"AKShare 申万成分股（{len(failed_industries)} 个行业失败，已保留旧缓存映射）"
    else:
        source = f"AKShare 申万成分股（{len(failed_industries)} 个行业失败，未写入 common/cache）"

    if missing_codes:
        source += f"（检测到 {len(missing_codes)} 只未映射股票，已自动刷新）"
    return refreshed_map, source


def _fetch_sw_index_spot_payload() -> Dict[str, Any]:
    ak = get_akshare()
    rows: List[Dict[str, Any]] = []
    source = "AKShare 申万一级指数实时行情"
    try:
        df = call_akshare_with_retry("申万一级指数", ak.index_realtime_sw, symbol="一级行业")
    except Exception as exc:
        return {"rows": [], "source": f"AKShare 申万一级指数接口暂不可用: {exc}"}
    for row in df.to_dict("records"):
        code = str(row.get("指数代码") or "").replace(".SI", "").strip()
        if code not in SW_INDUSTRY:
            continue
        prev = to_float(row.get("昨收盘"))
        close = to_float(row.get("最新价"))
        pct = None
        if prev not in (None, 0) and close is not None:
            pct = (close - prev) / prev * 100
        rows.append({"code": code, "name": SW_INDUSTRY[code], "close": close, "pct": pct, "source": source})
    return {"rows": rows, "source": source if rows else "AKShare 申万一级指数接口暂不可用"}


def load_or_fetch_sw_index_spot(data_date: str) -> Dict[str, Any]:
    return _load_or_fetch_build(_build_filename("fundflow_sw_index_spot", data_date), _fetch_sw_index_spot_payload)


def build_sw_industry(sw_spot: List[Dict[str, Any]], stock_rows: List[Dict[str, Any]], sw_mapping: Dict[str, Any], stock_to_industry: Dict[str, str]) -> List[Dict[str, Any]]:
    sw_map = (sw_mapping or {}).get("by_code") or {code: {"code": code, "name": name} for code, name in SW_INDUSTRY.items()}
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


def _fetch_northbound_dc() -> Optional[Dict[str, Any]]:
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_MUTUAL_DEAL_HISTORY",
        "columns": "ALL",
        "pageSize": "30",
        "sortColumns": "TRADE_DATE,MUTUAL_TYPE",
        "sortTypes": "-1,1",
        "source": "WEB",
        "client": "WEB",
    }
    text = http_get(f"{url}?{urllib.parse.urlencode(params)}", DC_HEADERS, timeout=15, retries=3)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    rows = (payload.get("result") or {}).get("data") or []
    days = sorted({str(row.get("TRADE_DATE", ""))[:10] for row in rows}, reverse=True)
    if not days:
        return None
    day = days[0]
    by_type: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if str(row.get("TRADE_DATE", ""))[:10] == day:
            by_type[str(row.get("MUTUAL_TYPE"))] = row

    def deal(mutual_type: str) -> Optional[float]:
        value = by_type.get(mutual_type, {}).get("DEAL_AMT")
        return value * 1e6 if value is not None else None

    sh_turnover = deal("001")
    sz_turnover = deal("002")
    total_turnover = deal("005")
    if total_turnover is None and sh_turnover is not None and sz_turnover is not None:
        total_turnover = sh_turnover + sz_turnover
    if sh_turnover is None and sz_turnover is None and total_turnover is None:
        return None
    return {
        "trade_date": day,
        "sh_connect_turnover": sh_turnover,
        "sz_connect_turnover": sz_turnover,
        "total_turnover": total_turnover,
        "available": True,
        "source": "东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY（kamt 不可用时的兜底）",
    }


def _fetch_northbound_payload(sh_amount: Optional[float], sz_amount: Optional[float]) -> Dict[str, Any]:
    result = {
        "trade_date": None,
        "sh_connect_turnover": None,
        "sz_connect_turnover": None,
        "total_turnover": None,
        "turnover_ratio": None,
        "net_buy": None,
        "net_buy_note": "北向净买入自2024-08-19起不再实时披露，本脚本不取/不编造该字段",
        "source": "东方财富 kamt 接口（成交额为公开披露项；净买入不披露）",
        "available": False,
    }
    fields = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
    data = em_get("/api/qt/kamt/get", {"fields": fields})
    if data:
        payload = data.get("data") or {}
        klines = payload.get("klines") if isinstance(payload, dict) else None
        if isinstance(klines, list) and klines:
            last = klines[-1]
            parts = last.split(",") if isinstance(last, str) else []
            field_names = fields.split(",")
            record = {field_names[index]: parts[index] for index in range(min(len(field_names), len(parts)))}
            total_turnover = to_float(record.get("f55")) or to_float(record.get("f54"))
            sh_turnover = to_float(record.get("f59")) or to_float(record.get("f58"))
            sz_turnover = to_float(record.get("f63")) or to_float(record.get("f62"))
            if total_turnover is None and sh_turnover is not None and sz_turnover is not None:
                total_turnover = sh_turnover + sz_turnover
            trade_date = record.get("f51")
            if trade_date and len(str(trade_date)) >= 8:
                result["trade_date"] = str(trade_date)[:10]
            if total_turnover is not None or sh_turnover is not None or sz_turnover is not None:
                result["sh_connect_turnover"] = sh_turnover
                result["sz_connect_turnover"] = sz_turnover
                result["total_turnover"] = total_turnover
                result["available"] = True
                return result
    dc_payload = _fetch_northbound_dc()
    if dc_payload:
        result["trade_date"] = dc_payload["trade_date"]
        result["sh_connect_turnover"] = dc_payload["sh_connect_turnover"]
        result["sz_connect_turnover"] = dc_payload["sz_connect_turnover"]
        result["total_turnover"] = dc_payload["total_turnover"]
        result["available"] = True
        result["source"] = dc_payload["source"]
        return result
    result["source"] = "东方财富 kamt/数据中心接口均不可用（被限流或未披露；不编造净买入）"
    return result


def _with_northbound_turnover_ratio(payload: Dict[str, Any], sh_amount: Optional[float], sz_amount: Optional[float]) -> Dict[str, Any]:
    result = dict(payload or {})
    total_turnover = to_float(result.get("total_turnover"))
    two_market_amount = (to_float(sh_amount) or 0) + (to_float(sz_amount) or 0)
    result["turnover_ratio"] = None
    if total_turnover and two_market_amount:
        result["turnover_ratio"] = total_turnover / two_market_amount
    return result


def load_or_fetch_northbound(data_date: str, sh_amount: Optional[float], sz_amount: Optional[float]) -> Dict[str, Any]:
    payload = _load_or_fetch_build(_build_filename("fundflow_northbound", data_date), lambda: _fetch_northbound_payload(sh_amount, sz_amount))
    return _with_northbound_turnover_ratio(payload, sh_amount, sz_amount)


def compute_style_proxy(sw_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_code = {row["code"]: row for row in sw_list}
    out = []
    for name, codes in STYLE_PROXY.items():
        pcts = [to_float(by_code[code]["pct"]) for code in codes if code in by_code and to_float(by_code[code]["pct"]) is not None]
        if pcts:
            out.append({"name": name, "pct": sum(pcts) / len(pcts), "members": [by_code[code]["name"] for code in codes if code in by_code]})
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

    纯数据驱动、无外部依赖、不调用任何模型：
      输入全部来自 collect_report_data 已产出的字段（指数/行业/主题/北向），
      输出一句确定性中文摘要 + 基调标签（偏强/偏弱/震荡），供 HTML 顶部横幅展示。
    """
    indices = report_data.get("indices") or []
    sw = report_data.get("sw_industry") or []
    sp = report_data.get("style_proxy") or []
    nb = report_data.get("northbound") or {}

    # 1) 大盘方向：核心指数涨跌幅均值
    core_names = ("上证指数", "深证成指", "创业板指")
    core_pcts = [x["pct"] for x in indices if x.get("name") in core_names and x.get("pct") is not None]
    avg_pct = (sum(core_pcts) / len(core_pcts)) if core_pcts else None

    # 2) 主题强弱（style_proxy 已按申万行业聚合）
    sp_sorted = sorted(sp, key=lambda x: x.get("pct") or 0)
    lead_theme = sp_sorted[-1] if sp_sorted else None
    weak_theme = sp_sorted[0] if sp_sorted else None

    # 3) 行业：领涨 / 主力净流入居前
    sw_pct = sorted([x for x in sw if x.get("pct") is not None], key=lambda x: x["pct"], reverse=True)
    sw_net = sorted([x for x in sw if x.get("main_net_in") is not None], key=lambda x: x["main_net_in"], reverse=True)
    top_net = sw_net[:2] if sw_net else []

    # 4) 北向成交占比
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


def fetch_market_breadth(data_date: str) -> Dict[str, Any]:
    """抓取全市场个股涨跌家数 + 涨停/跌停数量（AKShare 东方财富源）。

    口径：收盘快照；剔除北交所（代码 8 开头 / 920 开头）以对齐沪深A股广度惯例。
    单源失败不影响整体，缺失字段置 None，由渲染层显示「—」。
    """
    ak = get_akshare()
    warnings: List[str] = []
    out: Dict[str, Any] = {
        "available": False,
        "advance": None,
        "decline": None,
        "flat": None,
        "limit_up": None,
        "limit_down": None,
        "source": "",
        "warnings": warnings,
    }
    yyyymmdd = str(data_date).replace("-", "")

    # 1) 涨停 / 跌停 池（东方财富，仅近 30 交易日）
    try:
        zt = call_akshare_with_retry("涨停池", ak.stock_zt_pool_em, date=yyyymmdd)
        dt = call_akshare_with_retry("跌停池", ak.stock_zt_pool_dtgc_em, date=yyyymmdd)
        out["limit_up"] = int(len(zt)) if zt is not None else None
        out["limit_down"] = int(len(dt)) if dt is not None else None
    except Exception as e:  # noqa: BLE001
        warnings.append(f"涨停/跌停池获取失败: {e}")

    # 2) 全市场个股涨跌家数（东方财富 spot）
    try:
        spot = call_akshare_with_retry("全市场涨跌家数", ak.stock_zh_a_spot_em)
        if spot is not None and len(spot) > 0:
            codes = spot["代码"].astype(str)
            keep = ~codes.str.startswith(("8", "920"))  # 剔除北交所
            df = spot[keep]
            pct = df["涨跌幅"].astype(float, errors="coerce")
            out["advance"] = int((pct > 0).sum())
            out["decline"] = int((pct < 0).sum())
            out["flat"] = int(((pct == 0) & df["成交量"].notna()).sum())
            out["source"] = "东方财富个股行情"
    except Exception as e:  # noqa: BLE001
        warnings.append(f"全市场涨跌家数获取失败: {e}")

    out["available"] = any(v is not None for v in (out["advance"], out["limit_up"]))
    return out


def collect_report_data(data_date: Optional[str] = None, topn: int = 10, verbose: bool = True) -> Dict[str, Any]:
    reset_request_count()
    resolved_date = data_date or detect_trade_date("ashare")
    fetch_warnings: List[str] = []
    if verbose:
        print(f"[*] 数据日期: {resolved_date}")

    market_snapshot = load_or_fetch_market_snapshot(resolved_date)
    indices = market_snapshot.get("indices") or []
    style_indices = market_snapshot.get("style_indices") or []
    idx_source = market_snapshot.get("source") or SOURCE_EM
    sh_amount = (market_snapshot.get("two_market") or {}).get("sh")
    sz_amount = (market_snapshot.get("two_market") or {}).get("sz")
    if verbose:
        print(f"[+] 指数 {len(indices)} 条 + 风格 {len(style_indices)} 条（{idx_source}）")

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

    breadth = fetch_market_breadth(resolved_date)
    if verbose:
        print(f"[+] 个股涨跌家数: {'可用' if breadth['available'] else '暂不可用'}（{breadth['source'] or '—'}）")
    for w in breadth.get("warnings", []):
        fetch_warnings.append(w)

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
        "style_indices": style_indices,
        "style_indices_source": idx_source,
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


def main() -> Dict[str, Any]:
    parser = argparse.ArgumentParser(description="A股收盘数据生产脚本：按请求拆分 JSON 产物，并汇总生成 build/data/fundflow.json")
    parser.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    parser.add_argument("--out", help="页面 JSON 输出目录（默认 <项目根>/build/data）")
    parser.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    args = parser.parse_args()

    result = collect_report_data(data_date=args.date, topn=args.topn, verbose=True)
    path = write_report_json(result, out_dir=args.out)
    print(f"\n[✓] 数据产物已写出：\n    {path}")
    print(f"[i] 本次共发起 {get_request_count()} 次外部请求（含 HTTP 与 AKShare 重试；请求间隔 {REQUEST_DELAY}s）")
    return result


if __name__ == "__main__":
    main()
