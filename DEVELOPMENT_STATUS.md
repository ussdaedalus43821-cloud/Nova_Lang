# Nova development status

Baseline: NovaLang v2.0.1 (assignment fast paths and dispatch reorder).

## What the verification work added

The work after 2.0.1 closes gaps in how the language is verified, and fixes the
defects the new tests exposed. The full suite now records 1,921 parent checks;
all pass locally.

New stations (run one with `python3 tests/run_all.py --station NAME`):

| Station | Tests | Covers |
| --- | ---: | --- |
| `harness` | 8 | timeout rejection, report flushing, station selection, exit status, timezone-portable standard-library checks |
| `cli` | 34 | formatter, linter, disassembly and bootstrap command lines: modes, diagnostics, exit codes, batch continuation, malformed UTF-8 |
| `embedding` | 55 | callbacks into Python, value conversion, live-object reads and writes, host errors, import allowlist, bootstrap error-boundary parity |
| `repl` | 46 | multiline drafts, error recovery, EOF, session state, `help`, Ctrl-C, on both engines |
| `input-errors` | 6 | formatter refusal checks, malformed lockfiles, language-server framing |
| `portability` | 14 | Windows paths, file URIs, newlines, the time limit and the tree-walker skip, simulated on any platform |

The `cli`, `embedding`, `repl` and `input-errors` suites fail against the 2.0.1
source and pass with the fixes, which are listed under "Unreleased" in the
changelog.

Also changed: parity and differential checks reject timeouts (two engines
timing out used to compare equal), the standard-library example no longer
assumes a UTC epoch date, and `tests/run_coverage.py` measures statement and
branch coverage including Python subprocesses (see `docs/COVERAGE.md`).

## Roadmap

The milestones after M6 are in [`docs/ROADMAP.md`](docs/ROADMAP.md). The first,
M7, added continuous verification: the suite runs on GitHub across Linux, macOS
and Windows (see [`docs/CI.md`](docs/CI.md)), and a pull request needs the
`fast` check to merge. The next milestones are M8 (the GDScript VM) and M9 (the
language specification).

## Known gaps

- NovaLang-source and JavaScript (VS Code extension) coverage are not
  measured; Python coverage is.
- CI has shown the full suite passing on Linux for Python 3.7 through 3.13 and
  on macOS for 3.12 and Windows for 3.12. Windows failed its first run on four
  portability bugs, now fixed and pinned by the `portability` station. A later
  run confirmed the fixes on Windows 3.12, including the 300 generated-program
  comparisons (1,921 checks, none failing); on
  Windows 3.7 the tree-walker overflows the native stack on a program that
  reaches the 1200-call depth limit, and the process dies instead of printing
  the call-depth error. The VM, the default engine, is not involved. The
  generated comparisons skip those 16 programs there, visibly, and compare 284
  of 300 (see [`docs/CI.md`](docs/CI.md)).
