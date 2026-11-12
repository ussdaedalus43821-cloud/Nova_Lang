# Contributing to NovaLang

NovaLang is a hand-written, tree-walking interpreted language, built up
one stage at a time. This document is for anyone extending the language,
its standard library, or its embedding API. It describes the constraints
the codebase holds itself to, not just style preferences — several of them
are load-bearing.

## Architecture

Every piece of NovaLang follows the same pipeline, in both
implementations (`novalang.py`, the Python host, and `novalang.nova`, the
self-hosted one written in NovaLang itself):

```
source text  ->  Lexer       ->  tokens
tokens       ->  Parser      ->  AST (Abstract Syntax Tree)
AST          ->  Interpreter ->  a value
```

A new piece of syntax touches all three stages in order: teach the
**Lexer** to produce whatever new token(s) it needs, teach the **Parser**
to turn those tokens into a new AST node (or a new case on an existing
one), then teach the **Interpreter** to evaluate that node. Resist the
urge to special-case things later in the pipeline that belong earlier —
e.g. a new keyword belongs in the Lexer's keyword table, not sniffed out
of an identifier string in the Parser.

## Hard constraints

These aren't style preferences — they're the properties that make
NovaLang what it is, and a change that breaks one needs a real reason and
a note explaining why, not a quiet workaround.

- **No `eval()`, no `exec()`, no parser generators, no regular expressions
  in the core pipeline.** The Lexer, Parser, and Interpreter are all
  hand-written. (The `regex()` *standard library function* is fine — it's
  a NovaLang program using Python's `re` module deliberately, not the
  interpreter using regexes to parse NovaLang itself.)
- **Host/self-hosted parity.** Any behavior implemented in `novalang.py`
  must also work identically through `novalang.py --bootstrap` (i.e. as
  implemented by `novalang.nova`). If you add a built-in or a language
  feature to one, add it to the other in the same change, and verify with
  a diff:

  ```bash
  python3 novalang.py your_test.nova > /tmp/direct.txt
  python3 novalang.py --bootstrap your_test.nova > /tmp/bootstrap.txt
  diff /tmp/direct.txt /tmp/bootstrap.txt
  ```

  A feature that only exists on one side is a bug, not a partial
  implementation to finish later.
- **The scope barrier.** A plain variable assignment inside a function can
  never reach an enclosing function's locals — only the *contents* of a
  shared mutable container (a list or dict passed in, or a global) can
  carry state across calls. This is core to how NovaLang programs — and
  `novalang.nova` itself — track state across calls (the `state = {...}`
  accumulator pattern used throughout the examples and tests). Don't
  "fix" this without recognizing it's a deliberate design choice, not an
  oversight.
- **`isinstance(x, dict)`, not exact-type checks**, in the core
  interpreter's member/index-access paths. This is what lets
  `PythonObjectProxy` (a `dict` subclass that proxies a live Python
  object) work transparently as a NovaLang dictionary with zero changes
  to the interpreter itself. An exact-type check anywhere in that path
  would silently break the embedding API.
- **`python.*` stays a curated bridge, not open process access.** `
  python.import()`'s allowlist and the explicit `expose()`/
  `expose_module()`/`expose_global()` registration model are a deliberate
  narrowing of what a script can reach (not a security boundary, ADR 0003), and `python.*` is off unless `--allow-python` or
  `Nova(allow_python=True)` asks for it. Every access goes through
  `bridge_lookup` (names starting with `_` and ungranted modules are
  hidden); do not add a path around it. The reachability test in
  `tests/embedding/test_python_bridge.py` must keep passing on every Python
  in the matrix (see `README.md`'s Security section and
  `CHANGELOG.md`'s `[0.12.0]` entry). Don't widen what a NovaLang script
  can reach by default; if a use case needs more, that's what
  `expose_module()` is for — from the *embedding* Python program, not
  from inside the sandbox.

## Error conventions

Runtime errors are `NovaError(message, position, label=...)`. Reuse an
existing label where it fits (`TypeError`, `AssertionError`,
`FileNotFoundError`, `FileError`, `ImportError`, `PythonError`); introduce
a new one only when none of the existing labels actually describes the
failure. On the Python embedding side, every `Nova`/`CompiledScript`
method wraps `NovaError` as `NovaLangError` before it reaches calling
code — never let a raw `NovaError` (or an unrelated Python exception)
escape across that boundary.

## Adding a standard library function

1. Implement it as a `BuiltinFunction` in `novalang.py` (set
   `needs_interpreter=True` only if it needs to call back into NovaLang
   values, as `map`/`filter`/`reduce`/the `python.*` builtins do).
2. Add the matching case in `novalang.nova`'s builtin dispatch
   (`call_builtin`) — usually a one-line delegation to the host, since
   `novalang.nova` runs *under* `novalang.py` and can call straight
   through to it.
3. Document it in the REPL's `HELP` text in `novalang.py`, and in
   `README.md`'s standard library table.
4. Add at least one check to `examples/stdlib_full_test.nova` (the
   `check(label, actual, expected)` / `check_true(label, actual)` pattern
   used throughout that file) so it's covered by the regression suite
   going forward.

## Before you send a change

- **Run the whole suite.** `python3 tests/run_all.py` runs every station
  (conformance, differential VM-against-tree-walker, security matrix, formatter,
  linter, type checker, embedding, and the rest). At v2.2.0 that is **1,951
  checks**, and all of them must pass. `--quick` skips the slow self-hosted
  runs and is the tier pull requests are gated on.
- **CI.** Every pull request runs the `fast` job (the `--quick` tier on Linux
  and Windows). `fast` is the required check, so a pull request cannot merge
  while it is red. The `full` job runs the whole suite across the Python and
  operating-system matrix on pushes to the default branch, weekly, and on
  demand. [`docs/CI.md`](docs/CI.md) says what each job means.
- **Stop the line.** A failing check stops the work. It is not skipped,
  quarantined, loosened or "fixed later": `tests/run_all.py` is the Andon cord
  and exits 1 on any failure, and a failing check blocks the
  milestone. If a test is wrong, fix the test in the same change and say why;
  if the code is wrong, fix the code. A bug fix starts with a check that fails
  without it. Numbers in documents come with the command that reproduces them.

## Testing a change

NovaLang tests itself with `.nova` scripts. `python3 tests/run_all.py`
runs the whole line: the formatter and linter golden files under
`tests/`, the formatter's self-checks on every `.nova` file, and the
direct-vs-`--bootstrap` comparison below for every example, both on the
repo as it is and on a fully formatted copy of it, and every runnable
Python program under `examples/`, including both embedding-template test
suites (`--quick` skips the slow bootstrap runs). A new `.py` file under
`examples/` must be added to `PYTHON_PROGRAMS` or `PYTHON_EXEMPT` in
`tests/run_all.py`, or the line stops. The type checker has its own
station: if you change an operator, a built-in or a scope rule in
`novalang.py`, `tests/typecheck/crosscheck.py` will tell you whether
`tools/nova-typecheck.py` still agrees with it. Package resolution lives
in `novalang.py` (`resolve_package`) and `novalang.nova`, which must keep
matching; station 8 runs every package scenario on both engines. If you
add a keyword or a built-in, add it to
`editors/vscode/syntaxes/novalang.tmLanguage.json` too: station 9's drift
guard fails until the grammar knows every word the language does. Run
`python3 novalang.py --check` (and `--typecheck`, if it has annotations)
on any `.nova` file you touch. Programs run on the bytecode VM, with the
tree-walker (`--tree-walk`) kept as the reference. If you change what an
operation does, change the shared function in `novalang.py` that both
engines call, not either engine. Station 11 compares the engines on
everything, and `NOVA_DIFF_SEEDS=5000 python3 tests/vm/test_differential.py`
runs a longer soak of random programs. Before sending a change:

- Run every file under `examples/` both directly and with `--bootstrap`;
  outputs must match byte-for-byte (`examples/self_host_test.nova` is
  built specifically for this comparison).
- Run `examples/stdlib_full_test.nova` both ways; it must print exactly
  `All standard library tests passed.`
- If you touched the embedding API, `tests/run_all.py` already runs
  `examples/embedding_demo.py`, `examples/reactor_sim_integration.py` and
  `examples/daedalus_integration.py`, but it only checks that they exit
  0. Read their output to confirm it still matches what they claim to do.
- Add a new `examples/*.nova` file (or extend an existing one) for any
  new language feature or built-in, rather than only testing it by hand
  at the REPL.

## The specification and the conformance corpus

[`docs/spec/`](docs/spec/README.md) is the normative statement of the language
([ADR 0001](docs/decisions/0001-specification-is-normative.md)) and
[`tests/conformance/`](tests/conformance/README.md) is its host-neutral test
corpus. A change to what a program means, prints or reports as an error changes
the spec section that describes it and the cases that cite it, in the same pull
request; a new section needs a case, and the `conformance` station fails
otherwise. If an engine disagrees with the text and you are not fixing it now,
record it in `docs/spec/DIVERGENCES.md` with a case; do not loosen the case.

## Continuous integration

Pull requests run the quick tier of the suite on GitHub Actions; see
[`docs/CI.md`](docs/CI.md) for what runs, how to reproduce it locally, and how
a matrix row moves from probe to required. A red check is fixed, not skipped.

## Milestones

Larger changes are planned as numbered milestones in
[`docs/ROADMAP.md`](docs/ROADMAP.md). A milestone gets its own branch and a
pull request titled `Mn: <title>`, a test station that fails without the work,
a `### Mn:` changelog section, and an updated `DEVELOPMENT_STATUS.md`. A
decision that changes the language's direction is written up in
[`docs/decisions/`](docs/decisions/README.md) before work depends on it.

## Style

- No comments explaining *what* code does — name things so the code reads
  on its own. A comment earns its place only by explaining a *why* that
  isn't obvious from the code (a workaround, an invariant, a deliberate
  departure from what looks like the obvious approach).
- Keep changes minimal and scoped: a new built-in doesn't need a new
  abstraction layer if the existing `BuiltinFunction` pattern fits; a bug
  fix doesn't need surrounding refactoring.
- Match the existing docstring/comment voice in `novalang.py` and
  `novalang.nova` — plain, second-person-free, explaining the *design*
  rather than narrating the diff that produced it.
