"""python.* on the command line: off unless --allow-python, the same on every
way of running a program, and the report's payloads (issue 1) do nothing.

The payloads are harmless: they would print 42 or create one marker file in
the temporary folder the test runs in.
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

# (name, flags before the file) - the self-hosted interpreter is a second
# implementation that forwards python.* to the host, so it must agree.
MODES = (
    ("vm", []),
    ("tree-walker", ["--tree-walk"]),
    ("bootstrap", ["--bootstrap"]),
    ("bootstrap on the tree-walker", ["--tree-walk", "--bootstrap"]),
)


def with_flag(flags):
    """Insert --allow-python after any --tree-walk and before --bootstrap/the file."""
    out = list(flags)
    at = out.index("--bootstrap") if "--bootstrap" in out else len(out)
    return out[:at] + ["--allow-python"] + out[at:]


class PythonBridgeCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nova-bridge-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def run_program(self, source, flags, after=()):
        path = self.folder / "program.nova"
        path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "novalang.py")] + list(flags) + [str(path)] + list(after),
            cwd=self.folder, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120,
        )
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        return result

    def test_python_is_off_by_default_in_every_mode(self):
        for name, flags in MODES:
            for call in ('python.import("math")', 'python.get("math.pi")', 'python.call("math.sqrt", 4)',
                         'python.set("x", 1)'):
                with self.subTest(mode=name, call=call):
                    result = self.run_program(call + "\n", flags)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("PythonError", result.stderr)
                    self.assertIn("python.* is disabled", result.stderr)
                    self.assertIn("--allow-python", result.stderr)

    def test_allow_python_turns_it_on_in_every_mode(self):
        for name, flags in MODES:
            with self.subTest(mode=name):
                result = self.run_program(
                    'python.import("math")\nprint(python.call("math.sqrt", 81))\n', with_flag(flags))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "9\n", ""))

    def test_the_flag_after_the_file_belongs_to_the_script(self):
        # Only flags before the program count; the script's own arguments are its own.
        for name, flags in MODES:
            with self.subTest(mode=name):
                result = self.run_program('python.import("math")\n', flags, after=["--allow-python"])
                self.assertEqual(result.returncode, 1)
                self.assertIn("python.* is disabled", result.stderr)

    def test_the_reports_payloads_do_nothing_even_with_python_on(self):
        payload = '''python.import("json")
python.import("re")
let found = "nothing"
try { let b = python.get("json.__builtins__"); found = b["eval"]("6 * 7") } catch e { print("1:", e) }
try { let b = python.get("re.enum.bltns"); found = b["eval"]("6 * 7") } catch e { print("2:", e) }
try { let b = python.get("json.codecs.builtins"); found = b["open"]("marker.txt", "w") } catch e { print("3:", e) }
print(found)
'''
        expected = [
            '1: PythonError: "json.__builtins__" has no attribute "__builtins__"',
            '2: PythonError: "re.enum.bltns" has no attribute "enum"',
            '3: PythonError: "json.codecs.builtins" has no attribute "codecs"',
            "nothing",
        ]
        for name, flags in MODES:
            with self.subTest(mode=name):
                result = self.run_program(payload, with_flag(flags))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)
                self.assertEqual(list(self.folder.glob("marker.txt")), [])

    def test_a_script_cannot_replace_an_allowed_modules_function(self):
        program = ('python.import("json")\n'
                   'try { python.set("json.dumps", 5) } catch e { print("refused:", e) }\n'
                   'print(python.call("json.dumps", [1, 2]))\n')
        for name, flags in MODES:
            with self.subTest(mode=name):
                result = self.run_program(program, with_flag(flags))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                lines = result.stdout.splitlines()
                self.assertTrue(lines[0].startswith("refused: PythonError: cannot modify the module"), lines)
                self.assertEqual(lines[1], "[1, 2]")

    def test_bootstrap_script_takes_the_flag_too(self):
        path = self.folder / "program.nova"
        path.write_text('python.import("math")\nprint(python.get("math.pi") > 3)\n', encoding="utf-8")
        off = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), str(path)],
                             cwd=self.folder, capture_output=True, text=True, timeout=120)
        self.assertEqual(off.returncode, 1)
        self.assertIn("python.* is disabled", off.stderr)
        on = subprocess.run([sys.executable, str(ROOT / "bootstrap.py"), "--allow-python", str(path)],
                            cwd=self.folder, capture_output=True, text=True, timeout=120)
        self.assertEqual((on.returncode, on.stdout, on.stderr), (0, "true\n", ""))

    def test_the_repl_and_inline_code_follow_the_same_rule(self):
        off = subprocess.run([sys.executable, str(ROOT / "novalang.py"), 'python.get("math.pi")'],
                             cwd=self.folder, capture_output=True, text=True, timeout=60,
                             stdin=subprocess.DEVNULL)
        self.assertEqual(off.returncode, 1)
        self.assertIn("python.* is disabled", off.stderr)
        repl_off = subprocess.run([sys.executable, str(ROOT / "novalang.py")], input='python.import("math")\n',
                                  cwd=self.folder, capture_output=True, text=True, timeout=60)
        self.assertIn("python.* is disabled", repl_off.stdout)
        repl_on = subprocess.run([sys.executable, str(ROOT / "novalang.py"), "--allow-python"],
                                 input='python.import("math")\npython.get("math.pi") > 3\n',
                                 cwd=self.folder, capture_output=True, text=True, timeout=60)
        self.assertIn("true", repl_on.stdout)
        self.assertNotIn("PythonError", repl_on.stdout)


if __name__ == "__main__":
    unittest.main()
