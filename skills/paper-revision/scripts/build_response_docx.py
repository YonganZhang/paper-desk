#!/usr/bin/env python3
"""Render a point-by-point response letter from response.md into Word (and optionally PDF), with checks.

Usage:
    uv run --no-project --with python-docx python build_response_docx.py response.md \
        -o Response_to_Reviewers.docx [--pdf] --manuscript-text REVISED.(docx|pdf|txt) [--expect-comments N]
    python3 -I build_response_docx.py response.md --check [...]   # checks only, no python-docx needed
    (with python-docx installed, plain `python3 build_response_docx.py ...` works as well)

Requires: Python 3.9+; python-docx for rendering (not for --check); LibreOffice (soffice) for --pdf;
pdftotext (poppler-utils) when --manuscript-text is a PDF.
Syntax of response.md: ../references/response-letter-format.md ("response.md 语法").
Tests of the checks: ../tests/test_response_checks.py (in the skill folder: python3 -I -m unittest discover -s tests).
Colours: reviewer/editor text (`>` lines, rendered literally), headings, opening and closing in black; author
responses blue 0070C0; `<red>` spans red EE0000 (new figure/table elements only).

Checks print BLOCK (must fix before submission) or WARN (review) lines:
  BLOCK  front matter missing or still the template text; placeholders (placeholder/TODO/TBD/FIXME/XX/??);
         a comment without a response (each quote block starting with a number such as "1.", "(2)", "Q3" is one
         comment; an unnumbered quote block directly before it is treated as its preface); comment count differs
         from --expect-comments; a [[ ]] quote that is missing, differs at the end (citation/punctuation left out),
         only partly found, non-contiguous or uncheckable in
         --manuscript-text (comparison keeps case, digits, symbols and Unicode; only whitespace, quote/dash styles
         and PDF line-break hyphens are normalised); image file not found; a reviewer comment whose response shows
         no manuscript change (none of: a [[ ]] revised passage, a new figure/table, a sentence saying what was
         deleted/removed, a cross-reference such as "see our response to R1.5", or a
         <!-- no-change: reason --> line for a comment that requests nothing).
  WARN   "Dear sir"; a "revised title" label; repeated thanks in one response paragraph; a response that copies the
         comment; a [[ ]] block without a "The revised text ... reads (in ...)" label; title or journal of the front
         matter not used in the opening paragraph; an image row scaled down to fit the text width; an editor
         comment (section heading contains "editor") whose response shows no manuscript change or cross-reference.
Other single-line <!-- ... --> comments are notes for the author and are not rendered.
Exit code: 0 = no BLOCK (and no WARN with --strict); 1 = BLOCK found (unless --draft), or WARN with --strict;
           2 = bad arguments. The .docx/.pdf are still written when only BLOCK/WARN issues exist, for preview.
"""
from __future__ import annotations

import argparse
import difflib
import html
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

BLUE = (0x00, 0x70, 0xC0)
RED = (0xEE, 0x00, 0x00)
BLACK = (0x00, 0x00, 0x00)
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)(\{[^}]*\})?")
PLACEHOLDER_RE = re.compile(r"\b(placeholders?|TODO|TBD|FIXME)\b|XX+|\?\?|\[citation", re.IGNORECASE)
THANKS_RE = re.compile(r"\b(thank you|we thank|thanks|grateful)\b", re.IGNORECASE)
NUMBERED_RE = re.compile(r"^\s*(\(?\d+[a-z]?[.):]|\(?[ivx]{1,5}\)|Q\s*\d+|Comment\s*\d+|R\d+[.\-]\d+|[•●▪])", re.IGNORECASE)
LABEL_RE = re.compile(r"^\s*the revised (text|title|sentence|sentences|paragraph|caption|table)\b[^:]{0,80}:?\s*$", re.IGNORECASE)
DELETED_RE = re.compile(r"\b(deleted|removed)\b", re.IGNORECASE)
XREF_RE = re.compile(r"\b(addressed in|(see|refer to) (also )?(our |the )?(responses? to|reply to)"
                     r"|(see|refer to) (also )?(R\d|Reviewer\s*#?\s*\d|Comment\s*\d))", re.IGNORECASE)
EDITOR_RE = re.compile(r"\beditor", re.IGNORECASE)  # "Associate Editor", "Editor-in-Chief", "Editorial Office"
CHANGE_KINDS = ("revised", "figure/table", "deleted", "xref")  # evidence of a manuscript change, strongest first
TEMPLATE_DEFAULTS = ("Full Title of the Manuscript", "Journal Name", "Corresponding Author Name")


@dataclass
class Block:
    kind: str  # heading | para | quote | revised | bullet | table | images | caption | nochange
    lines: list = field(default_factory=list)
    color: tuple = BLACK
    lineno: int = 0
    group: int = 0  # [[ ]] passage number for revised blocks

    @property
    def text(self) -> str:
        return " ".join(self.lines)


def parse_front_matter(text: str):
    meta = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"').strip("'")
            nl = text.find("\n", end + 4)
            cut = nl + 1 if nl != -1 else len(text)
            return meta, text[cut:], text[:cut].count("\n")
    return meta, text, 0


def parse_blocks(body: str, line_offset: int):
    blocks: list[Block] = []
    mode = "opening"  # opening -> sections -> closing
    cur: Block | None = None
    in_revised = False
    group = 0

    def flush():
        nonlocal cur
        if cur is not None and cur.lines:
            blocks.append(cur)
        cur = None

    def body_color():
        return BLUE if mode == "sections" else BLACK

    for i, raw in enumerate(body.splitlines(), start=line_offset + 1):
        s = raw.strip()
        if in_revised:
            if s == "]]":
                flush()
                in_revised = False
            elif not s:
                flush()
                cur = Block("revised", color=BLUE, lineno=i, group=group)
            else:
                if cur is None:
                    cur = Block("revised", color=BLUE, lineno=i, group=group)
                cur.lines.append(s)
            continue
        if s == "<!-- closing -->":
            flush()
            mode = "closing"
            continue
        if s == "[[":
            flush()
            in_revised = True
            group += 1
            cur = Block("revised", color=BLUE, lineno=i, group=group)
            continue
        if not s:
            flush()
            continue
        note = re.fullmatch(r"<!--\s*(.*?)\s*-->", s)
        if note:
            flush()
            nc = re.match(r"no-change\s*:?\s*(.*)", note.group(1), re.IGNORECASE)
            if nc:
                blocks.append(Block("nochange", [nc.group(1).strip()], BLACK, i))
            continue  # other comment lines are author notes and are not rendered
        if s.startswith("# "):
            flush()
            if mode == "opening":
                mode = "sections"
            blocks.append(Block("heading", [s[2:].strip()], BLACK, i))
            continue
        if s.startswith(">"):
            content = s[1:].strip()
            if cur is None or cur.kind != "quote":
                flush()
                cur = Block("quote", color=BLACK, lineno=i)
            if content:
                cur.lines.append(content)
            elif cur.lines:
                flush()
                cur = Block("quote", color=BLACK, lineno=i)
            continue
        if s.startswith("|"):
            if cur is None or cur.kind != "table":
                flush()
                cur = Block("table", color=BLACK, lineno=i)
            cur.lines.append(s)
            continue
        if IMG_RE.search(s) and not IMG_RE.sub("", s).strip():
            flush()
            blocks.append(Block("images", [s], BLACK, i))
            continue
        if s.startswith("Caption:"):
            flush()
            blocks.append(Block("caption", [s[len("Caption:"):].strip()], BLACK, i))
            continue
        if re.match(r"^[-*] ", s):
            flush()
            blocks.append(Block("bullet", [s[2:].strip()], body_color(), i))
            continue
        if cur is None or cur.kind != "para":
            flush()
            cur = Block("para", color=body_color(), lineno=i)
        cur.lines.append(s)
    if in_revised:
        raise SystemExit(f"ERROR: unterminated [[ block starting near line {cur.lineno if cur else '?'}")
    flush()
    return blocks


def strip_markup(text: str) -> str:
    """Remove response.md markup from author text (bold/italic markers and tags)."""
    text = re.sub(r"</?(red|sup|sub)>", "", text)
    return text.replace("**", "").replace("\\*", "\x00").replace("*", "").replace("\x00", "*")


def strip_tags(text: str) -> str:
    """Remove only the tags allowed inside [[ ]] quotes; every other character is part of the quote."""
    return re.sub(r"</?(red|sup|sub)>", "", text).replace("**", "")


def canon(text: str) -> str:
    """Canonical form for verbatim comparison: decode entities, NFC, unify quote/dash/space styles and collapse
    whitespace. Case, digits, symbols, super/subscript characters and word boundaries are kept."""
    text = unicodedata.normalize("NFC", html.unescape(text))
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-"), ("−", "-"),
                 ("\u00ad", ""), ("\u00a0", " "), ("\u2009", " "), ("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def load_manuscript_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":  # reading order (not -layout), so two-column pages are not interleaved
        return subprocess.run(["pdftotext", str(path), "-"], capture_output=True, text=True, check=True, timeout=300).stdout
    if suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf8")
        paras = re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)
        return "\n".join(html.unescape("".join(re.findall(r"<[wm]:t[^>]*>([^<]*)</[wm]:t>", p))) for p in paras)
    return path.read_text(encoding="utf8", errors="replace")


def quote_status(quote: str, ms: tuple[str, str]) -> str:
    def has(x):
        return any(x in m for m in ms)
    q = canon(strip_tags(quote))
    if not re.search(r"\w", q):
        return "uncheckable"
    if has(q):
        return "found"
    trimmed = q.rstrip(".;:")
    if trimmed != q and len(trimmed) > 20 and has(trimmed):
        return "differs-at-end"  # e.g. citation or punctuation after the quoted sentence was left out
    parts = [canon(strip_tags(x)) for x in re.split(r"(?<=[.!?;])\s+", quote) if x.strip()]
    if len(parts) > 1 and all(has(x) for x in parts):
        return "non-contiguous"  # every sentence exists, but not as one continuous passage
    if len(q) > 120 and has(q[:60]) and has(q[-60:]):
        return "partial"  # start and end found, middle differs
    return "missing"


def run_checks(meta, blocks, md_dir: Path, manuscript: Path | None, expect_comments: int | None):
    issues = []  # (level, message)

    def block(msg):
        issues.append(("BLOCK", msg))

    def warn(msg):
        issues.append(("WARN", msg))

    for key in ("manuscript_id", "title", "journal"):
        if not meta.get(key):
            block(f"front matter: missing '{key}'")
    for key, val in meta.items():
        if PLACEHOLDER_RE.search(val) or val in TEMPLATE_DEFAULTS:
            block(f"front matter '{key}': still template/placeholder text '{val}'")

    opening = " ".join(strip_markup(b.text) for b in blocks if b.kind == "para" and b.color == BLACK and not any(
        x.kind == "heading" for x in blocks[: blocks.index(b)]))
    if meta.get("title") and canon(meta["title"]).lower() not in canon(opening).lower():
        warn("opening paragraph does not contain the front-matter title")
    if meta.get("journal") and meta["journal"].lower() not in opening.lower():
        warn("opening paragraph does not contain the front-matter journal name")

    pending = None  # {"line", "text", "numbered", "preface", "kinds", "nochange"}
    resp = None  # response being read: {"line", "kinds", "nochange", "editor"}
    section = ""
    change_report = []  # one entry per answered comment: where its manuscript change is shown
    units = 0
    seen_ids = set()
    last_label_idx = -10

    def close_response():
        nonlocal resp
        if resp is None:
            return
        kind = next((k for k in CHANGE_KINDS if k in resp["kinds"]), None)
        if kind is None and resp["nochange"] is not None:
            kind = "no-change"
            if not re.search(r"\w", resp["nochange"]):
                block(f"line {resp['line']}: <!-- no-change: --> needs a reason")
        if kind is None:
            msg = (f"line {resp['line']}: response shows no manuscript change — paste the revised text in [[ ]], say "
                   "what was deleted/removed, cross-reference the response that holds the change, or mark a comment "
                   "that requests nothing with <!-- no-change: reason -->")
            (warn if resp["editor"] else block)(msg)
        entry = {"line": resp["line"], "evidence": kind or "none"}
        if kind == "no-change":
            entry["reason"] = resp["nochange"]
        change_report.append(entry)
        resp = None

    def new_pending(line, text, numbered, preface):
        return {"line": line, "text": text, "numbered": numbered, "preface": preface, "kinds": set(), "nochange": None}

    for idx, b in enumerate(blocks):
        t = b.text
        where = f"line {b.lineno}"
        hit = PLACEHOLDER_RE.search(t)
        if hit:
            block(f"{where}: placeholder-like text {hit.group(0)!r}")
        for d in TEMPLATE_DEFAULTS:
            if d in t:
                block(f"{where}: template text {d!r} not replaced")
        if re.search(r"dear sir\b", t, re.IGNORECASE):
            warn(f"{where}: salutation 'Dear sir' — use 'Dear Editor,' or the editor's name")
        if re.search(r"revised title", t, re.IGNORECASE):
            warn(f"{where}: label says 'revised title' — confirm the quoted text really is the title")
        if b.kind in ("para", "bullet") and b.color == BLUE and len(THANKS_RE.findall(t)) >= 2:
            warn(f"{where}: thanks repeated within one response paragraph")

        if b.kind == "heading":
            close_response()
            if pending:
                block(f"line {pending['line']}: comment has no response")
            pending = None
            seen_ids = set()
            section = b.text
            continue
        if b.kind == "nochange":
            target = resp or pending
            if target is None:
                warn(f"{where}: <!-- no-change --> line is not inside a response")
            else:
                target["nochange"] = b.text
            continue
        if b.kind in ("revised", "images", "table"):
            target = resp or pending
            if target is not None:
                target["kinds"].add("revised" if b.kind == "revised" else "figure/table")
        if b.kind == "quote":
            close_response()
            numbered = bool(NUMBERED_RE.match(b.lines[0]))
            if numbered:
                cid = re.sub(r"\W", "", NUMBERED_RE.match(b.lines[0]).group(1)).lower()
                if cid and cid in seen_ids:
                    block(f"{where}: comment number {NUMBERED_RE.match(b.lines[0]).group(1)!r} appears twice in this section")
                seen_ids.add(cid)
            prev_is_quote = idx > 0 and blocks[idx - 1].kind == "quote"
            if pending and prev_is_quote and not (numbered and pending["numbered"]):
                if numbered:  # unnumbered preface ("Comments to the Author") followed by the first numbered comment
                    pending = new_pending(b.lineno, t, True, False)
                else:  # another paragraph of the same comment
                    pending["text"] += "\n" + t
                    pending["preface"] = False
            else:
                if pending and not pending["preface"]:
                    block(f"line {pending['line']}: comment has no response")
                pending = new_pending(b.lineno, t, numbered, not numbered)
            continue
        if b.color == BLUE and b.kind in ("para", "bullet"):
            plain = strip_markup(t)
            is_label = bool(LABEL_RE.match(plain)) or bool(re.match(r"^\s*the revised .{0,80}reads", plain, re.IGNORECASE)) and len(plain) < 140
            if is_label:
                last_label_idx = idx
            if pending and not is_label:
                answer = canon(strip_markup(re.sub(r"^\s*(\*\*)?[A-Za-z ]{0,20}response:\s*(\*\*)?", "", t, flags=re.IGNORECASE)))
                if not re.search(r"\w", answer):
                    block(f"{where}: empty response")
                else:
                    ratio = difflib.SequenceMatcher(None, canon(pending["text"]), answer).ratio()
                    if ratio >= 0.85:
                        warn(f"{where}: response looks like a copy of the comment above (similarity {ratio:.2f})")
                    units += 1
                    resp = {"line": pending["line"], "kinds": set(pending["kinds"]), "nochange": pending["nochange"],
                            "editor": bool(EDITOR_RE.search(section))}
                pending = None
            if resp is not None:
                if DELETED_RE.search(plain):
                    resp["kinds"].add("deleted")
                if XREF_RE.search(plain):
                    resp["kinds"].add("xref")
        if b.kind == "revised" and blocks[idx - 1].kind != "revised" and idx - last_label_idx > 2:
            warn(f"{where}: [[ ]] block without a preceding 'The revised text ... reads (in ...)' label")
        if b.kind == "images":
            for m in IMG_RE.finditer(t):
                if not (md_dir / m.group(1)).exists():
                    block(f"{where}: image not found: {m.group(1)}")
    close_response()
    if pending:
        block(f"line {pending['line']}: comment has no response")
    if expect_comments is not None and units != expect_comments:
        block(f"{units} answered comments found, --expect-comments says {expect_comments}")

    quote_report = []
    if manuscript is not None:
        raw = load_manuscript_text(manuscript)
        ms = (canon(raw), canon(re.sub(r"(?<=\w)-[ \t]*\n\s*(?=\w)", "", raw)))
        passages = {}
        for b in blocks:
            if b.kind == "revised":
                passages.setdefault(b.group, []).append(b)
        for grp in passages.values():
            status = quote_status(" ".join(x.text for x in grp), ms)
            quote_report.append((grp[0].lineno, status))
            if status != "found":
                block(f"line {grp[0].lineno}: revised-text quote check = {status}; copy the passage from the final manuscript")
    return issues, units, quote_report, change_report


# ---------------------------------------------------------------- rendering (python-docx)

def render(meta, blocks, md_dir: Path, out: Path):
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Emu, Inches, Mm, Pt, RGBColor

    notes = []
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    sec.top_margin = sec.bottom_margin = Inches(1)
    sec.left_margin = sec.right_margin = Inches(1.25)
    text_width = sec.page_width - sec.left_margin - sec.right_margin

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.0
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.styles["Footer"].font.size = Pt(9)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    fp._p.append(fld)

    def style_run(run, color, bold=False, italic=False, font=None, size=None):
        run.bold, run.italic = bold, italic
        run.font.color.rgb = RGBColor(*color)
        if font:
            run.font.name = font
            run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font)
        if size:
            run.font.size = Pt(size)

    def add_inline(par, text, color, base_bold=False, font=None, size=None):
        tokens = re.split(r"(\*\*|(?<!\\)\*|<red>|</red>|<sup>|</sup>|<sub>|</sub>)", text)
        bold, italic, red, sup, sub = base_bold, False, False, False, False
        for tok in tokens:
            if tok == "**":
                bold = not bold
            elif tok == "*":
                italic = not italic
            elif tok in ("<red>", "</red>"):
                red = tok == "<red>"
            elif tok in ("<sup>", "</sup>"):
                sup = tok == "<sup>"
            elif tok in ("<sub>", "</sub>"):
                sub = tok == "<sub>"
            elif tok:
                run = par.add_run(tok.replace("\\*", "*"))
                style_run(run, RED if red else color, bold, italic, font, size)
                run.font.superscript, run.font.subscript = sup, sub

    def set_three_line(table):
        borders = OxmlElement("w:tblBorders")
        for edge, val in (("top", "single"), ("left", "nil"), ("bottom", "single"), ("right", "nil"), ("insideH", "nil"), ("insideV", "nil")):
            el = OxmlElement(f"w:{edge}")
            el.set(qn("w:val"), val)
            if val == "single":
                el.set(qn("w:sz"), "8")
                el.set(qn("w:color"), "000000")
            borders.append(el)
        table._tbl.tblPr.append(borders)
        for cell in table.rows[0].cells:
            tcb = OxmlElement("w:tcBorders")
            b = OxmlElement("w:bottom")
            for k, v in (("w:val", "single"), ("w:sz", "4"), ("w:color", "000000")):
                b.set(qn(k), v)
            tcb.append(b)
            cell._tc.get_or_add_tcPr().append(tcb)

    for line in (f"Manuscript {meta.get('manuscript_id', '')}", "Response to Reviewers"):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        add_inline(p, line, BLACK, base_bold=True, size=12)

    for k, b in enumerate(blocks):
        if b.kind == "heading":
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.keep_with_next = True
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            add_inline(p, b.text, BLACK, base_bold=True, size=12)
        elif b.kind == "quote":  # reviewer/editor words: literal text, no markup interpretation
            style_run(doc.add_paragraph().add_run(b.text), BLACK)
        elif b.kind == "revised":
            first = not (k and blocks[k - 1].kind == "revised" and blocks[k - 1].group == b.group)
            last = not (k + 1 < len(blocks) and blocks[k + 1].kind == "revised" and blocks[k + 1].group == b.group)
            literal = b.text.replace("**", "").replace("*", "\\*")  # quotes keep operators such as a*b literally
            add_inline(doc.add_paragraph(), ("[" if first else "") + literal + ("]" if last else ""), BLUE)
        elif b.kind == "para":
            add_inline(doc.add_paragraph(), b.text, b.color)
        elif b.kind == "bullet":
            add_inline(doc.add_paragraph(style="List Bullet"), b.text, b.color)
        elif b.kind == "caption":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = True
            add_inline(p, b.text, BLACK, base_bold=True, font="Arial", size=8)
        elif b.kind == "images":
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.keep_with_next = True  # keep panels and caption together
            imgs = list(IMG_RE.finditer(b.text))
            gap = Inches(0.1)
            avail = text_width - gap * (len(imgs) - 1)
            asked = []
            for m in imgs:
                wm = re.search(r"width=([0-9.]+)in", m.group(2) or "")
                asked.append(Inches(float(wm.group(1))) if wm else None)
            free = [a for a in asked if a is None]
            fixed = sum(a for a in asked if a is not None)
            default = int((avail - fixed) / len(free)) if free and avail - fixed > Inches(1) * len(free) else int(Inches(1.5))
            widths = [a if a is not None else min(default, Inches(6)) for a in asked]
            if sum(widths) > avail:
                scale = avail / sum(widths)
                widths = [int(w * scale) for w in widths]
                notes.append(f"line {b.lineno}: images scaled to {scale:.0%} to fit the text width")
            for m, w in zip(imgs, widths):
                p.add_run().add_picture(str(md_dir / m.group(1)), width=Emu(w))
                p.add_run(" ")
        elif b.kind == "table":
            sep = next((r for r in b.lines if re.match(r"^\|(\s*:?-{2,}:?\s*\|)+\s*$", r)), None)
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in b.lines if r is not sep]
            if not cells:
                continue
            ncol = max(len(r) for r in cells)
            aligns = []
            for spec in (sep.strip().strip("|").split("|") if sep else []):
                spec = spec.strip()
                aligns.append(WD_ALIGN_PARAGRAPH.LEFT if spec.startswith(":") and not spec.endswith(":")
                              else WD_ALIGN_PARAGRAPH.RIGHT if spec.endswith(":") and not spec.startswith(":")
                              else WD_ALIGN_PARAGRAPH.CENTER)
            table = doc.add_table(rows=len(cells), cols=ncol)
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = True
            for ri, row in enumerate(cells):
                for ci in range(ncol):
                    par = table.cell(ri, ci).paragraphs[0]
                    par.alignment = aligns[ci] if ci < len(aligns) else WD_ALIGN_PARAGRAPH.CENTER
                    add_inline(par, row[ci] if ci < len(row) else "", BLACK, font="Arial", size=8)
            set_three_line(table)
            doc.add_paragraph()
    doc.save(str(out))
    return notes


def to_pdf(docx_path: Path) -> Path:
    # keep the LibreOffice profile next to the output, so a small /tmp or a running LibreOffice does not interfere
    with tempfile.TemporaryDirectory(prefix=".lo-profile-", dir=docx_path.resolve().parent) as profile:
        subprocess.run(
            ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path)],
            check=True, capture_output=True, timeout=300,
        )
    pdf = docx_path.with_suffix(".pdf")
    if not pdf.exists():
        raise SystemExit("ERROR: LibreOffice did not produce a PDF")
    return pdf


def main():
    ap = argparse.ArgumentParser(description="Render response.md into a Word response letter, with checks.")
    ap.add_argument("source", type=Path, help="response.md")
    ap.add_argument("-o", "--output", type=Path, help="output .docx (default: <source>.docx)")
    ap.add_argument("--pdf", action="store_true", help="also export PDF next to the .docx via LibreOffice")
    ap.add_argument("--check", action="store_true", help="run checks only, do not render")
    ap.add_argument("--manuscript-text", type=Path, help="final revised manuscript (.docx/.pdf/.txt) to verify [[ ]] quotes")
    ap.add_argument("--expect-comments", type=int, help="number of comments in the decision letter / tracker")
    ap.add_argument("--draft", action="store_true", help="preview mode: BLOCK issues do not change the exit code")
    ap.add_argument("--strict", action="store_true", help="WARN issues also give exit code 1")
    args = ap.parse_args()
    if not args.source.exists():
        print(f"ERROR: {args.source} not found", file=sys.stderr)
        sys.exit(2)
    if args.manuscript_text is not None and not args.manuscript_text.exists():
        print(f"ERROR: {args.manuscript_text} not found", file=sys.stderr)
        sys.exit(2)

    meta, body, offset = parse_front_matter(args.source.read_text(encoding="utf8"))
    blocks = parse_blocks(body, offset)
    md_dir = args.source.resolve().parent
    issues, units, quote_report, change_report = run_checks(meta, blocks, md_dir, args.manuscript_text, args.expect_comments)

    outputs = {}
    missing_image = any(lvl == "BLOCK" and "image not found" in msg for lvl, msg in issues)
    if not args.check and not missing_image:
        out = args.output or args.source.with_suffix(".docx")
        for note in render(meta, blocks, md_dir, out):
            issues.append(("WARN", note))
        outputs["docx"] = str(out)
        if args.pdf:
            outputs["pdf"] = str(to_pdf(out))
    for lvl, msg in issues:
        print(f"{lvl} {msg}")

    n_block = sum(1 for lvl, _ in issues if lvl == "BLOCK")
    n_warn = sum(1 for lvl, _ in issues if lvl == "WARN")
    summary = {
        "comments_answered": units,
        "revised_blocks": sum(1 for b in blocks if b.kind == "revised"),
        "manuscript_changes": {
            **{k: sum(1 for c in change_report if c["evidence"] == k) for k in CHANGE_KINDS},
            "no_change": [{"line": c["line"], "reason": c["reason"]} for c in change_report if c["evidence"] == "no-change"],
            "none": [c["line"] for c in change_report if c["evidence"] == "none"],
        },
        "quotes": {s: sum(1 for _, x in quote_report if x == s) for s in ("found", "differs-at-end", "non-contiguous", "partial", "missing", "uncheckable")} if quote_report else None,
        "block": n_block,
        "warn": n_warn,
        "ready": n_block == 0 and args.manuscript_text is not None,
        "outputs": outputs,
    }
    print(json.dumps(summary, ensure_ascii=False))
    sys.exit(1 if (n_block and not args.draft) or (args.strict and n_warn) else 0)


if __name__ == "__main__":
    main()
