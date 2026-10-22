"""Checks of build_response_docx.py that need no python-docx: every comment's response must show a manuscript change.

Run (in this skill folder): python3 -I -m unittest discover -s tests -v
"""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_response_docx.py"
spec = importlib.util.spec_from_file_location("build_response_docx", SCRIPT)
brd = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = brd  # dataclasses look the module up while the class is created
spec.loader.exec_module(brd)

HEAD = """---
manuscript_id: ABC-2026-001.R1
title: "A Test Title"
journal: Test Journal
---

Dear Editor, we revised "**A Test Title**" for *Test Journal*.

"""


def check(body):
    meta, text, offset = brd.parse_front_matter(HEAD + body)
    blocks = brd.parse_blocks(text, offset)
    issues, units, _, changes = brd.run_checks(meta, blocks, Path("."), None, None)
    return issues, units, changes, blocks


def levels(issues, needle="no manuscript change"):
    return [lvl for lvl, msg in issues if needle in msg]


class ManuscriptChangeEvidence(unittest.TestCase):
    def test_revised_passage(self):
        issues, units, changes, _ = check("""# Reviewer 1

> 1. The definition is unclear.

**Response:** Thank you for the question. We added a definition to Section 2.

**The revised text reads (in Section 2):**

[[
The porosity is defined as the pore volume divided by the bulk volume.
]]
""")
        self.assertEqual(units, 1)
        self.assertEqual(changes[0]["evidence"], "revised")
        self.assertEqual(levels(issues), [])

    def test_deletion_sentence(self):
        _, _, changes, _ = check("""# Reviewer 1

> 1. The claim in the Conclusions is not supported.

**Response:** Thank you for the careful observation. We have deleted this claim from Section 5 and the Abstract.
""")
        self.assertEqual(changes[0]["evidence"], "deleted")

    def test_cross_reference(self):
        issues, _, changes, _ = check("""# Reviewer 2

> 1. Same concern as another reviewer about the data split.

**Response:** Thank you. Please see our response to R1.3 (Section 3.1), where the data split is corrected.
""")
        self.assertEqual(changes[0]["evidence"], "xref")
        self.assertEqual(levels(issues), [])

    def test_new_table(self):
        _, _, changes, _ = check("""# Reviewer 1

> 1. Add an ablation study.

**Response:** Thank you for this suggestion. The ablation results are now in Table 3.

| Method | MAE |
|---|---|
| <red>Without X</red> | <red>0.10</red> |
""")
        self.assertEqual(changes[0]["evidence"], "figure/table")

    def test_explanation_only_blocks_for_reviewer(self):
        issues, _, changes, _ = check("""# Reviewer 1

> 1. Why did you choose this window length?

**Response:** Thank you for the question. The window length follows the sampling interval of the logs.
""")
        self.assertEqual(changes[0]["evidence"], "none")
        self.assertEqual(levels(issues), ["BLOCK"])

    def test_explanation_only_warns_for_editor(self):
        issues, _, changes, _ = check("""# Response to the Associate Editor

> Please revise the paper based on the reviewers' comments.

**Response:** We thank the Associate Editor for handling our manuscript.
""")
        self.assertEqual(changes[0]["evidence"], "none")
        self.assertEqual(levels(issues), ["WARN"])

    def test_no_change_marker_with_reason(self):
        issues, units, changes, blocks = check("""# Reviewer 2

> Comments to the Author
>
> I have no further comments.

**Response:** Thank you! We appreciate your positive assessment.

<!-- no-change: reviewer requests nothing -->
""")
        self.assertEqual(units, 1)
        self.assertEqual(changes[0], {"line": changes[0]["line"], "evidence": "no-change", "reason": "reviewer requests nothing"})
        self.assertEqual(levels(issues), [])
        self.assertFalse(any("<!--" in b.text for b in blocks if b.kind != "nochange"))

    def test_no_change_marker_before_response(self):
        _, _, changes, _ = check("""# Reviewer 2

> 1. The paper is well written.

<!-- no-change: praise only -->

**Response:** Thank you for the kind words.
""")
        self.assertEqual(changes[0]["evidence"], "no-change")

    def test_no_change_marker_needs_reason(self):
        issues, _, _, _ = check("""# Reviewer 2

> 1. The paper is well written.

**Response:** Thank you for the kind words.

<!-- no-change: -->
""")
        self.assertIn("BLOCK", levels(issues, "needs a reason"))

    def test_other_html_comments_are_not_rendered(self):
        _, _, changes, blocks = check("""# Reviewer 1

> 1. Why did you choose this window length?

<!-- TODO for us only: ask the student -->

**Response:** Thank you for the question. The window length follows the sampling interval.
""")
        self.assertFalse(any("<!--" in b.text for b in blocks))
        self.assertEqual(changes[0]["evidence"], "none")  # a plain note is not a no-change declaration

    def test_each_numbered_comment_is_checked(self):
        issues, units, changes, _ = check("""# Reviewer 1

> 1. Define porosity.

**Response:** Thank you. We added the definition.

**The revised text reads (in Section 2):**

[[
The porosity is defined as the pore volume divided by the bulk volume.
]]

> 2. Why this window length?

**Response:** Thank you for the question. It follows the sampling interval.
""")
        self.assertEqual(units, 2)
        self.assertEqual([c["evidence"] for c in changes], ["revised", "none"])
        self.assertEqual(levels(issues), ["BLOCK"])


if __name__ == "__main__":
    unittest.main()
