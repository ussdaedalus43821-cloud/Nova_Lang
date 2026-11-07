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
Python 3.7 process ends silently at the start of the generated-program
comparisons, before recording seven checks. The cause is not yet known;
`PYTHONFAULTHANDLER` is now set so that a native crash would print itself.

## What runs

| Job | When | What | Blocks a merge |
| --- | --- | --- | --- |
| `fast` | every pull request; pushes to the default branch; on demand | `run_all.py --quick` on Linux, Python 3.12 (80-102 s across three runs on GitHub) | Yes, once branch protection is set (below) |
| `full` | pushes to the default branch; weekly (Mondays 05:17 UTC); on demand | the whole suite across the matrix | The required rows, after merge |

`--quick` skips only the two slow bootstrap-parity stations (4 and 5). Everything
else runs, including the differential station that holds the VM to the
tree-walker.

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
