#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全市场行业面板改造 smoke test（零网络）。

验证：
  1. build_hk_sector 按 row['sector']（f100 恒生二级）全市场聚合，量纲为百分数；
  2. build_us_sector 按 row['sector']（f100 GICS 一级）全市场聚合；
  3. 渲染出的港股/美股页：行业面板文案正确、热点卡片涨跌幅不再显示 0.00%。
运行：python tests/smoke_fullmarket_panels.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fundflow.fundflow_processor import build_hk_sector, build_us_sector, compute_hk_hotspots, compute_us_hotspots, generate_hk_verdict
from fundflow.fundflow_ui_renderer import write_html

OUT = os.path.join(ROOT, "build", "smoke")
os.makedirs(OUT, exist_ok=True)


def hk_rows():
    # 真实口径：pct 为百分数（-2.64 = -2.64%），sector 为 f100 恒生二级行业
    return [
        {"code": "09988", "name": "阿里巴巴-W", "pct": -2.64, "main_net_in": 4.97e8, "sector": "专业零售"},
        {"code": "01810", "name": "小米集团-W", "pct": -1.74, "main_net_in": 4.13e8, "sector": "资讯科技器材"},
        {"code": "01211", "name": "比亚迪股份", "pct": -2.75, "main_net_in": 3.24e8, "sector": "汽车"},
        {"code": "00939", "name": "建设银行", "pct": 0.85, "main_net_in": -1.2e8, "sector": "银行"},
        {"code": "01398", "name": "工商银行", "pct": 0.42, "main_net_in": -9.0e7, "sector": "银行"},
        {"code": "00700", "name": "腾讯控股", "pct": 1.31, "main_net_in": 2.6e8, "sector": "软件服务"},
        {"code": "01801", "name": "信达生物", "pct": 3.15, "main_net_in": 8.0e7, "sector": "药品及生物科技"},
        {"code": "00005", "name": "汇丰控股", "pct": 0.12, "main_net_in": 3.0e7, "sector": "银行"},
        {"code": "00000", "name": "某ETF", "pct": 0.0, "main_net_in": 1.0, "sector": "-"},  # 应被过滤
    ]


def us_rows():
    return [
        {"code": "AAPL", "name": "苹果", "pct": 1.25, "main_net_in": 3.1e8, "sector": "信息技术"},
        {"code": "MSFT", "name": "微软", "pct": 0.98, "main_net_in": 2.4e8, "sector": "信息技术"},
        {"code": "JPM", "name": "摩根大通", "pct": -0.44, "main_net_in": -1.1e8, "sector": "金融"},
        {"code": "XOM", "name": "埃克森美孚", "pct": 2.07, "main_net_in": 1.5e8, "sector": "能源"},
        {"code": "BND", "name": "债券ETF", "pct": 0.1, "main_net_in": 5.0, "sector": "-"},  # 应被过滤
    ]


def base_result(date, **kw):
    r = {
        "data_date": date,
        "source": "smoke",
        "generated_at": "2026-09-10 16:00:00",
        "indices": [{"name": "恒生指数" if kw.get("market") == "hk" else "标普500",
                     "code": "hkHSI" if kw.get("market") == "hk" else "usINX",
                     "close": 25000.0, "pct": 0.42, "chg": 105.0, "main_net_in": None}],
        "northbound": {}, "southbound": {"available": False, "source": "smoke 暂不可用"},
        "sw_industry": [], "hk_sector": [], "us_sector": [], "global_liquidity": {},
        "breadth": {"available": False, "source": "smoke"},
        "stock_top_in": [], "stock_top_out": [], "stock_source": "smoke",
        "hotspots": {}, "fetch_warnings": [],
    }
    r.update(kw)
    return r


def main():
    hk_sector = build_hk_sector(hk_rows())
    us_sector = build_us_sector(us_rows())

    # 断言 1：ETF(sector='-') 被过滤；银行 3 只合并为 1 个行业
    hk_names = [s["name"] for s in hk_sector]
    assert "银行" in hk_names, hk_names
    bank = next(s for s in hk_sector if s["name"] == "银行")
    assert bank["n_members"] == 3, bank["n_members"]
    total_members = sum(s["n_members"] for s in hk_sector)
    assert total_members == 8, f"港股应聚合 8 只（ETF 被过滤），实际 {total_members}"

    # 断言 2：量纲为百分数（行业平均涨跌幅不应是 0.00 级别）
    assert abs(bank["pct"]) < 5 and abs(bank["pct"]) > 0.01, bank["pct"]
    it = next(s for s in hk_sector if s["name"] == "软件服务")
    assert abs(it["pct"] - 1.31) < 1e-9, it["pct"]

    us_names = [s["name"] for s in us_sector]
    assert "信息技术" in us_names and "金融" in us_names, us_names
    assert "硬件设备" not in us_names, "美股不应再按二级行业聚合"
    us_total = sum(s["n_members"] for s in us_sector)
    assert us_total == 4, f"美股应聚合 4 只（ETF 被过滤），实际 {us_total}"

    # 断言 3：渲染无异常，且文案 / 涨跌幅正确
    hk_res = base_result("2026-09-10", market="hk", hk_sector=hk_sector,
                         hotspots=compute_hk_hotspots(hk_sector))
    hk_res["market_verdict"] = generate_hk_verdict(hk_res)
    hk_path = os.path.join(OUT, "fundflow_hk_smoke.html")
    write_html(hk_path, hk_res, market="hk")

    us_res = base_result("2026-09-10", market="us", us_sector=us_sector,
                         hotspots=compute_us_hotspots(us_sector))
    us_res["market_verdict"] = {"headline": "smoke", "tone": "flat", "tone_word": "整体震荡"}
    us_path = os.path.join(OUT, "fundflow_us_smoke.html")
    write_html(us_path, us_res, market="us")

    hk_html = open(hk_path, encoding="utf-8").read()
    us_html = open(us_path, encoding="utf-8").read()

    assert "港股二级行业主力净流入" in hk_html
    assert "美股 GICS 一级行业主力净流入" in us_html, "美股面板应改为一级行业"
    assert "GICS 二级行业汇总" not in us_html
    assert "全市场覆盖 8 只" in hk_html, "港股页头应标注全市场覆盖只数"
    assert "全市场覆盖 4 只" in us_html, "美股页头应标注全市场覆盖只数"

    # 量纲回归：热点卡片必须出现真实百分数，而非 0.00%
    import re
    hk_pcts = re.findall(r'涨跌幅 <b class="[^"]*">([^<]*)</b>', hk_html)
    assert hk_pcts, "港股热点卡片缺失"
    assert any(p not in ("▲ +0.00%", "▼ -0.00%") for p in hk_pcts), f"港股涨跌幅仍是 0.00%：{hk_pcts}"
    print("港股热点卡片涨跌幅样例:", hk_pcts[:4])

    # 盘面定调不应出现 0.00% 领涨
    assert "(+0.00%)" not in hk_html, "盘面定调仍出现 +0.00%"

    print("OK: 全市场行业面板 smoke test 通过")
    print("  港股行业:", [(s["name"], round(s["pct"], 2), s["n_members"]) for s in hk_sector])
    print("  美股行业:", [(s["name"], round(s["pct"], 2), s["n_members"]) for s in us_sector])
    print("  产物:", hk_path, us_path)


if __name__ == "__main__":
    main()
