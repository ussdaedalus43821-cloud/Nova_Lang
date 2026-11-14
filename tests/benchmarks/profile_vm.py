#!/usr/bin/env python3
"""Where does the VM's time go? (M12 slice 2.) A counting build of the dispatch loop, not a sampling profile.

    python3 tests/benchmarks/profile_vm.py nova_log            a preset: nova_log, nova_data, nova_stats, or micro/<file>
    python3 tests/benchmarks/profile_vm.py path/to/file.nova [ARGS ...] [--units N --unit-name lines]
    python3 tests/benchmarks/profile_vm.py nova_log --markdown          tables in Markdown (docs/design/m12-vm-profile.md)
    python3 tests/benchmarks/profile_vm.py nova_log --cprofile          also the Python functions that cost the most

Nothing in novalang.py is changed. The profiler builds a copy of `execute` (the dispatch loop) in memory with three
lines added where each instruction is fetched: they count the opcode and credit the time since the previous fetch to
the previous opcode. It also wraps `Interpreter.call_value` and every built-in's implementation, so a call to a built-in
(`len`, `split`, ...) is split into what the library function itself costs and what the interpreter adds around it.

How to read the numbers, and how far to trust them:

  * Counts are exact. Times are estimates: every instruction pays for two clock reads, so the raw times are scaled so
    that they add up to the wall time of an uninstrumented run of the same program (the scale factor is printed;
    one or two is normal). Compare shares, not absolute nanoseconds.
  * An opcode's time includes everything it does: the CALL of a built-in includes the whole built-in.
  * The built-in table is a breakdown of the CALL time: `inside` is the library function, `around` is call_value's own
    checks (arity, limits, path grants, result size) plus the clock reads of the wrapper, which are subtracted.
  * What a share could win is an UPPER BOUND: removing a cost entirely is the most any fast path could do.
"""

import argparse
import contextlib
import cProfile
import gc
import inspect
import io
import os
import pstats
import statistics
import sys
import tempfile
import textwrap
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import novalang as nl  # noqa: E402
import suite  # noqa: E402

PRESETS = ("nova_log", "nova_data", "nova_stats")


# ---------------------------------------------------------------------------------------------- instrumentation

class Counters:
    def __init__(self):
        n = len(nl.OPCODES)
        self.ops = [0] * n
        self.op_time = [0.0] * n
        self.nest = [0.0]                      # time spent in nested execute() calls (imports, callbacks)
        self.builtin_calls = defaultdict(int)  # name -> calls
        self.builtin_total = defaultdict(float)   # name -> time in call_value
        self.builtin_inside = defaultdict(float)  # name -> time in the implementation
        self.user_calls = 0
        self.lookups = 0


def build_instrumented_execute(counters):
    """A copy of nl.execute with counting added at the fetch. Returns the function."""
    source = textwrap.dedent(inspect.getsource(nl.execute))
    fetch = "                op = ops[ip]\n                arg = args[ip]\n                ip += 1\n"
    assert source.count(fetch) == 1, "the fetch of the dispatch loop was not found: has execute() changed?"
    hook = ("                _now = _clock()\n"
            "                _T[_prev] += _now - _last - (_NEST[0] - _seen)\n"
            "                _seen = _NEST[0]\n"
            "                _C[op] += 1\n"
            "                _prev = op\n"
            "                _last = _clock()\n")
    source = source.replace(fetch, fetch + hook)
    start = "    while True:\n        try:\n"
    assert source.count(start) == 1
    source = source.replace(start, "    _prev = 0\n    _seen = _NEST[0]\n    _t0 = _clock()\n    _last = _t0\n" + start)
    # nested calls must be subtracted from the caller's next interval: wrap the whole function
    source = source.replace("def execute(interpreter, entry):", "def _inner(interpreter, entry):", 1)
    namespace = dict(vars(nl))
    namespace.update(_clock=time.perf_counter, _T=counters.op_time, _C=counters.ops, _NEST=counters.nest)
    exec(compile(source, "<instrumented execute>", "exec"), namespace)
    inner = namespace["_inner"]
    clock = time.perf_counter
    nest = counters.nest

    def execute(interpreter, entry):
        start_time = clock()
        try:
            return inner(interpreter, entry)
        finally:
            # credit the last instruction of this run, then tell the caller how long we were away
            nest[0] += clock() - start_time
    return execute


@contextlib.contextmanager
def instrumented(counters):
    original_execute = nl.execute
    original_call_value = nl.Interpreter.call_value
    saved_impl = {}
    clock = time.perf_counter

    def timed_impl(name, implementation):
        def wrapper(*a, **k):
            t = clock()
            try:
                return implementation(*a, **k)
            finally:
                counters.builtin_inside[name] += clock() - t
        return wrapper

    for name, function in nl.BUILTINS.items():
        if isinstance(function, nl.BuiltinFunction):
            saved_impl[name] = function.implementation
            function.implementation = timed_impl(name, function.implementation)

    def call_value(self, callee, args, position):
        if isinstance(callee, nl.BuiltinFunction):
            t = clock()
            try:
                return original_call_value(self, callee, args, position)
            finally:
                counters.builtin_calls[callee.name] += 1
                counters.builtin_total[callee.name] += clock() - t
        counters.user_calls += 1
        return original_call_value(self, callee, args, position)

    nl.execute = build_instrumented_execute(counters)
    nl.Interpreter.call_value = call_value
    try:
        yield
    finally:
        nl.execute = original_execute
        nl.Interpreter.call_value = original_call_value
        for name, implementation in saved_impl.items():
            nl.BUILTINS[name].implementation = implementation


def clock_cost():
    """Seconds one perf_counter() call costs here (the profiler pays two per instruction)."""
    t = time.perf_counter()
    for _ in range(200000):
        time.perf_counter()
    return (time.perf_counter() - t) / 200000


def wrapper_cost():
    """Seconds one wrapped call adds (two clock reads and a dictionary update), measured on a no-op."""
    clock = time.perf_counter
    acc = defaultdict(float)

    def f():
        pass

    def wrapped():
        t = clock()
        try:
            return f()
        finally:
            acc["x"] += clock() - t
    n = 200000
    t = clock()
    for _ in range(n):
        wrapped()
    with_wrapper = clock() - t
    t = clock()
    for _ in range(n):
        f()
    return (with_wrapper - (clock() - t)) / n


# ---------------------------------------------------------------------------------------------- running

def prepare(target, extra, work):
    """-> (program path, argv, profile name, grants, cwd, units, unit name, description)."""
    if target == "nova_log":
        log = os.path.join(work, "access.log")
        suite.generate([str(suite.WORK / "poc/nova_log/make_log.py"), log, str(suite.LOG_MB)], log)
        n = suite.count_lines(log)
        return suite.WORK / "poc/nova_log/nova_log.nova", [log], None, n, "lines", "Nova_Log, {} MB synthetic log".format(suite.LOG_MB)
    if target == "nova_data":
        csv = os.path.join(work, "transactions.csv")
        suite.generate([str(suite.WORK / "poc/nova_data/make_csv.py"), csv, "10000"], csv)
        return suite.WORK / "poc/nova_data/nova_data.nova", [csv], None, 10000, "rows", "Nova_Data, 10,000 CSV rows"
    if target == "nova_stats":
        d = suite.WORK / "poc/nova_stats"
        return d / "tests/bench.nova", ["50"], d, 50, "ticks", "Nova_Stats, 50 dashboard ticks"
    if target.startswith("micro/"):
        path = suite.WORK / (target if target.endswith(".nova") else target + ".nova")
        return path, extra, None, 1, "run", "micro program " + path.name
    path = Path(target).resolve()
    return path, extra, None, 1, "run", str(target)


def run_plain(program, argv, cwd):
    gc.collect()
    t = time.perf_counter()
    suite.run_once(program, argv, "trusted", {}, cwd=cwd)
    return time.perf_counter() - t


def profile(target, extra, units, unit_name, repeat):
    with tempfile.TemporaryDirectory(prefix="nova-profile-") as work:
        work = os.path.realpath(work)
        program, argv, cwd, n, unit, description = prepare(target, extra, work)
        units = units or n
        unit_name = unit_name or unit
        run_plain(program, argv, cwd)                                    # warm-up
        plain = statistics.median([run_plain(program, argv, cwd) for _ in range(repeat)])
        counters = Counters()
        with instrumented(counters):
            gc.collect()
            t = time.perf_counter()
            suite.run_once(program, argv, "trusted", {}, cwd=cwd)
            instrumented_wall = time.perf_counter() - t
    return {"description": description, "program": str(program), "plain_s": plain, "instrumented_s": instrumented_wall,
            "counters": counters, "units": units, "unit_name": unit_name}


# ---------------------------------------------------------------------------------------------- reporting

def singular(name):
    if name.endswith("sses"):
        return name[:-2]
    return name[:-1] if name.endswith("s") else name


def table(rows, header, markdown, align_right_from=1):
    body = [[str(c) for c in r] for r in rows]
    if markdown:
        out = ["| " + " | ".join(header) + " |",
               "| " + " | ".join("---" if i < align_right_from else "---:" for i in range(len(header))) + " |"]
        return "\n".join(out + ["| " + " | ".join(r) + " |" for r in body])
    widths = [max(len(r[i]) for r in [list(header)] + body) for i in range(len(header))]
    lines = ["  ".join((r[i].ljust(widths[i]) if i < align_right_from else r[i].rjust(widths[i])) for i in range(len(header)))
             for r in [list(header)] + body]
    return "\n".join(lines)


def report(result, markdown, cost_clock, cost_wrapper, cost_compare):
    c = result["counters"]
    positions = chain_positions()
    wall = result["plain_s"]
    raw_total = sum(c.op_time) or 1e-9
    scale = wall / raw_total
    total_ops = sum(c.ops)
    units, unit_name = result["units"], result["unit_name"]
    out = []
    out.append("{}: {:.3f} s plain wall time, {:,} {} ({:,.0f} {}/s)".format(
        result["description"], wall, units, unit_name, units / wall, unit_name))
    out.append("{:,} instructions executed: {:,.1f} per {}; {:,.1f} million instructions/s; {:.0f} ns per instruction on average".format(
        total_ops, total_ops / units, singular(unit_name),
        total_ops / wall / 1e6, wall / total_ops * 1e9))
    out.append("instrumented run {:.3f} s; times scaled by {:.2f} to match the plain run; one clock read costs {:.0f} ns".format(
        result["instrumented_s"], scale, cost_clock * 1e9))
    out.append("")
    rows = []
    for number in sorted(range(len(nl.OPCODES)), key=lambda i: -c.op_time[i]):
        if not c.ops[number]:
            continue
        seconds = c.op_time[number] * scale
        rows.append((nl.OPCODES[number], "{:,}".format(c.ops[number]), "{:.1f}".format(c.ops[number] / units),
                     "{:.1%}".format(c.ops[number] / total_ops), "{:.1%}".format(seconds / wall),
                     "{:.0f}".format(seconds / c.ops[number] * 1e9), positions.get(nl.OPCODES[number], "-"),
                     "{:.0f}".format(max(seconds / c.ops[number] - positions.get(nl.OPCODES[number], 0) * cost_compare, 0) * 1e9)))
    out.append("Instructions, by share of time")
    out.append(table(rows[:16], ("opcode", "count", "per " + singular(unit_name), "% of count", "% of time", "ns each",
                                 "chain tests before it", "ns without the chain tests"), markdown))
    failed = sum(c.ops[number] * positions.get(nl.OPCODES[number], 0) for number in range(len(nl.OPCODES)))
    estimate = failed * cost_compare
    out.append("")
    out.append("Dispatch chain: the loop is one if/elif chain, so an instruction pays for a failed test of every opcode listed before it.")
    out.append("{:,} failed tests ({:.1f} per instruction, {:.1f} per {}); one costs {:.1f} ns here (measured): about {:.1%} of the run "
               "({:.0f} ms of {:.0f} ms)".format(failed, failed / total_ops, failed / units, singular(unit_name),
                                                cost_compare * 1e9, estimate / wall, estimate * 1000, wall * 1000))
    out.append("")
    # built-ins
    brows = []
    call_time = sum(c.builtin_total.values())
    for name in sorted(c.builtin_calls, key=lambda k: -c.builtin_total[k]):
        calls = c.builtin_calls[name]
        total = c.builtin_total[name] * scale
        inside = c.builtin_inside[name] * scale
        total_adj = max(total - calls * cost_wrapper * scale, 0.0)    # the wrapper's own clock reads
        inside_adj = max(inside - calls * cost_wrapper * scale, 0.0)
        around = max(total_adj - inside_adj, 0.0)
        brows.append((name, "{:,}".format(calls), "{:.1f}".format(calls / units), "{:.1%}".format(total_adj / wall),
                      "{:.0f}".format(inside_adj / calls * 1e9), "{:.0f}".format(around / calls * 1e9)))
    out.append("Built-in calls (a breakdown of the CALL time; {:.0%} of all time is spent in calls to built-ins)".format(
        call_time * scale / wall))
    out.append(table(brows[:12], ("built-in", "calls", "per " + singular(unit_name), "% of time", "ns inside", "ns around"), markdown))
    out.append("")
    out.append("{:,} calls to NovaLang functions ({:.1f} per {}); {:,} LOAD_BUILTIN lookups ({:.1f} per {})".format(
        c.user_calls, c.user_calls / units, singular(unit_name), c.ops[nl.OP["LOAD_BUILTIN"]],
        c.ops[nl.OP["LOAD_BUILTIN"]] / units, singular(unit_name)))
    return "\n".join(out), {"scale": scale, "total_ops": total_ops, "wall": wall, "rows": rows, "brows": brows}


def lookup_cost():
    """ns for one Interpreter.lookup_builtin('len') on a trusted engine, measured directly."""
    interpreter = nl.Interpreter("vm")
    n = 300000
    t = time.perf_counter()
    for _ in range(n):
        interpreter.lookup_builtin("len")
    return (time.perf_counter() - t) / n * 1e9


def chain_positions():
    """{opcode name: how many `if op == X_` tests the dispatch loop makes before it reaches this one}."""
    import re
    source = inspect.getsource(nl.execute)
    names = re.findall(r"^ {16}(?:el)?if op == (\w+)_:", source, flags=re.M)
    return {name: index for index, name in enumerate(names)}


def compare_cost(depth=60):
    """Seconds one failed `if op == K:` test costs in a long if/elif chain here (measured, not assumed)."""
    lines = ["def chain(op, n):", "    for _ in range(n):"]
    for i in range(depth):
        lines.append("        {} op == {}:".format("if" if i == 0 else "elif", i))
        lines.append("            pass")
    namespace = {}
    exec("\n".join(lines), namespace)
    chain = namespace["chain"]
    n = 200000
    first = min(timeit_once(chain, 0, n) for _ in range(5))
    last = min(timeit_once(chain, depth - 1, n) for _ in range(5))
    return (last - first) / n / (depth - 1)


def timeit_once(function, op, n):
    t = time.perf_counter()
    function(op, n)
    return time.perf_counter() - t


def cprofile_report(target, extra, limit=14):
    with tempfile.TemporaryDirectory(prefix="nova-profile-") as work:
        program, argv, cwd, *_ = prepare(target, extra, os.path.realpath(work))
        profiler = cProfile.Profile()
        profiler.enable()
        suite.run_once(program, argv, "trusted", {}, cwd=cwd)
        profiler.disable()
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).sort_stats("tottime").print_stats(limit)
    return stream.getvalue()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target")
    parser.add_argument("args", nargs="*")
    parser.add_argument("--units", type=int)
    parser.add_argument("--unit-name")
    parser.add_argument("--repeat", type=int, default=3, help="plain runs for the reference wall time (default 3)")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--cprofile", action="store_true")
    options = parser.parse_args(argv)
    result = profile(options.target, options.args, options.units, options.unit_name, options.repeat)
    text, _ = report(result, options.markdown, clock_cost(), wrapper_cost(), compare_cost())
    print(text)
    print("\none Interpreter.lookup_builtin('len'): {:.0f} ns (a trusted engine)".format(lookup_cost()))
    if options.cprofile:
        print("\nPython functions by own time (cProfile, which slows everything; use the ranking, not the seconds):")
        print(cprofile_report(options.target, options.args))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
