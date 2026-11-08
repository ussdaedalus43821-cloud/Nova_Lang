"""Exercise the real REPL entry points using piped input."""

from pathlib import Path
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROMPT = "nova> "
CONTINUE = "  ... "
GOODBYE = "Goodbye, star-traveller.\n"
STOPPED = "\n(stopped)\n"
DISCARDED = "\n(input discarded)\n"


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

    def test_blank_line_ignores_braces_that_are_not_blocks(self):
        # A "{" inside a string, an f-string or a comment opens no block, so a
        # blank line submits the unfinished draft (to show the error) exactly as
        # it does for `1 +`. It once kept the draft open, on the raw character.
        for draft in ('let text = "{" +', "1 + # {", 'let text = f"{1}" +'):
            with self.subTest(draft=draft):
                output = self.session(draft + "\n\n40 + 2\n")
                self.assertIn("expression ends too early", output)
                self.assertTrue(output.endswith(PROMPT + "42\n" + PROMPT + "\n" + GOODBYE))

    def test_blank_line_still_keeps_a_real_open_block(self):
        for draft in ("if true {", "if true { 1 } else", "def f() {"):
            with self.subTest(draft=draft):
                output = self.session(draft + "\n\n}\n" if draft.endswith("{") else draft + "\n\n{ 2 }\n")
                self.assertNotIn("expression ends too early", output)
                self.assertNotIn("NovaError", output)

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

    # -- help ----------------------------------------------------------------

    def test_help_prints_the_reference_and_changes_nothing(self):
        output = self.session("let base = 40\nhelp\nHELP\nbase + 2\n")
        self.assertEqual(output, PROMPT + "40\n" + (PROMPT + novalang_help() + "\n") * 2
                         + PROMPT + "42\n" + PROMPT + "\n" + GOODBYE)

    def test_help_documents_commands_that_work(self):
        text = novalang_help()
        self.assertTrue(text.startswith("NovaLang v"))
        commands = text.split("REPL commands")[1].split("Values")[0]
        for command in ("vars", "tree <code>", "help", "exit | quit"):
            self.assertIn(command, commands)
        for claim in ("Ctrl-C", "--tree-walk", "--dis", "--bootstrap"):
            self.assertIn(claim, text)
        # Each documented command is real: none is reported as an error.
        output = self.session("vars\ntree 1 + 2\nhelp\nquit\n")
        self.assertNotIn("NovaError", output)
        self.assertIn("  PI = 3.14159", output)         # `vars` lists the predefined globals
        self.assertIn("BinOpNode", output)

    def test_help_inside_an_open_block_is_code_not_a_command(self):
        output = self.session("if true {\nhelp\n}\n")
        self.assertIn("undefined name 'help'", output)
        self.assertNotIn("REPL commands", output)

    # -- Ctrl-C --------------------------------------------------------------

    def interrupted(self, steps):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tests" / "repl" / "interrupt_driver.py"),
             json.dumps(steps), json.dumps(list(self.flags))],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertNotIn("Traceback", result.stdout)
        self.assertNotIn("InternalError:", result.stdout)
        _, prompt, transcript = result.stdout.partition(PROMPT)
        return prompt + transcript

    def test_ctrl_c_at_the_prompt_starts_a_fresh_line(self):
        self.assertEqual(self.interrupted(["let base = 40", "^C", "^C", "base + 2"]),
                         PROMPT + "40\n" + PROMPT + "\n" + PROMPT + "\n"
                         + PROMPT + "42\n" + PROMPT + "\n" + GOODBYE)

    def test_ctrl_c_discards_a_draft_and_nothing_of_it_runs(self):
        output = self.interrupted(["let base = 40", "def f(x) {", "return 1", "^C",
                                   "f", "base + 2"])
        self.assertIn(PROMPT + CONTINUE * 2 + DISCARDED + PROMPT, output)
        self.assertIn("undefined name 'f'", output)       # the draft was thrown away
        self.assertTrue(output.endswith(PROMPT + "42\n" + PROMPT + "\n" + GOODBYE))

    def test_ctrl_c_stops_a_runaway_loop_and_the_session_carries_on(self):
        output = self.interrupted(["let base = 40", ["interrupt", "while true { }"],
                                   "base + 2", "let after = 1", "after + base"])
        self.assertEqual(output, PROMPT + "40\n" + PROMPT + STOPPED + PROMPT + "42\n"
                         + PROMPT + "1\n" + PROMPT + "41\n" + PROMPT + "\n" + GOODBYE)

    def test_ctrl_c_inside_nested_calls_leaves_no_stale_state(self):
        output = self.interrupted([
            "let base = 40", "def spin(n) { while true { n = n + 1 } }",
            "def outer() { return spin(0) }", ["interrupt", "outer()"],
            "base + 2", "def boom() { return 1 / 0 }", "boom()", "vars"])
        self.assertIn(PROMPT + STOPPED + PROMPT + "42\n", output)
        # The call stack was unwound: a later error names only its own frame.
        frames = [line for line in output.splitlines() if line.startswith("  in ")]
        self.assertEqual(frames, ["  in boom()"])
        self.assertIn("  base = 40\n", output)
        self.assertTrue(output.endswith(PROMPT + "\n" + GOODBYE))


def novalang_help():
    """The text `help` prints, read from the module the REPL runs."""
    sys.path.insert(0, str(ROOT))
    import novalang
    return novalang.HELP


class VmReplTests(ReplContract, unittest.TestCase):
    flags = ()


class TreeReplTests(ReplContract, unittest.TestCase):
    flags = ("--tree-walk",)
