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
accounted for D-001 and D-003 to D-011; D-002 and D-012 to D-014 are the host's
own. Every entry but D-001 (normalized) and D-015 (a cosmetic difference in one
error message) is now resolved.

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

Status: resolved
Class: decision needed (decided 2026-11-08: the language's own limit, 4,000 digits)
Engines: all three Python engines
Spec: `[port.integers]`, `[sec.error-boundary]`
Cases: `port-number-literal-of-four-thousand-digits`,
`port-number-literal-past-four-thousand-digits-is-an-error`,
`port-number-literal-digits-count-on-both-sides-of-the-point`,
`port-num-reads-four-thousand-digits`, `port-num-past-four-thousand-digits-is-an-error`

A literal or a `num()` argument of more than 4300 digits was an error on the
Python releases that refuse it and an ordinary number on those that do not, and
the self-hosted interpreter worded the error differently. A literal and a
`num()` argument now have at most 4,000 digits on every engine, counted in the
text (both sides of a point, leading zeros included), so Python's own limit is
never reached.

Fixed 2026-11-08: `Lexer.read_number` and `builtin_num` count digits first;
`lex_number` in `novalang.nova` does the same.

### D-013 — Integer-to-text limits depend on the Python release

Status: resolved
Class: decision needed (decided 2026-11-08: the language's own limit, 4,000 digits)
Engines: all three Python engines
Spec: `[port.integers]`
Cases: `port-integer-bound-is-four-thousand-digits`,
`port-integer-addition-past-the-bound-is-an-error`,
`port-integer-subtraction-past-the-bound-is-an-error`,
`port-integer-multiplication-past-the-bound-is-an-error`,
`port-integer-bound-error-can-be-caught`,
`port-pow-past-the-bound-is-refused-before-it-is-computed`,
`port-sum-past-the-bound-is-an-error`, `port-round-past-the-bound-is-an-error`,
`port-json-loads-past-the-bound-is-an-error`

Python 3.11 and the security releases of 3.7 to 3.10 refuse to turn an integer of
more than 4300 digits into text, earlier releases do not, and integers built by
arithmetic had no bound at all. `print(big)` therefore worked on one Python and
failed on another, and a program could build an integer a microcontroller or a
browser could not hold.

An integer now has at most 4,000 digits: any operation that would pass it, on
every engine, is `the result has too many digits - an integer cannot have more
than 4000 digits`, and `pow()` refuses a result that large before computing it.
Every integer inside the bound converts to text, so Python's limit is never
reached.

Fixed 2026-11-08: `bounded_integer` and `INTEGER_LIMIT` in `novalang.py`, checked
in `binary_operation`, in the VM's inline `+`, `-` and `*`, after every built-in
call, in `to_nova_value` and in `json.loads()`. The self-hosted interpreter does
its arithmetic with the host's operators, so it inherits the check.

### D-014 — How a float prints depended on Python's `repr`

Status: resolved
Class: decision needed (decided 2026-11-08: a written rule, not a library's)
Engines: all three Python engines
Spec: `[port.floats]`, `[val.display]`
Cases: `port-float-display-just-above-a-power-of-two-needs-the-upper-neighbour`,
`port-float-display-extremes`, `port-float-display-limits-of-positional-form`,
`port-float-display-large-whole-values-are-exact`

The text of a float was whatever Python's `str` gave, which a host in another
language would have had to copy. The specification now states the rule (the
shortest digits that read back, the one nearest the true value among them,
positional from `0.0001` to `1e16` and `e` form below) and the engines compute it
with exact decimal arithmetic (`shortest_digits`, `float_text`, `format_float`
in `novalang.py`) and no longer call `repr`. The output is the same as before for
every float: `tests/portability/test_numbers.py` checks it against `repr` over
every power of two with its neighbours (subnormals included) and a large sample
of random bit patterns. A shortcut that tries only the nearest decimal of each
length is wrong for some powers of two (the first draft of the implementation
was), which is why the rule and the test name the upper neighbour.

### D-015 — A whole float in a syntax error loses its point

Status: open
Class: implementation bug (cosmetic)
Engines: self-hosted
Spec: `[err.syntax]`
Cases: `lex-whole-float-literal-is-shown-with-its-point-in-a-syntax-error`

When the offending token is a number written with a point and a whole value, such
as `5.`, the host names it `5.0` and the self-hosted interpreter `5`: its lexer
turns `5.` into the number 5 and the point is gone by the time the message is
written. `5.5` and integers are the same in both. Nothing else about the error
differs, and it can only appear inside a message about a syntax error.

Accepted as a known cosmetic difference (owner, 2026-11-08) and not worth
holding up the slice. It goes away when the self-hosted interpreter stops being
a second implementation of the numbers, as it will once it targets the bytecode
the VM runs.

## Not divergences, but worth knowing

The bytecode VM and the tree-walker agree on every corpus case, which is the
guarantee `tests/vm/` already enforces on a much larger body of programs. The
host's error *report* (source line, caret, call frames) is not part of the
language and is not compared for any engine.
