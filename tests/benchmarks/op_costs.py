#!/usr/bin/env python3
"""What does one operation cost on the VM? (M12 slice 2: measured upper bounds for the fast-path candidates.)

    python3 tests/benchmarks/op_costs.py [--markdown] [--iterations 200000] [--repeat 5]

Each probe is a NovaLang loop, inside a function (so locals are used, as in most programs), that does one thing per pass, timed in-process on the bytecode VM under `trusted`. The cost
of the empty loop (`for i = 1 to N { }`) is subtracted, so the figure is the extra nanoseconds the operation adds to a
pass. It includes the instructions that load the operands and store the result, which is how a program pays for it.
Read the figures as differences between operations on one machine, not as absolute speeds.
"""

import argparse
import contextlib
import gc
import io
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import novalang as nl  # noqa: E402

FUNCTIONS = """\
def one(a) { return a }
def zero() { return 0 }
"""
LOCALS = """\
let s = "abc,def,ghi"
let l = [10, 20, 30, 40, 50]
let d = {"k": 1, "j": 2}
let t = true
let u = false
let x = 0
let k = "k"
"""


def program(statement, iterations, in_function=True):
    loop = "for i = 1 to {} {{ {} }}\n".format(iterations, statement)
    if in_function:       # locals: LOAD_FAST/STORE_FAST, which is how most of a program runs
        return FUNCTIONS + "def run() {\n" + LOCALS + loop + "}\nrun()\n"
    return FUNCTIONS + LOCALS + loop       # module level: LOAD_GLOBAL/STORE_GLOBAL

# (label, statement run once per pass)
PROBES = [
    ("x = 7                       (LOAD_CONST, STORE_FAST)", "x = 7"),
    ("x = i                       (LOAD_FAST, STORE_FAST)", "x = i"),
    ("x = i + 1                   (int add)", "x = i + 1"),
    ("x = i * 3 % 7               (int mul, mod)", "x = i * 3 % 7"),
    ("x = i < 5                   (int compare)", "x = i < 5"),
    ("x = i == 5                  (int equality)", "x = i == 5"),
    ("x = s >= \"a\"                (string compare, not on the fast path)", "x = s >= \"a\""),
    ("x = s == \"a\"                (string equality)", "x = s == \"a\""),
    ("x = l[2]                    (list index, in range)", "x = l[2]"),
    ("x = l[-1]                   (list index from the end)", "x = l[-1]"),
    ("x = s[2]                    (string index)", "x = s[2]"),
    ("x = s[-1]                   (string index from the end)", "x = s[-1]"),
    ("x = d[\"k\"]                  (dictionary lookup)", "x = d[\"k\"]"),
    ("x = \"b\" in s                (substring test)", "x = \"b\" in s"),
    ("x = k in d                  (dictionary key test)", "x = k in d"),
    ("x = t and u                 (boolean and)", "x = t and u"),
    ("x = t or u                  (boolean or)", "x = t or u"),
    ("if t { x = 1 }              (branch taken)", "if t { x = 1 }"),
    ("if u { x = 1 }              (branch not taken)", "if u { x = 1 }"),
    ("x = len(l)                  (built-in call)", "x = len(l)"),
    ("x = split(s, \",\")           (built-in call, does work)", "x = split(s, \",\")"),
    ("x = one(i)                  (NovaLang function call)", "x = one(i)"),
    ("x = zero()                  (NovaLang call, no arguments)", "x = zero()"),
    ("x = [i, i]                  (build a list)", "x = [i, i]"),
]


def timed(source, repeat):
    best = []
    for _ in range(repeat + 1):
        interpreter = nl.Interpreter("vm")
        gc.collect()
        gc.disable()
        try:
            start = time.perf_counter()
            with contextlib.redirect_stdout(io.StringIO()):
                nl.run(source, interpreter)
            best.append(time.perf_counter() - start)
        finally:
            gc.enable()
    return statistics.median(best[1:])


def measure(iterations, repeat, in_function=True):
    empty = timed(program("", iterations, in_function), repeat)
    rows = [("the empty loop pass", empty / iterations * 1e9, 0.0)]
    for label, statement in PROBES:
        seconds = timed(program(statement, iterations, in_function), repeat)
        rows.append((label, seconds / iterations * 1e9, (seconds - empty) / iterations * 1e9))
    return rows


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iterations", type=int, default=200000)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--module-level", action="store_true", help="probe at module level (globals) instead of in a function")
    options = parser.parse_args(argv)
    rows = measure(options.iterations, options.repeat, not options.module_level)
    if options.markdown:
        print("| probe (one per loop pass) | ns per pass | extra ns over the empty loop |\n| --- | ---: | ---: |")
        for label, per_pass, extra in rows:
            print("| `{}` | {:.0f} | {} |".format(label.rstrip(), per_pass, "" if label.startswith("the empty") else "{:.0f}".format(extra)))
    else:
        for label, per_pass, extra in rows:
            print("{:62s} {:7.0f} ns/pass {:>8s}".format(label, per_pass, "" if label.startswith("the empty") else "+{:.0f} ns".format(extra)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
