#!/usr/bin/env python3
"""
test_compiler.py - holds the bytecode compiler (M4 phase 1) to account,
before any virtual machine exists to run what it makes.

    python3 tests/compiler/test_compiler.py   (also tests/run_all.py, station 10)

  1. Golden disassembly: each tests/compiler/X.nova compiles to exactly
     X.dis. These cover the hard cases - closures three levels deep,
     late binding, a closure per loop iteration, and every way out of a
     try/catch/finally.
  2. Every .nova file in the repository compiles, passes verify() (jumps,
     slots, constants and stack depth all consistent on every path), and
     compiles to the same bytecode twice.
  3. Every AST node class has a compiler handler.
  4. verify() itself rejects broken bytecode.
  5. The resolver is cross-checked against an independent implementation
     of the same scope rules - tools/nova_scope.py, which the linter and
     type checker use: for every name read in every file, both must
     decide it refers to a binding in the same scope.
"""

import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import novalang as nl  # noqa: E402
from nova_scope import ScopeWalker  # noqa: E402


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def parse(source):
    return nl.Parser(nl.Lexer(source).tokenize()).parse()


def all_programs():
    """(path, source, tree) for every .nova file that parses."""
    for path in sorted(glob.glob(os.path.join(ROOT, "**", "*.nova"), recursive=True)):
        if "/.nova_modules/" in path:
            continue
        source = read(path)
        try:
            tree = parse(source)
        except nl.NovaError:
            continue                    # deliberately broken fixtures
        yield path, source, tree


def test_golden(check):
    for path in sorted(glob.glob(os.path.join(HERE, "*.nova"))):
        source = read(path)
        expected = read(path[:-len(".nova")] + ".dis")
        code = nl.compile_source(source)
        actual = nl.disassemble(code, source) + "\n"
        check(actual == expected, rel(path) + " disassembles to its .dis", diff(expected, actual))


def test_every_file(check):
    count = 0
    for path, source, tree in all_programs():
        try:
            code = nl.compile_ast(tree)
            nl.verify(code)
            again = nl.compile_ast(parse(source))
            same = nl.disassemble(code, source) == nl.disassemble(again, source)
            check(same, rel(path) + " compiles the same way twice")
            count += 1
        except Exception as problem:  # noqa: BLE001
            check(False, rel(path) + " compiles and verifies",
                  "{}: {}".format(type(problem).__name__, problem))
    check(count > 50, "every .nova file in the repository was compiled ({})".format(count))


STRUCTURAL = {"ProgramNode", "BlockNode", "DictEntryNode", "TypeNode", "Node"}


def test_coverage(check):
    nodes = {name for name, value in vars(nl).items()
             if isinstance(value, type) and issubclass(value, nl.Node)}
    handled = {name[2:] for name in dir(nl.Compiler) if name[:2] in ("s_", "e_")}
    missing = sorted(nodes - handled - STRUCTURAL)
    check(not missing, "every AST node has a compiler handler", missing)


def broken(ops, args, nslots=0, constants=(), table=()):
    frame = nl.CFrame("broken", None, None, None)
    frame.slot_names = ["s{}".format(i) for i in range(nslots)]
    code = nl.CodeObject("broken", frame)
    code.ops = [nl.OP[name] for name in ops]
    code.args = list(args)
    code.positions = [None] * len(ops)
    code.constants = list(constants)
    code.nslots = nslots
    code.exception_table = list(table)
    return code


def test_verifier(check):
    cases = {
        "a jump out of the code": broken(["JUMP"], [5]),
        "a stack underflow": broken(["POP", "LOAD_CONST", "RETURN"], [None, 0, None],
                                    constants=[1]),
        "paths meeting at two depths": broken(
            ["LOAD_CONST", "JUMP_IF_NOT_TRUE", "LOAD_CONST", "LOAD_CONST", "RETURN"],
            [0, (1, 3), 0, 0, None], constants=[True, "if"]),
        "falling off the end": broken(["LOAD_CONST"], [0], constants=[1]),
        "a missing slot": broken(["LOAD_FAST", "RETURN"], [3, None], nslots=1),
        "RETURN with extra values": broken(["LOAD_CONST", "LOAD_CONST", "RETURN"],
                                           [0, 0, None], constants=[1]),
    }
    for label, code in cases.items():
        try:
            nl.verify(code)
            refused = False
        except nl.BytecodeError:
            refused = True
        check(refused, "verify() refuses " + label)
    good = broken(["LOAD_CONST", "RETURN"], [0, None], constants=[1])
    check(nl.verify(good), "verify() accepts a minimal module")


# -- the resolver cross-check ----------------------------------------------------

class TaggingWalker(ScopeWalker):
    """nova_scope's walk, noting for every name read which scope - named by
    the AST node that creates it - holds the binding it found."""

    def __init__(self, tree):
        super().__init__()
        self.block_of = {}              # id(statement list) -> ("block"|"root", node)
        self.tags = {id(self.scope): ("root", id(tree))}
        self.home = {}                  # id(Binding) -> id(Scope)
        self.reads = {}                 # id(VarNode) -> scope tag (None: builtin)
        # Scopes are labelled by id(), so none may be freed and have its id
        # reused by a later scope while the walk goes on.
        self.alive = [self.scope]
        self.collect(tree)

    def collect(self, node):
        if isinstance(node, nl.FunctionDefNode):
            self.block_of[id(node.body.statements)] = ("root", id(node))
        elif isinstance(node, nl.BlockNode):
            self.block_of.setdefault(id(node.statements), ("block", id(node)))
        for child in nl.children(node):
            self.collect(child)

    def statements(self, statements):
        tag = self.block_of.get(id(statements))
        if tag is not None and id(self.scope) not in self.tags:
            self.tags[id(self.scope)] = tag
            self.alive.append(self.scope)
        super().statements(statements)

    def bind(self, name, position, kind, scope=None):
        binding = super().bind(name, position, kind, scope)
        self.home[id(binding)] = id(scope or self.scope)
        self.alive.append(scope or self.scope)
        return binding

    def bound_in_loop(self, node, bindings):
        for binding in bindings:
            self.tags[self.home[id(binding)]] = ("loop", id(node))

    def visit_VarNode(self, node):
        binding = self.read(node.name, node.position)
        if node.name in nl.BUILTINS:
            return
        if binding is None:
            self.reads[id(node)] = "global"
        else:
            self.reads[id(node)] = self.tags.get(self.home[id(binding)], "untagged")


def resolver_tags(tree):
    resolution = nl.Resolver().resolve(tree)
    tag_of = {}
    for (kind, node_id), scope in resolution.scopes.items():
        tag_of[id(scope)] = "global" if scope.is_globals else (kind, node_id)
    found = {}
    for node_id, candidates in resolution.reads.items():
        first = candidates[0]
        found[node_id] = "global" if isinstance(first, nl.GlobalVar) else tag_of[id(first.scope)]
    return found


def test_resolver_agrees(check):
    files = reads = 0
    for path, source, tree in all_programs():
        walker = TaggingWalker(tree)
        walker.walk(tree)
        theirs = {key: ("global" if value == ("root", id(tree)) else value)
                  for key, value in walker.reads.items()}
        ours = resolver_tags(tree)
        disagree = [key for key in set(theirs) | set(ours) if theirs.get(key) != ours.get(key)]
        check(not disagree, rel(path) + ": the resolver agrees with nova_scope on every name",
              "{} of {} reads differ".format(len(disagree), len(ours)))
        files += 1
        reads += len(ours)
    check(reads > 1000, "the cross-check covered {} reads in {} files".format(reads, files))


def diff(expected, actual):
    import difflib
    return "".join(difflib.unified_diff(expected.splitlines(True), actual.splitlines(True),
                                        "expected", "actual"))[:3000]


def run(check):
    for test in (test_golden, test_every_file, test_coverage, test_verifier,
                 test_resolver_agrees):
        try:
            test(check)
        except Exception as problem:  # noqa: BLE001
            check(False, "{} raised {}: {}".format(test.__name__, type(problem).__name__, problem))


def main():
    failures = []

    def check(ok, label, detail=None):
        print("[{}] {}".format("ok" if ok else "FAILED", label))
        if not ok:
            failures.append(label)
            if detail:
                print("        " + str(detail)[:2000].replace("\n", "\n        "))
    run(check)
    print()
    print("All compiler tests passed." if not failures else
          "{} compiler test(s) failed.".format(len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
