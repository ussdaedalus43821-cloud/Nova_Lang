#!/usr/bin/env python3
"""Fuzzers for the restricted profile (docs/spec/16-sandbox.md, threat T13 and the whole of sbx.paths).

    python3 tests/security/fuzz.py programs --seed 1 --count 500     random hostile programs, small limits
    python3 tests/security/fuzz.py paths    --seed 1 --count 300     random paths and file operations
    python3 tests/security/fuzz.py --help

Both are seeded: the same seed and count make the same programs, so a failure is reproduced with the
printed seed and index. Both check what *happened*, not only what was printed:

programs   Random programs built from the built-in functions with hostile arguments, loops, recursion,
           try/catch/finally and big numbers, run on the bytecode VM and the tree-walker with small limits.
           A finding is any exception that is not a NovaLang error, a limit error or an exit (a Python
           traceback reaching the host: T13), a run that outlives its time limit by far, or the two engines
           printing different things. Memory in total is not a finding (threat model N2).

paths      A temporary tree with a file outside the granted folder, links that lead out of it, and random
           file operations on random spellings of paths (`..`, `//`, `.`, links, null bytes, long names,
           `~`, backslashes). A finding is a change to anything outside the granted folder (checked by
           snapshotting the tree: the file system is the oracle, not the engine), the content of an
           outside file in the output, or the temporary folder's real name in the output.

The unit tests (test_fuzz.py) run a small fixed-seed budget of each on every run of the security station.
"""

import argparse
import contextlib
import faulthandler
import hashlib
import io
import json
import os
import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

PURE = json.loads((Path(__file__).parent / "pure_builtins.json").read_text(encoding="utf-8"))["pure"]
GATED = sorted(nl.CAPABILITY_OF)
ENGINES = ("vm", "tree")
LIMITS = {"steps": 30000, "time": 3000, "output": 20000, "list": 2000, "string": 2000, "dict": 60}

# A program must not use more than this many seconds, however the limit is spelled. The limit is 3 s; a
# slow machine and a slow engine get a wide margin, because the finding is "never ends", not "slow".
WALL_SECONDS = 30.0
# Memory is deliberately not a finding: the limits bound each list and string, not how many a program keeps
# (threat model N2). Two thousand lists of two thousand items is 130 MB in 2,000 steps, by design; the
# subprocess runner's address-space limit is the answer, not an in-process check.


# ----------------------------------------------------------------------------------------------------------
# running a program

class Outcome:
    def __init__(self, output, error, kind, seconds, host=None):
        self.output, self.error, self.kind, self.seconds, self.host = output, error, kind, seconds, host

    def signature(self):
        return (self.output, self.error)


def run_program(source, engine, settings, folder=None):
    out = io.StringIO()
    capabilities = nl.Capabilities(profile="restricted", **settings)
    interpreter = nl.Interpreter(engine, capabilities=capabilities)
    if folder is not None:
        interpreter.file_stack.append(folder)
    real_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    started = time.time()
    error, kind, host = "", "ok", None
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                nl.run(source, interpreter)
            except nl.NovaError as problem:
                error, kind = "{}: {}".format(problem.label, problem.message.split("\n")[0]), "error"
            except nl.FatalLimit as problem:
                error, kind = "LimitError: " + problem.message, "limit"
            except nl.ProgramExit:
                kind = "exit"
            except SystemExit:
                kind = "exit"
            except BaseException as problem:  # noqa: BLE001 - anything else is the finding
                kind, host = "host", "{}: {}".format(type(problem).__name__, str(problem)[:200])
    finally:
        sys.stdin = real_stdin
    return Outcome(out.getvalue(), error, kind, time.time() - started, host)


def peak_megabytes():
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024.0 if sys.platform.startswith("linux") else 1024.0 * 1024.0)


# ----------------------------------------------------------------------------------------------------------
# programs

def literal(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\0", "\\0") + '"'


class Writer:
    """Random NovaLang source, typed well enough that programs run for a while before they fail, and
    hostile enough that most of them fail in an interesting way: huge counts, huge numbers, deep
    recursion, callbacks, loops that never end, every statement inside its own try."""

    NUMBERS = ["0", "1", "2", "3", "7", "-1", "-5", "100", "1000", "65536", "99999999999", "0.5", "-0.25",
               "1000000000000.0", "123456789012345678901234567890", "4000", "5000", "1000000", "2147483648",
               "999999999999999999999999999999999999999"]
    STRINGS = ['""', '"a"', '"abc"', '"hello world"', '"\\0"', '"\\n"', '"\u00e9"', '"data/in.txt"', '"1,2,3"',
               '"x"', '","', '" "']
    NUM_VARS = ["n0", "n1"]
    STR_VARS = ["s0", "s1"]
    LIST_VARS = ["l0", "l1"]
    DICT_VARS = ["d0"]

    def __init__(self, rng):
        self.rng = rng
        self.functions = []           # (name, arity)
        self.callbacks = []           # user functions taking one argument, for map/filter

    def pick(self, items):
        return items[self.rng.randrange(len(items))]

    def chance(self, p):
        return self.rng.random() < p

    # ---- expressions by kind
    def expr(self, kind=None, depth=3):
        kind = kind or self.pick(["num", "str", "list", "dict", "bool", "num", "str", "list"])
        if self.chance(0.07):
            kind = self.pick(["num", "str", "list", "dict", "bool"])          # the wrong type, on purpose
        return getattr(self, "e_" + kind)(depth)

    def e_num(self, depth):
        r = self.rng.random()
        if depth <= 0 or r < 0.25:
            return self.pick(self.NUMBERS) if self.chance(0.6) else self.pick(self.NUM_VARS)
        if r < 0.45:
            return "(%s %s %s)" % (self.e_num(depth - 1), self.pick(["+", "-", "*", "/", "%"]), self.e_num(depth - 1))
        if r < 0.50:
            return "(-%s)" % self.e_num(depth - 1)
        if r < 0.55:
            return "%s[%s]" % (self.e_list(depth - 1), self.e_num(depth - 1))
        if r < 0.60 and self.functions:
            name, arity = self.pick(self.functions)
            return "%s(%s)" % (name, ", ".join(self.expr(None, depth - 1) for _ in range(arity)))
        if r < 0.65:
            return "reduce(%s, %s, %s)" % (self.pick(["max", "min", "pow"]), self.e_list(depth - 1), self.e_num(depth - 1))
        name = self.pick(["len", "abs", "ceil", "floor", "round", "sqrt", "ln", "log", "log10", "sin", "cos", "tan",
                          "sum", "max", "min", "num", "byte_length", "pow", "pow", "pow"])
        if name in ("len",):
            return "len(%s)" % self.expr(None, depth - 1)
        if name in ("sum", "max", "min"):
            return "%s(%s)" % (name, self.e_list(depth - 1))
        if name == "num":
            return "num(%s)" % self.e_str(depth - 1)
        if name == "byte_length":
            return "byte_length(%s)" % self.e_str(depth - 1)
        if name == "pow":
            return "pow(%s, %s)" % (self.e_num(depth - 1), self.pick([self.e_num(depth - 1), "2", "100", "3999", "100000"]))
        if name == "round" and self.chance(0.5):
            return "round(%s, %s)" % (self.e_num(depth - 1), self.e_num(depth - 1))
        return "%s(%s)" % (name, self.e_num(depth - 1))

    def e_str(self, depth):
        r = self.rng.random()
        if depth <= 0 or r < 0.25:
            return self.pick(self.STRINGS) if self.chance(0.6) else self.pick(self.STR_VARS)
        if r < 0.40:
            return "(%s + %s)" % (self.e_str(depth - 1), self.e_str(depth - 1))
        if r < 0.50:
            return "(%s * %s)" % (self.e_str(depth - 1), self.pick([self.e_num(depth - 1), "3", "100", "100000", "1000000000"]))
        if r < 0.55:
            return "%s[%s:%s]" % (self.e_str(depth - 1), self.e_num(depth - 1), self.e_num(depth - 1))
        if r < 0.60:
            return "%s[%s]" % (self.e_str(depth - 1), self.e_num(depth - 1))
        if r < 0.65:
            return "join(%s, %s)" % (self.e_list(depth - 1), self.e_str(depth - 1))
        if r < 0.70:
            return "%s(%s, %s)" % (self.pick(["pad", "pad_left"]), self.e_str(depth - 1),
                                    self.pick([self.e_num(depth - 1), "5", "1000000"]))
        if r < 0.75:
            return "str(%s)" % self.expr(None, depth - 1)
        if r < 0.80:
            return "type(%s)" % self.expr(None, depth - 1)
        name = self.pick(["upper", "lower", "trim", "dirname", "reverse"])
        return "%s(%s)" % (name, self.e_str(depth - 1))

    def e_list(self, depth):
        r = self.rng.random()
        if depth <= 0 or r < 0.2:
            return self.pick(self.LIST_VARS) if self.chance(0.5) else "[%s]" % ", ".join(
                self.expr(None, 0) for _ in range(self.rng.randrange(0, 4)))
        if r < 0.30:
            return "(%s + %s)" % (self.e_list(depth - 1), self.e_list(depth - 1))
        if r < 0.38:
            return "(%s * %s)" % (self.e_list(depth - 1), self.pick([self.e_num(depth - 1), "3", "1000", "1000000000"]))
        if r < 0.46:
            return "range(%s)" % self.pick([self.e_num(depth - 1), "5", "500", "1000000", "-3"])
        if r < 0.52:
            return "split(%s, %s)" % (self.e_str(depth - 1), self.e_str(depth - 1))
        if r < 0.56:
            return "split_lines(%s)" % self.e_str(depth - 1)
        if r < 0.60:
            return "%s(%s)" % (self.pick(["keys", "values"]), self.e_dict(depth - 1))
        if r < 0.66:
            return "%s(%s)" % (self.pick(["sorted", "reverse"]), self.e_list(depth - 1))
        if r < 0.74:
            fn = self.pick(self.callbacks + ["str", "len", "abs", "type"]) if self.callbacks or self.chance(0.7) else "str"
            return "%s(%s, %s)" % (self.pick(["map", "filter"]), fn, self.e_list(depth - 1))
        if r < 0.78:
            return "%s[%s:%s]" % (self.e_list(depth - 1), self.e_num(depth - 1), self.e_num(depth - 1))
        if r < 0.82:
            return "[%s]" % ", ".join(self.pick(self.LIST_VARS) for _ in range(self.rng.randrange(1, 4)))
        return "[%s]" % ", ".join(self.expr(None, depth - 1) for _ in range(self.rng.randrange(0, 4)))

    def e_dict(self, depth):
        if depth <= 0 or self.chance(0.4):
            return self.pick(self.DICT_VARS)
        keys = []
        for _ in range(self.rng.randrange(0, 3)):
            key = self.pick(self.STRINGS)
            if key not in keys:
                keys.append(key)
        return "{" + ", ".join("%s: %s" % (k, self.expr(None, depth - 1)) for k in keys) + "}"

    def e_bool(self, depth):
        r = self.rng.random()
        if depth <= 0 or r < 0.2:
            return self.pick(["true", "false"])
        if r < 0.45:
            return "(%s %s %s)" % (self.e_num(depth - 1), self.pick(["<", ">", "<=", ">=", "==", "!="]), self.e_num(depth - 1))
        if r < 0.6:
            return "(%s == %s)" % (self.expr(None, depth - 1), self.expr(None, depth - 1))
        if r < 0.8:
            return "(%s %s %s)" % (self.e_bool(depth - 1), self.pick(["and", "or"]), self.e_bool(depth - 1))
        return "(not %s)" % self.e_bool(depth - 1)

    # ---- statements
    def block(self, depth, lines, wrap=True):
        pad = "  " * depth
        for _ in range(self.rng.randrange(1, 4)):
            inner = self.statement(depth)
            if wrap and self.chance(0.5) and not inner[0].startswith(("try", "def")):
                inner = ["try {"] + ["  " + x for x in inner] + ["} catch err {", "  print(str(err)[0:20])", "}"]
            lines.extend(pad + line for line in inner)

    def statement(self, depth):
        r = self.rng.random()
        e = self.expr
        if depth > 2:
            r *= 0.5
        if r < 0.12:
            return ["print(%s)" % e()]
        if r < 0.22:
            kind = self.pick(["num", "str", "list", "dict"])
            names = {"num": self.NUM_VARS, "str": self.STR_VARS, "list": self.LIST_VARS, "dict": self.DICT_VARS}[kind]
            return ["%s = %s" % (self.pick(names), e(kind))]
        if r < 0.28:
            return ["%s[%s] = %s" % (self.pick(self.LIST_VARS), e("num", 1), e(None, 2))]
        if r < 0.33:
            return ["%s[%s] = %s" % (self.pick(self.DICT_VARS), e("str", 1), e(None, 2))]
        if r < 0.40:
            return ["append(%s, %s)" % (self.pick(self.LIST_VARS), e(None, 2))]
        if r < 0.44:
            return ["throw(%s)" % e(None, 2)]
        if r < 0.54:
            lines = ["if %s {" % e("bool", 2)]
            self.block(depth + 1, lines)
            lines.append("} else {")
            self.block(depth + 1, lines)
            lines.append("}")
            return lines
        if r < 0.62:
            lines = ["for i%d = %s to %s {" % (depth, self.pick(["0", "1", "5"]),
                                                 self.pick(["3", "50", "100000", "100000000", e("num", 1)]))]
            self.block(depth + 1, lines)
            lines.append("}")
            return lines
        if r < 0.68:
            lines = ["for x%d in %s {" % (depth, e("list", 1))]
            self.block(depth + 1, lines)
            lines.append("}")
            return lines
        if r < 0.74:
            lines = ["while %s {" % self.pick(["true", "true", e("bool", 2), "n0 < 100000"])]
            self.block(depth + 1, lines)
            lines.append("}")
            return lines
        if r < 0.90:
            lines = ["try {"]
            self.block(depth + 1, lines, wrap=False)
            lines.append("} catch err {")
            self.block(depth + 1, lines, wrap=False)
            if self.chance(0.4):
                lines.append("} finally {")
                self.block(depth + 1, lines, wrap=False)
            lines.append("}")
            return lines
        if self.functions:
            name, arity = self.pick(self.functions)
            return ["%s(%s)" % (name, ", ".join(e(None, 2) for _ in range(arity)))]
        return ["print(%s)" % e()]

    def definition(self):
        name = "f%d" % len(self.functions)
        arity = self.pick([0, 1, 1, 1, 2])
        params = ["p%d" % i for i in range(arity)]
        self.functions.append((name, arity))
        if arity == 1:
            self.callbacks.append(name)
        lines = ["def %s(%s) {" % (name, ", ".join(params))]
        self.block(1, lines)
        shapes = ["return %s" % self.expr(None, 2)]
        if arity:
            shapes += ["return %s(%s)" % (name, ", ".join(self.pick(["p%d + 1" % i, "p%d" % i, "len(str(p%d))" % i]) if False else
                                                          "p0" for i in range(arity))),
                       "return %s(%s)" % (name, ", ".join("[p%d]" % i for i in range(arity))),
                       "return map(%s, [p0])" % name]
        lines.append("  " + self.pick(shapes))
        lines.append("}")
        return lines

    def program(self):
        lines = ["let n0 = %s" % self.pick(self.NUMBERS), "let n1 = %s" % self.pick(self.NUMBERS),
                 "let s0 = %s" % self.pick(self.STRINGS), "let s1 = %s" % self.pick(self.STRINGS),
                 "let l0 = [%s]" % ", ".join(self.pick(self.NUMBERS) for _ in range(self.rng.randrange(0, 4))),
                 "let l1 = [%s]" % ", ".join(self.pick(self.STRINGS) for _ in range(self.rng.randrange(0, 4))),
                 "let d0 = {}"]
        for _ in range(self.rng.randrange(0, 3)):
            lines.extend(self.definition())
        for _ in range(self.rng.randrange(3, 9)):
            inner = self.statement(0)
            if self.chance(0.8) and not inner[0].startswith(("try", "def")):
                inner = ["try {"] + ["  " + x for x in inner] + ["} catch err {", "  print(str(err)[0:20])", "}"]
            lines.extend(inner)
        return "\n".join(lines)


def settings_for(rng):
    limits = dict(LIMITS)
    if rng.random() < 0.3:
        limits["steps"] = rng.choice([100, 1000, 5000])
    if rng.random() < 0.2:
        limits["output"] = rng.choice([10, 100, 1000])
    if rng.random() < 0.2:
        limits["list"] = rng.choice([1, 10, 100])
    if rng.random() < 0.2:
        limits["string"] = rng.choice([1, 10, 100])
    return {"limits": limits}


def check_program(source, settings, report):
    """Run one program on both engines; return a list of findings."""
    findings = []
    outcomes = {}
    for engine in ENGINES:
        # A call that never returns (one long C-level operation in a built-in) cannot be reported from inside the
        # process: its own time limit is checked between steps. The watchdog prints where it is stuck and ends the
        # process, so the run fails with a stack and the seed instead of waiting for the job to time out.
        faulthandler.dump_traceback_later(WALL_SECONDS * 2, exit=True)
        try:
            outcome = run_program(source, engine, settings)
        finally:
            faulthandler.cancel_dump_traceback_later()
        outcomes[engine] = outcome
        if outcome.kind == "host":
            findings.append("{}: a host exception reached the program's caller: {}".format(engine, outcome.host))
        if outcome.seconds > WALL_SECONDS:
            findings.append("{}: ran for {:.1f} s against a time limit of {} ms".format(
                engine, outcome.seconds, settings["limits"]["time"]))
        for line in (outcome.error + "\n" + outcome.output).splitlines():
            if "Traceback" in line or line.startswith("InternalError"):
                findings.append("{}: the output has a host report: {}".format(engine, line[:120]))
        if len(outcome.output.encode("utf-8")) > settings["limits"]["output"]:
            findings.append("{}: printed {} bytes past an output limit of {}".format(
                engine, len(outcome.output.encode("utf-8")), settings["limits"]["output"]))
    vm, tree = outcomes["vm"], outcomes["tree"]
    # The tree-walker runs out of Python stack before it reaches the depth limit (the conformance runner skips
    # its deep cases for the same reason), and a time limit trips at a different step on each engine.
    incomparable = ("time limit" in vm.error + tree.error or "call depth" in vm.error + vm.output + tree.error
                    or "ran out of stack" in vm.error + tree.error)
    if (vm.kind in ("ok", "error", "exit") and tree.kind in ("ok", "error", "exit")
            and not incomparable and vm.signature() != tree.signature()):
        findings.append("the engines differ: vm {!r} / tree {!r}".format(vm.signature(), tree.signature()))
    return findings


def fuzz_programs(seed, count, report=print, start=0):
    failures = []
    for index in range(start, start + count):
        rng = random.Random("%s/%s" % (seed, index))
        source = Writer(rng).program()
        settings = settings_for(rng)
        found = check_program(source, settings, report)
        if found:
            failures.append((index, source, settings, found))
            report("FINDING seed={} index={}:\n  {}\n--- program ---\n{}\n--- limits: {} ---".format(
                seed, index, "\n  ".join(found), source, settings["limits"]))
    return failures


# ----------------------------------------------------------------------------------------------------------
# paths

OUTSIDE_MARKERS = ["SECRET-OUTSIDE", "PRIVATE-X", "SIBLING-X", "OUTSIDE-MODULE"]
COMPONENTS = ["data", "data", "sub", "..", "..", ".", "", "in.txt", "secret.txt", "private", "x.txt", "linkout",
              "linkdir", "up", "data2", "lib", "~", "a", " ", "\\", "DATA", "Secret.txt", "deep.txt", "new.txt",
              "\0", "...", "data.", "x" * 300, "%2e%2e", ":", "con", "in.txt/", "loop", "hop"]
SEPARATORS = ["/", "/", "/", "//", "/./", "\\"]


TRAPS = ["data/sub/up/../secret.txt", "data/linkdir/x.txt", "data/linkdir/../secret.txt", "data/up/secret.txt",
         "data/linkout", "data/hop", "lib/evil.nova", "data/sub/up/../../secret.txt", "data/sub/up/secret.txt",
         "data/linkdir", "data/up/data2/x.txt", "data/up/private/x.txt", "lib/../other/o.nova"]


def random_path(rng):
    if rng.random() < 0.3:
        path = rng.choice(TRAPS)
        if rng.random() < 0.3:
            path += rng.choice(SEPARATORS) + rng.choice(COMPONENTS)
        return path
    parts = [rng.choice(COMPONENTS) for _ in range(rng.randrange(1, 6))]
    if rng.random() < 0.5:
        parts.insert(0, "data")
    path = parts[0]
    for part in parts[1:]:
        path += rng.choice(SEPARATORS) + part
    if rng.random() < 0.08:
        path = "/" + path
    return path


def build_tree(folder, links):
    files = {"data/in.txt": "hello", "data/sub/deep.txt": "deep", "secret.txt": "SECRET-OUTSIDE",
             "private/x.txt": "PRIVATE-X", "data2/x.txt": "SIBLING-X", "lib/m.nova": "export let x = 1",
             "other/o.nova": 'export let x = "OUTSIDE-MODULE"'}
    for name, text in files.items():
        path = Path(folder).joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if links:
        for name, target in {"data/linkout": "../secret.txt", "data/linkdir": "../private", "data/sub/up": "..",
                             "data/up": "../..", "data/loop": "loop", "data/hop": "linkout",
                             "lib/evil.nova": "../other/o.nova"}.items():
            os.symlink(target, os.path.join(folder, *name.split("/")))


def snapshot(folder):
    found = {}
    for here, directories, names in os.walk(folder):
        for name in directories + names:
            path = os.path.join(here, name)
            rel = os.path.relpath(path, folder).replace(os.sep, "/")
            if os.path.islink(path):
                found[rel] = "link -> " + os.readlink(path)
            elif os.path.isdir(path):
                found[rel] = "directory"
            else:
                with open(path, "rb") as handle:
                    found[rel] = "file " + hashlib.sha256(handle.read()).hexdigest()
    return found


def operation(rng):
    one = rng.choice(["read", "exists", "listdir", "write", "append", "mkdir", "remove", "delete", "import"])
    path = random_path(rng)
    if one == "import":
        return 'import %s as m\nprint(m.x)' % literal(path)
    if one in ("write", "append"):
        return "%s(%s, %s)" % (one, literal(path), literal("pwned"))
    if one in ("rename", "copy"):
        return "%s(%s, %s)" % (one, literal(path), literal(random_path(rng)))
    return "%s(%s)" % (one, literal(path))


def program_of_operations(rng):
    lines = []
    for _ in range(rng.randrange(1, 6)):
        kind = rng.random()
        if kind < 0.2:
            call = "%s(%s, %s)" % (rng.choice(["rename", "copy"]), literal(random_path(rng)), literal(random_path(rng)))
        else:
            call = operation(rng)
        if call.startswith("import"):
            lines.append(call)          # an import is a statement of its own, at the top level
        else:
            lines.append("try { print(%s) } catch e { print(e) }" % call)
    # imports first: they are only allowed at the top level, and the rest may depend on nothing
    lines.sort(key=lambda line: 0 if line.startswith("import") else 1)
    return "\n".join(lines)


def check_paths(source, links, grants):
    """Run `source` in a fresh tree on both engines; return findings."""
    findings = []
    for engine in ENGINES:
        with tempfile.TemporaryDirectory(prefix="nova-fuzz-") as folder:
            folder = os.path.realpath(folder)
            build_tree(folder, links)
            before = snapshot(folder)
            here = os.getcwd()
            os.chdir(folder)
            try:
                outcome = run_program(source, engine, grants, folder)
            finally:
                os.chdir(here)
            after = snapshot(folder)
            writable = [w.rstrip("/") for w in grants.get("write", [])]
            for rel in sorted(set(before) | set(after)):
                if before.get(rel) != after.get(rel):
                    if not any(rel == w or rel.startswith(w + "/") for w in writable):
                        findings.append("{}: {} changed outside the writable folders ({} -> {})".format(
                            engine, rel, before.get(rel), after.get(rel)))
            shown = outcome.output + "\n" + outcome.error
            for marker in OUTSIDE_MARKERS:
                if marker in shown:
                    findings.append("{}: the content of an outside file ({}) was printed".format(engine, marker))
            if folder in shown or Path(folder).name in shown:
                findings.append("{}: the name of the temporary folder reached the output".format(engine))
            if outcome.kind == "host":
                findings.append("{}: a host exception reached the caller: {}".format(engine, outcome.host))
    return findings


def fuzz_paths(seed, count, report=print, links=True, start=0):
    failures = []
    for index in range(start, start + count):
        rng = random.Random("paths/%s/%s" % (seed, index))
        grants = {"read": ["data"], "write": ["data"] if rng.random() < 0.7 else [],
                  "import_from": ["lib"], "limits": dict(LIMITS)}
        source = program_of_operations(rng)
        found = check_paths(source, links, grants)
        if found:
            failures.append((index, source, found))
            report("FINDING seed={} index={}:\n  {}\n--- program ---\n{}\n--- grants: {} ---".format(
                seed, index, "\n  ".join(found), source, {k: v for k, v in grants.items() if k != "limits"}))
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("which", choices=["programs", "paths"])
    parser.add_argument("--seed", default="1")
    parser.add_argument("--count", type=int, default=200)
    arguments = parser.parse_args()
    if nl.SANDBOX_UNSUPPORTED:
        print("the restricted profile needs Python 3.8 or later on Windows")
        return 0
    started = time.time()
    if arguments.which == "programs":
        failures = fuzz_programs(arguments.seed, arguments.count)
    else:
        links = True
        try:
            with tempfile.TemporaryDirectory() as folder:
                os.symlink("target", os.path.join(folder, "link"))
        except (OSError, NotImplementedError, AttributeError):
            links = False
        failures = fuzz_paths(arguments.seed, arguments.count, links=links)
    print("{} {} of seed {}: {} finding(s) in {:.1f} s".format(
        arguments.count, arguments.which, arguments.seed, len(failures), time.time() - started))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
