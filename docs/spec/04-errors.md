# 4. Errors

## [err.model] What an error is

An error has a **label**, a **message** and, when it comes from a place in the
program, a **position**. Its text is `Label: message`, for example
`NovaError: division by zero`. The label is `NovaError` unless the error
belongs to a family that names itself: `TypeError` for built-in functions
given a value they cannot use (`TypeError: sqrt() needs a number that is not
negative`), `FileError` and `PythonError` for the host, and `Error` for a
program's own `throw`.

The message text in the catalogue below is part of the contract: a conforming
host reports these messages, with the dynamic parts filled in, character for
character. A host MAY report more than the label and message when it shows an
error to a person (the source line, a caret under the position, a list of the
active calls); that report is not part of the language and is not compared.

A position names a line. The host SHOULD report the 1-based line of the
construct at fault, for errors that have a place in the source (a runtime error
inside a function reports the line inside the function). Some errors have none:
`'return' only makes sense inside a function`.

```
print("a")
print("b")
let x = 1 / 0           # NovaError: division by zero   (line 3)
```

## [err.uncaught] An error nobody catches

An error that reaches the top of the program stops it. Everything the program
printed before it stays printed, nothing runs after it, and the program's exit
status is 1. A program that finishes has status 0, and `exit(n)` ends it at
once with status `n`.

Lexical and syntax errors (`[err.lexical]`, `[err.syntax]`) are found before
any statement runs, so a program with one prints nothing.

## [err.try-catch] `try` and `catch`

```
try { body } catch name { handler }
try { body } catch { handler }
```

If `body` finishes normally, `handler` is skipped. If an error occurs in
`body`, including inside a function the body calls, the rest of `body` is
abandoned and `handler` runs. `name`, if given, is a local of the handler
holding the error's **message as a string**: `Label: message` when the label is
not `NovaError`, and the bare message when it is.

```
try { 1 / 0 } catch e { print(e) }        # division by zero
try { sqrt(-1) } catch e { print(e) }     # TypeError: sqrt() needs a number that is not negative
```

An error inside a handler is a new error and goes to the enclosing `try`, so a
handler can add context and throw again. Lexical and syntax errors are not
catchable, because they are found before the program runs. `try` with neither
`catch` nor `finally` is `a 'try' needs a 'catch', a 'finally', or both`, and a
`catch` with no `try` is `unexpected 'catch'`.

## [err.finally] `finally`

`try { ... } finally { ... }` (with or without a `catch`) runs the `finally`
block after the body and the handler however they end: normally, by an error
that continues outward afterwards, or by `return` from a function.

```
try { throw("a") } finally { print("fin") }    # prints fin, then the error goes on
```

## [err.throw] `throw`

`throw(text)` raises an error whose message is `text`, with label `Error`.
Uncaught it prints `Error: text` and the program stops; caught, `name` is
`text` itself. The argument MUST be a string:
`throw needs a string, but got a number - use str() to convert it`; `throw` takes
exactly one argument.

## The catalogue

Messages are grouped by what kind of fault they report. `<...>` marks a part that
varies.

## [err.lexical] Lexical errors

Found while reading the source (`[lex.*]`), before anything runs:

| Message | Where |
| --- | --- |
| `this string is never closed` | `[lex.strings]` |
| `this f-string is never closed` | `[lex.fstrings]` |
| `unknown escape '\<c>'` | `[lex.escapes]` |
| `a number cannot have two decimal points` | `[lex.numbers]` |
| `unexpected character '<c>'` | `[lex.identifiers]`, `[lex.operators]` |
| `'!' on its own is not an operator - did you mean '!=' or 'not'?` | `[lex.operators]` |
| `this number has too many digits` | `[lex.numbers]`, `[port.integers]` |
| `this f-string placeholder is empty` | `[lex.fstrings]` |
| `this f-string placeholder needs a closing '}'` | `[lex.fstrings]` |
| `a '}' inside an f-string must be written '}}'` | `[lex.fstrings]` |

## [err.syntax] Syntax errors

Found while parsing, before anything runs. The message says what was expected
and what was found; `found` is followed by the token in quotes, or by a
description: `the end of the line`, `the end of the input`, `the string 's'`, or
a number. These are the messages the corpus pins:

| Message |
| --- |
| `unexpected '<token>'` |
| `the expression ends too early` |
| `expected a name after 'let', found <what>` |
| `expected a '=' after the name in a 'let', found <what>` |
| `expected a function name after 'def', found <what>` |
| `expected a new line between statements, found <what>` |
| `expected a ')' to close the argument list, found <what>` |
| `expected a ']' to close the list, found <what>` |
| `expected a key name, found <what>` / `expected a ':' after the key, found <what>` |
| `the key '<k>' appears twice in this dictionary` |
| `the left side of '=' must be a variable, a list item or a field` |
| `chained comparisons like 'a < b < c' are not supported yet` |
| `parameter '<p>' is listed twice` |
| `a 'try' needs a 'catch', a 'finally', or both` |

## [err.name] Name errors

`undefined name '<name>'` for a name that is not defined where it is read
(`[scope.global]`), including a call to such a name. The built-in names are
protected by `'<name>' is a built-in function and cannot be used as a variable
name` (`a function name`, `a parameter name`).

## [err.type] Type errors

An operation was given the wrong kind of value:

| Message | Where |
| --- | --- |
| `cannot use '<op>' on a <kind> and a <kind>` | `[expr.arithmetic]` |
| `cannot apply unary '<op>' to a <kind>` | `[expr.unary]` |
| `cannot compare a <kind> with a <kind> using '<op>'` | `[expr.ordering]` |
| `the left side of 'and' must be true or false, but it is a <kind>` (`'or'`, `the right side`) | `[expr.logic]` |
| `'not' needs true or false, but this is a <kind>` | `[expr.logic]` |
| `a '<if or while>' condition must be true or false, but this is a <kind>` | `[expr.logic]` |
| `a <kind> cannot be indexed` / `cannot be sliced` | `[expr.index]`, `[expr.slice]` |
| `a list index needs a whole number, but got <what>` | `[expr.index]` |
| `a dictionary key must be a string, but this is a <kind>` | `[expr.index]` |
| `'in' can only look for a string inside a string, not a <kind>` | `[expr.in]` |
| `<fn>() needs a list, a string or a dictionary, but got a <kind>` | built-ins |
| `strings cannot be changed in place - build a new one instead` | `[scope.assign]` |

`<kind>` is `number`, `string`, `boolean`, `list`, `dictionary` or `function`
(note: `dictionary`, where `type()` says `dict`).

## [err.value] Value errors

The kind is right, the value is not:

| Message | Where |
| --- | --- |
| `index <i> is out of range for a list of <n> item(s) - valid indexes are <lo> to <hi>` | `[expr.index]` |
| `this dictionary has no key '<k>' - it has <keys>` | `[expr.index]`, `[expr.member]` |
| `a slice bound needs a whole number, but got <what>` | `[expr.slice]` |
| `a string cannot be repeated a negative number of times` | `[expr.strings]` |
| `string repetition needs a whole number, but got <n>` | `[expr.strings]` |
| `a list cannot be repeated a negative number of times` | `[expr.lists]` |
| `list repetition needs a whole number, but got <n>` | `[expr.lists]` |
| `num() cannot read a number from "<text>"` | `[val.types]` |
| `a 'for' step must be greater than zero (use 'downto' to count down)` | `[scope.loop-var]` |
| `pop() cannot take anything from an empty list` | built-ins |
| `<fn>() needs a finite number, but got inf` (or `-inf`, `nan`) | `[port.floats]` |
| `the <start, end or step> of a 'for' range must be a finite number, but this is inf` | `[port.floats]` |
| `num(): that number has too many digits` | `[port.integers]` |
| `TypeError: json.loads(): that number has too many digits` | `[port.integers]` |
| `repeating that list <n> times would exceed 1000000 items` / `repeating that string <n> times would be too long` / `range() would build a list of <n> items, which is too large` | `[port.limits]` |
| `call depth of <N> exceeded - is the recursion missing a base case?` | `[port.limits]` |
| `TypeError: pow(): 0.0 cannot be raised to a negative power` | built-ins |

## [err.arithmetic] Arithmetic errors

`division by zero`, `integer division by zero` and
`cannot take the remainder of a division by zero` (`[expr.division]`). There is
no infinity or NaN to return, so these are errors. An integer too large to be a
float, used with a float or divided, is
`a number is too large for this operation - an integer beyond the range of a
float cannot be divided or mixed with a float` (`[port.integers]`); a built-in
given one reports `TypeError: <fn>(): a number is too large for this function`.
An integer result of 4,000 digits or more is
`the result has too many digits - an integer cannot have more than 4000 digits`
(`[port.integers]`).

## [err.call] Call errors

`<f>() expects <n> argument(s) but got <m>` for a user function,
`<f>() takes <n> argument(s) but got <m>` for a built-in, and
`<kind> is not a function, so it cannot be called` (`[expr.call]`).
