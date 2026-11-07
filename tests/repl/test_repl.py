"""Exercise the real REPL entry points using piped input."""

from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROMPT = "nova> "
CONTINUE = "  ... "
GOODBYE = "Goodbye, star-traveller.\n"


class ReplContract:
    def session(self, source, status=0):
        result = subprocess.run(
            [sys.executable, str(ROOT / "novalang.py"), *self.flags],
            input=source, cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("InternalError:", result.stdout)
        _, prompt, transcript = result.stdout.partition(PROMPT)
        self.assertEqual(prompt, PROMPT)
        return prompt + transcript

    def test_multiline_function_runs_only_when_called(self):
        output = self.session(
            'def announce() {\nprint("called")\n}\n'
            'print("defined")\nannounce()\n'
        )
        self.assertEqual(output,
                         PROMPT + CONTINUE * 2 + "<function announce()>\n"
                         + PROMPT + "defined\n" + PROMPT + "called\n"
                         + PROMPT + "\n" + GOODBYE)

    def test_nested_blocks_and_blank_lines(self):
        output = self.session("def choose(x)\n{\nif x > 0 {\n\nreturn x + 1\n}\n"
                              "return 0\n}\nchoose(4)\nchoose(0)\n")
        self.assertIn(PROMPT + CONTINUE * 7 + "<function choose(x)>\n", output)
        self.assertTrue(output.endswith(PROMPT + "5\n" + PROMPT + "0\n"
                                        + PROMPT + "\n" + GOODBYE))

    def test_blank_line_inside_open_list_preserves_draft(self):
        output = self.session("let scores = [\n7\n\n]\nscores[0] * 6\n")
        self.assertEqual(output, PROMPT + CONTINUE * 3 + "[7]\n" + PROMPT + "42\n"
                         + PROMPT + "\n" + GOODBYE)

    def test_blank_line_submits_incomplete_header_or_expression(self):
        for draft, diagnostic in (("def abandoned()", "expected a '{' to open the block"),
                                  ("1 +", "expression ends too early")):
            with self.subTest(draft=draft):
                output = self.session(draft + "\n\n40 + 2\n")
                self.assertIn(diagnostic, output)
                self.assertTrue(output.endswith(PROMPT + "42\n" + PROMPT + "\n" + GOODBYE))

    def test_syntax_error_leaves_prior_state_available(self):
        output = self.session("let base = 40\nlet = 7\nbase + 2\n")
        self.assertIn("NovaError:", output)
        self.assertTrue(output.endswith(PROMPT + "42\n" + PROMPT + "\n" + GOODBYE))

    def test_runtime_error_recovery_clears_call_frames(self):
        output = self.session(
            "let base = 40\ndef bad() { return 1 / 0 }\n"
            "def outer() { return bad() }\ndef good() { return base + 2 }\n"
            "bad()\nouter()\ngood()\n"
        )
        frames = [line for line in output.splitlines() if line.startswith("  in ")]
        self.assertEqual(frames, ["  in bad()", "  in bad()", "  in outer()"])
        self.assertEqual(output.count("division by zero"), 2)
        self.assertTrue(output.endswith(PROMPT + "42\n" + PROMPT + "\n" + GOODBYE))

    def test_undefined_name_and_type_error_recover(self):
        output = self.session("missing\n1 + true\n40 + 2\n")
        self.assertIn("undefined name 'missing'", output)
        self.assertIn("a number and a boolean", output)
        self.assertTrue(output.endswith(PROMPT + "42\n" + PROMPT + "\n" + GOODBYE))

    def test_empty_eof(self):
        self.assertEqual(self.session(""), PROMPT + "\n" + GOODBYE)

    def test_complete_final_line_with_or_without_newline(self):
        for source in ("print(42)", "print(42)\n"):
            with self.subTest(source=source):
                self.assertEqual(self.session(source),
                                 PROMPT + "42\n" + PROMPT + "\n" + GOODBYE)

    def test_incomplete_eof_reports_error_without_executing_draft(self):
        for source, diagnostic in (("let value = (", "expression ends too early"),
                                   ('if true {\nprint("DRAFT")', "never closed")):
            with self.subTest(source=source):
                output = self.session(source)
                self.assertIn(CONTINUE, output)
                self.assertIn(diagnostic, output)
                self.assertNotIn("\nDRAFT\n", output)
                self.assertTrue(output.endswith(PROMPT + "\n" + GOODBYE))

    def test_assignment_and_function_redefinition(self):
        output = self.session("let base = 5\ndef value() { return base }\nvalue()\n"
                              "base = 9\nvalue()\ndef value() { return base + 1 }\n"
                              "value()\nvars\n")
        self.assertIn(PROMPT + "5\n" + PROMPT + "9\n" + PROMPT + "9\n", output)
        self.assertIn(PROMPT + "10\n", output)
        self.assertIn("  base = 9\n", output)

    def test_tree_command_does_not_evaluate_expression(self):
        output = self.session('tree\ntree print("DRAFT")\nprint("live")\n')
        self.assertIn("usage: tree <code>\n", output)
        self.assertIn("CallNode", output)
        self.assertNotIn("\nDRAFT\n", output)
        self.assertTrue(output.endswith(PROMPT + "live\n" + PROMPT + "\n" + GOODBYE))

    def test_quit_and_exit_commands(self):
        for command in ("quit", "EXIT"):
            with self.subTest(command=command):
                self.assertEqual(self.session(command + '\nprint("DRAFT")\n'),
                                 PROMPT + GOODBYE)
        self.assertEqual(self.session("exit()"), PROMPT)
        self.assertEqual(self.session("exit(7)", status=7), PROMPT)


class VmReplTests(ReplContract, unittest.TestCase):
    flags = ()


class TreeReplTests(ReplContract, unittest.TestCase):
    flags = ("--tree-walk",)
