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
from common.market_data import em_get_direct
from common.market_data import FUND_FLOW_BATCH_HOST
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
from stocktrend.stocktrend_static_data import HK_BASE_DATA

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

def fetch_market_breadth(data_date: str, stock_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """抓取全市场个股涨跌家数 + 涨停/跌停数量（AKShare 东方财富源）。

    口径：收盘快照；剔除北交所（代码 8 开头 / 920 开头）以对齐沪深A股广度惯例。
    单源失败不影响整体，缺失字段置 None，由渲染层显示「—」。

    兜底：若 AKShare 全市场快照（stock_zh_a_spot_em，底层走 82.push2.eastmoney.com）
    在当前环境被代理拦截取不到，则复用已抓取的全市场个股资金流快照（stock_rows，
    走 push2delay.eastmoney.com，沙箱可用）按涨跌幅推导涨跌家数，确保收盘广度不空缺。
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

    # 3) 兜底：AKShare 全市场快照不可用（如沙箱代理拦截 82.push2）时，
    #    复用已抓取的全市场个股资金流快照（stock_rows，走 push2delay，沙箱可用）按涨跌幅推导。
    if out["advance"] is None and stock_rows:
        adv = dec = fl = 0
        for r in stock_rows:
            code = str(r.get("code") or "").zfill(6)
            if code.startswith(("8", "920")):  # 剔除北交所，与上方口径一致
                continue
            pct = to_float(r.get("pct"))
            if pct is None:
                continue
            if pct > 0:
                adv += 1
            elif pct < 0:
                dec += 1
            else:
                fl += 1
        if adv or dec or fl:
            out["advance"] = adv
            out["decline"] = dec
            out["flat"] = fl
            out["source"] = out["source"] or "东方财富全市场个股资金流(涨跌幅推导)"
            warnings.append("全市场涨跌家数：stock_zh_a_spot_em 不可用，已用全市场个股资金流快照涨跌幅推导。")

    out["available"] = any(v is not None for v in (out["advance"], out["limit_up"]))
    return out


# ════════════════════════════════════════════════════════════════════════════
# 港股资金流抓取（镜像 A 股，数据展示模块一一对应）
#  - 主要指数        → 腾讯 gtimg（hkHSI / hkHSTECH / hkHSCEI / hkHSCCI）
#  - 个股主力净流入  → 东方财富 push2 116.xxxxx + f62（全港股排行）
#  - 南向（港股通）  → 东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY（003/004/006）
#  - 全市场涨跌家数  → AKShare stock_hk_spot_em
#  - 港股行业分类    → 复用 stocktrend HK_BASE_DATA
# ════════════════════════════════════════════════════════════════════════════
HK_INDICES = [
    ("恒生指数", "hkHSI"),
    ("恒生科技指数", "hkHSTECH"),
    ("国企指数", "hkHSCEI"),
    ("红筹指数", "hkHSCCI"),
]
SOURCE_GT_HK = "腾讯财经 gtimg 接口（港股）"
SOURCE_EM_HK = "东方财富 East Money 公开行情接口（港股 116.xxxxx）"
SOURCE_AK_HK = "AKShare 港股行情（stock_hk_spot_em）"
SOURCE_DC_HK = "东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY（港股通成交额/净买入）"
EM_HK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}


def hk_secid(code: str) -> str:
    """港股在东方财富的 secid 格式：116.<5位代码>。"""
    return f"116.{str(code).zfill(5)}"


def _hk_universe_codes() -> List[str]:
    return [str(s["code"]).zfill(5) for s in HK_BASE_DATA.get("stocks", [])]


def _iter_chunks(items: List[str], size: int) -> List[List[str]]:
    return [items[i:i + size] for i in range(0, len(items), size or 1)]


def _fetch_hk_index_snapshot_payload() -> Dict[str, Any]:
    want_by_name = {name: gt for name, gt in HK_INDICES}
    codes = ",".join(gt for _, gt in HK_INDICES)
    text = http_get(f"https://qt.gtimg.cn/q={codes}", headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}, timeout=15, retries=3)
    indices: List[Dict[str, Any]] = []
    source = SOURCE_GT_HK
    if text:
        for segment in text.split(";"):
            segment = segment.strip()
            if not segment.startswith("v_"):
                continue
            parts = segment.split("~")
            if len(parts) < 33:
                continue
            name = parts[1]
            gt = want_by_name.get(name)
            if not gt:
                continue
            indices.append(
                {
                    "name": name,
                    "code": gt,
                    "close": to_float(parts[3]),
                    "pct": to_float(parts[32]),
                    "chg": to_float(parts[31]),
                    "main_net_in": None,
                    "turnover": None,
                    "source": SOURCE_GT_HK,
                }
            )
    return {"indices": indices, "source": source}


def load_or_fetch_hk_index_snapshot(data_date: str) -> Dict[str, Any]:
    return _load_or_fetch_build(_build_filename("fundflow_hk_index", data_date), _fetch_hk_index_snapshot_payload)


EM_HK_FUND_FLOW_FS = "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2"


def _fetch_hk_stock_fundflow_rank_em() -> Tuple[List[Dict[str, Any]], str]:
    """东方财富全港股资金流排行（按主力净流入 f62 排序）。

    东方财富 clist 接口服务端硬卡 pz=100/页（实测 pz=200/500/1000 均只返 100），
    故分别取「净流入 TOP100」（po=1）与「净流出 TOP100」（po=0）两页合并去重。
    该结果为「资金流绝对值最大」的约 200 只，用于个股资金流排行表；行业面板的全覆盖
    另由 `load_or_fetch_hk_stock_fundflow` 合并 ulist 按代码批量结果保证。
    """
    fields = "f12,f14,f2,f3,f62"
    base = {
        "pz": "100", "np": "1", "fltt": "2", "invt": "2",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fid": "f62",
        "fields": fields, "fs": EM_HK_FUND_FLOW_FS,
    }
    host = "https://push2delay.eastmoney.com"
    rows_by_code: Dict[str, Dict[str, Any]] = {}
    for po in ("1", "0"):
        params = {**base, "pn": "1", "po": po}
        query = urllib.parse.urlencode(params)
        text = http_get(f"{host}/api/qt/clist/get?{query}", EM_HK_HEADERS, timeout=20, retries=3)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        for row in diff_list((payload.get("data") or {})):
            code = str(row.get("f12") or "").zfill(5)
            if not code or code in rows_by_code:
                continue
            pct_raw = to_float(row.get("f3"))
            rows_by_code[code] = {
                "code": code,
                "name": row.get("f14"),
                "pct": pct_raw / 100 if pct_raw is not None else None,
                "main_net_in": to_float(row.get("f62")),
            }
    rows = list(rows_by_code.values())
    if not rows:
        return [], "东方财富延迟行情主机港股排行接口暂不可用"
    return rows, f"东方财富延迟行情主机全港股资金流排行（净流入/流出各 TOP100，覆盖 {len(rows)} 只）"


def _fetch_hk_stock_fundflow_payload() -> Tuple[List[Dict[str, Any]], str]:
    """回退路径：116.xxxxx 批量，仅覆盖静态标的池（HK_BASE_DATA）。"""
    codes = _hk_universe_codes()
    if not codes:
        return [], "港股静态标的池为空，无法抓取个股资金流"
    secids = [hk_secid(c) for c in codes]
    rows_by_code: Dict[str, Dict[str, Any]] = {}
    pending = list(secids)
    for batch in _iter_chunks(pending, 80):
        payload = em_get_direct(
            FUND_FLOW_BATCH_HOST,
            "/api/qt/ulist.np/get",
            {
                "fields": "f12,f14,f2,f3,f62",
                "secids": ",".join(batch),
                "fltt": "2",
                "invt": "2",
                "np": "1",
            },
            timeout=20,
            retries=3,
        )
        if not payload:
            continue
        for row in diff_list(payload.get("data") or {}):
            code = str(row.get("f12") or "").zfill(5)
            if not code:
                continue
            pct_raw = to_float(row.get("f3"))
            rows_by_code[code] = {
                "code": code,
                "name": row.get("f14"),
                "pct": pct_raw / 100 if pct_raw is not None else None,
                "main_net_in": to_float(row.get("f62")),
            }
    rows = [rows_by_code[c] for c in codes if c in rows_by_code]
    if not rows:
        return [], "东方财富延迟行情主机 116.xxxxx 批量接口暂不可用"
    return rows, f"东方财富延迟行情主机 116.xxxxx 批量资金流（覆盖 {len(rows)}/{len(codes)}）"


def load_or_fetch_hk_stock_fundflow(data_date: str, scope: str = "full") -> Tuple[List[Dict[str, Any]], str]:
    filename = f"stock_fundflow_hk_today_full_{data_date}.json"
    cached = load_build_json(filename)
    if cached is not None:
        return list(cached.get("rows") or []), cached.get("source", "build/full")
    # 注意：东方财富 clist 接口 pz 服务端硬卡 100/页，无法靠调大 pz 扩量；
    # 故采用「双路合并」：clist 全市场排行（看大单异动）+ ulist 按代码批量（保证 40 只代表股全覆盖）。
    rows_by_code: Dict[str, Dict[str, Any]] = {}
    sources: List[str] = []
    rank_rows, rank_src = _fetch_hk_stock_fundflow_rank_em()
    if rank_rows:
        for r in rank_rows:
            rows_by_code[r["code"]] = r  # clist 优先
        sources.append(rank_src)
    batch_rows, batch_src = _fetch_hk_stock_fundflow_payload()
    if batch_rows:
        for r in batch_rows:
            rows_by_code.setdefault(r["code"], r)  # ulist 补全 clist 未覆盖的代表股
        sources.append(batch_src)
    rows = list(rows_by_code.values())
    if not rows:
        return [], "东方财富港股个股资金流接口暂不可用"
    source = "；".join(sources) if sources else "东方财富港股个股资金流"
    save_build_json(filename, {"data_date": data_date, "scope": scope, "source": source, "rows": rows})
    return rows, source


def _fetch_southbound_payload(hk_total_turnover: Optional[float] = None) -> Dict[str, Any]:
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
    result = {
        "trade_date": None,
        "sh_connect_turnover": None,
        "sz_connect_turnover": None,
        "total_turnover": None,
        "net_buy": None,
        "turnover_ratio": None,
        "available": False,
        "source": SOURCE_DC_HK,
        "note": "南向（港股通）净买入公开披露，与北向不同；港股通(沪)/(深)为分渠道披露值，合计以「南向合计」为准。",
    }
    if not text:
        result["source"] = "东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY 接口暂不可用"
        return result
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return result
    rows = (payload.get("result") or {}).get("data") or []
    days = sorted({str(r.get("TRADE_DATE", ""))[:10] for r in rows}, reverse=True)
    if not days:
        return result
    day = days[0]
    by_type: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        if str(r.get("TRADE_DATE", ""))[:10] == day:
            by_type[str(r.get("MUTUAL_TYPE"))] = r

    def amt(mutual_type: str) -> Optional[float]:
        value = by_type.get(mutual_type, {}).get("DEAL_AMT")
        return value * 1e6 if value is not None else None  # DEAL_AMT 单位为百万元

    sh_turnover = amt("003")
    sz_turnover = amt("004")
    total_turnover = amt("006")
    net_raw = by_type.get("006", {}).get("NET_DEAL_AMT")
    net_buy = net_raw * 1e6 if net_raw is not None else None

    result["trade_date"] = day
    result["sh_connect_turnover"] = sh_turnover
    result["sz_connect_turnover"] = sz_turnover
    result["total_turnover"] = total_turnover
    result["net_buy"] = net_buy
    if total_turnover and hk_total_turnover:
        result["turnover_ratio"] = total_turnover / hk_total_turnover
    result["available"] = total_turnover is not None
    return result


def load_or_fetch_southbound(data_date: str, hk_total_turnover: Optional[float] = None) -> Dict[str, Any]:
    return _load_or_fetch_build(_build_filename("fundflow_hk_southbound", data_date), lambda: _fetch_southbound_payload(hk_total_turnover))


def _fetch_hk_full_quote() -> List[Dict[str, Any]]:
    """翻页拉全港股正股行情（东财 clist，fs=m:128+t:3 即主板+创业板普通股，约 2600 只）。

    走 push2delay.eastmoney.com，沙箱可用；仅取 f12 代码 / f14 名称 / f3 涨跌幅，
    用于推导全市场涨跌家数（与 AKShare stock_hk_spot_em 等价，但绕开沙箱代理拦截）。
    单页 pz 服务端硬卡 100，故按代码升序翻页拉全量。
    """
    fs = "m:128+t:3"
    out: List[Dict[str, Any]] = []
    pn = 1
    total: Optional[int] = None
    while True:
        q = urllib.parse.urlencode(
            {"pz": "100", "pn": str(pn), "fltt": "2", "invt": "2",
             "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fid": "f12",
             "fields": "f12,f14,f3", "fs": fs, "po": "0"}
        )
        t = http_get(f"https://push2delay.eastmoney.com/api/qt/clist/get?{q}", EM_HK_HEADERS, timeout=20, retries=2)
        if not t:
            break
        try:
            d = (json.loads(t) or {}).get("data") or {}
        except Exception:  # noqa: BLE001
            break
        if total is None:
            total = d.get("total")
        diff = d.get("diff") or {}
        if not diff:
            break
        for v in diff.values():
            pct = to_float(v.get("f3"))
            if pct is None:
                continue
            out.append({"code": str(v.get("f12") or ""), "name": v.get("f14"), "pct": pct})
        if total is not None and len(out) >= total:
            break
        pn += 1
        if pn > 60:  # 安全阀：最多 60 页（6000 只）
            break
    return out


def fetch_hk_market_breadth(data_date: str, stock_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """抓取港股全市场个股涨跌家数 + 总成交额（AKShare 港股源）。

    口径：收盘快照；港股无涨跌停板，故 limit_up/limit_down 恒为 None。
    单源失败不影响整体，缺失字段置 None，由渲染层显示「—」。

    兜底：AKShare 港股行情（stock_hk_spot_em，底层 82.push2.eastmoney.com）在沙箱/
    受限网络常被代理拦截，此时改用已抓取的全市场个股资金流快照（走 push2delay，
    沙箱可用）按涨跌幅 pct 推导涨跌家数。总成交额字段 AKShare 独家提供，兜底不补。
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
        "total_turnover": None,
        "source": "",
        "warnings": warnings,
    }
    yyyymmdd = str(data_date).replace("-", "")
    try:
        df = call_akshare_with_retry("港股全市场行情", ak.stock_hk_spot_em)
        if df is not None and len(df) > 0:
            pct = df["涨跌幅"].astype(float, errors="coerce")
            out["advance"] = int((pct > 0).sum())
            out["decline"] = int((pct < 0).sum())
            out["flat"] = int(((pct == 0) & df["成交量"].notna()).sum())
            if "成交额" in df.columns:
                out["total_turnover"] = float(df["成交额"].astype(float, errors="coerce").sum())
            out["source"] = SOURCE_AK_HK
    except Exception as e:  # noqa: BLE001
        warnings.append(f"港股全市场行情获取失败: {e}")

    # 兜底：AKShare 港股行情（stock_hk_spot_em，底层 82.push2）在沙箱/受限网络被代理拦截时，
    # 优先用全市场正股行情快照（翻页拉 t:3 全量，约 2600 只，走 push2delay）推涨跌家数；
    # 若全量也失败，退回已抓的个股资金流快照子集（样本内，约 213 只）。
    if out["advance"] is None:
        full = _fetch_hk_full_quote()
        if full:
            adv = dec = fl = 0
            for r in full:
                pct = to_float(r.get("pct"))
                if pct is None:
                    continue
                if pct > 0:
                    adv += 1
                elif pct < 0:
                    dec += 1
                else:
                    fl += 1
            if adv or dec or fl:
                out["advance"] = adv
                out["decline"] = dec
                out["flat"] = fl
                out["source"] = out["source"] or "东方财富全市场港股行情(涨跌幅推导)"
                warnings.append("港股全市场涨跌家数：stock_hk_spot_em 不可用，已用全市场港股正股行情快照涨跌幅推导（全量约 2600 只）。")
        elif stock_rows:
            adv = dec = fl = 0
            for r in stock_rows:
                pct = to_float(r.get("pct"))
                if pct is None:
                    continue
                if pct > 0:
                    adv += 1
                elif pct < 0:
                    dec += 1
                else:
                    fl += 1
            if adv or dec or fl:
                out["advance"] = adv
                out["decline"] = dec
                out["flat"] = fl
                out["sample_based"] = True
                out["source"] = out["source"] or "东方财富港股个股资金流(样本内涨跌幅推导)"
                warnings.append("港股全市场涨跌家数：stock_hk_spot_em 与全量行情均不可用，已用个股资金流快照涨跌幅推导（样本内约 200+ 只覆盖）。")

    out["available"] = any(v is not None for v in (out["advance"], out["total_turnover"]))
    return out

