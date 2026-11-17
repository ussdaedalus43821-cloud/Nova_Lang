"""The nesting limits are counted by the parser, the compiler and the tree-walker, not by the host's recursion limit
(docs/spec/06-portability.md [port.limits], G-051; the artifact loader's own count is V1 of docs/spec/17-bytecode.md).
The conformance corpus (cases/nesting.json) proves the engines agree at the boundaries; these tests prove how it is counted."""

import contextlib
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

ERROR = "the interpreter ran out of stack - recursion too deep"
RESTRICTED = "the restricted profile needs Python 3.8 or later on Windows ([sbx.profiles])"


def parse(source):
    return nl.Parser(nl.Lexer(source).tokenize()).parse()


def accepted(source):
    parse(source)
    return True


def refused(source):
    try:
        parse(source)
    except nl.NovaError as problem:
        return problem.message == ERROR
    return False


def parens(n):
    return "let x = " + "(" * n + "1" + ")" * n + "\n"


KINDS = {
    "parentheses": parens,
    "list brackets": lambda n: "let x = " + "[" * n + "]" * n + "\n",
    "dictionaries": lambda n: "let x = " + '{"a": ' * n + "1" + "}" * n + "\n",
    "blocks": lambda n: "if true {\n" * n + "}\n" * n,
    "argument lists": lambda n: "let x = " + "str(" * n + "1" + ")" * n + "\n",
    "indexes": lambda n: "let a = [0]\nlet x = " + "a[" * n + "0" + "]" * n + "\n",
}


class Boundaries(unittest.TestCase):
    def test_a_level_of_each_kind_of_bracket_counts_and_the_limit_is_exact(self):
        for name, make in KINDS.items():
            with self.subTest(name):
                self.assertTrue(accepted(make(nl.NESTING_LIMIT)), name)
                self.assertTrue(refused(make(nl.NESTING_LIMIT + 1)), name)

    def test_a_hole_of_an_f_string_is_a_level_inside_the_string(self):
        deep = 'let x = f"{' + "(" * (nl.NESTING_LIMIT - 1) + "1" + ")" * (nl.NESTING_LIMIT - 1) + '}"\n'
        self.assertTrue(accepted(deep))
        self.assertTrue(refused(deep.replace("{(", "{((").replace("))}", ")))}")))

    def test_sequential_brackets_are_not_nested(self):
        self.assertTrue(accepted("let x = [" + ",".join(["[]"] * 3000) + "]\n"))
        self.assertTrue(accepted("if true {\n}\n" * 3000))

    def test_chains_are_counted_by_the_depth_of_the_tree(self):
        limit = nl.TREE_DEPTH_LIMIT
        chains = {
            "and": lambda n: "let x = " + " and ".join(["true"] * n) + "\n",
            "sum": lambda n: "let x = " + " + ".join(["1"] * n) + "\n",
            "not": lambda n: "let x = " + "not " * n + "true\n",
            "minus": lambda n: "let x = " + "-" * n + "1\n",
            "else if": lambda n: "let x = 0\nif x == 1 { print(1) }\n" + "else if x == 2 { print(2) }\n" * n,
            "index": lambda n: "let a = [0]\nlet x = a" + "[0]" * n + "\n",
            "field": lambda n: "let a = {a: 0}\nlet x = a" + ".a" * n + "\n",
        }
        for name, make in chains.items():
            with self.subTest(name):
                self.assertTrue(accepted(make(limit - 10)), name)
                self.assertTrue(refused(make(limit + 10)), name)

    def test_the_count_is_the_parsers_own_and_not_the_hosts_recursion_limit(self):
        # With a limit this small nothing could be parsed if it were the host's: the counter alone decides.
        saved = nl.NESTING_LIMIT
        nl.NESTING_LIMIT = 10
        try:
            self.assertTrue(accepted(parens(10)))
            self.assertTrue(refused(parens(11)))
        finally:
            nl.NESTING_LIMIT = saved
        saved_depth = nl.TREE_DEPTH_LIMIT
        nl.TREE_DEPTH_LIMIT = 20
        try:
            self.assertTrue(accepted("let x = " + " + ".join(["1"] * 10) + "\n"))
            self.assertTrue(refused("let x = " + " + ".join(["1"] * 30) + "\n"))
        finally:
            nl.TREE_DEPTH_LIMIT = saved_depth

    def test_a_program_this_deep_is_refused_before_anything_of_it_runs(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(nl.NovaError):
                nl.run('print("ran")\n' + parens(nl.NESTING_LIMIT + 1), nl.Interpreter("vm"))
        self.assertEqual(out.getvalue(), "")


def deep_tree(depth):
    """A syntax tree `depth` levels deep that no parser made: a chain of unary minus, built from the bottom up."""
    node = nl.NumberNode(1)
    for _ in range(depth):
        node = nl.UnaryOpNode("-", node, 0)
    return nl.ProgramNode([node])


class CompilerAndTreeWalker(unittest.TestCase):
    """A tree that did not come from the parser is measured too, before either engine walks it."""

    def test_the_compiler_refuses_a_tree_that_is_too_deep(self):
        with self.assertRaises(nl.NovaError) as caught:
            nl.compile_ast(deep_tree(nl.TREE_DEPTH_LIMIT + 5))
        self.assertEqual(caught.exception.message, ERROR)

    def test_the_tree_walker_refuses_a_tree_that_is_too_deep(self):
        interpreter = nl.Interpreter("tree")
        with self.assertRaises(nl.NovaError) as caught:
            nl.run_program(deep_tree(nl.TREE_DEPTH_LIMIT + 5), interpreter)
        self.assertEqual(caught.exception.message, ERROR)

    def test_a_tree_within_the_limit_is_walked_by_both(self):
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                nl.run_program(deep_tree(200), nl.Interpreter(engine))       # no error (kept shallow: the tree-walker's native stack is small on old Windows)

    def test_the_measure_does_not_recurse(self):
        # A hundred thousand levels deep, measured with a recursion limit far below it.
        tree = deep_tree(100000)
        saved = sys.getrecursionlimit()
        sys.setrecursionlimit(500)
        try:
            with self.assertRaises(nl.NovaError):
                nl.check_tree_depth(tree)
        finally:
            sys.setrecursionlimit(saved)


class Profiles(unittest.TestCase):
    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, RESTRICTED)
    def test_the_restricted_profile_refuses_the_same_programs(self):
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                engine_ = nl.Nova(engine, profile="restricted")
                with self.assertRaises(nl.NovaLangError) as caught:
                    engine_.exec(parens(nl.NESTING_LIMIT + 1))
                self.assertIn(ERROR, str(caught.exception))

    def test_an_embedded_engine_gets_the_error_not_a_host_failure(self):
        for engine in ("vm", "tree"):
            with self.subTest(engine):
                with self.assertRaises(nl.NovaLangError) as caught:
                    nl.Nova(engine).exec("let x = " + " and ".join(["true"] * 20000) + "\n")
                self.assertIn(ERROR, str(caught.exception))

    def test_the_main_thread_runs_the_program_on_cpython(self):
        self.assertNotEqual(sys.implementation.name, "pypy")
        self.assertEqual(nl.main_with_room(["novalang.py", "--no-cache", str(ROOT / "examples" / "hello.nova")])
                         if (ROOT / "examples" / "hello.nova").exists() else 0, 0)


if __name__ == "__main__":
    unittest.main()
