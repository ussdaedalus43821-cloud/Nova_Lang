"""The language's own rules for numbers, independent of the Python underneath
([port.integers], [port.floats] in docs/spec/06-portability.md).

Floats print by a written rule, not by whatever `repr` gives, so another host
can reproduce them. `repr` is used here only as an oracle: the rule is meant to
agree with it everywhere, so a difference means the rule or the code is wrong.
Integers are bounded at 4,000 digits on every Python, whether or not that
release limits integer-to-text conversion itself.
"""

import inspect
import math
import random
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang  # noqa: E402


def bits_to_float(bits):
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def float_to_bits(value):
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def neighbours(value):
    """The floats either side of a positive finite float (math.nextafter is 3.9+)."""
    bits = float_to_bits(value)
    return ([bits_to_float(bits - 1)] if bits > 1 else []), [bits_to_float(bits + 1)]


class FloatDisplayTests(unittest.TestCase):
    def check(self, value):
        self.assertEqual(novalang.float_text(value), repr(value), repr(value))

    def test_every_power_of_two_and_its_neighbours(self):
        for exponent in range(-1074, 1024):
            value = math.ldexp(1.0, exponent)
            below, above = neighbours(value)
            for each in [value] + below + above:
                if 0 < each < math.inf:
                    self.check(each)
                    self.check(-each)

    def test_random_bit_patterns(self):
        generator = random.Random(20261108)
        for _ in range(60000):
            value = bits_to_float(generator.getrandbits(64))
            if math.isfinite(value) and value != 0:
                self.check(value)

    def test_everyday_floats(self):
        generator = random.Random(7)
        for _ in range(30000):
            self.check(generator.uniform(-10, 10))
            self.check(round(generator.random() * 1000, generator.randint(0, 6)))
            self.check(generator.random() * 10 ** generator.randint(-8, 20))

    def test_the_cases_the_spec_names(self):
        for value, text in [
            (0.1 + 0.2, "0.30000000000000004"), (1 / 3, "0.3333333333333333"),
            (0.0001, "0.0001"), (0.00001, "1e-05"), (1.23456e-05, "1.23456e-05"),
            (5e-324, "5e-324"), (2.2250738585072014e-308, "2.2250738585072014e-308"),
            (math.ldexp(1.0, -1017), "7.120236347223045e-307"),
            (2251799813685248.5, "2251799813685248.5"), (-0.5, "-0.5"),
        ]:
            self.assertEqual(novalang.float_text(value), text)

    def test_display_of_the_other_values(self):
        for value, text in [
            (float("inf"), "inf"), (float("-inf"), "-inf"), (float("nan"), "nan"),
            (5.0, "5"), (-0.0, "0"), (1e22, "10000000000000000000000"),
            (1e23, "99999999999999991611392"), (1e16, "10000000000000000"),
            (0.5, "0.5"), (100.25, "100.25"),
        ]:
            self.assertEqual(novalang.format_float(value), text)

    def test_the_code_does_not_borrow_pythons_float_formatting(self):
        for function in (novalang.shortest_digits, novalang.float_text, novalang.format_float):
            source = inspect.getsource(function)
            code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
            self.assertNotIn("repr(", code.split('"""')[-1], function.__name__)
            self.assertNotIn("str(value)", code, function.__name__)


class IntegerBoundTests(unittest.TestCase):
    def run_program(self, source, tree=False):
        import contextlib
        import io
        out = io.StringIO()
        interpreter = novalang.Interpreter("tree" if tree else "vm")
        with contextlib.redirect_stdout(out):
            novalang.run(source, interpreter)
        return out.getvalue().splitlines()

    def test_the_bound_is_the_languages_not_pythons(self):
        self.assertEqual(novalang.MAX_INTEGER_DIGITS, 4000)
        self.assertEqual(novalang.INTEGER_LIMIT, 10 ** 4000)
        self.assertLess(novalang.MAX_INTEGER_DIGITS, 4300)
        # Python's own limit (3.11+, and security releases) never comes into play.
        self.assertEqual(len(str(novalang.INTEGER_LIMIT - 1)), 4000)

    def test_pow_is_refused_without_being_computed(self):
        for source in ('print(pow(2, 1000000000))', 'print(pow(-3, 100000000000))',
                       'print(pow(10, 4000))'):
            for tree in (False, True):
                with self.assertRaises(novalang.NovaError) as caught:
                    self.run_program(source, tree)
                self.assertIn("too many digits", str(caught.exception))

    def test_both_engines_stop_at_the_same_place(self):
        program = ("let n = 1\nfor i = 1 to 3999 { n = n * 10 }\n"
                   "print(len(str(n * 9 + (n - 1))))\ntry { print(n * 10) } catch e { print(e) }\n")
        self.assertEqual(self.run_program(program), self.run_program(program, tree=True))

    def test_the_boundary_value_is_exact(self):
        self.assertEqual(novalang.bounded_integer(10 ** 4000 - 1, None), 10 ** 4000 - 1)
        self.assertEqual(novalang.bounded_integer(-(10 ** 4000 - 1), None), -(10 ** 4000 - 1))
        for value in (10 ** 4000, -(10 ** 4000)):
            with self.assertRaises(novalang.NovaError):
                novalang.bounded_integer(value, None)


if __name__ == "__main__":
    unittest.main()
