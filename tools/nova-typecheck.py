#!/usr/bin/env python3
"""
nova-typecheck - gradual type checking for NovaLang (poka-yoke for values).

    python3 tools/nova-typecheck.py file.nova [more.nova ...]
    python3 novalang.py --typecheck file.nova

Annotations are optional. Where they are written they are contracts,
checked before the program runs; the interpreter itself ignores them.

    def add(a: int, b: int) -> int { return a + b }
    let name: string = "nova"

Types: int, float, string, bool, list, dict, any.

    - `int` is a whole number and `float` is any number, so an int fits
      wherever a float is expected (NovaLang has one number type at run
      time; `int` is the promise that it is whole, which is what indexes,
      repetition counts and the like insist on).
    - Anything unannotated is `any`: unannotated variables, parameters and
      return types stay fully dynamic, and `any` fits everything.
    - Calls into a typed function are checked even from a file with no
      annotations of its own; nothing else in such a file is.

Codes:
    T001  unknown type name
    T002  argument of the wrong type
    T003  wrong number of arguments
    T004  return value of the wrong type
    T005  function can end without returning its declared type
    T006  value of the wrong type for a declared variable
    T007  operator used on types it does not accept
    T008  other misuse of a known type (condition not a bool, indexing
          something that cannot be indexed, calling a non-function, ...)

Every rule here mirrors what the interpreter does at run time, and
tests/run_all.py cross-checks the operator and built-in rules against the
real interpreter: whatever this accepts must not fail for type reasons
when it runs, and whatever it rejects must fail for some value of those
types.

Exit status: 0 clean, 1 if any type error was found, 2 if a file could
not be read or parsed.
"""

import difflib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nova_ast  # noqa: E402
from nova_ast import NovaError, nl  # noqa: E402
from nova_scope import ScopeWalker, terminates  # noqa: E402


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Type:
    """A NovaLang type. Simple types are singletons, compared by identity."""

    def __init__(self, name, article="a"):
        self.name = name
        self.article = article

    def describe(self):
        """How messages refer to a value of this type: 'an int'."""
        return (self.article + " " + self.name).strip()

    def __repr__(self):
        return self.name


ANY = Type("any", "any value of type")
INT = Type("int", "an")
FLOAT = Type("float")
STRING = Type("string")
BOOL = Type("bool")
LIST = Type("list")
DICT = Type("dict")
NOTHING = Type("nothing", "")        # what print() or a bare `return` gives

ANNOTATIONS = {
    "int": INT, "float": FLOAT, "string": STRING, "bool": BOOL,
    "list": LIST, "dict": DICT, "any": ANY,
}

# Spellings from other languages, so a T001 can say what was meant.
LIKELY_MEANT = {
    "integer": "int", "str": "string", "text": "string", "number": "float",
    "double": "float", "boolean": "bool", "array": "list", "map": "dict",
    "object": "dict", "dynamic": "any",
}


class FunctionType(Type):
    """A function's signature. `params` is a list of types, or None for a
    function that takes any number of arguments of any type; `required`
    is how many of them must be given. `typed` marks a signature written
    in a NovaLang annotation, as opposed to a built-in's."""

    def __init__(self, name, params, ret, required=None, typed=False, names=None):
        super().__init__("function")
        self.function_name = name
        self.names = names          # parameter names, for a NovaLang function
        self.params = params
        self.ret = ret
        self.required = len(params) if required is None and params is not None else required
        self.typed = typed


class ModuleType(Type):
    """An imported module: its exported names and their types."""

    def __init__(self, path, exports):
        super().__init__("module")
        self.path = path
        self.exports = exports


SAME = object()     # a built-in returns the type of its first argument


def fits(actual, expected):
    """Can a value of type `actual` be used where `expected` is declared?"""
    if expected is ANY or actual is ANY:
        return True
    if actual is expected:
        return True
    return actual is INT and expected is FLOAT


def numeric(t):
    return t is INT or t is FLOAT


def arithmetic(left, right):
    """+ - * % on two numbers: whole stays whole, otherwise any number."""
    return INT if left is INT and right is INT else FLOAT


# ---------------------------------------------------------------------------
# Operators - each mirrors Interpreter.visit_BinOpNode / visit_CompareNode
# ---------------------------------------------------------------------------

def binary_result(op, left, right):
    """The type of `left op right`, or None if the interpreter would reject
    it for some values of these types."""
    if left is ANY or right is ANY:
        return ANY
    if op == "+":
        if left is right and left in (STRING, LIST, DICT):
            return left
        if numeric(left) and numeric(right):
            return arithmetic(left, right)
        return None
    if op == "*":
        for seq, count in ((left, right), (right, left)):
            if seq in (STRING, LIST):
                return seq if count is INT else None
        if numeric(left) and numeric(right):
            return arithmetic(left, right)
        return None
    if not (numeric(left) and numeric(right)):
        return None
    if op == "/":
        return FLOAT
    if op == "//":
        return INT          # floor division always gives a whole number
    return arithmetic(left, right)      # - and %


def compare_result(op, left, right):
    """The type of a comparison (always bool), or None if it is rejected."""
    if op in ("==", "!="):
        return BOOL
    if op == "in":
        if right is ANY:
            return BOOL
        if right is STRING or right is DICT:
            return BOOL if fits(left, STRING) else None
        return BOOL if right is LIST else None
    if left is ANY or right is ANY:
        return BOOL
    if (numeric(left) and numeric(right)) or (left is STRING and right is STRING):
        return BOOL
    return None


# ---------------------------------------------------------------------------
# Built-ins. Only pure and read-only ones are typed; every other built-in
# is `any -> any`, so it can never cause a false alarm. Each entry is
# (parameter types, how many are required, return type), and run_all.py
# checks every entry against the real built-in.
# ---------------------------------------------------------------------------

BUILTIN_SIGNATURES = {
    "print": (None, 0, NOTHING),
    "len": ([ANY], 1, INT),
    "upper": ([STRING], 1, STRING),
    "lower": ([STRING], 1, STRING),
    "trim": ([STRING], 1, STRING),
    "split": ([STRING, STRING], 1, LIST),
    "split_lines": ([STRING], 1, LIST),
    "join": ([LIST, STRING], 2, STRING),
    "pad": ([STRING, INT], 2, STRING),
    "pad_left": ([STRING, INT], 2, STRING),
    "replace_all": ([STRING, STRING, STRING], 3, STRING),
    "str": ([ANY], 1, STRING),
    "type": ([ANY], 1, STRING),
    "num": ([ANY], 1, FLOAT),
    "keys": ([DICT], 1, LIST),
    "values": ([DICT], 1, LIST),
    "append": ([LIST, ANY], 2, LIST),
    "choice": ([LIST], 1, ANY),
    "exists": ([STRING], 1, BOOL),
    "abspath": ([STRING], 1, STRING),
    "dirname": ([STRING], 1, STRING),
    "time": ([], 0, FLOAT),
    "random": ([], 0, FLOAT),
    "randint": ([INT, INT], 2, INT),
    "abs": ([FLOAT], 1, SAME),
    "floor": ([FLOAT], 1, INT),
    "ceil": ([FLOAT], 1, INT),
    "sqrt": ([FLOAT], 1, FLOAT),
    "pow": ([FLOAT, FLOAT], 2, FLOAT),
    "sin": ([FLOAT], 1, FLOAT),
    "cos": ([FLOAT], 1, FLOAT),
    "tan": ([FLOAT], 1, FLOAT),
    "ln": ([FLOAT], 1, FLOAT),
    "log10": ([FLOAT], 1, FLOAT),
}

UNTYPED_BUILTIN = FunctionType("", None, ANY, 0)

# Globals the interpreter predefines (see Interpreter.__init__).
PREDEFINED_TYPES = {"PI": FLOAT, "E": FLOAT, "json": DICT, "python": DICT}


def builtin_type(name):
    signature = BUILTIN_SIGNATURES.get(name)
    if signature is None:
        return UNTYPED_BUILTIN
    params, required, ret = signature
    return FunctionType(name, params, ret, required)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

class Finding:
    """`end` is where the problem stops (exclusive), or None when only its
    start is known; the command line shows only the start."""

    def __init__(self, position, code, message, contract=False, end=None):
        self.position = position
        self.code = code
        self.message = message
        self.contract = contract    # a typed function's signature was broken
        self.end = end


def position_of(node):
    start = getattr(node, "_start", None)
    return start if start is not None else getattr(node, "position", None)


def end_of(node):
    """Where a node's source text stops, when that is known."""
    end = getattr(node, "_end", None)
    if end is not None:
        return end
    if isinstance(node, (nl.VarNode, nl.TypeNode)):
        return node.position + len(node.name)
    if isinstance(node, nl.MemberNode):
        return node.position + 1 + len(node.name)       # the '.' and the field
    return None


def callee_name(node):
    if isinstance(node, nl.VarNode):
        return node.name + "()"
    if isinstance(node, nl.MemberNode):
        inner = callee_name(node.target)
        return (inner[:-2] if inner.endswith("()") else "this") + "." + node.name + "()"
    return "this function"


# ---------------------------------------------------------------------------
# The checker
# ---------------------------------------------------------------------------

class Checker(ScopeWalker):
    """Statements keep ScopeWalker's scope rules; every expression handler
    returns the expression's Type."""

    def __init__(self, parsed, program, path, base_dir, contracts_only):
        super().__init__()
        self.parsed = parsed
        self.program = program
        self.path = path
        self.base_dir = os.path.dirname(path) if path else base_dir
        self.contracts_only = contracts_only
        self.findings = []
        self.returns = None         # the function whose body is being checked

    def run(self):
        self.walk(self.parsed.tree)
        exports = {}
        for name, binding in self.scope.names.items():
            if binding.exported:
                exports[name] = binding.declared or ANY
        self.findings.sort(key=lambda finding: (finding.position or 0, finding.code))
        return exports

    def report(self, node_or_position, code, message, contract=False, end=None):
        if self.contracts_only and not contract:
            return
        position = node_or_position
        if not isinstance(position, int) and position is not None:
            position = position_of(node_or_position)
            if end is None:
                end = end_of(node_or_position)
        self.findings.append(Finding(position, code, message, contract, end))

    def resolve(self, type_node):
        """The Type an annotation names; ANY (after a T001) if none."""
        if type_node is None:
            return None
        found = ANNOTATIONS.get(type_node.name)
        if found is not None:
            return found
        known = dict(LIKELY_MEANT, **{name: name for name in ANNOTATIONS})
        guess = known.get(type_node.name.lower())
        if guess is None:
            close = difflib.get_close_matches(type_node.name.lower(), list(known), n=1)
            guess = known[close[0]] if close else None
        hint = " - did you mean '{}'?".format(guess) if guess else (
            " - the types are " + ", ".join(ANNOTATIONS)
        )
        self.report(type_node, "T001",
                    "unknown type '{}'{}".format(type_node.name, hint))
        return ANY

    # -- statements ---------------------------------------------------------

    def condition(self, expression, node):
        kind = self.visit(expression)
        if not fits(kind, BOOL):
            keyword = "a 'while'" if isinstance(node, nl.WhileNode) else "an 'if'"
            self.report(expression, "T008",
                        "{} condition must be a bool, but this is {}".format(
                            keyword, kind.describe()))

    def declared_check(self, binding, kind, node, verb):
        if binding is None or binding.declared is None or fits(kind, binding.declared):
            return
        if isinstance(binding.declared, (FunctionType, ModuleType)):
            self.report(node, "T006", "{!r} is {}, so it cannot be given {}".format(
                binding.name, binding.declared.describe(), kind.describe()))
        else:
            self.report(node, "T006", "{!r} is declared {}, but {} {}".format(
                binding.name, binding.declared.name, verb, kind.describe()))

    def visit_LetNode(self, node):
        kind = self.visit(node.value)
        declared = self.resolve(node.type_name)
        binding = self.bind(node.name, node.position, "var")
        binding.declared = declared
        self.declared_check(binding, kind, node.value, "its value is")
        return kind

    def visit_AssignNode(self, node):
        kind = self.visit(node.value)
        binding = self.assign(node.name, node.position)
        self.declared_check(binding, kind, node.value, "this assigns")
        return kind

    def visit_IndexAssignNode(self, node):
        target = self.visit(node.target)
        index = self.visit(node.index)
        kind = self.visit(node.value)
        if target is STRING:
            self.report(node.target, "T008",
                        "strings cannot be changed in place - build a new one instead")
        elif target is LIST:
            self.index_check(index, node.index, "a list index")
        elif target is DICT or isinstance(target, ModuleType):
            self.key_check(index, node.index)
        elif target is not ANY:
            self.report(node.target, "T008", "{} cannot be indexed".format(target.describe()))
        return kind

    def visit_MemberAssignNode(self, node):
        target = self.visit(node.target)
        kind = self.visit(node.value)
        if not (target is ANY or target is DICT or isinstance(target, ModuleType)):
            self.report(node.target, "T008",
                        "only a dictionary can have fields set, but this is {}".format(
                            target.describe()))
        return kind

    def signature(self, node):
        params = [self.resolve(kind) or ANY for kind in node.param_types]
        ret = self.resolve(node.return_type) or ANY
        typed = node.return_type is not None or any(k is not None for k in node.param_types)
        return FunctionType(node.name, params, ret, typed=typed, names=list(node.params))

    def visit_FunctionDefNode(self, node):
        binding = super().visit_FunctionDefNode(node)
        binding.declared = self.signature(node)
        node._signature = binding.declared
        return binding

    def enter_function(self, node, params):
        signature = node._signature
        for binding, kind in zip(params, signature.params):
            binding.declared = kind if kind is not ANY else None
        self.returns = signature

    def leave_function(self, node):
        signature = self.returns
        self.returns = None
        if signature.ret is not ANY and not terminates(node.body):
            span = self.parsed.name_after(node.position, node.name)
            self.report(node.position, "T005",
                        "{}() is declared to return {}, but can reach its end without "
                        "returning anything".format(node.name, signature.ret.describe()),
                        end=span[1] if span else None)

    def visit_ReturnNode(self, node):
        kind = NOTHING if node.value is None else self.visit(node.value)
        signature = self.returns
        if signature is None or signature.ret is ANY:
            return
        if not fits(kind, signature.ret):
            message = "{}() must return {}, but this returns {}".format(
                signature.function_name, signature.ret.describe(),
                "nothing" if kind is NOTHING else kind.describe())
            if node.value is not None:
                self.report(node.value, "T004", message)
            else:
                self.report(node.position, "T004", message, end=node.position + len("return"))

    def visit_ThrowNode(self, node):
        kind = self.visit(node.value)
        if not fits(kind, STRING):
            self.report(node.value, "T008",
                        "throw needs a string, but this is {}".format(kind.describe()))

    def visit_ForNode(self, node):
        for part, role in ((node.start, "start"), (node.end, "end"), (node.step, "step")):
            if part is None:
                continue
            kind = self.visit(part)
            if not fits(kind, FLOAT):
                self.report(part, "T008", "the {} of a 'for' range must be a number, but "
                            "this is {}".format(role, kind.describe()))
        self.loop(node, [node.name])

    def visit_ForInNode(self, node):
        kind = self.visit(node.iterable)
        if not (kind is ANY or kind in (LIST, STRING, DICT)):
            self.report(node.iterable, "T008", "'for ... in' needs a list, a string or a "
                        "dictionary, but this is {}".format(kind.describe()))
        names = [node.name] if node.second_name is None else [node.name, node.second_name]
        self.loop(node, names)

    def visit_ImportNode(self, node):
        bindings = super().visit_ImportNode(node)
        module = self.program.module(node.path, self.base_dir)
        if module is None:
            return bindings
        if node.names is not None:
            for binding in bindings:
                kind = module.exports.get(binding.name)
                binding.declared = kind if kind is not ANY else None
        else:
            for binding in bindings:
                binding.declared = ModuleType(module.path, module.exports)
        return bindings

    def visit_DeleteNode(self, node):
        target = self.visit(node.target)
        key = self.visit(node.key)
        if not (target is ANY or target is DICT or isinstance(target, ModuleType)):
            self.report(node.target, "T008", "delete works on dictionary entries, but this "
                        "is {}".format(target.describe()))
        self.key_check(key, node.key)

    def visit_DeleteFileNode(self, node):
        kind = self.visit(node.path)
        if not fits(kind, STRING):
            self.report(node.path, "T008",
                        "delete() needs a file name string, but this is {}".format(kind.describe()))

    # -- expressions --------------------------------------------------------

    def visit_VarNode(self, node):
        binding = self.read(node.name, node.position)
        if binding is not None:
            return binding.declared or ANY
        if node.name in nl.BUILTINS:
            return builtin_type(node.name)
        return PREDEFINED_TYPES.get(node.name, ANY)

    def visit_NumberNode(self, node):
        return INT if isinstance(node.value, int) else FLOAT

    def visit_StringNode(self, node):
        return STRING

    def visit_BooleanNode(self, node):
        return BOOL

    def visit_InterpolationNode(self, node):
        for part in node.parts:
            self.visit(part)
        return STRING

    def visit_ListNode(self, node):
        for item in node.items:
            self.visit(item)
        return LIST

    def visit_DictNode(self, node):
        for entry in node.entries:
            self.visit(entry.value)
        return DICT

    def visit_UnaryOpNode(self, node):
        kind = self.visit(node.operand)
        if kind is ANY or numeric(kind):
            return kind
        self.report(node.operand, "T007", "cannot apply unary '{}' to {}".format(
            node.op, kind.describe()))
        return ANY

    def visit_NotNode(self, node):
        kind = self.visit(node.operand)
        if not fits(kind, BOOL):
            self.report(node.operand, "T007",
                        "'not' needs a bool, but this is {}".format(kind.describe()))
        return BOOL

    def visit_LogicalOpNode(self, node):
        for side, operand in (("left", node.left), ("right", node.right)):
            kind = self.visit(operand)
            if not fits(kind, BOOL):
                self.report(operand, "T007", "the {} side of '{}' must be a bool, but this "
                            "is {}".format(side, node.op, kind.describe()))
        return BOOL

    def visit_BinOpNode(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        result = binary_result(node.op, left, right)
        if result is None:
            self.report(node.left, "T007", "cannot use '{}' on {} and {}".format(
                node.op, left.describe(), right.describe()),
                end=end_of(node) or end_of(node.right))
            return ANY
        return result

    def visit_CompareNode(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        if compare_result(node.op, left, right) is None:
            self.report(node.left, "T007", "cannot use '{}' on {} and {}".format(
                node.op, left.describe(), right.describe()),
                end=end_of(node) or end_of(node.right))
        return BOOL

    def index_check(self, kind, node, role):
        if not fits(kind, INT):
            self.report(node, "T008", "{} must be an int, but this is {}".format(
                role, kind.describe()))

    def key_check(self, kind, node):
        if not fits(kind, STRING):
            self.report(node, "T008", "a dictionary key must be a string, but this is "
                        "{}".format(kind.describe()))

    def visit_IndexNode(self, node):
        target = self.visit(node.target)
        index = self.visit(node.index)
        if target is LIST:
            self.index_check(index, node.index, "a list index")
            return ANY
        if target is STRING:
            self.index_check(index, node.index, "a string index")
            return STRING
        if target is DICT or isinstance(target, ModuleType):
            self.key_check(index, node.index)
            return ANY
        if target is not ANY:
            self.report(node.target, "T008", "{} cannot be indexed".format(target.describe()))
        return ANY

    def visit_SliceNode(self, node):
        target = self.visit(node.target)
        for bound in (node.start, node.end):
            if bound is not None:
                self.index_check(self.visit(bound), bound, "a slice bound")
        if target in (LIST, STRING):
            return target
        if target is not ANY:
            self.report(node.target, "T008", "{} cannot be sliced".format(target.describe()))
        return ANY

    def visit_MemberNode(self, node):
        target = self.visit(node.target)
        if isinstance(target, ModuleType):
            if node.name in target.exports:
                return target.exports[node.name]
            self.report(node.target, "T008", "module \"{}\" has no exported {!r}".format(
                os.path.basename(target.path), node.name))
            return ANY
        if target is DICT or target is ANY:
            return ANY
        self.report(node.target, "T008", "{} has no fields, so '.{}' means nothing "
                    "here".format(target.describe(), node.name))
        return ANY

    def visit_CallNode(self, node):
        callee = self.visit(node.callee)
        args = [self.visit(arg) for arg in node.args]
        if callee is ANY:
            return ANY
        if not isinstance(callee, FunctionType):
            self.report(node.callee, "T008", "{} is not a function, so it cannot be "
                        "called".format(callee.describe()))
            return ANY
        name = callee_name(node.callee)
        contract = callee.typed
        if callee.params is not None:
            if not callee.required <= len(args) <= len(callee.params):
                wanted = (str(len(callee.params)) if callee.required == len(callee.params)
                          else "{} to {}".format(callee.required, len(callee.params)))
                self.report(node.callee, "T003", "{} takes {} argument{} but is given {}".format(
                    name, wanted, "" if wanted == "1" else "s", len(args)), contract)
            for index, (arg, actual, expected) in enumerate(zip(node.args, args, callee.params)):
                if not fits(actual, expected):
                    self.report(arg, "T002", "argument {} of {} must be {}, but this is "
                                "{}".format(index + 1, name, expected.describe(),
                                            actual.describe()), contract)
        if callee.ret is SAME:
            if args and (numeric(args[0]) or args[0] is ANY):
                return args[0]
            return FLOAT
        return callee.ret


# ---------------------------------------------------------------------------
# Programs: a file and everything it imports
# ---------------------------------------------------------------------------

class Module:
    def __init__(self, path, exports, findings, source):
        self.path = path
        self.exports = exports
        self.findings = findings
        self.source = source


class Program:
    """Checks files on demand, each once, following imports the way the
    interpreter resolves them (relative to the importing file, then the
    current directory). A module that is missing, does not parse, or is
    part of an import cycle simply has no known exports here; the
    interpreter reports those problems itself when it runs. A package name
    is resolved by novalang.resolve_package, exactly as at run time."""

    def __init__(self):
        self.modules = {}           # absolute path -> Module (None while loading)

    def resolve(self, raw_path, base_dir):
        if nl.is_package_import(raw_path):
            # The interpreter's own resolver, so the two cannot disagree.
            try:
                return nl.resolve_package(raw_path, base_dir, None)
            except NovaError:
                return None
        candidates = []
        if base_dir is not None:
            candidates.append(os.path.normpath(os.path.join(base_dir, raw_path)))
        candidates.append(os.path.normpath(os.path.join(os.getcwd(), raw_path)))
        for candidate in candidates:
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
        return None

    def module(self, raw_path, base_dir):
        resolved = self.resolve(raw_path, base_dir)
        if resolved is None:
            return None
        if resolved not in self.modules:
            self.modules[resolved] = None
            try:
                with open(resolved, "r", encoding="utf-8") as handle:
                    source = handle.read()
                self.modules[resolved] = self.check(source, resolved)
            except (OSError, NovaError):
                self.modules.pop(resolved, None)
                return None
        return self.modules[resolved]

    def check(self, source, path, base_dir=None, checker_class=None, parsed=None):
        """Check one file. `path` is None for source that is not a file
        (a one-liner, the REPL); imports then resolve against base_dir.
        `checker_class` (a Checker subclass) is used for this file only -
        the editor support uses one that records every name it resolves -
        and `parsed` saves parsing `source` again when the caller has."""
        parsed = parsed or nova_ast.parse(source)
        contracts_only = not parsed.tree.annotated
        checker = (checker_class or Checker)(parsed, self, path, base_dir or os.getcwd(),
                                             contracts_only)
        exports = checker.run()
        module = Module(path, exports, checker.findings, source)
        module.parsed = parsed
        module.scope = checker.scope        # its top-level bindings, for editors
        module.checker = checker
        return module


def check_source(source, path=None, base_dir=None):
    """Type-check `source` and the modules it imports. Returns the
    Program (whose .modules hold the imports) and the source's own Module.
    Raises NovaError if `source` does not parse."""
    program = Program()
    module = program.check(source, os.path.abspath(path) if path else None, base_dir)
    return program, module


def all_modules(program, module):
    """The checked file first, then every module it reached."""
    yield module
    for path in sorted(program.modules):
        if program.modules[path] is not None and program.modules[path] is not module:
            yield program.modules[path]


def format_finding(display_path, module, finding):
    lines = module.parsed.lines
    if finding.position is None:
        where = display_path
    else:
        where = "{}:{}:{}".format(display_path, lines.line(finding.position),
                                  lines.column(finding.position))
    return "{}: {} {}".format(where, finding.code, finding.message)


def line_of(module, finding):
    if finding.position is None:
        return "?"
    return str(module.parsed.lines.line(finding.position))


class GateCache:
    """The type gate's results for one interpreter's lifetime, one per
    absolute module path, so an import graph is checked once per load
    instead of once per importer (OmniCalc: 159 checks for 37 loads).

    A result is reused only for the exact source it was checked from. Any
    other source for a cached path, or a failed module load (the one time
    the interpreter reads a file again), discards everything: a module
    checked against an import's old version must be checked again too."""

    def __init__(self):
        self.program = Program()

    def clear(self):
        self.program = Program()

    def module(self, source, path, base_dir):
        if path is not None:
            cached = self.program.modules.get(path)
            if cached is not None:
                if cached.source == source:
                    return cached
                self.clear()
        module = self.program.check(source, path, base_dir)
        if path is not None:
            self.program.modules[path] = module
        return module


def gate_refusal(source, base_dir=None, cache=None, path=None):
    """For novalang.py: (message, position) saying why `source` must not
    run, or None. Plain data rather than a NovaError, because novalang.py
    may be running as __main__, whose NovaError is a different class from
    the one this module imported. Only the source's own findings count
    here - each imported module answers for itself when it is loaded.
    `cache` (a GateCache) and `path` (the module's absolute path, None for
    a program that is not a module) let a load reuse earlier checks."""
    if cache is None:
        _, module = check_source(source, path, base_dir)
    else:
        module = cache.module(source, path, base_dir)
    if not module.findings:
        return None
    first = module.findings[0]
    message = "{} {}".format(first.code, first.message)
    others = module.findings[1:]
    if others:
        message += "".join(
            "\n  also line {}: {} {}".format(line_of(module, finding), finding.code, finding.message)
            for finding in others
        )
    return message, first.position


def check_file_graph(path):
    """For --bootstrap and the CLI: every finding in `path` and in every
    module it imports, as printable lines (the self-hosted interpreter
    loads imports itself, so they must all be checked up front)."""
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    program, module = check_source(source, path)
    lines = []
    for each in all_modules(program, module):
        shown = path if each is module else display_path(each.path)
        lines.extend(format_finding(shown, each, finding) for finding in each.findings)
    return lines


def display_path(path):
    """A module's path relative to the current directory when it is inside
    it, absolute otherwise."""
    relative = os.path.relpath(path)
    return path if relative.startswith("..") else relative


USAGE = "usage: {} file.nova [more.nova ...]"


def main(argv):
    args = argv[1:]
    if not args or any(arg.startswith("-") for arg in args):
        print(USAGE.format(argv[0]), file=sys.stderr)
        return 2
    status = 0
    for path in args:
        try:
            lines = check_file_graph(path)
        except OSError as problem:
            print("nova-typecheck: cannot read {}: {}".format(path, problem), file=sys.stderr)
            status = 2
            continue
        except NovaError as error:
            print(path, file=sys.stderr)
            with open(path, "r", encoding="utf-8") as handle:
                print(error.render(handle.read()), file=sys.stderr)
            status = 2
            continue
        for line in lines:
            print(line)
        if lines:
            status = max(status, 1)
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
