"""NaN and infinity in floor, ceil, round, sleep, sin, cos, tan and `for`
headers (issue 3): a catchable NovaError, never a raw Python ValueError or
OverflowError, and the same on every way of running a program.

They come from num() of a decimal string too long for a float, from the
difference of two such numbers, and from float overflow. (json.loads used to
hand them over too, from "NaN" and "1e999"; it now refuses both, D-022.)
"""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

# Direct and self-hosted (--bootstrap), each on the VM and the tree-walker.
MODES = {
    "vm": [],
    "tree-walker": ["--tree-walk"],
    "bootstrap": ["--bootstrap"],
    "bootstrap on the tree-walker": ["--tree-walk", "--bootstrap"],
}

SOURCES = '''
let long = num("1" + "0" * 400 + ".0")
let nan = long - long
let inf = num("1" + "0" * 500 + ".0")
let overflow = num("1" + "0" * 308 + ".0") * 10
'''

ALL_CALLS = '''
for v in [nan, inf, -inf, long, overflow] {
    try { print(floor(v)) } catch e { print("floor:", e) }
    try { print(ceil(v)) } catch e { print("ceil:", e) }
    try { print(round(v)) } catch e { print("round:", e) }
    try { print(sin(v)) } catch e { print("sin:", e) }
    try { sleep(v) } catch e { print("sleep:", e) }
    try { for i = 0 to v { break } } catch e { print("for to:", e) }
    try { for i = v downto 0 { break } } catch e { print("for downto:", e) }
    try { for i = 0 to 3 step v { break } } catch e { print("for step:", e) }
}
print(round(nan, 2), round(2.567, 2), floor(-2.5), ceil(-2.5), round(2.6), floor(7), sin(0))
'''


class NonFiniteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nova-nonfinite-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def run_program(self, source, flags):
        path = self.folder / "program.nova"
        path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(ROOT / "novalang.py")] + flags + [str(path)],
            cwd=self.folder, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=120,
        )
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        for raw in ("ValueError", "OverflowError", "math domain error"):
            self.assertNotIn(raw, result.stdout + result.stderr)
        return result

    def test_every_call_is_caught_with_the_same_message_in_every_mode(self):
        outputs = {}
        for name, flags in MODES.items():
            result = self.run_program(SOURCES + ALL_CALLS, flags)
            self.assertEqual((name, result.returncode, result.stderr), (name, 0, ""))
            outputs[name] = result.stdout
        reference = outputs["vm"]
        for name, text in outputs.items():
            self.assertEqual(text, reference, name)
        lines = reference.splitlines()
        self.assertIn("floor: TypeError: floor() needs a finite number, but got nan", lines)
        self.assertIn("ceil: TypeError: ceil() needs a finite number, but got -inf", lines)
        self.assertIn("round: TypeError: round() needs a finite number, but got inf", lines)
        self.assertIn("sin: TypeError: sin() needs a finite number, but got inf", lines)
        self.assertIn("sleep: TypeError: sleep() needs a finite number, but got nan", lines)
        self.assertIn("for to: the end of a 'for' range must be a finite number, but this is inf", lines)
        self.assertIn("for downto: the start of a 'for' range must be a finite number, but this is nan", lines)
        self.assertIn("for step: a 'for' step must be a finite number, but this is -inf", lines)
        # NaN passes through sin(), as in Python (the one bare "nan" line);
        # the long string and the float overflow both became inf.
        self.assertEqual(lines.count("nan"), 1)
        self.assertEqual(lines.count("floor: TypeError: floor() needs a finite number, but got inf"), 3)
        # Unchanged, finite behavior, including round() with a digit count.
        self.assertEqual(lines[-1], "nan 2.57 -3 -2 3 7 0")

    def test_uncaught_it_is_a_labelled_error_with_exit_status_1(self):
        for name, flags in MODES.items():
            for call in ("floor", "ceil", "round"):
                with self.subTest(mode=name, call=call):
                    result = self.run_program(
                        'print("before")\nlet big = num("1" + "0" * 400 + ".0")\n{}(big - big)\n'.format(call), flags)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, "before\n")
                    self.assertIn("{}() needs a finite number, but got nan".format(call), result.stderr)
                    self.assertIn("TypeError", result.stderr)


if __name__ == "__main__":
    unittest.main()
