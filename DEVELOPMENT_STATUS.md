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
| `cli` | 32 | formatter, linter, disassembly and bootstrap command lines: modes, diagnostics, exit codes, batch continuation, malformed UTF-8 |
| `embedding` | 53 | callbacks into Python, value conversion, live-object reads and writes, host errors, import allowlist, bootstrap error-boundary parity |
| `repl` | 26 | multiline drafts, error recovery, EOF, session state, on both engines |
| `input-errors` | 6 | formatter refusal checks, malformed lockfiles, language-server framing |
| `portability` | 10 | Windows paths, file URIs, newlines and the time limit, simulated on any platform |

The `cli`, `embedding`, `repl` and `input-errors` suites fail against the 2.0.1
source and pass with the fixes, which are listed under "Unreleased" in the
changelog.

Also changed: parity and differential checks reject timeouts (two engines
timing out used to compare equal), the standard-library example no longer
assumes a UTC epoch date, and `tests/run_coverage.py` measures statement and
branch coverage including Python subprocesses (see `docs/COVERAGE.md`).

## Roadmap

The milestones after M6 are in [`docs/ROADMAP.md`](docs/ROADMAP.md). The first,
M7, adds continuous verification. A CI workflow is written (see
[`docs/CI.md`](docs/CI.md)) but has not yet run on GitHub, so every result above
was still produced by running the suite by hand.

## Known gaps

- The REPL's blank-line check looks for a raw `{` in the draft, so a brace
  inside a quoted string can affect whether an incomplete draft is submitted.
- The REPL `help` command and Ctrl-C handling have no transcript tests.
- NovaLang-source and JavaScript (VS Code extension) coverage are not
  measured; Python coverage is.
- CI has shown the full suite passing on Linux for Python 3.7 through 3.13 and
  on macOS for 3.12. Windows failed its first run on four portability bugs,
  now fixed and pinned by the `portability` station but not yet confirmed by a
  run (see [`docs/CI.md`](docs/CI.md)); the 300 generated-program comparisons
  have never run there.
