#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fundflow 页面总控：先生成 JSON，再渲染 HTML。"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


from common.storage import default_build_dir
from common.storage import read_json
from fundflow.fundflow_data_fetcher import collect_report_data
from fundflow.fundflow_data_fetcher import write_report_json
from fundflow.fundflow_ui_renderer import write_html


def build_fundflow_report(data_date: str | None = None, out_dir: str | None = None, topn: int = 10, verbose: bool = True) -> Dict:
    target_dir = out_dir or default_build_dir()
    os.makedirs(target_dir, exist_ok=True)

    result = collect_report_data(data_date=data_date, topn=topn, verbose=verbose)
    json_path = write_report_json(result, out_dir=target_dir)
    html_path = os.path.join(target_dir, "fundflow.html")
    write_html(html_path, read_json(json_path))
    return {"json_path": json_path, "html_path": html_path, "result": result}


def main() -> Dict:
    parser = argparse.ArgumentParser(description="fundflow 页面总控：生成 build/fundflow.json 与 build/fundflow.html")
    parser.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    parser.add_argument("--out", help="输出目录（默认 <项目根>/build）")
    parser.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    args = parser.parse_args()

    written = build_fundflow_report(data_date=args.date, out_dir=args.out, topn=args.topn, verbose=True)
    print("\n[✓] 已写出：")
    print(f"    JSON : {written['json_path']}")
    print(f"    HTML : {written['html_path']}")
    return written


if __name__ == "__main__":
    main()
