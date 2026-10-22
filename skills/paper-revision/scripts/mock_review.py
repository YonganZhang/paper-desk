#!/usr/bin/env python3
"""Mock peer review of a revision: build one frozen review packet, and verify reviewer reports against it.

Usage:
    python3 -I mock_review.py packet --comments DECISION --old ORIGINAL --new REVISED --response RESPONSE \
        --journal "Journal" --out PACKET_DIR [--extra FILE ...] [--force]
    python3 -I mock_review.py verify PACKET_DIR/reports/NAME.md PACKET_DIR [--expect-comments N]

packet   copies the original files to PACKET_DIR/originals/ and converts each to UTF-8 text
         (01_review_comments.txt, 02_original_manuscript.txt, 03_revised_manuscript.txt, 04_response_letter.txt,
         05_extra_*.txt): .docx -> text with revision-red runs wrapped in {+ … +}, equations flattened to $…$ and
         table rows as "cell | cell"; .pdf -> pdftotext; .tex -> \\input/\\include files expanded; .md/.txt/.eml copied.
         Fills ../assets/mock-review-prompt.md into prompt.md and writes manifest.json with a PACKET_ID (sha256 of the
         packet texts and original files). Without --old the packet is marked incomplete. Refuses to rebuild a packet
         that already has reports unless --force, which moves old reports to reports/_history/<time>/.
verify   recomputes the PACKET_ID from the packet files and checks a report: exact PACKET_ID, VERDICT, recommendation
         and confidence values, non-empty required sections with table rows, VERDICT consistent with the
         recommendation and critical issues, and (with --expect-comments) enough comment rows.
The reviewers themselves are any models or sub-agents you have; each reads PACKET_DIR/prompt.md independently and
writes PACKET_DIR/reports/<name>.md (see ../references/mock-review.md). This script calls no model or network.
Requires: Python 3.9+ standard library; pdftotext (poppler-utils) only for .pdf inputs.
Exit code: 0 = done; 1 = conversion/validation failure; 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
PROMPT_TEMPLATE = SKILL / "assets" / "mock-review-prompt.md"
REVISION_RED = re.compile(r'<w:color\b[^>]*\bw:val="(?:FF0000|EE0000|C00000)"', re.IGNORECASE)
OMATH = re.compile(r"<m:oMath(?:Para)?\b.*?</m:oMath(?:Para)?>", re.S)
VERDICTS = ("PASS", "FAIL", "INSUFFICIENT_MATERIALS")


def flatten_math(xml: str) -> str:
    """Replace each Word equation (OMML) by one plain run "$…$" holding its m:t text (structure is lost)."""
    def repl(m):
        body = m.group(0)
        text = "".join(re.findall(r"<m:t[^>]*>([^<]*)</m:t>", body))
        color = '<w:rPr><w:color w:val="FF0000"/></w:rPr>' if REVISION_RED.search(body) else ""
        return f"<w:r>{color}<w:t>${text}$</w:t></w:r>" if text else ""
    return OMATH.sub(repl, xml)


def para_line(p: str) -> tuple[str, int]:
    parts, red = [], 0
    for r in re.findall(r"<w:r[ >].*?</w:r>", p, flags=re.S):
        t = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", r))
        if not t:
            continue
        if REVISION_RED.search(r):
            red += 1
            parts.append("{+" + t + "+}")
        else:
            parts.append(t)
    return html.unescape("".join(parts).replace("+}{+", "")), red


def docx_text(path: Path) -> tuple[str, int]:
    """Plain text of a .docx body: red runs wrapped in {+ … +}, equations as $…$, table rows as "a | b | c"."""
    with zipfile.ZipFile(path) as z:
        xml = flatten_math(z.read("word/document.xml").decode("utf8"))
    lines, red_runs = [], 0
    for m in re.finditer(r"<w:tbl>.*?</w:tbl>|<w:p[ >].*?</w:p>", xml, flags=re.S):
        chunk = m.group(0)
        if chunk.startswith("<w:tbl>"):
            for tr in re.findall(r"<w:tr[ >].*?</w:tr>", chunk, flags=re.S):
                cells = []
                for tc in re.findall(r"<w:tc[ >].*?</w:tc>", tr, flags=re.S):
                    texts = [para_line(p) for p in re.findall(r"<w:p[ >].*?</w:p>", tc, flags=re.S)]
                    red_runs += sum(n for _, n in texts)
                    cells.append(" ".join(t for t, _ in texts if t.strip()))
                lines.append("| " + " | ".join(cells) + " |")
        else:
            line, n = para_line(chunk)
            red_runs += n
            if line.strip():
                lines.append(line)
    return "\n".join(lines), red_runs


def tex_expanded(path: Path, root: Path | None = None, depth: int = 0) -> str:
    """LaTeX source with \\input{} / \\include{} files inlined. Like LaTeX itself, nested paths are resolved from the
    main file's directory (the compile directory), not from the including file."""
    root = root or path.parent

    def repl(m):
        name = m.group(2)
        cand = root / (name if name.endswith(".tex") else name + ".tex")
        if depth < 10 and cand.exists():
            return f"% ---- begin {name} ----\n" + tex_expanded(cand, root, depth + 1) + f"\n% ---- end {name} ----\n"
        return m.group(0)
    out = []
    for line in path.read_text(encoding="utf8", errors="replace").splitlines():
        parts = re.split(r"(?<!\\)(%)", line, maxsplit=1)
        code, sep, comment = (parts + ["", ""])[:3]
        if "revmarks" not in code:  # the revision-mark macro file is not manuscript content
            code = re.sub(r"\\(input|include)\{([^}]+)\}", repl, code)
        out.append(code + sep + comment)
    return "\n".join(out)


def to_text(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        text, red = docx_text(path)
        return text, f"docx, {red} red runs marked {{+ +}}" if red else "docx"
    if suffix == ".pdf":
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=300)
        if out.returncode:
            raise SystemExit(f"ERROR: pdftotext failed on {path}: {out.stderr.strip()}")
        return out.stdout, "pdf"
    if suffix == ".tex":
        return tex_expanded(path), "tex (\\input/\\include expanded)"
    if suffix in (".md", ".txt", ".eml", ".markdown"):
        return path.read_text(encoding="utf8", errors="replace"), suffix[1:]
    raise SystemExit(f"ERROR: unsupported file type {path}")


def packet_id(packet: Path, files: list[str]) -> str:
    """Short sha256 over everything a reviewer can read: the material texts and the frozen original files."""
    h = hashlib.sha256()
    originals = sorted(p for p in (packet / "originals").rglob("*") if p.is_file())
    for path in [packet / f for f in sorted(files)] + originals:
        h.update(str(path.relative_to(packet)).encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def cmd_packet(a):
    out = a.out
    reports = out / "reports"
    old_reports = [p for p in reports.glob("*.md")] if reports.exists() else []
    if old_reports and not a.force:
        raise SystemExit(f"ERROR: {out} already has reports; use a new --out, or --force to move them to reports/_history/")
    out.mkdir(parents=True, exist_ok=True)
    reports.mkdir(exist_ok=True)
    if old_reports:
        hist = reports / "_history" / datetime.now().strftime("%Y%m%dT%H%M%S")
        hist.mkdir(parents=True)
        for p in reports.iterdir():
            if p.is_file():
                shutil.move(str(p), hist / p.name)
    originals = out / "originals"
    if originals.exists():
        shutil.rmtree(originals)
    originals.mkdir()

    items = [("01_review_comments.txt", a.comments, "Decision letter with all editor and reviewer comments")]
    if a.old:
        items.append(("02_original_manuscript.txt", a.old, "Original (previously reviewed) manuscript"))
    items.append(("03_revised_manuscript.txt", a.new, "Revised manuscript"))
    items.append(("04_response_letter.txt", a.response, "Authors' point-by-point response letter"))
    for i, extra in enumerate(a.extra or [], start=1):
        items.append((f"05_extra_{i}_{re.sub(r'[^A-Za-z0-9]+', '_', extra.stem)[:40]}.txt", extra, "Supplementary material"))

    manifest, listing, warnings = [], [], []
    for name, src, role in items:
        if not src.exists():
            raise SystemExit(f"ERROR: {src} not found")
        text, kind = to_text(src)
        (out / name).write_text(text, encoding="utf8")
        orig = originals / f"{name[:2]}_{src.name}"
        shutil.copy2(src, orig)
        manifest.append({"file": name, "role": role, "source": str(src.resolve()), "original_copy": str(orig.relative_to(out)),
                         "kind": kind, "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "chars": len(text)})
        listing.append(f"- `{name}` — {role} ({kind}); original file: `{orig.relative_to(out)}`")
        if "manuscript" in name and len(text) < 3000:
            warnings.append(f"{name}: only {len(text)} characters extracted; check the conversion")
    complete = bool(a.old)
    if not complete:
        warnings.append("materials incomplete: no original manuscript (--old); the review cannot verify deletions or replacements")
        listing.append("- The original manuscript is NOT available. Mark judgements that need it as cannot judge.")

    prompt = PROMPT_TEMPLATE.read_text(encoding="utf8")
    prompt = prompt.replace("{{JOURNAL}}", a.journal).replace("{{PACKET_DIR}}", str(out.resolve()))
    prompt = prompt.replace("{{FILE_LIST}}", "\n".join(listing))
    pid = packet_id(out, [m["file"] for m in manifest])
    (out / "prompt.md").write_text(prompt.replace("{{PACKET_ID}}", pid), encoding="utf8")
    (out / "manifest.json").write_text(json.dumps({
        "packet_id": pid, "created": datetime.now().isoformat(timespec="seconds"), "journal": a.journal,
        "complete": complete, "files": manifest}, ensure_ascii=False, indent=1), encoding="utf8")
    print(json.dumps({"packet": str(out), "packet_id": pid, "complete": complete,
                      "files": [m["file"] for m in manifest], "warnings": warnings}, ensure_ascii=False))


def load_manifest(packet: Path) -> dict:
    mf = packet / "manifest.json"
    if not mf.exists():
        raise SystemExit(f"ERROR: {mf} not found; run the packet command first")
    return json.loads(mf.read_text(encoding="utf8"))


RECOMMENDATIONS = ("accept", "minor revision", "major revision", "reject")


def sections(text: str) -> dict[str, list[str]]:
    out, cur = {}, None
    for line in text.splitlines():
        if line.strip().startswith("```"):
            continue
        if line.startswith("## "):
            cur = line[3:].strip().lower()
            out[cur] = []
        elif cur is not None and line.strip():
            out[cur].append(line.strip())
    return out


def table_rows(lines: list[str]) -> list[str]:
    rows = [x for x in lines if x.startswith("|") and not re.match(r"^\|[\s:\-|]+\|$", x)]
    return rows[1:] if rows else []  # first row is the header


def field(text: str, key: str) -> str:
    m = re.search(rf"^\W*{key}:\s*(.+?)\s*$", text, flags=re.M)
    return m.group(1).strip().strip("`*") if m else ""


def check_report(text: str, pid: str, expect_comments: int | None = None) -> list[str]:
    problems = []
    if field(text, "PACKET_ID") != pid:
        problems.append(f"PACKET_ID is {field(text, 'PACKET_ID')!r}, expected {pid}")
    verdict = field(text, "VERDICT")
    if verdict not in VERDICTS:
        problems.append(f"VERDICT {verdict!r} not one of {VERDICTS}")
    rec = field(text, "OVERALL_RECOMMENDATION").lower()
    if rec not in RECOMMENDATIONS:
        problems.append(f"OVERALL_RECOMMENDATION {rec!r} not one of {RECOMMENDATIONS}")
    if field(text, "CONFIDENCE").lower() not in ("high", "medium", "low"):
        problems.append("CONFIDENCE missing or not high/medium/low")
    sec = sections(text)
    for name in ("recommendation by reviewer", "comment-by-comment check"):
        if not table_rows(sec.get(name, [])):
            problems.append(f"section '## {name}' missing or has no table rows")
    for name in ("fatal issues", "response letter weaknesses"):
        if not sec.get(name):
            problems.append(f"section '## {name}' missing or empty")
    n_rows = len(table_rows(sec.get("comment-by-comment check", [])))
    if expect_comments and n_rows < expect_comments:
        problems.append(f"comment-by-comment check has {n_rows} rows, expected at least {expect_comments}")
    critical = any("[critical]" in x.lower() for x in sec.get("fatal issues", []))
    if verdict == "PASS" and (rec not in ("accept", "minor revision") or critical):
        problems.append("VERDICT PASS contradicts the recommendation or a critical fatal issue")
    if verdict == "FAIL" and rec in ("accept", "minor revision") and not critical:
        problems.append("VERDICT FAIL contradicts an Accept/Minor recommendation without critical issues")
    return problems


def cmd_verify(a):
    manifest = load_manifest(a.packet)
    pid = manifest["packet_id"]
    problems = []
    if packet_id(a.packet, [m["file"] for m in manifest["files"]]) != pid:
        problems.append("packet files changed after the packet was built; rebuild the packet and re-run the review")
    problems += check_report(a.report.read_text(encoding="utf8"), pid, a.expect_comments)
    print(json.dumps({"report": str(a.report), "packet_id": pid, "complete_materials": manifest.get("complete"),
                      "ok": not problems, "problems": problems}, ensure_ascii=False))
    raise SystemExit(1 if problems else 0)


def main():
    ap = argparse.ArgumentParser(description="Mock peer review: build the review packet; verify reviewer reports.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("packet", help="build the review packet")
    p.add_argument("--comments", type=Path, required=True, help="decision letter / reviewer comments")
    p.add_argument("--old", type=Path, help="original manuscript (without it the packet is marked incomplete)")
    p.add_argument("--new", type=Path, required=True, help="revised manuscript (marked .docx, main .tex or PDF)")
    p.add_argument("--response", type=Path, required=True, help="response letter (.md, .docx or .pdf)")
    p.add_argument("--journal", required=True)
    p.add_argument("--extra", type=Path, nargs="*", help="supplementary files")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--force", action="store_true", help="rebuild even if reports exist (old reports go to reports/_history/)")
    v = sub.add_parser("verify", help="check a reviewer report against the packet")
    v.add_argument("report", type=Path)
    v.add_argument("packet", type=Path)
    v.add_argument("--expect-comments", type=int, help="minimum rows in the comment-by-comment table")
    a = ap.parse_args()
    {"packet": cmd_packet, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    main()
