#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股收盘数据生产脚本
===================
职责：
  1. 抓取 A 股收盘核心数据
  2. 生成统一 JSON 中间产物
  3. 可选导出申万行业 CSV

本脚本不负责 HTML 页面渲染；HTML 由 funflow_ui_renderer.py 基于 JSON 产物构造。
"""
import argparse
import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


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
DC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "*/*",
}
GTIMG_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://gu.qq.com/",
}
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
    ("大盘成长", "0.399372"), ("大盘价值", "0.399373"),
    ("中盘成长", "0.399374"), ("中盘价值", "0.399375"),
    ("小盘成长", "0.399376"), ("小盘价值", "0.399377"),
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

REQ_COUNT = {"n": 0}
REQUEST_DELAY = float(os.environ.get("REQ_DELAY", "0.35"))
CACHE_TTL_HOURS = int(os.environ.get("FUND_CACHE_TTL_HOURS", str(24 * 7)))
STATIC_CACHE_TTL_HOURS = int(os.environ.get("FUND_STATIC_CACHE_TTL_HOURS", str(24 * 180)))
FUND_FLOW_BATCH_SIZE = int(os.environ.get("FUND_FLOW_BATCH_SIZE", "400"))
FUND_FLOW_BATCH_HOST = os.environ.get("FUND_FLOW_BATCH_HOST", "https://push2delay.eastmoney.com")


def _script_dirs():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    cache_dir = os.path.join(script_dir, ".cache")
    os.makedirs(cache_dir, exist_ok=True)
    return script_dir, root_dir, cache_dir


def default_build_dir():
    _, root_dir, _ = _script_dirs()
    return os.path.join(root_dir, "build")


def _cache_path(name):
    _, _, cache_dir = _script_dirs()
    return os.path.join(cache_dir, name)


def _load_cache(name, max_age_hours=CACHE_TTL_HOURS):
    path = _cache_path(name)
    if not os.path.exists(path):
        return None
    age_sec = time.time() - os.path.getmtime(path)
    if age_sec > max_age_hours * 3600:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(name, data):
    path = _cache_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _akshare():
    try:
        import akshare as ak  # type: ignore
        return ak
    except ImportError:
        raise SystemExit("缺少依赖 akshare。请先创建 venv 并执行 `pip install -r requirements.txt`。")


def _count_external_request(n=1):
    REQ_COUNT["n"] += n


def _paced_call(fn, *args, **kwargs):
    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)
    _count_external_request()
    return fn(*args, **kwargs)


def _http_get(url, headers, timeout=15, retries=3, backoff=1.5):
    REQ_COUNT["n"] += 1
    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                for enc in ("utf-8", "gbk"):
                    try:
                        return raw.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", "ignore")
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, TimeoutError):
            time.sleep(backoff * (i + 1))
    return None


def em_get(path, params, timeout=None, retries=None):
    if timeout is None:
        timeout = int(os.environ.get("EM_TIMEOUT", "15"))
    if retries is None:
        retries = int(os.environ.get("EM_RETRIES", "3"))
    if "ut" not in params:
        params = {**params, "ut": EM_UT}
    q = urllib.parse.urlencode(params)
    for host in EM_HOSTS:
        url = f"{host}{path}?{q}&_={int(time.time() * 1000)}"
        txt = _http_get(url, EM_HEADERS, timeout=timeout, retries=retries)
        if txt:
            try:
                obj = json.loads(txt)
                if obj.get("rc") == 0 and obj.get("data"):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def em_get_direct(host, path, params, timeout=None, retries=None):
    if timeout is None:
        timeout = int(os.environ.get("EM_TIMEOUT", "15"))
    if retries is None:
        retries = int(os.environ.get("EM_RETRIES", "3"))
    if "ut" not in params:
        params = {**params, "ut": EM_UT}
    q = urllib.parse.urlencode(params)
    url = f"{host}{path}?{q}&_={int(time.time() * 1000)}"
    txt = _http_get(url, EM_HEADERS, timeout=timeout, retries=retries)
    if not txt:
        return None
    try:
        obj = json.loads(txt)
    except json.JSONDecodeError:
        return None
    if obj.get("rc") == 0 and obj.get("data") is not None:
        return obj
    return None


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if v in ("", "-", "--", "None"):
            return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _diff_list(data):
    d = data.get("diff") if isinstance(data, dict) else None
    if d is None:
        return []
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return [d[k] for k in sorted(d.keys(), key=lambda x: int(x) if x.isdigit() else x)]
    return []


def detect_trade_date():
    txt = _http_get("https://qt.gtimg.cn/q=sh000001", GTIMG_HEADERS, timeout=12, retries=2)
    if txt:
        import re
        m = re.search(r"~(\d{14})~", txt)
        if m:
            d = m.group(1)[:8]
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        d = now - datetime.timedelta(days=(now.weekday() - 4))
        return d.strftime("%Y-%m-%d")
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        d = now - datetime.timedelta(days=1)
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        return d.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


def _pick_amount(r, *fields):
    for f in fields:
        v = _to_float(r.get(f))
        if v is not None and 1e11 <= abs(v) <= 1e13:
            return v
    return None


def fetch_market_snapshot():
    out_idx, out_style = [], []
    sh_amt = sz_amt = None
    src = SOURCE_EM
    secids = ",".join(s for _, s in INDICES) + "," + ",".join(s for _, s in STYLE_INDEX)
    data = em_get("/api/qt/ulist.np/get", {"fields": "f12,f14,f2,f3,f4,f6,f62", "secids": secids})
    if data:
        rows = {r.get("f12"): r for r in _diff_list(data.get("data", {}))}
        for name, sid in INDICES:
            code = sid.split(".")[1]
            r = rows.get(code)
            if r:
                close = _to_float(r.get("f2"))
                pct = _to_float(r.get("f3"))
                chg = _to_float(r.get("f4"))
                out_idx.append({
                    "name": name,
                    "code": code,
                    "close": close / 100 if close is not None else None,
                    "pct": pct / 100 if pct is not None else None,
                    "chg": chg / 100 if chg is not None else None,
                    "main_net_in": _to_float(r.get("f62")),
                    "turnover": _to_float(r.get("f6")),
                    "source": SOURCE_EM,
                })
        for name, sid in STYLE_INDEX:
            code = sid.split(".")[1]
            r = rows.get(code)
            if r:
                close = _to_float(r.get("f2"))
                pct = _to_float(r.get("f3"))
                out_style.append({
                    "name": name,
                    "code": code,
                    "close": close / 100 if close is not None else None,
                    "pct": pct / 100 if pct is not None else None,
                    "source": SOURCE_EM,
                })
        r_sh, r_sz = rows.get("000001"), rows.get("399001")
        if r_sh:
            sh_amt = _pick_amount(r_sh, "f6", "f7", "f8", "f67")
        if r_sz:
            sz_amt = _pick_amount(r_sz, "f6", "f7", "f8", "f67")
    if not out_idx:
        src = SOURCE_GT
        want = {s.split(".")[1]: n for n, s in INDICES}
        codes = ",".join(
            f"sh{c}" if s.startswith("1.") else f"sz{c}"
            for _, s in INDICES
            for c in [s.split(".")[1]]
        )
        txt = _http_get(f"https://qt.gtimg.cn/q={codes}", GTIMG_HEADERS, timeout=15, retries=3)
        if txt:
            for seg in txt.split(";"):
                seg = seg.strip()
                if not seg.startswith("v_"):
                    continue
                name = seg.split("~")[1]
                parts = seg.split("~")
                code = None
                for c, n in want.items():
                    if n == name:
                        code = c
                        break
                if code is None:
                    continue
                out_idx.append({
                    "name": name,
                    "code": code,
                    "close": _to_float(parts[3]),
                    "pct": _to_float(parts[32]),
                    "chg": _to_float(parts[31]),
                    "main_net_in": None,
                    "turnover": None,
                    "source": SOURCE_GT,
                })
    return out_idx, out_style, sh_amt, sz_amt, src


def _load_sw_mapping_from_cache():
    cached = _load_cache("sw_mapping.json")
    if not cached:
        return None
    by_code = cached.get("by_code") or {}
    if not by_code:
        return None
    return cached


def fetch_sw_mapping():
    cached = _load_cache("sw_mapping.json", max_age_hours=STATIC_CACHE_TTL_HOURS)
    if cached and (cached.get("by_code") or {}):
        return cached, "本地缓存"
    cached = _load_sw_mapping_from_cache()
    if cached:
        return cached, "本地缓存"
    by_code = {k: {"code": k, "name": v} for k, v in SW_INDUSTRY.items()}
    cache_payload = {
        "by_code": by_code,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_cache("sw_mapping.json", cache_payload)
    return cache_payload, "内置申万一级常量"


def fetch_sw_index_spot():
    ak = _akshare()
    try:
        df = _paced_call(ak.index_realtime_sw, symbol="一级行业")
    except Exception as e:
        return [], f"AKShare 申万一级指数接口暂不可用: {e}"
    out = []
    for row in df.to_dict("records"):
        code = str(row.get("指数代码") or "").replace(".SI", "").strip()
        if code not in SW_INDUSTRY:
            continue
        prev = _to_float(row.get("昨收盘"))
        close = _to_float(row.get("最新价"))
        pct = None
        if prev not in (None, 0) and close is not None:
            pct = (close - prev) / prev * 100
        out.append({
            "code": code,
            "name": SW_INDUSTRY[code],
            "close": close,
            "pct": pct,
            "source": "AKShare 申万一级指数实时行情",
        })
    return out, ("AKShare 申万一级指数实时行情" if out else "AKShare 申万一级指数接口暂不可用")


def _market_by_code(code):
    if code.startswith(("600", "601", "603", "605", "688", "689")):
        return "sh"
    if code.startswith(("000", "001", "002", "003", "300", "301")):
        return "sz"
    if code.startswith(("430", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879", "880", "920")):
        return "bj"
    return None


def _secid_from_code(code):
    market = _market_by_code(code)
    if market == "sh":
        return f"1.{code}"
    if market in ("sz", "bj"):
        return f"0.{code}"
    return None


def _iter_chunks(items, size):
    if size <= 0:
        size = 200
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _fetch_stock_fundflow_by_secid_batches(stock_codes, indicator="今日"):
    if indicator != "今日":
        return [], "secid 批量资金流当前仅支持今日口径"
    secids = []
    secid_to_code = {}
    for code in sorted({str(x).zfill(6) for x in (stock_codes or []) if x}):
        secid = _secid_from_code(code)
        if not secid:
            continue
        secids.append(secid)
        secid_to_code[secid] = code
    if not secids:
        return [], "申万成分股映射为空，无法做 secid 批量资金流请求"

    rows_by_code = {}
    pending = list(secids)
    batch_plan = [FUND_FLOW_BATCH_SIZE]
    if FUND_FLOW_BATCH_SIZE > 80:
        batch_plan.append(80)

    for batch_size in batch_plan:
        if not pending:
            break
        next_pending = []
        for batch in _iter_chunks(pending, batch_size):
            obj = em_get_direct(
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
                retries=2,
            )
            if not obj:
                next_pending.extend(batch)
                continue
            diff = _diff_list((obj.get("data") or {}))
            if not diff:
                next_pending.extend(batch)
                continue
            seen_codes = set()
            for r in diff:
                code = str(r.get("f12") or "").zfill(6)
                if not code:
                    continue
                seen_codes.add(code)
                pct_raw = _to_float(r.get("f3"))
                rows_by_code[code] = {
                    "code": code,
                    "name": r.get("f14"),
                    "market": _market_by_code(code),
                    "pct": pct_raw / 100 if pct_raw is not None else None,
                    "main_net_in": _to_float(r.get("f62")),
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


def _fetch_stock_fundflow_rank_em_fallback(indicator="今日"):
    indicator_map = {
        "今日": [
            "f62",
            "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f204,f205,f124",
            "f3",
            "f62",
        ],
        "3日": [
            "f267",
            "f12,f14,f2,f127,f267,f268,f269,f270,f271,f272,f273,f274,f275,f276,f257,f258,f124",
            "f127",
            "f267",
        ],
        "5日": [
            "f164",
            "f12,f14,f2,f109,f164,f165,f166,f167,f168,f169,f170,f171,f172,f173,f257,f258,f124",
            "f109",
            "f164",
        ],
        "10日": [
            "f174",
            "f12,f14,f2,f160,f174,f175,f176,f177,f178,f179,f180,f181,f182,f183,f260,f261,f124",
            "f160",
            "f174",
        ],
    }
    cfg = indicator_map.get(indicator)
    if not cfg:
        return [], "不支持的 indicator"
    fid, fields, pct_key, net_key = cfg
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
    first = em_get("/api/qt/clist/get", params)
    if not first:
        q = urllib.parse.urlencode(params)
        txt = _http_get(f"{host}/api/qt/clist/get?{q}", EM_HEADERS, timeout=20, retries=2)
        if not txt:
            return [], "东方财富延迟行情主机不可用"
        try:
            first = json.loads(txt)
        except json.JSONDecodeError:
            return [], "东方财富延迟行情主机返回非 JSON"
    total = (((first or {}).get("data") or {}).get("total") or 0)
    rows = []
    total_page = max(1, (int(total) + 99) // 100)
    for page in range(1, total_page + 1):
        params["pn"] = str(page)
        q = urllib.parse.urlencode(params)
        txt = _http_get(f"{host}/api/qt/clist/get?{q}", EM_HEADERS, timeout=20, retries=2)
        if not txt:
            break
        try:
            obj = json.loads(txt)
        except json.JSONDecodeError:
            break
        diff = _diff_list((obj or {}).get("data") or {})
        if not diff:
            break
        for r in diff:
            code = str(r.get("f12") or "").zfill(6)
            market = _market_by_code(code)
            if not market:
                continue
            pct_raw = _to_float(r.get(pct_key))
            rows.append({
                "code": code,
                "name": r.get("f14"),
                "market": market,
                "pct": pct_raw / 100 if pct_raw is not None else None,
                "main_net_in": _to_float(r.get(net_key)),
            })
    return rows, ("东方财富延迟行情主机个股资金流全市场排行" if rows else "东方财富延迟行情主机个股资金流接口暂不可用")


def fetch_all_stock_fundflow_rank(indicator="今日", stock_codes=None):
    if stock_codes:
        rows, batch_src = _fetch_stock_fundflow_by_secid_batches(stock_codes, indicator=indicator)
        if rows:
            return rows, batch_src
    ak = _akshare()
    try:
        df = _paced_call(ak.stock_individual_fund_flow_rank, indicator=indicator)
    except Exception as e:
        rows, fallback_src = _fetch_stock_fundflow_rank_em_fallback(indicator)
        if rows:
            return rows, f"AKShare 失败，已回退到东方财富延迟行情主机: {fallback_src}"
        return [], f"AKShare 个股资金流排行接口暂不可用: {e}"
    prefix = indicator
    rows = []
    pct_col = f"{prefix}涨跌幅"
    net_col = f"{prefix}主力净流入-净额"
    for r in df.to_dict("records"):
        code = str(r.get("代码") or "").zfill(6)
        market = _market_by_code(code)
        if not market:
            continue
        rows.append({
            "code": code,
            "name": r.get("名称"),
            "market": market,
            "pct": _to_float(r.get(pct_col)),
            "main_net_in": _to_float(r.get(net_col)),
        })
    return rows, ("AKShare 个股资金流全市场排行" if rows else "AKShare 个股资金流排行接口暂不可用")


def fetch_sw_stock_map():
    cached = _load_cache("sw_stock_map.json", max_age_hours=STATIC_CACHE_TTL_HOURS)
    if cached and cached.get("stock_to_industry"):
        return cached["stock_to_industry"], "本地缓存"
    ak = _akshare()
    stock_to_industry = {}
    for code in SW_INDUSTRY:
        try:
            df = _paced_call(ak.index_component_sw, symbol=code)
        except Exception:
            continue
        for row in df.to_dict("records"):
            stock_code = str(row.get("证券代码") or "").zfill(6)
            if stock_code:
                stock_to_industry[stock_code] = code
    if not stock_to_industry:
        return {}, "AKShare 申万成分股接口暂不可用"
    payload = {
        "stock_to_industry": stock_to_industry,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _save_cache("sw_stock_map.json", payload)
    return stock_to_industry, "AKShare 申万成分股"


def build_sw_industry(sw_spot, stock_rows, sw_mapping, stock_to_industry):
    sw_map = (sw_mapping or {}).get("by_code") or {k: {"code": k, "name": v} for k, v in SW_INDUSTRY.items()}
    sums = {}
    for row in stock_rows:
        code = row["code"]
        ind_code = stock_to_industry.get(code)
        if ind_code not in sw_map:
            continue
        sums[ind_code] = sums.get(ind_code, 0.0) + (_to_float(row.get("main_net_in")) or 0.0)
    out = []
    for x in sw_spot:
        code = x["code"]
        meta = sw_map.get(code) or {"code": code, "name": x["name"]}
        out.append({
            "code": code,
            "name": meta["name"],
            "close": x.get("close"),
            "pct": x.get("pct"),
            "main_net_in": sums.get(code),
            "source": SOURCE_SW,
        })
    return out


def _fetch_northbound_dc():
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
    txt = _http_get(f"{url}?{urllib.parse.urlencode(params)}", DC_HEADERS, timeout=15, retries=3)
    if not txt:
        return None
    try:
        obj = json.loads(txt)
    except json.JSONDecodeError:
        return None
    rows = (obj.get("result") or {}).get("data") or []
    days = sorted({str(r.get("TRADE_DATE", ""))[:10] for r in rows}, reverse=True)
    if not days:
        return None
    day = days[0]
    by_type = {}
    for r in rows:
        if str(r.get("TRADE_DATE", ""))[:10] == day:
            by_type[str(r.get("MUTUAL_TYPE"))] = r

    def deal(t):
        v = by_type.get(t, {}).get("DEAL_AMT")
        return v * 1e6 if v is not None else None

    sh, sz = deal("001"), deal("002")
    tot = deal("005")
    if tot is None and sh is not None and sz is not None:
        tot = sh + sz
    if sh is None and sz is None and tot is None:
        return None
    return {
        "trade_date": day,
        "sh_connect_turnover": sh,
        "sz_connect_turnover": sz,
        "total_turnover": tot,
        "available": True,
        "source": "东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY（kamt 不可用时的兜底）",
    }


def fetch_northbound(sh_amount, sz_amount):
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
        d = data.get("data") or {}
        klines = d.get("klines") if isinstance(d, dict) else None
        if isinstance(klines, list) and klines:
            last = klines[-1]
            parts = last.split(",") if isinstance(last, str) else []
            flds = fields.split(",")
            rec = {flds[i]: parts[i] for i in range(min(len(flds), len(parts)))}
            tot = _to_float(rec.get("f55")) or _to_float(rec.get("f54"))
            sh = _to_float(rec.get("f59")) or _to_float(rec.get("f58"))
            sz = _to_float(rec.get("f63")) or _to_float(rec.get("f62"))
            if tot is None and sh is not None and sz is not None:
                tot = sh + sz
            t = rec.get("f51")
            if t and len(str(t)) >= 8:
                result["trade_date"] = str(t)[:10]
            if tot is not None or sh is not None or sz is not None:
                result["sh_connect_turnover"] = sh
                result["sz_connect_turnover"] = sz
                result["total_turnover"] = tot
                two_mkt = (_to_float(sh_amount) or 0) + (_to_float(sz_amount) or 0)
                if tot and two_mkt:
                    result["turnover_ratio"] = tot / two_mkt
                result["available"] = True
                return result, SOURCE_EM
    dc = _fetch_northbound_dc()
    if dc:
        result["trade_date"] = dc["trade_date"]
        result["sh_connect_turnover"] = dc["sh_connect_turnover"]
        result["sz_connect_turnover"] = dc["sz_connect_turnover"]
        result["total_turnover"] = dc["total_turnover"]
        two_mkt = (_to_float(sh_amount) or 0) + (_to_float(sz_amount) or 0)
        if dc["total_turnover"] and two_mkt:
            result["turnover_ratio"] = dc["total_turnover"] / two_mkt
        result["available"] = True
        result["source"] = dc["source"]
        return result, dc["source"]
    result["source"] = "东方财富 kamt/数据中心接口均不可用（被限流或未披露；不编造净买入）"
    return result, result["source"]


def compute_style_proxy(sw_list):
    by_code = {x["code"]: x for x in sw_list}
    out = []
    for name, codes in STYLE_PROXY.items():
        pcts = [_to_float(by_code[c]["pct"]) for c in codes if c in by_code and _to_float(by_code[c]["pct"]) is not None]
        if pcts:
            out.append({
                "name": name,
                "pct": sum(pcts) / len(pcts),
                "members": [by_code[c]["name"] for c in codes if c in by_code],
            })
    return out


def fetch_stock_fundflow_top(topn=10, stock_rows=None, stock_source=None):
    rows = list(stock_rows or [])
    if not rows:
        rows, src = fetch_all_stock_fundflow_rank("今日")
    else:
        src = stock_source or "个股资金流"
    rows_in = [x for x in rows if x.get("main_net_in") is not None]
    rows_in.sort(key=lambda x: x["main_net_in"], reverse=True)
    top_in = rows_in[:topn]
    rows_out = [x for x in rows if x.get("main_net_in") is not None]
    rows_out.sort(key=lambda x: x["main_net_in"])
    top_out = rows_out[:topn]
    return top_in, top_out, (src if (top_in or top_out) else "东方财富个股资金流排行接口暂不可用")


def compute_hotspots(sw_list, topn=5):
    valid = [x for x in sw_list if _to_float(x["pct"]) is not None]
    valid.sort(key=lambda x: x["pct"], reverse=True)
    return {
        "hot": valid[:topn],
        "weak": valid[-topn:][::-1],
    }


def yi(v):
    if v is None:
        return "—"
    return round(v / 1e8, 2)


def write_json(path, result):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def write_csv(path, sw_list):
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["代码", "行业", "涨跌幅%", "主力净流入(亿元)"])
        for x in sorted(sw_list, key=lambda z: (z["pct"] if z["pct"] is not None else -99), reverse=True):
            w.writerow([x["code"], x["name"], x["pct"], yi(x["main_net_in"])])


def collect_report_data(data_date=None, topn=10, merge_path=None, verbose=True):
    if data_date is None:
        data_date = detect_trade_date()
    if verbose:
        print(f"[*] 数据日期: {data_date}")

    indices, style_idx, sh_amt, sz_amt, idx_src = fetch_market_snapshot()
    style_src = idx_src
    if verbose:
        print(f"[+] 指数 {len(indices)} 条 + 风格 {len(style_idx)} 条（{idx_src}）")

    sw_mapping, sw_mapping_src = fetch_sw_mapping()
    if verbose:
        print(f"[+] 申万一级映射: {len((sw_mapping or {}).get('by_code', {}))}/31 条（{sw_mapping_src}）")

    stock_to_industry, stock_map_src = fetch_sw_stock_map()
    if verbose:
        print(f"[+] 申万成分股映射: {len(stock_to_industry)} 条股票映射（{stock_map_src}）")

    sw_spot, sw_spot_src = fetch_sw_index_spot()
    if verbose:
        print(f"[+] 申万一级指数: {len(sw_spot)}/31 条（{sw_spot_src}）")

    stock_rows, stock_rows_src = fetch_all_stock_fundflow_rank("今日", stock_codes=stock_to_industry.keys())
    if verbose:
        print(f"[+] 个股资金流全市场: {len(stock_rows)} 条（{stock_rows_src}）")

    sw_list = build_sw_industry(sw_spot, stock_rows, sw_mapping, stock_to_industry)
    sw_src = f"{sw_spot_src} + {stock_rows_src}"
    if verbose:
        print(f"[+] 申万一级行业聚合: {len(sw_list)}/31 条（{sw_src}）")

    nb, nb_src = fetch_northbound(sh_amt, sz_amt)
    if verbose:
        print(f"[+] 北向资金: {'可用' if nb['available'] else '暂不可用'}（{nb_src}）")

    style_proxy = compute_style_proxy(sw_list)
    if verbose:
        print(f"[+] 风格代理: {len(style_proxy)} 条主题（金融防御/医药景气/科技成长/周期资源）")

    top_in, top_out, stock_src = fetch_stock_fundflow_top(topn, stock_rows=stock_rows, stock_source=stock_rows_src)
    if verbose:
        print(f"[+] 个股资金流 TOP: 净流入 {len(top_in)} / 净流出 {len(top_out)} 条（{stock_src}）")

    hotspots = compute_hotspots(sw_list)

    merged = False
    if merge_path and os.path.exists(merge_path):
        with open(merge_path, encoding="utf-8") as f:
            over = json.load(f)
        if over.get("sw_industry") and not sw_list:
            sw_list = over["sw_industry"]
            sw_src = over.get("sw_industry_source", "外部补全（MCP：东方财富妙想/腾讯自选股）")
            merged = True
        if over.get("northbound") and not nb.get("available"):
            nb = {**nb, **over["northbound"]}
            merged = True
        if over.get("stock_top_in"):
            top_in = over["stock_top_in"]
            merged = True
        if over.get("stock_top_out"):
            top_out = over["stock_top_out"]
            merged = True
        if over.get("stock_source"):
            stock_src = over["stock_source"]
        if over.get("style_indices"):
            style_idx = over["style_indices"]
            style_src = over.get("style_indices_source", style_src)
        style_proxy = compute_style_proxy(sw_list)
        hotspots = over.get("hotspots") or compute_hotspots(sw_list)
        if verbose:
            print(f"[+] --merge {merge_path}：补全 申万 {len(sw_list)}/31、北向 {'可用' if nb.get('available') else '无'}、个股TOP {len(top_in)}/{len(top_out)}")

    overall_source = SOURCE_SW if (sw_list or nb["available"] or top_in) else "腾讯gtimg(指数回退)+AKShare/东方财富(受限)"
    if merged:
        overall_source += "（主源受限，部分模块由外部数据补全）"

    return {
        "data_date": data_date,
        "source": overall_source,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note_northbound": "北向净买入自2024-08-19起不再披露，仅取成交额与成交占比，不编造净买入。",
        "indices": indices,
        "sw_industry": sw_list,
        "sw_industry_source": sw_src,
        "northbound": nb,
        "two_market": {"sh": sh_amt, "sz": sz_amt},
        "style_indices": style_idx,
        "style_indices_source": style_src,
        "style_proxy": style_proxy,
        "stock_top_in": top_in,
        "stock_top_out": top_out,
        "stock_source": stock_src,
        "hotspots": hotspots,
        "request_count": REQ_COUNT["n"],
    }


def main():
    ap = argparse.ArgumentParser(description="A股收盘数据生产脚本（输出 JSON / CSV，中间产物写入 build/）")
    ap.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    ap.add_argument("--fmt", default="json", help="输出格式（逗号分隔，可多选）：json / csv（默认 json）")
    ap.add_argument("--out", help="输出目录（默认 <项目根>/build）")
    ap.add_argument("--merge", help="补全数据 JSON（主源被限流时填充缺失模块）")
    ap.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    args = ap.parse_args()

    result = collect_report_data(
        data_date=args.date,
        topn=args.topn,
        merge_path=args.merge,
        verbose=True,
    )

    out_dir = args.out or default_build_dir()
    os.makedirs(out_dir, exist_ok=True)
    fmts = [f.strip().lower() for f in args.fmt.split(",") if f.strip()]
    if not fmts:
        fmts = ["json"]

    base = os.path.join(out_dir, "funflow")
    written = []

    if "json" in fmts:
        json_path = f"{base}.json"
        write_json(json_path, result)
        written.append(f"JSON : {json_path}")
    if "csv" in fmts:
        if result["sw_industry"]:
            csv_path = f"{base}_industry.csv"
            write_csv(csv_path, result["sw_industry"])
            written.append(f"CSV  : {csv_path}")
        else:
            print("[!] CSV 跳过：申万行业数据暂缺（--fmt csv 已指定，但无数据可导出）")

    print(f"\n[✓] 数据产物已写出（{result['data_date']}，目录 {out_dir}）：")
    for w in written:
        print("    " + w)
    print(f"[i] 本次共发起 {REQ_COUNT['n']} 次 HTTP 请求（含失败重试；请求间隔 {REQUEST_DELAY}s）")
    return result


if __name__ == "__main__":
    main()
