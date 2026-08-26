#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股收盘数据获取脚本
====================
数据口径 : 当日收盘后（默认取"最近一个已收盘交易日"；可用 --date YYYY-MM-DD 覆盖）
数据来源 :
  - 主要指数 / 风格指数 / 两市成交额 / 北向成交额：东方财富公开接口，指数回退腾讯 gtimg
  - 申万一级涨跌幅：AKShare -> 申万指数实时行情
  - 申万一级主力净流入：AKShare 申万成分映射 + 东方财富个股资金流按申万一级成分股聚合
重要约定 :
  1. 页面中的"申万一级行业主力净流入"为脚本按个股资金流聚合后的统计值，
     不是东方财富行业页的原始字段，因此不展示东财行业页口径文案。
  2. 北向资金净买入自 2024-08-19 起不再实时披露。本脚本只取【成交额】与【成交占比】，
     绝不编造净买入数字；即便接口返回净买额字段，也统一置 None 并标注"不再披露"。
  3. 长周期静态数据（申万一级映射、申万成分股映射）写入 fundflow/.cache/，
     默认缓存 180 天并随仓库提交，避免 CI 每次全量回源。
  4. 个股资金流优先按申万成分股 secid 分批请求，行业聚合与个股 TOP 共享同一批数据，
     默认批大小 400，减少全市场分页请求和风控风险。
输出格式 : 默认仅 HTML 网页报告；可用 --fmt 选择 json / md / csv / html（逗号分隔，可多选）
          所有产物写入 <项目根>/build/ 目录，文件名固定（无日期），每天运行覆盖前一天。
依赖     : Python 标准库 + AKShare（见 requirements.txt）。
用法     :
  python3 ashare_close_fetcher.py                            # 取最近交易日，默认仅输出 HTML -> build/ashare_close.html
  python3 ashare_close_fetcher.py --date 2026-08-25          # 指定数据日期
  python3 ashare_close_fetcher.py --fmt json,md,html         # 同时输出 JSON + Markdown + HTML
  python3 ashare_close_fetcher.py --fmt csv --out /tmp/x     # 仅申万行业 CSV，自定义目录
注意     : 在 WorkBuddy 自动化沙箱内，部分公开接口可能被出口代理拦截；
           此时脚本会尽量回退，并在申万/北向/资金流模块标注"接口暂不可用"。
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
# 东方财富行情主机：push2 为完整源（申万 90. 指数、kamt 仅此可用）；
# push2delay 为延迟行情主机，对本机 IP 更宽容（指数/个股/两市额可用，但不含申万与 kamt）。
# 2026-08-25 实测：push2 系列曾被 EM WAF 对本 IP 限流（http 000/空应答），push2delay 仍可用，
# 故把 delay 放在第二顺位作降级。
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
# 东方财富行情接口统一令牌（部分端点需要）
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"
# 数据中心 datacenter-web（报表接口，对 push2 被限流的场景作兜底；北向成交即出自此）
DC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
    "Referer": "https://data.eastmoney.com/",
    "Accept": "*/*",
}
GTIMG_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://gu.qq.com/",
}
# 主要指数 secid（东方财富格式：1=上交所 0=深交所；中证指数用 1. 前缀）
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

# 申万一级行业（31 个，2021 版）code -> 名称
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

# 国证风格指数 secid（用于"规模×价值/成长"维度）
STYLE_INDEX = [
    ("大盘成长", "0.399372"), ("大盘价值", "0.399373"),
    ("中盘成长", "0.399374"), ("中盘价值", "0.399375"),
    ("小盘成长", "0.399376"), ("小盘价值", "0.399377"),
]

# 风格主题代理（由申万行业涨跌幅聚合，复用已取数据，免额外请求）
STYLE_PROXY = {
    "金融防御": ["801780", "801790"],
    "医药景气": ["801150"],
    "科技成长": ["801080", "801750", "801770", "801760", "801730"],
    "周期资源": ["801050", "801040", "801950", "801960", "801030", "801710", "801720", "801890", "801740", "801880", "801170"],
}

SOURCE_EM = "东方财富 East Money 公开行情接口（与证券时报·数据宝同源）"
SOURCE_GT = "腾讯财经 gtimg 接口（回退源）"
SOURCE_SW = "AKShare 申万一级指数 + 东方财富个股资金流聚合"


# ---------------------------------------------------------------------------
# 通用抓取
# ---------------------------------------------------------------------------
# 请求计数（用于统计本次运行的总请求量）
REQ_COUNT = {"n": 0}
# 每次 HTTP 请求前主动延迟（秒），避免短时间密集请求触发数据源限流；
# 可用环境变量 REQ_DELAY 调整（0 关闭，如 REQ_DELAY=0.6）
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
    last_err = None
    REQ_COUNT["n"] += 1
    if REQUEST_DELAY > 0:
        time.sleep(REQUEST_DELAY)  # 主动限速，分散请求
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                # 东方财富为 UTF-8；腾讯 gtimg 为 GBK
                for enc in ("utf-8", "gbk"):
                    try:
                        return raw.decode(enc)
                    except UnicodeDecodeError:
                        continue
                return raw.decode("utf-8", "ignore")
        except (urllib.error.URLError, urllib.error.HTTPError, ConnectionError, TimeoutError) as e:
            last_err = e
            time.sleep(backoff * (i + 1))
    return None


def em_get(path, params, timeout=None, retries=None):
    """东方财富接口：依次尝试多个 host，返回解析后的 dict 或 None（失败）。

    可通过环境变量调优（便于在受限网络下快速失败）：
      EM_TIMEOUT  单请求超时秒数（默认 15）
      EM_RETRIES  重试次数（默认 3）
    """
    if timeout is None:
        timeout = int(os.environ.get("EM_TIMEOUT", "15"))
    if retries is None:
        retries = int(os.environ.get("EM_RETRIES", "3"))
    # 部分行情端点需要 ut 令牌，未显式提供时自动补上
    if "ut" not in params:
        params = {**params, "ut": EM_UT}
    q = urllib.parse.urlencode(params)
    for host in EM_HOSTS:
        url = f"{host}{path}?{q}&_={int(time.time()*1000)}"
        txt = _http_get(url, EM_HEADERS, timeout=timeout, retries=retries)
        if txt:
            try:
                obj = json.loads(txt)
                if obj.get("rc") == 0 and obj.get("data"):
                    return obj
            except json.JSONDecodeError:
                continue
    return None


def dc_get(params, timeout=None, retries=None):
    if timeout is None:
        timeout = int(os.environ.get("EM_TIMEOUT", "15"))
    if retries is None:
        retries = int(os.environ.get("EM_RETRIES", "3"))
    base = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    url = f"{base}?{urllib.parse.urlencode(params)}"
    txt = _http_get(url, DC_HEADERS, timeout=timeout, retries=retries)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def em_get_direct(host, path, params, timeout=None, retries=None):
    """直接请求指定东财 host，避免在已知稳定的延迟主机上额外探测其他域名。"""
    if timeout is None:
        timeout = int(os.environ.get("EM_TIMEOUT", "15"))
    if retries is None:
        retries = int(os.environ.get("EM_RETRIES", "3"))
    if "ut" not in params:
        params = {**params, "ut": EM_UT}
    q = urllib.parse.urlencode(params)
    url = f"{host}{path}?{q}&_={int(time.time()*1000)}"
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
    """clist/ulist 的 diff 可能是 list 或 {idx:row} 字典，统一成 list。"""
    d = data.get("diff") if isinstance(data, dict) else None
    if d is None:
        return []
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        return [d[k] for k in sorted(d.keys(), key=lambda x: int(x) if x.isdigit() else x)]
    return []


# ---------------------------------------------------------------------------
# 交易日判定
# ---------------------------------------------------------------------------
def detect_trade_date():
    """优先用腾讯 gtimg 上证指数返回的真实行情日期；失败则按日历推算。"""
    # 1) 腾讯 gtimg 实时/收盘日期
    txt = _http_get("https://qt.gtimg.cn/q=sh000001", GTIMG_HEADERS, timeout=12, retries=2)
    if txt:
        # v_sh000001="...~YYYYMMDDHHMMSS~..."
        import re
        m = re.search(r"~(\d{14})~", txt)
        if m:
            d = m.group(1)[:8]
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    # 2) 日历推算：跳过周末；若当前为工作日且未到 15:30，则取上一交易日
    now = datetime.datetime.now()
    if now.weekday() >= 5:  # 周六/日
        d = now - datetime.timedelta(days=(now.weekday() - 4))
        return d.strftime("%Y-%m-%d")
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        d = now - datetime.timedelta(days=1)
        while d.weekday() >= 5:
            d -= datetime.timedelta(days=1)
        return d.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 1) 主要指数
# ---------------------------------------------------------------------------
def _pick_amount(r, *fields):
    """从多个字段中挑出量级在 1e11~1e13（元，即百亿~万亿）的成交额字段。"""
    for f in fields:
        v = _to_float(r.get(f))
        if v is not None and 1e11 <= abs(v) <= 1e13:
            return v
    return None


def fetch_market_snapshot():
    """合并抓取：主要指数 + 国证风格指数 + 两市成交额（一次 ulist 请求，减少请求量）。

    返回 (indices, style_indices, 沪市成交额, 深市成交额, 来源)。
    沪市成交额取上证指数 f6，深市成交额取深证成指 f6（量级校验，回退 f7/f8/f67）。
    EM 整体不可用时回退腾讯 gtimg（仅指数报价）。"""
    out_idx, out_style = [], []
    sh_amt = sz_amt = None
    src = SOURCE_EM
    secids = ",".join(s for _, s in INDICES) + "," + ",".join(s for _, s in STYLE_INDEX)
    data = em_get("/api/qt/ulist.np/get",
                  {"fields": "f12,f14,f2,f3,f4,f6,f62", "secids": secids})
    if data:
        rows = {r.get("f12"): r for r in _diff_list(data.get("data", {}))}
        for name, sid in INDICES:
            code = sid.split(".")[1]
            r = rows.get(code)
            if r:
                out_idx.append({
                    "name": name, "code": code,
                    "close": _to_float(r.get("f2")) / 100 if _to_float(r.get("f2")) is not None else None,
                    "pct": _to_float(r.get("f3")) / 100 if _to_float(r.get("f3")) is not None else None,
                    "chg": _to_float(r.get("f4")) / 100 if _to_float(r.get("f4")) is not None else None,
                    "main_net_in": _to_float(r.get("f62")),  # 元
                    "turnover": _to_float(r.get("f6")),       # 元（成交额）
                    "source": SOURCE_EM,
                })
        for name, sid in STYLE_INDEX:
            code = sid.split(".")[1]
            r = rows.get(code)
            if r:
                out_style.append({
                    "name": name, "code": code,
                    "close": _to_float(r.get("f2")) / 100 if _to_float(r.get("f2")) is not None else None,
                    "pct": _to_float(r.get("f3")) / 100 if _to_float(r.get("f3")) is not None else None,
                    "source": SOURCE_EM,
                })
        r_sh, r_sz = rows.get("000001"), rows.get("399001")
        if r_sh:
            sh_amt = _pick_amount(r_sh, "f6", "f7", "f8", "f67")
        if r_sz:
            sz_amt = _pick_amount(r_sz, "f6", "f7", "f8", "f67")
    # 回退：腾讯 gtimg（仅指数报价，无主力净流入/风格/两市额）
    if not out_idx:
        src = SOURCE_GT
        want = {s.split(".")[1]: n for n, s in INDICES}
        codes = ",".join(f"sh{c}" if s.startswith("1.") else f"sz{c}" for _, s in INDICES for c in [s.split(".")[1]])
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
                if code is None:
                    continue
                out_idx.append({
                    "name": name, "code": code,
                    "close": _to_float(parts[3]),
                    "pct": _to_float(parts[32]),
                    "chg": _to_float(parts[31]),
                    "main_net_in": None,
                    "turnover": None,   # gtimg 回退源不取成交额
                    "source": SOURCE_GT,
                })
    return out_idx, out_style, sh_amt, sz_amt, src


# ---------------------------------------------------------------------------
# 2) 申万一级行业：指数涨跌幅 + 个股资金流聚合
#    涨跌幅来自申万一级指数公开页；主力净流入来自东方财富全市场个股资金流按申万一级映射聚合。
# ---------------------------------------------------------------------------
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
    """按 secid 批量请求个股涨跌幅和主力净流入。

    这里直接复用已缓存的申万成分股映射，只请求实际需要聚合的股票，
    避免对全市场排行做分页扫描。
    """
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

    fields = "f12,f14,f2,f3,f62"
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
                    "fields": fields,
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


def fetch_sw_stock_map():
    cached = _load_cache("sw_stock_map.json", max_age_hours=STATIC_CACHE_TTL_HOURS)
    if cached and cached.get("stock_to_industry"):
        return cached["stock_to_industry"], "本地缓存"
    ak = _akshare()
    stock_to_industry = {}
    for code, name in SW_INDUSTRY.items():
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


# ---------------------------------------------------------------------------
# 3) 北向资金：成交额 + 成交占比（不取净买入）
#    kamt 接口返回 data.klines：按分钟、逗号分隔的字符串数组；最后一条=收盘。
#    字段顺序对应请求的 fields。以下映射取"人民币口径"成交额：
#      f55=北向合计成交额(人民币)  f59=沪股通成交额(人民币)  f63=深股通成交额(人民币)
#      (对应的 f54/f58/f62 为港币口径，作回退)
#    净买入：自 2024-08-19 起不再披露，本脚本一律置 None，绝不编造。
# ---------------------------------------------------------------------------
def _fetch_northbound_dc():
    """东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY：沪/深股通与北向合计成交额。
    MUTUAL_TYPE：001=沪股通 002=深股通 003/004=港股通(沪/深) 005=北向合计 006=港股通合计
    DEAL_AMT 单位：百万元 -> 元（×1e6）。kamt 被限流/不可用时的兜底源。"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {"reportName": "RPT_MUTUAL_DEAL_HISTORY", "columns": "ALL", "pageSize": "30",
              "sortColumns": "TRADE_DATE,MUTUAL_TYPE", "sortTypes": "-1,1",
              "source": "WEB", "client": "WEB"}
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
    return {"trade_date": day, "sh_connect_turnover": sh, "sz_connect_turnover": sz,
            "total_turnover": tot, "available": True,
            "source": "东方财富数据中心 RPT_MUTUAL_DEAL_HISTORY（kamt 不可用时的兜底）"}


def fetch_northbound(sh_amount, sz_amount):
    result = {
        "trade_date": None,
        "sh_connect_turnover": None,   # 沪股通成交额（元）
        "sz_connect_turnover": None,   # 深股通成交额（元）
        "total_turnover": None,        # 北向合计成交额（元）
        "turnover_ratio": None,        # 占两市成交比
        "net_buy": None,               # 净买入：自2024-08起不再披露
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
            # 成交额：优先人民币口径(f55/f59/f63)，回退港币口径(f54/f58/f62)
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
    # 兜底：kamt 不可用（被限流等）时改走数据中心 RPT_MUTUAL_DEAL_HISTORY
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


# ---------------------------------------------------------------------------
# 4) 风格指数（国证风格 + 主题代理）
# ---------------------------------------------------------------------------
def compute_style_proxy(sw_list):
    """由申万行业涨跌幅聚合出 金融防御/医药景气/科技成长/周期资源 主题代理。"""
    by_code = {x["code"]: x for x in sw_list}
    out = []
    for name, codes in STYLE_PROXY.items():
        pcts = [_to_float(by_code[c]["pct"]) for c in codes if c in by_code and _to_float(by_code[c]["pct"]) is not None]
        if pcts:
            out.append({"name": name, "pct": sum(pcts) / len(pcts), "members": [by_code[c]["name"] for c in codes if c in by_code]})
    return out


# ---------------------------------------------------------------------------
# 5) 个股资金流 TOP（净流入/净流出）
#    直接复用 AKShare 的全市场排行结果，避免额外请求。
# ---------------------------------------------------------------------------
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
        "hot": valid[:topn],                  # 涨幅居前 = 今日热点
        "weak": valid[-topn:][::-1],           # 跌幅居前 = 今日异动（弱势）
    }


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def yi(v):
    """元 -> 亿元（字符串，保留2位）；None/缺失返回 '—'。"""
    if v is None:
        return "—"
    return round(v / 1e8, 2)


def _fmt(v, nd=2):
    """通用单元格格式化：None -> '—'，否则保留 nd 位。"""
    if v is None:
        return "—"
    if isinstance(v, float):
        return round(v, nd)
    return v


def write_markdown(path, result):
    d = result["data_date"]
    src = result["source"]
    L = []
    L.append(f"# A股收盘数据快照（{d}）\n")
    L.append(f"> 数据口径：当日收盘后 ｜ 数据来源：{src} ｜ 生成时间：{result['generated_at']}\n")
    L.append("## 一、主要指数\n")
    L.append("| 指数 | 收盘 | 涨跌幅% | 涨跌点 | 主力净流入(亿) | 来源 |")
    L.append("|---|---|---|---|---|---|")
    for x in result["indices"]:
        L.append(f"| {x['name']} | {_fmt(x['close'])} | {_fmt(x['pct'])} | {_fmt(x['chg'])} | {yi(x['main_net_in'])} | {x['source']} |")
    L.append("\n## 二、申万一级行业（31）涨跌幅 & 主力净流入\n")
    if result["sw_industry"]:
        L.append("| 代码 | 行业 | 涨跌幅% | 主力净流入(亿) |")
        L.append("|---|---|---|---|")
        for x in sorted(result["sw_industry"], key=lambda z: (z['pct'] if z['pct'] is not None else -99), reverse=True):
            L.append(f"| {x['code']} | {x['name']} | {_fmt(x['pct'])} | {yi(x['main_net_in'])} |")
    else:
        L.append(f"_（{result['sw_industry_source']}）_")
    L.append("\n## 三、北向资金（仅成交额/占比，净买入不披露）\n")
    nb = result["northbound"]
    if nb.get("available"):
        L.append(f"- 沪股通成交额：{yi(nb['sh_connect_turnover'])} 亿元")
        L.append(f"- 深股通成交额：{yi(nb['sz_connect_turnover'])} 亿元")
        L.append(f"- 北向合计成交额：{yi(nb['total_turnover'])} 亿元")
        L.append(f"- 成交占比（占两市）：{round(nb['turnover_ratio']*100,2) if nb['turnover_ratio'] else None} %")
    else:
        L.append(f"_（{nb['source']}）_")
    L.append(f"- 净买入：{nb['net_buy_note']}")
    L.append("\n## 四、风格指数\n")
    L.append("### 国证风格（规模×价值/成长）\n")
    if result["style_indices"]:
        L.append("| 风格 | 收盘 | 涨跌幅% |")
        L.append("|---|---|---|")
        for x in result["style_indices"]:
            L.append(f"| {x['name']} | {_fmt(x['close'])} | {_fmt(x['pct'])} |")
    else:
        L.append(f"_（{result['style_indices_source']}）_")
    L.append("\n### 主题代理（由申万行业聚合）\n")
    if result["style_proxy"]:
        L.append("| 主题 | 涨跌幅% | 组成 |")
        L.append("|---|---|---|")
        for x in result["style_proxy"]:
            L.append(f"| {x['name']} | {round(x['pct'],2)} | {'/'.join(x['members'])} |")
    L.append("\n## 五、资金流 TOP & 热点异动\n")
    L.append("### 行业热点（涨幅前5）/ 异动（跌幅前5）\n")
    hs = result["hotspots"]
    L.append("**热点：** " + "、".join(f"{x['name']}({x['pct']}%)" for x in hs["hot"]) if hs["hot"] else "_无_")
    L.append("\n**异动(弱势)：** " + "、".join(f"{x['name']}({x['pct']}%)" for x in hs["weak"]) if hs["weak"] else "_无_")
    L.append("\n### 个股主力净流入 TOP\n")
    if result["stock_top_in"]:
        L.append("| 代码 | 名称 | 涨跌幅% | 主力净流入(亿) |")
        L.append("|---|---|---|---|")
        for x in result["stock_top_in"]:
            L.append(f"| {x['code']} | {x['name']} | {_fmt(x['pct'])} | {yi(x['main_net_in'])} |")
    else:
        L.append(f"_（{result['stock_source']}）_")
    L.append("\n### 个股主力净流出 TOP\n")
    if result["stock_top_out"]:
        L.append("| 代码 | 名称 | 涨跌幅% | 主力净流入(亿) |")
        L.append("|---|---|---|---|")
        for x in result["stock_top_out"]:
            L.append(f"| {x['code']} | {x['name']} | {_fmt(x['pct'])} | {yi(x['main_net_in'])} |")
    else:
        L.append(f"_（{result['stock_source']}）_")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def write_csv(path, sw_list):
    import csv
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["代码", "行业", "涨跌幅%", "主力净流入(亿元)"])
        for x in sorted(sw_list, key=lambda z: (z['pct'] if z['pct'] is not None else -99), reverse=True):
            w.writerow([x["code"], x["name"], x["pct"], yi(x["main_net_in"])])


# ---------------------------------------------------------------------------
# 6) 静态 HTML 网页报告（纯 HTML/CSS，无 JS —— 兼容移动端 Safari）
#    由 py 的 result 直接渲染，数据内联进 HTML 标签；CSS 内联自 report.css。
#    跑一次 py 即同时产出 JSON / MD / CSV / HTML，刷新 html 即看最新。
# ---------------------------------------------------------------------------
_WEEK = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

def _weekday_cn(date_str):
    try:
        return _WEEK[datetime.datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except Exception:
        return ""

def idx_prefix(code):
    if code.startswith("399"):
        return "SZ"
    if code.startswith("932"):
        return "CSI"
    if code.startswith("899"):
        return "BJ"
    return "SH"

def h_cls(v):
    if v is None:
        return "flat"
    return "up" if v > 0 else ("down" if v < 0 else "flat")

def h_pct(v):
    if v is None:
        return ("—", "flat")
    if v > 0:
        return (f"▲ +{v:.2f}%", "up")
    if v < 0:
        return (f"▼ {v:.2f}%", "down")
    return ("— 0.00%", "flat")

def h_yi(v):
    return None if v is None else v / 1e8

def h_yi_signed(v):
    if v is None:
        return "—"
    y = v / 1e8
    return f"+{y:.2f}" if y >= 0 else f"{y:.2f}"

def h_amount(v):
    if v is None:
        return "—"
    a = abs(v)
    if a >= 1e12:
        return f"{v/1e12:.3f}万亿"
    if a >= 1e8:
        return f"{v/1e8:.0f}亿"
    if a >= 1e4:
        return f"{v/1e4:.0f}万"
    return f"{v:.0f}"

def heat_bg(pct):
    if pct is None:
        return "background:rgba(255,255,255,.03)"
    mag = min(abs(pct), 4.0) / 4.0
    a = 0.14 + 0.62 * mag
    if pct >= 0:
        return f"background:linear-gradient(135deg,rgba(246,70,93,{a:.2f}),rgba(246,70,93,{a*0.55:.2f}))"
    return f"background:linear-gradient(135deg,rgba(14,203,129,{a:.2f}),rgba(14,203,129,{a*0.55:.2f}))"

def _load_css(script_dir):
    p = os.path.join(script_dir, "report.css")
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def _panel(title, tag, body):
    return (f'  <div class="panel sec-gap">\n'
            f'    <div class="p-title"><span class="bar"></span>{title}\n'
            f'      <span class="tag">{tag}</span>\n'
            f'    </div>\n{body}  </div>\n')

def _empty_body(msg):
    return (f'    <div class="style-note" style="border-left-color:var(--txt3)">'
            f'<b style="color:var(--txt2)">⚠ 数据暂缺</b> ｜ {msg}</div>\n')

def write_html(path, result):
    d = result["data_date"]
    wd = _weekday_cn(d)
    css = _load_css(os.path.dirname(os.path.abspath(__file__)))
    S = []
    S.append(f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
             f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
             f'<title>A股收盘 · 资金流向监控 · {d}</title>\n<style>\n{css}\n</style>\n'
             f'</head>\n<body>\n<div class="wrap">\n')

    # ===== HEADER =====
    S.append(f'''  <div class="hdr">
    <div class="hdr-l">
      <div class="logo"><svg viewBox="0 0 24 24" fill="none"><path d="M4 17l5-6 4 3 7-9" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/><path d="M15 5h5v5" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
      <div>
        <h1>A股收盘 · <em>资金流向监控</em></h1>
        <div class="sub">CLOSE SNAPSHOT · CAPITAL FLOW · STYLE RADAR · NORTHBOUND</div>
      </div>
    </div>
    <div class="hdr-r">
      <span class="live-badge"><span class="dot"></span>数据日期 {d}（{wd}）· 收盘</span>
      <div class="src-line">生成于 <b>{result["generated_at"]}</b> ｜ 来源：{result["source"]}</div>
    </div>
  </div>
''')

    # ===== 1. 主要指数 =====
    idx_rows = []
    for x in result["indices"]:
        pct_s, cls = h_pct(x["pct"])
        prev = (x["close"] - x["chg"]) if (x["close"] is not None and x["chg"] is not None) else None
        close_s = f'{x["close"]:,.2f}' if x["close"] is not None else "—"
        prev_s = f'{prev:,.2f}' if prev is not None else "—"
        chg_s = f'{x["chg"]:+,.2f}' if x["chg"] is not None else "—"
        amt_s = h_amount(x.get("turnover"))
        idx_rows.append(
            f'      <tr>\n'
            f'        <td>{x["name"]}<span class="code">{idx_prefix(x["code"])}{x["code"]}</span></td>\n'
            f'        <td style="color:var(--txt);font-weight:700">{close_s}</td>\n'
            f'        <td class="{cls}">{pct_s}</td>\n'
            f'        <td class="{cls}">{chg_s}</td>\n'
            f'        <td style="color:var(--txt3)">{prev_s}</td>\n'
            f'        <td style="color:var(--txt2)">{amt_s}</td>\n'
            f'      </tr>')
    if idx_rows:
        body = ('    <table class="idx-table">\n      <thead>\n'
                '        <tr><th>指数</th><th>收盘点位</th><th>涨跌幅</th><th>涨跌点</th><th>昨收</th><th>成交额</th></tr>\n'
                '      </thead>\n      <tbody>\n' + "\n".join(idx_rows) +
                '\n      </tbody>\n    </table>\n')
    else:
        body = _empty_body("主要指数数据暂不可用，请在本机运行 py。")
    S.append(_panel("主要指数收盘点位 MARKET INDICES", f"{d} 收盘 · 涨红跌绿", body))

    # ===== 2. 核心 KPI + 资金主线 =====
    idx_by_name = {x["name"]: x for x in result["indices"]}
    def kpi(name, code, val, val_cls, chg, chg_cls, sub, glow=None):
        glow_c = f'<div class="glow-{glow}"></div>' if glow else ''
        cd = f'<span class="k-code">{code}</span>' if code else ''
        return (f'      <div class="kpi">\n'
                f'        <div class="k-name">{name} {cd}</div>\n'
                f'        <div class="k-val {val_cls}">{val}</div>\n'
                f'        <div class="k-chg {chg_cls}">{chg}</div>\n'
                f'        <div class="k-sub">{sub}</div>\n        {glow_c}</div>')
    kpis = []
    for nm, pref, glow in (("上证指数", "SH000001", "up"), ("深证成指", "SZ399001", "dn"),
                           ("创业板指", "SZ399006", "dn"), ("科创50", "SH000688", "up")):
        x = idx_by_name.get(nm)
        if x and x["close"] is not None:
            pct_s, cls = h_pct(x["pct"])
            prev = (x["close"] - x["chg"]) if x["chg"] is not None else None
            sub = f'{prev:,.2f}→{x["close"]:,.2f}' if prev is not None else "—"
            kpis.append(kpi(nm, pref, f'{x["close"]:,.2f}', cls, pct_s, cls, sub, glow))
    # 两市成交额
    tm = result.get("two_market") or {}
    sh, sz = tm.get("sh"), tm.get("sz")
    if sh is not None or sz is not None:
        tot = (sh or 0) + (sz or 0)
        kpis.append(kpi("两市成交额", "", h_amount(tot), "cyan",
                        f'沪 {h_amount(sh)} · 深 {h_amount(sz)}', "cyan", "收盘口径", "cy"))
    # 北向成交占比
    nb = result["northbound"]
    if nb.get("turnover_ratio"):
        kpis.append(kpi("北向成交占比", "", f'{nb["turnover_ratio"]*100:.1f}%', "cyan",
                        "净买入未披露", "flat", "通道成交额口径", "cy"))
    # 申万主力净流入汇总
    sw = result["sw_industry"]
    net_vals = [x["main_net_in"] for x in sw if x.get("main_net_in") is not None]
    if net_vals:
        s = sum(net_vals) / 1e8
        cls = "up" if s >= 0 else "down"
        kpis.append(kpi("申万主力净流入", "", f'{s:+.1f}亿', cls, "31行业汇总", cls,
                        "涨红/跌绿口径", "up" if s >= 0 else "dn"))
    # 涨跌行业数
    if sw:
        up_n = sum(1 for x in sw if (x.get("pct") or 0) > 0)
        dn_n = sum(1 for x in sw if (x.get("pct") or 0) < 0)
        kpis.append(kpi("涨跌行业数", "", f'{up_n}↑ / {dn_n}↓', "up",
                        f'共 {len(sw)} 个行业', "flat", "涨多/跌少", "up"))
    kpi_html = '    <div class="kpis">\n' + "\n".join(kpis) + "\n    </div>\n" if kpis else _empty_body("市场 KPI 数据暂缺。")
    # 资金主线
    if sw:
        ins = sorted([x for x in sw if x.get("main_net_in")], key=lambda z: z["main_net_in"], reverse=True)[:2]
        outs = sorted([x for x in sw if x.get("main_net_in")], key=lambda z: z["main_net_in"])[:2]
        in_tx = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in ins) or "—"
        out_tx = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in outs) or "—"
        ml = (f'    <div class="mainline"><div class="ml-label">\n'
              f'      <svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4.5 13.5H11L9.5 22 19 9.5h-6.5L13 2z" fill="var(--cyan)" opacity=".85"/></svg>\n      今日资金主线\n'
              f'    </div><div class="ml-item"><span class="dot" style="background:var(--up);box-shadow:0 0 8px var(--up)"></span><b class="up">主力净流入居前</b> {in_tx}</div>'
              f'<div class="ml-item"><span class="dot" style="background:var(--down);box-shadow:0 0 8px var(--down)"></span><b class="down">主力净流出居前</b> {out_tx}</div></div>\n')
    else:
        ml = ('    <div class="mainline"><div class="ml-label">\n'
              '      <svg viewBox="0 0 24 24" fill="none"><path d="M13 2L4.5 13.5H11L9.5 22 19 9.5h-6.5L13 2z" fill="var(--cyan)" opacity=".85"/></svg>\n      今日资金主线\n'
              '    </div><div class="ml-item"><span class="arrow">申万行业数据暂缺（沙箱出口受限/接口未披露），在本机运行 py 即可填充资金主线。</span></div></div>\n')
    S.append(_panel("核心市场 KPI", "收盘口径", kpi_html + ml))

    # ===== 3. 全市场主力资金分布 =====
    if sw:
        in_sum = sum(h_yi(x["main_net_in"]) for x in sw if x.get("main_net_in") and x["main_net_in"] > 0)
        out_sum = sum(h_yi(x["main_net_in"]) for x in sw if x.get("main_net_in") and x["main_net_in"] < 0)
        tot_m = in_sum + abs(out_sum)
        in_p = in_sum / tot_m * 100 if tot_m else 0
        out_p = abs(out_sum) / tot_m * 100 if tot_m else 0
        in_top = sorted([x for x in sw if x.get("main_net_in") and x["main_net_in"] > 0],
                        key=lambda z: z["main_net_in"], reverse=True)[:6]
        out_top = sorted([x for x in sw if x.get("main_net_in") and x["main_net_in"] < 0],
                         key=lambda z: z["main_net_in"])[:6]
        in_nm = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in in_top) or "—"
        out_nm = "、".join(f'{x["name"]} {h_yi_signed(x["main_net_in"])}亿' for x in out_top) or "—"
        body = (f'    <div class="dist">\n    <div class="dist-bar">\n'
                f'      <div class="seg" style="width:{out_p:.1f}%;background:linear-gradient(90deg,rgba(14,203,129,.55),rgba(14,203,129,.9))" title="流出行业合计 {out_sum:.1f}亿">流出 {out_sum:.1f}亿</div>\n'
                f'      <div class="seg" style="width:{in_p:.1f}%;background:linear-gradient(90deg,rgba(246,70,93,.6),rgba(246,70,93,.95))" title="流入行业合计 {in_sum:.1f}亿">流入 {in_sum:.1f}亿</div>\n'
                f'    </div>\n    <div class="dist-legend"><div class="it"><span class="sw" style="background:rgba(246,70,93,.9)"></span>{in_nm}</div>'
                f'<div class="it"><span class="sw" style="background:rgba(14,203,129,.9)"></span>{out_nm}</div></div></div>\n')
    else:
        body = _empty_body("申万行业数据暂缺，无法汇总主力资金分布。")
    S.append(_panel("全市场主力资金分布 MAIN CAPITAL DISTRIBUTION",
                    "按申万31行业主力净额汇总", body))

    # ===== 4. 申万行业热力图 + 资金流条形 =====
    if sw:
        cells = []
        for x in sorted(sw, key=lambda z: (z.get("pct") or 0), reverse=True):
            pct_s, _ = h_pct(x["pct"])
            cells.append(
                f'      <div class="hcell" style="{heat_bg(x["pct"])}">\n'
                f'        <div class="hn">{x["name"]}</div>\n'
                f'        <div class="hp">{x["pct"]:+.2f}%</div>\n'
                f'        <div class="hf">主力 {h_yi_signed(x["main_net_in"])}亿</div>\n'
                f'      </div>')
        heat = '    <div class="heat">\n' + "\n".join(cells) + "\n    </div>\n"
        # 资金流条形 TOP12（按 |净额|）
        top = sorted([x for x in sw if x.get("main_net_in") is not None],
                     key=lambda z: abs(z["main_net_in"]), reverse=True)[:12]
        maxv = max(abs(x["main_net_in"]) for x in top) if top else 1
        rows = []
        for x in top:
            v = x["main_net_in"]
            w = (abs(h_yi(v)) / h_yi(maxv) * 46) if maxv else 0
            if v >= 0:
                bar = f'<div class="bar in" style="width:{w:.1f}%"><span class="v">+{h_yi(v):.1f}亿</span></div>'
            else:
                bar = f'<div class="bar out" style="width:{w:.1f}%"><span class="v">{h_yi(v):.1f}亿</span></div>'
            rows.append(f'      <div class="flow-row"><div class="fn">{x["name"]}</div><div class="fb">{bar}</div><div class="fn"></div></div>')
        flow = ('    <div class="p-title" style="margin-top:14px;margin-bottom:8px"><span class="bar"></span>行业主力净流入 TOP（红=净流入 / 绿=净流出）</div>\n'
                '    <div class="flow-wrap"><div class="flow-axis"></div>\n' + "\n".join(rows) + "\n    </div>\n")
        body = heat + flow
    else:
        body = _empty_body("申万行业数据暂缺，无法绘制热力图与资金流条形。")
    S.append(_panel("申万一级行业 · 涨跌热力图 & 资金流", "31 行业 · 涨红跌绿", body))

    # ===== 4.5 个股资金流 TOP =====
    ti, to = result["stock_top_in"], result["stock_top_out"]
    if ti or to:
        def _rank_rows(items):
            rows = []
            for i, x in enumerate(items[:10], 1):
                net = h_yi(x.get("main_net_in"))
                net_s = f"+{net:.2f}亿" if net is not None and net >= 0 else (f"{net:.2f}亿" if net is not None else "—")
                cls = "up" if (net or 0) >= 0 else "down"
                pct_s, _ = h_pct(x.get("pct"))
                rows.append(f'      <div class="rank-row"><div class="rk">{i}</div>'
                            f'<div class="nm">{x["name"]}<span class="cd">{x.get("code","")}</span>'
                            f'<span class="cd" style="color:var(--txt2)">{pct_s}</span></div>'
                            f'<div class="vv {cls}">{net_s}</div></div>')
            return "\n".join(rows)
        body = (f'    <div class="g-1-1">\n'
                f'      <div><div class="p-title" style="margin-bottom:8px"><span class="bar"></span>主力净流入 TOP</div>\n'
                f'        <div class="rank">\n{_rank_rows(ti)}\n        </div>\n      </div>\n'
                f'      <div><div class="p-title" style="margin-bottom:8px"><span class="bar"></span>主力净流出 TOP</div>\n'
                f'        <div class="rank">\n{_rank_rows(to)}\n        </div>\n      </div>\n'
                f'    </div>\n')
    else:
        body = _empty_body("个股资金流数据暂缺（东方财富主源受限时可用 --merge 补全）。")
    S.append(_panel("个股资金流 TOP STOCK RANK", "主力净额 · 收盘", body))

    # ===== 5. 风格指数 + 主题代理 =====
    si = result["style_indices"]
    sp = result["style_proxy"]
    if si or sp:
        parts = []
        if si:
            rws = []
            for x in si:
                pct_s, cls = h_pct(x["pct"])
                rws.append(f'      <tr><td>{x["name"]}</td><td style="color:var(--txt);font-weight:700">{x["close"]:,.2f}'
                           f'</td><td class="{cls}">{pct_s}</td></tr>')
            parts.append('    <table class="idx-table">\n      <thead><tr><th>风格指数</th><th>收盘</th><th>涨跌幅</th></tr></thead>\n'
                         '      <tbody>\n' + "\n".join(rws) + '\n      </tbody>\n    </table>\n')
        if sp:
            bars = []
            for x in sp:
                pct_s, cls = h_pct(x["pct"])
                w = min(abs(x["pct"]) / 3 * 50, 50)
                if x["pct"] >= 0:
                    bar = f'<div class="sa-fill" style="left:50%;width:{w:.1f}%;background:linear-gradient(90deg,rgba(246,70,93,.4),rgba(246,70,93,.95))"></div>'
                else:
                    bar = f'<div class="sa-fill" style="right:50%;width:{w:.1f}%;background:linear-gradient(270deg,rgba(14,203,129,.4),rgba(14,203,129,.95))"></div>'
                bars.append(f'      <div class="sa-bar"><div class="mid"></div>{bar}'
                             f'<span style="position:absolute;{"left" if x["pct"]>=0 else "right"}:8px;top:5px;font-family:var(--mono);font-size:10.5px;color:var(--txt2)">{x["name"]} {pct_s}</span></div>')
            parts.append('    <div class="style-axis"><div class="sa-title"><span>主题代理（申万行业聚合）</span><span>跌 ◀ 　 ▶ 涨</span></div>\n'
                         + "\n".join(bars) + '\n    </div>\n')
        body = "\n".join(parts)
    else:
        body = _empty_body("风格指数数据暂缺（沙箱出口受限，请在本机运行 py）。")
    S.append(_panel("风格指数 & 主题代理 STYLE RADAR", "国证风格 + 主题聚合", body))

    # ===== 6. 北向资金 =====
    if nb.get("available"):
        t_r = f'{nb["turnover_ratio"]*100:.2f}%' if nb.get("turnover_ratio") else "—"
        body = ('    <div class="nkpis">\n'
                f'      <div class="nkpi"><div class="nl">沪股通成交额</div><div class="nv">{h_amount(nb["sh_connect_turnover"])}</div></div>\n'
                f'      <div class="nkpi"><div class="nl">深股通成交额</div><div class="nv">{h_amount(nb["sz_connect_turnover"])}</div></div>\n'
                f'      <div class="nkpi"><div class="nl">北向合计成交额</div><div class="nv">{h_amount(nb["total_turnover"])}</div></div>\n'
                f'      <div class="nkpi"><div class="nl">成交占比(占两市)</div><div class="nv">{t_r}</div></div>\n'
                '    </div>\n'
                '    <div class="n-note">⚠ 北向净买入自 2024-08-19 起不再实时披露，本页仅展示公开的【成交额】与【成交占比】，不展示/不编造净买入数字。</div>\n')
    else:
        body = _empty_body(nb.get("source", "北向数据暂缺") + "（净买入不披露，不编造）。")
    S.append(_panel("北向资金 NORTHBOUND TRACKER", "仅成交额 / 占比", body))

    # ===== 7. 热点 / 异动板块 =====
    hs = result.get("hotspots") or {}
    hot = hs.get("hot", [])
    weak = hs.get("weak", [])
    if hot or weak:
        def hcol(title, items, color):
            cards = []
            for x in items:
                pct_s, cls = h_pct(x["pct"])
                cards.append(f'      <div class="hot-card"><div class="ic" style="background:rgba(255,255,255,.05);color:var(--{color})">{x["name"][:2]}</div>'
                             f'<div><div class="ht">{x["name"]}</div><div class="hd">涨跌幅 {pct_s}</div></div></div>')
            return (f'    <div class="hot-col"><h4>{title} <span class="pill" style="background:rgba(246,70,93,.12);color:var(--up-b)">TOP {len(items)}</span></h4>\n'
                    + "\n".join(cards) + '\n    </div>')
        body = '    <div class="hot">\n' + hcol("今日热点（涨幅前）", hot, "up-b") + hcol("今日异动（跌幅前）", weak, "down-b") + '    </div>\n'
    else:
        body = _empty_body("热点/异动板块数据暂缺（需申万行业涨跌幅）。")
    S.append(_panel("热点 & 异动板块 HOTSPOTS", "申万行业涨跌 TOP", body))

    # ===== FOOTER =====
    S.append(f'''  <div class="foot">
    <b>数据日期</b>：{d}（{wd}，收盘后口径）　｜　<b>生成时间</b>：{result["generated_at"]}<br>
    <b>数据来源</b>：{result["source"]}；北向成交额为公开披露项，<b>净买入不披露、不编造</b>。<br>
    <b>口径说明</b>：涨红跌绿（A股惯例）；成交额/净流入单位为元，展示折算为亿/万亿；行业与个股口径以东方财富/腾讯自选股收盘数据为准。
  </div>
  <div class="disclaimer">本报告由 <b>ashare_close_fetcher.py</b> 自动生成 · 仅供研究参考，不构成投资建议</div>
''')

    S.append('</div>\n</body>\n</html>\n')
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(S))


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="A股收盘数据获取 + 报告生成脚本（AKShare + 东方财富/腾讯，收盘后口径）")
    ap.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    ap.add_argument("--fmt", default="html",
                    help="输出格式（逗号分隔，可多选）：json / md / csv / html（默认仅 html）")
    ap.add_argument("--out", help="输出目录（默认 <项目根>/build）")
    ap.add_argument("--merge", help="补全数据 JSON（东方财富被限流时，用外部/MCP 数据填充缺失模块）")
    ap.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    args = ap.parse_args()

    data_date = args.date or detect_trade_date()
    print(f"[*] 数据日期: {data_date}")

    # 1) 主要指数 + 国证风格指数 + 两市成交额：合并为一次 ulist 请求
    indices, style_idx, sh_amt, sz_amt, idx_src = fetch_market_snapshot()
    style_src = idx_src  # 风格指数与主要指数同源同请求
    print(f"[+] 指数 {len(indices)} 条 + 风格 {len(style_idx)} 条（{idx_src}）")

    sw_mapping, sw_mapping_src = fetch_sw_mapping()
    print(f"[+] 申万一级映射: {len((sw_mapping or {}).get('by_code', {}))}/31 条（{sw_mapping_src}）")

    stock_to_industry, stock_map_src = fetch_sw_stock_map()
    print(f"[+] 申万成分股映射: {len(stock_to_industry)} 条股票映射（{stock_map_src}）")

    sw_spot, sw_spot_src = fetch_sw_index_spot()
    print(f"[+] 申万一级指数: {len(sw_spot)}/31 条（{sw_spot_src}）")

    stock_rows, stock_rows_src = fetch_all_stock_fundflow_rank("今日", stock_codes=stock_to_industry.keys())
    print(f"[+] 个股资金流全市场: {len(stock_rows)} 条（{stock_rows_src}）")

    sw_list = build_sw_industry(sw_spot, stock_rows, sw_mapping, stock_to_industry)
    sw_src = f"{sw_spot_src} + {stock_rows_src}"
    print(f"[+] 申万一级行业聚合: {len(sw_list)}/31 条（{sw_src}）")

    nb, nb_src = fetch_northbound(sh_amt, sz_amt)
    print(f"[+] 北向资金: {'可用' if nb['available'] else '暂不可用'}（{nb_src}）")

    style_proxy = compute_style_proxy(sw_list)
    print(f"[+] 风格代理: {len(style_proxy)} 条主题（金融防御/医药景气/科技成长/周期资源）")

    top_in, top_out, stock_src = fetch_stock_fundflow_top(args.topn, stock_rows=stock_rows, stock_source=stock_rows_src)
    print(f"[+] 个股资金流 TOP: 净流入 {len(top_in)} / 净流出 {len(top_out)} 条（{stock_src}）")

    hotspots = compute_hotspots(sw_list)

    # --merge：东方财富被限流时，用外部补全（如 MCP 数据）填充缺失模块
    merged = False
    if args.merge and os.path.exists(args.merge):
        with open(args.merge, encoding="utf-8") as f:
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
        print(f"[+] --merge {args.merge}：补全 申万 {len(sw_list)}/31、北向 {'可用' if nb.get('available') else '无'}、个股TOP {len(top_in)}/{len(top_out)}")

    overall_source = SOURCE_SW if (sw_list or nb["available"] or top_in) else "腾讯gtimg(指数回退)+AKShare/东方财富(受限)"
    if merged:
        overall_source += "（主源受限，部分模块由外部数据补全）"

    result = {
        "data_date": data_date,
        "source": overall_source,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note_northbound": "北向净买入自2024-08-19起不再披露，仅取成交额与成交占比，不编造净买入。",
        "indices": indices,
        "sw_industry": sw_list,
        "sw_industry_source": sw_src,
        "northbound": nb,
        "two_market": {"sh": sh_amt, "sz": sz_amt},  # 两市成交额（元），用于 KPI
        "style_indices": style_idx,
        "style_indices_source": style_src,
        "style_proxy": style_proxy,
        "stock_top_in": top_in,
        "stock_top_out": top_out,
        "stock_source": stock_src,
        "hotspots": hotspots,
    }

    # 输出目录：默认 <项目根>/build（脚本在 fundflow/，项目根为其父目录），每天覆盖前一天
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    out_dir = args.out or os.path.join(root_dir, "build")
    os.makedirs(out_dir, exist_ok=True)

    fmts = [f.strip().lower() for f in args.fmt.split(",") if f.strip()]
    if not fmts:
        fmts = ["html"]

    base = os.path.join(out_dir, "ashare_close")  # 固定名，无日期
    written = []

    if "json" in fmts:
        json_path = f"{base}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        written.append(f"JSON : {json_path}")
    if "md" in fmts:
        md_path = f"{base}.md"
        write_markdown(md_path, result)
        written.append(f"MD   : {md_path}")
    if "csv" in fmts:
        if sw_list:
            csv_path = f"{base}_industry.csv"
            write_csv(csv_path, sw_list)
            written.append(f"CSV  : {csv_path}")
        else:
            print("[!] CSV 跳过：申万行业数据暂缺（--fmt csv 已指定，但无数据可导出）")
    if "html" in fmts:
        html_path = f"{base}.html"
        write_html(html_path, result)
        written.append(f"HTML : {html_path}")

    print(f"\n[✓] 已写出（{data_date}，目录 {out_dir}）：")
    for w in written:
        print("    " + w)
    print(f"[i] 本次共发起 {REQ_COUNT['n']} 次 HTTP 请求（含失败重试；请求间隔 {REQUEST_DELAY}s）")
    return result


if __name__ == "__main__":
    main()
