#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从统一真实数据快照渲染预览页：读 build/data/snapshot.json -> preview/*.html。

改完页面后直接跑本脚本即可基于真实数据看效果，不依赖 mock。
所有页面统一从单一快照文件取数。

用法：
    python preview_from_snapshot.py                 # 渲染 fundflow + stocktrend 全部预览
    python preview_from_snapshot.py --only fundflow  # 仅 fundflow 预览
    python preview_from_snapshot.py --only stocktrend # 仅 stocktrend 预览
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.storage import read_json
from fundflow.fundflow_ui_renderer import write_html as ff_write_html
from stocktrend.stocktrend_ui_renderer import render_page as st_render_page
from stocktrend.stocktrend_ui_renderer import write_html as st_write_html

SNAP = os.path.join(ROOT, "build", "data", "snapshot.json")
PREVIEW = os.path.join(ROOT, "preview")


def _load() -> dict:
    if not os.path.exists(SNAP):
        raise SystemExit(f"[!] 找不到统一快照文件：{SNAP}\n    请先运行：python make_snapshot.py")
    payload = read_json(SNAP)
    return payload.get("data") if isinstance(payload, dict) and "data" in payload else payload


def build_fundflow(data: dict) -> list:
    funds = data.get("funds", {})
    made: list = []
    for mkt in ("ashare", "hk"):
        if mkt not in funds:
            continue
        out = os.path.join(PREVIEW, f"fundflow_{mkt}_preview.html")
        try:
            ff_write_html(out, funds[mkt])
            made.append(out)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] fundflow {mkt} 预览渲染失败：{exc}\n{traceback.format_exc()}")
    if not made:
        print("[!] 快照中无 fundflow 数据，跳过")
    return made


def build_stocktrend(data: dict) -> list:
    st = data.get("stocktrend", {})
    made: list = []
    for mkt in ("ashare", "hk"):
        if mkt not in st:
            continue
        out = os.path.join(PREVIEW, f"stocktrend_{mkt}_preview.html")
        try:
            st_write_html(out, st_render_page(st[mkt]))
            made.append(out)
        except Exception as exc:  # noqa: BLE001
            print(f"[!] stocktrend {mkt} 预览渲染失败：{exc}\n{traceback.format_exc()}")
    if not made:
        print("[!] 快照中无 stocktrend 数据，跳过")
    return made


def main() -> None:
    parser = argparse.ArgumentParser(description="从统一快照渲染预览页")
    parser.add_argument("--only", choices=["fundflow", "stocktrend", "all"], default="all")
    args = parser.parse_args()

    data = _load()
    os.makedirs(PREVIEW, exist_ok=True)
    made: list = []
    if args.only in ("all", "fundflow"):
        made += build_fundflow(data)
    if args.only in ("all", "stocktrend"):
        made += build_stocktrend(data)

    if made:
        print(f"[✓] 预览已写出 {len(made)} 个：")
        for p in made:
            print(f"    {p}")
    else:
        print("[!] 未生成任何预览（快照缺少对应模块数据）")


if __name__ == "__main__":
    main()
