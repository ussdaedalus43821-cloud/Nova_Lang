# Continuous integration

`.github/workflows/ci.yml` runs `tests/run_all.py`, the project's stop-the-line
suite, on GitHub Actions. This is milestone M7 in [`ROADMAP.md`](ROADMAP.md).

**Status of this workflow:** it has been validated against GitHub's workflow
schema and every step has been reproduced locally, but it had not yet run on
GitHub when it was written. Expect the first run to turn up something. Fix it
the way any failing check is fixed: in the workflow or the code, not by
loosening the check.

## What runs

| Job | When | What | Blocks a merge |
| --- | --- | --- | --- |
| `fast` | every pull request; pushes to the default branch; on demand | `run_all.py --quick` on Linux, Python 3.12 (about 1.5 minutes) | Yes, once branch protection is set (below) |
| `full` | pushes to the default branch; weekly (Mondays 05:17 UTC); on demand | the whole suite across the matrix | The required rows, after merge |

`--quick` skips only the two slow bootstrap-parity stations (4 and 5). Everything
else runs, including the differential station that holds the VM to the
tree-walker.

Each job uploads `checks.jsonl` (one JSON line per completed check) as an
artifact, so a failure can be read without re-running.

## Required rows and probes

The `full` matrix has two kinds of row, set by `probe` in the workflow.

- **Required** rows are combinations the suite has been seen passing on. A
  failure fails the workflow.
- **Probes** report but cannot fail the workflow. They exist because the
  README says "Python 3.7+" and nothing has run the suite on 3.7, 3.8 or any
  non-Linux platform.

Python 3.7 evidence so far, as of 2026-11-07:

| Evidence | Result |
| --- | --- |
| Every `.py` file parses under the 3.7, 3.8 and 3.9 grammars (`ast.parse(feature_version=...)`) | pass, 39 files |
| `vermin` minimum-version analysis of the standard-library use | 3.7 |
| Full suite, Python 3.13, Linux | pass, 1,919 checks |
| Quick tier, Python 3.11 and 3.12, Linux, NumPy installed | pass, 1,846 checks each |
| Full suite, Python 3.11 and 3.12, Linux, NumPy installed | pass, 1,919 checks each |
| Full suite, Python 3.9.6, macOS | reported passing by the author of the verification work; not reproduced here |
| Any run on 3.7, 3.8, 3.10, macOS or Windows | none yet; these are the probes |

The static checks make 3.7 plausible, and only a run proves it.

**Promoting a probe.** When a probe row passes, change its `probe` to `false`
in the same pull request that records the result here. **If a probe fails and
the fix is not worth making,** raise the minimum stated in `README.md` to the
oldest version that passes, rather than leaving the claim and the evidence
apart. Either way the README and this table must end up agreeing with the
required rows; that is an exit criterion of M7.

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
probe rows are for.

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
