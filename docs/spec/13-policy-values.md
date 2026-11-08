# 13. The policy dialect: values, operators and built-in functions

Source text, syntax and statements are `12-policy-syntax.md`; this chapter says
what the values of the policy dialect are, what the operators do to them, and what
the 33 built-in functions do. The rule engine and its functions (`held`, and the
host functions a game registers) are `14-policy-engine.md`.

**Errors in this chapter.** An error stops the program (`[pol.errors]`). Its text is
`line N: message` except for the **operator errors** (`expected a number, got
string` from `-`, `*`, `<`, ...), which have no line: an operator has no place of
its own in the source, so the text is the bare message. Errors from built-in
functions and from indexing have the line of the call or the access.

## [pol.types] Values

There are seven kinds of value, and `type(v)` answers their name:

| Kind | `type()` | Notes |
| --- | --- | --- |
| null | `null` | the one value `null`; what a function without `return` gives |
| boolean | `bool` | `true`, `false` |
| number | `number` | a 64-bit float; whole numbers are not a separate kind |
| string | `string` | a sequence of characters (Unicode code points); `len` counts them |
| list | `list` | ordered, mutable, may hold any values |
| dictionary | `dict` | text keys in insertion order, mutable, any values |
| function | `func` | made by `func`; closes over its scope (`[pol.func]`) |

Lists and dictionaries are **shared, not copied**, when assigned, passed or stored:
every name for one sees a change made through another. Strings and numbers cannot
be changed, only replaced. Built-in functions are not values (`[pol.calls]`), so
`type(len)` is `unknown identifier 'len'`.

## [pol.num-display] How a number is written

Wherever a number becomes text (`print`, `str`, `+` with a string, `join`, an error
message), it is written as follows, character for character, so every host
shows the same text:

1. NaN is `nan`; positive infinity is `inf`; negative infinity is `-inf`.
2. A number with no fractional part whose magnitude is below `1e15` is written as a
   whole number with no point: `42`, `-7`, `100000000000000`. Negative zero is
   `0`.
3. Any other number is written with **exactly six digits after the point**, as the
   exact decimal value of the float rounded to six places (the result of a C
   `printf("%.6f")`), then every trailing `0` is removed, then a trailing `.`:
   `1.5`, `0.333333`, `123456789.123457`, `-0.25`, `1000000000000000` (a whole
   number of `1e15` or more keeps all its digits).

Consequences that are part of the rule: a number that rounds to zero at six places
is written `0`, or **`-0` if it was negative** (`-0.0000004` is `-0`); `0.1 + 0.2` is
`0.3`; `1/3` is `0.333333`. The exact digits of a whole number above about
`1e22` are those of the float's exact value, which depends on the host's
formatting library; cases stay below that.

## [pol.text] The display text of a value

`print`, `str`, `join`, `split`, `contains`, `upper`, `lower` and `+` with a string
turn a value into text the same way:

- `null`, `true`, `false` are those words; a number is `[pol.num-display]`; a string is
  itself;
- a list is `[` its items separated by `, ` and `]`; a dictionary is `{` then
  `key: value` pairs separated by `, ` and `}`; a function is `<func name>` or
  `<func anonymous>`;
- **inside a list or dictionary, a string is wrapped in double quotes and nothing
  inside it is escaped** (`["a\nb"]` shows the real line feed between the quotes); a
  dictionary key is written bare, not quoted: `{a: 1, b c: "x"}`.

At the top level a string is not quoted: `print("a", ["a"])` shows `a ["a"]`.
Collections nest to any depth with the same rule. **A display text of more than 1,000,000
characters is an error** (`a string cannot have more than 1000000 characters`, `[pol.limits]`)
where the dialect makes one, and it is detected as the text is built, so a structure that
shares its parts with itself is refused at once.

## [pol.truthiness] What counts as true

Where a value is used as a condition (`if`, `while`), as an operand of `and`, `or`
or `not`, or by `bool()`, **`false`, `null`, the number `0`, the empty string, the
empty list and the empty dictionary are false and everything else is true**:
`"0"`, `" "`, `"false"`, `[0]`, `[null]`, `{a: 0}`, a function, a negative
number and NaN are true. No condition is an error because of its kind.

## [pol.equality] Equality

`a == b` and `a != b` never fail and never convert: **values of different kinds are
never equal** (`1 == "1"`, `true == 1`, `null == false`, `0 == ""` are all false).
Within a kind: numbers by value (`1 == 1.0`; NaN is not equal to anything, itself
included; `inf == inf`), strings by characters (case matters), booleans and null
trivially; lists by length and then item by item; dictionaries by having the same
set of keys with equal values, whatever their order; functions only if they are the
same function value (`f == g` after `let g = f`, but never two separately written
`func`s). The comparison is deep and sees through sharing.

## [pol.arith] Arithmetic

`+ - * / %` and prefix `-` work on numbers. A **boolean counts as a number** (`true`
is 1, `false` is 0), so `2 + true` is 3 and `-true` is -1. Any other kind is an error:
`expected a number, got null` (the kind is `null`, `string`, `list`, `dict` or
`func`), with no line. The left operand is checked before the right. Both operands
are evaluated before either is checked, so an error in an operand wins.

- `+` is also concatenation, `[pol.concat]`.
- **Division by zero is zero**: `x / 0` is `0` for any `x`, NaN and infinity
  included, and **`x % 0` is `0`**. Neither is an error.
- `%` is the C `fmod`: the result has the sign of the left operand, `-7 % 3` is
  `-1`, `7 % -3` is `1`, `7.5 % 2` is `1.5`.
- Numbers are IEEE 64-bit floats: `inf - inf` and `inf * 0` are NaN, `1 / inf` is `0`,
  there is no overflow error.

## [pol.concat] `+` with strings and lists

If **either** operand of `+` is a string, the result is the string made of the
display text (`[pol.text]`) of the left operand followed by that of the right, whatever
the other kind is: `"n=" + 42` is `n=42`, `"x" + null` is `xnull`, `1 + "a"` is `1a`,
`"v=" + [1, "x"]` is `v=[1, "x"]`. A result of more than 1,000,000 characters is the
error of `[pol.text]` (with no line, as an operator error). It associates to the left, so `"a" + 1 + 2` is
`a12` and `1 + 2 + "a"` is `3a`.

If both are lists, the result is a **new** list with the items of the left and then the
right (the originals are untouched, and the items themselves are shared); if it would have
more than 1,000,000 items the operator fails with `a list cannot have more than 1000000 items`
(`[pol.limits]`, no line). Anything else
is `[pol.arith]`: `[1] + 2`, `{} + {}` and `null + [1]` are `expected a number, got
list` (or `dict`, `null`: the first operand that is not a number or boolean).

## [pol.compare] Ordering

`<  >  <=  >=` compare **numbers only** (and booleans as 0 and 1): `1 < 2`,
`false < true`. Strings, lists, null and the rest are refused with `expected a number,
got string` (no line), so **strings cannot be ordered**. A comparison involving NaN is
false. Comparison operators can be chained and mean `(a < b) < c`, so `1 < 2 < 3` is
`true < 3`, which is `true`, and `2 < 1 < 3` is `false < 3`, also `true`.

## [pol.logic] `and`, `or`, `not`

`not v` is `true` if `v` is false (`[pol.truthiness]`) and `false` otherwise. `a and b`
is `false` if `a` is false, without evaluating `b`, and otherwise the truthiness of
`b`; `a or b` is `true` if `a` is true, without evaluating `b`, and otherwise the
truthiness of `b`. **The result is always `true` or `false`, never an operand**: `0 or 3` is
`true` and `"" or "x"` is `true`. Evaluation is left to right.

## [pol.index] Reading with `[]` and `.`

`a[i]` and `a.name` read one element; `a.name` is `a["name"]`.

- **List.** `i` must be a number (`list index must be a number` for a string, a
  boolean, `null` or anything else, which includes `a.name`). Its **whole part**
  (truncated toward zero) is used: `a[1.9]` is `a[1]`, `a[-0.5]` is `a[0]`. A
  negative index counts from the end (`a[-1]` is the last item). One outside the
  list is `list index 5 out of range (size 1)`, showing the whole part as given
  (`-2`, not the adjusted index).
- **String.** The same, giving a one-character string; the error is `string index
  2 out of range (length 2)` and `string index must be a number`. `s.length` is
  that error, as the string has no members.
- **Dictionary.** The key is turned into text (`[pol.dict-keys]`); a key that is not
  there is `dict has no key 'z'`, with the key's text between the quotes exactly as
  it is (a key containing `'` or `\` is not escaped).
- **Anything else** is `cannot index a number` (or `null`, `bool`, `func`).

**A number used as an index, a position or a count must be finite.** Infinity and NaN
have no whole part, so as an index (reading or writing) or as an argument of `slice`,
`remove_at` or `range`, they are `expected a finite number, got inf` (`-inf`, `nan`).

Writing with `a[i] = v` follows the same rules (`[pol.assign]`).

## [pol.dict-keys] Dictionary keys

A dictionary's keys are always strings. Whatever is used as a key (in `{[k]: v}`,
`d[k]`, `d[k] = v`, `has`, `get`) that is not a string is first turned into its
display text, so `d[1]`, `d[1.0]` and `d["1"]` are one entry, `d[true]` is the key
`true`, `d[null]` is `null`, and `d[[1, "a"]]` is the key `[1, "a"]`. `keys(d)` therefore only ever
returns strings. A key written twice keeps its
first position and the later value; a new key goes last.

## [pol.lib] Built-in functions: calling them

The built-in functions are a fixed set of 33 names:

```
abs min max clamp exp sqrt floor round pow ramp lerp pick rand held
type str num bool int
len keys has get append remove_at slice range join split contains upper lower
print
```

A call passes the arguments, already evaluated (`[pol.calls]`). **A call needs at least as
many arguments as the function's minimum; it may pass more, which are ignored**
(except by `min`, `max`, `pick` and `print`, which use them all). With fewer, the
error is `clamp() needs 3 argument(s), got 1`. The minimum is 1 for `abs min max exp
sqrt floor round ramp pick type str num bool int len keys upper lower range`; 2 for
`pow rand held has append remove_at join split contains`; 3 for `clamp lerp get slice`;
and 0 for `print`. A built-in that is given an argument of the wrong kind fails with
the message in its section. All these errors have the line of the call. `held` is
`14-policy-engine.md`.

## [pol.lib-math] Numeric functions

Every argument is a number (a boolean counts); anything else is `expected a number,
got string` (with the line of the call).

- `abs(x)`: magnitude. `abs(-1e400)` is `inf`.
- `min(a, b, ...)` and `max(a, b, ...)`: the smallest and largest of **one or more**
  numbers. A list is refused (`min([1, 2])` is `expected a number, got list`).
- `clamp(v, lo, hi)`: `lo` if `v < lo`, otherwise `hi` if `v > hi`, otherwise `v`. With
  `lo > hi` the test on `lo` comes first: `clamp(5, 1, 0)` is `0`, `clamp(-5, 1, 0)` is `1`.
- `exp(x)`: e to the power of `x`, **with `x` first limited to between -700 and 700**,
  so `exp(1000)` is `exp(700)` and nothing overflows.
- `sqrt(x)`: the square root, **of 0 if `x` is negative**.
- `floor(x)`: the largest whole number not above `x`. For infinity and NaN it returns
  its argument.
- `round(x)`: **half away from zero**, computed as `floor(x + 0.5)` for `x >= 0` and
  `-floor(-x + 0.5)` otherwise, so `round(2.5)` is 3, `round(-2.5)` is -3, `round(0.4)`
  is 0, and (as the formula says) `round(0.49999999999999994)` is 1. Infinity and NaN
  are returned unchanged.
- `pow(base, exponent)`: C `pow`. Overflow saturates to infinity, with the sign
  negative only for a negative base and an odd whole exponent (`pow(10, 400)` is `inf`,
  `pow(-10, 401)` is `-inf`, `pow(-10, 400)` is `inf`). `pow(0, -1)` is `inf`. A
  negative base with a fractional exponent is NaN (`pow(-8, 1/3)`).
- `ramp(x)`: `x` limited to 0 through 1. `lerp(a, b, t)`: `a + (b - a) * t` with `t`
  limited to 0 through 1.
- `int(x)`: `x` with its fractional part removed (toward zero), as a number:
  `int(2.9)` is 2, `int(-2.9)` is -2. Infinity and NaN are returned unchanged; very
  large numbers are already whole and unchanged. `int("7")` is an error (the string is
  not a number): use `num`.

## [pol.lib-convert] Type and conversion functions

- `type(v)`: the name of `v`'s kind (`[pol.types]`).
- `str(v)`: the display text of `v` (`[pol.text]`); a string is returned as it is.
- `bool(v)`: `true` or `false` by `[pol.truthiness]`.
- `num(v)`: for a number, itself; for a boolean 1 or 0; for **a string, the number it
  reads as**; anything else (`null`, list, dictionary, function) is `expected a
  number, got null`. A string reads as a number only in this form, ASCII only: an
  optional `+` or `-`, digits with an optional point (`2.5`, `5.`, `.5`, `007`), an
  optional exponent (`e` or `E`, an optional sign, digits), with spaces, tabs, line
  feeds and carriage returns allowed around it; a result beyond the float range is
  infinity (`num("1e999")`). **Any other string, including the empty string, gives
  0**: `num("bad")`, `num("12abc")`, `num("0x10")`, `num("1_0")`, `num("1,5")`,
  `num("inf")`, `num("nan")` and digits of other scripts are all `0`.

## [pol.lib-collections] Lists, dictionaries and strings

- `len(v)`: the number of characters, items or entries. Anything else is `len() needs
  a list, dict or string`.
- `keys(d)`: a new list of the dictionary's keys in order (`keys() needs a dict`).
- `has(c, x)`: for a dictionary, whether the key (as text, `[pol.dict-keys]`) is
  present; for a list, whether some item `== x` (`[pol.equality]`); otherwise `has()
  needs a dict or list` (a string is refused).
- `get(d, key, fallback)`: the value for the key, or `fallback` if absent (`get() needs
  a dict`). All three arguments are required.
- `append(list, x)`: adds `x` at the end of the list **in place** and returns that same
  list (`append() needs a list`); to a list that already has 1,000,000 items it fails with
  `a list cannot have more than 1000000 items`.
- `remove_at(list, i)`: removes the item at the whole part of `i` and returns it. The
  index must be inside the list, and **a negative index is not counted from the end**:
  `remove_at() index 1 out of range (size 1)`, `index -1` likewise. `remove_at() needs a
  list` for another kind.
- `slice(x, start, end)`: a **new** list, or a string, of the items or characters from
  position `start` up to but not including `end`. Both are whole parts, **a negative one
  is taken as 0**, and a position past the end stops at the end: `slice([1, 2, 3], -2,
  3)` is the whole list and `slice("hello", 1, 3)` is `el`. `end <= start` gives an
  empty list or string. `slice() needs a list or string` for another kind.
- `range(n)` and `range(a, b)`: a new list of numbers, the whole numbers from 0 up to
  but not including `n`, or from `a` up to but not including `b`; empty if there are
  none (`range(5, 2)`, `range(-3)`). Whole parts are used. A third argument is ignored.
  A list cannot have more than 1,000,000 items (`[pol.limits]`): a `range` that would make a longer one
  fails at once with `a list cannot have more than 1000000 items`, before anything is built.
  The step budget does not count the items a built-in makes, which is why the size is limited.

## [pol.lib-text] Text functions

All of these first turn a non-string argument into its display text (`[pol.text]`),
except `join`'s first argument.

- `join(list, separator)`: the display text of the items with the separator between
  them. `join() needs a list` for another kind. `join([], ",")` is the empty string.
- `split(s, separator)`: a list of the pieces of `s` between occurrences of the separator,
  scanning from the left, **a plain string and not a pattern**. `split("a,,b", ",")` is
  `["a", "", "b"]`, `split("", ",")` is `[""]`, `split(",", ",")` is `["", ""]`. **An empty
  separator splits into characters** (`split("ab", "")` is `["a", "b"]`; `split("", "")` is
  `[]`).
- `contains(s, t)`: whether the text `s` has the text `t` inside it, case-sensitive; every
  text contains the empty one.
- `upper(s)`, `lower(s)`: the text with its letters converted to upper or lower case. For
  the ASCII letters this is exact; **for other letters the result is the host's** (Python
  converts `ß` to `SS`; a port may not), and cases do not test them.

## [pol.lib-random] `pick` and `rand`

`pick(a, b, ...)` returns one of its arguments, chosen at random (with one argument, that
argument, even a list: `pick([1, 2])` is the list). `rand(lo, hi)` returns a random number
from `lo` up to `hi`; with equal bounds that number. The generator belongs to the host and
is **seeded by it**: the policy dialect promises the range of the result and that a host that
starts from the same seed in the same order of calls gets the same sequence, not which
sequence it is (the Python engine and the Godot port use different generators, so a
program's `pick` and `rand` results are not portable between them).

## [pol.lib-print] `print`

`print(a, b, ...)` adds one entry to the program's output: the display text of its arguments
(`[pol.text]`) joined with single spaces, which is the empty string for no arguments. It
returns `null`. An entry is one call, not one line: a string with line feeds in it is one
entry. The host decides where the entries go (a console, an event log). The arguments are
evaluated before anything is written, so `print("a", nope)` writes nothing.
