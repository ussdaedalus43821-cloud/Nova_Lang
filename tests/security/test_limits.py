"""The resource limits through the embedding API on both Python engines (docs/spec/16-sandbox.md [sbx.limits]).

What the conformance cases cannot say: an engine is usable again after a fatal limit, a host function that calls
back into the script is part of the same run and cannot reset the budget, a `finally` block never runs for a fatal
limit, a limit can be lowered but not raised, and the trusted profile has none of the three fatal limits.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

ENGINES = ("vm", "tree")
LOOP = "let i = 0\nwhile i < {n} {{\n  i = i + 1\n}}\ni"


class Fatal(unittest.TestCase):
    def test_a_fatal_limit_is_a_limit_error_and_the_engine_works_again(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"steps": 500})
            with self.assertRaises(nl.NovaLangError) as caught:
                nova.eval(LOOP.format(n=100000))
            self.assertTrue(str(caught.exception).startswith("LimitError: step budget of 500 steps"))
            self.assertEqual(nova.eval(LOOP.format(n=100)), 100)         # the counters start from zero again

    def test_nothing_in_the_program_sees_a_fatal_limit(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"steps": 500})
            program = ('try {\n  let i = 0\n  while i < 100000 {\n    i = i + 1\n  }\n} catch e {\n  print("caught")\n}'
                       ' finally {\n  print("finally")\n}\nprint("after")')
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(nl.NovaLangError):
                nova.exec(program)
            self.assertEqual(out.getvalue(), "")        # no catch, no finally, nothing after

    def test_a_fatal_limit_inside_a_function_inside_try_passes_every_frame(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"steps": 500})
            program = ('def spin() {\n  try {\n    while true {\n    }\n  } finally {\n    print("inner")\n  }\n}\n'
                       'try {\n  spin()\n} catch e {\n  print("outer")\n}')
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(nl.NovaLangError):
                nova.exec(program)
            self.assertEqual(out.getvalue(), "")

    def test_a_host_callback_cannot_reset_the_budget(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"steps": 1000})
            nova.exec("def burn(n) {\n  let i = 0\n  while i < n {\n    i = i + 1\n  }\n  return i\n}")
            calls = []

            def host(n):
                calls.append(n)
                return nova.call("burn", 400)                   # a call into the script from inside a run

            nova.expose_global("host", host)
            with self.assertRaises(nl.NovaLangError) as caught:
                nova.eval("let k = 0\nwhile k < 50 {\n  host(1)\n  k = k + 1\n}")
            self.assertIn("step budget", str(caught.exception))
            self.assertLess(len(calls), 50)                     # it stopped: 50 x 400 passes would be 20,000 steps

    def test_a_call_a_host_makes_has_a_budget_of_its_own(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"steps": 1000})
            nova.exec("def burn(n) {\n  let i = 0\n  while i < n {\n    i = i + 1\n  }\n  return i\n}")
            for _ in range(5):                                   # five calls of 600 passes: each within its own budget
                self.assertEqual(nova.call("burn", 600), 600)
            with self.assertRaises(nl.NovaLangError):
                nova.call("burn", 5000)


class Limits(unittest.TestCase):
    def test_a_limit_can_be_lowered_but_not_raised(self):
        nl.Nova(profile="restricted", limits={"list": 10, "string": 10, "dict": 10, "depth": 10})
        for name in ("list", "string", "dict", "depth"):
            with self.assertRaises(nl.NovaLangError, msg=name):
                nl.Nova(profile="restricted", limits={name: nl.LIMIT_REFERENCE[name] + 1})
        nl.Nova(profile="restricted", limits={"steps": 10 ** 9, "time": 10 ** 7, "output": 10 ** 9})   # these may go either way

    def test_the_three_fatal_limits_are_for_restricted_only(self):
        for engine in ENGINES:
            nova = nl.Nova(engine)
            self.assertEqual(nova.eval(LOOP.format(n=20000)), 20000)
            self.assertIsNone(nova.interpreter.limits.steps)
            self.assertIsNone(nova.interpreter.limits.time)
            self.assertIsNone(nova.interpreter.limits.output)

    def test_the_default_budget_lets_a_modest_loop_finish(self):
        for engine in ENGINES:
            self.assertEqual(nl.Nova(engine, profile="restricted").eval(LOOP.format(n=20000)), 20000)

    def test_a_catchable_limit_can_be_caught(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"list": 10})
            out = io.StringIO()
            with redirect_stdout(out):
                nova.exec('try {\n  let l = range(50)\n} catch e {\n  print("caught", e)\n}\nprint("after")')
            self.assertEqual(out.getvalue().splitlines(),
                             ["caught range() would build a list of 50 items, which is too large", "after"])

    def test_sizes_are_refused_before_the_memory_is_used(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"string": 1000, "list": 1000})
            # an operand pair whose result would be 10**12 items is refused from the operands, instantly
            with self.assertRaises(nl.NovaLangError):
                nova.eval('let l = [1]\nlet i = 0\nwhile i < 40 {\n  l = l + l\n  i = i + 1\n}')
            with self.assertRaises(nl.NovaLangError):
                nova.eval('let l = [1, 2]\nfor i = 1 to 40 {\n  l = [l, l]\n}\nstr(l)')
            with self.assertRaises(nl.NovaLangError):
                nova.eval('"x" * 99999999')

    def test_no_python_failure_reaches_the_program(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted")
            for program in ('let s = "ab"\nfor i = 1 to 60 {\n  s = s + s\n}',
                            'let l = [1]\nfor i = 1 to 60 {\n  l = l + l\n}',
                            'let d = {}\nlet i = 0\nwhile i < 2000000 {\n  d[str(i)] = i\n  i = i + 1\n}'):
                with self.assertRaises(nl.NovaLangError, msg=program) as caught:
                    nova.eval(program)
                self.assertNotIn("MemoryError", str(caught.exception))


class Time(unittest.TestCase):
    def test_a_sleep_that_would_pass_the_limit_does_not_start(self):
        import time
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", clock=True, limits={"time": 100})
            started = time.monotonic()
            with self.assertRaises(nl.NovaLangError) as caught:
                nova.eval("sleep(5000)")
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(str(caught.exception), "LimitError: time limit of 100 ms exceeded")


class Output(unittest.TestCase):
    def test_the_write_that_would_pass_the_limit_is_not_made(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", limits={"output": 25})
            out = io.StringIO()
            with redirect_stdout(out), self.assertRaises(nl.NovaLangError):
                nova.exec('print("0123456789")\nprint("0123456789")\nprint("0123456789")')
            self.assertEqual(out.getvalue(), "0123456789\n0123456789\n")        # 22 bytes written, 33 would pass 25


if __name__ == "__main__":
    unittest.main()
