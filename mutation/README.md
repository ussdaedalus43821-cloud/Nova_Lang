# Mutation test

A mutation test plants one small deliberate bug (a "mutant") in the code, runs the tests, and asks whether a test failed. A mutant that no test notices
is a gap in the tests, not in the code. This folder is the tooling; the code under test is `novalang.py`, `novalang.nova` and `std/date.nova`.

| File | What it does |
| --- | --- |
| `generate.py` | Chooses the mutants: a seeded sample (`--seed`, `--total`), or **every** viable mutant of some areas (`--exhaustive sandbox,steps,nesting`). Areas: `sandbox`, `steps`, `nesting`, `parser`, `vm`, `date`. |
| `run_mutants.py` | Runs them against the quick tier (`tests/run_all.py --quick`), cheapest station first, in a scratch copy of the repository; the repository itself is never touched. `--confirm` counts a catch only if the failing station fails a second time. `--slice I/N` runs one share of the mutants, so several machines can split the work. Resumes where it stopped. |
| `report.py` | The score, the score per area, how mutants were caught, the survivors and the failures that did not repeat. `--markdown` for a job summary. |
| `time_stations.py` | Times each station of the quick tier on the unmutated code; `results/station_times.json` is that timing, used to order stations and to set each station's time limit. |

**A mutant is caught** when a test station fails on it (twice, with `--confirm`) or times out. Timeouts are reported apart: a loop that never ends is caught by
the clock. **A control** is a run of the unchanged code at the same load; it must pass, and the report lists every control.

## On this machine

    python3 mutation/generate.py --seed 20261117 --total 200          # the sample of 200
    python3 mutation/run_mutants.py --workers 4 --confirm
    python3 mutation/report.py

## In the cloud (GitHub Actions, free on a public repository)

Actions tab, **Mutation test**, Run workflow. The defaults run every mutant of the sandbox, step-limit and nesting code on 14 runners; the report is in the
job summary and in the `mutation-report` artifact. For a trial, set `only_slices` to `0` and `per_slice_limit` to `6`. A Free account has 20 runners for
everything at once, pull request checks included, so keep `max_parallel` at 14 or below.
