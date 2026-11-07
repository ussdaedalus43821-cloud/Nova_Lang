import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "vm"))
import run_all
import test_differential


class HarnessTests(unittest.TestCase):
    def test_timeouts_never_count_as_parity(self):
        for compare, timeout in ((run_all.same, ("timeout", "")),
                                 (test_differential.same, ("timeout", "", ""))):
            finished = (0,) + timeout[1:]
            for name in ("examples/math.nova", "examples/reactor_sim.nova"):
                for left, right in ((timeout, timeout), (finished, timeout),
                                    (timeout, finished)):
                    with self.subTest(compare=compare.__module__, name=name,
                                      left=left, right=right):
                        self.assertFalse(compare(left, right, name))
                self.assertTrue(compare(finished, finished, name))

    def test_expected_errors_still_compare(self):
        self.assertTrue(run_all.same((1, "error"), (1, "error"), "bad.nova"))
        self.assertTrue(test_differential.same((1, "", "error"), (1, "", "error"),
                                              "bad.nova"))
        self.assertFalse(test_differential.same((1, "", "a"), (1, "", "b"), "bad.nova"))

    def test_report_flushes_and_handles_diagnostic_objects(self):
        report = unittest.mock.Mock(wraps=io.StringIO())
        line = run_all.Line(report)
        line.check(True, "diagnostic", [object()])
        record = json.loads(report.getvalue())
        self.assertTrue(record["passed"])
        self.assertEqual(record["label"], "diagnostic")
        report.flush.assert_called_once()

    def test_station_selection_and_report(self):
        calls = []
        def first(line):
            calls.append("first")
            line.check(True, "first check")
        def second(line):
            calls.append("second")
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "results.jsonl"
            with patch.object(run_all, "STATIONS", [("first", first), ("second", second)]), \
                    contextlib.redirect_stdout(io.StringIO()):
                status = run_all.main(["run_all.py", "--station", "first", "--report", str(report)])
            self.assertEqual(status, 0)
            self.assertEqual(calls, ["first"])
            self.assertEqual(json.loads(report.read_text())["label"], "first check")

    def test_failed_station_returns_failure(self):
        with patch.object(run_all, "STATIONS", [("bad", lambda line: line.check(False, "bad"))]), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run_all.main(["run_all.py"]), 1)

    def test_differential_reports_each_completed_file(self):
        paths = [str(ROOT / name) for name in
                 ("examples/math.nova", "examples/fib.nova", "examples/file_demo.nova")]
        seen = []
        result = ((0, "ok", ""), (0, "ok", ""))
        with patch.object(test_differential, "both", return_value=result):
            results = test_differential.run_all_of(paths, [], lambda path, value: seen.append(path))
        self.assertCountEqual(seen, paths)
        self.assertEqual(seen[-1], paths[-1])
        self.assertEqual(set(results), set(paths))

    def run_stdlib(self, flags, timezone, source=None):
        with tempfile.TemporaryDirectory() as folder:
            script = ROOT / "examples" / "stdlib_full_test.nova"
            if source is not None:
                script = Path(folder) / "stdlib.nova"
                script.write_text(source, encoding="utf-8")
            return subprocess.run([sys.executable, str(ROOT / "novalang.py")] + flags + [str(script)],
                                  cwd=folder, env=dict(os.environ, TZ=timezone),
                                  capture_output=True, text=True, timeout=30)

    def test_stdlib_in_multiple_timezones(self):
        for timezone in ("UTC", "America/Chicago", "Pacific/Kiritimati"):
            for flags in ([], ["--tree-walk"], ["--bootstrap"]):
                with self.subTest(timezone=timezone, flags=flags):
                    result = self.run_stdlib(flags, timezone)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stdout, "All standard library tests passed.\n")

    def test_stdlib_failures_report_count_and_exit_nonzero(self):
        source = (ROOT / "examples" / "stdlib_full_test.nova").read_text()
        source = source.replace('check("abs(-7)", abs(-7), 7)',
                                'check("abs(-7)", abs(-7), 8)')
        for flags in ([], ["--tree-walk"], ["--bootstrap"]):
            result = self.run_stdlib(flags, "UTC", source)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("51 checks run, 1 FAILED:", result.stdout)
            self.assertIn("abs(-7): expected 8, got 7", result.stdout)
            self.assertNotIn("NovaError", result.stderr)


if __name__ == "__main__":
    unittest.main()
