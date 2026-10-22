#!/usr/bin/env python3
"""给投稿系统用的轻量版 docx：插图按版面显示宽度重采样到 300 dpi，存成 JPEG（质量 92），正文不动。
用于系统提示「文件最好控制在 5M 以内，便于审稿」的情形；原图版 docx 另存，录用后按期刊要求交原图。

用法：docx_light.py <in.docx> <out.docx> [dpi=300]
依赖：Pillow。只处理 PNG 插图；其他格式原样保留。
"""
import io, re, sys, zipfile
from PIL import Image

SRC, OUT = sys.argv[1:3]
DPI = int(sys.argv[3]) if len(sys.argv) > 3 else 300
z = zipfile.ZipFile(SRC)
doc = z.read("word/document.xml").decode()
rels = z.read("word/_rels/document.xml.rels").decode()
ctypes = z.read("[Content_Types].xml").decode()

# 每个图片关系的最大显示宽度（pt）：VML 的 style="width:…pt" 和 DrawingML 的 wp:extent（EMU）
width = {}
for m in re.finditer(r'<v:shape [^>]*style="([^"]*)"[^>]*>.*?<v:imagedata r:id="([^"]+)"', doc, re.S):
    w = re.search(r"width:([\d.]+)pt", m.group(1))
    if w: width[m.group(2)] = max(width.get(m.group(2), 0), float(w.group(1)))
for m in re.finditer(r'<wp:extent cx="(\d+)"[^>]*/>.*?<a:blip r:embed="([^"]+)"', doc, re.S):
    width[m.group(2)] = max(width.get(m.group(2), 0), int(m.group(1)) / 12700)

new_media, renamed = {}, {}
for m in re.finditer(r'<Relationship [^>]*Id="([^"]+)"[^>]*Target="(media/[^"]+\.png)"[^>]*/>', rels):
    rid, tgt = m.group(1), m.group(2)
    if rid not in width: continue
    im = Image.open(io.BytesIO(z.read("word/" + tgt))).convert("RGB")
    tw = round(width[rid] / 72 * DPI)
    if im.width > tw:
        im = im.resize((tw, round(im.height * tw / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=92, dpi=(DPI, DPI))
    jt = tgt[:-4] + ".jpeg"
    new_media["word/" + jt] = buf.getvalue(); renamed["word/" + tgt] = "word/" + jt
    rels = rels.replace(f'Target="{tgt}"', f'Target="{jt}"')
if 'Extension="jpeg"' not in ctypes:
    ctypes = ctypes.replace("<Default ", '<Default Extension="jpeg" ContentType="image/jpeg"/><Default ', 1)

zo = zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED)
for it in z.infolist():
    if it.filename in renamed: continue
    data = z.read(it.filename)
    if it.filename == "word/_rels/document.xml.rels": data = rels.encode()
    elif it.filename == "[Content_Types].xml": data = ctypes.encode()
    zo.writestr(it, data)
for name, data in new_media.items():
    zo.writestr(name, data)
zo.close()
print(f"{len(new_media)} 幅图改为 {DPI} dpi JPEG")
