# Security tests (M11)

```
python3 -m unittest discover -s tests/security   the capability, path, limit, determinism, runner and command-line tests
python3 tests/security/matrix.py            the coverage matrix: which cell is proved on which engine
python3 tests/security/matrix.py --strict   fail while any cell is pending (M11's exit criterion; the station runs it)
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
