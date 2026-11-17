"""G-051 (docs/GAPS.md): a deeply nested program ends with NovaLang's nesting error on every host, and not in a crash on PyPy.

The nesting limits are counted by the parser ([port.limits]: 1000 brackets, braces and blocks, a syntax tree 5000 deep), and on PyPy
the interpreter runs in a thread with a large stack (`main_with_room`). This is the check that it holds there. It needs a PyPy interpreter,
which CI does not have, so it is skipped unless NOVA_PYPY names one:

    NOVA_PYPY=$(uv python find pypy@3.10) python3 -m unittest tests.portability.test_pypy_nesting -v

PyPy stays a measurement and not a supported engine (the restricted profile has not been offered on it): this proves one gap closed,
not that the whole suite passes there.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPY = os.environ.get("NOVA_PYPY")
NESTING_ERROR = "NovaError: the interpreter ran out of stack - recursion too deep"
CRASHES = (-11, -6, 139, 134)       # a signal as the OS reports it, or as a shell does


def chain(operands):
    return "print(" + " and ".join(["true"] * operands) + ")\n"


def parens(levels):
    return "let x = " + "(" * levels + "1" + ")" * levels + "\nprint(x)\n"


def blocks(levels):
    return "if true {\n" * levels + "}\n" * levels + 'print("done")\n'


def lists(levels):
    return "let x = " + "[" * levels + "]" * levels + "\nprint(len(x))\n"


def run(interpreter, source, *flags):
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "nested.nova")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        return subprocess.run([interpreter, str(ROOT / "novalang.py"), "--no-cache", *flags, path], cwd=str(ROOT),
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)


ENGINES = {"vm": (), "tree-walker": ("--tree-walk",), "restricted": ("--profile", "restricted"),
           "restricted tree-walker": ("--tree-walk", "--profile", "restricted")}


@unittest.skipUnless(PYPY, "set NOVA_PYPY to a PyPy interpreter to run the G-051 check")
class PyPyNesting(unittest.TestCase):
    def test_G051_the_chain_that_crashed_pypy_gets_the_named_error(self):
        for name, flags in ENGINES.items():
            with self.subTest(name):
                done = run(PYPY, chain(20000), *flags)
                self.assertNotIn(done.returncode, CRASHES, "PyPy crashed: exit {}".format(done.returncode))
                self.assertEqual(done.returncode, 1)
                self.assertIn(NESTING_ERROR, done.stdout + done.stderr)

    def test_G051_the_limits_are_the_same_on_pypy_and_on_cpython(self):
        for kind, make in (("parens", parens), ("blocks", blocks), ("lists", lists)):
            for name, flags in ENGINES.items():
                for levels, ok in ((1000, True), (1001, False)):
                    with self.subTest(kind=kind, engine=name, levels=levels):
                        for interpreter in (PYPY, sys.executable):
                            done = run(interpreter, make(levels), *flags)
                            self.assertEqual(done.returncode, 0 if ok else 1, (interpreter, done.stderr[-200:]))
                            if not ok:
                                self.assertIn(NESTING_ERROR, done.stdout + done.stderr)

    def test_G051_a_long_chain_is_accepted_up_to_the_tree_depth_limit_and_not_beyond(self):
        for name, flags in ENGINES.items():
            with self.subTest(name):
                self.assertEqual(run(PYPY, chain(4000), *flags).stdout.strip(), "true")
                refused = run(PYPY, chain(6000), *flags)
                self.assertEqual(refused.returncode, 1)
                self.assertIn(NESTING_ERROR, refused.stdout + refused.stderr)

    def test_G051_a_short_program_works_on_pypy(self):
        done = run(PYPY, chain(500))
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "true"))


if __name__ == "__main__":
    unittest.main()
