#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目主入口：统一构建 fundflow 与 stocktrend 页面。"""
from __future__ import annotations

import argparse
import os
from typing import Dict

from common.site_navigation import render_site_index
from common.storage import default_data_dir
from common.storage import default_site_dir
from common.storage import read_json
from fundflow.fundflow_main import build_fundflow_report


def build_stocktrend_report(data_date: str | None = None, out_dir: str | None = None, market: str = "all") -> Dict:
    from stocktrend.stocktrend_data_fetcher import collect_pages
    from stocktrend.stocktrend_data_fetcher import write_page_jsons
    from stocktrend.stocktrend_ui_renderer import render_page
    from stocktrend.stocktrend_ui_renderer import write_html

    data_dir = out_dir or default_data_dir()
    site_dir = default_site_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(site_dir, exist_ok=True)

    pages = collect_pages(data_date=data_date, market=market)
    json_paths = write_page_jsons(pages, out_dir=data_dir)

    html_paths = []
    for json_path in json_paths:
        payload = read_json(json_path)
        page_data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
        html_name = os.path.splitext(os.path.basename(json_path))[0] + ".html"
        html_path = os.path.join(site_dir, html_name)
        write_html(html_path, render_page(page_data))
        html_paths.append(html_path)
    return {"json_paths": json_paths, "html_paths": html_paths, "pages": pages}


def build_site_index(fundflow_result: Dict, stocktrend_result: Dict, out_dir: str | None = None) -> str:
    target_dir = out_dir or default_site_dir()
    os.makedirs(target_dir, exist_ok=True)

    trade_date = fundflow_result.get("result", {}).get("data_date") or "最新交易日"
    cards = [
        {
            "title": "A股资金流日报",
            "href": "fundflow.html",
            "badge": "fundflow",
            "description": "看市场强弱、行业热力图、主力净流入、北向成交占比，适合先把握当天全市场主线。",
        }
    ]
    if "ashare" in stocktrend_result.get("pages", {}):
        cards.append(
            {
                "title": "A股个股走势",
                "href": "stocktrend_ashare.html",
                "badge": "stocktrend / ashare",
                "description": "聚焦 32 只核心 A 股，按收盘口径查看估值、位置、资金面、财务与风险提示。",
            }
        )
    if "hk" in stocktrend_result.get("pages", {}):
        cards.append(
            {
                "title": "港股个股走势",
                "href": "stocktrend_hk.html",
                "badge": "stocktrend / hk",
                "description": "查看港股代表标的的收盘快照、估值、南向持股和分红信息，适合和 A 股页并列浏览。",
            }
        )

    html = render_site_index(
        title="stock-voyager 静态报告导航",
        subtitle="统一入口页，负责把 A 股资金流、A 股个股走势、港股个股走势三张静态页面组织在一起。",
        date_text=f"当前页面数据日期：{trade_date}",
        cards=cards,
    )
    index_path = os.path.join(target_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as file:
        file.write(html)
    return index_path


def main() -> Dict:
    parser = argparse.ArgumentParser(description="统一构建 fundflow 与 stocktrend 页面")
    parser.add_argument("--date", help="交易日 YYYY-MM-DD（默认取最近交易日）")
    parser.add_argument("--out", help="页面 JSON 输出目录（默认 <项目根>/build/data）")
    parser.add_argument("--topn", type=int, default=10, help="fundflow 个股资金流 TOP 数量")
    parser.add_argument("--stocktrend-market", choices=["all", "ashare", "hk"], default="all", help="stocktrend 输出市场")
    args = parser.parse_args()

    fundflow_result = build_fundflow_report(data_date=args.date, out_dir=args.out, topn=args.topn, verbose=True)
    stocktrend_result = build_stocktrend_report(data_date=args.date, out_dir=args.out, market=args.stocktrend_market)
    index_path = build_site_index(fundflow_result, stocktrend_result)

    print("\n[✓] 页面产物已写出：")
    print(f"    site index : {index_path}")
    print(f"    fundflow JSON : {fundflow_result['json_path']}")
    print(f"    fundflow HTML : {fundflow_result['html_path']}")
    for path in stocktrend_result["json_paths"]:
        print(f"    stocktrend JSON : {path}")
    for path in stocktrend_result["html_paths"]:
        print(f"    stocktrend HTML : {path}")
    return {"index_path": index_path, "fundflow": fundflow_result, "stocktrend": stocktrend_result}


if __name__ == "__main__":
    main()
