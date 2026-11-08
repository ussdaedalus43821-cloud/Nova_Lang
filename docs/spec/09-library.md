# 9. The core library

The built-in functions that compute and have no effect outside the program: they
work on values and nothing else. Printing is `print` (`[val.display]`); the
functions that touch files, the clock, randomness, the environment and the
process are the `host` profile and come in a later chapter. All of these are
global names that cannot be redefined (`[scope.reserved]`).

## [lib.calls] Calling a library function

A function with a fixed number of arguments called with another number is
`<f>() takes <n> argument(s) but got <m>` (`[err.call]`). The functions that take
a range of counts say what they take instead:

| Call | Error |
| --- | --- |
| `pop()`, `pop(l, i, x)` | `pop() takes a list and an optional index` |
| `range()`, `range(a, b, c, d)` | `range() takes 1, 2 or 3 numbers` |
| `split()`, `split(s, a, b)` | `split() takes a string and an optional separator` |
| `round()`, `round(x, n, m)` | `round() takes a number and an optional digit count` |
| `sorted()`, `sorted(l, d, x)` | `sorted() takes a list and an optional true or false` |
| `reduce(f)`, `reduce(f, l, a, b)` | `reduce() takes a function, a list and an optional starting value` |
| `assert()`, `assert(c, m, x)` | `assert() takes a condition and an optional message` |

An argument of the wrong kind is an error whose **label** depends on the
function, and the catalogue below gives each. The functions that compute with
numbers, lists and functions (`abs`, `round`, `floor`, `ceil`, `sqrt`, `pow`, the
trigonometric and logarithm functions, `min`, `max`, `sum`, `reverse`, `sorted`,
`map`, `filter`, `reduce`, `assert`, `json.dumps`) use `TypeError`
(`TypeError: abs() needs a number, but got a string`). The functions that work on
strings, collections and indexes (`len`, `keys`, `values`, `append`, `pop`,
`range`, `upper`, `lower`, `trim`, `split`, `join`, `pad`, `pad_left`,
`replace_all`, `split_lines`, `regex`, `json.loads` given a non-string) use the plain
`NovaError`. A caught error reads `TypeError: ...` for the first group and the
bare message for the second (`[err.try-catch]`).

## [lib.collections] Lists, dictionaries and ranges

- `len(x)` is the number of items of a list, characters (code points) of a string
  or entries of a dictionary. Anything else: `len() needs a list, a string or a
  dictionary, but got a number`.
- `keys(d)` and `values(d)` are new lists of a dictionary's keys and values in its
  order (`[port.order]`); `keys() needs a dictionary, but got a list`.
- `append(list, value)` adds to the **end of the list itself** and returns that
  same list. A first argument that is neither a list nor a file name is `append()
  needs a list or a file name as its first argument, but got a number` (a string
  first argument appends to a file, which is the `host` profile). A list cannot
  grow beyond 1,000,000 items (`a list cannot grow beyond 1000000 items`).
- `pop(list)` removes and returns the last item, `pop(list, i)` the item at `i`,
  counted as in `[expr.index]` (negative from the end). Errors: `pop() cannot take
  anything from an empty list`; `pop() needs a list as its first argument, but got
  a number`; and the index errors of `[expr.index]` (`index 5 is out of range for
  a list of 1 item(s) - valid indexes are -1 to 0`).
- `range(n)`, `range(a, b)` and `range(a, b, step)` are lists of whole numbers:
  from 0 (or `a`) up to **but not including** `n` (or `b`), by 1 (or `step`, which
  may be negative to count down). A range that is already past its end is `[]`.
  The arguments MUST be whole numbers, `2.0` counting (`range() needs a whole
  number, but got 1.5`), the step MUST NOT be zero (`range() cannot step by zero`)
  and the list is bounded (`[port.limits]`).
- `reverse(x)` is a new string with the code points of a string in the opposite
  order, or a new list with a list's items in the opposite order (`TypeError:
  reverse() needs a string or a list, but got a number`).
- `sorted(list)` is a new list in ascending order and `sorted(list, true)` in
  descending order; the argument itself is not changed.
  Numbers are ordered by value, strings by code point (`[port.text]`). A list that
  mixes numbers and strings is `TypeError: sorted() needs items that can be
  compared with each other`, a second argument that is not a boolean is `TypeError:
  sorted()'s second argument must be true or false`, and a first that is not a list
  is `TypeError: sorted() needs a list, but got a number`. What `sorted` does with
  lists, dictionaries, booleans or NaN as items is not specified (D-019).

## [lib.text] Strings

- `upper(s)` and `lower(s)` convert case, `trim(s)` removes whitespace from both
  ends. For ASCII text these are exact: the letters `a`-`z` and `A`-`Z` change,
  and the whitespace is space, tab, line feed, carriage return, vertical tab and
  form feed. What they do to other characters (`upper("ß")`, a no-break space) is
  the host's Unicode behavior and is not specified (D-020).
- `split(s, sep)` is the list of the pieces of `s` between non-overlapping
  occurrences of `sep`, scanning from the left; there is a piece (possibly `""`)
  on each side of every separator, so `split("a,b,,c", ",")` is `["a", "b", "",
  "c"]` and `split("", ",")` is `[""]`. `sep` MUST NOT be empty (`split() cannot use
  an empty separator`). `split(s)` with no separator splits on runs of whitespace
  and drops the empty pieces at the ends, so `split("  a  b ")` is `["a", "b"]` and
  `split("   ")` is `[]`.
- `join(list, sep)` is the items written as `str` writes them (`[val.display]`),
  separated by `sep`. `join([], ",")` is `""`. The first argument MUST be a list
  and the separator a string (`the separator of join() needs a string, but got a
  number`).
- `str(x)` is how `print` writes `x`, as a string.
- `pad(s, n)` adds spaces on the right and `pad_left(s, n)` on the left until `s` is
  `n` code points long. A string already `n` long or longer, or a negative `n`, is
  returned unchanged. `n` MUST be a whole number.
- `replace_all(s, old, new)` replaces every non-overlapping occurrence of `old`
  from the left with `new`. An empty `old` matches between every character and at
  both ends: `replace_all("abc", "", "-")` is `-a-b-c-`.
- `split_lines(s)` is the lines of `s` without their line ends. A line ends at a
  line feed, a carriage return or a carriage return followed by a line feed, and a
  line end at the very end of the text does not start another line:
  `split_lines("a\nb\r\nc\n")` is `["a", "b", "c"]` and `split_lines("")` is `[]`.
  Other separators (form feed, `U+2028`) are the host's (D-020).

A string argument of the wrong kind is `upper() needs a string, but got a number`;
for the second and later arguments the message names the role (`the separator of
split() needs a string`, `the text for replace_all() needs a string`).

## [lib.regex] `regex`

`regex(pattern, text)` is `true` if the pattern matches **anywhere** in the text.
The language specifies this much of the pattern syntax, which every host MUST
support with its usual meaning: literal characters; `.` (any one character except
a line feed); `[abc]`, `[a-z]` and `[^0-9]`; `*`, `+` and `?`; `|`; `(` `)`
grouping; `^` and `$` for the start and end of the text (`$` MAY also match just before a
final line feed). `\d`, `\w`, `\s` and `\b`
are supported for ASCII text; on other text they follow the host (D-021). More of
the host's regular-expression dialect may work but is not portable. A bad pattern
is `TypeError: regex(): bad pattern: <the host's reason>`, and only the part up to
the reason is specified. A pattern can take exponential time on some texts; the
language puts no limit on that (`[sec.limits]`).

## [lib.math] Numbers

- `abs(x)` is the magnitude; `abs(-0.0)` is `0`.
- `floor(x)` and `ceil(x)` are the whole number at or below, or at or above, `x`
  (`floor(-2.1)` is `-3`, `ceil(-2.9)` is `-2`); `round(x)` is the nearest whole
  number and **a tie goes to the even one**: `round(2.5)` is `2`, `round(3.5)` is
  `4`, `round(-2.5)` is `-2`. They refuse infinity and NaN (`[port.floats]`).
- `round(x, n)` rounds to `n` digits after the point (before it, if `n` is
  negative). The rule is the exact value of `x` rounded to `n` places, a tie going
  to the even digit, and then the nearest float to that: `round(2.675, 2)` is
  `2.67` because the float written `2.675` is a little below it, and `round(1250,
  -2)` is `1200`. `n` MUST be a whole number. An integer stays an integer.
- `sqrt(x)` is the square root, correctly rounded, and an error for a negative
  `x` (`TypeError: sqrt() needs a number that is not negative`).
- `pow(a, b)` is `a` to the power `b`. With whole `a` and non-negative whole `b`
  the result is exact; a negative power is a float (`pow(2, -1)` is `0.5`). `pow(0,
  -1)` is `TypeError: pow(): 0.0 cannot be raised to a negative power`; a negative
  base with a fractional power would be complex and is `TypeError: pow() produced
  a complex result, which NovaLang cannot represent`; a result of 4,000 digits or
  more is an error (`[port.integers]`). `pow(0, 0)` is `1`.
- `sin`, `cos`, `tan`, `ln` and `log10` take and give floats. They are accurate to
  within a few units in the last place but are **not required to give the same last
  digits on every host**; a program that prints them should round first. `sin(0)`,
  `cos(0)`, `tan(0)`, `ln(1)` and `log10(1)` are exact. `ln` and `log10` of a number that is not greater than zero are `TypeError:
  ln() needs a number greater than zero`.
- `PI` and `E` are the floats nearest to π and e: `3.141592653589793` and
  `2.718281828459045`.
- `min`, `max` and `sum` take several numbers or one list of numbers (a single
  number counts as one). `sum` adds from the left starting at the integer 0, so
  `sum([0.1, 0.2])` is `0.30000000000000004`. `min`/`max` of an empty list or no
  arguments is `TypeError: min() needs at least one number`; an item that is not a
  number is `TypeError: sum() needs a number, but got a string`. When two items
  are equal (`1` and `1.0`) the first is returned.

Every math function names a non-number argument as `TypeError: abs() needs a
number, but got a string`, and a boolean is not a number.

## [lib.functional] `map`, `filter` and `reduce`

The first argument is a function: a user function or any built-in
(`TypeError: map() needs a function, but got a number`), the second a list
(`TypeError: map() needs a list, but got a number`).

- `map(f, list)` is a new list of `f(item)` for each item, in order; `f` is called
  once per item, left to right.
- `filter(f, list)` is the items for which `f(item)` is `true`, in order. `f` MUST
  return a boolean (`TypeError: filter()'s function must return true or false`).
- `reduce(f, list)` folds from the left: `f(f(a, b), c)`. `reduce(f, list, start)`
  starts from `start`, so an empty list gives `start`. Without a start an empty list
  is `reduce() needs a non-empty list, or an initial value as a third argument`,
  and a one-item list gives that item without calling `f`.

An error raised by `f` is the caller's error (`[err.try-catch]`). `f` is called with
the number of arguments the library gives it, so a function that takes another
number is `two() expects 2 argument(s) but got 1`.

## [lib.json] JSON

`json.dumps(value)`, `json.pretty(value)` and `json.loads(text)` convert between
values and JSON text.

- Writing. `nothing` is `null`, booleans `true`/`false`, integers their digits,
  lists `[...]`, dictionaries `{...}` with their keys in order. Items are
  separated by `, ` and keys from values by `: ` in `dumps`. A string is quoted,
  with `\"`, `\\`, `\n`, `\r`, `\t`, `\b` and `\f` for those characters, `\u00XX`
  for other characters below U+0020, and **every character above U+007E written
  as `\uXXXX` with lowercase hex digits**, a character beyond U+FFFF as a pair of
  surrogates, so the output is always ASCII: `json.dumps("é😀")` is
  `"é😀"`. A float is written as in `[port.floats]` using the digits
  rule and the layout *positional from 0.0001 up to 1e16*, but a float with a
  whole value keeps a `.0`: `json.dumps(2.0)` is `2.0` and `json.dumps(1e22)` is
  `1e+22`. A function is `TypeError: json.dumps() cannot represent a function`.
  What it writes for infinity and NaN is not specified (D-022).
- `json.pretty(value)` is the same text with a line to every item and two spaces of
  indent per level; `[]` and `{}` stay on one line.
- Reading. `json.loads` accepts standard JSON: whitespace is space, tab, line feed
  and carriage return; strings take the usual escapes including `\uXXXX` pairs;
  `1`, `-0` and `5` are integers (`-0` is `0`) and anything with a point or an
  exponent is a float (`json.loads("1.0")` is the float `1.0`, which prints `1`);
  `null` is `nothing`. A repeated key keeps its first position and its last value.
  A number of more than 4,000 digits is `TypeError: json.loads(): that number has
  too many digits` (`[port.integers]`). Text that is not JSON, or has anything after
  the value, is `TypeError: json.loads(): <the host's reason>` and only the prefix
  is specified. `json.loads(5)` is `json.loads() needs a string, but got a number`.

## [lib.assert] `assert`

`assert(condition)` and `assert(condition, message)` do nothing when the condition
is `true` and return `nothing`. When it is `false` they raise `AssertionError:
assertion failed`, or with the message `AssertionError: <message>`. The condition
MUST be a boolean (`TypeError: assert() needs true or false, but got a number`), and
when it fails the message MUST be a string (`the message for assert() needs a
string, but got a number`); a message is not looked at when the condition holds.
A caught assertion reads `AssertionError: boom`.
