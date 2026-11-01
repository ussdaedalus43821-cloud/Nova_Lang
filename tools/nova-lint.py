#!/usr/bin/env python3
"""
nova-lint - static checks for NovaLang (poka-yoke: catch it before it runs).

    python3 tools/nova-lint.py file.nova [more.nova ...]

Reads the program with the real Lexer and Parser but never executes it.

    E001  undefined name       a name is read that nothing defines
    W001  unused variable      a variable is assigned but never read
    W002  unreachable code     a statement after return/break/continue/throw

Exit status: 0 clean (warnings allowed), 1 if any error was found, 2 if a
file could not be read or parsed. `--strict` makes warnings fail too.

The scope model is the interpreter's own, and lives in nova_scope.py so the
type checker shares it. Function bodies are checked after the whole file,
when every enclosing scope holds all the names it will ever get. That makes
the checker lenient (it will not notice a function called before a global
it needs exists) but never wrong about a name defined somewhere it can see.

A program run inside an embedding host may use names the host defines.
Declare them with a comment anywhere in the file:

    # nova-lint: globals score, spawn_enemy
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nova_ast  # noqa: E402
from nova_ast import NovaError, nl  # noqa: E402
from nova_scope import TERMINATORS, ScopeWalker  # noqa: E402

# Names every program can see without defining them: the reserved
# built-ins plus the globals Interpreter.__init__ predefines.
PREDEFINED = frozenset(nl.BUILTINS) | frozenset(nl.Interpreter().globals.values)

DIRECTIVE = re.compile(r"#\s*nova-lint:\s*globals?\s+(.*)$")

class Finding:
    def __init__(self, position, code, message):
        self.position = position
        self.code = code
        self.message = message

    @property
    def is_error(self):
        return self.code.startswith("E")


class Linter(ScopeWalker):
    """The scope rules come from ScopeWalker; this adds what to report."""

    def __init__(self, parsed):
        super().__init__()
        self.parsed = parsed
        self.findings = []
        self.predefined = set(PREDEFINED)
        for comment in parsed.comments:
            match = DIRECTIVE.search(comment.text)
            if match:
                self.predefined.update(
                    name.strip() for name in match.group(1).split(",") if name.strip()
                )

    def run(self):
        self.walk(self.parsed.tree)
        for binding in self.bindings:
            if (
                binding.kind == "var"
                and not binding.used
                and not binding.exported
                and not binding.name.startswith("_")
            ):
                self.report(
                    binding.position, "W001",
                    "{!r} is assigned but never used".format(binding.name),
                )
        self.findings.sort(key=lambda finding: (finding.position or 0, finding.code))
        return self.findings

    def report(self, position, code, message):
        self.findings.append(Finding(position, code, message))

    def on_read(self, name, position, binding):
        if binding is None and name not in self.predefined:
            self.report(position, "E001", "undefined name {!r}".format(name))

    def on_unreachable(self, statement, following):
        self.report(
            statement_position(following), "W002",
            "this code can never run - " + describe_exit(statement),
        )

    def on_import_error(self, node, error):
        self.report(node.position, "E002", error.message)


def statement_position(node):
    start = getattr(node, "_start", None)
    return start if start is not None else getattr(node, "position", None)


def describe_exit(node):
    if isinstance(node, TERMINATORS):
        keyword = type(node).__name__[:-len("Node")].lower()
        return "the '{}' before it always leaves the block".format(keyword)
    if isinstance(node, nl.IfNode):
        return "every branch of the 'if' before it leaves the block"
    return "the 'try' before it always leaves the block"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lint_source(source):
    """Return the findings for `source`; raises NovaError if it does not parse."""
    parsed = nova_ast.parse(source)
    return Linter(parsed).run(), parsed


def format_finding(path, parsed, finding):
    if finding.position is None:
        where = path
    else:
        where = "{}:{}:{}".format(
            path, parsed.lines.line(finding.position), parsed.lines.column(finding.position)
        )
    return "{}: {} {}".format(where, finding.code, finding.message)


USAGE = "usage: {} [--strict] file.nova [more.nova ...]"


def main(argv):
    args = argv[1:]
    strict = False
    if args and args[0] == "--strict":
        strict, args = True, args[1:]
    if not args or any(arg.startswith("-") for arg in args):
        print(USAGE.format(argv[0]), file=sys.stderr)
        return 2

    status = 0
    for path in args:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError as problem:
            print("nova-lint: cannot read {}: {}".format(path, problem), file=sys.stderr)
            status = 2
            continue
        try:
            findings, parsed = lint_source(source)
        except NovaError as error:
            print(path, file=sys.stderr)
            print(error.render(source), file=sys.stderr)
            status = 2
            continue
        for finding in findings:
            print(format_finding(path, parsed, finding))
            if finding.is_error or strict:
                status = max(status, 1)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
