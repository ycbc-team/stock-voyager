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

def _compute_index_note(df, data_date) -> Optional[str]:
    """指数卡定性副标：均线定位(A) + 区间高低(B)。失败/数据不足返回 None。"""
    try:
        if df is None or getattr(df, "empty", True):
            return None
        d = df.copy()
        d["日期"] = d["日期"].astype(str)
        if data_date:
            d = d[d["日期"] <= str(data_date)]
        if d.empty or "收盘" not in d.columns:
            return None
        closes = d["收盘"].astype(float)
        last = float(closes.iloc[-1])
        ma_parts = []
        for n in (5, 10, 20):
            if len(closes) >= n:
                ma = float(closes.iloc[-n:].mean())
                if last > ma:
                    ma_parts.append(n)
        ma_txt = f"站上{'/'.join(str(p) for p in ma_parts)}日线" if ma_parts else "跌破均线"
        win = closes.iloc[-20:] if len(closes) >= 20 else closes
        range_txt = ""
        if len(win) >= 2:
            if last >= float(win.max()):
                range_txt = "创近20日新高"
            elif last <= float(win.min()):
                range_txt = "近20日新低"
        return ma_txt + (f" · {range_txt}" if range_txt else "")
    except Exception:
        return None

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

    # 指数日K：成交额环比(prev_total) + 指数卡定性副标(均线定位+区间高低)
    index_daily: Dict[str, Any] = {}
    if data_date:
        try:
            ak = get_akshare()
            for _nm, _sym in (
                ("上证指数", "sh000001"),
                ("深证成指", "sz399001"),
                ("创业板指", "sz399006"),
                ("科创50", "sh000688"),
            ):
                try:
                    index_daily[_nm] = call_akshare_with_retry(f"{_nm}日K", ak.stock_zh_index_daily_em, symbol=_sym)
                except Exception:
                    index_daily[_nm] = None
        except Exception:
            index_daily = {}
        sh_df = index_daily.get("上证指数")
        sz_df = index_daily.get("深证成指")
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

    # 指数卡定性副标：均线定位(A)+区间高低(B)，缺失时渲染层显示『—』
    for _x in indices:
        _df = index_daily.get(_x.get("name"))
        _x["idx_note"] = _compute_index_note(_df, data_date) if _df is not None else None

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

def _pool_to_list(df) -> List[Dict[str, Any]]:
    """将涨停/跌停池 DataFrame 转换为 [{code, name, pct}] 列表（列名兼容中/英写法）。"""
    if df is None or len(df) == 0:
        return []
    cols = list(df.columns)
    out: List[Dict[str, Any]] = []

    def pick(row, *names):
        for n in names:
            if n in cols:
                return row.get(n)
        return None

    for _, row in df.iterrows():
        code = pick(row, "代码", "code")
        name = pick(row, "名称", "name")
        pct = to_float(pick(row, "涨跌幅", "pct"))
        if code is None:
            continue
        out.append({"code": str(code), "name": str(name) if name is not None else "", "pct": pct})
    return out

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
        "zt_list": [],
        "dt_list": [],
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
        out["zt_list"] = _pool_to_list(zt)
        out["dt_list"] = _pool_to_list(dt)
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

