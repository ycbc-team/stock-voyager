#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股收盘数据获取脚本
====================
数据口径 : 当日收盘后（默认取"最近一个已收盘交易日"；可用 --date YYYY-MM-DD 覆盖）
数据来源 : 东方财富 East Money 公开行情接口 push2 / datacenter
          （与"证券时报·数据宝"收盘表同源：申万一级行业、主力资金净流入、北向成交额均出自此）
          指数/个股回退源 : 腾讯财经 gtimg（沙箱环境下更稳，作为回退）
重要约定 :
  1. 北向资金净买入自 2024-08-19 起不再实时披露。本脚本只取【成交额】与【成交占比】，
     绝不编造净买入数字；即便接口返回净买额字段，也统一置 None 并标注"不再披露"。
  2. 所有输出显式标注 数据日期 与 数据来源。
输出格式 : JSON（机器可读） / Markdown（人读） / CSV（申万行业表）
依赖     : 仅 Python 标准库（urllib / json / datetime / argparse），零第三方依赖，可裸跑。
用法     :
  python3 ashare_close_fetcher.py                      # 取最近交易日，输出全部（默认 ./ashare_close_<date>.{json,md,csv}）
  python3 ashare_close_fetcher.py --date 2026-08-25 --md report.md --json report.json --csv industry.csv
  python3 ashare_close_fetcher.py --csv industry.csv   # 仅导出申万行业 CSV
注意     : 在 WorkBuddy 自动化沙箱内，东方财富 push2 数据接口可能被出口代理拦截；
           此时脚本会自动回退到腾讯 gtimg 取指数，并在申万/北向/资金流模块标注"接口暂不可用"。
           在本机（Mac/PC 正常网络）运行可取得完整数据。
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
EM_HOSTS = [
    "https://push2.eastmoney.com",
    "https://push2his.eastmoney.com",
]
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
}
# 东方财富行情接口统一令牌（部分端点需要）
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"
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


# ---------------------------------------------------------------------------
# 通用抓取
# ---------------------------------------------------------------------------
def _http_get(url, headers, timeout=15, retries=3, backoff=1.5):
    last_err = None
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
def fetch_indices():
    out = []
    src = SOURCE_EM
    # 东方财富 ulist
    secids = ",".join(s for _, s in INDICES)
    data = em_get("/api/qt/ulist.np/get",
                  {"fields": "f12,f14,f2,f3,f4,f6,f62", "secids": secids})
    if data:
        rows = {r.get("f12"): r for r in _diff_list(data.get("data", {}))}
        for name, sid in INDICES:
            code = sid.split(".")[1]
            r = rows.get(code)
            if r:
                out.append({
                    "name": name,
                    "code": code,
                    "close": _to_float(r.get("f2")) / 100 if _to_float(r.get("f2")) is not None else None,
                    "pct": _to_float(r.get("f3")) / 100 if _to_float(r.get("f3")) is not None else None,
                    "chg": _to_float(r.get("f4")) / 100 if _to_float(r.get("f4")) is not None else None,
                    "main_net_in": _to_float(r.get("f62")),  # 元
                    "source": SOURCE_EM,
                })
    # 回退：腾讯 gtimg（仅指数报价，无主力净流入）
    if not out:
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
                # 用名称反查代码（gtimg 名称与上证指数等一致）
                code = None
                for c, n in want.items():
                    if n == name:
                        code = c
                if code is None:
                    continue
                out.append({
                    "name": name, "code": code,
                    "close": _to_float(parts[3]),
                    "pct": _to_float(parts[32]),
                    "chg": _to_float(parts[31]),
                    "main_net_in": None,
                    "source": SOURCE_GT,
                })
    return out, src


# ---------------------------------------------------------------------------
# 2) 申万一级行业：涨跌幅 + 主力资金净流入
#    采用与指数同款的 ulist.np + 31 个申万一级行业指数 secid（90.801010…），
#    可同时取 涨跌幅(f3) 与 主力净流入(f62)，且不受行业板块分类(东方财富/申万)切换影响。
# ---------------------------------------------------------------------------
def fetch_sw_industry():
    secids = ",".join(f"90.{c}" for c in SW_INDUSTRY.keys())
    data = em_get("/api/qt/ulist.np/get",
                  {"fields": "f12,f14,f2,f3,f62", "secids": secids})
    out = []
    if data:
        for r in _diff_list(data.get("data", {})):
            code = str(r.get("f12", "")).replace("90.", "")
            if code not in SW_INDUSTRY:
                continue
            f2 = _to_float(r.get("f2"))
            f3 = _to_float(r.get("f3"))
            out.append({
                "code": code,
                "name": SW_INDUSTRY[code],
                # 指数类 f2 单位为"分"(×100)，需 /100；若已是真实值则 /100 也无妨（申万指数均 >100）
                "close": f2 / 100 if f2 is not None else None,
                "pct": f3 / 100 if f3 is not None else None,
                "main_net_in": _to_float(r.get("f62")),  # 元
                "source": SOURCE_EM,
            })
    return out, (SOURCE_EM if out else "东方财富接口暂不可用（沙箱出口受限，请在本机运行）")


# ---------------------------------------------------------------------------
# 3) 北向资金：成交额 + 成交占比（不取净买入）
#    kamt 接口返回 data.klines：按分钟、逗号分隔的字符串数组；最后一条=收盘。
#    字段顺序对应请求的 fields。以下映射取"人民币口径"成交额：
#      f55=北向合计成交额(人民币)  f59=沪股通成交额(人民币)  f63=深股通成交额(人民币)
#      (对应的 f54/f58/f62 为港币口径，作回退)
#    净买入：自 2024-08-19 起不再披露，本脚本一律置 None，绝不编造。
# ---------------------------------------------------------------------------
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
    result["source"] = "东方财富 kamt 接口暂不可用（沙箱出口受限/该字段未披露；不编造净买入）"
    return result, result["source"]


# ---------------------------------------------------------------------------
# 4) 风格指数（国证风格 + 主题代理）
# ---------------------------------------------------------------------------
def fetch_style_indices():
    out = []
    src = SOURCE_EM
    secids = ",".join(s for _, s in STYLE_INDEX)
    data = em_get("/api/qt/ulist.np/get", {"fields": "f12,f14,f2,f3", "secids": secids})
    if data:
        rows = {r.get("f12"): r for r in _diff_list(data.get("data", {}))}
        for name, sid in STYLE_INDEX:
            code = sid.split(".")[1]
            r = rows.get(code)
            if r:
                out.append({
                    "name": name, "code": code,
                    "close": _to_float(r.get("f2")) / 100 if _to_float(r.get("f2")) is not None else None,
                    "pct": _to_float(r.get("f3")) / 100 if _to_float(r.get("f3")) is not None else None,
                    "source": SOURCE_EM,
                })
    else:
        src = "东方财富接口暂不可用（沙箱出口受限，请在本机运行）"
    return out, src


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
# ---------------------------------------------------------------------------
def fetch_stock_fundflow_top(topn=10):
    rows = []
    for fs in ("m:0+t:6", "m:1+t:6"):  # 沪市 / 深市 A 股
        data = em_get("/api/qt/clist/get",
                      {"pn": "1", "pz": str(topn), "fs": fs, "po": "1",
                       "fields": "f12,f14,f2,f3,f62"})
        if data:
            for r in _diff_list(data.get("data", {})):
                rows.append({
                    "code": str(r.get("f12", "")),
                    "name": r.get("f14"),
                    "pct": _to_float(r.get("f3")) / 100 if _to_float(r.get("f3")) is not None else None,
                    "main_net_in": _to_float(r.get("f62")),  # 元
                })
    rows.sort(key=lambda x: (x["main_net_in"] or -1e30), reverse=True)
    top_in = rows[:topn]
    # 净流出：按 f62 升序，重新拉取（po=-1）
    rows_out = []
    for fs in ("m:0+t:6", "m:1+t:6"):
        data = em_get("/api/qt/clist/get",
                      {"pn": "1", "pz": str(topn), "fs": fs, "po": "-1",
                       "fields": "f12,f14,f2,f3,f62"})
        if data:
            for r in _diff_list(data.get("data", {})):
                rows_out.append({
                    "code": str(r.get("f12", "")),
                    "name": r.get("f14"),
                    "pct": _to_float(r.get("f3")) / 100 if _to_float(r.get("f3")) is not None else None,
                    "main_net_in": _to_float(r.get("f62")),
                })
    rows_out.sort(key=lambda x: (x["main_net_in"] if x["main_net_in"] is not None else 1e30))
    top_out = rows_out[:topn]
    return top_in, top_out, (SOURCE_EM if (top_in or top_out) else "东方财富接口暂不可用（沙箱出口受限，请在本机运行）")


def compute_hotspots(sw_list, topn=5):
    valid = [x for x in sw_list if _to_float(x["pct"]) is not None]
    valid.sort(key=lambda x: x["pct"], reverse=True)
    return {
        "hot": valid[:topn],                  # 涨幅居前 = 今日热点
        "weak": valid[-topn:][::-1],           # 跌幅居前 = 今日异动（弱势）
    }


# ---------------------------------------------------------------------------
# 两市成交额（用于北向占比）
# ---------------------------------------------------------------------------
def fetch_two_market_amount():
    """返回 (沪市成交额元, 深市成交额元)。从指数报价中识别成交额字段（量级 1e11~1e13）。"""
    secids = "1.000001,0.399001"
    data = em_get("/api/qt/ulist.np/get",
                  {"fields": "f12,f14,f2,f3,f6,f7,f8,f67", "secids": secids})
    if not data:
        return None, None
    res = {}
    for r in _diff_list(data.get("data", {})):
        code = r.get("f12")
        amt = None
        for f in ("f7", "f8", "f67", "f6"):
            v = _to_float(r.get(f))
            if v is not None and 1e11 <= abs(v) <= 1e13:
                amt = v
                break
        res[code] = amt
    return res.get("000001"), res.get("399001")


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
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="A股收盘数据获取脚本（东方财富/腾讯，收盘后口径）")
    ap.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    ap.add_argument("--json", help="JSON 输出路径")
    ap.add_argument("--md", help="Markdown 输出路径")
    ap.add_argument("--csv", help="申万行业 CSV 输出路径")
    ap.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    args = ap.parse_args()

    data_date = args.date or detect_trade_date()
    print(f"[*] 数据日期: {data_date}")

    indices, idx_src = fetch_indices()
    print(f"[+] 主要指数: {len(indices)} 条（{idx_src}）")

    sw_list, sw_src = fetch_sw_industry()
    print(f"[+] 申万一级行业: {len(sw_list)}/31 条（{sw_src}）")

    sh_amt, sz_amt = fetch_two_market_amount()
    nb, nb_src = fetch_northbound(sh_amt, sz_amt)
    print(f"[+] 北向资金: {'可用' if nb['available'] else '暂不可用'}（{nb_src}）")

    style_idx, style_src = fetch_style_indices()
    style_proxy = compute_style_proxy(sw_list)
    print(f"[+] 风格指数: {len(style_idx)} 条国证 + {len(style_proxy)} 条主题代理")

    top_in, top_out, stock_src = fetch_stock_fundflow_top(args.topn)
    print(f"[+] 个股资金流 TOP: 净流入 {len(top_in)} / 净流出 {len(top_out)} 条（{stock_src}）")

    hotspots = compute_hotspots(sw_list)
    overall_source = SOURCE_EM if (sw_list or nb["available"] or top_in) else "腾讯gtimg(指数回退)+东方财富(受限)"

    result = {
        "data_date": data_date,
        "source": overall_source,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note_northbound": "北向净买入自2024-08-19起不再披露，仅取成交额与成交占比，不编造净买入。",
        "indices": indices,
        "sw_industry": sw_list,
        "sw_industry_source": sw_src,
        "northbound": nb,
        "style_indices": style_idx,
        "style_indices_source": style_src,
        "style_proxy": style_proxy,
        "stock_top_in": top_in,
        "stock_top_out": top_out,
        "stock_source": stock_src,
        "hotspots": hotspots,
    }

    # 默认产物与脚本同目录（移动脚本后样例也落在同目录），--json/--md/--csv 可覆盖
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    base = os.path.join(_script_dir, f"ashare_close_{data_date}")
    json_path = args.json or f"{base}.json"
    md_path = args.md or f"{base}.md"
    csv_path = args.csv or (f"{base}_industry.csv" if not args.csv else args.csv)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    write_markdown(md_path, result)
    if sw_list:
        write_csv(csv_path, sw_list)
    else:
        csv_path = None

    print(f"\n[✓] 已写出：\n    JSON : {json_path}\n    MD   : {md_path}" +
          (f"\n    CSV  : {csv_path}" if csv_path else ""))
    return result


if __name__ == "__main__":
    main()
