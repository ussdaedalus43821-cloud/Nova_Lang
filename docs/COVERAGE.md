# Measuring NovaLang coverage

The coverage runner measures Python statements and branches while running the
existing regression suite in a temporary source copy. It keeps the language
runtime's dependencies unchanged.

## Run

Use a Python environment with the full suite's NumPy dependency, plus Node.js
and Git on the executable path. The baseline uses Python 3.12.14 and coverage.py
7.6.1.

```sh
python3 -m pip install 'coverage==7.6.1'
python3 tests/run_coverage.py --output coverage-output
```

An isolated coverage installation can be supplied with `--coverage-path PATH`.
The output directory must be empty to avoid mixing old and new measurements.
Repeat `--station NAME` to measure selected stations instead of the complete
suite. A selected run must not be described as full-suite coverage.

## What is recorded

- `suite.log`: the suite output and final success/failure summary.
- `checks.jsonl`: the existing test runner's individual check results.
- `run.json`: environment, tool version, process-record count, station contexts,
  duration and test exit status.
- `source-manifest.json`: hashes identifying the scratch input.
- `.coverage` and `raw/`: merged data and the individual Python process records.
- `coverage.json`, `coverage.txt`, `html/index.html`: complete Python results,
  missed lines, missed branches and annotated source.
- `station-NAME.json`: coverage attributable to an individual test station.

Detailed JSON, annotated HTML, raw process records and merged databases under
`docs/audit/` are retained locally and ignored by Git. Human-readable summaries,
environment metadata and test logs remain available for version control. Generate
the detailed views with the commands above when they are absent from a checkout.

Python subprocesses inherit an invocation-scoped startup hook and write separate
data files. Those files are merged before reporting. No global Python startup
files are modified. Station labels are propagated to child processes as well
as assigned to the parent test process. This follows coverage.py's
[subprocess measurement mechanism](https://coverage.readthedocs.io/en/5.5/subprocess.html).

Scratch paths are mapped back to the working source. All Python input files
are explicitly included in the report, including files with no recorded
execution. This avoids excluding untouched tools or directories without
`__init__.py` from the denominator.

## Interpret the results

The primary implementation scope is `novalang.py`, `bootstrap.py`, and all
Python files directly under `tools/`. Tests and Python examples are reported
separately from that scope. A whole-repository percentage includes test code,
interactive demos and the coverage runner itself, so it answers a different
question.

Statement coverage is executed statements divided by all executable statements.
Branch coverage is observed branch destinations divided by possible branch
destinations. Coverage.py's default percentage combines statements and branches;
it must not be labeled statement coverage.

Station percentages overlap and must not be added together. Module initialization
in the parent occurs before the first station and has an empty context; it is
included in the overall result.

These reports do not measure `.nova` source coverage or the VS Code extension's
JavaScript coverage. Executing the bootstrap interpreter exercises Python runtime
paths but does not establish which NovaLang-written source lines or branches
were executed. Killed or timed-out processes may not flush their records; always
inspect the suite exit status and failures alongside the percentages.

The baseline is evidence for choosing tests, not a release threshold. Missing
error-handling paths, security boundaries and semantic edge cases should be
prioritized by risk as well as by their number of uncovered lines.
