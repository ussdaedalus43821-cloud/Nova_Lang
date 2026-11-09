"""The deterministic mode through the embedding API and the command line (docs/spec/16-sandbox.md [sbx.determinism])."""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

ENGINES = ("vm", "tree")
PROGRAM = "[random(), randint(1, 100), choice([1, 2, 3, 4, 5]), shuffle([1, 2, 3, 4, 5, 6]), time(), now()]"


class Replay(unittest.TestCase):
    def test_the_same_seed_and_start_give_the_same_values_on_both_engines_and_every_time(self):
        seen = set()
        for engine in ENGINES:
            for _ in range(3):
                nova = nl.Nova(engine, deterministic=True, seed=5, clock_start=1000.25)
                seen.add(repr(nova.eval(PROGRAM)))
        self.assertEqual(len(seen), 1)

    def test_another_seed_gives_another_sequence(self):
        a = nl.Nova(deterministic=True, seed=1).eval("[random(), random()]")
        b = nl.Nova(deterministic=True, seed=2).eval("[random(), random()]")
        self.assertNotEqual(a, b)

    def test_without_the_mode_nothing_changes(self):
        values = {nl.Nova().eval("random()") for _ in range(5)}
        self.assertGreater(len(values), 1)
        self.assertAlmostEqual(nl.Nova().eval("time()"), time.time(), delta=5)

    def test_the_engine_keeps_its_state_between_evals_and_a_new_engine_starts_over(self):
        nova = nl.Nova(deterministic=True, seed=3)
        first, second = nova.eval("random()"), nova.eval("random()")
        self.assertNotEqual(first, second)
        self.assertEqual(nl.Nova(deterministic=True, seed=3).eval("random()"), first)

    def test_sleep_does_not_wait(self):
        nova = nl.Nova(deterministic=True)
        started = time.monotonic()
        nova.exec("sleep(3600000)")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(nova.eval("monotonic()"), 3600.0)

    def test_the_virtual_sleep_does_not_count_against_the_time_limit(self):
        nova = nl.Nova(profile="restricted", clock=True, random=True, deterministic=True, limits={"time": 100})
        nova.exec("sleep(86400000)")
        self.assertEqual(nova.eval("monotonic()"), 86400.0)


class Configuration(unittest.TestCase):
    def test_seed_and_start_need_the_mode(self):
        for settings in ({"seed": 1}, {"clock_start": 5.0}):
            with self.assertRaises(nl.NovaLangError, msg=settings):
                nl.Nova(**settings)

    def test_the_settings_are_checked(self):
        for settings in ({"deterministic": "yes"}, {"deterministic": True, "seed": 1.5},
                         {"deterministic": True, "seed": True}, {"deterministic": True, "clock_start": "now"},
                         {"deterministic": True, "clock_start": 10 ** 12}):
            with self.assertRaises(nl.NovaLangError, msg=settings):
                nl.Nova(**settings)

    def test_trusted_takes_the_mode_but_still_no_grants(self):
        nl.Nova(profile="trusted", deterministic=True, seed=1)
        with self.assertRaises(nl.NovaLangError):
            nl.Nova(profile="trusted", deterministic=True, read=["data"])

    def test_the_mode_does_not_grant_the_functions(self):
        nova = nl.Nova(profile="restricted", deterministic=True)
        for name in ("random()", "time()", "now()", "sleep(1)"):
            with self.assertRaises(nl.NovaLangError, msg=name) as caught:
                nova.eval(name)
            self.assertIn("undefined name", str(caught.exception))


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv, source="print(random(), now())"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prog.nova"
            path.write_text(source)
            return subprocess.run([sys.executable, str(ROOT / "novalang.py")] + list(argv) + [str(path)],
                                  capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)

    def test_the_flags_select_the_mode_and_all_engines_agree(self):
        flags = ["--deterministic", "--seed", "42", "--clock-start", "86400"]
        outputs = {self.run_cli(*extra, *flags).stdout for extra in ([], ["--tree-walk"])}
        self.assertEqual(len(outputs), 1)
        self.assertEqual(next(iter(outputs)).split()[1], "1970-01-02T00:00:00+00:00")

    def test_mistakes_in_the_flags_are_refused(self):
        for argv in (["--seed", "7"], ["--clock-start", "5"], ["--deterministic", "--seed", "many"],
                     ["--deterministic", "--clock-start", "soon"]):
            done = self.run_cli(*argv)
            self.assertEqual(done.returncode, 2, msg=argv)


if __name__ == "__main__":
    unittest.main()
