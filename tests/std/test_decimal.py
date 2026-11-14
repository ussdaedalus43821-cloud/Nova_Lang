"""std:decimal against Python's `decimal` module as the oracle (M13 slice 2).

A seeded set of random decimals and operations is turned into one NovaLang program; its output is
compared line by line with what Python's `decimal` (set to a precision far beyond anything used)
computes. Every rounding mode, every operation, positive and negative values, ties and non-ties. The
bytecode VM gets the big sample, the tree-walker a smaller one and the self-hosted interpreter (about
30 times slower) a small one: the module is NovaLang source, so the three run the same code, and
this is what shows they agree on it.
"""

import decimal
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODES = {"half_even": decimal.ROUND_HALF_EVEN, "half_up": decimal.ROUND_HALF_UP, "half_down": decimal.ROUND_HALF_DOWN,
         "up": decimal.ROUND_UP, "down": decimal.ROUND_DOWN, "floor": decimal.ROUND_FLOOR, "ceiling": decimal.ROUND_CEILING}
CONTEXT = decimal.Context(prec=5000, Emax=999999, Emin=-999999)


def text(d):
    """Python's text for a decimal in the form std:decimal prints: no exponent, no negative zero."""
    out = format(d, "f")
    return out[1:] if out.startswith("-") and d == 0 else out


def random_decimal(rng):
    whole = rng.choice([0, 0, 1, 5, rng.randrange(10), rng.randrange(10 ** rng.randrange(1, 14))])
    places = rng.choice([0, 1, 2, 2, 3, rng.randrange(0, 9)])
    frac = "".join(rng.choice("0123456789") for _ in range(places))
    # ties are the interesting case for rounding: bias towards a trailing 5
    if frac and rng.random() < 0.4:
        frac = frac[:-1] + "5"
    sign = rng.choice(["", "", "-"])
    return "{}{}{}".format(sign, whole, "." + frac if frac else "")


def build(count, seed):
    """(NovaLang source, expected output lines)."""
    rng = random.Random(seed)
    source, expected = ['import "std:decimal" as dec', "def show(a) { return dec.to_string(a) }"], []
    for _ in range(count):
        a, b = random_decimal(rng), random_decimal(rng)
        da, db = decimal.Decimal(a), decimal.Decimal(b)
        mode = rng.choice(sorted(MODES))
        places = rng.randrange(0, 7)
        quantum = decimal.Decimal(1).scaleb(-places)
        source.append('print(show(dec.parse("{}")))'.format(a))
        expected.append(text(da))
        source.append('print(show(dec.add(dec.parse("{}"), dec.parse("{}"))), show(dec.sub(dec.parse("{}"), dec.parse("{}"))), '
                      'show(dec.mul(dec.parse("{}"), dec.parse("{}"))), dec.cmp(dec.parse("{}"), dec.parse("{}")))'.format(a, b, a, b, a, b, a, b))
        expected.append("{} {} {} {}".format(text(CONTEXT.add(da, db)), text(CONTEXT.subtract(da, db)), text(CONTEXT.multiply(da, db)),
                                              (da > db) - (da < db)))
        source.append('print(show(dec.quantize(dec.parse("{}"), {}, "{}")), dec.to_int(dec.parse("{}"), "{}"))'.format(a, places, mode, a, mode))
        expected.append("{} {}".format(text(da.quantize(quantum, rounding=MODES[mode], context=CONTEXT)),
                                       int(da.quantize(decimal.Decimal(1), rounding=MODES[mode], context=CONTEXT))))
        if db != 0:
            source.append('print(show(dec.div(dec.parse("{}"), dec.parse("{}"), {}, "{}")))'.format(a, b, places, mode))
            quotient = CONTEXT.divide(da, db)
            expected.append(text(quotient.quantize(quantum, rounding=MODES[mode], context=CONTEXT)))
        x = round(rng.uniform(-1000, 1000), rng.randrange(0, 6))
        source.append('print(show(dec.from_float({!r}, {}, "{}")))'.format(x, places, mode))
        expected.append(text(decimal.Decimal(repr(x)).quantize(quantum, rounding=MODES[mode], context=CONTEXT)))
    return "\n".join(source) + "\n", expected


def run(flags, source):
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "oracle.nova")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        done = subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True,
                              timeout=900, stdin=subprocess.DEVNULL, env=dict(os.environ, NOVALANG_CACHE="off"))
    return done


class Oracle(unittest.TestCase):
    def check(self, flags, count, seed):
        source, expected = build(count, seed)
        done = run(flags, source)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        got = done.stdout.splitlines()
        self.assertEqual(len(got), len(expected))
        for index, (want, have) in enumerate(zip(expected, got)):
            if want != have:
                self.fail("line {}: expected {!r}, got {!r}\n{}".format(index + 1, want, have, source.splitlines()[0:0]))

    def test_vm(self):
        self.check([], 400, 20261114)

    def test_tree_walker(self):
        self.check(["--tree-walk"], 60, 7)

    def test_self_hosted(self):
        self.check(["--bootstrap"], 12, 99)

    def test_the_restricted_profile_needs_no_grant(self):
        if sys.platform == "win32" and sys.version_info < (3, 8):
            self.skipTest("the restricted profile refuses to start on Windows with Python 3.7")
        source, expected = build(10, 3)
        done = run(["--profile", "restricted"], source)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertEqual(done.stdout.splitlines(), expected)


if __name__ == "__main__":
    unittest.main()
