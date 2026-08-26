#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目主入口：统一构建 fundflow 与 stocktrend 页面。"""
from __future__ import annotations

import argparse
import os
from typing import Dict

from common.storage import default_build_dir
from common.storage import read_json
from fundflow.fundflow_main import build_fundflow_report
from stocktrend.stocktrend_data_fetcher import collect_pages
from stocktrend.stocktrend_data_fetcher import write_page_jsons
from stocktrend.stocktrend_ui_renderer import render_page
from stocktrend.stocktrend_ui_renderer import write_html


def build_stocktrend_report(data_date: str | None = None, out_dir: str | None = None, market: str = "all") -> Dict:
    target_dir = out_dir or default_build_dir()
    os.makedirs(target_dir, exist_ok=True)

    pages = collect_pages(data_date=data_date, market=market)
    json_paths = write_page_jsons(pages, out_dir=target_dir)

    html_paths = []
    for json_path in json_paths:
        payload = read_json(json_path)
        html_path = os.path.splitext(json_path)[0] + ".html"
        write_html(html_path, render_page(payload))
        html_paths.append(html_path)
    return {"json_paths": json_paths, "html_paths": html_paths, "pages": pages}


def main() -> Dict:
    parser = argparse.ArgumentParser(description="统一构建 fundflow 与 stocktrend 页面")
    parser.add_argument("--date", help="交易日 YYYY-MM-DD（默认取最近交易日）")
    parser.add_argument("--out", help="输出目录（默认 <项目根>/build）")
    parser.add_argument("--topn", type=int, default=10, help="fundflow 个股资金流 TOP 数量")
    parser.add_argument("--stocktrend-market", choices=["all", "ashare", "hk"], default="all", help="stocktrend 输出市场")
    args = parser.parse_args()

    fundflow_result = build_fundflow_report(data_date=args.date, out_dir=args.out, topn=args.topn, verbose=True)
    stocktrend_result = build_stocktrend_report(data_date=args.date, out_dir=args.out, market=args.stocktrend_market)

    print("\n[✓] 页面产物已写出：")
    print(f"    fundflow JSON : {fundflow_result['json_path']}")
    print(f"    fundflow HTML : {fundflow_result['html_path']}")
    for path in stocktrend_result["json_paths"]:
        print(f"    stocktrend JSON : {path}")
    for path in stocktrend_result["html_paths"]:
        print(f"    stocktrend HTML : {path}")
    return {"fundflow": fundflow_result, "stocktrend": stocktrend_result}


if __name__ == "__main__":
    main()
