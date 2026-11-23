"""Tests added after the mutation test of 2026-11-17 (mutation/MUTATION_REPORT.md): each one pins down behaviour that a deliberately planted bug left unnoticed.

Every test names the mutants it is meant to kill. The size pre-checks are tested directly because their only job is to refuse BEFORE a large
string or list is built: the result is checked again afterwards, so a test that looks only at the output cannot tell a working pre-check
from a missing one (the memory of the process is the difference).
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

RESTRICTED = "the restricted profile needs Python 3.8 or later on Windows ([sbx.profiles])"


def engine(**limits):
    return nl.Interpreter("vm", capabilities=nl.Capabilities("restricted", limits=limits))


def refuses(interpreter, name, *args):
    """Does the pre-check of `name` refuse these arguments, before the built-in runs?"""
    try:
        interpreter.check_call_arguments(nl.BUILTINS[name], list(args), 0)
    except nl.NovaError as problem:
        return problem.message
    return None


@unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED)
class SizePrechecks(unittest.TestCase):
    """[sbx.limits] string.join: the operands of a built-in say how big the result must be, and a result that cannot fit is refused first."""

    def test_join_is_refused_before_it_is_built_when_even_the_least_it_could_be_is_too_long(self):    # M014, M034
        # three empty items and a four-character separator: at least 3 + 2 * 4 = 11 characters, while the list's own text is far shorter
        items = [""] * 3
        self.assertIsNotNone(refuses(engine(string=10), "join", items, "bbbb"))
        self.assertIsNone(refuses(engine(string=11), "join", items, "bbbb"))

    def test_a_one_item_join_costs_no_separator(self):                                                # M010, M029
        self.assertIsNone(refuses(engine(string=2), "join", [""], "bb"))
        self.assertEqual(nl.Nova(profile="restricted", limits={"string": 2}).eval('join([""], "bb")'), "")

    def test_pad_is_refused_before_it_is_built_when_the_width_is_beyond_the_limit(self):             # M030
        interpreter = engine(string=10)
        for name in ("pad", "pad_left"):
            with self.subTest(name):
                self.assertIsNone(refuses(interpreter, name, "a", 10))
                self.assertIsNotNone(refuses(interpreter, name, "a", 11))
                self.assertIsNotNone(refuses(interpreter, name, "a", 200000000))

    def test_replace_all_is_refused_before_it_is_built_when_it_would_grow_beyond_the_limit(self):    # M026, M036
        interpreter = engine(string=10)
        self.assertIsNotNone(refuses(interpreter, "replace_all", "aaaa", "a", "xxxxx"))              # 4 + 4 * 4 = 20
        self.assertIsNone(refuses(interpreter, "replace_all", "aaaa", "a", "xx"))                    # 4 + 4 * 1 = 8
        big = engine(string=1000000)
        self.assertIsNotNone(refuses(big, "replace_all", "a" * 100000, "a", "x" * 2000))             # 200 million characters
        self.assertIsNone(refuses(big, "replace_all", "a" * 100000, "a", "xy"))

    def test_range_is_refused_before_it_is_built_whatever_the_number_of_arguments(self):              # M020
        interpreter = engine(list=100)
        expected = "range() would build a list of 5000 items, which is too large"
        self.assertEqual(refuses(interpreter, "range", 5000), expected)
        self.assertEqual(refuses(interpreter, "range", 0, 5000), expected)
        self.assertEqual(refuses(interpreter, "range", 0, 5000, 1), expected)
        self.assertIsNone(refuses(interpreter, "range", 0, 100, 1))

    def test_the_message_a_program_sees_for_a_long_range_does_not_depend_on_its_arguments(self):       # M020
        for source in ("range(0, 5000, 1)", "range(5000)", "range(0, 5000)"):
            with self.subTest(source):
                with self.assertRaises(nl.NovaLangError) as caught:
                    nl.Nova(profile="restricted", limits={"list": 100}).eval(source)
                self.assertIn("range() would build a list of 5000 items", str(caught.exception))


class IntegerErrorPosition(unittest.TestCase):
    def test_the_too_many_digits_error_points_at_the_multiplication(self):                            # M160
        source = "let a = 1\nlet r = pow(10, 2000) * pow(10, 2001)\nlet b = 2"
        with self.assertRaises(nl.NovaLangError) as caught:
            nl.Nova("vm").exec(source)
        position = caught.exception.nova_error.position
        self.assertEqual(source[position], "*")


def trip_position(source, limit=1):
    interpreter = nl.Interpreter("vm", capabilities=nl.Capabilities("restricted", limits={"steps": limit, "time": 600000, "output": 10 ** 8}))
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            nl.run(source, interpreter)
        except nl.FatalLimit as limit_error:
            return limit_error.position
    return "no limit"


@unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED)
class StepLimitErrorPositions(unittest.TestCase):
    """The position of a fatal limit error is the operation that ran the budget out ([sbx.limits]); a host that shows it shows the right place."""

    SETUP = "let A = [0] * 100\n"

    def test_each_charging_operation_reports_its_own_operator(self):                                   # M066, M076, M077, M087, M132, M139, M144
        for name, operator, body, before in (("==", "==", "let r = A == A\n", 1), ("!=", "!=", "let r = A != A\n", 1),
                                             ("+", "+", "let r = A + A\n", 1), ("in", "in", "let r = 5 in A\n", 2)):
            with self.subTest(name):
                source = self.SETUP + body * 4
                position = trip_position(source)
                self.assertIsInstance(position, int, "the error carries a position")
                self.assertEqual(source[position:position + len(operator)], operator)
                self.assertEqual(source[:position].count(" %s " % operator), before, "the use that runs the budget out")

    def test_a_call_that_runs_the_budget_out_reports_its_own_parenthesis(self):                        # M070
        source = "print(1)\nprint(2)\nprint(3)\n"
        position = trip_position(source)
        self.assertEqual(source[position], "(")
        self.assertEqual(source[:position].count("print"), 2)


if __name__ == "__main__":
    unittest.main()
