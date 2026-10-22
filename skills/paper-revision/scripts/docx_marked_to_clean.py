#!/usr/bin/env python3
"""Make the clean manuscript from the red-marked Word manuscript and check the pair.

Usage:
    python3 -I docx_marked_to_clean.py MARKED.docx CLEAN.docx [--list-red RED.md] [--colors EE0000,FF0000]

What it does (stdlib only):
  * copies MARKED.docx to CLEAN.docx, turning every run coloured with a revision colour (default FF0000, EE0000,
    C00000) in the body, footnotes, endnotes, headers and footers black; nothing else changes;
  * fails when the check cannot vouch for the clean file: texts (including equation text) differ, revision red is
    left in CLEAN, a revision colour is defined in styles.xml (red applied through a style would survive), Word
    tracked changes or comments are present in any part, or no revision red exists at all (pass --allow-no-red for
    a deletion-only revision);
  * reports the colours used in the body so that red text that is not a revision mark can be spotted (then mark
    revisions with another colour and pass it via --colors);
  * --list-red writes every paragraph that contains red text, red spans wrapped in «R»…«/R», and flags
    paragraphs where a red sentence closely resembles a black sentence (old text probably not deleted).
Prints a JSON summary. Exit code: 0 = clean written and all checks passed; 1 = a check failed; 2 = bad input.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import zipfile
from pathlib import Path

PARTS = re.compile(r"^word/(document|footnotes|endnotes|header\d*|footer\d*)\.xml$")
# insertions, deletions, moves and formatting/property revisions
TRACKED = re.compile(r"<w:(ins|del|moveFrom|moveTo|rPrChange|pPrChange|sectPrChange|tblPrChange|tblGridChange|"
                     r"trPrChange|tcPrChange|cellIns|cellDel|cellMerge|numberingChange)\b")
OMATH = re.compile(r"<m:oMath(?:Para)?\b.*?</m:oMath(?:Para)?>", re.S)


def flatten_math(xml: str, cre) -> str:
    """Equations as one run "$…$" (red if any part is revision red), so red_report lists revised equations."""
    def repl(m):
        text = "".join(re.findall(r"<m:t[^>]*>([^<]*)</m:t>", m.group(0)))
        color = '<w:rPr><w:color w:val="FF0000"/></w:rPr>' if cre.search(m.group(0)) else ""
        return f"<w:r>{color}<w:t>${text}$</w:t></w:r>" if text else ""
    return OMATH.sub(repl, xml)


def color_re(colors):
    alt = "|".join(re.escape(c) for c in colors)
    return re.compile(r'<w:color\b[^>]*\bw:val="(?:' + alt + r')"[^>]*/>', re.IGNORECASE)


def para_text(xml: str):
    """Paragraphs with their text, including Word equation text (m:t) so math-only paragraphs are compared."""
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        yield p, "".join(re.findall(r"<[wm]:t[^>]*>([^<]*)</[wm]:t>", p))


def all_text(z: zipfile.ZipFile) -> str:
    out = []
    for name in sorted(n for n in z.namelist() if PARTS.match(n)):
        xml = z.read(name).decode("utf8")
        out.extend(t for _, t in para_text(xml))
    return "\n".join(out)


ABBREV = re.compile(r"\b(Fig|Figs|Eq|Eqs|Ref|Refs|No|Sec|Tab|vs|al|e\.g|i\.e|cf|approx)\.\s+", re.IGNORECASE)


def sentences(text: str):
    protected = ABBREV.sub(lambda m: m.group(0).rstrip() + "\u00a7", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(\[])", protected)
    return [s.replace("\u00a7", " ").strip() for s in parts if len(s.strip()) > 20]


def red_report(xml: str, cre) -> tuple[list[str], int]:
    lines, flagged = [], 0
    for p, _ in para_text(xml):
        parts, red_text, black_text = [], [], []
        for r in re.findall(r"<w:r[ >].*?</w:r>", p, flags=re.S):
            t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", r))
            if not t:
                continue
            if cre.search(r):
                parts.append("«R»" + t + "«/R»")
                red_text.append(t)
            else:
                parts.append(t)
                black_text.append(t)
        if not red_text:
            continue
        shown = "".join(parts).replace("«/R»«R»", "")
        note = ""
        for rs in sentences("".join(red_text)):
            for bs in sentences("".join(black_text)):
                ratio = difflib.SequenceMatcher(None, rs.lower(), bs.lower()).ratio()
                if ratio >= 0.6 or rs.split()[:4] == bs.split()[:4]:
                    note = f"> ⚠ possible old text left next to its replacement (same opening words or similarity {ratio:.2f}): “{bs[:120]}…”\n"
                    break
            if note:
                break
        flagged += bool(note)
        lines.append(shown + "\n" + note)
    return lines, flagged


def main():
    ap = argparse.ArgumentParser(description="Make the clean .docx from the red-marked .docx and check the pair.")
    ap.add_argument("marked", type=Path)
    ap.add_argument("clean", type=Path)
    ap.add_argument("--list-red", type=Path, help="write red-marked paragraphs to this Markdown file")
    ap.add_argument("--colors", default="FF0000,EE0000,C00000", help="comma-separated hex colours that mark revisions")
    ap.add_argument("--allow-no-red", action="store_true", help="accept a marked file without red (deletion-only revision)")
    args = ap.parse_args()
    if not args.marked.exists() or args.marked.resolve() == args.clean.resolve():
        print("ERROR: MARKED must exist and differ from CLEAN", file=sys.stderr)
        sys.exit(2)
    cre = color_re([c.strip().upper() for c in args.colors.split(",") if c.strip()])

    failures, red_runs, report_lines, flagged, colors_used = [], {}, [], 0, {}
    with zipfile.ZipFile(args.marked) as zin, zipfile.ZipFile(args.clean, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if PARTS.match(info.filename):
                xml = data.decode("utf8")
                if TRACKED.search(xml):
                    failures.append(f"{info.filename}: Word tracked changes ({TRACKED.search(xml).group(1)}) present; "
                                    "accept or reject them first")
                if info.filename == "word/document.xml":
                    for c in re.findall(r'<w:color\b[^>]*\bw:val="([0-9A-Fa-f]{6}|auto)"', xml):
                        colors_used[c.upper()] = colors_used.get(c.upper(), 0) + 1
                n = len(cre.findall(xml))
                if n:
                    red_runs[info.filename] = n
                    if info.filename == "word/document.xml" and args.list_red:
                        report_lines, flagged = red_report(flatten_math(xml, cre), cre)
                    xml = cre.sub('<w:color w:val="000000"/>', xml)
                data = xml.encode("utf8")
            elif info.filename == "word/styles.xml" and cre.search(data.decode("utf8")):
                failures.append("word/styles.xml defines a revision colour; red applied through a style would stay red — "
                                "use direct red formatting for revisions")
            elif info.filename == "word/comments.xml":
                failures.append("Word comments present; remove them before submission")
            zout.writestr(info, data)

    with zipfile.ZipFile(args.marked) as zm, zipfile.ZipFile(args.clean) as zc:
        same_text = all_text(zm) == all_text(zc)
        left = sum(len(cre.findall(zc.read(n).decode("utf8"))) for n in zc.namelist() if PARTS.match(n))
    if not same_text:
        failures.append("texts of MARKED and CLEAN differ")
    if left:
        failures.append(f"{left} revision-red runs left in CLEAN")
    if not sum(red_runs.values()) and not args.allow_no_red:
        failures.append("no revision red found; check --colors, or pass --allow-no-red for a deletion-only revision")

    if args.list_red:
        args.list_red.write_text("# Red-marked paragraphs\n\n" + "\n".join(report_lines), encoding="utf8")
    summary = {
        "red_runs": red_runs,
        "texts_identical": same_text,
        "red_left_in_clean": left,
        "colors_used_in_body": dict(sorted(colors_used.items(), key=lambda kv: -kv[1])[:10]),
        "paragraphs_with_red": len(report_lines) if args.list_red else None,
        "possible_old_text_left": flagged if args.list_red else None,
        "failures": failures,
        "clean": str(args.clean),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
