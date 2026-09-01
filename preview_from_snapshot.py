#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从真实数据快照渲染预览页：读 build/data/fundflow_snapshot.json -> preview/fundflow_preview.html。

改完页面后直接跑本脚本即可基于真实数据看效果，不依赖 mock。

用法：
    python preview_from_snapshot.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from common.storage import read_json
from fundflow.fundflow_ui_renderer import write_html

SNAP = os.path.join(ROOT, "build", "data", "fundflow_snapshot.json")
OUT = os.path.join(ROOT, "preview", "fundflow_preview.html")


def main() -> None:
    if not os.path.exists(SNAP):
        raise SystemExit(f"[!] 找不到快照文件：{SNAP}\n    请先运行：python make_snapshot.py")
    payload = read_json(SNAP)
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    write_html(OUT, data)
    print(f"[✓] 预览已写出：{OUT}")


if __name__ == "__main__":
    main()
