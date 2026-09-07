#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
post-build 渲染校验：构建完个股走势页后，校验「真正可见」的股票卡片数量，
避免结构性 HTML 错误（漏引号 / 标签错嵌）把后续整页吞进坏属性、渲染只剩 1 张卡片
却因源文件里仍有 32 个标记而漏检。

指标：只统计「在可见列表（.sector-grid 的直接子 .stock-item）里」的卡片——这正是用户
在浏览器里能看到的卡片数。坏页面里其余卡片会被嵌套进首个弹窗（.modal-overlay），
不再作为 sector-grid 的直接子，所以数量会从 32 跌到 4，一眼可分。

用法：
    python verify_render.py build/site/stocktrend_ashare.html:32 build/site/stocktrend_hk.html:40
    python verify_render.py build/site/stocktrend_ashare.html --expect 32
    python verify_render.py --auto build/site/   # 按文件名自动匹配预期值

退出码：全部通过=0；任一不通过=1（可接在 CI / 构建后卡住部署）。

解析优先序：
    1. 本机有 Chrome/Chromium -> `chrome --headless --dump-dom` 拿浏览器解析后的 DOM（最贴近真实渲染）
    2. 否则用 BeautifulSoup(html5lib) 解析文件（html5lib 实现 W3C HTML5 解析算法，与浏览器一致）
    3. 若 bs4/html5lib 缺失 -> 退回内置 html.parser 做轻量统计
"""
import argparse
import os
import shutil
import subprocess
import sys
from html.parser import HTMLParser

# 文件名 -> 预期「可见列表卡片数」的默认映射
DEFAULT_EXPECT = {
    "stocktrend_ashare.html": 32,
    "stocktrend_hk.html": 40,
}

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_chrome():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def count_with_bs4(html, use_chrome_dom=False, chrome_path=None):
    """用 BeautifulSoup 解析，返回可见列表卡片数。use_chrome_dom=True 时先经 Chrome 解析。"""
    from bs4 import BeautifulSoup

    if use_chrome_dom and chrome_path:
        try:
            dom = subprocess.run(
                [chrome_path, "--headless=new", "--no-sandbox", "--disable-gpu",
                 "--dump-dom", "file://" + os.path.abspath(html)],
                capture_output=True, text=True, timeout=120,
            ).stdout
            if dom.strip():
                html = dom
        except Exception as e:
            print(f"  [warn] Chrome --dump-dom 失败，退回直接解析: {e}", file=sys.stderr)
    try:
        soup = BeautifulSoup(html, "html5lib")
    except Exception:
        soup = BeautifulSoup(html, "lxml")
    total = 0
    per_grid = []
    for g in soup.find_all("div", class_="sector-grid"):
        n = len(g.find_all("div", class_="stock-item", recursive=False))
        per_grid.append(n)
        total += n
    return total, per_grid


class _StdlibCounter(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # 元素栈：(tag, classes_set)
        self.total = 0
        self.per_grid = []

    def _classes(self, attrs):
        for k, v in attrs:
            if k == "class" and v:
                return set(v.split())
        return set()

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        # 当前父元素（入栈前栈顶）
        if tag == "div" and "stock-item" in classes:
            parent = self.stack[-1][1] if self.stack else set()
            if "sector-grid" in parent:
                self.total += 1
        # sector-grid 开：记录一个新 grid 起点
        if tag == "div" and "sector-grid" in classes:
            self.per_grid.append(0)
        elif tag == "div" and "stock-item" in classes and self.stack and "sector-grid" in self.stack[-1][1]:
            if self.per_grid:
                self.per_grid[-1] += 1
        if tag not in self.VOID:
            self.stack.append((tag, classes))

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        # 弹到匹配的起始标签
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return
        # 无匹配则忽略（宽容解析）


def count_with_stdlib(html):
    p = _StdlibCounter()
    p.feed(html)
    return p.total, p.per_grid


def count_visible(file_path, use_chrome=True):
    chrome_path = find_chrome() if use_chrome else None
    if chrome_path:
        try:
            return count_with_bs4(file_path, use_chrome_dom=True, chrome_path=chrome_path)
        except Exception as e:
            print(f"  [warn] Chrome 路径解析失败，退回 html5lib: {e}", file=sys.stderr)
    # 非 Chrome 路径：读取文件内容再交给解析器（不要直接把路径当 HTML）
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()
    try:
        from bs4 import BeautifulSoup  # noqa: F401
        return count_with_bs4(html, use_chrome_dom=False, chrome_path=None)
    except Exception:
        print("  [warn] bs4/html5lib 不可用，退回内置 html.parser", file=sys.stderr)
        return count_with_stdlib(html)


def parse_arg_files(args):
    files = []
    for spec in args.files:
        if ":" in spec:
            path, _, exp = spec.rpartition(":")
            files.append((path, int(exp)))
        else:
            base = os.path.basename(spec)
            exp = args.expect
            if exp is None:
                exp = DEFAULT_EXPECT.get(base)
            files.append((spec, exp))
    return files


def main():
    ap = argparse.ArgumentParser(description="post-build 渲染校验：可见股票卡片数")
    ap.add_argument("files", nargs="*", help="文件路径，可用 path:EXPECT 指定预期卡片数")
    ap.add_argument("--expect", type=int, default=None, help="默认预期卡片数（未用 path:EXPECT 时）")
    ap.add_argument("--auto", metavar="DIR", help="扫描目录，按文件名自动匹配预期值")
    ap.add_argument("--no-chrome", action="store_true", help="强制不使用 Chrome，仅用解析器")
    args = ap.parse_args()

    files = parse_arg_files(args)
    if args.auto:
        for name, exp in DEFAULT_EXPECT.items():
            p = os.path.join(args.auto, name)
            if os.path.exists(p):
                files.append((p, exp))

    if not files:
        ap.error("未指定任何文件（用 FILE:EXPECT 或 --auto DIR）")

    all_ok = True
    for path, expect in files:
        if not os.path.exists(path):
            print(f"[FAIL] 文件不存在: {path}")
            all_ok = False
            continue
        total, per = count_visible(path, use_chrome=not args.no_chrome)
        if expect is None:
            print(f"[??] {os.path.basename(path)}: 可见列表卡片={total} (per grid {per})，未设预期值，跳过断言")
            continue
        status = "PASS" if total == expect else "FAIL"
        if total != expect:
            all_ok = False
        print(f"[{status}] {os.path.basename(path)}: 可见列表卡片={total} (预期 {expect})  per-grid={per}")

    if not all_ok:
        print("\n校验未通过：可见卡片数与预期不符，疑似结构性 HTML 错误，已阻断部署。")
        sys.exit(1)
    print("\n校验通过：可见卡片数与预期一致。")
    sys.exit(0)


if __name__ == "__main__":
    main()
