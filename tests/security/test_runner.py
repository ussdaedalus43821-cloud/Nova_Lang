"""The subprocess runner through its Python API and the command line (docs/spec/16-sandbox.md [sbx.runner])."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402


def setUpModule():
    if nl.SANDBOX_UNSUPPORTED:
        raise unittest.SkipTest("the restricted profile needs Python 3.8 or later on Windows")


class Api(unittest.TestCase):
    def test_a_run_that_ends_by_itself_gives_its_output_and_status(self):
        result = nl.run_isolated('print("hi")\nprint(1 + 1)\nexit(3)', process=True)
        self.assertEqual((result.stdout, result.status, result.killed, result.error), ("hi\n2\n", 3, None, ""))

    def test_every_engine_runs_through_it(self):
        for engine, bootstrap in (("vm", False), ("tree", False), ("vm", True)):
            result = nl.run_isolated('print(upper("ok"))', engine=engine, bootstrap=bootstrap)
            self.assertEqual(result.stdout, "OK\n", msg=(engine, bootstrap))

    def test_a_mistake_in_the_settings_is_refused_before_anything_starts(self):
        for settings in ({"reed": ["x"]}, {"limits": {"steps": 0}}, {"read": "data"}):
            with self.assertRaises(nl.NovaLangError, msg=settings):
                nl.run_isolated("print(1)", **settings)

    def test_a_hang_inside_a_call_the_engine_cannot_interrupt_is_killed_from_outside(self):
        started = time.monotonic()
        result = nl.run_isolated('python.import("time")\npython.call("time.sleep", 30)', python=["time"], limits={"time": 400})
        self.assertEqual((result.killed, result.status), ("time", 1))
        self.assertEqual(result.error, "LimitError: time limit of 400 ms exceeded")
        self.assertLess(time.monotonic() - started, 20)

    def test_the_trusted_profile_has_no_deadline_unless_one_is_given(self):
        result = nl.run_isolated("while true {\n}", profile="trusted", wall_ms=300)
        self.assertEqual((result.killed, result.error), ("time", "LimitError: time limit of 300 ms exceeded"))

    def test_a_flood_is_cut_off_at_the_cap(self):
        result = nl.run_isolated('while true {\n  print("x" * 1000)\n}', limits={"output": 10 ** 9, "time": 60000},
                                 output_cap=100000)
        self.assertEqual((result.killed, result.error), ("output", "LimitError: output limit of 100000 bytes exceeded"))
        self.assertLessEqual(len(result.stdout), 100000)

    def test_the_child_has_an_empty_environment_but_for_the_names_passed(self):
        os.environ["NOVA_RUNNER_PROBE"] = "visible"
        try:
            hidden = nl.run_isolated('print(env("NOVA_RUNNER_PROBE"))', env=["NOVA_RUNNER_PROBE"])
            shown = nl.run_isolated('print(env("NOVA_RUNNER_PROBE"))', env=["NOVA_RUNNER_PROBE"],
                                    pass_env=["NOVA_RUNNER_PROBE"])
        finally:
            del os.environ["NOVA_RUNNER_PROBE"]
        self.assertEqual((hidden.stdout, shown.stdout), ("nothing\n", "visible\n"))

    def test_standard_input_reaches_the_child_only_when_the_capability_is_granted(self):
        without = nl.run_isolated("print(input())", input_text="line\n")
        self.assertNotEqual(without.status, 0)               # `input` is not defined without the grant
        self.assertIn("undefined name 'input'", without.stderr)
        granted = nl.run_isolated("print(input())", stdin=True, input_text="line\n")
        self.assertEqual((granted.stdout, granted.status), ("line\n", 0))

    def test_input_the_child_never_reads_does_not_hold_up_the_deadline(self):
        # the pipe to a child that never reads holds about 64 KiB; the rest of 3 MB used to block the parent's write
        # until the child's own limit ended it, with the wall-clock deadline not yet started
        for size in (1, 70000, 3000000):
            started = time.monotonic()
            result = nl.run_isolated("while true {\n}", stdin=True, input_text="x" * size, wall_ms=200,
                                     limits={"time": 5000, "steps": 400000000})
            self.assertEqual((result.killed, result.error), ("time", "LimitError: time limit of 5000 ms exceeded"),
                             msg=size)
            self.assertLess(time.monotonic() - started, 2.0, msg=size)

    def test_the_working_directory_is_the_callers_so_a_relative_grant_means_the_same_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "data"))
            with open(os.path.join(folder, "data", "in.txt"), "w") as handle:
                handle.write("hello")
            here = os.getcwd()
            os.chdir(folder)
            try:
                ok = nl.run_isolated('print(read("data/in.txt"))', read=["data"])
                denied = nl.run_isolated('print(read("../x"))', read=["data"])
            finally:
                os.chdir(here)
        self.assertEqual(ok.stdout, "hello\n")
        self.assertIn("outside the folders", denied.stderr)

    def test_the_child_is_gone_when_the_parent_returns(self):
        # a killed run must not leave its child behind: the same call, repeated, never piles up
        for _ in range(3):
            nl.run_isolated("while true {\n}", profile="trusted", wall_ms=200)

    @unittest.skipUnless(sys.platform.startswith("linux"), "the address-space limit is applied on Linux")
    def test_memory_is_limited_on_linux(self):
        result = nl.run_isolated('let big = []\nlet i = 0\nwhile i < 600 {\n  append(big, "x" * 900000 + str(i))\n'
                                 '  i = i + 1\n}\nprint(len(big))', memory_mb=400, limits={"time": 60000})
        self.assertEqual(result.error, "LimitError: memory limit of 400 MB exceeded")
        self.assertEqual(result.status, 1)


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv, source='print("hello")'):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prog.nova"
            path.write_text(source)
            return subprocess.run([sys.executable, str(ROOT / "novalang.py")] + list(argv) + [str(path)],
                                  capture_output=True, text=True, timeout=90, stdin=subprocess.DEVNULL)

    def test_isolate_runs_the_program(self):
        done = self.run_cli("--isolate", "--profile", "restricted")
        self.assertEqual((done.returncode, done.stdout), (0, "hello\n"))

    def test_the_runner_flags_belong_to_isolate(self):
        for argv in (["--wall-ms", "500"], ["--memory-mb", "100"], ["--output-cap", "100"], ["--pass-env", "HOME"]):
            done = self.run_cli(*argv)
            self.assertEqual(done.returncode, 2, msg=argv)

    def test_the_runner_flags_are_checked(self):
        for argv in (["--isolate", "--wall-ms", "soon"], ["--isolate", "--memory-mb", "0"], ["--isolate", "--wall-ms"]):
            self.assertEqual(self.run_cli(*argv).returncode, 2, msg=argv)

    def test_a_mistake_in_the_sandbox_flags_is_refused_before_the_child_starts(self):
        done = self.run_cli("--isolate", "--profile", "restricted", "--limit", "stepz=5")
        self.assertEqual(done.returncode, 2)

    def test_the_exit_status_comes_through(self):
        done = self.run_cli("--isolate", "--profile", "restricted", "--allow-process", source="exit(5)")
        self.assertEqual(done.returncode, 5)


if __name__ == "__main__":
    unittest.main()
