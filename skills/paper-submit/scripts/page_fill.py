#!/usr/bin/env python3
"""逐页报告 PDF 正文区的留白：最后一行内容以下空了多少（占版心高度的百分比），以及页内最大的连续空白带。

用法：page_fill.py <pdf> [--top-mm 26 --bottom-mm 15]
用于排版检查（paper-submit 的 references/preflight.md 第 4 节）：除末页和章节另起页外，留白超过约 20% 的页要调整。
依赖：Pillow、poppler-utils（pdftoppm）。
"""
import argparse, subprocess, tempfile, glob, os
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("pdf"); ap.add_argument("--top-mm", type=float, default=26); ap.add_argument("--bottom-mm", type=float, default=15)
a = ap.parse_args()
with tempfile.TemporaryDirectory() as d:
    subprocess.run(["pdftoppm", "-r", "40", "-gray", a.pdf, f"{d}/p"], check=True)
    pages = sorted(glob.glob(f"{d}/p-*.pgm"))
    for i, f in enumerate(pages, 1):
        im = Image.open(f); W, H = im.size; px = im.load()
        mm = H / 285.0                                   # 页高约 285 mm
        top, bot = int(a.top_mm * mm), H - int(a.bottom_mm * mm)
        rows = [any(px[x, y] < 200 for x in range(0, W, 2)) for y in range(top, bot)]
        ink = [k for k, r in enumerate(rows) if r]
        last = ink[-1] if ink else 0
        gap = run = 0
        for r in rows[:last + 1]:
            run = 0 if r else run + 1; gap = max(gap, run)
        h = bot - top
        print(f"p{i:02d} 底部留白 {100 * (h - last - 1) / h:4.0f}%  页内最大空白带 {100 * gap / h:4.0f}%")
