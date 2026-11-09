"""The type gate under the restricted profile on all three engines (D-045, docs/spec/16-sandbox.md [sbx.profiles]).

A restricted program that imports a granted module with a wrong annotation is refused before the wrong code runs, on
the bytecode VM, the tree-walker and the self-hosted interpreter. The self-hosted launcher checks the import graph
itself, so a second test shows that the walk reads only what the program could import: a module outside the grants is
never opened to be checked.
"""

import builtins
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bootstrap  # noqa: E402
import novalang as nl  # noqa: E402

BAD = 'export let x: float = "not a number"\n'


def make_tree(folder):
    for name, text in {"lib/ok.nova": "export let y = 1\n", "lib/bad.nova": BAD, "other/bad.nova": BAD,
                       "main.nova": 'import "lib/bad.nova" as b\nprint(b.x)\n',
                       "outside.nova": 'import "other/bad.nova" as b\nprint(b.x)\n',
                       "fine.nova": 'import "lib/ok.nova" as m\nprint(m.y)\n',
                       "wrong_main.nova": 'let n: float = "text"\nprint(n)\n'}.items():
        path = Path(folder, *name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class Restricted(unittest.TestCase):
    def setUp(self):
        if nl.SANDBOX_UNSUPPORTED:
            self.skipTest("the restricted profile needs Python 3.8 or later on Windows")
        self.folder = tempfile.TemporaryDirectory(prefix="nova-typegate-")
        self.addCleanup(self.folder.cleanup)
        self.root = os.path.realpath(self.folder.name)
        make_tree(self.root)

    def run_cli(self, program, *engine, grants=("--allow-import", "lib")):
        command = [sys.executable, str(ROOT / "novalang.py"), "--profile", "restricted"] + list(engine) + list(grants)
        return subprocess.run(command + [program], cwd=self.root, capture_output=True, text=True, timeout=300,
                              env=dict(os.environ, PYTHONUTF8="1"))

    def run_bootstrap(self, program):
        command = [sys.executable, str(ROOT / "novalang.py"), "--profile", "restricted", "--allow-import", "lib",
                   "--bootstrap", program]
        return subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=300,
                              env=dict(os.environ, PYTHONUTF8="1"))

    def test_the_vm_and_the_tree_walker_refuse_a_granted_module_with_a_wrong_type(self):
        for engine in ([], ["--tree-walk"]):
            done = self.run_cli("main.nova", *engine)
            self.assertEqual(done.returncode, 1, engine)
            self.assertIn("ImportError: while loading module", done.stderr, engine)
            self.assertIn("TypeCheckError: T006", done.stderr, engine)
            self.assertNotIn("not a number\n", done.stdout, engine)

    def test_the_self_hosted_interpreter_refuses_it_too(self):
        done = self.run_bootstrap("main.nova")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("TypeCheckError: lib/bad.nova:1:", done.stderr)
        self.assertIn("T006", done.stderr)
        self.assertEqual(done.stdout, "", "the wrong code ran before it was refused")

    def test_the_self_hosted_interpreter_checks_the_program_itself(self):
        done = self.run_bootstrap("wrong_main.nova")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("TypeCheckError", done.stderr)
        self.assertEqual(done.stdout, "")

    def test_a_module_that_is_fine_still_runs(self):
        done = self.run_bootstrap("fine.nova")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "1"), done.stderr)

    def test_a_module_outside_the_grant_is_refused_by_the_import_and_never_opened_by_the_check(self):
        opened = []
        real_open = builtins.open

        def spy(file, *arguments, **keywords):
            opened.append(os.path.realpath(os.fspath(file)) if isinstance(file, (str, os.PathLike)) else None)
            return real_open(file, *arguments, **keywords)

        here = os.getcwd()
        os.chdir(self.root)
        builtins.open = spy
        try:
            caps = nl.Capabilities(profile="restricted", import_from=["lib"])

            def granted(path):
                real = nl.real_path(path)
                return real is not None and any(nl.inside_folder(real, r) for r in caps.roots["import"])

            findings = bootstrap.type_check_graph(os.path.join(self.root, "outside.nova"), granted)
            inside = bootstrap.type_check_graph(os.path.join(self.root, "main.nova"), granted)
        finally:
            builtins.open = real_open
            os.chdir(here)
        self.assertEqual(findings, [], "the walk found an error in a module the program may not import")
        self.assertNotIn(os.path.join(self.root, "other", "bad.nova"), opened)
        self.assertTrue(any("T006" in line for line in inside), inside)

        done = self.run_bootstrap("outside.nova")
        self.assertEqual(done.returncode, 1)
        self.assertIn("outside the folders this program may use", done.stderr)
        self.assertNotIn("TypeCheckError", done.stderr)

    def test_the_trusted_profile_is_unchanged(self):
        command = [sys.executable, str(ROOT / "novalang.py"), "--bootstrap", "main.nova"]
        done = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=300,
                              env=dict(os.environ, PYTHONUTF8="1"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("TypeCheckError: lib/bad.nova:1:", done.stderr)


if __name__ == "__main__":
    unittest.main()
