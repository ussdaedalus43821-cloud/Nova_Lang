# Embedding boundary regression tests

```sh
python3 -m unittest discover -s tests/embedding -v
python3 tests/run_all.py --station embedding
```

There are 26 shared contracts exercised independently on each engine, plus one
bootstrap parity test with VM/tree subcases: 53 unit tests. The full runner wraps
them in one parent check. Fixtures use host objects and the public `Nova` API;
the bootstrap test configures real interpreter instances with an exposed host
object before executing the actual self-hosted interpreter.

The contracts cover returned callbacks and closures, nested function containers,
primitive/tuple/dictionary/None conversions, copy-versus-live-object semantics,
exposed global functions and methods, registry call/get/set, nested callbacks,
host recovery from callback failures, callback state isolation and cleanup after
errors. Rejected reads and writes must become controlled errors, and a rejected
setter is attempted once. Explicit script/host control-flow exceptions remain
visible to the host.

Import checks verify that `os`, `subprocess` and an unknown module remain denied
without explicit exposure, while allowlisted `math` and a host-supplied dummy
module retain their existing behavior. The tests do not change the allowlist or
define a new object-access permission model.

The bootstrap parity test checks the same exposed-property rejection in direct
and self-hosted execution on both engines. It does not claim general support for
passing target-interpreter function dictionaries as Python callbacks under
bootstrap; that is separate from Python-hosted `Nova` function conversion.
