"""Render the fictitious example and a signed/unsigned mixed letter through the public script.

Run (in this skill folder): python3 -m unittest discover -s tests -v
Needs the same tools as the script (see references/cover-letter.md, "渲染与依赖").
Work files go to a temporary folder (set TMPDIR to move it off a small /tmp).
"""
import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts/render_cover_letter.py"
ROSTER = SKILL / "assets/authors.example.yml"


def tiny_png(path: Path, width: int = 60, height: int = 20) -> None:
    """A grey PNG made with the standard library, standing in for a logo or signature image."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + b"\x80\x80\x80" * width for _ in range(height))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def render(letter: Path, out: Path, *extra: str) -> tuple[int, dict, str]:
    run = subprocess.run([sys.executable, str(SCRIPT), str(letter), str(out), *extra], capture_output=True, text=True)
    report = json.loads(run.stdout) if run.stdout.strip().startswith("{") else {"stderr": run.stderr}
    pdf = out / "cover_letter.pdf"
    text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout if pdf.exists() else ""
    return run.returncode, report, text


class RenderCoverLetterTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="paper-submission-kit-"))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def test_example_renders_on_one_page(self):
        code, report, text = render(SKILL / "assets/example_cover_letter.md", self.work / "out", "--roster", str(ROSTER))
        self.assertEqual(code, 0, report)
        self.assertEqual(report["pdf_pages"], 1)
        self.assertEqual(report["signers"], ["Si Li", "San Zhang"])
        self.assertTrue((self.work / "out/cover_letter_editable.docx").exists())
        self.assertIn("Corresponding Authors:", text)
        self.assertNotIn("Ph.D.", text)

    def test_signed_and_unsigned_signers_share_a_letter(self):
        assets = self.work / "assets"
        tiny_png(assets / "logos/example-univ.png")
        tiny_png(assets / "signatures/zhang-san.png")
        letter = self.work / "mixed.md"
        letter.write_text(
            "---\ntitle: Test title\nauthors: [San Zhang, Wu Wang]\njournal: Test Journal\nlogos: [example-univ]\n"
            "signers: [zhang-san, {id: wang-wu, name: Wu Wang, title: Lecturer, "
            "affiliation: [Example College, Example City], email: wangwu@example.com}]\n---\n\n"
            "Dear Editor,\n\nWe respectfully submit our manuscript.\n", encoding="utf-8")
        code, report, text = render(letter, self.work / "mixed", "--roster", str(ROSTER), "--assets", str(assets))
        self.assertEqual(code, 0, report)
        self.assertEqual(report["signers_without_signature"], ["Wu Wang"])
        self.assertIn("Lecturer", text)
        self.assertIn("Example University, Example City", text)

    def test_signer_without_facts_is_bad_input(self):
        letter = self.work / "bad.md"
        letter.write_text("---\ntitle: T\nauthors: [A]\njournal: J\nsigners: [nobody]\n---\n\nDear Editor,\n",
                          encoding="utf-8")
        code, report, _ = render(letter, self.work / "bad")
        self.assertEqual(code, 2)
        self.assertIn("nobody", report["stderr"])


if __name__ == "__main__":
    unittest.main()
