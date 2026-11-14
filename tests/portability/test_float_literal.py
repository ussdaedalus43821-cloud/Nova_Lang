"""G-052 (docs/GAPS.md): a float literal too large for a binary64 is infinity, silently, on every engine.

A gap probe: it PASSES while the gap exists and FAILS the day the lexer refuses (or otherwise treats) such a literal, so docs/GAPS.md
cannot rot. The spec says an overflowing float *result* is infinity ([port.floats]); this is the same rule reaching a literal."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "print(1" + "0" * 400 + ".0)\nprint(1" + "0" * 400 + ".0 - 1" + "0" * 400 + ".0)\n"


class FloatLiteralOverflow(unittest.TestCase):
    def test_G052_an_overflowing_float_literal_is_infinity_on_every_engine(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "literal.nova")
            Path(path).write_text(SOURCE, encoding="utf-8")
            for flags in ((), ("--tree-walk",), ("--bootstrap",)):
                with self.subTest(flags=flags):
                    done = subprocess.run([sys.executable, str(ROOT / "novalang.py"), *flags, path], capture_output=True, text=True,
                                          stdin=subprocess.DEVNULL, timeout=300)
                    self.assertEqual((done.returncode, done.stdout.split()), (0, ["inf", "nan"]), done.stderr[-300:])


if __name__ == "__main__":
    unittest.main()
