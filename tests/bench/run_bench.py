#!/usr/bin/env python3
"""
run_bench.py - NovaLang's benchmarks, best of N, as whole processes.

    python3 tests/bench/run_bench.py [--runs 3] [--tree-walk]

Each benchmark is timed end to end - starting Python, compiling and
running - because that is what someone running NovaLang waits for.
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

BENCHMARKS = [
    ("fib(22)", ["tests/bench/fib22.nova"]),
    ("examples/fib.nova", ["examples/fib.nova"]),
    ("examples/fib.nova --bootstrap", ["--bootstrap", "examples/fib.nova"]),
    ("self_host_test --bootstrap", ["--bootstrap", "examples/self_host_test.nova"]),
    ("loops (200k iterations)", ["tests/bench/loops.nova"]),
    ("closures (100k closure calls)", ["tests/bench/closures.nova"]),
    ("index_assign (550k stores and deletes)", ["tests/bench/index_assign.nova"]),
]


def best(args, runs):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        done = subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + args,
                              cwd=ROOT, capture_output=True, text=True)
        times.append(time.perf_counter() - start)
        if done.returncode != 0:
            raise SystemExit("benchmark failed: {}\n{}".format(args, done.stderr))
    return min(times)


def main(argv):
    runs = int(argv[argv.index("--runs") + 1]) if "--runs" in argv else 3
    prefix = ["--tree-walk"] if "--tree-walk" in argv else []
    for label, args in BENCHMARKS:
        print("{:34s} {:7.3f} s".format(label, best(prefix + args, runs)), flush=True)


if __name__ == "__main__":
    main(sys.argv)
