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
accounted for every entry but D-002, D-012 and D-013 (the host's own); D-003 to D-011 are fixed, so only D-001 (normalized) remains.

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

Status: resolved
Class: decision needed (decided 2026-11-08: ASCII only)
Engines: bytecode VM, tree-walker
Spec: `[lex.identifiers]`, `[lex.numbers]`

`novalang.py` used Python's `isalpha`, `isalnum` and `isdecimal`, so `let é = 1`
and `print(١٢٣)` ran. The specification, and the self-hosted interpreter,
allow ASCII letters, digits and `_` only. For a language meant for financial and
hardware systems, look-alike characters (a Cyrillic `а` for a Latin `a`) must
be an error, not a second program; the project owner decided to enforce the
specification on the host. A breaking change, made in 2.1.0.

Names, number literals, `num()`, the printing of dictionary keys (`{"é": 1}`
prints with its quotes) and the formatter now use ASCII-only tests
(`is_digit`, `is_name_start`, `is_bare_name` in `novalang.py`).

A related crash was fixed earlier: a superscript digit such as `²` passed
`isdigit` but not `int()`, so `print(²)` and `num("²")` ended in a raw Python
`ValueError` instead of a NovaLang error.

### D-003 — Offending tokens in syntax errors are not quoted

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[err.syntax]`
Cases (now passing, unmodified): 16, for example `lex-two-statements-on-one-line-error`

The host writes `expected a new line between statements, found 'print'`,
`unexpected ')'` and `found the string 's'`. The self-hosted interpreter writes
`found print`, `unexpected )` and `found the string s`: the same message
without the quotation marks around the token.

Fixed 2026-11-08: `p_describe` quotes tokens the way the host's `describe` does (`quote_text`).

### D-004 — `1.2.3` is a parse error, not a lexical one

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[lex.numbers]`
Cases (now passing, unmodified): `lex-two-decimal-points-error`

The host reports `a number cannot have two decimal points`. The self-hosted
lexer reads `1.2` and then `.3`, so the program fails later with
`expected a ')' to close the argument list, found 0.3`.

Fixed 2026-11-08: `lex_number` raises the lexical error on a second decimal point.

### D-005 — "a number is not a function" loses its article

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[expr.call]`
Cases (now passing, unmodified): `expr-call-a-number-error`

`a number is not a function, so it cannot be called` (host) against
`number is not a function, so it cannot be called` (self-hosted).

Fixed 2026-11-08: `type_phrase` names the value with its article.

### D-006 — Wrong built-in argument count crashes the wrong way

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[expr.call]`, `[err.call]`
Cases (now passing, unmodified): `err-call-builtin-wrong-argument-count`

`len()` is `len() takes 1 argument(s) but got 0` on the host. The self-hosted
interpreter does not check the count for its built-ins and reads a missing
argument, so the program fails with `this list is empty, so it has no item to
index`, which says nothing about the call.

Fixed 2026-11-08: `call_target_value` checks a built-in's argument count against `BUILTIN_ARITY`.

### D-007 — Comparing functions overflows the self-hosted stack

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[val.equality]`
Cases (now passing, unmodified): `val-equality-of-functions-is-identity`

`f == f` is `true` on the host. In the self-hosted interpreter a function is a
dictionary that refers to its own scope, and `==` compares dictionaries by
walking them, so comparing two functions recurses until the host stack runs
out and the program ends with `the self-hosted interpreter ran out of stack`.
Equality of functions MUST be identity. On Python before 3.11 the same
recursion overflows the C stack and the interpreter's process is killed (exit
status -11 on Linux) instead of printing a message, so the corpus accepts either
(`"unstable": true`).

Fixed 2026-11-08: Every function value carries an `id`; `target_equal` compares functions by identity.

### D-008 — A new name assigned inside a block leaks out of it

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[scope.assign]`, `[scope.blocks]`
Cases (now passing, unmodified): `scope-new-name-in-block-is-local`

`if true { y = 5 }` then `print(y)` is `undefined name 'y'` on the host. The
self-hosted interpreter creates `y` in the enclosing scope, so the program
prints `5`. (`let` inside a block is scoped correctly by both.)

Fixed 2026-11-08: `env_assign` creates a new name in the innermost scope.

### D-009 — Duplicate parameter names are accepted

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[scope.param]`
Cases (now passing, unmodified): `scope-duplicate-parameter-error`

`def f(a, a)` is `parameter 'a' is listed twice` on the host and runs on the
self-hosted interpreter, where the second `a` wins.

Fixed 2026-11-08: `parse_function_def` refuses a repeated parameter name.

### D-010 — Built-in names can be redefined

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[scope.reserved]`
Cases (now passing, unmodified): `scope-builtin-names-cannot-be-variables`,
`scope-builtin-names-cannot-be-assigned`, `scope-builtin-names-cannot-be-function-names`,
`scope-builtin-names-cannot-be-parameters`

`let print = 5`, `print = 1`, `def len() { }` and `def f(len)` are errors on the
host (`'print' is a built-in function and cannot be used as a variable name`)
and are accepted by the self-hosted interpreter.

Fixed 2026-11-08: `p_guard_name` is applied at every site the host guards, and `abspath` and `dirname` were added to the self-hosted built-ins.

### D-011 — Top-level `return`, `break` and `continue` are ignored

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[scope.toplevel]`
Cases (now passing, unmodified): `scope-return-at-top-level-error`, `scope-break-outside-loop-error`,
`scope-continue-outside-loop-error`, `scope-return-inside-loop-at-top-level-error`

On the host each is an error. The self-hosted interpreter accepts them and
the program ends normally with status 0.

Fixed 2026-11-08: `run_program` turns a `return`, `break` or `continue` that reaches the top level into the host's errors.

### D-012 — A number with thousands of digits

Status: open
Untested: it depends on Python's own limit on turning text into an integer, which
differs between releases (see D-013)
Class: decision needed
Engines: all three Python engines
Spec: `[port.integers]`, `[sec.error-boundary]`
Cases: none

A number literal or a `num()` argument of more than 4300 digits is
`this number has too many digits` (literal) or `num(): that number has too many
digits` on the Python releases that refuse it, and an ordinary number on those
that do not. The self-hosted lexer builds numbers with `num()`, so the two
messages differ. Like D-013 this needs the language to define its own digit
limit.

### D-013 — Integer-to-text limits depend on the Python release

Status: open
Untested: the behaviour differs between Python releases, so no case can pin it on
every host
Class: decision needed
Engines: all three Python engines
Spec: `[port.integers]`
Cases: none

Python 3.11 and the security releases of 3.7 to 3.10 refuse to turn an integer of
more than 4300 digits into text, and the three engines turn that refusal into
`an integer with more than 4300 digits cannot be converted to text`. Earlier
releases of those versions have no limit, so `print(big)` succeeds there. The
specification says a host MAY refuse beyond a host-defined size of at least 4,300
digits; it does not say a host MUST. To make the engines agree on every Python the
reference would have to enforce its own limit (and decide it: 4,300 digits, or
a size in bits) instead of inheriting Python's, and the same question applies
to integers built by arithmetic, which are unbounded. That is a language decision.

## Not divergences, but worth knowing

The bytecode VM and the tree-walker agree on every corpus case, which is the
guarantee `tests/vm/` already enforces on a much larger body of programs. The
host's error *report* (source line, caret, call frames) is not part of the
language and is not compared for any engine.
