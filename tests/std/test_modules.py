"""The standard modules (docs/spec/08-modules.md [mod.std]): the list in lib/std/modules.json against
the files and their exports, and the capability rule on every engine.

The capability rule has no conformance case yet because no standard module declares a capability in
this version (the spec says so). It is proved here instead, with a throw-away module that declares
`files.read`, on the bytecode VM, the tree-walker and the self-hosted interpreter. The interpreter
finds lib/std beside itself, so the test runs a COPY of the interpreter's files in a temporary folder
whose lib/std holds the throw-away registry; the real lib/std is never touched.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STD = os.path.join(ROOT, "lib", "std")
CAPABILITIES = {"files.read", "files.write", "import", "env", "clock", "random", "stdin", "process", "regex", "python"}

def run(argv, interpreter=None, cwd=None):
    """Run `novalang.py` (the real one, or a copy whose lib/std was swapped) as a script on `argv`."""
    script = os.path.join(interpreter or ROOT, "novalang.py")
    done = subprocess.run([sys.executable, script] + argv, capture_output=True, text=True, timeout=120, cwd=cwd,
                          stdin=subprocess.DEVNULL, env=dict(os.environ, NOVALANG_CACHE="off"))
    return done.returncode, done.stdout, done.stderr


class Registry(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(STD, "modules.json"), encoding="utf-8") as handle:
            self.modules = json.load(handle)["modules"]

    def test_every_module_has_a_file_and_every_file_a_module(self):
        files = sorted(name[:-5] for name in os.listdir(STD) if name.endswith(".nova"))
        self.assertEqual(files, sorted(self.modules))

    def test_descriptors_are_complete_and_use_known_words(self):
        for name, descriptor in self.modules.items():
            with self.subTest(module=name):
                self.assertEqual(sorted(descriptor), ["capabilities", "exports", "since", "tier"])
                self.assertTrue(set(descriptor["capabilities"]) <= CAPABILITIES)
                self.assertIn(descriptor["tier"], ("provisional", "stable"))
                self.assertRegex(descriptor["since"], r"^\d+\.\d+\.\d+$")
                self.assertEqual(descriptor["exports"], sorted(descriptor["exports"]))

    def test_the_exports_are_exactly_the_descriptors_on_every_engine(self):
        for name, descriptor in self.modules.items():
            for flags in ([], ["--tree-walk"], ["--bootstrap"]):
                with self.subTest(module=name, flags=flags):
                    with tempfile.TemporaryDirectory() as folder:
                        program = os.path.join(folder, "main.nova")
                        with open(program, "w", encoding="utf-8") as handle:
                            handle.write('import "std:{}" as m\nprint(json.dumps(sorted(keys(m))))\n'.format(name))
                        status, out, err = run(flags + [program])
                    self.assertEqual(status, 0, err)
                    self.assertEqual(json.loads(out), descriptor["exports"])


@unittest.skipIf(sys.platform == "win32" and sys.version_info < (3, 8),
                 "the restricted profile refuses to start on Windows with Python 3.7 (SANDBOX_UNSUPPORTED)")
class DeclaredCapabilities(unittest.TestCase):
    """`import "std:gated"` needs the 'files.read' capability its descriptor declares."""

    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        base = cls.folder.name
        cls.copy = os.path.join(base, "interpreter")
        os.makedirs(os.path.join(cls.copy, "tools"))
        for name in os.listdir(ROOT):
            if name.endswith((".py", ".nova")) and os.path.isfile(os.path.join(ROOT, name)):
                shutil.copy(os.path.join(ROOT, name), cls.copy)
        for name in os.listdir(os.path.join(ROOT, "tools")):
            if name.endswith(".py"):
                shutil.copy(os.path.join(ROOT, "tools", name), os.path.join(cls.copy, "tools"))
        std = os.path.join(cls.copy, "lib", "std")
        os.makedirs(std)
        with open(os.path.join(std, "modules.json"), "w", encoding="utf-8") as handle:
            json.dump({"modules": {"gated": {"capabilities": ["files.read"], "tier": "provisional",
                                              "since": "2.3.0", "exports": ["x"]},
                                   "open": {"capabilities": [], "tier": "provisional",
                                            "since": "2.3.0", "exports": ["y"]}}}, handle)
        with open(os.path.join(std, "gated.nova"), "w", encoding="utf-8") as handle:
            handle.write("export let x = 1\n")
        with open(os.path.join(std, "open.nova"), "w", encoding="utf-8") as handle:
            handle.write("export let y = 2\n")
        cls.data = os.path.join(base, "data")
        os.mkdir(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def program(self, text):
        path = os.path.join(self.folder.name, "main.nova")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    ENGINES = ([], ["--tree-walk"], ["--bootstrap"])

    def test_restricted_without_the_grant_is_refused_at_the_import(self):
        path = self.program('print("start")\nimport "std:gated" as g\nprint(g.x)\n')
        for flags in self.ENGINES:
            with self.subTest(flags=flags):
                status, out, err = run(["--profile", "restricted"] + flags + [path], self.copy)
                self.assertEqual(status, 1, err)
                self.assertEqual(out, "start\n")          # at the import, not before and not later
                self.assertIn("ImportError: std:gated needs the 'files.read' capability, which this run did not grant", err)

    def test_the_grant_lets_it_in(self):
        path = self.program('import "std:gated" as g\nprint(g.x)\n')
        for flags in self.ENGINES:
            with self.subTest(flags=flags):
                status, out, err = run(["--profile", "restricted", "--allow-read", self.data] + flags + [path], self.copy)
                self.assertEqual((status, out), (0, "1\n"), err)

    def test_the_trusted_profile_has_every_capability(self):
        path = self.program('import "std:gated" as g\nprint(g.x)\n')
        for flags in self.ENGINES:
            with self.subTest(flags=flags):
                status, out, err = run(flags + [path], self.copy)
                self.assertEqual((status, out), (0, "1\n"), err)

    def test_a_module_that_declares_nothing_is_open_to_a_bare_restricted_run(self):
        path = self.program('import "std:open" as o\nprint(o.y)\n')
        for flags in self.ENGINES:
            with self.subTest(flags=flags):
                status, out, err = run(["--profile", "restricted"] + flags + [path], self.copy)
                self.assertEqual((status, out), (0, "2\n"), err)

    def test_the_import_grant_is_not_what_lets_a_standard_module_in(self):
        # `import` is a different capability: granting it does not grant files.read for std:gated.
        path = self.program('import "std:gated" as g\nprint(g.x)\n')
        for flags in self.ENGINES:
            with self.subTest(flags=flags):
                status, out, err = run(["--profile", "restricted", "--allow-import", self.data] + flags + [path], self.copy)
                self.assertEqual(status, 1)
                self.assertIn("needs the 'files.read' capability", err)


if __name__ == "__main__":
    unittest.main()
