"""The escape-attempt corpus, checked against the file system.

`tests/conformance/cases/sandbox-escape.json` holds hostile programs and what the engines print for them. A
printed refusal proves the program was told no; it does not prove that nothing happened. This test runs every
case on the two Python engines in a folder it can inspect, takes a snapshot of every file and link before and
after, and fails if anything outside the folders the case may write to has changed, or if the text of a file
the case may not read shows up anywhere in what the program printed.

The self-hosted interpreter runs the same cases through the conformance runner (python3 tests/run_all.py).
"""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "conformance"))

import novalang as nl  # noqa: E402
import engines  # noqa: E402

CASES = json.loads((ROOT / "tests" / "conformance" / "cases" / "sandbox-escape.json").read_text(encoding="utf-8"))["cases"]


def snapshot(folder):
    """Everything under `folder`, as {relative path: description}: files by content, links by target."""
    found = {}
    for here, directories, names in os.walk(folder):
        for name in directories + names:
            path = os.path.join(here, name)
            rel = os.path.relpath(path, folder).replace(os.sep, "/")
            if os.path.islink(path):
                found[rel] = "link -> " + os.readlink(path)
            elif os.path.isdir(path):
                found[rel] = "directory"
            else:
                with open(path, "rb") as handle:
                    found[rel] = "file " + hashlib.sha256(handle.read()).hexdigest()
    return found


def inside(rel, folders):
    return any(rel == folder or rel.startswith(folder.rstrip("/") + "/") for folder in folders)


class EscapeCorpus(unittest.TestCase):
    def setUp(self):
        if nl.SANDBOX_UNSUPPORTED:
            self.skipTest("the restricted profile needs Python 3.8 or later on Windows")

    def run_case(self, case, engine):
        if case.get("platforms") and not any(sys.platform.startswith(name) for name in case["platforms"]):
            self.skipTest("this case is for " + "/".join(case["platforms"]))
        if case.get("symlinks") and engines.symlinks_unavailable():
            self.skipTest("this machine cannot make symbolic links")
        sandbox = case["sandbox"]
        with tempfile.TemporaryDirectory(prefix="nova-escape-") as folder:
            folder = os.path.realpath(folder)
            engines.write_files(folder, case["source"], case.get("files") or {}, case.get("symlinks"))
            before = snapshot(folder)
            here = os.getcwd()
            os.chdir(folder)
            try:
                with engines.patched_environment(case.get("env")):
                    result = engines.run_in_process_in(case["source"], engine, folder, case.get("stdin", ""),
                                                       case.get("args"), False,
                                                       dict(sandbox))
            finally:
                os.chdir(here)
            after = snapshot(folder)
        writable = [name.rstrip("/") for name in sandbox.get("write", [])]
        for rel in sorted(set(before) | set(after)):
            if before.get(rel) != after.get(rel):
                self.assertTrue(inside(rel, writable), "{} changed outside the folders the case may write to: "
                                "{} -> {}".format(rel, before.get(rel), after.get(rel)))
        shown = "\n".join(result["output"]) + "\n" + result["error"]
        readable = [name.rstrip("/") for name in sandbox.get("read", []) + sandbox.get("import_from", [])]
        for rel, text in (case.get("files") or {}).items():
            if not inside(rel, readable) and rel != "main.nova" and len(text) > 3 and text in shown:
                self.fail("the text of {} (outside the grant) was printed".format(rel))
        self.assertNotIn("InternalError", result["error"])
        self.assertNotIn("Traceback", shown)


def make(case, engine):
    def test(self):
        self.run_case(case, engine)
    return test


for _case in CASES:
    for _engine in ("vm", "tree"):
        if _case.get("deep") and _engine == "tree":
            continue
        setattr(EscapeCorpus, "test_{}_{}".format(_case["name"].replace("-", "_"), _engine), make(_case, _engine))


class TheCheckCanSee(unittest.TestCase):
    """The snapshot comparison fails when the sandbox is holed: put the hole back and require the failure."""

    def test_a_path_check_that_lets_everything_in_is_caught(self):
        if nl.SANDBOX_UNSUPPORTED:
            self.skipTest("the restricted profile needs Python 3.8 or later on Windows")
        case = next(c for c in CASES if c["name"] == "esc-paths-nothing-is-written-created-or-removed-outside")
        original = nl.inside_folder
        # the hole is confined to the test's own temporary tree: a folder is taken to be its parent
        nl.inside_folder = lambda real, root: original(real, os.path.dirname(root))
        try:
            check = EscapeCorpus("run_case")
            with self.assertRaises(AssertionError):
                check.run_case(case, "vm")
        finally:
            nl.inside_folder = original


class TheCorpusIsWhatItClaims(unittest.TestCase):
    def test_every_case_is_an_attack_that_runs_in_the_sandbox_profile(self):
        self.assertGreaterEqual(len(CASES), 50)
        for case in CASES:
            self.assertEqual(case["profile"], "sandbox", case["name"])
            self.assertTrue(case["name"].startswith("esc-"), case["name"])

    def test_no_case_names_a_file_of_this_machine(self):
        text = json.dumps(CASES)
        for fragment in ("/etc/", "/home/", "/Users/", "/root", "C:\\\\", "/proc/", "/sys/"):
            self.assertNotIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
