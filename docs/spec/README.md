# NovaLang language specification

Status: **first slice, draft.** Written 2026-11-08 for milestone M9. It covers
lexical rules, values, expressions, scoping, the error catalogue, the security
properties of the language and the rules a portable host must follow. Statements
beyond `let`, assignment, blocks, loops, functions and `try`/`catch`/`finally`,
the standard library, modules and the type annotations are still to come.

This specification is normative ([ADR 0001](../decisions/0001-specification-is-normative.md)):
where an implementation and this text disagree, one of them has a bug, and the
disagreement is written down in [`DIVERGENCES.md`](DIVERGENCES.md) until it is
resolved. `novalang.py` is the first conforming host, not the definition.

## Who this is written for

NovaLang is the foundation of a wider ecosystem ([`../ROADMAP.md`](../ROADMAP.md)):
the same language is meant to run on servers, in browsers (WebAssembly), on
phones and edge computers, on microcontrollers with a few hundred kilobytes of
memory, and eventually to compile itself. A specification that only describes
what `novalang.py` happens to do cannot serve those hosts, so this text is
written for someone implementing NovaLang on a platform that has not been
chosen yet, and two habits follow:

- **If a rule is ambiguous, it is written down and a case pins it**, even when the
  answer is whatever the first implementation did by accident (how a float
  prints, how a string compares). Where the accident is a Python-ism that a port
  would struggle with, the text says so and the question goes to the project
  owner; it is never left implicit.
- **What a smaller host may not do is stated** (`06-portability.md`): it may bound
  integers, depth and sizes, and must then refuse with an error, never wrap,
  truncate or crash.

## Reading this document

- **MUST**, **MUST NOT** and **MAY** have their usual meaning for a conforming
  host. A statement without one of those words describes the language.
- **Every section has an id** in square brackets in its heading, such as
  `[lex.numbers]`. The conformance corpus cites these ids, and the station that
  runs it fails if a section has no case citing it, or a case cites a section
  that does not exist.
- **Examples** are real: each one in a section is a case in
  [`tests/conformance/cases/`](../../tests/conformance/cases/) (the case's `spec`
  field names the section), and the expected output shown is what the corpus
  requires.
- **Error text.** Where a section says a program is rejected, it gives the
  message. Messages are part of the contract (section `[err.model]`), written
  with the dynamic parts in italics or as `<...>`.

## Profiles

A *profile* names a set of language features a host implements. Every case in
the corpus carries one. The profiles so far:

| Profile | Contents |
| --- | --- |
| `core` | The language itself, the values and the built-in functions that compute on them. No files, environment, clock, randomness, processes, modules or embedding. Deterministic. |
| `modules` | `import` and `export`: a program that loads other files. Needs a file system, or something that stands in for one, and a way to find a module relative to the file that imports it. `core` plus this. |
| `embedding` | A host program that runs the language inside itself: binds values and functions for the script, runs it, calls into it, and receives its errors (`11-embedding.md`). Needs a host program; the self-hosted interpreter has none. |
| `python` | The `python.*` bridge to Python, reference host only, off unless asked for (`11-embedding.md`). |
| `host` | What a program needs from the machine it runs on: process exit status, files, the environment, the clock, randomness and standard input (`10-host.md`). Present only if the host provides it (`[sec.principles]`). |

| `policy` | The game's policy dialect, a separate language specified in `12-policy-syntax.md` onwards ([ADR 0004](../decisions/0004-policy-dialect-after-measurement.md)). Its cases run on the policy engine (`dialects/policy/`) and never on NovaLang's engines. |

## Files

| File | Sections |
| --- | --- |
| [`01-lexical.md`](01-lexical.md) | `lex.*`: source text, line ends, comments, names, numbers, strings, f-strings, operators |
| [`02-expressions.md`](02-expressions.md) | `val.*` the value model, `expr.*` the expression grammar and its meaning |
| [`03-scoping.md`](03-scoping.md) | `scope.*`: names, blocks, functions, closures, shared values |
| [`04-errors.md`](04-errors.md) | `err.*`: the error model, `try`/`catch`/`finally`, the message catalogue |
| [`05-security.md`](05-security.md) | `sec.*`: what the language guarantees (no ambient authority, no dynamic code, no reflection, scope isolation, no host failures leaking) |
| [`06-portability.md`](06-portability.md) | `port.*`: integers, floats and how they print, text, ordering and determinism, limits |
| [`07-statements.md`](07-statements.md) | `stmt.*`: `if`, `while`, both `for` forms, loop `else`, `break`/`continue`, `def`, `delete` |
| [`08-modules.md`](08-modules.md) | `mod.*`: `import`, `export`, finding files, the module cache, scope, cycles, errors while loading |
| [`09-library.md`](09-library.md) | `lib.*`: the core library (collections, strings, `regex`, math, `map`/`filter`/`reduce`, JSON, `assert`) |
| [`10-host.md`](10-host.md) | `host.*`: files, the clock, randomness, the environment and the process (the `host` profile) |
| [`11-embedding.md`](11-embedding.md) | `emb.*`: engines, values across the boundary, binding host values, calling in, errors; `py.*`: the Python bridge and what it can reach |
| [`12-policy-syntax.md`](12-policy-syntax.md) | `pol.*`: the policy dialect's source text, syntax, statements, scopes, calls, modules, limits and error text (the `policy` profile) |
| [`DIVERGENCES.md`](DIVERGENCES.md) | Where an implementation does not yet follow this text |

## The conformance corpus

[`tests/conformance/`](../../tests/conformance/README.md) holds host-neutral
cases (source, expected output, expected error, expected exit status) and the
station that runs them on the bytecode VM, the tree-walker and the self-hosted
interpreter: `python3 tests/run_all.py --station conformance`.

## Versioning

NovaLang's version is `MAJOR.MINOR.PATCH`. For the language, not an
implementation:

- A **patch** release changes no program's meaning; it fixes a bug where an
  implementation did not follow this specification.
- A **minor** release may make new programs valid, and may make a program that
  was an error valid. It MUST NOT change what a valid program does or prints.
  It MAY change which message an invalid program reports only to fix a typo or
  to make the message more specific, and such a change is listed in the changelog.
- A **major** release may change what valid programs do.

Message text is part of the contract, so changing it is at least a minor change
and is checked by the corpus.
