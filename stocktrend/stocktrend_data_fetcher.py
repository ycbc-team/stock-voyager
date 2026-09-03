#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stocktrend 数据收集脚本
=======================

职责：
  1. 抓取 A 股与港股核心股票的最新数据
  2. 优先复用 build/ 中已存在的共享请求产物
  3. 生成两个 JSON 中间产物，供 UI 渲染脚本输出页面
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import urllib.parse
from typing import Any, Callable, Dict, List, Optional


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


from common.market_data import EM_HEADERS
from common.market_data import call_akshare_with_retry
from common.market_data import detect_trade_date
from common.market_data import get_akshare
from common.market_data import http_get
from common.market_data import load_or_fetch_stock_fundflow_build
from common.storage import default_data_dir
from common.storage import load_build_json
from common.storage import save_build_json
from common.storage import save_data_json
from common.storage import write_json
from stocktrend.stocktrend_static_data import HK_BASE_DATA


_AKSHARE_CLIENT: Optional[Any] = None


def _get_akshare_client() -> Any:
    global _AKSHARE_CLIENT
    if _AKSHARE_CLIENT is None:
        _AKSHARE_CLIENT = get_akshare()
    return _AKSHARE_CLIENT


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return float(value)
    text = str(value).strip()
    if not text or text in {"--", "-", "None", "nan"}:
        return None
    text = text.replace(",", "").replace("%", "").replace("倍", "").replace("元", "")
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _fmt_signed_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%"


def _fmt_yi(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value / 1e8:.2f}亿"


def _fmt_signed_yi(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value / 1e8:.2f}亿"


def _fmt_market_cap(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1e12:
        return f"{value / 1e12:.2f}万亿"
    return f"{value / 1e8:.2f}亿"


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _load_or_fetch_build(filename: str, loader: Callable[[], Any]) -> Any:
    cached = load_build_json(filename)
    if cached is not None:
        return cached
    payload = loader()
    save_build_json(filename, payload)
    return payload


def _http_json(url: str, params: Dict[str, Any], timeout: int = 20, retries: int = 4) -> Optional[Dict[str, Any]]:
    query = urllib.parse.urlencode(params)
    text = http_get(f"{url}?{query}", EM_HEADERS, timeout=timeout, retries=retries)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _safe_ak_call(label: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return call_akshare_with_retry(label, fn, *args, **kwargs)
    except Exception as exc:
        print(f"[!] {label} 失败：{exc}")
        return None


def _load_hk_base_data() -> Dict[str, Any]:
    return HK_BASE_DATA


A_SHARE_SECTORS = [
    {"key": "cycle", "title": "大周期板块", "label": "周期", "color": "#ff8c42"},
    {"key": "tech", "title": "大科技板块", "label": "科技", "color": "#3fb950"},
    {"key": "consumer", "title": "大消费板块", "label": "消费", "color": "#f0c040"},
    {"key": "finance", "title": "大金融与公用事业板块", "label": "金融公用", "color": "#58a6ff"},
]


A_SHARE_COMBOS = [
    {"cls": "combo-stable", "title": "稳健红利组合", "codes": ["600941", "600900", "601088", "600036", "601318"], "desc": "偏向现金流与分红能力，适合把握 A 股核心资产中的稳健底仓。"},
    {"cls": "combo-growth", "title": "核心消费组合", "codes": ["600519", "600887", "000333", "603605", "000538"], "desc": "聚焦品牌壁垒与消费龙头，适合中长期跟踪景气与估值切换。"},
    {"cls": "combo-aggressive", "title": "景气制造组合", "codes": ["300750", "002594", "002415", "600150", "601899"], "desc": "弹性更强，受行业景气与周期波动影响更大，适合分批布局。"},
]


def _a_stock(code: str, zh: str, sector: str, l1: str, l2: str, l2_code: str, border: str) -> Dict[str, Any]:
    return {"code": code, "zh": zh, "en": zh, "sector": sector, "l1": l1, "l2": l2, "l2_code": l2_code, "border": border}


# 分组与顺序严格对齐外部链接「一级行业个股走势分析」(bj8 部署版)
# 大周期 / 大科技 / 大消费 / 大金融与公用事业
A_SHARE_STOCKS = [
    # —— 大周期板块（8个行业）——
    _a_stock("601088", "中国神华", "cycle", "资源公用", "煤炭", "6010", "red"),
    _a_stock("600938", "中国海油", "cycle", "资源公用", "石油天然气", "6020", "red"),
    _a_stock("600309", "万华化学", "cycle", "资源公用", "化工材料", "6030", "orange"),
    _a_stock("000708", "中信特钢", "cycle", "制造升级", "钢铁材料", "3020", "brown"),
    _a_stock("601899", "紫金矿业", "cycle", "资源公用", "有色金属", "6040", "orange"),
    _a_stock("300750", "宁德时代", "cycle", "制造升级", "动力电池", "3030", "green"),
    _a_stock("600585", "海螺水泥", "cycle", "资源公用", "建材", "6050", "gray"),
    _a_stock("601668", "中国建筑", "cycle", "基建建筑", "建筑央企", "5010", "blue"),
    # —— 大科技板块（8个行业）——
    _a_stock("002415", "海康威视", "tech", "科技成长", "安防设备", "4010", "green"),
    _a_stock("002594", "比亚迪", "tech", "制造升级", "新能源汽车", "3040", "purple"),
    _a_stock("300033", "同花顺", "tech", "科技成长", "金融 IT", "4020", "blue"),
    _a_stock("600941", "中国移动", "tech", "通信运营", "运营商", "5020", "blue"),
    _a_stock("002027", "分众传媒", "tech", "消费龙头", "广告传媒", "1080", "gray"),
    _a_stock("600760", "中航沈飞", "tech", "制造升级", "军工装备", "3050", "red"),
    _a_stock("600031", "三一重工", "tech", "制造升级", "工程机械", "3060", "orange"),
    _a_stock("600150", "中国船舶", "tech", "制造升级", "船舶制造", "3070", "red"),
    # —— 大消费板块（10个行业）——
    _a_stock("600519", "贵州茅台", "consumer", "消费龙头", "白酒", "1010", "yellow"),
    _a_stock("600887", "伊利股份", "consumer", "消费龙头", "乳制品", "1020", "green"),
    _a_stock("600276", "恒瑞医药", "consumer", "医药健康", "创新药", "2010", "blue"),
    _a_stock("000333", "美的集团", "consumer", "家电消费", "白电", "3010", "orange"),
    _a_stock("600398", "海澜之家", "consumer", "消费龙头", "服饰零售", "1030", "brown"),
    _a_stock("603195", "公牛集团", "consumer", "消费龙头", "家居消费", "1040", "yellow"),
    _a_stock("601888", "中国中免", "consumer", "消费龙头", "免税零售", "1050", "orange"),
    _a_stock("600754", "锦江酒店", "consumer", "消费龙头", "酒店旅游", "1060", "gray"),
    _a_stock("603605", "珀莱雅", "consumer", "消费龙头", "美妆护理", "1070", "purple"),
    _a_stock("000538", "云南白药", "consumer", "医药健康", "中药", "2020", "yellow"),
    # —— 大金融与公用事业板块（7个行业）——
    _a_stock("600036", "招商银行", "finance", "金融地产", "银行", "5030", "blue"),
    _a_stock("601318", "中国平安", "finance", "金融地产", "保险", "5040", "purple"),
    _a_stock("600048", "保利发展", "finance", "金融地产", "房地产", "5050", "brown"),
    _a_stock("600900", "长江电力", "finance", "资源公用", "水电", "6060", "green"),
    _a_stock("603568", "伟明环保", "finance", "资源公用", "环保服务", "6070", "green"),
    _a_stock("601816", "京沪高铁", "finance", "交通运输", "铁路运输", "5060", "gray"),
]


SECTOR_RISK_TEXT = {
    "cycle": ["商品价格中枢波动", "政策与供给节奏变化", "周期股高位回撤速度较快"],
    "tech": ["技术迭代快、竞争格局变化快", "高估值阶段波动更大", "机构持仓拥挤时回撤更明显"],
    "consumer": ["消费需求恢复不及预期", "渠道或品牌竞争加剧", "高位估值阶段回撤放大"],
    "finance": ["宏观信用周期影响盈利", "政策与监管环境变化", "地产与利率周期传导估值波动"],
}


def _extract_report_year(value: Any) -> Optional[int]:
    if value is None:
        return None
    if hasattr(value, "year"):
        try:
            return int(value.year)
        except Exception:
            return None
    match = re.search(r"(\d{4})", str(value))
    return int(match.group(1)) if match else None


def _pick_latest_row_per_year(rows: List[Dict[str, Any]], year_key: str) -> Dict[int, Dict[str, Any]]:
    by_year: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        year = _extract_report_year(row.get(year_key))
        if year is None:
            continue
        if year not in by_year:
            by_year[year] = row
    return by_year


def _find_metric(row: Dict[str, Any], keywords: List[str]) -> Optional[float]:
    for key, value in row.items():
        normalized = str(key).replace("(", "（").replace(")", "）")
        if all(word in normalized for word in keywords):
            parsed = _to_float(value)
            if parsed is not None:
                return parsed
    return None


def _extract_year_from_row(row: Dict[str, Any], candidate_keys: List[str]) -> Optional[int]:
    for key in candidate_keys:
        year = _extract_report_year(row.get(key))
        if year is not None:
            return year
    for value in row.values():
        year = _extract_report_year(value)
        if year is not None:
            return year
    return None


def _find_metric_by_any_keywords(row: Dict[str, Any], keyword_groups: List[List[str]]) -> Optional[float]:
    for keywords in keyword_groups:
        value = _find_metric(row, keywords)
        if value is not None:
            return value
    return None


def _dedupe_texts(items: List[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _build_holding_warning(payload: Dict[str, Any], label: str) -> Optional[str]:
    summary = payload.get("summary") or {}
    requested = int(summary.get("requested") or 0)
    failed = int(summary.get("failed") or 0)
    success = int(summary.get("success") or 0)
    if requested <= 0 or failed <= 0:
        return None
    reasons = _dedupe_texts(payload.get("error_reasons") or [])
    reason_text = "；".join(reasons[:2])
    if len(reasons) > 2:
        reason_text += " 等"
    if failed >= requested:
        return f"{label}接口本次全部失败；失败原因：{reason_text or '公开接口返回异常'}。对应股票持股项显示“—”。"
    return f"{label}接口本次部分失败：成功 {success} / {requested}；失败原因：{reason_text or '公开接口返回异常'}。对应失败股票持股项显示“—”。"




def _build_result_payload(source: str, trade_date: str, issue: Optional[str] = None, **data: Any) -> Dict[str, Any]:
    payload = {"source": source, "as_of": trade_date}
    if issue:
        payload["issue"] = issue
    payload.update(data)
    return payload


def _build_aggregate_warning(payload: Dict[str, Any], label: str) -> Optional[str]:
    summary = payload.get("summary") or {}
    requested = int(summary.get("requested") or 0)
    failed = int(summary.get("failed") or 0)
    success = int(summary.get("success") or 0)
    if requested <= 0 or failed <= 0:
        return None
    reasons = _dedupe_texts(payload.get("error_reasons") or [])
    reason_text = "；".join(reasons[:2]) if reasons else "公开接口返回异常"
    if len(reasons) > 2:
        reason_text += " 等"
    return f"{label}存在异常：成功 {success} / {requested}；失败原因：{reason_text}。失败字段显示“—”。"


def _fetch_spot_rows_direct(codes: List[str], market: str) -> List[Dict[str, Any]]:
    secids = []
    for code in codes:
        secids.append(f"{'1' if code.startswith('6') else '0'}.{code}" if market == "ashare" else f"116.{code}")
    payload = _http_json(
        "https://push2delay.eastmoney.com/api/qt/ulist.np/get",
        {
            "fields": "f12,f14,f2,f3,f4,f5,f6,f7,f8,f9,f10,f15,f16,f17,f18,f20,f21,f23,f24,f25",
            "secids": ",".join(secids),
            "fltt": "2",
            "invt": "2",
            "np": "1",
        },
    )
    rows = []
    for row in ((payload or {}).get("data") or {}).get("diff") or []:
        code = str(row.get("f12") or "").zfill(6 if market == "ashare" else 5)
        rows.append(
            {
                "代码": code,
                "名称": row.get("f14"),
                "最新价": _to_float(row.get("f2")),
                "涨跌幅": _to_float(row.get("f3")),
                "涨跌额": _to_float(row.get("f4")),
                "成交量": _to_float(row.get("f5")),
                "成交额": _to_float(row.get("f6")),
                "振幅": _to_float(row.get("f7")),
                "换手率": _to_float(row.get("f8")),
                "市盈率-动态": _to_float(row.get("f9")),
                "量比": _to_float(row.get("f10")),
                "最高": _to_float(row.get("f15")),
                "最低": _to_float(row.get("f16")),
                "今开": _to_float(row.get("f17")),
                "昨收": _to_float(row.get("f18")),
                "总市值": _to_float(row.get("f20")),
                "流通市值": _to_float(row.get("f21")),
                "市净率": _to_float(row.get("f23")),
                "60日涨跌幅": _to_float(row.get("f24")),
                "年初至今涨跌幅": _to_float(row.get("f25")),
            }
        )
    return rows


def _fetch_hist_rows_direct(market: str, code: str, start: str, end: str) -> List[Dict[str, Any]]:
    ak = _get_akshare_client()
    if market == "ashare":
        symbol = f"{'sh' if code.startswith('6') else 'sz'}{code}"
        df = _safe_ak_call(f"{code} A股历史行情", ak.stock_zh_a_daily, symbol=symbol)
    else:
        df = _safe_ak_call(f"{code} 港股历史行情", ak.stock_hk_daily, symbol=code)
    if df is None or df.empty:
        return []

    rows: List[Dict[str, Any]] = []
    start_date = dt.datetime.strptime(start, "%Y%m%d").date()
    end_date = dt.datetime.strptime(end, "%Y%m%d").date()
    for row in df.to_dict("records"):
        row_date = row.get("date")
        if not row_date or row_date < start_date or row_date > end_date:
            continue
        turnover = _to_float(row.get("turnover"))
        if turnover is not None and market == "ashare" and turnover <= 1:
            turnover = turnover * 100
        rows.append(
            {
                "日期": str(row_date),
                "开盘": _to_float(row.get("open")),
                "收盘": _to_float(row.get("close")),
                "最高": _to_float(row.get("high")),
                "最低": _to_float(row.get("low")),
                "成交量": _to_float(row.get("volume")),
                "成交额": _to_float(row.get("amount")),
                "振幅": None,
                "涨跌幅": None,
                "涨跌额": None,
                "换手率": turnover,
                "股票代码": code,
            }
        )
    for index in range(1, len(rows)):
        prev_close = rows[index - 1].get("收盘")
        current_close = rows[index].get("收盘")
        current_high = rows[index].get("最高")
        current_low = rows[index].get("最低")
        if prev_close not in (None, 0) and current_close is not None:
            rows[index]["涨跌额"] = current_close - prev_close
            rows[index]["涨跌幅"] = (current_close / prev_close - 1) * 100
            if current_high is not None and current_low is not None:
                rows[index]["振幅"] = (current_high - current_low) / prev_close * 100
    return rows


def _load_ashare_spot(trade_date: str) -> Dict[str, Dict[str, Any]]:
    filename = f"stocktrend_ashare_spot_{trade_date}.json"
    rows = _load_or_fetch_build(filename, lambda: _fetch_spot_rows_direct([item["code"] for item in A_SHARE_STOCKS], "ashare"))
    return {str(row.get("代码") or "").zfill(6): row for row in rows}


def _load_hk_spot(trade_date: str) -> Dict[str, Dict[str, Any]]:
    hk_codes = [str(item["code"]).zfill(5) for item in _load_hk_base_data()["stocks"]]
    filename = f"stocktrend_hk_spot_{trade_date}.json"
    rows = _load_or_fetch_build(filename, lambda: _fetch_spot_rows_direct(hk_codes, "hk"))
    return {str(row.get("代码") or "").zfill(5): row for row in rows}


def _fetch_hist_rows(market: str, code: str, trade_date: str) -> List[Dict[str, Any]]:
    codes = [item["code"] for item in A_SHARE_STOCKS] if market == "ashare" else [str(item["code"]).zfill(5) for item in _load_hk_base_data()["stocks"]]
    payload = _load_hist_cache(market, codes, trade_date)
    item = (payload.get("items") or {}).get(code) or {}
    return list(item.get("rows") or [])


def _compute_hist_stats(rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    if not rows:
        return {"w52l": None, "w52h": None, "pos": None, "chg5": None, "chg20": None, "chg60": None, "ytd": None}
    recent = rows[-252:] if len(rows) > 252 else rows
    lows = [_to_float(row.get("最低")) for row in recent]
    highs = [_to_float(row.get("最高")) for row in recent]
    closes = [_to_float(row.get("收盘")) for row in rows]
    dates = [str(row.get("日期") or "") for row in rows]
    current_close = closes[-1]
    w52l = min(value for value in lows if value is not None) if any(value is not None for value in lows) else None
    w52h = max(value for value in highs if value is not None) if any(value is not None for value in highs) else None
    pos = None
    if current_close is not None and w52l is not None and w52h is not None:
        pos = 50.0 if w52h == w52l else _clip((current_close - w52l) / (w52h - w52l) * 100.0, 0.0, 100.0)

    def period_return(days: int) -> Optional[float]:
        if len(closes) <= days:
            return None
        old = closes[-days - 1]
        if old in (None, 0):
            return None
        return (current_close / old - 1) * 100 if current_close is not None else None

    year_start_close = None
    if dates:
        year_text = str(dates[-1])[:4]
        for index, date_text in enumerate(dates):
            if date_text.startswith(year_text):
                year_start_close = closes[index]
                break
    ytd = None
    if current_close is not None and year_start_close not in (None, 0):
        ytd = (current_close / year_start_close - 1) * 100

    return {"w52l": w52l, "w52h": w52h, "pos": round(pos, 0) if pos is not None else None, "chg5": period_return(5), "chg20": period_return(20), "chg60": period_return(60), "ytd": ytd}


def _latest_hist_row(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return rows[-1] if rows else {}


def _prev_close_from_hist(rows: List[Dict[str, Any]]) -> Optional[float]:
    if len(rows) < 2:
        return None
    return _to_float(rows[-2].get("收盘"))


def _load_hist_cache(market: str, codes: List[str], trade_date: str) -> Dict[str, Any]:
    filename = f"stocktrend_hist_{market}_{trade_date}.json"
    cached = load_build_json(filename)
    if cached is not None:
        return cached

    start = (dt.datetime.strptime(trade_date, "%Y-%m-%d") - dt.timedelta(days=420)).strftime("%Y%m%d")
    end = trade_date.replace("-", "")
    items: Dict[str, Any] = {}
    summary = {"requested": len(codes), "success": 0, "failed": 0}
    error_reasons: List[str] = []
    source = "AKShare 历史行情"

    for code in codes:
        rows = _fetch_hist_rows_direct(market, code, start, end)
        issue = None if rows else "公开接口返回空数据"
        if issue:
            summary["failed"] += 1
            error_reasons.append(issue)
        else:
            summary["success"] += 1
        items[code] = _build_result_payload(source, trade_date, issue=issue, rows=rows)

    payload = {"items": items, "summary": summary, "error_reasons": _dedupe_texts(error_reasons), "source": source}
    save_build_json(filename, payload)
    return payload


def _load_aggregate_by_code(filename: str, codes: List[str], label: str, loader: Callable[[str], Dict[str, Any]], source: str, trade_date: str) -> Dict[str, Any]:
    cached = load_build_json(filename)
    if cached is not None:
        return cached

    items: Dict[str, Any] = {}
    summary = {"requested": len(codes), "success": 0, "failed": 0}
    error_reasons: List[str] = []
    for code in codes:
        payload = loader(code)
        payload.setdefault("source", source)
        payload.setdefault("as_of", trade_date)
        issue = payload.get("issue")
        if issue:
            summary["failed"] += 1
            error_reasons.append(str(issue))
        else:
            summary["success"] += 1
        items[code] = payload
    result = {"items": items, "summary": summary, "error_reasons": _dedupe_texts(error_reasons), "source": source}
    save_build_json(filename, result)
    return result


def _fetch_ashare_dividends(code: str, trade_date: str) -> Dict[str, Any]:
    def loader(stock_code: str) -> Dict[str, Any]:
        ak = _get_akshare_client()
        df = _safe_ak_call(f"{stock_code} A股分红", ak.stock_fhps_detail_em, symbol=stock_code)
        if df is None or df.empty:
            return _build_result_payload("东方财富 A股分红", trade_date, issue="公开接口返回空数据", div5=[], div_years=[], div_ttm_ps=None)
        rows = df.to_dict("records")
        rows_by_year: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            y = _extract_report_year(row.get("报告期")) or _extract_year_from_row(row, ["报告期"])
            if y is None:
                continue
            rows_by_year.setdefault(y, []).append(row)
        years = sorted(rows_by_year.keys())[-5:]
        divs: List[Optional[float]] = []
        for year in years:
            total = 0.0
            cnt = 0
            for row in rows_by_year[year]:
                cash_ratio = _to_float(row.get("现金分红-现金分红比例"))
                if cash_ratio is not None:
                    total += cash_ratio / 10.0
                    cnt += 1
            divs.append(round(total, 4) if cnt else None)
        # TTM 股息率：除权除息日在 [trade_date-365, trade_date] 的全部每股分红（含中期）之和
        from datetime import datetime as _dt, timedelta as _td
        try:
            _tdate = _dt.strptime(trade_date, "%Y-%m-%d").date()
        except Exception:
            _tdate = None
        _cutoff = (_tdate - _td(days=365)) if _tdate else None
        _ttm, _ttm_cnt = 0.0, 0
        _ttm_dates: List[str] = []
        for row in rows:
            _raw = str(row.get("除权除息日") or "")
            _cr = _to_float(row.get("现金分红-现金分红比例"))
            if not _raw or _cr is None:
                continue
            try:
                _d = _dt.strptime(_raw[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if _cutoff and _cutoff <= _d <= _tdate:
                _ttm += _cr / 10.0
                _ttm_cnt += 1
                _ttm_dates.append(_raw[:10])
        _ttm_ps = round(_ttm, 4) if _ttm_cnt else None
        return _build_result_payload(
            "东方财富 A股分红", trade_date, div5=divs, div_years=years,
            div_ttm_ps=_ttm_ps, div_ttm_dates=_ttm_dates,
        )

    payload = _load_aggregate_by_code(
        f"stocktrend_ashare_dividends_{trade_date}.json",
        [item["code"] for item in A_SHARE_STOCKS],
        "A股分红",
        loader,
        "东方财富 A股分红",
        trade_date,
    )
    return (payload.get("items") or {}).get(code) or _build_result_payload("东方财富 A股分红", trade_date, issue="聚合缓存缺失", div5=[], div_years=[], div_ttm_ps=None)


def _fetch_hk_financial_indicator(code: str, trade_date: str) -> Dict[str, Any]:
    def loader(stock_code: str) -> Dict[str, Any]:
        ak = _get_akshare_client()
        df = _safe_ak_call(f"{stock_code} 港股核心指标", ak.stock_hk_financial_indicator_em, symbol=stock_code)
        if df is None or df.empty:
            return _build_result_payload("东方财富 港股核心指标", trade_date, issue="公开接口返回空数据")
        row = df.iloc[0].to_dict()
        return _build_result_payload(
            "东方财富 港股核心指标",
            trade_date,
            pe=_to_float(row.get("市盈率")),
            pb=_to_float(row.get("市净率")),
            div=_to_float(row.get("股息率TTM(%)")),
            dividend_ttm=_to_float(row.get("每股股息TTM(港元)")),
            mkt_raw=_to_float(row.get("总市值(港元)")),
            roe=_to_float(row.get("股东权益回报率(%)")),
        )

    payload = _load_aggregate_by_code(
        f"stocktrend_hk_financials_{trade_date}.json",
        [str(item["code"]).zfill(5) for item in _load_hk_base_data()["stocks"]],
        "港股核心指标",
        loader,
        "东方财富 港股核心指标",
        trade_date,
    )
    return (payload.get("items") or {}).get(code) or _build_result_payload("东方财富 港股核心指标", trade_date, issue="聚合缓存缺失")


def _fetch_hk_financial_analysis(code: str, trade_date: str) -> Dict[str, Any]:
    def loader(stock_code: str) -> Dict[str, Any]:
        ak = _get_akshare_client()
        analysis_fn = getattr(ak, "stock_financial_hk_analysis_indicator_em", None)
        if analysis_fn is None:
            return _build_result_payload("东方财富 港股财务分析", trade_date, issue="AKShare 未提供港股财务分析接口")
        df = _safe_ak_call(f"{stock_code} 港股财务分析", analysis_fn, symbol=stock_code)
        if df is None or df.empty:
            return _build_result_payload("东方财富 港股财务分析", trade_date, issue="公开接口返回空数据")
        row = df.iloc[-1].to_dict()
        report_year = _extract_year_from_row(row, ["REPORT_DATE", "REPORT_YEAR", "REPORT_DATE_NAME", "报告期"])
        return _build_result_payload(
            "东方财富 港股财务分析",
            trade_date,
            roe=_find_metric_by_any_keywords(row, [["净资产收益率"], ["股东权益回报率"]]),
            margin=_find_metric_by_any_keywords(row, [["销售毛利率"], ["毛利率"]]),
            liab=_find_metric_by_any_keywords(row, [["资产负债率"], ["负债率"]]),
            report_year=report_year,
        )

    payload = _load_aggregate_by_code(
        f"stocktrend_hk_financial_analysis_{trade_date}.json",
        [str(item["code"]).zfill(5) for item in _load_hk_base_data()["stocks"]],
        "港股财务分析",
        loader,
        "东方财富 港股财务分析",
        trade_date,
    )
    return (payload.get("items") or {}).get(code) or _build_result_payload("东方财富 港股财务分析", trade_date, issue="聚合缓存缺失")


def _fetch_hk_dividends(code: str, trade_date: str) -> Dict[str, Any]:
    def loader(stock_code: str) -> Dict[str, Any]:
        ak = _get_akshare_client()
        dividend_fn = getattr(ak, "stock_hk_dividend_payout_em", None)
        if dividend_fn is None:
            return _build_result_payload("东方财富 港股分红派息", trade_date, issue="AKShare 未提供港股分红接口", div5=[], div_years=[])
        df = _safe_ak_call(f"{stock_code} 港股分红派息", dividend_fn, symbol=stock_code)
        if df is None or df.empty:
            return _build_result_payload("东方财富 港股分红派息", trade_date, issue="公开接口返回空数据", div5=[], div_years=[])
        latest_by_year: Dict[int, Dict[str, Any]] = {}
        for row in df.to_dict("records"):
            year = _extract_year_from_row(row, ["报告期", "派息年度", "年度", "财年", "财政年度"])
            if year is None:
                continue
            latest_by_year[year] = row
        years = sorted(latest_by_year.keys())[-5:]
        divs: List[Optional[float]] = []
        for year in years:
            row = latest_by_year[year]
            divs.append(_find_metric_by_any_keywords(row, [["每股股息"], ["每股派息"], ["派息", "每股"], ["股息"]]))
        return _build_result_payload("东方财富 港股分红派息", trade_date, div5=divs, div_years=years)

    payload = _load_aggregate_by_code(
        f"stocktrend_hk_dividends_{trade_date}.json",
        [str(item["code"]).zfill(5) for item in _load_hk_base_data()["stocks"]],
        "港股分红派息",
        loader,
        "东方财富 港股分红派息",
        trade_date,
    )
    return (payload.get("items") or {}).get(code) or _build_result_payload("东方财富 港股分红派息", trade_date, issue="聚合缓存缺失", div5=[], div_years=[])


def _fetch_stock_connect_holdings(codes: List[str], trade_date: str, market_key: str, label: str) -> Dict[str, Any]:
    filename = f"stocktrend_{market_key}_holdings_{trade_date}.json"
    cached = load_build_json(filename)
    if cached is not None:
        return cached

    payload: Dict[str, Any] = {
        "items": {},
        "summary": {"requested": len(codes), "success": 0, "failed": 0},
        "error_reasons": [],
    }
    ak = _get_akshare_client()
    holding_fn = getattr(ak, "stock_hsgt_individual_em", None)
    if holding_fn is None:
        payload["summary"]["failed"] = len(codes)
        payload["error_reasons"] = ["AKShare 未提供 stock_hsgt_individual_em 接口"]
        save_build_json(filename, payload)
        return payload

    for code in codes:
        try:
            df = call_akshare_with_retry(f"{code} {label}", holding_fn, symbol=code)
        except Exception as exc:
            reason = str(exc)
            payload["items"][code] = {"issue": reason}
            payload["summary"]["failed"] += 1
            payload["error_reasons"].append(reason)
            print(f"[!] {code} {label} 失败：{exc}")
            continue

        if df is None or df.empty:
            reason = "公开接口返回空数据"
            payload["items"][code] = {"issue": reason}
            payload["summary"]["failed"] += 1
            payload["error_reasons"].append(reason)
            continue

        row = df.iloc[-1].to_dict()
        shares = _to_float(row.get("持股数量"))
        pct = (
            _to_float(row.get("持股数量占A股百分比"))
            if row.get("持股数量占A股百分比") is not None
            else _find_metric_by_any_keywords(
                row,
                [["持股数量占A股百分比"], ["占总股本", "比例"], ["占已发行股份", "比例"], ["占比"]],
            )
        )
        issue = None
        if shares is None and pct is None:
            issue = "公开接口未返回持股字段"
            payload["summary"]["failed"] += 1
            payload["error_reasons"].append(issue)
        else:
            payload["summary"]["success"] += 1
        payload["items"][code] = {
            "shares": shares,
            "pct": pct,
            "holding_date": str(row.get("持股日期") or ""),
            "issue": issue,
        }

    payload["error_reasons"] = _dedupe_texts(payload["error_reasons"])
    save_build_json(filename, payload)
    return payload




def _report_period_raw(row: Dict[str, Any]) -> str:
    """从财务分析行里提取报告期原始字符串（优先『报告期』字段，回退遍历所有值）。"""
    for k, v in (row or {}).items():
        if "报告期" in str(k) or "REPORT" in str(k).upper():
            return str(v)
    for v in (row or {}).values():
        if re.search(r"\d{4}[-/]?\d{2}[-/]?\d{2}", str(v)):
            return str(v)
    return ""


def _find_annual_row(rows: List[Dict[str, Any]]):
    """找最近一个『年报』（报告期月份为 12）的行，返回 (年份, 行) 或 None。"""
    best = None
    for r in rows or []:
        raw = _report_period_raw(r)
        m = re.search(r"(\d{4})[-/]?(\d{1,2})", raw)
        if not m:
            continue
        y = int(m.group(1))
        mo = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 0
        if mo == 12 and (best is None or y > best[0]):
            best = (y, r)
    return best


def _build_fin3(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """取最近 5 个报告期年份的 ROE / 毛利率 / 资产负债率 / 每股收益 / 每股经营现金流。

    每条带 annual 标记（报告期为 12 月 = 年报）。「盈利质量与排雷」与「分红回报全景」
    优先用 annual=True 的年报口径，避免中报（半年值）造成 ROE 腰斩的错觉。
    """
    by_year: Dict[int, Dict[str, Any]] = {}
    for row in rows or []:
        raw = _report_period_raw(row)
        m = re.search(r"(\d{4})[-/]?(\d{1,2})", raw)
        year = int(m.group(1)) if m else None
        if not year:
            year = _extract_year_from_row(row, ["REPORT_DATE", "REPORT_YEAR", "REPORT_DATE_NAME"])
        if not year:
            continue
        month = int(m.group(2)) if (m and m.lastindex and m.lastindex >= 2) else 12
        # rows 已按报告期降序，setdefault 保留每年「最新一期」报告
        by_year.setdefault(year, (month, row))
    seq: List[Dict[str, Any]] = []
    for year in sorted(by_year.keys(), reverse=True)[:5]:
        month, row = by_year[year]
        seq.append({
            "year": year,
            "annual": month == 12,
            "roe": _to_float(row.get("ROEJQ")),
            "margin": _to_float(row.get("XSMLL")),
            "liab": _to_float(row.get("ZCFZL")),
            "eps": _to_float(row.get("EPSJB")),
            "ocfps": _to_float(row.get("MGJYXJJE")),
        })
    return seq




def _fetch_ashare_financial_snapshot(code: str, trade_date: str) -> Dict[str, Any]:
    def loader(stock_code: str) -> Dict[str, Any]:
        symbol = f"{stock_code}.SH" if stock_code.startswith("6") else f"{stock_code}.SZ"
        ak = _get_akshare_client()
        analysis_fn = getattr(ak, "stock_financial_analysis_indicator_em", None)
        if analysis_fn is None:
            return _build_result_payload("东方财富 A股财务分析", trade_date, issue="AKShare 未提供 A股财务分析接口")
        df = _safe_ak_call(f"{stock_code} A股财务分析", analysis_fn, symbol=symbol, indicator="按报告期")
        if df is None or df.empty:
            return _build_result_payload("东方财富 A股财务分析", trade_date, issue="公开接口返回空数据")
        rows = df.to_dict("records")
        annual = _find_annual_row(rows)
        chosen = annual[1] if annual else (rows[0] if rows else {})
        chosen_year = annual[0] if annual else _extract_year_from_row(chosen, ["REPORT_DATE", "REPORT_YEAR", "REPORT_DATE_NAME"])
        period_label = "年报" if annual else "最新报告期"
        return _build_result_payload(
            "东方财富 A股财务分析",
            trade_date,
            roe=_to_float(chosen.get("ROEJQ")),
            margin=_to_float(chosen.get("XSMLL")),
            liab=_to_float(chosen.get("ZCFZL")),
            eps=_to_float(chosen.get("EPSJB")),
            report_year=chosen_year,
            report_period=period_label,
            fin3=_build_fin3(rows),
        )

    payload = _load_aggregate_by_code(
        f"stocktrend_ashare_financials_{trade_date}.json",
        [item["code"] for item in A_SHARE_STOCKS],
        "A股财务分析",
        loader,
        "东方财富 A股财务分析",
        trade_date,
    )
    return (payload.get("items") or {}).get(code) or _build_result_payload("东方财富 A股财务分析", trade_date, issue="聚合缓存缺失")


_MARGIN_TARGET_CODES = {item["code"] for item in A_SHARE_STOCKS}


def _absorb_margin_rows(df: Any, code_col: str, date_col: Optional[str], out: Dict[str, Dict[str, Any]]) -> None:
    """把单市场融资融券明细行筛入目标股票集合。"""
    for row in df.to_dict("records"):
        code = str(row.get(code_col) or "").zfill(6)
        if code not in _MARGIN_TARGET_CODES:
            continue
        rec = out.setdefault(code, {})
        if rec.get("margin_balance") is None:
            rec["margin_balance"] = _to_float(row.get("融资余额"))
        if rec.get("margin_buy") is None:
            rec["margin_buy"] = _to_float(row.get("融资买入额"))
        if date_col and rec.get("margin_date") is None:
            rec["margin_date"] = str(row.get(date_col) or "")[:10]


def _fetch_ashare_margin(trade_date: str) -> Dict[str, Dict[str, Any]]:
    """融资融券明细：每交易日 2 次请求（上交所 + 深交所各一次全市场），筛出清单内个股的融资余额/融资买入额。

    数据源为沪深交易所官网（AKShare stock_margin_detail_sse/szse，交易所 T 日收盘后披露次日可取）；
    非融资融券标的自然不在返回表内，调用方以缺失视为「—」。
    """
    def loader() -> Dict[str, Any]:
        ak = _get_akshare_client()
        date_compact = trade_date.replace("-", "")
        result: Dict[str, Dict[str, Any]] = {}
        sse_fn = getattr(ak, "stock_margin_detail_sse", None)
        if sse_fn is not None:
            sse = _safe_ak_call("沪市融资融券明细", sse_fn, date=date_compact)
            if sse is not None and not sse.empty:
                _absorb_margin_rows(sse, "标的证券代码", "信用交易日期", result)
        szse_fn = getattr(ak, "stock_margin_detail_szse", None)
        if szse_fn is not None:
            szse = _safe_ak_call("深市融资融券明细", szse_fn, date=date_compact)
            if szse is not None and not szse.empty:
                _absorb_margin_rows(szse, "证券代码", None, result)
        for rec in result.values():
            date_text = str(rec.get("margin_date") or trade_date)[:10]
            if re.fullmatch(r"\d{8}", date_text):
                date_text = f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:8]}"
            rec["margin_date"] = date_text
        return result

    return _load_or_fetch_build(f"stocktrend_ashare_margin_{trade_date}.json", loader) or {}


def _fetch_ashare_northbound(trade_date: str) -> Dict[str, Dict[str, Any]]:
    codes = [item["code"] for item in A_SHARE_STOCKS]
    payload = _fetch_stock_connect_holdings(codes, trade_date, "ashare_northbound", "A股北向持股")
    result: Dict[str, Dict[str, Any]] = {}
    for code, row in (payload.get("items") or {}).items():
        result[str(code).zfill(6)] = {
            "north_shares": row.get("shares"),
            "north_pct": row.get("pct"),
            "north_date": row.get("holding_date"),
            "issue": row.get("issue"),
        }
    return result


def _fetch_ashare_main_flow(codes: List[str], trade_date: str) -> Dict[str, Dict[str, Any]]:
    rows, _, _ = load_or_fetch_stock_fundflow_build(trade_date, stock_codes=codes, scope="stocktrend")
    payload: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("code") or "").zfill(6)
        payload[code] = {"main_net_in": _to_float(row.get("main_net_in")), "pct": _to_float(row.get("pct"))}
    return payload




