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
  security boundary (see `README.md`'s Security section and
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

## Testing a change

There's no separate test framework — NovaLang tests itself with `.nova`
scripts and shell-level diffing. Before sending a change:

- Run every file under `examples/` both directly and with `--bootstrap`;
  outputs must match byte-for-byte (`examples/self_host_test.nova` is
  built specifically for this comparison).
- Run `examples/stdlib_full_test.nova` both ways; it must print exactly
  `All standard library tests passed.`
- If you touched the embedding API, run `examples/embedding_demo.py`,
  `examples/reactor_sim_integration.py`, and
  `examples/daedalus_integration.py` and confirm their output still
  matches what they claim to do.
- Add a new `examples/*.nova` file (or extend an existing one) for any
  new language feature or built-in, rather than only testing it by hand
  at the REPL.

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
