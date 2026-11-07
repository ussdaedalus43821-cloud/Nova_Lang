"""Real command-line contracts: diagnostics, exit codes and filesystem effects."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FORMATTER = ("tools/nova-fmt.py",)
LINTERS = (("tools/nova-lint.py",), ("novalang.py", "--check"))
DISASSEMBLERS = (("tools/nova_compiler.py",), ("novalang.py", "--dis"))
BOOTSTRAPS = (("bootstrap.py",), ("novalang.py", "--bootstrap"))
MESSY = "let value=1+2\nprint( value )\n"
FORMATTED = "let value = 1 + 2\nprint(value)\n"
BROKEN = "let broken = (\n"


class CliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="nova-cli-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def file(self, name, source):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def invoke(self, entry, *args):
        result = subprocess.run(
            [sys.executable, str(ROOT / entry[0])] + list(entry[1:])
            + [str(arg) for arg in args],
            cwd=self.folder, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotIn("Traceback (most recent call last)", result.stderr)
        return result

    def assert_result(self, result, status, stdout=None, stderr=None):
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        if stdout is not None:
            self.assertEqual(result.stdout, stdout)
        if stderr is not None:
            self.assertEqual(result.stderr, stderr)

    def test_formatter_print_does_not_write_or_execute(self):
        path = self.file("input with spaces.nova", 'write("marker.txt","unexpected")\n')
        original = path.read_bytes()
        result = self.invoke(FORMATTER, path)
        self.assert_result(result, 0, 'write("marker.txt", "unexpected")\n', "")
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((self.folder / "marker.txt").exists())

    def test_formatter_check_reports_changed_file_without_writing(self):
        path = self.file("input.nova", MESSY)
        result = self.invoke(FORMATTER, "--check", path)
        self.assert_result(result, 1, "would reformat {}\n".format(path), "")
        self.assertEqual(path.read_text(), MESSY)

    def test_formatter_check_accepts_canonical_file(self):
        path = self.file("input.nova", FORMATTED)
        self.assert_result(self.invoke(FORMATTER, "--check", path), 0, "", "")
        self.assertEqual(path.read_text(), FORMATTED)

    def test_formatter_write_and_dispatcher_produce_expected_content(self):
        for entry, flags in ((FORMATTER, ["--write"]), (FORMATTER, ["-w"]),
                             (("novalang.py", "--format"), [])):
            with self.subTest(entry=entry, flags=flags):
                path = self.file("input.nova", MESSY)
                result = self.invoke(entry, *flags, path)
                self.assert_result(result, 0, "reformatted {}\n".format(path), "")
                self.assertEqual(path.read_text(), FORMATTED)
                # A second write must be a no-op, including the file timestamp.
                os.utime(path, (946684800, 946684800))
                before = path.stat().st_mtime_ns
                self.assert_result(self.invoke(entry, *flags, path), 0, "", "")
                self.assertEqual(path.read_text(), FORMATTED)
                self.assertEqual(path.stat().st_mtime_ns, before)

    def test_formatter_usage_errors(self):
        for entry, args in ((FORMATTER, []), (FORMATTER, ["--unknown"]),
                            (FORMATTER, ["--write"]), (FORMATTER, ["--check"]),
                            (("novalang.py", "--format"), [])):
            with self.subTest(entry=entry, args=args):
                result = self.invoke(entry, *args)
                self.assert_result(result, 2, "")
                self.assertIn("usage:", result.stderr)

    def test_formatter_read_failures(self):
        for path in (self.folder / "missing.nova", self.folder):
            with self.subTest(path=path):
                result = self.invoke(FORMATTER, path)
                self.assert_result(result, 2, "")
                self.assertIn("nova-fmt: cannot read {}:".format(path), result.stderr)

    def test_formatter_invalid_utf8_preserves_file_and_continues_batch(self):
        path = self.folder / "invalid.nova"
        path.write_bytes(b"\xff\n")
        for entry, flags in ((FORMATTER, []), (FORMATTER, ["--check"]),
                             (FORMATTER, ["--write"]), (("novalang.py", "--format"), [])):
            with self.subTest(entry=entry, flags=flags):
                valid = self.file("valid.nova", MESSY)
                result = self.invoke(entry, *flags, path, valid)
                self.assert_result(result, 2)
                self.assertIn("cannot read {}:".format(path), result.stderr)
                self.assertEqual(path.read_bytes(), b"\xff\n")
                if flags == ["--write"] or entry != FORMATTER:
                    self.assertEqual(valid.read_text(), FORMATTED)
                else:
                    self.assertEqual(valid.read_text(), MESSY)
                    self.assertIn(FORMATTED if not flags else "would reformat", result.stdout)

    def test_formatter_parse_failure_preserves_input(self):
        path = self.file("broken.nova", BROKEN)
        for flags in ([], ["--check"], ["--write"]):
            with self.subTest(flags=flags):
                result = self.invoke(FORMATTER, *flags, path)
                self.assert_result(result, 2, "")
                self.assertIn(str(path), result.stderr)
                self.assertIn("NovaError:", result.stderr)
                self.assertIn("^", result.stderr)
                self.assertEqual(path.read_text(), BROKEN)

    def test_formatter_batch_continues_and_preserves_error_status(self):
        missing = self.folder / "missing.nova"
        changed = self.file("changed.nova", MESSY)
        canonical = self.file("canonical.nova", FORMATTED)
        for paths in ((missing, changed, canonical), (changed, canonical, missing)):
            with self.subTest(paths=paths):
                result = self.invoke(FORMATTER, "--check", *paths)
                self.assert_result(result, 2, "would reformat {}\n".format(changed))
                self.assertIn("cannot read", result.stderr)
                self.assertEqual(changed.read_text(), MESSY)

    def test_formatter_batch_write_processes_valid_files_after_parse_failure(self):
        broken = self.file("broken.nova", BROKEN)
        valid = self.file("valid.nova", MESSY)
        result = self.invoke(FORMATTER, "--write", broken, valid)
        self.assert_result(result, 2, "reformatted {}\n".format(valid))
        self.assertIn("NovaError:", result.stderr)
        self.assertEqual(broken.read_text(), BROKEN)
        self.assertEqual(valid.read_text(), FORMATTED)

    def test_linter_clean_file(self):
        path = self.file("clean.nova", FORMATTED)
        for entry in LINTERS:
            for flags in ([], ["--strict"]):
                with self.subTest(entry=entry, flags=flags):
                    self.assert_result(self.invoke(entry, *flags, path), 0, "", "")

    def test_linter_warning_status_and_position(self):
        path = self.file("warning.nova", "let unused = 1\n")
        expected = "{}:1:1: W001 'unused' is assigned but never used\n".format(path)
        for entry in LINTERS:
            with self.subTest(entry=entry):
                self.assert_result(self.invoke(entry, path), 0, expected, "")
                self.assert_result(self.invoke(entry, "--strict", path), 1, expected, "")

    def test_linter_errors_fail_without_executing_source(self):
        path = self.file("error.nova", 'write("marker.txt", "unexpected")\nprint(missing)\n')
        expected = "{}:2:7: E001 undefined name 'missing'\n".format(path)
        for entry in LINTERS:
            with self.subTest(entry=entry):
                self.assert_result(self.invoke(entry, path), 1, expected, "")
                self.assertFalse((self.folder / "marker.txt").exists())

    def test_linter_usage_errors(self):
        for entry in LINTERS:
            for args in ([], ["--strict"], ["--unknown"]):
                with self.subTest(entry=entry, args=args):
                    result = self.invoke(entry, *args)
                    self.assert_result(result, 2, "")
                    self.assertIn("usage:", result.stderr)

    def test_linter_read_failures(self):
        for entry in LINTERS:
            for path in (self.folder / "missing.nova", self.folder):
                with self.subTest(entry=entry, path=path):
                    result = self.invoke(entry, path)
                    self.assert_result(result, 2, "")
                    self.assertIn("nova-lint: cannot read {}:".format(path), result.stderr)

    def test_linter_invalid_utf8_reports_read_error_and_continues_batch(self):
        path = self.folder / "invalid.nova"
        path.write_bytes(b"\xff\n")
        warning = self.file("warning.nova", "let unused = 1\n")
        for entry in LINTERS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, "--strict", path, warning)
                self.assert_result(result, 2)
                self.assertIn("cannot read {}:".format(path), result.stderr)
                self.assertIn("W001", result.stdout)

    def test_linter_parse_failure(self):
        path = self.file("broken.nova", BROKEN)
        for entry in LINTERS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, path)
                self.assert_result(result, 2, "")
                self.assertIn(str(path), result.stderr)
                self.assertIn("NovaError:", result.stderr)
                self.assertEqual(path.read_text(), BROKEN)

    def test_linter_batch_continues_and_preserves_error_status(self):
        warning = self.file("warning.nova", "let unused = 1\n")
        missing = self.folder / "missing.nova"
        for entry in LINTERS:
            for paths in ((missing, warning), (warning, missing)):
                with self.subTest(entry=entry, paths=paths):
                    result = self.invoke(entry, "--strict", *paths)
                    self.assert_result(result, 2)
                    self.assertIn("W001", result.stdout)
                    self.assertIn("cannot read", result.stderr)

    def test_disassembly_does_not_run_source(self):
        path = self.file("input with spaces.nova", 'def add(a, b) { return a + b }\n'
                         'write("marker.txt", "unexpected")\n')
        outputs = []
        for entry in DISASSEMBLERS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, path)
                self.assert_result(result, 0, stderr="")
                self.assertIn("code <module>\n", result.stdout)
                self.assertIn("code add(a, b)\n", result.stdout)
                self.assertIn("LOAD_CONST", result.stdout)
                self.assertIn("CALL", result.stdout)
                self.assertFalse((self.folder / "marker.txt").exists())
                outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])

    def test_disassembly_usage(self):
        for entry in DISASSEMBLERS:
            with self.subTest(entry=entry):
                result = self.invoke(entry)
                self.assert_result(result, 2, "")
                self.assertIn("usage:", result.stderr)

    def test_disassembly_read_and_parse_failures(self):
        broken = self.file("broken.nova", BROKEN)
        for entry in DISASSEMBLERS:
            for path in (self.folder / "missing.nova", self.folder, broken):
                with self.subTest(entry=entry, path=path):
                    result = self.invoke(entry, path)
                    self.assert_result(result, 2, "")
                    self.assertIn(str(path), result.stderr)
                    self.assertIn("NovaError:" if path == broken else "cannot read", result.stderr)

    def test_disassembly_invalid_utf8_reports_read_error_and_continues_batch(self):
        path = self.folder / "invalid.nova"
        path.write_bytes(b"\xff\n")
        valid = self.file("valid.nova", "print(42)\n")
        for entry in DISASSEMBLERS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, path, valid)
                self.assert_result(result, 2)
                self.assertIn("cannot read {}:".format(path), result.stderr)
                self.assertIn("== {}\n".format(valid), result.stdout)
                self.assertIn("code <module>\n", result.stdout)

    def test_disassembly_batch_continues_after_errors(self):
        broken = self.file("broken.nova", BROKEN)
        first = self.file("first.nova", "print(1)\n")
        second = self.file("second.nova", "print(2)\n")
        for entry in DISASSEMBLERS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, first, broken, second)
                self.assert_result(result, 2)
                self.assertIn("== {}\n".format(first), result.stdout)
                self.assertIn("== {}\n".format(second), result.stdout)
                self.assertEqual(result.stdout.count("code <module>\n"), 2)
                self.assertIn("NovaError:", result.stderr)

    def test_bootstrap_usage(self):
        for entry in BOOTSTRAPS:
            with self.subTest(entry=entry):
                result = self.invoke(entry)
                self.assert_result(result, 2, "")
                self.assertIn("usage:", result.stderr)

    def test_bootstrap_forwards_args_and_resolves_target_relative_imports(self):
        self.file("project dir/helper.nova", "export def answer() { return 42 }\n")
        target = self.file("project dir/target with spaces.nova",
                           'import "./helper.nova" as helper\n'
                           'print(helper.answer())\nprint(join(args(), "|"))\n')
        for entry in BOOTSTRAPS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, target, "argument", "two words", '"quoted"', "\\slash")
                self.assert_result(result, 0, '42\nargument|two words|"quoted"|\\slash\n', "")

    def test_bootstrap_missing_or_unreadable_target(self):
        for entry in BOOTSTRAPS:
            for path in (self.folder / "missing.nova", self.folder):
                with self.subTest(entry=entry, path=path):
                    result = self.invoke(entry, path)
                    self.assert_result(result, 1, "")
                    self.assertIn("FileNotFoundError:" if path.name == "missing.nova"
                                  else "FileError:", result.stderr)
                    self.assertIn(str(path), result.stderr)

    def test_bootstrap_invalid_utf8_is_a_file_error(self):
        path = self.folder / "invalid.nova"
        path.write_bytes(b"\xff\n")
        for entry in BOOTSTRAPS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, path)
                self.assert_result(result, 1, "")
                self.assertIn("FileError:", result.stderr)
                self.assertIn(str(path), result.stderr)

    def test_direct_execution_invalid_utf8_is_a_file_error(self):
        path = self.folder / "invalid.nova"
        path.write_bytes(b"\xff\n")
        for entry in (("novalang.py",), ("novalang.py", "--tree-walk")):
            with self.subTest(entry=entry):
                result = self.invoke(entry, path)
                self.assert_result(result, 1, "")
                self.assertIn("FileError:", result.stderr)
                self.assertIn(str(path), result.stderr)

    def test_bootstrap_syntax_errors_do_not_execute_source(self):
        target = self.file("broken.nova", 'write("marker.txt", "unexpected")\n' + BROKEN)
        for entry in BOOTSTRAPS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, target)
                self.assert_result(result, 1, "")
                self.assertIn("ParseError@", result.stderr)
                self.assertFalse((self.folder / "marker.txt").exists())

    def test_bootstrap_type_errors_refuse_before_execution(self):
        target = self.file("typed.nova", 'write("marker.txt", "unexpected")\nlet total: int = "wrong"\n')
        for entry in BOOTSTRAPS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, target)
                self.assert_result(result, 1, "")
                self.assertIn("TypeCheckError:", result.stderr)
                self.assertFalse((self.folder / "marker.txt").exists())

    def test_bootstrap_runtime_errors_preserve_prior_output(self):
        target = self.file("runtime.nova", 'print("before")\nthrow("boom")\nprint("after")\n')
        for entry in BOOTSTRAPS:
            with self.subTest(entry=entry):
                result = self.invoke(entry, target)
                self.assert_result(result, 1, "before\n")
                self.assertIn("boom", result.stderr)

    def test_bootstrap_preserves_script_exit_status(self):
        target = self.file("exit.nova", "exit(7)\n")
        for entry in BOOTSTRAPS:
            with self.subTest(entry=entry):
                self.assert_result(self.invoke(entry, target), 7, "", "")


if __name__ == "__main__":
    unittest.main()
