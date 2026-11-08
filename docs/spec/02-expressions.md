# 2. Values and expressions

## Values

## [val.types] Kinds of value

There are seven kinds of value. `type(x)` returns the name in the left column.

| `type(x)` | Values |
| --- | --- |
| `"number"` | integers and floats (`[val.numbers]`) |
| `"string"` | sequences of characters (`[lex.strings]`) |
| `"boolean"` | `true` and `false` |
| `"list"` | ordered, mutable sequences of values |
| `"dict"` | mappings from string keys to values; entries keep insertion order |
| `"function"` | user functions (`def`) and built-in functions |
| `"nothing"` | the value of a call that returns nothing |

`nothing` has no literal and no name. It is what `f()` produces when `f` has no
`return` or a bare `return`; `type(f())` is `"nothing"`. A name that is never
defined, such as `nothing`, is an error (`[err.name]`).

Lists, dictionaries and functions are *references*: giving one a second name
does not copy it (`[scope.references]`). Numbers, strings and booleans behave as
values.

`num(text)` reads a number from a string (leading and trailing ASCII whitespace,
`[lib.text]`, is ignored) and `str(x)` converts any value to a string. `num` of something that
is not a number is an error: `num() cannot read a number from "x"`.

## [val.numbers] Numbers

A number is an integer of at most 4,000 decimal digits or a float (an IEEE 754
double). `type` does not tell them apart, and they compare equal when their
values are equal: `1 == 1.0`. Integer arithmetic is exact: `99999999999999999999
+ 1` is `100000000000000000000`. An integer that would pass 4,000 digits is an
error, not a rounded or wrapped value (`[port.integers]`).

An operation on two integers gives an integer, except `/`, which gives an
integer when the quotient is whole (`10 / 2` is `5`) and a float otherwise. If
either operand is a float the result is a float.

## [val.display] How values print

`print` and `str` write a value as follows.

| Value | Text |
| --- | --- |
| integer | its decimal digits |
| float | `5.0` prints `5`, `0.1 + 0.2` prints `0.30000000000000004`; the exact rules, including exponents, `inf` and `nan`, are in `[port.floats]` |
| string | the characters themselves; inside a list or dictionary, in double quotes with `\\`, `\"`, `\n` and `\t` escaped |
| `true`, `false` | `true`, `false` |
| `nothing` | `nothing` |
| list | `[` the items, separated by `, `, `]` |
| dictionary | `{` `key: value` pairs separated by `, `, `}`; a key prints bare when it is a name and in double quotes otherwise |
| user function | `<function name(params)>` |
| built-in function | `<built-in function name>` |

`print(a, b, ...)` writes the texts separated by single spaces and a line end.
`print()` writes an empty line.

```
print([1, "a", true, [2], {k: 1}], {}, [])     # [1, "a", true, [2], {k: 1}] {} []
print({"a": 1, "b c": 2})                       # {a: 1, "b c": 2}
```

## [val.equality] Equality

`==` and `!=` compare any two values and never fail. Values of different kinds
are never equal (`1 == "1"`, `true == 1` and `[] == {}` are all `false`);
there is no conversion. Numbers are equal when their values are, whatever their
form. Strings are equal when their characters are. Lists are equal when they
have the same length and equal items in order. Dictionaries are equal when they
have the same keys with equal values, whatever the order. Functions are equal
only to themselves.

## Expressions

## [expr.literals] Literals

A literal is a number (`[lex.numbers]`), a string (`[lex.strings]`), `true`,
`false`, a list `[a, b, ...]` or a dictionary `{key: value, ...}`. List and
dictionary literals nest and may be empty; items are evaluated left to right.

## [expr.lists] Lists

`a + b` joins two lists into a new one. `list * n` and `n * list`, with `n` a
whole number that is not negative, repeat a list into a new one
(`[0] * 3` is `[0, 0, 0]`); a negative count is
`a list cannot be repeated a negative number of times` and a fractional one is
`list repetition needs a whole number, but got 1.5`. Neither operation changes
its operands. A comma separates items and a trailing comma is a syntax
error (`unexpected ']'`); a missing one is
`expected a ']' to close the list, found 2`. `a + 2`, a list plus a non-list, is
a type error.

## [expr.dicts] Dictionaries

A key is a name or a string literal (keywords are allowed: `[lex.keywords]`);
`{a: 1}` and `{"a": 1}` are the same. A key that appears twice in a literal is
an error: `the key 'a' appears twice in this dictionary`. Other keys
(`{1: 2}`) are `expected a key name, found 1`. There is no trailing comma
(`expected a key name, found '}'`), and a missing colon is
`expected a ':' after the key, found 1`.

`a + b` of two dictionaries is a new dictionary with the entries of both, the
right operand winning on a shared key. `dict * 2` is a type error.

## [expr.newlines] Line ends inside expressions

A line end ends a statement (`[lex.newlines]`), so an expression cannot be
continued on the next line after an operator, a comma in a call, an opening
parenthesis or the `=` of a `let`: each of those is `the expression ends too
early`. The exception is the contents of list and dictionary literals, where
line ends between the items are ignored:

```
let d = {
a: 1,
b: 2
}
```

A block's `{` MAY be on the line after its `if`, `while`, `def` or `for` header,
and `else` MAY start the line after the `}` that closes the `if` block.

## [expr.group] Parentheses

`( expression )` groups. It changes only the order of evaluation.
A parenthesis that is never closed is a syntax error.

## [expr.precedence] Precedence and associativity

From lowest to highest binding:

| Level | Operators | Grouping |
| --- | --- | --- |
| 1 | `or` | left |
| 2 | `and` | left |
| 3 | `not` | prefix |
| 4 | `==` `!=` `<` `>` `<=` `>=` `in` | none (`[expr.chaining]`) |
| 5 | `+` `-` | left |
| 6 | `*` `/` `//` `%` | left |
| 7 | unary `+` `-` | prefix |
| 8 | call `f(...)`, index `a[i]`, slice `a[i:j]`, member `a.k` | left |

So `not 1 == 2` is `not (1 == 2)`, `not true and false` is `(not true) and false`,
and `2 + 3 * 4` is 14. There is no power operator.

## [expr.unary] Unary plus and minus

`+x` and `-x` apply to numbers. On any other kind they are an error:
`cannot apply unary '-' to a string`. Unary operators bind tighter than the
binary ones: `-2 * -3` is 6 and `1 - -2` is 3.

## [expr.arithmetic] Arithmetic

`+`, `-` and `*` on two numbers give a number (`[val.numbers]`). `+` also joins
two strings, two lists and two dictionaries (`[expr.strings]`, `[expr.lists]`,
`[expr.dicts]`), and `*` repeats strings and lists. Any other pair of kinds is
an error naming the operator and both kinds: `cannot use '+' on a string and a
number`, `cannot use '*' on a boolean and a number`.

## [expr.division] Division

- `a / b` is true division: `7 / 2` is `3.5`, `10 / 2` is `5`.
- `a // b` is floor division, the quotient rounded toward minus infinity:
  `7 // 2` is 3, `-7 // 2` is -4, `7 // -2` is -4, `7.5 // 2` is 3.
- `a % b` is the remainder with the sign of `b`, so that
  `a == (a // b) * b + a % b`: `-7 % 3` is 2, `7 % -3` is -2, `7.5 % 2` is 1.5.

A zero divisor is an error, never infinity: `division by zero` for `/`,
`integer division by zero` for `//` (also for floats), and
`cannot take the remainder of a division by zero` for `%`.

## [expr.strings] Strings

`a + b` joins two strings; `string + number` and `number + string` are errors
(use `str()`). `string * n` and `n * string` repeat a string, `"ab" * 3` is
`"ababab"`, `"x" * 0` is `""`. `n` MUST be a whole number that is not negative:
`a string cannot be repeated a negative number of times`, and
`string repetition needs a whole number, but got 1.5`. `string * string` is an
error. A float with a whole value counts as whole.

## [expr.ordering] Ordering

`<`, `<=`, `>` and `>=` compare two numbers by value, or two strings by
character code (so `"B" < "a"`). Every other pair is an error, even two
booleans, two lists or two dictionaries: `cannot compare a list with a list
using '<'`, `cannot compare a number with a string using '<'`. The result is a
boolean.

## [expr.chaining] Comparison cannot be chained

Comparisons do not associate: `1 < 2 < 3`, `1 == 1 == 1` and
`x in a == true` are all syntax errors, `chained comparisons like 'a < b < c'
are not supported yet`. Parenthesise one side: `(1 < 2) == true`.

## [expr.logic] Boolean logic

`and`, `or` and `not` work on booleans only, and so do the conditions of `if`
and `while`. Other values are not "truthy" or "falsy"; they are errors:

- `the left side of 'and' must be true or false, but it is a number`
  (`'or'` likewise; `the right side of ...` for the second operand)
- `'not' needs true or false, but this is a number`
- `a 'if' condition must be true or false, but this is a number`
  (`'while'` likewise)

`and` and `or` evaluate their right operand only when the left one does not
decide the result, so `false and (1 / 0 == 0)` is `false` without an error.
The result is always a boolean.

## [expr.index] Indexing

`list[i]` and `string[i]` take the item at position `i`, counting from 0, with
negative positions counting from the end (`-1` is the last). `i` MUST be a
whole number; `1.0` counts. Otherwise:

- `a list index needs a whole number, but got 1.5` (also `a string`, `a boolean`)
- `index 2 is out of range for a list of 2 item(s) - valid indexes are -2 to 1`
  (for a string, `a string of 2 character(s)`)
- `a number cannot be indexed`

`dict[key]` takes the value of a string key. A missing key is an error that
lists the keys the dictionary has: `this dictionary has no key 'b' - it has a`.
A non-string key is `a dictionary key must be a string, but this is a number`.

Assigning to an index is covered with the statements (`[scope.assign]`); strings
cannot be changed in place.

## [expr.slice] Slicing

`a[i:j]` is a new list or string of the items from position `i` up to but not
including `j`. Either bound MAY be left out (`a[:2]`, `a[3:]`, `a[:]`), and a
negative bound counts from the end. Bounds beyond the ends are clamped, and a
range that is empty or backwards gives an empty result, so `a[10:]` and `a[3:1]`
are `[]`. A slice is always a copy. A bound MUST be a whole number
(`a slice bound needs a whole number, but got 1.5`); numbers and dictionaries
cannot be sliced (`a number cannot be sliced`).

## [expr.member] Member access

`d.name` is `d["name"]` for a dictionary, with the same missing-key error, and
`name` may be a keyword. `d.a.b` and `d["a"]["b"]` can be mixed.

## [expr.in] Membership

`x in c` is a boolean. For a list `c` it is whether some item equals `x`; for a
dictionary, whether `x` is a key; for a string, whether `x` is a substring (the
empty string is in every string). `1 in "abc"` is
`'in' can only look for a string inside a string, not a number`, and a
right operand that is not a list, string or dictionary is
`'in' needs a list, a string or a dictionary on its right, but got a number`.

## [expr.call] Calls

`f(a, b)` evaluates `f`, then the arguments left to right, then calls. A user
function MUST receive exactly as many arguments as it has parameters:
`f() expects 1 argument(s) but got 2`. A built-in function with a fixed number of
arguments reports `len() takes 1 argument(s) but got 0`. A function returns the
value of `return`, or `nothing`. Functions are values: they can be stored in
variables and lists and passed as arguments, and recursion is allowed.

Calling something that is not a function is an error:
`a number is not a function, so it cannot be called` (`nothing is not a function,
so it cannot be called` for `print(1)(2)`). Calling a name that is not defined
is `undefined name 'f'`.
