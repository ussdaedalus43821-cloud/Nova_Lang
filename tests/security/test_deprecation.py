"""Deprecation warnings and the gate on their test hook (docs/spec/10-host.md [host.warnings] and [host.probe],
docs/spec/11-embedding.md [emb.warnings]).

The conformance corpus (cases/deprecation.json, the `emb-warnings-*` cases) proves the three engines agree. These tests
prove what a corpus cannot: what the command line and an embedding host see, and that no program can reach the hook.
"""

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

PROBE = "_deprecated_probe"
ENGINE_FLAGS = {"vm": [], "tree": ["--tree-walk"], "bootstrap": ["--bootstrap"]}
RESTRICTED_NEEDS_PYTHON_38 = "the restricted profile needs Python 3.8 or later on Windows ([sbx.profiles])"
LINE = re.compile(r"^warning: _deprecated_probe\(\) is deprecated since 2\.4; use nothing \(a test hook\) "
                  r"\(removal not before 3\.0\) \(line (\d+)\)$")


def nova(flags, source, engine="vm", cwd=None):
    """(status, stdout, stderr) of `novalang.py FLAGS program` on one engine. `flags` come before the engine's own."""
    with tempfile.TemporaryDirectory(prefix="nova-dep-") as folder:
        path = os.path.join(folder, "main.nova")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(source)
        engine_flags = ENGINE_FLAGS[engine]
        command = [sys.executable, str(ROOT / "novalang.py")] + [f for f in engine_flags if f != "--bootstrap"] + list(flags)
        command += (["--bootstrap"] if engine == "bootstrap" else []) + [path]
        done = subprocess.run(command, capture_output=True, cwd=cwd or folder,
                              env=dict(os.environ, PYTHONUTF8="1"), timeout=120)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


class Table(unittest.TestCase):
    def test_the_table_in_the_interpreter_is_the_list_in_the_specification(self):
        text = (ROOT / "docs" / "spec" / "DEPRECATIONS.md").read_text(encoding="utf-8")
        listed = set()
        for row in text.splitlines():
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            if row.startswith("|") and len(cells) == 4 and not row.startswith("| ---") and cells[0] != "Item" \
                    and not cells[0].startswith("*("):
                listed.add(cells[0].strip("`").replace("()", ""))
        self.assertEqual(listed, set(nl.DEPRECATED))

    def test_the_probe_is_not_a_builtin_and_not_in_the_real_table(self):
        self.assertNotIn(PROBE, nl.BUILTINS)
        self.assertNotIn(PROBE, nl.DEPRECATED)
        self.assertNotIn(PROBE, nl.CAPABILITY_OF)


class CommandLine(unittest.TestCase):
    PROGRAM = 'print("a")\nfor i in range(3) {\n    _deprecated_probe()\n}\n_deprecated_probe()\nprint("b")\n'

    def test_each_call_site_warns_once_on_stderr_and_stdout_and_status_are_untouched(self):
        for engine in ENGINE_FLAGS:
            with self.subTest(engine):
                status, out, err = nova(["--_deprecation-probe"], self.PROGRAM, engine)
                self.assertEqual((status, out.split()), (0, ["a", "b"]))
                lines = err.strip().splitlines()
                self.assertEqual([int(LINE.match(line).group(1)) for line in lines], [3, 5], err)

    def test_off_says_nothing_and_both_spellings_of_the_flag_work(self):
        for engine in ENGINE_FLAGS:
            for flags in (["--warnings=off"], ["--warnings", "off"]):
                with self.subTest(engine=engine, flags=flags):
                    status, out, err = nova(["--_deprecation-probe"] + flags, self.PROGRAM, engine)
                    self.assertEqual((status, err), (0, ""))

    def test_error_ends_the_run_with_status_1_and_cannot_be_caught(self):
        program = 'print("before")\ntry {\n    _deprecated_probe()\n} catch e {\n    print("caught")\n} finally {\n    print("finally")\n}\n'
        for engine in ENGINE_FLAGS:
            with self.subTest(engine):
                status, out, err = nova(["--_deprecation-probe", "--warnings=error"], program, engine)
                self.assertEqual((status, out.split()), (1, ["before"]))
                self.assertIn("DeprecationError: _deprecated_probe() is deprecated since 2.4", err)
                self.assertNotIn("warning:", err)

    def test_a_mode_that_is_not_one_is_a_usage_error(self):
        for flags in (["--warnings=loud"], ["--warnings", "loud"], ["--warnings"]):
            with self.subTest(flags):
                status, out, err = nova(flags, "print(1)\n")
                self.assertEqual((status, out), (2, ""))
                self.assertIn("--warnings needs", err)

    def test_the_deterministic_mode_prints_no_warning(self):
        for engine in ENGINE_FLAGS:
            with self.subTest(engine):
                status, out, err = nova(["--_deprecation-probe", "--profile", "trusted", "--deterministic"], self.PROGRAM, engine)
                self.assertEqual((status, out.split(), err), (0, ["a", "b"], ""))

    def test_a_function_of_the_programs_own_with_that_name_is_not_deprecated(self):
        program = 'def _deprecated_probe() {\n    return 1\n}\nprint(_deprecated_probe())\n'
        for engine in ENGINE_FLAGS:
            with self.subTest(engine):
                status, out, err = nova(["--_deprecation-probe"], program, engine)
                self.assertEqual((status, out.split(), err), (0, ["1"], ""))


class Embedding(unittest.TestCase):
    SOURCE = 'for i in range(3) {\n    _deprecated_probe()\n}\n_deprecated_probe()\nprint("done")\n'

    def run_it(self, **settings):
        out, err = io.StringIO(), io.StringIO()
        seen = []
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            engine = nl.Nova(_deprecation_probe=True, warning=seen.append, **settings)
            engine.exec(self.SOURCE)
        return engine, seen, out.getvalue(), err.getvalue()

    def test_the_callback_and_the_log_get_the_same_lines_and_nothing_is_printed(self):
        for engine_name in ("vm", "tree"):
            with self.subTest(engine_name):
                engine, seen, out, err = self.run_it(engine=engine_name)
                self.assertEqual(engine.warning_log, seen)
                self.assertEqual([int(LINE.match(line).group(1)) for line in seen], [2, 4])
                self.assertEqual((out, err), ("done\n", ""))

    def test_the_log_is_a_copy(self):
        engine, _, _, _ = self.run_it()
        engine.warning_log.append("x")
        self.assertEqual(len(engine.warning_log), 2)

    def test_off_calls_nothing_and_error_raises_the_deprecation_error(self):
        engine, seen, _, _ = self.run_it(warnings="off")
        self.assertEqual((seen, engine.warning_log), ([], []))
        with self.assertRaises(nl.NovaLangError) as caught:
            self.run_it(warnings="error")
        self.assertIn("DeprecationError: _deprecated_probe() is deprecated since 2.4", str(caught.exception))

    def test_a_call_site_is_remembered_per_engine(self):
        first, _, _, _ = self.run_it()
        second, _, _, _ = self.run_it()
        self.assertEqual((len(first.warning_log), len(second.warning_log)), (2, 2))

    def test_the_settings_are_checked_when_the_engine_is_made(self):
        with self.assertRaises(ValueError):
            nl.Nova(warnings="loud")
        with self.assertRaises(TypeError):
            nl.Nova(warning="not callable")

    def test_without_the_request_there_is_no_probe_and_nothing_is_ever_logged(self):
        engine = nl.Nova()
        with self.assertRaises(nl.NovaLangError) as caught:
            engine.exec("_deprecated_probe()")
        self.assertIn("undefined name '_deprecated_probe'", str(caught.exception))
        self.assertEqual(engine.warning_log, [])


class Gate(unittest.TestCase):
    """How the hook is kept away from programs: the user's condition for item 3 of L6."""

    PROGRAM = 'print("a")\n_deprecated_probe()\n'

    def test_a_trusted_program_cannot_name_it_unless_the_host_asked(self):
        for engine in ENGINE_FLAGS:
            with self.subTest(engine):
                status, out, err = nova([], self.PROGRAM, engine)
                self.assertEqual((status, out.split()), (1, ["a"]))
                self.assertIn("undefined name '{}'".format(PROBE), err)
                self.assertNotIn("warning:", err)

    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED_NEEDS_PYTHON_38)
    def test_a_restricted_program_cannot_use_it_on_any_engine_with_or_without_every_grant(self):
        with tempfile.TemporaryDirectory(prefix="nova-dep-grant-") as granted:
            profiles = {
                "nothing": ["--profile", "restricted"],
                "every grant": ["--profile", "restricted", "--allow-read", granted, "--allow-write", granted,
                                "--allow-import", granted, "--allow-env", "PATH", "--allow-clock", "--allow-random",
                                "--allow-stdin", "--allow-process", "--allow-regex"],
                "a warnings mode": ["--profile", "restricted", "--warnings=error"],
            }
            for engine in ENGINE_FLAGS:
                for label, flags in profiles.items():
                    with self.subTest(engine=engine, grants=label):
                        status, out, err = nova(flags, self.PROGRAM, engine)
                        self.assertEqual((status, out.split()), (1, ["a"]))
                        self.assertIn("undefined name '{}'".format(PROBE), err)
                        self.assertNotIn("warning:", err)
                        self.assertNotIn("DeprecationError", err)

    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED_NEEDS_PYTHON_38)
    def test_a_restricted_embedded_engine_cannot_use_it_either(self):
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                nova_engine = nl.Nova(engine, profile="restricted")
                with self.assertRaises(nl.NovaLangError) as caught, contextlib.redirect_stdout(io.StringIO()):
                    nova_engine.exec(self.PROGRAM)
                self.assertIn("undefined name '{}'".format(PROBE), str(caught.exception))
                self.assertEqual(nova_engine.warning_log, [])

    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED_NEEDS_PYTHON_38)
    def test_asking_for_it_in_the_restricted_profile_fails_before_any_program_runs(self):
        for engine in ENGINE_FLAGS:
            with self.subTest(engine):
                status, out, err = nova(["--profile", "restricted", "--_deprecation-probe"], self.PROGRAM, engine)
                self.assertEqual((status, out), (2, ""))
                self.assertIn("not available with --profile restricted", err)
        for engine in ("vm", "tree"):
            with self.subTest("embedding " + engine):
                with self.assertRaises(nl.NovaLangError) as caught:
                    nl.Nova(engine, profile="restricted", _deprecation_probe=True)
                self.assertIn("not available in the restricted profile", str(caught.exception))
        with self.assertRaises(nl.NovaLangError):
            nl.Nova(profile="restricted", clock=True, limits={"steps": 100000}, _deprecation_probe=True)

    def test_no_environment_variable_or_program_function_switches_it_on(self):
        # The request is made by whoever starts the engine, in code or with a flag. Nothing a process inherits does it,
        # and the program itself has no function that changes its engine's settings.
        program = 'print(env("NOVA_DEPRECATION_PROBE"))\n_deprecated_probe()\n'
        with tempfile.TemporaryDirectory(prefix="nova-dep-") as folder:
            path = os.path.join(folder, "main.nova")
            Path(path).write_text(program, encoding="utf-8")
            for name in ("NOVA_DEPRECATION_PROBE", "NOVA_TEST_HOOKS", "NOVA_DEPRECATION_TEST"):
                done = subprocess.run([sys.executable, str(ROOT / "novalang.py"), path], capture_output=True,
                                      env=dict(os.environ, **{name: "1"}), timeout=60)
                self.assertEqual(done.returncode, 1)
                self.assertIn("undefined name", done.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
