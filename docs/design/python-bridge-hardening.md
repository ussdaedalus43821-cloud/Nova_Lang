# Design: closing the `python.*` bridge escapes (issue 1)

Status: **Design approved by the owner on 2026-11-08; nothing in this
document is implemented yet.** Implementation follows the issue 3 change, on
its own branch.

Issue 1 reports that `python.get()` can reach Python's `builtins` and so run
arbitrary code, contradicting the README's description of `python.*` as a
"deliberate, narrow bridge". The issue text is a bug report from outside the
code base; this design rests on what the code does and on the checks below,
which were run against `63605ef`, not on the report.

## Decisions already made

1. **`python` is off by default everywhere.** Standalone runs need an
   explicit `--allow-python` flag. An embedding host needs
   `Nova(allow_python=True)` (this was open question O1; the owner chose
   option A). A minor-version bump (2.1.0) is accepted.
2. **A script cannot write what it cannot read.** Names that start with `_`
   are blocked for assignment through `PythonObjectProxy` as well as for reads.
3. **Module objects stay proxies.** They are never converted into recursive
   dictionaries.

## What the code does today (verified)

| Cause | Where | Check |
| --- | --- | --- |
| `resolve_python_path` walks every dotted component with `hasattr` and `getattr` and rejects none, so `json.__builtins__` resolves. `python.get`, `call` and `set` all use it. | `novalang.py` `resolve_python_path` | The report's payload reads `eval` out of `builtins`. |
| `PythonObjectProxy.__contains__`, `__getitem__` and `__setitem__` use `hasattr`, `getattr` and `setattr` with no filter. Only `_visible_keys()` (iteration, `keys()`) hides `_` names. | `PythonObjectProxy` | `reactor["_secret"]` reads and writes private state of an object given to `expose_global`. |
| `python` is defined for every `Interpreter`, standalone runs included. | `Interpreter.__init__` defines `python` from `PYTHON_NAMESPACE` | The README says the namespace exists only inside an embedding program. `novalang.nova` also binds its own `python` global, delegating to the host's. |
| Printing a module proxy recurses until the stack runs out. | `format_value` on a `PythonObjectProxy` | `python.get("statistics.sys")` has `type() == "dict"`, `keys()` works, `print()` fails with "ran out of stack". The recursion is in the display, not in a conversion to a dict. |

**Finding that changes the fix:** blocking `_` names would not close the hole.
Several allowlisted modules expose other modules under **public** names, and
those reach `builtins` and `sys`:

```
re.enum.bltns            -> builtins      (read eval out of it: 6 * 7 = 42)
json.codecs.builtins     -> builtins      (read eval out of it: 6 * 7 = 42)
statistics.sys           -> sys           (sys.modules reaches every imported module)
json.codecs.sys, re.enum.sys, collections.abc.sys -> sys
```

Both `eval` routes above were run on the current code with a harmless
expression. A breadth-first search over public names from the ten allowlisted
modules, three levels deep, finds eight routes to `builtins` or `sys`. The set
depends on the Python version, because module internals change between
releases.

## Design

### D1. One gate for every bridge access

A single function, used by `resolve_python_path`, `PythonObjectProxy` reads,
writes and membership, and `_visible_keys`, decides whether a name on an
object may be seen:

1. **A name that starts with `_` is never visible,** for reads, writes and
   calls, on every object. This covers `__builtins__`, `__class__`,
   `__globals__`, `__import__` and private state of exposed objects.
2. **An attribute whose value is a module is visible only if that module is
   granted:** its top-level name is on `PYTHON_IMPORT_ALLOWLIST` or was
   exposed by the embedder with `expose_module`. `collections.abc` is granted
   because `collections` is; `re.enum`, `json.codecs` and `statistics.sys`
   are not. A blocked module attribute behaves as if it did not exist
   ("`json` has no attribute `codecs`"), so the error does not confirm that it
   is there.
3. Everything else is visible as before, including functions, classes and
   constants of a granted module.

Reads and calls of a hidden name give the existing "has no attribute"
`PythonError`. A write to a `_` name gives `PythonError`: "cannot set private
attribute". `PythonObjectProxy.keys()`, `items()` and `values()` use the same
gate, so listing and direct access agree.

### D2. Module objects stay proxies, and printing one is shallow

A module is wrapped as a `PythonObjectProxy`, as today. Formatting any proxy
(`print`, `format_repr`, `json.dumps`, string conversion) writes its
`__repr__`, `<python object module>`, and does not iterate its attributes.
Granted modules can still reference each other in a cycle, so shallow
formatting is needed even after D1. `to_python_value` already unwraps a proxy
to its target, so that direction is unchanged.

### D3. `python` is off unless asked for

- `Interpreter` takes `allow_python`, default `False`. When it is false, the
  `python` global is a stub whose members raise `PythonError`: "python.* is
  disabled; run with --allow-python, or create the host with
  allow_python=True". A stub gives a clear message where an undefined name
  would not, and grants no capability.
- `novalang.py --allow-python` sets it for a file, the REPL and code on the
  command line. `--bootstrap` passes the flag through, and `novalang.nova`
  binds its own `python` global only when the host's is enabled.
- `Nova(engine=None, allow_python=False)` is the embedding switch: a host
  that wants `python.import`, `python.call`, `python.get` and `python.set`
  passes `allow_python=True`.
- `expose_global` is unaffected: it binds an object directly and does not need
  `python`. D1 still applies to the proxy it creates.

### D4. Tests

Each lands in the stations that already exist (`cli`, `embedding`,
`portability` if platform-sensitive), and each fails against the current
source:

- Every payload in the report, run through the CLI on the VM, the
  tree-walker and both under `--bootstrap`: each ends in a `PythonError`, none
  runs code, none leaves `/tmp/novalang-poc` behind.
- The two public routes and `statistics.sys`.
- Proxy reads, writes and membership of `_secret`, `__class__` and
  `__dict__` on an object from `expose_global`.
- **A reachability test:** from each allowlisted module, walk every path the
  gate allows to a depth of four, and fail if any step reaches a module that
  is not granted, or any of `eval`, `exec`, `compile`, `open`, `__import__`,
  `getattr` or `setattr`, found by identity. It runs in the CI matrix, so each
  Python version from 3.7 to 3.13 checks its own module internals. This is the
  test that guards against the next release adding a public alias.
- `print()` of a module proxy returns instead of exhausting the stack.
- Standalone `python` is the disabled stub; `--allow-python` and
  `allow_python=True` restore it, and the existing embedding tests pass with
  the flag.

### D5. Compatibility

This is a deliberate breaking change for embedders: scripts that read or write
`_`-prefixed attributes of exposed objects, or that walk to modules through a
module attribute, stop working, and every host that uses `python.*` must pass
`allow_python=True`. It needs a changelog entry, a README correction, and a
minor version bump (2.1.0).

## What this does not do

- **It is not a sandbox.** It follows ADR 0003's second option: deny by
  default, grant explicitly, test every denial, and say that untrusted code
  still needs a separate process or container.
- A script can still read the string form of private state through
  `string.Formatter`, which formats attribute chains. That leaks text, not
  objects, and does not run code. It is a documented residual.
- Resource use by allowlisted modules (a regular expression that backtracks
  badly, a very large `random` draw) is not addressed.
- `sys.setrecursionlimit(20000)` at import, which the report raises for
  Pyodide's stack, is a separate issue.
- Nothing here has had an independent review.

## Decision record for the default

The choice for embedding hosts was between **A, off everywhere**, and **B, on
for `Nova()` and off for the command line**. The owner chose A on 2026-11-08.
It matches ADR 0003's deny-by-default and the issue reporter's own host, which
deletes `python` after every `Nova()`. Every existing embedder of `python.*`
breaks until it passes `allow_python=True`, which is why the change needs the
minor-version bump and a prominent changelog entry. The in-repo examples and
tests that use `python.*` are updated to pass it.
