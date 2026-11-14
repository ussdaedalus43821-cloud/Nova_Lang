# GAPS.md - gaps found in NovaLang itself, outside the proof-of-concept apps

The proof-of-concept apps keep their own logs: Nova_Stats G-001 to G-026, Nova_Sort G-027 to G-035, Nova_Log G-036 to G-042 and
Nova_Data G-043 to G-050 (see [`ROADMAP.md`](ROADMAP.md), M13, "Requirements from the Proof-of-Concept Apps"). This file continues the same numbering
for gaps found any other way, here in M12 work, so the ecosystem keeps one list. The next free number is **G-053**.

**How to read an entry.** *Tried* is what was done and the exact result. *Why it matters* says what promise it touches. *Fix* says where it is planned.
*Probe* is a check in `tests/` that passes while the gap exists and fails the day it is fixed, as in the proof-of-concept repositories.

**Severity:** LIMIT - BLOCKER - FRICTION - TRAP - minor. A **PORTABILITY** gap is one that appears only on a host the project does not yet support.

| # | Gap | Severity | Planned |
| --- | --- | --- | --- |
| G-052 | A float literal too large for a binary64 is silently infinity (a 400-digit `1000...0.0`), and `inf - inf` of two of them is `nan` | TRAP (minor) | M13, with the number work: **decided 2026-11-14 (slice 2): keep and document** (`[lib.std-format]`); the lexer is not changed |
| G-051 | On PyPy a deeply nested program crashes the interpreter (segmentation fault) instead of getting the named nesting error; the nesting limit depends on the host's `RecursionError` | PORTABILITY, and a TRAP: the same setting crashes at 20,000 and silently runs at 10,000 | M12 slice 6, or earlier |

## G-051 The nesting limit depends on the host's recursion limit, and PyPy breaks it - PORTABILITY
- **Found:** 2026-11-14, running NovaLang's own test suite on PyPy 3.10.16 to see whether the 9x to 14x speedup of the benchmark suite
  ([`benchmarks.md`](benchmarks.md), "D7, first measurement") could be a supported engine.
- **Tried:** a program that is one long chain, `print(true and true and ... and true)` with 20,000 operands.
  - **CPython 3.9.6:** `NovaError: the interpreter ran out of stack - recursion too deep`, exit status 1. This is the behaviour the specification
    asks for ([`spec/06-portability.md`](spec/06-portability.md) `[port.limits]`, [`spec/05-security.md`](spec/05-security.md)).
  - **PyPy 3.10.16, as it ships:** the interpreter is killed by a **segmentation fault** (exit status 139), under `trusted` and under `restricted`, with no
    output. It aborts the sandbox unit tests at the first such case and the conformance run (`sbx-limit-nesting`, `esc-parser-nesting-*`).
  - **PyPy with the recursion limit capped at 10,000** (a `sitecustomize` hook outside the repository; `novalang.py` unchanged): the crash is gone, all 256
    sandbox unit tests pass, and the conformance corpus fails **2 cases**, in which PyPy neither raises the nesting error nor crashes: the program runs and prints its result.
- **Why it matters:** `novalang.py` does `sys.setrecursionlimit(20000)` and turns the host's `RecursionError` into NovaLang's nesting error. That means the
  limit is *whatever the host's recursion limit means*: on CPython it is a frame count the C stack can hold; on PyPy the same number either overruns the C
  stack or is not counted the way the corpus expects. A language limit that a host can silently change into a crash, or into no limit at all, is not a limit.
  It does not break the supported configurations (CPython 3.7 to 3.13); it is why **PyPy is a measurement and not a supported engine**, and why the
  `restricted` profile must not be offered on it (M12 plan, slice 8: a new engine may not carry the name until the 201-cell matrix passes on it).
- **Workaround:** none in the program. Do not run NovaLang on PyPy.
- **Fix (decided 2026-11-14: slice 6 or earlier):** make the nesting depth **explicit**: a counter in the parser, the compiler and the tree-walker (and the
  loader of the bytecode chapter, [`spec/17-bytecode.md`](spec/17-bytecode.md) V1), with a stated maximum and the same
  error text, independent of the host's recursion limit; then raise `sys.setrecursionlimit` only as far as that maximum needs, and re-run the two failing conformance cases and the
  suite on PyPy. The explicit limit is worth having on CPython too: it is the same on every host, as the portability chapter wants.
- **Probe:** [`tests/portability/test_pypy_nesting.py`](../tests/portability/test_pypy_nesting.py) (`test_G051_*`). It needs a PyPy interpreter, which CI does not have, so it is skipped
  unless `NOVA_PYPY` names one: `NOVA_PYPY=$(uv python find pypy@3.10) python3 -m unittest tests.portability.test_pypy_nesting -v`. It passes while PyPy crashes and fails the day it gives the named
  error.

## G-052 A float literal that overflows is silently infinity - TRAP (minor)
- **Found:** 2026-11-14, writing the constants section of the bytecode specification ([`spec/17-bytecode.md`](spec/17-bytecode.md) `[bc.constants]`, finding F3 of [`design/m12-bytecode-notes.md`](design/m12-bytecode-notes.md)):
  a constant pool can hold `inf`, and no source can make a NaN constant, which led to asking what *can* make an infinite one.
- **Tried:** `print(1` followed by 400 zeros and `.0)` prints `inf`; two such literals subtracted print `nan`. The same on the VM, the tree-walker and the self-hosted interpreter.
- **Why it matters:** [`spec/06-portability.md`](spec/06-portability.md) `[port.floats]` says an overflowing float *result* is infinity, not an error, so a literal that overflows
  follows the same rule; but integers that are too large are an error ("never a wrong answer ... or infinity"), so a long literal that is a whole number with a `.0` behaves
  differently from the same digits without it. It is a literal nobody writes on purpose, and `inf` is not otherwise reachable from source.
- **Decided (owner, 2026-11-14):** the bytecode format accepts positive infinity as a float constant so every program that compiles can be written; whether the lexer should refuse
  such a literal is decided in M13 with the number-formatting and decimal work (G-008, G-044).
- **Probe:** [`tests/portability/test_float_literal.py`](../tests/portability/test_float_literal.py): the three engines print `inf` and `nan`; it fails the day that changes.
