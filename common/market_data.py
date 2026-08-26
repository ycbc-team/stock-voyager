#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared external request helpers for fundflow and stocktrend."""
from __future__ import annotations

import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

from common.storage import load_build_json
from common.storage import save_build_json


EM_HOSTS = [
    "https://push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
    "https://push2his.eastmoney.com",
]
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"
GTIMG_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://gu.qq.com/",
}
DC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "*/*",
}

REQUEST_DELAY = float(os.environ.get("REQ_DELAY", "0.35"))
HTTP_BACKOFF = float(os.environ.get("REQUEST_RETRY_BACKOFF", "1.6"))
AK_RETRIES = int(os.environ.get("AKSHARE_RETRIES", "3"))
AK_BACKOFF = float(os.environ.get("AKSHARE_RETRY_BACKOFF", "1.8"))
FUND_FLOW_BATCH_SIZE = int(os.environ.get("FUND_FLOW_BATCH_SIZE", "400"))
FUND_FLOW_BATCH_HOST = os.environ.get("FUND_FLOW_BATCH_HOST", "https://push2delay.eastmoney.com")

REQUEST_COUNT = {"n": 0}


def reset_request_count() -> None:
    REQUEST_COUNT["n"] = 0


def get_request_count() -> int:
    return REQUEST_COUNT["n"]


def _count_external_request() -> None:
    REQUEST_COUNT["n"] += 1


def _sleep(delay: Optional[float] = None) -> None:
    actual_delay = REQUEST_DELAY if delay is None else delay
    if actual_delay > 0:
        time.sleep(actual_delay)


def get_akshare() -> Any:
    try:
        import akshare as ak  # type: ignore
        return ak
    except ImportError as exc:
        raise SystemExit("缺少依赖 akshare。请先执行 `pip install -r requirements.txt`。") from exc


def call_akshare_with_retry(label: str, fn: Any, *args: Any, retries: Optional[int] = None, backoff: Optional[float] = None, **kwargs: Any) -> Any:
    max_retries = AK_RETRIES if retries is None else retries
    retry_backoff = AK_BACKOFF if backoff is None else backoff
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        _count_external_request()
        _sleep()
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            if attempt >= max_retries - 1:
                break
            time.sleep(retry_backoff ** attempt)
    if last_error is not None:
        raise last_error
    return None


def http_get(url: str, headers: Dict[str, str], timeout: int = 15, retries: int = 3, backoff: Optional[float] = None) -> Optional[str]:
    retry_backoff = HTTP_BACKOFF if backoff is None else backoff
    for attempt in range(retries):
        _count_external_request()
        _sleep()
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
                for encoding in ("utf-8", "gbk"):
                    try:
                        return raw.decode(encoding)
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", "ignore")
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, TimeoutError):
            if attempt >= retries - 1:
                break
            time.sleep(retry_backoff ** attempt)
    return None


def em_get(path: str, params: Dict[str, Any], timeout: Optional[int] = None, retries: Optional[int] = None) -> Optional[Dict[str, Any]]:
    actual_timeout = int(os.environ.get("EM_TIMEOUT", "15")) if timeout is None else timeout
    actual_retries = int(os.environ.get("EM_RETRIES", "3")) if retries is None else retries
    if "ut" not in params:
        params = {**params, "ut": EM_UT}
    query = urllib.parse.urlencode(params)
    for host in EM_HOSTS:
        text = http_get(f"{host}{path}?{query}&_={int(time.time() * 1000)}", EM_HEADERS, timeout=actual_timeout, retries=actual_retries)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if payload.get("rc") == 0 and payload.get("data"):
            return payload
    return None


def em_get_direct(host: str, path: str, params: Dict[str, Any], timeout: Optional[int] = None, retries: Optional[int] = None) -> Optional[Dict[str, Any]]:
    actual_timeout = int(os.environ.get("EM_TIMEOUT", "15")) if timeout is None else timeout
    actual_retries = int(os.environ.get("EM_RETRIES", "3")) if retries is None else retries
    if "ut" not in params:
        params = {**params, "ut": EM_UT}
    query = urllib.parse.urlencode(params)
    text = http_get(f"{host}{path}?{query}&_={int(time.time() * 1000)}", EM_HEADERS, timeout=actual_timeout, retries=actual_retries)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if payload.get("rc") == 0 and payload.get("data") is not None:
        return payload
    return None


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "-", "--", "None"):
            return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def diff_list(data: Any) -> List[Dict[str, Any]]:
    diff = data.get("diff") if isinstance(data, dict) else None
    if diff is None:
        return []
    if isinstance(diff, list):
        return diff
    if isinstance(diff, dict):
        return [diff[key] for key in sorted(diff.keys(), key=lambda item: int(item) if str(item).isdigit() else str(item))]
    return []


def market_by_code(code: str) -> Optional[str]:
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"
    if code.startswith(("430", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879", "880", "920")):
        return "bj"
    return None


def secid_from_code(code: str) -> Optional[str]:
    market = market_by_code(code)
    if market == "sh":
        return f"1.{code}"
    if market in ("sz", "bj"):
        return f"0.{code}"
    return None


def detect_trade_date() -> str:
    text = http_get("https://qt.gtimg.cn/q=sh000001", GTIMG_HEADERS, timeout=12, retries=3)
    if text:
        import re
        match = re.search(r"~(\d{14})~", text)
        if match:
            raw_date = match.group(1)[:8]
            return f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        day = now - datetime.timedelta(days=(now.weekday() - 4))
        return day.strftime("%Y-%m-%d")
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        day = now - datetime.timedelta(days=1)
        while day.weekday() >= 5:
            day -= datetime.timedelta(days=1)
        return day.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def _iter_chunks(items: Iterable[str], size: int) -> Iterable[List[str]]:
    values = list(items)
    chunk_size = size if size > 0 else 200
    for index in range(0, len(values), chunk_size):
        yield values[index:index + chunk_size]


def _fetch_stock_fundflow_by_secid_batches(stock_codes: Iterable[str], indicator: str = "今日") -> Tuple[List[Dict[str, Any]], str]:
    if indicator != "今日":
        return [], "secid 批量资金流当前仅支持今日口径"
    secids: List[str] = []
    secid_to_code: Dict[str, str] = {}
    for code in sorted({str(item).zfill(6) for item in (stock_codes or []) if item}):
        secid = secid_from_code(code)
        if not secid:
            continue
        secids.append(secid)
        secid_to_code[secid] = code
    if not secids:
        return [], "股票代码为空，无法做 secid 批量资金流请求"

    rows_by_code: Dict[str, Dict[str, Any]] = {}
    pending = list(secids)
    batch_plan = [FUND_FLOW_BATCH_SIZE]
    if FUND_FLOW_BATCH_SIZE > 80:
        batch_plan.append(80)

    for current_batch_size in batch_plan:
        if not pending:
            break
        next_pending: List[str] = []
        for batch in _iter_chunks(pending, current_batch_size):
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
                next_pending.extend(batch)
                continue
            rows = diff_list((payload.get("data") or {}))
            if not rows:
                next_pending.extend(batch)
                continue
            seen_codes = set()
            for row in rows:
                code = str(row.get("f12") or "").zfill(6)
                if not code:
                    continue
                seen_codes.add(code)
                pct_raw = to_float(row.get("f3"))
                rows_by_code[code] = {
                    "code": code,
                    "name": row.get("f14"),
                    "market": market_by_code(code),
                    "pct": pct_raw / 100 if pct_raw is not None else None,
                    "main_net_in": to_float(row.get("f62")),
                }
            for secid in batch:
                code = secid_to_code.get(secid)
                if code and code not in seen_codes and code not in rows_by_code:
                    next_pending.append(secid)
        pending = next_pending

    rows = [rows_by_code[code] for code in sorted(rows_by_code)]
    if not rows:
        return [], "东方财富延迟行情主机 secid 批量接口暂不可用"
    covered = len(rows)
    total = len(secids)
    if pending:
        return rows, f"东方财富延迟行情主机 secid 批量资金流（覆盖 {covered}/{total}，未命中批次已跳过）"
    return rows, f"东方财富延迟行情主机 secid 批量资金流（覆盖 {covered}/{total}）"


def _fetch_stock_fundflow_rank_em_fallback(indicator: str = "今日") -> Tuple[List[Dict[str, Any]], str]:
    indicator_map = {
        "今日": ["f62", "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124", "f3", "f62"],
        "3日": ["f267", "f12,f14,f2,f127,f267,f268,f269,f270,f271,f272,f273,f274,f275,f276,f257,f258,f124", "f127", "f267"],
        "5日": ["f164", "f12,f14,f2,f109,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f257,f258,f124", "f109", "f164"],
        "10日": ["f174", "f12,f14,f2,f160,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f260,f261,f124", "f160", "f174"],
    }
    config = indicator_map.get(indicator)
    if not config:
        return [], "不支持的 indicator"
    fid, fields, pct_key, net_key = config
    params = {
        "fid": fid,
        "po": "1",
        "pz": "100",
        "pn": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fs": "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2",
        "fields": fields,
    }
    host = "https://push2delay.eastmoney.com"
    first_page = em_get("/api/qt/clist/get", params)
    if not first_page:
        query = urllib.parse.urlencode(params)
        text = http_get(f"{host}/api/qt/clist/get?{query}", EM_HEADERS, timeout=20, retries=3)
        if not text:
            return [], "东方财富延迟行情主机不可用"
        try:
            first_page = json.loads(text)
        except json.JSONDecodeError:
            return [], "东方财富延迟行情主机返回非 JSON"
    total = (((first_page or {}).get("data") or {}).get("total") or 0)
    rows: List[Dict[str, Any]] = []
    total_page = max(1, (int(total) + 99) // 100)
    for page in range(1, total_page + 1):
        params["pn"] = str(page)
        query = urllib.parse.urlencode(params)
        text = http_get(f"{host}/api/qt/clist/get?{query}", EM_HEADERS, timeout=20, retries=3)
        if not text:
            break
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            break
        for row in diff_list((payload or {}).get("data") or {}):
            code = str(row.get("f12") or "").zfill(6)
            market = market_by_code(code)
            if not market:
                continue
            pct_raw = to_float(row.get(pct_key))
            rows.append({"code": code, "name": row.get("f14"), "market": market, "pct": pct_raw / 100 if pct_raw is not None else None, "main_net_in": to_float(row.get(net_key))})
    return rows, ("东方财富延迟行情主机个股资金流全市场排行" if rows else "东方财富延迟行情主机个股资金流接口暂不可用")


def fetch_stock_fundflow_rank(indicator: str = "今日", stock_codes: Optional[Iterable[str]] = None) -> Tuple[List[Dict[str, Any]], str]:
    if stock_codes:
        rows, source = _fetch_stock_fundflow_by_secid_batches(stock_codes, indicator=indicator)
        if rows:
            return rows, source
    ak = get_akshare()
    try:
        df = call_akshare_with_retry("AKShare 个股资金流排行", ak.stock_individual_fund_flow_rank, indicator=indicator)
    except Exception as exc:
        rows, fallback_source = _fetch_stock_fundflow_rank_em_fallback(indicator)
        if rows:
            return rows, f"AKShare 失败，已回退到东方财富延迟行情主机: {fallback_source}"
        return [], f"AKShare 个股资金流排行接口暂不可用: {exc}"

    prefix = indicator
    pct_col = f"{prefix}涨跌幅"
    net_col = f"{prefix}主力净流入-净额"
    rows = []
    for row in df.to_dict("records"):
        code = str(row.get("代码") or "").zfill(6)
        market = market_by_code(code)
        if not market:
            continue
        rows.append({"code": code, "name": row.get("名称"), "market": market, "pct": to_float(row.get(pct_col)), "main_net_in": to_float(row.get(net_col))})
    return rows, ("AKShare 个股资金流全市场排行" if rows else "AKShare 个股资金流排行接口暂不可用")


def load_or_fetch_stock_fundflow_build(data_date: str, stock_codes: Optional[Iterable[str]] = None, scope: str = "full") -> Tuple[List[Dict[str, Any]], str, str]:
    full_filename = f"stock_fundflow_today_full_{data_date}.json"
    full_payload = load_build_json(full_filename)
    if full_payload:
        rows = list(full_payload.get("rows") or [])
        if stock_codes:
            wanted = {str(code).zfill(6) for code in stock_codes}
            rows = [row for row in rows if str(row.get("code") or "").zfill(6) in wanted]
        return rows, full_payload.get("source", "build/full"), full_filename

    scoped_filename = f"stock_fundflow_today_{scope}_{data_date}.json"
    scoped_payload = load_build_json(scoped_filename)
    if scoped_payload:
        return list(scoped_payload.get("rows") or []), scoped_payload.get("source", "build/scoped"), scoped_filename

    rows, source = fetch_stock_fundflow_rank(indicator="今日", stock_codes=stock_codes)
    payload = {
        "data_date": data_date,
        "scope": scope,
        "source": source,
        "rows": rows,
    }
    save_build_json(scoped_filename, payload)
    return rows, source, scoped_filename
