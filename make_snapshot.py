#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目统一真实数据快照：调用各模块真实收盘数据收集函数，汇总写入 build/data/snapshot.json。

覆盖：
  - fundflow    A股/港股资金流（collect_report_data / collect_report_data_hk）
  - stocktrend  A股/港股个股走势（collect_pages）

此文件是预览/开发改页面统一读取的【唯一真实数据源】，无需 mock。

用法：
    python make_snapshot.py                       # 自动取最近交易日（收盘后），全量抓取
    python make_snapshot.py --date 2026-09-01     # 指定数据日期
    python make_snapshot.py --skip-stocktrend     # 仅刷新资金流（更快，分步验证用）
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.market_data import detect_trade_date


def _safe(label: str, fn, *args, **kwargs):
    """执行 fn；成功返回 (True, 结果)，失败返回 (False, 错误信息)。"""
    try:
        return True, fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        return False, f"{label} 失败: {exc}\n{traceback.format_exc()}"


def _load_old_stocktrend(out_path: str) -> dict:
    """读取旧 snapshot.json 中的 stocktrend 真实数据，用于保留/兜底（避免预览断供）。"""
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            return json.load(f).get("data", {}).get("stocktrend", {}) or {}
    except Exception:
        return {}


def _old_date(out_path: str) -> str:
    """读取旧 snapshot.json 的数据日期，用于标注保留数据的时效。"""
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            return json.load(f).get("_meta", {}).get("data_date", "?")
    except Exception:
        return "?"


def main() -> None:
    parser = argparse.ArgumentParser(description="生成项目统一真实数据快照 build/data/snapshot.json")
    parser.add_argument("--date", help="数据日期 YYYY-MM-DD（默认取最近交易日）")
    parser.add_argument("--topn", type=int, default=10, help="个股资金流 TOP 数量")
    parser.add_argument("--skip-stocktrend", action="store_true", help="仅刷新资金流，跳过 stocktrend（更快）")
    args = parser.parse_args()

    data_date = args.date or detect_trade_date("ashare")
    print(f"[*] 数据日期: {data_date}")

    modules: dict = {}
    data: dict = {}

    # ---- fundflow：A股 + 港股资金流 ----
    from fundflow.fundflow_processor import collect_report_data, collect_report_data_hk

    ok_a, res_a = _safe("fundflow A股", collect_report_data, data_date, args.topn, True)
    modules["funds_ashare"] = "ok" if ok_a else f"failed: {str(res_a)[:240]}"
    if ok_a:
        data.setdefault("funds", {})["ashare"] = res_a

    ok_h, res_h = _safe("fundflow 港股", collect_report_data_hk, data_date, args.topn, True)
    modules["funds_hk"] = "ok" if ok_h else f"failed: {str(res_h)[:240]}"
    if ok_h:
        data.setdefault("funds", {})["hk"] = res_h

    # ---- stocktrend：A股 + 港股个股走势 ----
    # out 路径提前，便于保留旧 stocktrend 真实数据（避免预览断供）
    out = os.path.join(ROOT, "build", "data", "snapshot.json")

    if not args.skip_stocktrend:
        from stocktrend.stocktrend_processor import collect_pages

        ok_s, pages = _safe("stocktrend", collect_pages, data_date, "all")
        if ok_s:
            for mkt in ("ashare", "hk"):
                if mkt in pages:
                    modules[f"stocktrend_{mkt}"] = "ok"
                    data.setdefault("stocktrend", {})[mkt] = pages[mkt]
                else:
                    modules[f"stocktrend_{mkt}"] = "skipped(无数据)"
        else:
            # 抓取失败：若旧文件已有真实 stocktrend 数据，保留之，不丢真实数据
            old_st = _load_old_stocktrend(out)
            if old_st:
                data["stocktrend"] = old_st
                old_d = _old_date(out)
                for mkt in ("ashare", "hk"):
                    modules[f"stocktrend_{mkt}"] = f"failed→preserved(旧 {old_d})"
            else:
                modules["stocktrend_ashare"] = f"failed: {str(pages)[:200]}"
                modules["stocktrend_hk"] = "failed"
    else:
        # 显式跳过：保留旧 stocktrend 真实数据（来自上次全量），仅刷新资金流
        old_st = _load_old_stocktrend(out)
        if old_st:
            data["stocktrend"] = old_st
            old_d = _old_date(out)
            modules["stocktrend_ashare"] = f"preserved(旧 {old_d})"
            modules["stocktrend_hk"] = f"preserved(旧 {old_d})"
        else:
            modules["stocktrend_ashare"] = "skipped(--skip-stocktrend, 无旧数据)"
            modules["stocktrend_hk"] = "skipped(--skip-stocktrend, 无旧数据)"

    if not data:
        raise SystemExit("[!] 所有模块抓取均失败，保留旧快照文件未改动。请检查网络/接口后重试。")

    payload = {
        "_meta": {
            "cache_scope": "preview_snapshot",
            "data_date": data_date,
            "saved_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": "项目统一真实收盘数据快照（fundflow 资金流 + stocktrend 个股走势）。预览/开发改页面统一读此单文件，无需 mock。",
            "modules": modules,
        },
        "data": data,
    }

    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, out)  # 原子替换，避免中断留下半截文件

    size = os.path.getsize(out)
    print(f"\n[✓] 统一快照已写出：{out}")
    print(f"    数据日期: {data_date} | 大小: {size / 1024:.1f} KB")
    print("    模块状态:")
    for k, v in modules.items():
        print(f"      - {k}: {v}")


if __name__ == "__main__":
    main()
