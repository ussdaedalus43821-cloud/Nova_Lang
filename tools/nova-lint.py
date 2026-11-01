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

The scope model is the interpreter's own (see Environment in novalang.py):
  - function calls and the global scope are barriers; blocks are not;
  - reading a name walks every enclosing scope;
  - `x = ...` updates an existing `x` out to the nearest barrier, otherwise
    it creates `x` in the current block - so a name first assigned inside
    an `if` is gone after it;
  - `let` always binds in the current scope.
Function bodies run when called, not when defined, so a body is checked
only after the whole file, when every enclosing scope holds all the names
it will ever get. That makes the checker lenient (it will not notice a
function called before a global it needs exists) but never wrong about a
name that is defined somewhere it can see.

A program run inside an embedding host may use names the host defines.
Declare them with a comment anywhere in the file:

    # nova-lint: globals score, spawn_enemy
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nova_ast  # noqa: E402
from nova_ast import NovaError, Visitor, nl  # noqa: E402

# Names every program can see without defining them: the reserved
# built-ins plus the globals Interpreter.__init__ predefines.
PREDEFINED = frozenset(nl.BUILTINS) | frozenset(nl.Interpreter().globals.values)

DIRECTIVE = re.compile(r"#\s*nova-lint:\s*globals?\s+(.*)$")

TERMINATORS = (nl.ReturnNode, nl.BreakNode, nl.ContinueNode, nl.ThrowNode)


class Finding:
    def __init__(self, position, code, message):
        self.position = position
        self.code = code
        self.message = message

    @property
    def is_error(self):
        return self.code.startswith("E")


class Binding:
    __slots__ = ("name", "position", "kind", "used", "exported")

    def __init__(self, name, position, kind):
        self.name = name
        self.position = position
        self.kind = kind            # var, function, param, loop, catch, import
        self.used = False
        self.exported = False


class Scope:
    __slots__ = ("names", "parent", "barrier")

    def __init__(self, parent=None, barrier=False):
        self.names = {}
        self.parent = parent
        self.barrier = barrier

    def lookup(self, name):
        scope = self
        while scope is not None:
            if name in scope.names:
                return scope.names[name]
            scope = scope.parent
        return None


def terminates(node):
    """Does control never fall through to the statement after `node`?"""
    if isinstance(node, TERMINATORS):
        return True
    if isinstance(node, nl.BlockNode):
        return any(terminates(statement) for statement in node.statements)
    if isinstance(node, nl.IfNode):
        return (
            node.else_block is not None
            and terminates(node.then_block)
            and terminates(node.else_block)
        )
    if isinstance(node, nl.TryNode):
        if node.finally_block is not None and terminates(node.finally_block):
            return True
        if node.catch_block is None:
            return terminates(node.body)
        return terminates(node.body) and terminates(node.catch_block)
    return False


class Linter(Visitor):
    def __init__(self, parsed):
        self.parsed = parsed
        self.findings = []
        self.bindings = []
        self.deferred = []          # (FunctionDefNode, defining scope)
        self.predefined = set(PREDEFINED)
        for comment in parsed.comments:
            match = DIRECTIVE.search(comment.text)
            if match:
                self.predefined.update(
                    name.strip() for name in match.group(1).split(",") if name.strip()
                )
        self.scope = Scope(barrier=True)

    # -- driver -------------------------------------------------------------

    def run(self):
        self.statements(self.parsed.tree.statements)
        while self.deferred:
            function, scope = self.deferred.pop(0)
            self.function_body(function, scope)
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

    # -- scopes -------------------------------------------------------------

    def bind(self, name, position, kind, scope=None):
        binding = Binding(name, position, kind)
        (scope or self.scope).names[name] = binding
        self.bindings.append(binding)
        return binding

    def assign(self, name, position):
        scope = self.scope
        while scope is not None:
            if name in scope.names:
                return scope.names[name]
            if scope.barrier:
                break
            scope = scope.parent
        return self.bind(name, position, "var")

    def read(self, name, position):
        binding = self.scope.lookup(name)
        if binding is not None:
            binding.used = True
        elif name not in self.predefined:
            self.report(position, "E001", "undefined name {!r}".format(name))

    def nested(self, block, parent=None, names=()):
        """Check `block` in a fresh transparent scope, binding `names` first."""
        saved = self.scope
        self.scope = Scope(parent or saved)
        try:
            for name, position, kind in names:
                self.bind(name, position, kind)
            self.statements(block.statements)
        finally:
            self.scope = saved

    def function_body(self, node, scope):
        saved = self.scope
        self.scope = Scope(scope, barrier=True)
        try:
            for param in node.params:
                self.bind(param, node.position, "param")
            self.statements(node.body.statements)
        finally:
            self.scope = saved

    # -- statements ---------------------------------------------------------

    def statements(self, statements):
        reported = False
        for index, statement in enumerate(statements):
            self.visit(statement)
            if (
                not reported
                and index + 1 < len(statements)
                and terminates(statement)
            ):
                following = statements[index + 1]
                self.report(
                    statement_position(following), "W002",
                    "this code can never run - " + describe_exit(statement),
                )
                reported = True

    def visit_ProgramNode(self, node):
        self.statements(node.statements)

    def visit_BlockNode(self, node):
        self.nested(node)

    def visit_LetNode(self, node):
        self.visit(node.value)
        self.bind(node.name, node.position, "var")

    def visit_AssignNode(self, node):
        self.visit(node.value)
        self.assign(node.name, node.position)

    def visit_IndexAssignNode(self, node):
        self.visit(node.target)
        self.visit(node.index)
        self.visit(node.value)

    def visit_MemberAssignNode(self, node):
        self.visit(node.target)
        self.visit(node.value)

    def visit_FunctionDefNode(self, node):
        binding = self.bind(node.name, node.position, "function")
        self.deferred.append((node, self.scope))
        return binding

    def visit_ExportNode(self, node):
        self.visit(node.inner)
        binding = self.scope.names.get(node.inner.name)
        if binding is not None:
            binding.exported = True

    def visit_ReturnNode(self, node):
        if node.value is not None:
            self.visit(node.value)

    def visit_ThrowNode(self, node):
        self.visit(node.value)

    def visit_BreakNode(self, node):
        pass

    def visit_ContinueNode(self, node):
        pass

    def visit_IfNode(self, node):
        self.visit(node.condition)
        self.nested(node.then_block)
        if isinstance(node.else_block, nl.IfNode):
            self.visit(node.else_block)
        elif node.else_block is not None:
            self.nested(node.else_block)

    def visit_WhileNode(self, node):
        self.visit(node.condition)
        self.nested(node.body)
        if node.else_block is not None:
            self.nested(node.else_block)

    def visit_ForNode(self, node):
        self.visit(node.start)
        self.visit(node.end)
        if node.step is not None:
            self.visit(node.step)
        self.loop(node, [node.name])

    def visit_ForInNode(self, node):
        self.visit(node.iterable)
        names = [node.name] if node.second_name is None else [node.name, node.second_name]
        self.loop(node, names)

    def loop(self, node, names):
        loop_scope = Scope(self.scope)
        for name in names:
            self.bind(name, node.position, "loop", loop_scope)
        self.nested(node.body, parent=loop_scope)
        if node.else_block is not None:
            self.nested(node.else_block)

    def visit_TryNode(self, node):
        self.nested(node.body)
        if node.catch_block is not None:
            names = []
            if node.catch_name is not None:
                names.append((node.catch_name, node.position, "catch"))
            self.nested(node.catch_block, names=names)
        if node.finally_block is not None:
            self.nested(node.finally_block)

    def visit_ImportNode(self, node):
        if node.names is not None:
            for name in node.names:
                self.bind(name, node.position, "import")
            return
        try:
            name = node.alias or nl.default_module_name(node.path, node.position)
        except NovaError as error:
            self.report(node.position, "E002", error.message)
            return
        self.bind(name, node.position, "import")

    def visit_DeleteNode(self, node):
        self.visit(node.target)
        self.visit(node.key)

    def visit_DeleteFileNode(self, node):
        self.visit(node.path)

    # -- expressions --------------------------------------------------------

    def visit_VarNode(self, node):
        self.read(node.name, node.position)

    def visit_NumberNode(self, node):
        pass

    def visit_StringNode(self, node):
        pass

    def visit_BooleanNode(self, node):
        pass

    def visit_UnaryOpNode(self, node):
        self.visit(node.operand)

    def visit_NotNode(self, node):
        self.visit(node.operand)

    def visit_BinOpNode(self, node):
        self.visit(node.left)
        self.visit(node.right)

    visit_CompareNode = visit_BinOpNode
    visit_LogicalOpNode = visit_BinOpNode

    def visit_ListNode(self, node):
        for item in node.items:
            self.visit(item)

    def visit_DictNode(self, node):
        for entry in node.entries:
            self.visit(entry.value)

    def visit_IndexNode(self, node):
        self.visit(node.target)
        self.visit(node.index)

    def visit_SliceNode(self, node):
        self.visit(node.target)
        if node.start is not None:
            self.visit(node.start)
        if node.end is not None:
            self.visit(node.end)

    def visit_MemberNode(self, node):
        self.visit(node.target)

    def visit_InterpolationNode(self, node):
        for part in node.parts:
            self.visit(part)

    def visit_CallNode(self, node):
        self.visit(node.callee)
        for arg in node.args:
            self.visit(arg)


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
