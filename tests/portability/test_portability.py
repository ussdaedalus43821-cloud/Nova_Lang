"""Behavior that must not depend on the platform, tested on every platform by
simulating the one that differs.

Each case here was found failing on Windows by the first run of the full CI
matrix (docs/CI.md). The simulations let Linux and macOS runs hold the same
line: a patched platform.system(), a forced non-SIGALRM time limit, a text
mode that translates newlines, and pathlib's pure Windows paths.
"""

import builtins
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "vm"))

import bootstrap  # noqa: E402
import differential  # noqa: E402
import novalang  # noqa: E402


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SelfHostedPathTests(unittest.TestCase):
    """novalang.nova names modules from paths the way the host's os.sep and
    os.path.basename do: backslashes on Windows, never on POSIX."""

    @classmethod
    def setUpClass(cls):
        cls.engine = (ROOT / "novalang.nova").read_text(encoding="utf-8")

    def run_nova(self, system, *calls):
        program = self.engine + "\n" + "\n".join(calls) + "\n"
        captured = io.StringIO()
        with mock.patch("platform.system", return_value=system), contextlib.redirect_stdout(captured):
            novalang.run(program, novalang.Interpreter("vm"))
        return captured.getvalue().splitlines()

    @staticmethod
    def call(function, path):
        return "print({}({}, 0))".format(function, bootstrap.nova_string_literal(path))

    def test_windows_paths(self):
        windows = "C:\\Users\\runner\\proj\\.nova_modules\\cyc-a\\main.nova"
        got = self.run_nova(
            "Windows",
            self.call("module_label", windows),
            self.call("default_module_name", "C:\\Users\\runner\\proj\\shapes.nova"),
            self.call("default_module_name", "./sub/mod.nova"),
        )
        self.assertEqual(got, ["cyc-a/main.nova", "shapes", "mod"])

    def test_posix_paths_match_the_host(self):
        path = "/proj/.nova_modules/cyc-a/main.nova"
        got = self.run_nova(
            "Linux",
            self.call("module_label", path),
            self.call("default_module_name", "a/b/mod.nova"),
        )
        self.assertEqual(got, ["cyc-a/main.nova", "mod"])
        if os.sep == "/":  # the host reads the real platform, so compare only where it agrees
            self.assertEqual(got[0], novalang.module_label(path))
            self.assertEqual(got[1], novalang.default_module_name("a/b/mod.nova", None))

    def test_backslash_is_not_a_separator_on_posix(self):
        got = self.run_nova(
            "Linux",
            'try { print(default_module_name("a\\\\b.nova", 0)) } catch e { print("refused") }',
        )
        self.assertEqual(got, ["refused"])


class DeadlineTests(unittest.TestCase):
    """The differential tests' time limit works where SIGALRM does not exist."""

    def test_thread_deadline_interrupts_a_busy_loop(self):
        started = time.time()
        with self.assertRaises(differential.Timeout):
            with differential.thread_deadline(1):
                while True:
                    pass
        self.assertLess(time.time() - started, 5)

    def test_thread_deadline_does_not_fire_after_the_body_finishes(self):
        with differential.thread_deadline(0.2):
            pass
        time.sleep(0.6)  # a stray Timeout would surface here

    def test_a_program_that_never_finishes_is_reported_without_sigalrm(self):
        with mock.patch.object(differential, "HAS_SIGALRM", False):
            out, error, status = differential.outcome("while true { }", "vm", seconds=1)
        self.assertEqual((out, status), ("", -1))
        self.assertIn("did not finish", error)

    def test_a_finishing_program_is_unaffected_without_sigalrm(self):
        with mock.patch.object(differential, "HAS_SIGALRM", False):
            self.assertEqual(differential.outcome("print(1 + 2)", "vm"), ("3\n", "", 0))


class FormatterOutputTests(unittest.TestCase):
    def test_write_gives_the_same_bytes_whatever_the_text_mode(self):
        formatter = load_tool("nova-fmt")
        real_open = builtins.open

        def windows_open(path, mode="r", *args, **kwargs):
            # Text mode with no newline argument writes os.linesep: CRLF on Windows.
            if "w" in mode and "b" not in mode and kwargs.get("newline") is None:
                kwargs["newline"] = "\r\n"
            return real_open(path, mode, *args, **kwargs)

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "f.nova"
            target.write_bytes(b"let a=1\n")
            with mock.patch.object(formatter, "open", windows_open, create=True), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(formatter.main(["nova-fmt.py", "--write", str(target)]), 0)
            self.assertEqual(target.read_bytes(), b"let a = 1\n")


class LanguageServerUriTests(unittest.TestCase):
    def test_windows_paths_become_canonical_file_uris(self):
        server = load_tool("nova-lsp")
        path = "C:\\Users\\runner\\Temp\\ws\\a b.nova"
        with mock.patch("pathlib.Path", PureWindowsPath), mock.patch("os.path.abspath", lambda p: p):
            uri = server.path_to_uri(path)
        self.assertEqual(uri, "file:///C:/Users/runner/Temp/ws/a%20b.nova")

    def test_posix_paths_are_unchanged(self):
        server = load_tool("nova-lsp")
        self.assertEqual(server.path_to_uri("/tmp/with space/é.nova"), "file:///tmp/with%20space/%C3%A9.nova")


if __name__ == "__main__":
    unittest.main()
