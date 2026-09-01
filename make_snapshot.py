#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实数据快照：调用 collect_report_data 取真实收盘数据，存入 build/data/fundflow_snapshot.json。

后续预览/开发改页面时，直接读此文件取数，无需 mock。

用法：
    python make_snapshot.py                      # 自动取最近交易日（收盘后）
    python make_snapshot.py --date 2026-08-31    # 指定数据日期
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fundflow.fundflow_processor import collect_report_data


def main() -> None:
    parser = argparse.ArgumentParser(description="生成真实数据快照 build/data/fundflow_snapshot.json")
    parser.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    parser.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    args = parser.parse_args()

    result = collect_report_data(data_date=args.date, topn=args.topn, verbose=True)
    data_date = result.get("data_date")
    payload = {
        "_meta": {
            "cache_scope": "preview_snapshot",
            "source": result.get("source"),
            "data_date": data_date,
            "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": "真实收盘数据快照，供预览/开发取数，无需 mock",
        },
        "data": result,
    }
    out = os.path.join(ROOT, "build", "data", "fundflow_snapshot.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    size = os.path.getsize(out)
    print(f"\n[✓] 快照已写出：{out}")
    print(f"    数据日期: {data_date} | 大小: {size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
