# Security tests (M11)

```
python3 -m unittest discover -s tests/security   the capability, path, limit, determinism, runner and command-line tests
python3 tests/security/matrix.py            the coverage matrix: which cell is proved on which engine
python3 tests/security/matrix.py --strict   fail while any cell is pending (M11's exit criterion; the station runs it)
python3 tests/security/fuzz.py programs --seed 7 --count 2000   random hostile programs on the VM and the tree-walker
python3 tests/security/fuzz.py paths --seed 7 --count 3000      random file operations on random path spellings
python3 tests/run_all.py --station security-matrix
```

The matrix is derived from [`docs/spec/16-sandbox.md`](../../docs/spec/16-sandbox.md): a row of the capability
table gives a denial cell and a grant cell, a row of the limit table gives a trip cell (and an uncatchable cell
for a fatal limit), and a row of the path table gives a path cell, each needed on the bytecode VM, the
tree-walker and the self-hosted interpreter. The conformance cases (`tests/conformance/cases/sandbox-*.json`)
claim cells with their `matrix` field. A cell is **covered** when a case claims it and the engine follows the
specification there, **pending** when the case records a divergence (`docs/spec/DIVERGENCES.md`).

`pending.json` lists the cells that have no case yet and why. The station fails for a hole it does not explain
and for an excuse that is no longer needed, so neither can go unnoticed. Escape attempts that a JSON case cannot
express (a symbolic link, a case-insensitive file system) and the fuzzer are added here in slices 2 and 6.

What the station does not prove: that the specification is the right one. The threat model
(`docs/design/m11-threat-model.md`) and the independent review are for that.

## The escape corpus and the fuzzers (slice 6)

* `tests/conformance/cases/sandbox-escape.json` holds hostile programs (names that must stay undefined, every spelling of
  a path that leaves the grant, links, modules, fatal limits caught in every syntactic position, size evasion, parser and
  stack depth, the Python bridge) and runs on all three engines with the rest of the conformance corpus. `test_escape.py`
  runs the same programs on the two Python engines in a temporary tree and compares a snapshot of every file and link
  before and after: nothing outside the folders a case may write to may change, and the text of a file outside the grant
  may not reach the output. It also proves the check can see: with a path check that lets everything in, it fails.
* `fuzz.py` makes random programs and random file operations from a seed. A finding is a Python exception reaching the
  caller, a run that outlives its time limit, a change on disk outside the grant, outside content or the temporary folder's
  name in the output, or the two engines printing different things. `test_fuzz.py` runs a small fixed-seed budget on every run
  and also puts a hole back (a check that lets everything in, one that ignores links, the old `for` count that leaked
  `OverflowError`) and requires the fuzzer to report it. A fuzzer that has never found anything proves nothing.
* `matrix.py` also checks that every built-in function is either gated by a capability (`CAPABILITY_OF`) or listed as pure in
  `pure_builtins.json`, that every gated name is in the capability table of the specification, and that a sandbox case shows
  each gated name to be undefined without its capability. A new built-in that touches the machine cannot be added without
  someone deciding which it is.
* What the first runs found and fixed (the fuzzers were run on about 6,000 programs and 6,000 path operations before the merge): a
  `for` bound beyond the range of a float raised Python's `OverflowError`; the empty string or list repeated a huge number of
  times did too; two dictionaries merged with `+` could pass the dictionary limit (also on the self-hosted interpreter).

