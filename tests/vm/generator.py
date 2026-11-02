"""
generator.py - seeded random NovaLang programs for differential testing.

    program = generate(seed)

Every program parses, terminates and is deterministic, and is built to hit
what the bytecode compiler and VM find hardest:

  - scopes: a small pool of names (a, b, x, total, ...) reused everywhere,
    so `let` shadows, assignments sometimes update an outer binding and
    sometimes create a block-local that then vanishes, and module-level
    blocks assign names that may or may not be globals;
  - closures: functions defined inside functions, blocks and loops, reading
    names bound before or after them, returned and called later, and made
    once per loop iteration;
  - control flow: if/else-if chains, while/for/for-in loops with
    break/continue and else blocks, try/catch/finally nested with return,
    break, continue and throw in any part, stray break/continue in a
    function (an error the caller can catch), and a top-level return;
  - errors: undefined names, bad operands, out-of-range indexes, missing
    keys, non-boolean conditions, bad call arity, and deep recursion.

Termination is by construction: every loop runs off a counter only the loop
touches, and a function only calls functions defined before it (plus one
bounded recursive one). Output is printed as the program goes, so the two
engines are compared on everything a program does, not just how it ends.
"""

import random

NAMES = ["a", "b", "c", "x", "y", "total", "item"]
CHUNK_MARK = "# --- chunk ---"         # see differential.outcome
# Reads favour the names a program defines up front; `item` starts undefined
# and is only ever block-local or a loop variable, so reading it after its
# block is a genuine (and deliberately occasional) scope error.
READ_NAMES = NAMES[:6] * 4 + ["item"]
STRINGS = ['"one"', '"two"', '"x"', '""', '"hello world"']


class Generator:
    def __init__(self, seed):
        self.random = random.Random(seed)
        self.functions = []             # names callable at this point, with arity
        self.counter = 0
        self.lines = []

    # -- helpers ---------------------------------------------------------------

    def chance(self, p):
        return self.random.random() < p

    def pick(self, items):
        return self.random.choice(items)

    def fresh(self, prefix):
        self.counter += 1
        return "{}{}".format(prefix, self.counter)

    def emit(self, depth, text):
        self.lines.append("    " * depth + text)

    # -- expressions ----------------------------------------------------------
    #
    # Mostly well-typed, so programs run long enough to exercise the code
    # after them; the errors come from `error_statement`, on purpose, and
    # from names that legitimately no longer exist (a block-local read
    # after its block), which is exactly what scope tests are for.

    def number(self, depth=0):
        """An expression that is usually a number."""
        if depth > 2 or self.chance(0.35):
            roll = self.random.random()
            if roll < 0.5:
                return self.pick(READ_NAMES)
            if roll < 0.9:
                return str(self.random.randint(-3, 9))
            if roll < 0.95 and self.functions:
                return self.call()
            return "len([{}])".format(", ".join("1" for _ in range(self.random.randint(0, 3))))
        roll = self.random.random()
        left = self.number(depth + 1)
        if roll < 0.55:
            return "({} {} {})".format(left, self.pick(["+", "-", "*"]), self.number(depth + 1))
        if roll < 0.7:
            return "({} {} {})".format(left, self.pick(["//", "%", "/"]), self.random.randint(1, 4))
        if roll < 0.8:
            return "{}{}".format(self.pick(["-", "+"]), left)
        if roll < 0.86 and self.functions:
            return self.call()
        if roll < 0.95:
            return self.indexing()
        return "len({})".format(self.pick(['"abc"', "[1, 2]", '""', "{k: 1}"]))

    # Every kind of index, on every kind of target: in range, negative, too
    # big, whole and fractional floats, booleans, and string keys present
    # and missing - the cases a fast path for indexing could get wrong.
    INDEXES = ["0", "1", "2", "-1", "-3", "3", "5", "1.0", "1.5", "true", '"k"', '"n"', '"missing"']

    def indexing(self):
        target = self.pick(["[10, 20, 30]", '"abc"', "{k: 1, n: 2}", "[]", "{}"])
        return "({})[{}]".format(target, self.pick(self.INDEXES))

    def value(self, depth=0):
        """Any kind of value."""
        roll = self.random.random()
        if roll < 0.55:
            return self.number(depth)
        if roll < 0.65:
            return self.pick(STRINGS)
        if roll < 0.75:
            return "[{}]".format(", ".join(self.number(2) for _ in range(self.random.randint(0, 3))))
        if roll < 0.82:
            return "{{k: {}, n: 2}}".format(self.number(2))
        if roll < 0.9:
            # Holes are parenthesised: a dict literal would otherwise open
            # with `{{`, which is a literal brace in an f-string.
            return 'f"{{({})}}-{{({})}}"'.format(self.number(2), self.value(3))
        return self.condition(depth)

    def expression(self, depth=0):
        return self.value(depth)

    def assigned(self):
        """What a name is set to: mostly a number, so arithmetic keeps working."""
        return self.number() if self.chance(0.85) else self.value()

    def call(self):
        name, arity = self.pick(self.functions)
        return "{}({})".format(name, ", ".join(self.number(2) for _ in range(arity)))

    def condition(self, depth=0):
        roll = self.random.random()
        if roll < 0.55 or depth > 2:
            return "{} {} {}".format(self.number(2), self.pick(["<", ">", "==", "!=", "<=", ">="]),
                                     self.random.randint(0, 5))
        if roll < 0.7:
            return self.pick(["true", "false"])
        if roll < 0.85:
            return "({} {} {})".format(self.condition(depth + 1), self.pick(["and", "or"]),
                                       self.condition(depth + 1))
        if roll < 0.92:
            return "(not {})".format(self.condition(depth + 1))
        return "{} in [{}, {}]".format(self.number(2), self.random.randint(0, 3),
                                       self.random.randint(0, 3))

    ERRORS = [
        "print(nowhere_{n})",                       # an undefined name
        'print("text" - {n})',                      # bad operands
        "print([1, 2][{n} + 5])",                   # an index out of range
        "print({{k: 1}}.missing)",                  # a missing key
        "if {n} {{ print(1) }}",                    # a condition that is not a bool
        "print(not {n})",                           # `not` on a number
        "print(deep())",                            # the wrong number of arguments
        "print(5({n}))",                            # calling a number
        'throw("deliberate {n}")',
        "let z_{n} = {{k: 1}}\nz_{n}[{n}] = 2",       # a key that is not a string
    ]

    def error_statement(self, depth):
        for line in self.pick(self.ERRORS).format(n=self.random.randint(0, 9)).split("\n"):
            self.emit(depth, line)

    # -- statements -------------------------------------------------------------

    def block(self, depth, context, count=None):
        count = count if count is not None else self.random.randint(1, 4)
        visible = list(self.functions)      # a function defined in here ends with it
        for _ in range(count):
            self.statement(depth, context)
        self.functions = visible

    def statement(self, depth, context):
        """context: in_function, in_loop, top (dict of flags)."""
        roll = self.random.random()
        deep = depth > 4
        if roll < 0.14 or deep and roll < 0.5:
            self.emit(depth, "{} = {}".format(self.pick(NAMES), self.assigned()))
        elif roll < 0.24 or deep:
            self.emit(depth, "let {} = {}".format(self.pick(NAMES), self.assigned()))
        elif roll < 0.33:
            self.emit(depth, "print({})".format(", ".join(
                self.expression() for _ in range(self.random.randint(1, 3)))))
        elif roll < 0.36:
            self.store_through(depth)
        elif roll < 0.46:
            self.emit(depth, "if {} {{".format(self.condition()))
            self.block(depth + 1, context)
            while self.chance(0.3):
                self.emit(depth, "}} else if {} {{".format(self.condition()))
                self.block(depth + 1, context)
            if self.chance(0.5):
                self.emit(depth, "} else {")
                self.block(depth + 1, context)
            self.emit(depth, "}")
        elif roll < 0.56:
            self.loop(depth, context)
        elif roll < 0.68:
            self.function(depth, context)
        elif roll < 0.78:
            self.try_statement(depth, context)
        elif roll < 0.84 and context.get("in_function"):
            self.emit(depth, "return {}".format(self.expression()))
        elif roll < 0.89 and context.get("in_loop"):
            self.emit(depth, "if {} {{".format(self.condition()))
            self.emit(depth + 1, self.pick(["break", "continue"]))
            self.emit(depth, "}")
        elif roll < 0.93:
            self.error_statement(depth)
        elif roll < 0.95 and context.get("in_function") and not context.get("in_loop"):
            self.emit(depth, self.pick(["break", "continue"]))      # stray: an error
        elif roll < 0.98:
            self.closures(depth, context)
        elif self.chance(0.5):
            # Chained assignment, and a dictionary's fields set and deleted.
            record = self.fresh("record")
            self.emit(depth, "let {} = {{k: {}, n: 2}}".format(record, self.number(2)))
            self.emit(depth, "{}.k = {} = {}".format(record, self.pick(NAMES), self.number(1)))
            self.emit(depth, '{}["{}"] = {}'.format(record, self.pick(["n", "new"]), self.value(1)))
            self.emit(depth, "delete {}.{}".format(record, self.pick(["k", "absent"])))
            self.emit(depth, 'delete {}["n"]'.format(record))
            self.emit(depth, "print({})".format(record))
        else:
            self.store_through(depth)

    # Assignment through an index, a member or delete, on every kind of
    # target with every kind of index (INDEXES, plus -4: a negative index
    # Python would take but NovaLang refuses), and a value that may change
    # the target while it is evaluated - the cases a fast path for these
    # opcodes could get wrong, or get right in the wrong order (M6).
    STORE_TARGETS = ["[10, 20, 30]", "[]", '"abc"', "{k: 1, n: 2}", "{}", "7"]

    def store_through(self, depth):
        target = self.fresh("held")
        literal = self.pick(self.STORE_TARGETS)
        self.emit(depth, "let {} = {}".format(target, literal))
        values = [self.expression(), self.expression(), "pop({})".format(target),
                  "len({})".format(target)]
        if literal.startswith("["):
            # Grows the list before the store happens. Only ever on a list:
            # append() on a string appends to the file of that name.
            values.append("len(append({}, 1))".format(target))
        value = self.pick(values)
        index = self.pick(self.INDEXES + ["-4"])
        kind = self.random.random()
        if kind < 0.6:
            statement = "{}[{}] = {}".format(target, index, value)
        elif kind < 0.8:
            statement = "{}.k = {}".format(target, value)
        else:
            statement = "delete {}[{}]".format(target, index)
        self.emit(depth, "try {")
        self.emit(depth + 1, statement)
        self.emit(depth, "} catch problem {")
        self.emit(depth + 1, 'print("refused:", problem)')
        self.emit(depth, "}")
        self.emit(depth, "print({})".format(target))

    def loop(self, depth, context):
        inner = dict(context, in_loop=True)
        kind = self.random.random()
        if kind < 0.4:
            counter = self.fresh("w")
            self.emit(depth, "let {} = 0".format(counter))
            self.emit(depth, "while {} < {} {{".format(counter, self.random.randint(0, 4)))
            self.emit(depth + 1, "{0} = {0} + 1".format(counter))
        elif kind < 0.75:
            variable = self.pick(NAMES + [self.fresh("i")])
            if self.chance(0.5):
                self.emit(depth, "for {} = {} to {}{} {{".format(
                    variable, self.random.randint(0, 2), self.random.randint(0, 5),
                    " step {}".format(self.random.randint(1, 3)) if self.chance(0.3) else ""))
            else:
                self.emit(depth, "for {} = {} downto {} {{".format(
                    variable, self.random.randint(2, 5), self.random.randint(0, 2)))
        else:
            first = self.pick(NAMES)
            if self.chance(0.5):
                self.emit(depth, "for {} in [{}] {{".format(first, ", ".join(
                    str(self.random.randint(0, 5)) for _ in range(self.random.randint(0, 4)))))
            else:
                second = self.pick([n for n in NAMES if n != first])
                self.emit(depth, "for {}, {} in {{p: 1, q: 2, r: 3}} {{".format(first, second))
        self.block(depth + 1, inner)
        if self.chance(0.25):
            self.emit(depth, "} else {")
            self.block(depth + 1, context, 1)
        self.emit(depth, "}")

    def function(self, depth, context):
        name = self.fresh("f")
        params = self.random.sample(NAMES, self.random.randint(0, 2))
        self.emit(depth, "def {}({}) {{".format(name, ", ".join(params)))
        saved = list(self.functions)
        self.block(depth + 1, {"in_function": True})
        self.emit(depth + 1, "return {}".format(self.expression()))
        self.emit(depth, "}")
        self.functions = saved + [(name, len(params))]
        if self.chance(0.7):
            self.emit(depth, "print({})".format(self.call_of(name, len(params))))

    def call_of(self, name, arity):
        return "{}({})".format(name, ", ".join(self.expression(1) for _ in range(arity)))

    def closures(self, depth, context):
        """Closures made in a loop, each with its own variable - called later."""
        bucket = self.fresh("made")
        self.emit(depth, "let {} = []".format(bucket))
        variable = self.pick(NAMES)
        self.emit(depth, "for {} in [1, 2, 3] {{".format(variable))
        self.emit(depth + 1, "let {} = {} * 10".format(self.pick(NAMES), variable))
        inner = self.fresh("g")
        self.emit(depth + 1, "def {}() {{".format(inner))
        self.emit(depth + 2, "return {}".format(self.expression(1)))
        self.emit(depth + 1, "}")
        self.emit(depth + 1, "append({}, {})".format(bucket, inner))
        self.emit(depth, "}")
        self.emit(depth, "for {} in {} {{".format(self.fresh("h"), bucket))
        self.emit(depth + 1, "print({}[0]())".format(bucket))
        self.emit(depth, "}")

    def try_statement(self, depth, context):
        self.emit(depth, "try {")
        self.block(depth + 1, context)
        has_catch = self.chance(0.75)
        if has_catch:
            if self.chance(0.8):
                self.emit(depth, "} catch problem {")
                self.emit(depth + 1, 'print("caught", problem)')
            else:
                self.emit(depth, "} catch {")
            self.block(depth + 1, context, self.random.randint(0, 2))
        if not has_catch or self.chance(0.5):
            self.emit(depth, "} finally {")
            self.emit(depth + 1, 'print("finally")')
            self.block(depth + 1, context, self.random.randint(0, 2))
        self.emit(depth, "}")

    # -- programs ---------------------------------------------------------------

    def program(self):
        for name in NAMES[:6]:
            self.emit(0, "let {} = {}".format(name, self.random.randint(0, 5)))
        self.emit(0, "def deep(n) {")
        self.emit(1, "if n <= 0 { return 0 }")
        self.emit(1, "return deep(n - 1) + 1")
        self.emit(0, "}")
        self.functions.append(("deep", 1))
        # Sometimes run as REPL-style chunks: each is compiled alone, so the
        # globals the earlier chunks made are known only when it runs.
        chunked = self.chance(0.4)
        if chunked:
            self.emit(0, CHUNK_MARK)
        for _ in range(self.random.randint(4, 12)):
            if chunked and self.chance(0.4):
                self.emit(0, CHUNK_MARK)
            if self.chance(0.85):
                # Keep going after an error, so later code is compared too.
                self.emit(0, "try {")
                self.statement(1, {"top": True})
                self.emit(0, "} catch problem {")
                self.emit(1, 'print("error:", problem)')
                self.emit(0, "}")
            else:
                self.statement(0, {"top": True})
        if self.chance(0.05):
            self.emit(0, "deep(5000)")                      # the call-depth limit
        if self.chance(0.04):
            self.emit(0, "return")                          # an error at the top level
        self.emit(0, 'print("end", a, b, c)')
        return "\n".join(self.lines) + "\n"


def generate(seed):
    return Generator(seed).program()
