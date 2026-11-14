#!/usr/bin/env python3
"""NovaLang's baseline benchmarks (M12 starts from these numbers).

    python3 tests/benchmarks/run.py                  the whole suite, a table on standard output
    python3 tests/benchmarks/run.py --json out.json  also write every sample
    python3 tests/benchmarks/run.py --markdown       print the table as Markdown (what docs/benchmarks.md holds)
    python3 tests/benchmarks/run.py --only startup   one group: startup, compile, loop, embedding
    python3 tests/benchmarks/run.py --repeat 15      samples per measurement (default 9)
    python3 tests/benchmarks/run.py --bootstrap      also time the self-hosted interpreter (slow)

What it measures, and what it does not:

  startup    cold start: a new Python process that imports novalang and runs an empty program, next to a bare
             `python3 -c pass` so the cost of Python itself can be subtracted;
  compile    the front end on a real 3,500-line program (novalang.nova, the self-hosted interpreter): lexing,
             parsing and compiling to bytecode, each timed on its own, in one process;
  loop       steady-state execution of a tight loop on the bytecode VM and on the tree-walker, with the opcode
             work of one iteration counted as one iteration, and on the VM under the `restricted` profile so that
             the price of M11's limit checks is a number (trusted is unlimited);
  workloads  programs that do real work, in-process, trusted and restricted (see suite.py): about a dozen micro
             programs, Nova_Data, Nova_Log and Nova_Stats; --full adds the 50 MB Nova_Log benchmark
  embedding  the embedding API: creating an engine, `eval` of a cached script, `call` of a NovaLang function from
             Python, and a call that goes back out to a Python host function.

Every measurement runs one warm-up and then --repeat samples and reports the median, the fastest and the spread
((max - min) / median). On a shared machine the spread is the number to look at first: a difference smaller than
it is noise. The numbers are for comparing one machine with itself over time (the M12 plan, D6), not for comparing
machines. Nothing here depends on the machine's name, paths or user.
"""

import argparse
import gc
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

LOOP_ITERATIONS = 200_000
LOOP_PROGRAM = """\
let total = 0
for i = 1 to {n} {{
  total = total + i % 7
}}
print(total)
""".format(n=LOOP_ITERATIONS)
EMBEDDING_SOURCE = "def add(a, b) { return a + b }\ndef twice(f, x) { return f(f(x)) }\n"


def sample(function, repeat, warmup=None):
    """`repeat` timings of function() in seconds, after `warmup` untimed calls (default 1; NOVA_BENCH_WARMUP=n for a JIT)."""
    if warmup is None:
        warmup = int(os.environ.get("NOVA_BENCH_WARMUP", "1"))
    for _ in range(warmup):
        function()
    times = []
    for _ in range(repeat):
        gc.collect()
        gc.disable()
        try:
            start = time.perf_counter()
            function()
            times.append(time.perf_counter() - start)
        finally:
            gc.enable()
    return times


def summary(name, group, times, unit_count=None, unit="", note=""):
    median = statistics.median(times)
    row = {"group": group, "name": name, "median_ms": median * 1000, "min_ms": min(times) * 1000,
           "max_ms": max(times) * 1000, "spread": (max(times) - min(times)) / median if median else 0.0,
           "samples": len(times), "note": note}
    if unit_count:
        row["per_second"] = unit_count / median
        row["unit"] = unit
    return row


def run_process(arguments, cwd=None):
    done = subprocess.run([sys.executable] + arguments, cwd=cwd or str(ROOT), capture_output=True, text=True,
                          env=dict(os.environ, PYTHONUTF8="1"))
    if done.returncode != 0:
        raise SystemExit("benchmark process failed: {}\n{}".format(arguments, done.stderr[-500:]))


# ------------------------------------------------------------------------------------------------ groups

def startup(repeat, with_bootstrap):
    rows = []
    with tempfile.TemporaryDirectory(prefix="nova-bench-") as folder:
        empty = os.path.join(folder, "empty.nova")
        Path(empty).write_text("", encoding="utf-8")
        script = str(ROOT / "novalang.py")
        rows.append(summary("python3 -c pass (the floor)", "startup",
                            sample(lambda: run_process(["-c", "pass"]), repeat)))
        rows.append(summary("import novalang", "startup",
                            sample(lambda: run_process(["-c", "import novalang"]), repeat)))
        rows.append(summary("novalang.py empty.nova (VM)", "startup",
                            sample(lambda: run_process([script, empty]), repeat)))
        rows.append(summary("novalang.py --tree-walk empty.nova", "startup",
                            sample(lambda: run_process([script, "--tree-walk", empty]), repeat)))
        rows.append(summary("novalang.py --profile restricted empty.nova", "startup",
                            sample(lambda: run_process([script, "--profile", "restricted", empty]), repeat)))
        if with_bootstrap:
            rows.append(summary("novalang.py --bootstrap empty.nova (self-hosted)", "startup",
                                sample(lambda: run_process([script, "--bootstrap", empty]), max(3, repeat // 3)),
                                note="fewer samples: it is slow"))
    return rows


def compile_stages(repeat):
    source = (ROOT / "novalang.nova").read_text(encoding="utf-8")
    lines = source.count("\n")
    tokens = nl.Lexer(source).tokenize()
    ast = nl.Parser(tokens).parse()
    rows = [
        summary("lex ({:,} lines)".format(lines), "compile",
                sample(lambda: nl.Lexer(source).tokenize(), repeat), lines, "lines/s"),
        summary("parse ({:,} tokens)".format(len(tokens)), "compile",
                sample(lambda: nl.Parser(tokens).parse(), repeat), lines, "lines/s",
                note="the same token list is parsed on every sample"),
        summary("compile AST to bytecode", "compile", sample(lambda: nl.compile_ast(ast), repeat), lines, "lines/s"),
        summary("lex + parse + compile", "compile", sample(lambda: nl.compile_source(source), repeat), lines,
                "lines/s"),
    ]
    return rows


def run_program(source, engine, profile):
    capabilities = (nl.Capabilities(profile="restricted", limits={"steps": 5_000_000, "time": 60000})
                    if profile == "restricted" else None)
    interpreter = nl.Interpreter(engine, capabilities=capabilities)
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        nl.run(source, interpreter)


def loops(repeat):
    rows = []
    for label, engine, profile in (("VM, trusted", "vm", "trusted"), ("tree-walker, trusted", "tree", "trusted"),
                                   ("VM, restricted (limits on)", "vm", "restricted")):
        if profile == "restricted" and nl.SANDBOX_UNSUPPORTED:
            continue
        rows.append(summary("tight loop, {:,} iterations: {}".format(LOOP_ITERATIONS, label), "loop",
                            sample(lambda: run_program(LOOP_PROGRAM, engine, profile), max(3, repeat // 2)),
                            LOOP_ITERATIONS, "iterations/s"))
    return rows


def embedding(repeat):
    rows = []
    rows.append(summary("Nova() (a new engine)", "embedding", sample(lambda: nl.Nova(), repeat * 4), 1, "engines/s"))
    rows.append(summary("Nova().eval('1 + 2') (a new engine and a first, uncached script)", "embedding",
                        sample(lambda: nl.Nova().eval("1 + 2"), repeat * 4), 1, "engines/s"))
    nova = nl.Nova()
    nova.exec(EMBEDDING_SOURCE)
    calls = 20_000
    rows.append(summary("nova.eval('1 + 2') x {:,} (cached script)".format(calls), "embedding",
                        sample(lambda: [nova.eval("1 + 2") for _ in range(calls)], repeat), calls, "evals/s"))
    rows.append(summary("nova.call('add', 1, 2) x {:,}".format(calls), "embedding",
                        sample(lambda: [nova.call("add", 1, 2) for _ in range(calls)], repeat), calls, "calls/s"))
    host = nl.Nova()
    host.expose_global("py_inc", lambda x: x + 1)
    host.exec("def run(n) {\n  let total = 0\n  for i = 1 to n { total = py_inc(total) }\n  return total\n}\n")
    rows.append(summary("NovaLang loop calling a Python host function x {:,}".format(calls), "embedding",
                        sample(lambda: host.call("run", calls), repeat), calls, "host calls/s"))
    nova.exec("def build(n) { let l = []\n for i = 1 to n { append(l, i) }\n return l }\n")
    rows.append(summary("nova.call('build', 1000) -> a Python list of 1,000", "embedding",
                        sample(lambda: [nova.call("build", 1000) for _ in range(50)], repeat), 50, "calls/s"))
    return rows


def workloads_group(repeat):
    import suite
    return suite.workloads(min(repeat, WORKLOAD_REPEAT), full=OPTIONS["full"], log_file=OPTIONS["log_file"])


WORKLOAD_REPEAT = 5      # workloads are long; the default of 9 samples would take half an hour
OPTIONS = {"full": False, "log_file": None}
GROUPS = {"startup": None, "compile": compile_stages, "loop": loops, "embedding": embedding,
          "workloads": workloads_group}


def environment():
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), capture_output=True,
                                text=True).stdout.strip() or "unknown"
        dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=str(ROOT),
                                    capture_output=True, text=True).stdout.strip())
    except OSError:
        commit, dirty = "unknown", False
    return {"python": platform.python_version(), "implementation": platform.python_implementation(),
            "system": platform.system(), "machine": platform.machine(), "cpus": os.cpu_count(),
            "novalang": nl.__version__, "commit": commit + ("+modified" if dirty else "")}


def table(rows, markdown):
    def line(row):
        rate = "{:,.0f} {}".format(row["per_second"], row["unit"]) if "per_second" in row else ""
        name = row["name"] + (" [{}]".format(row["profile"]) if "profile" in row else "")
        compile_cell = ("{:.1f} ({:.1%})".format(row["compile_ms"], row["compile_share"])
                        if "compile_ms" in row else "")
        return (name, "{:.3f}".format(row["median_ms"]), "{:.3f}".format(row["min_ms"]),
                "{:.0%}".format(row["spread"]), rate, compile_cell)
    header = ("measurement", "median ms", "min ms", "spread", "rate", "compile ms (share)")
    body = [line(row) for row in rows]
    out = []
    if markdown:
        out.append("| " + " | ".join(header) + " |")
        out.append("| --- | ---: | ---: | ---: | ---: | ---: |")
        out += ["| " + " | ".join(cells) + " |" for cells in body]
    else:
        widths = [max(len(cells[i]) for cells in [header] + body) for i in range(6)]
        for cells in [header] + body:
            out.append("  ".join(cells[i].ljust(widths[i]) if i == 0 else cells[i].rjust(widths[i]) for i in range(6)))
    return "\n".join(out)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=9, help="samples per measurement (workloads use at most 5)")
    parser.add_argument("--json")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--only", choices=sorted(GROUPS))
    parser.add_argument("--bootstrap", action="store_true", help="also time the self-hosted interpreter's start-up")
    parser.add_argument("--full", action="store_true", help="workloads: also run the 50 MB Nova_Log benchmark (3 samples)")
    parser.add_argument("--log-file", help="workloads: also time Nova_Log on this access log (trusted)")
    arguments = parser.parse_args(argv)
    OPTIONS["full"], OPTIONS["log_file"] = arguments.full, arguments.log_file
    rows = []
    for name in GROUPS:
        if arguments.only and arguments.only != name:
            continue
        if name == "startup":
            rows += startup(arguments.repeat, arguments.bootstrap)
        else:
            rows += GROUPS[name](arguments.repeat)
    env = environment()
    print("# NovaLang {novalang}, {implementation} {python}, {system} {machine}, {cpus} CPUs".format(**env))
    print(table(rows, arguments.markdown))
    if arguments.json:
        Path(arguments.json).write_text(json.dumps({"environment": env, "rows": rows}, indent=1) + "\n",
                                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
