#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fundflow_data_fetcher.py —— 仅负责「发起外部请求」
=================================================

⚠️ 硬性边界（违反即 bug，tests/test_layer_boundary.py 会拦截）：
  本文件【只】做三件事：
    1. 发起外部请求（AKShare / 东方财富 push2 / 腾讯 gtimg）；
    2. 把响应适配成可序列化结构（dict / list / DataFrame）；
    3. 写入 build/cache（经由 common/storage 层）。
  【绝不】在此做纯本地业务加工：聚合、涨跌家数推导、指数副标、
  涨停/跌停池转 list、北向占比、环比计算等 —— 这些一律放
  fundflow_processor.py。

写新函数前先问自己（判断标准）：
  - 这个函数最终会不会调到 http_get / em_get / call_akshare / get_akshare？
        → 会：属于 fetcher，留这里。
        → 不会（纯内存计算）：它是【处理函数】，必须放进 fundflow_processor.py。
  - 已迁出、若在本文件再出现同名即违规的函数：
        compute_index_note / pool_to_list / with_northbound_turnover_ratio /
        compute_us_market_breadth / derive_breadth_from_rows / compute_prev_total

历史教训（2026-09-09）：美股 fetch_us_market_breadth 与遗留的
_compute_index_note / _pool_to_list / _with_northbound_turnover_ratio 曾错误
落在 fetcher（规则只在文档、无机器校验所致）。现已迁入 processor 并加边界测试兜底。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
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
        from fundflow.fundflow_processor import compute_prev_total
        prev_total = compute_prev_total(index_daily.get("上证指数"), index_daily.get("深证成指"), data_date)

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
    from fundflow.fundflow_processor import compute_index_note
    for _x in indices:
        _df = index_daily.get(_x.get("name"))
        _x["idx_note"] = compute_index_note(_df, data_date) if _df is not None else None

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

def load_or_fetch_northbound(data_date: str, sh_amount: Optional[float], sz_amount: Optional[float]) -> Dict[str, Any]:
    payload = _load_or_fetch_build(_build_filename("fundflow_northbound", data_date), lambda: _fetch_northbound_payload(sh_amount, sz_amount))
    from fundflow.fundflow_processor import with_northbound_turnover_ratio
    return with_northbound_turnover_ratio(payload, sh_amount, sz_amount)

def fetch_market_breadth(data_date: str, stock_rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """抓取全市场个股涨跌家数 + 涨停/跌停数量（AKShare 东方财富源）。

    口径：收盘快照；剔除北交所（代码 8 开头 / 920 开头）以对齐沪深A股广度惯例。
    单源失败不影响整体，缺失字段置 None，由渲染层显示「—」。

    兜底：若 AKShare 全市场快照（stock_zh_a_spot_em，底层走 82.push2.eastmoney.com）
    在当前环境被代理拦截取不到，则复用已抓取的全市场个股资金流快照（stock_rows，
    走 push2delay.eastmoney.com，沙箱可用）按涨跌幅推导涨跌家数，确保收盘广度不空缺。
    """
    from fundflow.fundflow_processor import pool_to_list
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
        out["zt_list"] = pool_to_list(zt)
        out["dt_list"] = pool_to_list(dt)
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
        from fundflow.fundflow_processor import derive_breadth_from_rows
        adv, dec, fl = derive_breadth_from_rows(stock_rows)
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
        from fundflow.fundflow_processor import derive_breadth_from_rows
        full = _fetch_hk_full_quote()
        if full:
            adv, dec, fl = derive_breadth_from_rows(full, exclude_prefixes=())
            if adv or dec or fl:
                out["advance"] = adv
                out["decline"] = dec
                out["flat"] = fl
                out["source"] = out["source"] or "东方财富全市场港股行情(涨跌幅推导)"
                warnings.append("港股全市场涨跌家数：stock_hk_spot_em 不可用，已用全市场港股正股行情快照涨跌幅推导（全量约 2600 只）。")
        elif stock_rows:
            adv, dec, fl = derive_breadth_from_rows(stock_rows, exclude_prefixes=())
            if adv or dec or fl:
                out["advance"] = adv
                out["decline"] = dec
                out["flat"] = fl
                out["sample_based"] = True
                out["source"] = out["source"] or "东方财富港股个股资金流(样本内涨跌幅推导)"
                warnings.append("港股全市场涨跌家数：stock_hk_spot_em 与全量行情均不可用，已用个股资金流快照涨跌幅推导（样本内约 200+ 只覆盖）。")

    out["available"] = any(v is not None for v in (out["advance"], out["total_turnover"]))
    return out


# ════════════════════════════════════════════════════════════════════════════
# 美股资金流抓取（镜像 A 股 / 港股，数据展示模块一一对应）
#  - 主要指数        → 腾讯 gtimg（usINX 标普500 / usIXIC 纳斯达克 / usDJI 道琼斯 / usVIX 恐慌指数）
#  - 个股主力净流入  → 东方财富 push2delay clist（fs=m:105+t:1，全美股排行，约 3500+ 只）
#  - 美股 GICS 行业  → 复用 common/cache/us_gics_map.json 静态分类（镜像港股 HK_BASE_DATA 思路），由全美股资金流聚合
#  - 全球资金面      → 腾讯 gtimg（usVIX 恐慌指数 / usCL WTI 原油；其余宏观序列 gtimg 无则优雅降级）
#
# 注意：东方财富美股 clist 在 fltt=2 下 f3 已是「真实涨跌幅百分数」（如 6.1 = +6.1%），
#       与港股代码里 f3/100 的处理不同；美股直接采用 f3，不再除 100。
# ════════════════════════════════════════════════════════════════════════════
SOURCE_GT_US = "腾讯财经 gtimg 接口（美股）"
SOURCE_EM_US = "东方财富 East Money 公开行情接口（美股 m:105+t:1,m:106+t:1）"
# m:105+t:1 ≈ NASDAQ 类（约 3500 只），m:106+t:1 ≈ NYSE（约 1700 只），合并后约 5300 只普通股。
# ETF / 非股票品种 f100='-'，解析层额外过滤兜底。
EM_US_FS = "m:105+t:1,m:106+t:1"
EM_US_HEADERS = EM_HK_HEADERS  # 与港股同款 EastMoney 头
EM_US_CLIST_UT = "bd1d9ddb04089700cf9c27f6f7426281"  # 与港股 clist 同款 ut（已验证可用）
GTIMG_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}  # 与港股 gtimg 同款头

# 美股主要指数（gtimg 符号 → 展示名）。以 gtimg 返回的 code 字段（如 ".INX"）做匹配，避免中文名漂移。
US_INDICES = [
    ("标普500", ".INX", "usINX"),
    ("纳斯达克指数", ".IXIC", "usIXIC"),
    ("道琼斯指数", ".DJI", "usDJI"),
    ("恐慌指数VIX", ".VIX", "usVIX"),
]

# 全球资金面 / 外部流动性（美股北向的等价模块）。可解析的展示，不可解析的优雅降级为「—」。
US_MACRO = [
    ("恐慌指数VIX", "usVIX"),
    ("WTI原油", "usOIL"),   # usOIL = iPath 标普高盛原油 ETN，跟踪 WTI 原油
    ("现货黄金", "usGLD"),   # usGLD = SPDR 黄金 ETF，跟踪现货黄金
    ("美元指数", "usUUP"),   # usUUP = Invesco 美元指数 ETF（兑一篮子货币）
]

# 美股 GICS 行业静态映射表（镜像港股 HK_BASE_DATA 思路）。
# 数据来源：common/cache/us_gics_map.json（已入库、git 跟踪、零运行时网络依赖）。
# 该表是「行业主力净流入」面板聚合与展示的唯一数据源，按 sub_industry（二级行业）汇总。
# 东财美股接口未提供 二级行业字段，故以静态映射补齐；新增标的只需在 us_gics_map.json 追加一行，
# ulist 补全覆盖与二级行业聚合均直接读取本表（运行时不再依赖此处的内联常量）。
_US_GICS_MAP_CACHE: Optional[Dict[str, Any]] = None


def _load_us_gics_map() -> Dict[str, Any]:
    """读取 common/cache/us_gics_map.json（美股 curated 标的 GICS 一级/二级行业静态表）。

    文件随仓库入库，运行时无需联网；缺失时优雅降级为空白表（面板退化为东财一级行业 f100）。
    """
    global _US_GICS_MAP_CACHE
    if _US_GICS_MAP_CACHE is not None:
        return _US_GICS_MAP_CACHE
    data = load_cache_json("us_gics_map.json")
    if not isinstance(data, dict) or not data.get("stocks"):
        _US_GICS_MAP_CACHE = {"stocks": []}
        return _US_GICS_MAP_CACHE
    _US_GICS_MAP_CACHE = data
    return _US_GICS_MAP_CACHE


def _us_universe_codes() -> List[str]:
    return [str(s["code"]).upper() for s in _load_us_gics_map().get("stocks", [])]


def _us_code_to_sector() -> Dict[str, Dict[str, str]]:
    mapping: Dict[str, Dict[str, str]] = {}
    for s in _load_us_gics_map().get("stocks", []):
        code = str(s["code"]).upper()
        mapping[code] = {
            "sector": s.get("sector", ""),
            "sub_industry": s.get("sub_industry", ""),
            "zh": s.get("zh", ""),
        }
    return mapping


def _us_sector_order() -> List[str]:
    seen: List[str] = []
    for s in _load_us_gics_map().get("stocks", []):
        sec = s.get("sector", "")
        if sec and sec not in seen:
            seen.append(sec)
    return seen


def _us_sub_industry_order() -> List[str]:
    """按 us_gics_map.json 出现顺序排列的二级行业列表（用于稳定展示顺序，渲染层会再按资金流重排）。"""
    seen: List[str] = []
    for s in _load_us_gics_map().get("stocks", []):
        sub = s.get("sub_industry", "")
        if sub and sub not in seen:
            seen.append(sub)
    return seen


def _fetch_us_index_snapshot_payload() -> Dict[str, Any]:
    want = {gt: disp for disp, code, gt in US_INDICES}
    codes = ",".join(gt for _, code, gt in US_INDICES)
    text = http_get(f"https://qt.gtimg.cn/q={codes}", GTIMG_HEADERS, timeout=15, retries=3)
    indices: List[Dict[str, Any]] = []
    if text:
        for segment in text.split(";"):
            segment = segment.strip()
            if not segment.startswith("v_"):
                continue
            sym = segment.split("=")[0][2:]  # v_usINX -> usINX
            disp = want.get(sym)
            if not disp:
                continue
            inner = segment.split('"')[1] if '"' in segment else ""
            parts = inner.split("~")
            if len(parts) < 33:
                continue
            indices.append(
                {
                    "name": disp,
                    "code": sym,
                    "close": to_float(parts[3]),
                    "pct": to_float(parts[32]),
                    "chg": to_float(parts[31]),
                    "main_net_in": None,
                    "turnover": None,
                    "source": SOURCE_GT_US,
                }
            )
    return {"indices": indices, "source": SOURCE_GT_US}


def load_or_fetch_us_index_snapshot(data_date: str) -> Dict[str, Any]:
    return _load_or_fetch_build(_build_filename("fundflow_us_index", data_date), _fetch_us_index_snapshot_payload)


def _fetch_us_curated_via_ulist() -> Dict[str, Dict[str, Any]]:
    """直拉 72 只静态标的（保证 GICS 二级行业面板 100% 命中，不受 clist 限流丢页影响）。

    EastMoney 美股 secid 按交易所前缀区分：NASDAQ=105. / NYSE=106.。
    72 只 < 单批上限 80，故两个前缀各一批（共 2 次请求）即可全覆盖。
    clist 全量扫描在沙箱 IP 下常被限流丢页，ulist 单次批量请求稳定，作为补全覆盖来源。
    """
    codes = _us_universe_codes()
    sector_map = _us_code_to_sector()
    out: Dict[str, Dict[str, Any]] = {}
    for prefix in ("105.", "106."):
        secids = [f"{prefix}{c}" for c in codes]
        payload = em_get_direct(
            FUND_FLOW_BATCH_HOST, "/api/qt/ulist.np/get",
            {"fields": "f12,f14,f2,f3,f62,f100", "secids": ",".join(secids),
             "fltt": "2", "invt": "2", "np": "1"},
            timeout=20, retries=3,
        )
        if not payload:
            continue
        data = payload.get("data") or {}
        diff = data.get("diff") or {}
        rows = list(diff.values()) if isinstance(diff, dict) else diff
        for row in rows:
            code = str(row.get("f12") or "").strip().upper()
            if not code:
                continue
            f100 = str(row.get("f100") or "").strip()
            meta = sector_map.get(code, {})
            out[code] = {
                "code": code,
                "name": row.get("f14") or meta.get("zh"),
                "pct": to_float(row.get("f3")),
                "main_net_in": to_float(row.get("f62")),
                "sector": f100 if f100 and f100 != "-" else meta.get("sector", ""),
            }
    return out


def _fetch_us_stock_fundflow_full() -> Tuple[List[Dict[str, Any]], str, int]:
    """东方财富全美股资金流排行（fs=m:105+t:1,m:106+t:1，按主力净流入 f62 排序）。

    服务端 pz 单页硬卡 100，故翻页拉全量（约 5300 只 NYSE + NASDAQ 普通股），用于：
      - 个股资金流 TOP 排行（按 f62 取头尾）
      - 全市场涨跌家数（breadth，按 f3 推导）
      - GICS 二级行业聚合（按 us_gics_map.json 静态 sub_industry 映射过滤后聚合）
    f3 在 fltt=2 下已是真实涨跌幅百分数（如 6.1 = +6.1%），直接采用，不再除 100。
    f100 为东财自带 GICS 一级行业字段；f100='-' 的为 ETF / 非股票品种，解析时过滤。
    """
    fields = "f12,f14,f2,f3,f62,f100"
    base = {
        "pz": "100", "np": "1", "fltt": "2", "invt": "2",
        "ut": EM_US_CLIST_UT, "fid": "f62",
        "fields": fields, "fs": EM_US_FS,
    }
    host = "https://push2delay.eastmoney.com"
    rows_by_code: Dict[str, Dict[str, Any]] = {}
    pn = 1
    total: Optional[int] = None
    total_pages: Optional[int] = None
    fail_retries = 0
    short_retries = 0
    max_retries = 4
    retry_sleep = 2.0
    while True:
        params = {**base, "pn": str(pn), "po": "1"}
        query = urllib.parse.urlencode(params)
        text = http_get(f"{host}/api/qt/clist/get?{query}", EM_US_HEADERS, timeout=20, retries=3)
        rows: List[Dict[str, Any]] = []
        ok = False
        if text:
            try:
                payload = json.loads(text)
                data = payload.get("data") or {}
                if total is None:
                    total_raw = data.get("total")
                    total = int(total_raw) if isinstance(total_raw, (int, float)) else None
                    if total is not None:
                        total_pages = max(1, (total + 99) // 100)
                diff = data.get("diff") or {}
                rows = list(diff.values()) if isinstance(diff, dict) else diff
                ok = bool(rows)
            except json.JSONDecodeError:
                ok = False
        if not ok:
            fail_retries += 1
            if fail_retries >= max_retries:
                if total_pages is not None and pn >= total_pages:
                    break
                # 持续失败：跳过本页继续（最多丢 ~100 只），避免丢失整条尾部
                pn += 1
                fail_retries = 0
                short_retries = 0
                if pn > 80:  # 安全阀
                    break
                time.sleep(retry_sleep)
                continue
            time.sleep(retry_sleep)
            continue
        # 限流导致的「半页」：非末页却少于 100 行 → 重试该页（不推进 pn）
        if total_pages is not None and pn < total_pages and len(rows) < 100:
            short_retries += 1
            if short_retries < max_retries:
                time.sleep(retry_sleep)
                continue
            short_retries = 0  # 重试仍半页：接受残缺数据，继续
        else:
            short_retries = 0
        fail_retries = 0
        for row in rows:
            code = str(row.get("f12") or "").strip().upper()
            if not code:
                continue
            # 过滤 ETF / 非股票品种（f100 为空或 '-'）
            f100 = str(row.get("f100") or "").strip()
            if not f100 or f100 == "-":
                continue
            pct_raw = to_float(row.get("f3"))
            rows_by_code[code] = {
                "code": code,
                "name": row.get("f14"),
                "pct": pct_raw,  # 真实涨跌幅百分数，不再除 100
                "main_net_in": to_float(row.get("f62")),
                "sector": f100,  # GICS 一级（东财自带），未在 curated 映射中时可用作兜底
            }
        # 终止判定：已抓满预期页数，或去重计数已达 total（东财 total 不含 ETF 时可直接命中）
        if total_pages is not None and pn >= total_pages:
            break
        if total is not None and len(rows_by_code) >= total:
            break
        pn += 1
        if pn > 80:  # 安全阀：m:105 约 6000+ 只，放宽到 80 页
            break
    rows = list(rows_by_code.values())
    if not rows:
        return [], "东方财富美股个股资金流接口暂不可用", 0
    # 补全覆盖：clist 限流丢页时，用 ulist 直拉 72 只静态标的，保证 GICS 二级面板 100% 命中
    curated = _fetch_us_curated_via_ulist()
    added = 0
    for code, c in curated.items():
        if code not in rows_by_code:
            rows_by_code[code] = c
            added += 1
    if added:
        print(f"[info] 美股 ulist 补全覆盖 {added} 只静态标的（clist 限流丢页补齐）", file=sys.stderr)
    rows = list(rows_by_code.values())
    coverage = (len(rows_by_code) / total) if total else None
    if coverage is not None and coverage < 0.9:
        print(f"[warn] 美股全量抓取覆盖偏低：{len(rows_by_code)}/{total}（{coverage:.0%}），可能存在限流丢页", file=sys.stderr)
    return rows, f"东方财富延迟行情主机全美股资金流（覆盖 {len(rows)} 只）", (total or len(rows))


def load_or_fetch_us_stock_fundflow(data_date: str, scope: str = "full") -> Tuple[List[Dict[str, Any]], str]:
    filename = f"stock_fundflow_us_today_full_{data_date}.json"
    cached = load_build_json(filename)
    if cached is not None:
        return list(cached.get("rows") or []), cached.get("source", "build/full")
    rows, src, _total = _fetch_us_stock_fundflow_full()
    if not rows:
        return [], src or "东方财富美股个股资金流接口暂不可用"
    save_build_json(filename, {"data_date": data_date, "scope": scope, "source": src, "rows": rows})
    return rows, src


def _fetch_us_global_liquidity_payload() -> Dict[str, Any]:
    """全球资金面 / 外部流动性（美股北向的等价模块）。

    腾讯 gtimg：usVIX（恐慌指数）、usCL（WTI 原油）可解析；usDXY / usTNX / usXAU 在 gtimg 无对应，
    解析不到则优雅降级（不出现在结果中，渲染层显示「—」）。
    """
    want = {gt: disp for disp, gt in US_MACRO}
    codes = ",".join(gt for _, gt in US_MACRO)
    text = http_get(f"https://qt.gtimg.cn/q={codes}", GTIMG_HEADERS, timeout=15, retries=2)
    items: List[Dict[str, Any]] = []
    if text:
        for segment in text.split(";"):
            segment = segment.strip()
            if not segment.startswith("v_"):
                continue
            sym = segment.split("=")[0][2:]  # v_usVIX -> usVIX
            disp = want.get(sym)
            if not disp:
                continue
            inner = segment.split('"')[1] if '"' in segment else ""
            parts = inner.split("~")
            if len(parts) < 33:
                continue
            price = to_float(parts[3])
            pct = to_float(parts[32])
            if price is None and pct is None:
                continue
            items.append({"name": disp, "code": sym, "price": price, "pct": pct})
    return {"items": items, "source": SOURCE_GT_US}


def load_or_fetch_us_global_liquidity(data_date: str) -> Dict[str, Any]:
    return _load_or_fetch_build(_build_filename("fundflow_us_global", data_date), _fetch_us_global_liquidity_payload)



