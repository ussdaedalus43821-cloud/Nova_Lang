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
accounted for D-001, D-003 to D-011, D-015, D-016, D-017 and D-024; the rest are the
host's own. Everything is resolved except D-001 (normalized), D-015 (a cosmetic
difference in one error message), D-040 to D-046 (the sandbox profile of `16-sandbox.md`: D-040 to D-044 are resolved, D-045 and D-046 are open and untested) and D-025 and D-033 (case conversion beyond ASCII,
an open decision for NovaLang and for the policy dialect). D-030 to D-033 are the
policy dialect engine's (`dialects/policy/`, ADR 0004), found while writing
`13-policy-values.md`.

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

### D-016 — `delete` on a list lacked the host's hint

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[stmt.delete]`
Cases: `stmt-delete-on-a-list-is-an-error`

The host adds ` - use pop() to remove a list item` when `delete` is given a list;
the self-hosted interpreter did not, and named a boolean or `nothing` without its
article. Found by the statements probes and fixed in the same change.

### D-017 — Importing: the self-hosted interpreter differed in seven ways

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[mod.import]`, `[mod.errors]`, `[mod.cycles]`, `[mod.scope]`
Cases: `mod-import-as-needs-no-valid-file-name`, `mod-import-with-a-missing-name-is-an-error`,
`mod-import-with-the-same-name-twice-is-a-syntax-error`,
`mod-scope-top-level-return-in-a-module-is-an-error`,
`mod-scope-a-module-cannot-see-the-importers-names`, `mod-cycle-is-an-import-error`,
`mod-errors-a-runtime-error-reaches-the-importer-wrapped`,
`mod-errors-a-syntax-error-in-a-module-is-caught-at-import`, `mod-resolution-missing-module-can-be-caught`

Found by the first module probes, and fixed with them:

- an error inside a module reached the importer bare; the host wraps it as
  `ImportError: while loading module "<path>":` with the report indented;
- import failures (not found, not installed, circular) had no `ImportError`
  label, so a `catch` saw a different text;
- `import "1st.nova" as ok` was refused because the default name was computed
  even when an alias made it unnecessary;
- a `return`, `break` or `continue` at the top of a module was ignored;
- `import "m.nova" with x, x` was accepted (`'x' is imported twice`);
- the missing-export message omitted `- it exports a, b`;
- a circular import named the files without their extension (`a -> b -> a`).

The label difference is part of D-001's normalization: the self-hosted
interpreter writes `Error: ImportError: message`, which the station reads as the
label it names.

### D-018 — Modules did not get `PI`, `E`, `json` and `python`

Status: resolved
Class: decision needed (decided 2026-11-08 by the maintainer's brief: a module is a fresh program)
Engines: bytecode VM, tree-walker
Spec: `[mod.scope]`, `[scope.global]`
Cases: `mod-scope-a-module-has-the-built-ins-and-predefined-names`

The host defined `PI`, `E`, `json` and `python` only in the scope of the program
it started, so a module that used `json.dumps` or `PI` failed with `undefined
name`, while the self-hosted interpreter gave modules all four. A module now
starts with the same predefined names as a program (`Interpreter.new_global_scope`).
`python` follows the host's switch exactly as in the program: it is the refusing
stub unless `--allow-python` or `allow_python=True` was given, so a module gains no
reach a program did not have.

### D-019 — What `sorted` does with items that are not all numbers or all strings

Status: resolved
Class: decision needed (decided 2026-11-08: booleans count as 0 and 1; mixed kinds are refused)
Engines: all three Python engines
Spec: `[lib.collections]`
Cases: `lib-sorted-treats-booleans-as-zero-and-one`, `lib-sorted-refuses-what-cannot-be-ordered`

`sorted` ordered lists of lists item by item and put `false` before `true`, while
`<` on two lists is an error, and a NaN among numbers left the order to Python's
sort. It now sorts numbers and booleans together by value (`false` is 0, `true` is
1) and strings by code point, and refuses a mixture of the two, any other kind of
item, and NaN with `TypeError: sorted() needs items that can be compared with each
other`.

### D-020 — Whitespace and line ends followed Python's Unicode tables

Status: resolved
Class: decision needed (decided 2026-11-08: ASCII only)
Engines: all three Python engines
Spec: `[lib.text]`, `[val.types]`
Cases: `lib-trim-and-split-use-ascii-whitespace-only`,
`lib-num-skips-only-ascii-whitespace`,
`lib-split-lines-ends-lines-only-at-line-feeds-and-returns`

`trim`, `split` with no separator and `num` skipped whatever Python calls
whitespace (no-break space, the Unicode spaces, U+001C to U+001F), and
`split_lines` also split on form feed, vertical tab, U+0085, U+2028 and U+2029, so
a text meant different things on hosts with different tables. Whitespace is now the
six ASCII characters space, tab, line feed, carriage return, vertical tab and form
feed, and a line ends only at a line feed, a carriage return or both together.
A program that relied on trimming a no-break space now keeps it.

### D-021 — Regular-expression classes beyond ASCII

Status: resolved
Class: decision needed (decided 2026-11-08: ASCII only)
Engines: all three Python engines
Spec: `[lib.regex]`
Cases: `lib-regex-classes-are-ascii`

`\d`, `\w`, `\s` and `\b` followed Unicode in Python, so `regex("^\\d+$", "١٢٣")`
(Arabic-Indic digits) was `true`, against the language's ASCII-only digits (D-002).
They now mean `0`-`9`; `A`-`Z`, `a`-`z`, `0`-`9` and `_`; the ASCII whitespace; and the edge
of those (`re.ASCII`). `$` before a final line feed, everything beyond the specified
subset, and a pattern that backtracks badly (`[sec.limits]`) are unchanged.

### D-022 — `json.dumps` and `json.loads` of infinity and NaN

Status: resolved
Class: decision needed (decided 2026-11-08: refuse both)
Engines: all three Python engines
Spec: `[lib.json]`
Cases: `lib-json-dumps-refuses-nan-and-infinity`,
`lib-json-loads-refuses-nan-infinity-and-overflow`

`json.dumps` wrote `Infinity`, `-Infinity` and `NaN`, and `json.loads` accepted
them and numbers like `1e999`, though JSON has no such values. `json.dumps` now
raises `TypeError: json.dumps() cannot represent NaN or infinity`, and `json.loads`
raises `TypeError: json.loads(): NaN is not valid JSON` (or `Infinity`,
`-Infinity`) and `TypeError: json.loads(): that number is too large`. The decision
asked for a `ValueError` from `json.loads`; NovaLang has no such label (the labels
are in `[err.model]`), so it carries `TypeError` like every other `json.loads`
error.

### D-023 — Variable-argument built-ins leaked a raw Python exception

Status: resolved
Class: implementation bug
Engines: bytecode VM, tree-walker
Spec: `[lib.calls]`, `[sec.error-boundary]`
Cases: `lib-range-of-argument-counts-errors`

`round()`, `sorted()`, `reduce()`, `reduce(f)` and `assert()` with no arguments
ended in `InternalError: IndexError` (a Python exception, status 70, no
`try`/`catch` could stop it), and too many arguments were silently accepted by
those and by `exit`. Each now reports what it takes (`round() takes a number and an
optional digit count`).

### D-024 — Library calls in the self-hosted interpreter

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[lib.calls]`, `[lib.functional]`, `[lib.json]`
Cases: `lib-range-of-argument-counts-errors`, `lib-higher-order-argument-errors`,
`lib-json-dumps-refuses-functions`

It did not check the argument count of `pop`, `range`, `split` and the other
built-ins that take a range of counts (it read past the arguments or ignored the
extra ones), did not validate the arguments of `map`, `filter` and `reduce`, wrote
a function out through `json.dumps` instead of refusing it, and reported errors the
host labels `TypeError` without the label. Fixed; D-001's normalization now also
reads `Error: TypeError: message` as the label it names.

### D-026 — File errors depended on the operating system

Status: resolved
Class: implementation bug
Engines: all three Python engines
Spec: `[host.files]`
Cases: `host-files-folder-and-file-mixups-are-file-errors`

`read`, `write` and `append` on a folder, `delete` on a folder and `listdir` on a
file ended in whatever the operating system's error was: `IsADirectoryError` on
Linux and macOS, `PermissionError` on Windows, with a different message. The
specification fixes the messages (`FileError: d is a directory, not a file`), so the
host now asks first (`os.path.isdir`, `isfile`) and does not leave it to the system.
The wording of failures the host cannot predict (`remove` of a full folder,
`rename` of a missing file) stays the operating system's, and only the prefix is
specified.

### D-027 — Text written to a file was translated on Windows

Status: resolved
Class: implementation bug
Engines: all three Python engines
Spec: `[host.files]`
Cases: `host-files-read-turns-every-line-end-into-a-line-feed`

`write` and `append` opened the file in Python's text mode, which writes each `\n` as
`\r\n` on Windows, so the same program made different files and `write("a",
"x\ry\r\nz\n")` read back with a different length on Windows than on Linux. They
now write the text exactly (`newline=""`). `read` still turns `\r\n` and `\r` into
`\n`, which is now written down.

### D-028 — `log` in the self-hosted interpreter

Status: resolved
Class: implementation bug
Engines: self-hosted
Spec: `[host.process]`
Cases: `host-process-log-goes-to-standard-error`

It logged only its first argument, and `log()` with none read past its arguments.
It now joins every argument with spaces as `print` does.

### D-029 — Two embedding calls let an internal error escape

Status: resolved
Class: implementation bug
Engines: bytecode VM, tree-walker
Spec: `[emb.errors]`, `[sec.error-boundary]`
Cases: `emb-built-in-names-cannot-be-bound`, `emb-a-number-past-the-bound-cannot-be-bound`,
`emb-call-arguments-past-the-bound-are-an-error`

`Nova.expose_global` with a built-in's name, a number beyond the bound or a module
the host did not grant, and `Nova.call` with an argument beyond the bound, raised the
interpreter's internal `NovaError` instead of the `NovaLangError` every other method
raises, which an embedding program cannot be expected to catch. Both now raise
`NovaLangError`. (Found by probing the boundary for the embedding chapter.)

### D-025 — Case conversion beyond ASCII

Status: open
Untested: it depends on the Unicode tables of the Python underneath
Class: decision needed
Engines: all three Python engines
Spec: `[lib.text]`
Cases: none beyond ASCII

`upper` and `lower` follow Python's full Unicode case mapping: `upper("ß")` is
`"SS"`, `lower("İ")` is two characters. A port needs those tables, and a newer
Unicode version can change a result. The decision: keep it host-defined, restrict
the two functions to ASCII (as D-020 did for whitespace), or name a Unicode version
and ship the mapping.

### D-030 — Policy dialect: names and keys quoted the way Python quotes them

Status: resolved
Class: implementation bug
Engines: the policy dialect engine
Spec: `[pol.index]`, `[pol.import]`

The policy engine wrote the name or key in a message with Python's `repr`, so
`dict has no key 'it's'` came out as `dict has no key "it's"` and a key with a
backslash was doubled, while the GDScript port writes `'` + the text + `'`. The
specification says the text goes between plain quotes exactly as it is. Fixed in
`dialects/policy/` (the messages for a missing key, an unknown name or function, a
module that cannot be read and a circular import).

### D-031 — Policy dialect: infinity and NaN in whole-number functions

Status: resolved
Class: implementation bug
Engines: the policy dialect engine
Spec: `[pol.lib-math]`, `[pol.index]`, `[pol.lib-collections]`

`floor`, `round` and `int` of infinity or NaN, `pow(0, -1)`, `pow` of a negative base
with a fractional exponent, and any index, `slice`, `remove_at` or `range` argument
that was infinity or NaN each ended in a raw Python exception (`OverflowError`,
`ValueError`, `ZeroDivisionError`, or a `TypeError` from a complex result) instead of
a result or a language error, which a game would see as a crashed host. The
specification now says: `floor`, `round` and `int` return a non-finite argument
unchanged; `pow` follows C (`pow(0, -1)` is `inf`, a negative base with a fractional
exponent is NaN, and overflow takes its sign from the base and the exponent); a
non-finite index, position or count is `expected a finite number, got inf`.

### D-032 — Policy dialect: `num` accepted Python's float syntax

Status: resolved
Class: implementation bug
Engines: the policy dialect engine
Spec: `[pol.lib-convert]`

`num("1_0")` was 10, `num("inf")` was `inf`, `num("nan")` was NaN and digits of other
scripts were read, because the engine handed the text to Python's `float`. The GDScript
port's `to_float` accepts none of those and reads a leading number out of text such as
`12abc`. The specification gives one grammar (an optional sign, digits with an optional
point, an optional exponent, ASCII spaces around it) and makes anything else `0`; the
engine now follows it.

### D-034 — Policy dialect: an error in a signal was blamed on a rule, or lost

Status: resolved
Class: implementation bug
Engines: the policy dialect engine
Spec: `[pol.decl-signals]`, `[pol.engine-errors]`

The engine did not look for an error after evaluating the signals. If any rule followed, the
signal's error was found while evaluating that rule's condition and reported as that rule's
(`rule 'r': line 1: unknown identifier 'nope'`, naming a rule that had nothing wrong); with no
rule the error was never reported and the tick succeeded. The GDScript port's bytecode backend
already stops the tick with the signal's own error. The specification says that, and the
engine now does.

### D-035 — Policy dialect: a non-number where the engine needs one

Status: resolved
Class: implementation bug
Engines: the policy dialect engine
Spec: `[pol.engine-errors]`, `[pol.fault-schedule]`, `[pol.fault-api]`

A fault `duration` that was not a number (`duration "long"`, or an unknown name), or a
`t` input or `fault_*` timing parameter that was not a number, ended in a raw Python
`TypeError` or `ValueError`, and `inject_fault` of a fault whose duration failed
started the fault with duration 0 and reported success. All now fail with the
ordinary `expected a number, got string` or the expression's own error; a fault that
cannot work out its duration does not start; `inject_fault` returns false.

### D-033 — Policy dialect: case conversion beyond ASCII

Status: open
Untested: it depends on the Unicode tables of the host underneath
Class: decision needed
Engines: the policy dialect engine (and any port)
Spec: `[pol.lib-text]`

`upper` and `lower` follow Python's full Unicode case mapping (`upper("ß")` is `"SS"`);
a port's engine maps each character on its own. The same decision as D-025 for the
NovaLang functions: it stays host-defined, and the cases use ASCII only.

### D-040 — No capability gating: every host function is defined for every program

Status: resolved
Class: implementation bug
Engines: bytecode VM, tree-walker, self-hosted
Spec: `[sbx.capabilities]`, `[sbx.profiles]`

There is no `restricted` profile. `read`, `write`, `exists`, `listdir`, `mkdir`, `remove`,
`rename`, `copy`, the file form of `append`, `delete` of a file, `env`, `time`, `now`,
`sleep`, `format_time`, `random` and its three companions, `input`, `exit`, `args`,
`platform`, `cwd`, `abspath`, `regex` and `replace_all` are built-ins of every engine, in
every program and in an embedded `Nova()`. `import` reads any module. A grant of `env`
names does not hide the others. The cases run a `restricted` program on engines that
ignore the `sandbox` object and record what each does instead of the specified
`undefined name 'read'`. Found by the measurements for the M11 plan (a script run by
`Nova()` read `/etc/hostname`). Closed by slice 2 of M11.

Fix: a `Capabilities` object chosen when the engine is created; a denied name is not
defined.

Resolved 2026-11-08 (M11 slice 2): `Capabilities` in `novalang.py` for the bytecode VM and the tree-walker, `configure_sandbox` in `novalang.nova` for the self-hosted interpreter. A denied name is not defined (the VM looks gated names up when the program runs, `LOAD_BUILTIN`, so one compiled script is right for either profile); the names stay reserved, so `let read = 1` is the same error in both profiles.
### D-041 — No path confinement

Status: resolved
Class: implementation bug
Engines: bytecode VM, tree-walker, self-hosted
Spec: `[sbx.paths]`

A program can read, write or import any path the process can reach: through `..`, an
absolute path, or a name that does not exist yet. A module is found outside its own
folder (`import "../outside.nova"` ran). There is no `FileError: <path> is outside the
folders this program may use`. Closed by slice 2 of M11.

Fix: resolve every path to its real path and compare it with the granted folders before
touching the file system.

Resolved 2026-11-08 (M11 slice 2): every path argument and every `import` is resolved with `realpath` and compared with the granted folders (`..`, absolute paths, symbolic links, a sibling folder that shares a prefix, a path that does not exist yet) before the file system is touched. The self-hosted interpreter uses the new host function `realpath` (`[host.files]`).
### D-042 — Size, depth and nesting limits are missing, or end in the host's failure

Status: resolved
Class: implementation bug
Engines: bytecode VM, tree-walker, self-hosted
Spec: `[sbx.limits]`, `[sbx.errors]`

The fixed limits of `[port.limits]` exist for `*`, `append` and `range`, and the depth and
integer-digit limits match the specification. Missing: a size limit on `+` of lists and
strings, `join`, `pad`, `replace_all`, `str` of a structure, `split`, `read` and `input`,
and any limit on dictionary entries; none of the limits can be set lower. `s = s + s`
forty times, or the same with a list, ends with a raw Python `MemoryError`. A program
nested 20,000 brackets deep ends with Python's `RecursionError`: the command line turns
it into `the interpreter ran out of stack - recursion too deep`, the library does not, and
the self-hosted interpreter reports `InternalError: RecursionError`. Closed by slice 3 of M11.

Fix: check each size from the operands before the memory is used, with the error of the
row; turn `RecursionError` and `MemoryError` into the error of the nearest row.

Resolved 2026-11-08 (M11 slice 3): every size is checked from the operands (or, for a built-in that cannot produce more than a small multiple of them, from the result) with the error of its row; the limits can be lowered (`limits={"list": ...}`); a program nested too deeply is `NovaError: the interpreter ran out of stack - recursion too deep` on all three engines (the self-hosted parser has its own limit of 100 levels, the specification's minimum). A Python `MemoryError` can no longer reach a restricted program.
### D-043 — No step budget, time limit or output limit

Status: resolved
Class: implementation bug
Engines: bytecode VM, tree-walker, self-hosted
Spec: `[sbx.limits]`

`while true { }` never ends, a program can write output without bound, and nothing can
stop a run after a time; `sleep` sleeps for as long as it was told. The game port and the
policy dialect already have a step budget. The three limits do not exist as
`LimitError` and none of them is uncatchable. Closed by slice 3 of M11.

Fix: count steps and check the clock in the same place; the three errors are of kind
`fatal` and `try` does not see them.

Resolved 2026-11-08 (M11 slice 3): the step budget, the time limit and the output limit exist on all three engines, end the run with `LimitError`, and cannot be caught: `try`, `catch` and `finally` never see one (`FatalLimit` is not even an `Exception` in the Python engines; the self-hosted `try` rethrows a message that begins `LimitError: `).
### D-044 — Sandbox settings are not read; a Python grant does not replace the default list

Status: resolved
Class: implementation bug
Engines: bytecode VM, tree-walker, self-hosted
Spec: `[sbx.capabilities]`, `[sbx.profiles]`

An engine has no `profile` and no grants. With `allow_python` the bridge accepts the whole
default list of `[py.import]`, which holds `re`, `random` and `datetime`: three modules
that would give back the `regex`, `random` and `clock` capabilities. Closed by slice 2 of M11.

Fix: `python=[...]` names the only modules `python.import` accepts.

Resolved 2026-11-08 (M11 slice 2): the `python` grant names the only modules `python.import` accepts, on all three engines; the plain `--allow-python` is refused with `--profile restricted`.
### D-045 — The self-hosted interpreter has no type gate in the restricted profile

Status: open
Untested: it needs an annotated module with a wrong type, imported by a restricted program; the case is added in slice 6 of M11
Class: implementation bug
Engines: self-hosted
Spec: `[sbx.profiles]`

The self-hosted interpreter reads the program and its modules itself, so its launcher type-checks the whole import graph
before it starts (`bootstrap.py`). In the restricted profile that walk would read modules wherever the program's import
paths point before any grant is consulted, so it is skipped: a program whose annotations are wrong is not refused
there, while the bytecode VM and the tree-walker refuse it when the module is loaded. Not a way out of a grant; a
difference in what is refused.

Fix: type-check each module as it is imported, after the path check, as the host does.

### D-046 — The self-hosted interpreter counts output in characters, and times a run by the wall clock

Status: open
Untested: it needs non-ASCII output, or a change of the system clock during a run, which a corpus case cannot arrange portably
Class: implementation bug
Engines: self-hosted
Spec: `[sbx.limits]` (output, time)

The output limit is in **bytes**. The Python engines count the UTF-8 bytes of what `print` and `log` write; the self-hosted
interpreter, which has no way to ask for a byte length, counts characters, so for non-ASCII text it lets through up to
four times as much. Its time limit reads the host's `time()` (the wall clock) where the Python engines read a monotonic
clock, so a clock set back during a run lengthens the run. Neither is a way past a limit by more than a small factor.

Fix: a host function for the byte length of a text, and a monotonic clock for the self-hosted engine's own use.

## Not divergences, but worth knowing

The bytecode VM and the tree-walker agree on every corpus case, which is the
guarantee `tests/vm/` already enforces on a much larger body of programs. The
host's error *report* (source line, caret, call frames) is not part of the
language and is not compared for any engine.
