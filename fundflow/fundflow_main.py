#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股收盘主脚本
==============
职责：
  1. 调用 funflow_data_fetcher.py 生产中间数据
  2. 将中间数据写入 build/funflow.json
  3. 基于 JSON 中间产物调用 funflow_ui_renderer.py 生成 HTML

默认产物：
  - build/funflow.json
  - build/funflow.html

可选产物：
  - build/funflow_industry.csv
"""
import argparse
import os

from funflow_data_fetcher import collect_report_data, default_build_dir, write_csv, write_json
from funflow_ui_renderer import load_result, write_html


def main():
    ap = argparse.ArgumentParser(description="A股收盘总控脚本：先生产数据，再基于 JSON 中间产物渲染 HTML")
    ap.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    ap.add_argument("--fmt", default="html", help="输出格式（逗号分隔，可多选）：html / json / csv（默认 html）")
    ap.add_argument("--out", help="输出目录（默认 <项目根>/build）")
    ap.add_argument("--merge", help="补全数据 JSON（主源被限流时填充缺失模块）")
    ap.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    args = ap.parse_args()

    out_dir = args.out or default_build_dir()
    os.makedirs(out_dir, exist_ok=True)

    requested = {f.strip().lower() for f in args.fmt.split(",") if f.strip()}
    if not requested:
        requested = {"html"}

    emit_html = "html" in requested
    emit_csv = "csv" in requested
    emit_json = "json" in requested or emit_html

    result = collect_report_data(
        data_date=args.date,
        topn=args.topn,
        merge_path=args.merge,
        verbose=True,
    )

    base = os.path.join(out_dir, "funflow")
    written = []
    json_path = f"{base}.json"

    if emit_json:
        write_json(json_path, result)
        tag = "JSON*" if emit_html and "json" not in requested else "JSON "
        written.append(f"{tag}: {json_path}")

    if emit_csv:
        if result["sw_industry"]:
            csv_path = f"{base}_industry.csv"
            write_csv(csv_path, result["sw_industry"])
            written.append(f"CSV  : {csv_path}")
        else:
            print("[!] CSV 跳过：申万行业数据暂缺（--fmt csv 已指定，但无数据可导出）")

    if emit_html:
        html_path = f"{base}.html"
        render_input = load_result(json_path)
        write_html(html_path, render_input)
        written.append(f"HTML : {html_path}")

    print(f"\n[✓] 已写出（{result['data_date']}，目录 {out_dir}）：")
    for item in written:
        print("    " + item)
    if emit_html and "json" not in requested:
        print("[i] JSON* 为 HTML 渲染所需中间产物，已按 MVC 流程保存在 build/ 中")
    print(f"[i] 数据抓取阶段共发起 {result.get('request_count', 0)} 次 HTTP 请求（含失败重试）")
    return result


if __name__ == "__main__":
    main()
