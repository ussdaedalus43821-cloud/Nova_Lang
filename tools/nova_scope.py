"""
nova_scope.py - NovaLang's scope rules, as a reusable AST walk.

nova-lint and nova-typecheck both need to know, at every point in a
program, which binding a name refers to. They must agree with the
interpreter about that, or one of them is wrong. So the rules live here
once, written to match Environment in novalang.py:

  - function calls and the global scope are barriers; blocks are not;
  - reading a name walks every enclosing scope;
  - `x = ...` updates an existing `x` out to the nearest barrier, otherwise
    it creates `x` in the current block - so a name first assigned inside
    an `if` is gone after it;
  - `let` always binds in the current scope;
  - a `for` gets a scope of its own for its loop variables, and its body
    a scope inside that; a `catch` binds its name in the catch block.

Function bodies run when called, not when defined, so ScopeWalker checks
each body only after the whole file, when every enclosing scope holds all
the names it will ever get. It knows nothing about what is being checked:
subclasses override the expression handlers (which may return a value -
the type checker returns a type) and the on_* hooks.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nova_ast import NovaError, Visitor, nl  # noqa: E402

TERMINATORS = (nl.ReturnNode, nl.BreakNode, nl.ContinueNode, nl.ThrowNode)


class Binding:
    """One name bound in one scope. `kind` is var, function, param, loop,
    catch or import. `declared` is free for a subclass to use (the type
    checker stores the declared type there)."""

    __slots__ = ("name", "position", "kind", "used", "exported", "declared")

    def __init__(self, name, position, kind):
        self.name = name
        self.position = position
        self.kind = kind
        self.used = False
        self.exported = False
        self.declared = None


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


class ScopeWalker(Visitor):
    """Walks a program in the interpreter's scope discipline.

    Subclasses hook in through:
        on_read(name, position, binding)      binding is None if unresolved
        on_unreachable(statement, following)  first dead statement of a block
        on_import_error(node, error)          an import that names no module
        condition(expression, node)           an if/while condition
    and may override any visit_* handler. Expression handlers here visit
    their children and return None."""

    def __init__(self):
        self.scope = Scope(barrier=True)
        self.bindings = []
        self.deferred = []          # (FunctionDefNode, defining scope)

    # -- driver -------------------------------------------------------------

    def walk(self, program):
        self.statements(program.statements)
        while self.deferred:
            function, scope = self.deferred.pop(0)
            self.function_body(function, scope)

    # -- hooks --------------------------------------------------------------

    def on_read(self, name, position, binding):
        pass

    def on_unreachable(self, statement, following):
        pass

    def on_import_error(self, node, error):
        pass

    def condition(self, expression, node):
        return self.visit(expression)

    # -- scopes -------------------------------------------------------------

    def bind(self, name, position, kind, scope=None):
        binding = Binding(name, position, kind)
        (scope or self.scope).names[name] = binding
        self.bindings.append(binding)
        return binding

    def assign(self, name, position):
        """The binding `name = ...` updates, creating it here if needed."""
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
        self.on_read(name, position, binding)
        return binding

    def nested(self, block, parent=None, names=()):
        """Walk `block` in a fresh transparent scope, binding `names` first.
        Each entry of `names` is (name, position, kind)."""
        saved = self.scope
        self.scope = Scope(parent or saved)
        try:
            bound = [self.bind(name, position, kind) for name, position, kind in names]
            self.bound_in_block(bound)
            self.statements(block.statements)
        finally:
            self.scope = saved

    def bound_in_block(self, bindings):
        """Called with the bindings `nested` just made (loop variables, a
        caught error's name), before the block runs."""

    def function_body(self, node, scope):
        saved = self.scope
        self.scope = Scope(scope, barrier=True)
        try:
            params = [self.bind(param, node.position, "param") for param in node.params]
            self.enter_function(node, params)
            self.statements(node.body.statements)
            self.leave_function(node)
        finally:
            self.scope = saved

    def enter_function(self, node, params):
        pass

    def leave_function(self, node):
        pass

    # -- statements ---------------------------------------------------------

    def statements(self, statements):
        reported = False
        for index, statement in enumerate(statements):
            self.visit(statement)
            if not reported and index + 1 < len(statements) and terminates(statement):
                self.on_unreachable(statement, statements[index + 1])
                reported = True

    def visit_ProgramNode(self, node):
        self.statements(node.statements)

    def visit_BlockNode(self, node):
        self.nested(node)

    def visit_LetNode(self, node):
        self.visit(node.value)
        return self.bind(node.name, node.position, "var")

    def visit_AssignNode(self, node):
        self.visit(node.value)
        return self.assign(node.name, node.position)

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
        self.condition(node.condition, node)
        self.nested(node.then_block)
        if isinstance(node.else_block, nl.IfNode):
            self.visit(node.else_block)
        elif node.else_block is not None:
            self.nested(node.else_block)

    def visit_WhileNode(self, node):
        self.condition(node.condition, node)
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
        bound = [self.bind(name, node.position, "loop", loop_scope) for name in names]
        self.bound_in_loop(node, bound)
        self.nested(node.body, parent=loop_scope)
        if node.else_block is not None:
            self.nested(node.else_block)

    def bound_in_loop(self, node, bindings):
        """Called with a loop's variable bindings, before its body."""

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
            return [self.bind(name, node.position, "import") for name in node.names]
        try:
            name = node.alias or nl.default_module_name(node.path, node.position)
        except NovaError as error:
            self.on_import_error(node, error)
            return []
        return [self.bind(name, node.position, "import")]

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

    def visit_CompareNode(self, node):
        self.visit(node.left)
        self.visit(node.right)

    def visit_LogicalOpNode(self, node):
        self.visit(node.left)
        self.visit(node.right)

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
