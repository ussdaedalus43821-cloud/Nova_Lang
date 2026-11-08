# NovaLang language specification

Status: **first slice, draft.** Written 2026-11-08 for milestone M9. It covers
lexical rules, values, expressions, scoping and the error catalogue. Statements
beyond `let`, assignment, blocks, loops, functions and `try`/`catch`/`finally`,
the standard library, modules and the type annotations are still to come.

This specification is normative ([ADR 0001](../decisions/0001-specification-is-normative.md)):
where an implementation and this text disagree, one of them has a bug, and the
disagreement is written down in [`DIVERGENCES.md`](DIVERGENCES.md) until it is
resolved. `novalang.py` is the first conforming host, not the definition.

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
the corpus carries one. This slice has one profile:

| Profile | Contents |
| --- | --- |
| `core` | Everything in this specification so far, with no host I/O, no modules and no embedding. |

Profiles for host I/O, embedding and the game dialect ([ADR 0002](../decisions/0002-game-dialect-and-profiles.md))
are added as their sections are written.

## Files

| File | Sections |
| --- | --- |
| [`01-lexical.md`](01-lexical.md) | `lex.*`: source text, line ends, comments, names, numbers, strings, f-strings, operators |
| [`02-expressions.md`](02-expressions.md) | `val.*` the value model, `expr.*` the expression grammar and its meaning |
| [`03-scoping.md`](03-scoping.md) | `scope.*`: names, blocks, functions, closures, shared values |
| [`04-errors.md`](04-errors.md) | `err.*`: the error model, `try`/`catch`/`finally`, the message catalogue |
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
