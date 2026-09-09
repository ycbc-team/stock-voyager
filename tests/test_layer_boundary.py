#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分层边界回归测试
================
确保 fundflow_data_fetcher 只含「请求」逻辑，纯本地处理已迁入
fundflow_processor。若有人在 fetcher 里重新塞入处理函数，本测试失败。

运行方式：
  python tests/test_layer_boundary.py        # 无 pytest 依赖也可跑
  pytest tests/test_layer_boundary.py        # 或走 pytest（CI 推荐）
"""
import inspect
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fundflow import fundflow_data_fetcher as F
from fundflow import fundflow_processor as P

# 纯本地处理函数：必须只在 processor 出现，绝不在 fetcher
PROCESSING_FUNCS = [
    "compute_index_note",
    "pool_to_list",
    "with_northbound_turnover_ratio",
    "compute_us_market_breadth",
    "derive_breadth_from_rows",
    "compute_prev_total",
]

# 处理函数命名关键字：fetcher 内一旦出现此类名字的函数定义即疑似违规
# （用于捕捉未来新增的、不在 PROCESSING_FUNCS 名单里的处理函数）
PROCESSING_KEYWORDS = (
    "compute", "derive", "note", "ratio", "breadth",
    "to_list", "prev_total", "aggregate", "enrich",
)

# 合法的请求入口前缀：带这些前缀的函数即便含处理关键字也视为「请求函数」
# （如 fetch_market_breadth / fetch_hk_market_breadth 确实发请求）
REQUEST_PREFIXES = ("fetch", "load", "build", "_fetch", "_load", "_build")


def _fetcher_func_names() -> list:
    src = inspect.getsource(F)
    return re.findall(r"^def (\w+)\(", src, flags=re.M)


def test_processing_not_in_fetcher():
    for fn in PROCESSING_FUNCS:
        assert not hasattr(F, fn), (
            f"[分层违规] 纯处理函数 {fn} 出现在 fetcher，"
            f"必须迁到 fundflow_processor.py"
        )


def test_processing_in_processor():
    missing = [fn for fn in PROCESSING_FUNCS if not hasattr(P, fn)]
    assert not missing, f"[分层缺失] 以下处理函数不在 processor：{missing}"


def test_no_processing_named_funcs_in_fetcher():
    names = _fetcher_func_names()
    bad = [
        n for n in names
        if any(k in n for k in PROCESSING_KEYWORDS)
        and not n.startswith(REQUEST_PREFIXES)
    ]
    assert not bad, f"[分层违规] fetcher 内出现疑似处理函数定义：{bad}"


if __name__ == "__main__":
    test_processing_not_in_fetcher()
    test_processing_in_processor()
    test_no_processing_named_funcs_in_fetcher()
    print("OK: 分层边界校验通过 — fetcher 仅含请求逻辑，纯处理已迁入 processor")
