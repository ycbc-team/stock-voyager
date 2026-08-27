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


ak = get_akshare()


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
    {"key": "consumer", "title": "大消费板块", "label": "消费", "color": "#f0c040"},
    {"key": "healthcare", "title": "医药健康板块", "label": "医药", "color": "#58a6ff"},
    {"key": "manufacturing", "title": "制造升级板块", "label": "制造", "color": "#ff8c42"},
    {"key": "tech", "title": "科技成长板块", "label": "科技", "color": "#3fb950"},
    {"key": "finance", "title": "金融地产板块", "label": "金融", "color": "#bc8cff"},
    {"key": "resource", "title": "资源公用板块", "label": "资源", "color": "#f85149"},
]


A_SHARE_COMBOS = [
    {"cls": "combo-stable", "title": "稳健红利组合", "codes": ["600941", "600900", "601088", "600036", "601318"], "desc": "偏向现金流与分红能力，适合把握 A 股核心资产中的稳健底仓。"},
    {"cls": "combo-growth", "title": "核心消费组合", "codes": ["600519", "600887", "000333", "603605", "000538"], "desc": "聚焦品牌壁垒与消费龙头，适合中长期跟踪景气与估值切换。"},
    {"cls": "combo-aggressive", "title": "景气制造组合", "codes": ["300750", "002594", "002415", "600150", "601899"], "desc": "弹性更强，受行业景气与周期波动影响更大，适合分批布局。"},
]


def _a_stock(code: str, zh: str, sector: str, l1: str, l2: str, l2_code: str, border: str) -> Dict[str, Any]:
    return {"code": code, "zh": zh, "en": zh, "sector": sector, "l1": l1, "l2": l2, "l2_code": l2_code, "border": border}


A_SHARE_STOCKS = [
    _a_stock("600519", "贵州茅台", "consumer", "消费龙头", "白酒", "1010", "yellow"),
    _a_stock("600887", "伊利股份", "consumer", "消费龙头", "乳制品", "1020", "green"),
    _a_stock("600276", "恒瑞医药", "healthcare", "医药健康", "创新药", "2010", "blue"),
    _a_stock("000333", "美的集团", "manufacturing", "制造升级", "白电", "3010", "orange"),
    _a_stock("600398", "海澜之家", "consumer", "消费龙头", "服饰零售", "1030", "brown"),
    _a_stock("603195", "公牛集团", "consumer", "消费龙头", "家居消费", "1040", "yellow"),
    _a_stock("601888", "中国中免", "consumer", "消费龙头", "免税零售", "1050", "orange"),
    _a_stock("600754", "锦江酒店", "consumer", "消费龙头", "酒店旅游", "1060", "gray"),
    _a_stock("603605", "珀莱雅", "consumer", "消费龙头", "美妆护理", "1070", "purple"),
    _a_stock("601088", "中国神华", "resource", "资源公用", "煤炭", "6010", "red"),
    _a_stock("600938", "中国海油", "resource", "资源公用", "石油天然气", "6020", "red"),
    _a_stock("600309", "万华化学", "resource", "资源公用", "化工材料", "6030", "orange"),
    _a_stock("000708", "中信特钢", "manufacturing", "制造升级", "钢铁材料", "3020", "brown"),
    _a_stock("601899", "紫金矿业", "resource", "资源公用", "有色金属", "6040", "orange"),
    _a_stock("300750", "宁德时代", "manufacturing", "制造升级", "动力电池", "3030", "green"),
    _a_stock("600585", "海螺水泥", "resource", "资源公用", "建材", "6050", "gray"),
    _a_stock("601668", "中国建筑", "finance", "金融地产", "建筑央企", "5010", "blue"),
    _a_stock("002415", "海康威视", "tech", "科技成长", "安防设备", "4010", "green"),
    _a_stock("002594", "比亚迪", "manufacturing", "制造升级", "新能源汽车", "3040", "purple"),
    _a_stock("300033", "同花顺", "tech", "科技成长", "金融 IT", "4020", "blue"),
    _a_stock("600941", "中国移动", "finance", "金融地产", "运营商", "5020", "blue"),
    _a_stock("002027", "分众传媒", "consumer", "消费龙头", "广告传媒", "1080", "gray"),
    _a_stock("600760", "中航沈飞", "manufacturing", "制造升级", "军工装备", "3050", "red"),
    _a_stock("600031", "三一重工", "manufacturing", "制造升级", "工程机械", "3060", "orange"),
    _a_stock("600036", "招商银行", "finance", "金融地产", "银行", "5030", "blue"),
    _a_stock("601318", "中国平安", "finance", "金融地产", "保险", "5040", "purple"),
    _a_stock("600048", "保利发展", "finance", "金融地产", "房地产", "5050", "brown"),
    _a_stock("600900", "长江电力", "resource", "资源公用", "水电", "6060", "green"),
    _a_stock("603568", "伟明环保", "resource", "资源公用", "环保服务", "6070", "green"),
    _a_stock("601816", "京沪高铁", "finance", "金融地产", "铁路运输", "5060", "gray"),
    _a_stock("000538", "云南白药", "healthcare", "医药健康", "中药", "2020", "yellow"),
    _a_stock("600150", "中国船舶", "manufacturing", "制造升级", "船舶制造", "3070", "red"),
]


SECTOR_RISK_TEXT = {
    "consumer": ["消费需求恢复不及预期", "渠道或品牌竞争加剧", "高位估值阶段回撤放大"],
    "healthcare": ["集采与政策扰动盈利节奏", "研发兑现与产品放量低于预期", "市场风格切换导致估值承压"],
    "manufacturing": ["行业景气波动影响订单释放", "原材料价格扰动利润率", "资本开支阶段带来现金流压力"],
    "tech": ["技术迭代快、竞争格局变化快", "高估值阶段波动更大", "机构持仓拥挤时回撤更明显"],
    "finance": ["宏观信用周期影响盈利", "政策与监管环境变化", "地产与利率周期传导估值波动"],
    "resource": ["商品价格中枢波动", "政策与供给节奏变化", "周期股高位回撤速度较快"],
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


def _build_issue_text(label: str, issue: Optional[str]) -> Optional[str]:
    text = str(issue or "").strip()
    if not text:
        return None
    return f"{label}异常：{text}"


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
        df = _safe_ak_call(f"{stock_code} A股分红", ak.stock_fhps_detail_em, symbol=stock_code)
        if df is None or df.empty:
            return _build_result_payload("东方财富 A股分红", trade_date, issue="公开接口返回空数据", div5=[], div_years=[])
        rows = df.to_dict("records")
        by_year = _pick_latest_row_per_year(rows, "报告期")
        years = sorted(by_year.keys())[-5:]
        divs: List[Optional[float]] = []
        for year in years:
            cash_ratio = _to_float(by_year[year].get("现金分红-现金分红比例"))
            divs.append(round(cash_ratio / 10.0, 4) if cash_ratio is not None else None)
        return _build_result_payload("东方财富 A股分红", trade_date, div5=divs, div_years=years)

    payload = _load_aggregate_by_code(
        f"stocktrend_ashare_dividends_{trade_date}.json",
        [item["code"] for item in A_SHARE_STOCKS],
        "A股分红",
        loader,
        "东方财富 A股分红",
        trade_date,
    )
    return (payload.get("items") or {}).get(code) or _build_result_payload("东方财富 A股分红", trade_date, issue="聚合缓存缺失", div5=[], div_years=[])


def _fetch_hk_financial_indicator(code: str, trade_date: str) -> Dict[str, Any]:
    def loader(stock_code: str) -> Dict[str, Any]:
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


def _fetch_ashare_financial_snapshot(code: str, trade_date: str) -> Dict[str, Any]:
    def loader(stock_code: str) -> Dict[str, Any]:
        symbol = f"{stock_code}.SH" if stock_code.startswith("6") else f"{stock_code}.SZ"
        analysis_fn = getattr(ak, "stock_financial_analysis_indicator_em", None)
        if analysis_fn is None:
            return _build_result_payload("东方财富 A股财务分析", trade_date, issue="AKShare 未提供 A股财务分析接口")
        df = _safe_ak_call(f"{stock_code} A股财务分析", analysis_fn, symbol=symbol, indicator="按报告期")
        if df is None or df.empty:
            return _build_result_payload("东方财富 A股财务分析", trade_date, issue="公开接口返回空数据")
        row = df.iloc[0].to_dict()
        report_year = _extract_year_from_row(row, ["REPORT_DATE", "REPORT_YEAR", "REPORT_DATE_NAME"])
        return _build_result_payload(
            "东方财富 A股财务分析",
            trade_date,
            roe=_to_float(row.get("ROEJQ")),
            margin=_to_float(row.get("XSMLL")),
            liab=_to_float(row.get("ZCFZL")),
            eps=_to_float(row.get("EPSJB")),
            report_year=report_year,
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
    return {
        "signal": signal,
        "suggest": suggest,
        "summary": f"{name} 当前以 {pe_text}、{pos_text} 为核心跟踪锚点，{flow_text}，{north_text}。",
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
    return {
        "signal": signal,
        "suggest": suggest,
        "summary": f"{name} 当前以 {pe_text}、{pos_text} 为核心跟踪锚点，{div_text}，{south_text}。",
        "trend": f"{name} 处于 {pos_text} 区间，建议结合估值位置、区间涨跌与南向持股变化做跟踪。",
        "capital": f"{south_text}；{div_text}。",
        "risks": SECTOR_RISK_TEXT.get(sector_key, ["行业景气波动", "估值回撤风险", "市场风格切换风险"]),
    }


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

        price = _to_float(hist_last.get("收盘")) or _to_float(spot.get("最新价"))
        last_div = None
        for value in reversed(dividends.get("div5") or []):
            if value is not None:
                last_div = value
                break
        div_yield = None
        if price not in (None, 0) and last_div is not None:
            div_yield = last_div / price * 100

        generated = _build_generic_texts(meta["zh"], meta["sector"], _to_float(spot.get("市盈率-动态")), hist_stats.get("pos"), flow.get("main_net_in"), north.get("north_pct"))
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
                "financial_source": financial.get("source"),
                "financial_as_of": financial.get("as_of"),
                "div5": dividends.get("div5") or [],
                "div_years": dividends.get("div_years") or [],
                "dividend_source": dividends.get("source"),
                "dividend_as_of": dividends.get("as_of"),
                "main_inflow": flow.get("main_net_in"),
                "north_pct": north.get("north_pct"),
                "north_shares": north.get("north_shares"),
                "north_date": north.get("north_date"),
                "north_value": None,
                "history_as_of": trade_date,
                "data_issues": stock_issues,
                **generated,
            }
        )

    return {
        "meta": {
            "market_code": "ashare",
            "title": "A股核心个股走势分析",
            "tag": f"收盘快照 · {trade_date}",
            "subtitle": "依据《个股走势分析》需求文档的 32 只核心 A 股清单生成；使用统一静态模板渲染，可直接部署或归档。",
            "date": f"行情：{trade_date} 收盘快照（AKShare / 东方财富）｜ A股惯例：涨红跌绿",
            "databadge": "⚠️ 数据口径：行情为当日收盘快照；主力净流入优先复用 build/cache 中的共享资金流产物；北向持股、财务分析、分红均来自公开接口。",
            "modal_databadge": "⚠️ 本页为静态收盘快照：价格、涨跌、成交额、市值、估值均对应收盘口径；主力净流入为当日口径；分红 / 财务指标取公开披露值，若缺失则显示“—”。",
            "disclaimer": "⚠️ 免责声明：页面仅做公开数据整理与展示，不构成投资建议。",
            "footer": f"A股核心个股走势分析 · {trade_date} · 数据源：AKShare / 东方财富",
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
            "tag": f"收盘快照 · {trade_date}",
            "date": f"行情：{trade_date} 收盘快照（AKShare / 东方财富）｜ 港股惯例：涨红跌绿",
            "databadge": "⚠️ 数据口径：行情为当日收盘快照；PE / PB / 股息率优先取东方财富港股核心指标；ROE / 毛利率 / 资产负债率、近 5 年分红、南向持股优先走实时公开接口，缺失则显示“—”。",
            "modal_databadge": "⚠️ 本页为静态模板 + 实时数据：价格、涨跌、成交额对应收盘口径；PE / PB / 股息率、财务分析、分红派息、南向持股均优先取公开接口实时结果。",
            "disclaimer": "⚠️ 免责声明：页面仅做公开数据整理与展示，不构成投资建议。行业分类、组合分组与风险提示为静态模板配置；价格、估值、财务、分红、南向持股为实时公开数据。",
            "footer": f"{meta.get('title', '港股核心个股走势分析')} · {trade_date} · 数据源：AKShare / 东方财富 / 港交所公开披露链路",
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
    trade_date = data_date or detect_trade_date()
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
    parser = argparse.ArgumentParser(description="stocktrend 数据收集脚本：按请求拆分 JSON 产物，并汇总生成 stocktrend 页面 JSON")
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
