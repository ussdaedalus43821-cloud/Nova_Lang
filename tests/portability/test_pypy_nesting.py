"""G-051 (docs/GAPS.md): on PyPy, a deeply nested program crashes the interpreter instead of getting NovaLang's nesting error.

This is a gap probe in the sense of the proof-of-concept repositories: it PASSES while the gap exists and FAILS the day it is fixed,
so docs/GAPS.md cannot rot. It needs a PyPy interpreter, which CI does not have, so it is skipped unless NOVA_PYPY names one:

    NOVA_PYPY=$(uv python find pypy@3.10) python3 -m unittest tests.portability.test_pypy_nesting -v
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPY = os.environ.get("NOVA_PYPY")
SEGFAULT = (-11, 139)       # a signal as the OS reports it, or as a shell does


def chain(operands):
    return "print(" + " and ".join(["true"] * operands) + ")\n"


def run(interpreter, source, *flags):
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "chain.nova")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        return subprocess.run([interpreter, str(ROOT / "novalang.py"), *flags, path], cwd=str(ROOT), stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=300)


@unittest.skipUnless(PYPY, "set NOVA_PYPY to a PyPy interpreter to run the G-051 probe")
class PyPyNesting(unittest.TestCase):
    def test_G051_pypy_crashes_on_a_long_chain_in_both_profiles(self):
        for flags in ((), ("--profile", "restricted")):
            with self.subTest(flags=flags):
                done = run(PYPY, chain(20000), *flags)
                # Today: killed by a segmentation fault. Fixed: exit status 1 and the nesting error.
                self.assertIn(done.returncode, SEGFAULT, "the gap is fixed? exit {}\n{}".format(done.returncode, done.stderr[-300:]))
                self.assertNotIn("recursion too deep", done.stdout + done.stderr)

    def test_G051_cpython_gives_the_named_error_for_the_same_program(self):
        done = run(sys.executable, chain(20000))
        self.assertEqual(done.returncode, 1)
        self.assertIn("NovaError: the interpreter ran out of stack - recursion too deep", done.stdout + done.stderr)

    def test_G051_a_short_chain_works_on_pypy(self):
        done = run(PYPY, chain(500))
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "true"))


if __name__ == "__main__":
    unittest.main()
