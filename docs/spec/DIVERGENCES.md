# Divergence log

Where an implementation does not follow [the specification](README.md), and what
is being done about it. Created 2026-11-08 by the first run of the conformance
corpus on the three Python engines.

Each entry has a **Status**:

- `open`: an implementation disagrees with the specification. At least one
  corpus case records exactly what the engine does instead (its `divergences`
  field), so the disagreement cannot grow, and the case fails the day the engine
  starts following the specification, as a reminder to close the entry.
- `normalized`: the corpus ignores a documented, systematic difference in how
  one engine words the *headline* of an error, instead of recording it case by
  case. The rule is in `tests/conformance/conformance.py`.
- `resolved`: fixed. Kept for the record; no case may cite it.

and a **Class**: an *implementation bug* (the text is right and the engine
should change), a *spec bug* (the engine is right and the text should change), or
*decision needed* (either could be right and the project owner chooses; a
change would break existing programs).

The engines are the bytecode VM and the tree-walker (both `novalang.py`, which
agree on every case in the corpus) and the self-hosted interpreter
(`novalang.nova`, run with `--bootstrap`). The self-hosted interpreter
accounts for every entry but D-002, which is the host's.

### D-001 — Error headlines in the self-hosted interpreter

Status: normalized
Class: implementation bug
Engines: self-hosted
Spec: `[err.model]`

The self-hosted interpreter reports a lexical or syntax error as
`Error: LexError@12: message` or `Error: ParseError@12: message` (a kind and a
character offset in front of the message), and a runtime error that its own code
raises with the label `Error` where the host says `NovaError`. It also reports no
line number and its report shows lines of `novalang.nova` and its call frames
rather than the program's. The corpus compares the message and, for these two
patterns, ignores the prefix and the label; it does not compare the line for this
engine. Every other label (`TypeError`, `PythonError`, `Error` for `throw`) is
compared exactly.

Fix: have the self-hosted interpreter raise errors that carry `NovaError`, the
message and a line, as the host's do.

### D-002 — Non-ASCII letters and digits in the host lexer

Status: open
Class: decision needed
Engines: bytecode VM, tree-walker
Spec: `[lex.identifiers]`, `[lex.numbers]`
Cases: `lex-non-ascii-letter-in-identifier`, `lex-non-ascii-digit-is-not-a-number`

`novalang.py` uses Python's `isalpha` and `isdecimal` to read names and numbers,
so `let é = 1` and `print(١٢٣)` (Arabic-Indic digits) run. The specification, and
the self-hosted interpreter, allow ASCII only and report
`unexpected character 'é'`. Tightening the host is the simplest way to agree
but would break any program that uses an accented name; widening the
specification would mean choosing which Unicode categories count and teaching
the self-hosted interpreter (which has no way to ask for a character's class)
the same answer. The specification states the ASCII rule until the owner decides.

A related crash is fixed: a superscript digit such as `²` passed `isdigit` but
not `int()`, so `print(²)` and `num("²")` ended in a raw Python `ValueError`
instead of a NovaLang error. Both now report `unexpected character '²'` and
`num() cannot read a number from "²"`, and have corpus cases.

### D-003 — Offending tokens in syntax errors are not quoted

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[err.syntax]`
Cases: 16, for example `lex-two-statements-on-one-line-error`

The host writes `expected a new line between statements, found 'print'`,
`unexpected ')'` and `found the string 's'`. The self-hosted interpreter writes
`found print`, `unexpected )` and `found the string s`: the same message
without the quotation marks around the token.

### D-004 — `1.2.3` is a parse error, not a lexical one

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[lex.numbers]`
Cases: `lex-two-decimal-points-error`

The host reports `a number cannot have two decimal points`. The self-hosted
lexer reads `1.2` and then `.3`, so the program fails later with
`expected a ')' to close the argument list, found 0.3`.

### D-005 — "a number is not a function" loses its article

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[expr.call]`
Cases: `expr-call-a-number-error`

`a number is not a function, so it cannot be called` (host) against
`number is not a function, so it cannot be called` (self-hosted).

### D-006 — Wrong built-in argument count crashes the wrong way

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[expr.call]`, `[err.call]`
Cases: `err-call-builtin-wrong-argument-count`

`len()` is `len() takes 1 argument(s) but got 0` on the host. The self-hosted
interpreter does not check the count for its built-ins and reads a missing
argument, so the program fails with `this list is empty, so it has no item to
index`, which says nothing about the call.

### D-007 — Comparing functions overflows the self-hosted stack

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[val.equality]`
Cases: `val-equality-of-functions-is-identity`

`f == f` is `true` on the host. In the self-hosted interpreter a function is a
dictionary that refers to its own scope, and `==` compares dictionaries by
walking them, so comparing two functions recurses until the host stack runs
out and the program ends with `the self-hosted interpreter ran out of stack`.
Equality of functions MUST be identity. On Python before 3.11 the same
recursion overflows the C stack and the interpreter's process is killed (exit
status -11 on Linux) instead of printing a message, so the corpus accepts either
(`"unstable": true`).

### D-008 — A new name assigned inside a block leaks out of it

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[scope.assign]`, `[scope.blocks]`
Cases: `scope-new-name-in-block-is-local`

`if true { y = 5 }` then `print(y)` is `undefined name 'y'` on the host. The
self-hosted interpreter creates `y` in the enclosing scope, so the program
prints `5`. (`let` inside a block is scoped correctly by both.)

### D-009 — Duplicate parameter names are accepted

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[scope.param]`
Cases: `scope-duplicate-parameter-error`

`def f(a, a)` is `parameter 'a' is listed twice` on the host and runs on the
self-hosted interpreter, where the second `a` wins.

### D-010 — Built-in names can be redefined

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[scope.reserved]`
Cases: `scope-builtin-names-cannot-be-variables`,
`scope-builtin-names-cannot-be-assigned`, `scope-builtin-names-cannot-be-function-names`,
`scope-builtin-names-cannot-be-parameters`

`let print = 5`, `print = 1`, `def len() { }` and `def f(len)` are errors on the
host (`'print' is a built-in function and cannot be used as a variable name`)
and are accepted by the self-hosted interpreter.

### D-011 — Top-level `return`, `break` and `continue` are ignored

Status: open
Class: implementation bug
Engines: self-hosted
Spec: `[scope.toplevel]`
Cases: `scope-return-at-top-level-error`, `scope-break-outside-loop-error`,
`scope-continue-outside-loop-error`, `scope-return-inside-loop-at-top-level-error`

On the host each is an error. The self-hosted interpreter accepts them and
the program ends normally with status 0.

## Not divergences, but worth knowing

The bytecode VM and the tree-walker agree on every corpus case, which is the
guarantee `tests/vm/` already enforces on a much larger body of programs. The
host's error *report* (source line, caret, call frames) is not part of the
language and is not compared for any engine.
