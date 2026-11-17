"""The step budget counts work as well as passes and calls (docs/spec/16-sandbox.md [sbx.limits], steps; G-042, decision D5).

The conformance corpus (cases/step-work.json) proves that a run is stopped at the same point on the VM, the tree-walker and the
self-hosted interpreter. These tests prove the arithmetic of the cost model and that the two Python engines agree to the step."""

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

RESTRICTED = "the restricted profile needs Python 3.8 or later on Windows ([sbx.profiles])"


def steps_used(source, engine, **limits):
    """The steps a program takes in the restricted profile, counted by the engine itself, and what it printed."""
    settings = {"steps": 50000000, "time": 600000, "output": 100000000}
    settings.update(limits)
    interpreter = nl.Interpreter(engine, capabilities=nl.Capabilities("restricted", regex=True, limits=settings))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        nl.run(source, interpreter)
    return interpreter.steps, out.getvalue()


class Arithmetic(unittest.TestCase):
    def test_a_hundred_and_twenty_eight_units_of_work_are_one_step_and_the_regex_matcher_uses_the_same_rate(self):
        self.assertEqual(nl.WORK_PER_STEP, 128)
        self.assertEqual(nl.REGEX_UNIT, nl.WORK_PER_STEP)

    def test_the_default_ceiling_is_five_million_steps_in_restricted_and_there_is_none_in_trusted(self):
        self.assertEqual(nl.LIMIT_DEFAULTS["steps"], 5000000)
        self.assertEqual(nl.Limits(restricted=True).steps, 5000000)
        self.assertIsNone(nl.Limits().steps)

    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED)
    def test_units_that_do_not_make_a_step_are_carried_to_the_next_charge(self):
        interpreter = nl.Interpreter("vm", capabilities=nl.Capabilities("restricted", limits={"steps": 1000, "time": 600000}))
        with interpreter.running():
            interpreter.charge(100)
            self.assertEqual((interpreter.steps, interpreter.step_units), (0, 100))
            interpreter.charge(28)
            self.assertEqual((interpreter.steps, interpreter.step_units), (1, 0))
            interpreter.charge(127)
            interpreter.charge(129)
            self.assertEqual((interpreter.steps, interpreter.step_units), (3, 0))
            interpreter.charge(1000)
            self.assertEqual((interpreter.steps, interpreter.step_units), (10, 1000 - 7 * 128))

    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED)
    def test_enough_work_in_one_call_ends_the_run_with_the_budget_error(self):
        interpreter = nl.Interpreter("vm", capabilities=nl.Capabilities("restricted", limits={"steps": 100, "time": 600000}))
        with interpreter.running():
            with self.assertRaises(nl.FatalLimit) as caught:
                interpreter.charge(128 * 101)
        self.assertIn("step budget of 100 steps exhausted", str(caught.exception))


@unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED)
class Engines(unittest.TestCase):
    def test_the_vm_and_the_tree_walker_take_exactly_the_same_number_of_steps(self):
        setup = 'let A = range(5000)\nlet S = "x" * 5000\nlet L = [3, 1, 2] * 1500\nlet D = {}\nD["a"] = 1\n'
        operations = ["len(A + A)", "A == A", "S == S", "S != S + S", "4999 in A", '"a" in D', "len(S[1:])", "len(sorted(L))",
                      "len(str(A))", 'len(join(["ab"] * 3000, ","))', "len(range(20000))", "len(json.dumps(A))", "len(A * 3)"]
        for operation in operations:
            with self.subTest(operation):
                source = setup + "let r = " + operation + "\nprint(r)\n"
                vm, tree = steps_used(source, "vm"), steps_used(source, "tree")
                self.assertEqual(vm, tree)

    def test_work_costs_steps_where_a_count_of_passes_and_calls_alone_would_say_one(self):
        steps, _ = steps_used('let A = range(100000)\nlet r = len(A + A)\n', "vm")
        # the range (its count, then the list it returns) and the sum (its two operands), 128 units to a step, and the two calls
        self.assertEqual(steps, (100000 + 100000 + 200000) // nl.WORK_PER_STEP + 2)

    def test_equal_strings_are_charged_by_their_length_on_both_engines(self):
        source = 'let S = "x" * 6400\nlet r = S == S\n'
        small = 'let S = "x" * 64\nlet r = S == S\n'
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                self.assertGreater(steps_used(source, engine)[0], steps_used(small, engine)[0] + 40)

    def test_in_walks_a_list_or_a_string_and_looks_a_dictionary_up_by_key(self):
        big = 'let L = range(6400)\nlet S = "y" * 6400\nlet D = {}\nlet k = 0\nwhile k < 640 {\n    D[str(k)] = k\n    k = k + 1\n}\n'
        base = steps_used(big, "vm")[0]
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                in_list = steps_used(big + "let r = 6399 in L\n", engine)[0] - steps_used(big, engine)[0]
                in_string = steps_used(big + 'let r = "z" in S\n', engine)[0] - steps_used(big, engine)[0]
                in_dictionary = steps_used(big + 'let r = "639" in D\n', engine)[0] - steps_used(big, engine)[0]
                self.assertEqual((in_list, in_string, in_dictionary), (50, 50, 0))
        self.assertGreater(base, 0)

    def test_a_slice_is_charged_for_what_it_copies_and_not_for_what_it_cuts_from(self):
        long_text = 'let S = "x" * 100000\n'
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                base = steps_used(long_text, engine)[0]
                self.assertEqual(steps_used(long_text + "let r = S[0:10]\n", engine)[0], base)
                self.assertEqual(steps_used(long_text + "let r = S[0:6400]\n", engine)[0], base + 50)

    def test_append_len_and_pop_cost_one_step_however_long_the_list_is(self):
        # Charged by the length of the list they work on, building a list of n items would cost n * n / 2 units.
        build = 'let out = []\nlet i = 0\nwhile i < 20000 {\n    append(out, i)\n    i = i + 1\n}\nlet n = len(out)\npop(out)\n'
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                self.assertEqual(steps_used(build, engine)[0], 20000 * 2 + 2)

    def test_a_pass_of_a_loop_is_counted_when_it_is_over_on_both_engines(self):
        loops = ['while true {\n    print(1)\n}\n', 'for i in range(100) {\n    print(i)\n}\n',
                 'for x in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] {\n    print(x)\n}\n',
                 'for i in range(100) {\n    if i < 4 {\n        continue\n    }\n    print(i)\n}\n']
        for loop in loops:
            for limit in range(1, 13):
                with self.subTest(loop=loop[:24], limit=limit):
                    results = []
                    for engine in ("vm", "tree"):
                        try:
                            results.append(steps_used(loop, engine, steps=limit)[1])
                        except nl.FatalLimit:
                            results.append(None)
                    self.assertEqual(results[0], results[1])

    def test_a_pass_left_by_break_is_not_counted(self):
        source = 'let n = 0\nwhile true {\n    n = n + 1\n    if n > 3 {\n        break\n    }\n}\n'
        self.assertEqual(steps_used(source, "vm")[0], 3)
        self.assertEqual(steps_used(source, "tree")[0], 3)

    def test_a_raised_ceiling_lets_the_same_program_finish(self):
        loop = 'let n = 0\nwhile n < 200 {\n    n = n + 1\n}\nprint(n)\n'
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                with self.assertRaises(nl.FatalLimit):
                    steps_used(loop, engine, steps=100)
                self.assertEqual(steps_used(loop, engine, steps=100000)[1], "200\n")

    def test_the_embedding_api_takes_the_same_ceiling(self):
        nova = nl.Nova(profile="restricted", limits={"steps": 1000, "time": 600000})
        with self.assertRaises(nl.NovaLangError) as caught:
            nova.exec('let A = range(100000)\nlet n = 0\nwhile n < 100 {\n    let r = len(A + A)\n    n = n + 1\n}\n')
        self.assertIn("step budget of 1000 steps exhausted", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
