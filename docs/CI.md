# Continuous integration

`.github/workflows/ci.yml` runs `tests/run_all.py`, the project's stop-the-line
suite, on GitHub Actions. This is milestone M7 in [`ROADMAP.md`](ROADMAP.md).

**Status of this workflow:** it has run on GitHub. The `fast` job passed on
three runs (80, 99 and 102 seconds for the test step, against 82 seconds for
the same tier locally), including the editor station finding `node` with no
install step. The first `full` matrix run (2026-11-07, merge `d49a4bb`, run
#5) passed on Linux for Python 3.7 through 3.13 and on macOS for 3.12, and
failed on both Windows rows for four portability reasons, listed under
[The first Windows run](#the-first-windows-run). A dispatched run of the fixes
(run #7, 2026-11-07, `d9c2de5`) passed every required row, and on Windows 3.12
none of the four recurred and all 300 generated-program comparisons passed.
It also showed a mistake in the new `portability` station (a POSIX-path test
that ran the real functions on Windows), fixed since, and that the Windows
Python 3.7 process dies at the start of the generated-program comparisons,
before recording seven checks. A single-row dispatch with `PYTHONFAULTHANDLER`
set found the cause: a native stack overflow, described under
[Windows Python 3.7: stack overflow](#windows-python-37-stack-overflow).

## What runs

| Job | When | What | Blocks a merge |
| --- | --- | --- | --- |
| `fast` | every pull request; pushes to the default branch; on demand | `run_all.py --quick` on Linux, Python 3.12 (80-102 s across three runs on GitHub) | Yes, once branch protection is set (below) |
| `full` | pushes to the default branch; weekly (Mondays 05:17 UTC); on demand | the whole suite across the matrix | The required rows, after merge |

`--quick` skips only the two slow bootstrap-parity stations (4 and 5). Everything
else runs, including the differential station that holds the VM to the
tree-walker.

A manual dispatch can narrow the `full` job instead of running all ten rows:
the `rows` input takes `os/python` pairs (for example `windows-latest/3.7`) and
`station` takes one `run_all.py` station name (for example `differential`).
Both empty is the whole matrix. The matrix itself is defined in the `plan` job
of the workflow; inputs reach its script through the environment, and an
unknown row or malformed station name fails the plan rather than running
something unintended.

Each job uploads `checks.jsonl` (one JSON line per completed check) as an
artifact, so a failure can be read without re-running.

## Required rows and probes

The `full` matrix has two kinds of row, set by `probe` in the workflow.

- **Required** rows are combinations the suite has been seen passing on. A
  failure fails the workflow run. The `full` job runs after a merge, so a red
  required row marks the default branch red; it blocks nothing, and nothing
  can block a merge until branch protection is set (below).
- **Probes** report but cannot fail the workflow. They are for combinations the
  suite has not yet been seen passing on. Today that is Windows only.

Evidence for the README's "Python 3.7+", as of 2026-11-07:

| Evidence | Result |
| --- | --- |
| Every `.py` file parses under the 3.7, 3.8 and 3.9 grammars (`ast.parse(feature_version=...)`) | pass, 39 files |
| `vermin` minimum-version analysis of the standard-library use | 3.7 |
| Full suite, Linux (ubuntu-22.04), Python 3.7, 3.8, 3.9 and 3.10 | pass, on GitHub |
| Full suite, Linux (ubuntu-24.04), Python 3.11, 3.12 and 3.13 | pass, on GitHub (and locally, 1,919 checks) |
| Full suite, macOS, Python 3.12 | pass, on GitHub |
| Full suite, Windows, Python 3.7 and 3.12 | fail, the same 8 checks on both: a platform problem, not a version one |
| Full suite, Python 3.9.6, macOS | reported passing by the author of the verification work; not reproduced here |

What this supports: Python 3.7 and later on Linux, and 3.12 on macOS. It does
not yet support any claim about Windows, or about 3.7 anywhere but Linux.

**Reading a failed probe.** First decide which of two things failed, because
only one of them says anything about the supported versions:

- **The code does not support that version** (a syntax error, a missing
  standard-library function, a failing check on that interpreter). This is a
  real signal about the floor.
- **The runner or action setup failed** (no build of that Python for that
  image, a dependency that will not install there, a setup step that errors
  before any test runs). This is workflow plumbing: fix the workflow or move
  the row to an image that has the version. It says nothing about the floor,
  and the `checks.jsonl` artifact will be missing or empty.

The test step's own output separates them: a row whose `Full suite` step never
started, or whose artifact has no checks, is plumbing.

**Promoting a probe.** When a probe row passes, change its `probe` to `false`
in the same pull request that records the result here. The Linux and macOS
rows were promoted this way after run #5. **If a probe fails for
the first reason and the fix is not worth making,** raise the minimum stated
in `README.md` to the oldest version that passes, rather than leaving the claim
and the evidence apart. The second kind of failure never justifies changing
the stated minimum. Either way the README and this table must end up agreeing
with the required rows; that is an exit criterion of M7.

## The first Windows run

Both Windows rows failed in their `Full suite` step (which did start, so this
is a result and not plumbing), with the same 8 checks on Python 3.7 and 3.12.
The 8 are 5 + 1 + 1 + 1; the four formatter cases are subtests inside one
check.

| Failing check | Cause | Kind | Change |
| --- | --- | --- | --- |
| `lsp: definition of ...` (5 checks) | `path_to_uri` built `"file://"` + `pathname2url(path)`, which is `file://///C:/...` on Windows; the test helper built `file://C:\...` | product bug (server) and test bug | `Path.as_uri()` in both; the output is byte-identical on POSIX |
| `pkg: ... circular import, naming packages` | the self-hosted `module_label` looked for `/.nova_modules/` only, so a Windows path fell through to a module-name check that rejects it; the host uses `os.sep` | product bug (`novalang.nova`) | separators follow `platform()`, mirroring the host |
| `malformed input regressions pass` (4 subtests) | `nova-fmt --write` wrote in text mode, which is CRLF on Windows: `b'let next_value = 2\r\n' != b'let next_value = 2\n'`. Not permission bits; the test never changes permissions | product behavior: the same file formatted to different bytes per platform | writes LF everywhere |
| `vm: test_generated raised AttributeError` | `tests/vm/differential.py` used `signal.SIGALRM`, which Windows does not have | test-harness bug | a thread-based deadline where `SIGALRM` is missing |

Windows recorded 1,918 checks against Linux's 1,919. Diffing the two label
sets shows the difference is exactly the two generated-program checks, replaced
by the one failure above, and that no station aborted: every other check ran.
That means Windows has never executed the 300 generated-program comparisons, so
the next run may show differences between the engines there.

`tests/portability` (the `portability` station) pins all four on every
platform by simulating the Windows condition: a patched `platform.system()`, a
forced non-`SIGALRM` time limit, a text mode that translates newlines, and
pathlib's pure Windows paths. Run against the previous source it fails as the
Windows run did.

## Windows Python 3.7: stack overflow

The first Windows 3.7 run ended with exit code 1 and no output, which looked
like a watchdog rather than a crash. Re-running that one row with
`PYTHONFAULTHANDLER=1` (run #10, single-row dispatch) printed
`Windows fatal exception: stack overflow` and the Python stack: the
tree-walker, repeating `visit_CallNode`, `call_value`, `execute_block`,
`visit_ReturnNode`, `visit_BinOpNode` and `evaluate` (about nine Python frames
per NovaLang call). The same step reported exit code 127 once it ran under
`bash`, and 1 under PowerShell before: the shell's number for a killed process
is not evidence about the cause.

What is known:

- 16 of the 300 generated programs recurse until the call-depth limit
  (`MAX_CALL_DEPTH`, 1200). Each level costs about nine Python frames, so the
  tree-walker needs on the order of 10,000 nested Python calls to produce the
  friendly "call depth of 1200 exceeded" error.
- Before Python 3.11, a Python-to-Python call also uses native stack. The
  limit in `novalang.py` (`sys.setrecursionlimit(20000)`) was chosen
  empirically on POSIX; Windows' stack is far smaller than Linux's 8 MB, and
  that is the combination that overflows. Python 3.12 on Windows does not.
- The default engine is the VM, which keeps NovaLang calls on its own stack, so
  this affects `--tree-walk` and `Interpreter("tree")`. The tree-walker is the
  reference the differential tests compare against.

What is not known: the exact seed (the dump shows only the innermost 100
frames), whether Windows 3.8 to 3.10 are also affected (no such rows exist; the
scope below assumes they are), and whether the checks after the crash pass.

### The decision: skip, visibly, where the tree-walker cannot run them

Three remedies were weighed (a larger-stack thread, a lower depth limit for the
tree-walker, or documenting and exempting). The third was chosen because the
other two change behavior to fix a test problem. `tests/vm/test_differential.py`
now does this, and only this:

- **Scope:** `tree_walker_stack_limited()` is true only when
  `sys.platform == "win32"` and Python is older than 3.11. Linux, macOS and
  Windows with 3.11 or later run exactly the comparisons they ran before, with
  the same check labels.
- **How a program is chosen:** on a limited platform the VM runs each generated
  program first (it keeps NovaLang calls on its own stack, so it cannot
  overflow). A program that ends in `call depth of 1200 exceeded` with exit
  status 1 is not given to the tree-walker. Nothing is detected by trying the
  tree-walker, because a native overflow cannot be caught.
- **Coverage:** 16 of the 300 seeds (31, 32, 38, 39, 41, 54, 56, 65, 92, 109,
  150, 193, 259, 262, 267, 290) end in that error on both engines; the next
  deepest program reaches 135 calls. So **284 of 300 generated programs are
  compared on both engines** on those platforms, and 16 are decided on the VM
  alone. The other platforms compare all 300.
- **Visible:** the station prints a `SKIPPED:` line with the count, the seeds and
  the coverage (`Compared on both engines: 284/300`) and records two checks:
  the skip itself, with its counts, and `284 of 300 generated programs run the
  same on both engines`. A Windows row on Python 3.10 or older therefore records
  one more check than the others.
- **Capped:** the skip check fails if more than a tenth of the programs are
  skipped, so it cannot grow into hiding the comparison.
- **Tested everywhere:** `tests/portability` forces the limited path on any
  platform and checks the scope, that the tree-walker never receives a skipped
  program, the printed line, the labels, the unchanged behavior elsewhere and
  the cap.

What this does not do: it does not make `--tree-walk` safe on deep recursion on
Windows with older Pythons. A user program that recurses to the limit there
still kills the process; the larger-stack thread remains the fix for that, and
is a separate decision. The Windows rows stay probes.

## Reproducing a job locally

```sh
python3 -m pip install numpy          # the examples station needs it
python3 -u tests/run_all.py --quick   # the fast job
python3 -u tests/run_all.py           # one cell of the full matrix
```

Node.js (any recent version, only the `node` binary) and Git must be on the
path; the editor and packages stations use them. A single station can be run
with `--station NAME` (see the list at the top of `tests/run_all.py`). The
`PYTHONUTF8=1` environment the workflow sets keeps console encoding from
being the thing that fails on Windows; the interpreter itself opens source
files as UTF-8 explicitly.

## Branch protection

A workflow can report a failure; only repository settings can make it block.
This cannot be set from the repository's files, so it is a one-time manual
step for a repository admin:

1. Settings, Branches, add a rule for the default branch.
2. Require status checks to pass before merging, and select **`fast`**
   (the job's name under the `CI` workflow).
3. Require branches to be up to date before merging.

Do not select `full` rows: they run after merge, and probes are not meant to
block.

Keep `fast` a single job. If it ever becomes a matrix, GitHub names each
check `fast (3.12)` and the required name `fast` silently stops matching,
leaving pull requests ungated with no error. After saving the rule, reload a
pull request: the merge box should list `fast` as required.

The repository's default branch is currently `claude/novalang-repl-math-5ihjqq`.
The workflow does not depend on the name (it compares against the repository's
configured default), but a name like `main` would be less surprising, and
renaming it in Settings is safe for the workflow.

## Line endings

A Windows checkout may convert line endings. This was tested rather than
assumed: with every text file in the repository converted to CRLF, the
formatter, linter, line-break, type-checker, package and compiler stations
(1,617 checks) all pass, so no `.gitattributes` is needed for them. Stations
not in that experiment (parity, differential, CLI, REPL) are what the Windows
probe rows are for. Writing is a separate matter from reading: `nova-fmt --write`
now writes LF on every platform, because text mode wrote CRLF on Windows.

## Pinned actions

Every action is pinned to a commit SHA with its tag in a comment, so a moved
tag cannot change what runs. `.github/dependabot.yml` proposes updates weekly.
Review an update's changelog before merging it; the pinned versions' inputs
were read from their `action.yml` when this was written.

## Not covered here

- Godot: the GDScript port of the VM lives in `Reactor-Game` and is checked by
  a headless-Godot job there (milestone M8).
- Coverage thresholds as a gate: coverage is evidence for choosing tests, not a
  release threshold (see [`COVERAGE.md`](COVERAGE.md)).
- The REPL's known gaps (a `{` inside a quoted string in a draft, `help`,
  Ctrl-C), the remaining M7 items.
