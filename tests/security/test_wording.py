"""The words the documents may use about the restricted profile ([sbx.claims], ADR 0005).

Until an independent reviewer has an outcome in the review table, no document may describe the `restricted` profile as
a sandbox guarantee, as safe, or as a security boundary. The allowed description is "capability gating and resource
limits". This test reads every Markdown file of the repository and fails on a stronger phrase that has no negation
in front of it on the same line (or the line before), so a careless edit cannot promise more than the tests prove.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN = [
    r"security boundary", r"sandbox guarantee", r"secure sandbox", r"safe to run", r"fully secure", r"escape[- ]proof",
    r"bullet[- ]?proof", r"unhackable", r"guarantees? isolation", r"isolated from the host", r"is (?:a )?sandbox\b",
    r"(?:restricted|sandbox|profile)\b[^.]{0,60}\b(?:is|are) (?:safe|secure)\b",
    # The TOCTOU fix closes the final-component swap, not every race (parent components remain, Phase 6).
    # No document may call the sandbox "race-free" or the file operations "atomic" (ADR 0005, [sbx.toctou]).
    # Scoped to the claim: "atomic groups" (a regex feature) and "atomic rename" (a mechanism) are untouched.
    r"race[- ]?free",
    r"(?:restricted|sandbox|profile|the open|opens?|file operations?|operations?|the check|use of the path)\b"
    r"[^.\n]{0,60}\b(?:is|are|become[sd]?|remains?|stays?|made|now)\b[^.\n]{0,25}\batomic\b",
]
NEGATION = re.compile(r"\b(?:not|no|never|nor|neither|without|until|cannot|may not|must not)\b|n't", re.I)
# Files that talk about the words themselves, or quote a historical sentence, are read with the same rule but may name the
# phrases inside quotation marks or backticks: a quoted phrase is a mention, not a claim.
QUOTED = re.compile(r"[\"'`“”‘’][^\"'`“”‘’]*[\"'`“”‘’]")

# Mentions that are not claims, each with the reason. A new entry is a decision someone reads.
EXEMPT = {
    # the rejected option of ADR 0003, described in order to be rejected
    "docs/decisions/0003-security-stance.md": ["describe the\n   result as a security boundary", "result as a security boundary. Cheap to ship"],
}

LABEL = "Owner-reviewed and Architect-reviewed, pending independent third-party audit"
LABELLED = [
    "docs/design/m11-threat-model.md", "docs/spec/16-sandbox.md", "docs/design/m11-review-package.md",
    "docs/design/m11-security-plan.md",
]


def markdown_files():
    skip = {".git", "node_modules", "__pycache__"}
    for path in ROOT.rglob("*.md"):
        if not any(part in skip for part in path.relative_to(ROOT).parts):
            yield path


def claims_in(text):
    """Yield (line number, line, phrase) for each forbidden phrase with no negation near it and not inside quotes."""
    lines = text.splitlines()
    for number, line in enumerate(lines):
        window = " ".join(lines[max(0, number - 1):number + 1])
        unquoted = QUOTED.sub(" ", line)
        for phrase in FORBIDDEN:
            if re.search(phrase, unquoted, re.I) and not NEGATION.search(window):
                yield number + 1, line.strip(), phrase


class Wording(unittest.TestCase):
    def test_no_document_promises_more_than_the_claim(self):
        found = []
        for path in markdown_files():
            name = str(path.relative_to(ROOT)).replace("\\", "/")
            for number, line, phrase in claims_in(path.read_text(encoding="utf-8", errors="replace")):
                if any(fragment.split("\n")[-1].strip() in line for fragment in EXEMPT.get(name, [])):
                    continue
                found.append("{}:{}: {!r} ({})".format(path.relative_to(ROOT), number, line[:110], phrase))
        self.assertEqual(found, [], "a document says more than [sbx.claims] allows:\n" + "\n".join(found))

    def test_the_check_can_see(self):
        self.assertTrue(list(claims_in("The restricted profile is a security boundary for hostile code.")))
        self.assertTrue(list(claims_in("Scripts run in a secure sandbox.")))
        self.assertTrue(list(claims_in("It is safe to run anything in restricted.")))
        self.assertTrue(list(claims_in("The restricted profile is safe.")))
        self.assertFalse(list(claims_in("renaming it in Settings is safe for the workflow.")))
        self.assertFalse(list(claims_in("This is not a security boundary.")))
        self.assertFalse(list(claims_in('No document may say "security boundary" until the review is done.')))
        self.assertFalse(list(claims_in("capability gating and resource limits")))
        # the TOCTOU wording rule ([sbx.toctou], ADR 0005)
        self.assertTrue(list(claims_in("The restricted profile is race-free.")))
        self.assertTrue(list(claims_in("File operations are atomic.")))
        self.assertTrue(list(claims_in("The open is now atomic against a swap.")))
        self.assertFalse(list(claims_in("Regex refuses atomic groups and possessive quantifiers.")))
        self.assertFalse(list(claims_in("Writes are to a temporary file and an atomic rename.")))
        self.assertFalse(list(claims_in("The open is not atomic across the parent path.")))

    def test_the_documents_carry_the_review_label(self):
        for name in LABELLED:
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn(LABEL, text, name)

    def test_the_readme_quotes_the_claims_and_the_gaps(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("capability gating plus resource limits", text)
        for gap in ("isolation", "memory", "hard links", "container"):
            self.assertIn(gap, text)

    def test_the_review_package_lists_the_open_gaps(self):
        text = (ROOT / "docs/design/m11-review-package.md").read_text(encoding="utf-8")
        for needle in ("D-045", "N2", "N11", "N12", "RLIMIT_AS", "TOCTOU"):
            self.assertIn(needle, text)

    def test_the_sandbox_spec_states_the_toctou_wording_exactly(self):
        """[sbx.toctou], ADR 0005: the one sentence every document must use for the TOCTOU posture, so
        no edit can quietly upgrade "mitigated" to "closed" or "race-free"."""
        text = (ROOT / "docs/spec/16-sandbox.md").read_text(encoding="utf-8")
        self.assertIn("Static attacks are refused.", text)
        self.assertIn("mitigated by O_NOFOLLOW (final component)", text)
        self.assertIn("remains vulnerable to parent-component races until Phase 6", text)


if __name__ == "__main__":
    unittest.main()
