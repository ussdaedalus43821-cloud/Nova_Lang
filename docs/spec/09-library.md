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
  Numbers are ordered by value, strings by code point (`[port.text]`), and a boolean
  counts as 0 (`false`) or 1 (`true`) so booleans and numbers sort together; the
  items stay what they were. A list that mixes strings with numbers or booleans,
  that holds any other kind of item (a list, a dictionary, a function, `nothing`),
  or that holds a NaN, is `TypeError: sorted() needs items that can be compared
  with each other` (the same things `<` refuses, `[expr.ordering]`, apart from the
  booleans). A second argument that is not a boolean is `TypeError: sorted()'s
  second argument must be true or false`, and a first that is not a list is
  `TypeError: sorted() needs a list, but got a number`.

## [lib.text] Strings

- `upper(s)` and `lower(s)` convert case: the letters `a`-`z` and `A`-`Z` change.
  What they do to other characters (`upper("ß")`, `lower("É")`) is the host's
  Unicode behavior and is not specified (D-025).
- `trim(s)` removes **whitespace** from both ends. **Whitespace is ASCII only**: space,
  tab, line feed, carriage return, vertical tab and form feed. A no-break space, an
  em space or any other Unicode space is an ordinary character, so every host
  trims the same text the same way (D-020). `num()` skips the same whitespace
  around a number (`[val.types]`).
- `split(s, sep)` is the list of the pieces of `s` between non-overlapping
  occurrences of `sep`, scanning from the left; there is a piece (possibly `""`)
  on each side of every separator, so `split("a,b,,c", ",")` is `["a", "b", "",
  "c"]` and `split("", ",")` is `[""]`. `sep` MUST NOT be empty (`split() cannot use
  an empty separator`). `split(s)` with no separator splits on runs of that ASCII
  whitespace and drops the empty pieces at the ends, so `split("  a  b ")` is `["a", "b"]` and
  `split("   ")` is `[]`.
- `join(list, sep)` is the items written as `str` writes them (`[val.display]`),
  separated by `sep`. `join([], ",")` is `""`. The first argument MUST be a list
  and the separator a string (`the separator of join() needs a string, but got a
  number`).
- `str(x)` is how `print` writes `x`, as a string.
- `byte_length(s)` is the number of bytes of the UTF-8 form of `s`, a whole number: `byte_length("abc")`
  is 3 and `byte_length("é")` is 2. A lone surrogate counts as one byte (it has no UTF-8 form; the host writes
  a replacement). A limit in bytes (`16-sandbox.md` `[sbx.limits]`, output) counts with it. A first argument that
  is not a string is `byte_length() needs a string, but got a number`.
- `pad(s, n)` adds spaces on the right and `pad_left(s, n)` on the left until `s` is
  `n` code points long. A string already `n` long or longer, or a negative `n`, is
  returned unchanged. `n` MUST be a whole number.
- `replace_all(s, old, new)` replaces every non-overlapping occurrence of `old`
  from the left with `new`. An empty `old` matches between every character and at
  both ends: `replace_all("abc", "", "-")` is `-a-b-c-`.
- `split_lines(s)` is the lines of `s` without their line ends. A line ends at a
  line feed, a carriage return, or a carriage return followed by a line feed
  (one line end), and **nothing else** does: form feed, vertical tab, `U+0085` and
  `U+2028` stay inside the line. A line end at the very end of the text does not
  start another line: `split_lines("a\nb\r\nc\n")` is `["a", "b", "c"]` and
  `split_lines("")` is `[]`.

A string argument of the wrong kind is `upper() needs a string, but got a number`;
for the second and later arguments the message names the role (`the separator of
split() needs a string`, `the text for replace_all() needs a string`).

## [lib.regex] `regex` and the pattern dialect

`regex(pattern, text)` is `true` if the pattern matches **anywhere** in the text. A bad pattern is `TypeError:
regex(): bad pattern: <reason>`; the reasons below are the ones this version gives, and only the part up to the
reason is specified.

**The dialect (M13).** The pattern language is specified here, and every host MUST give each construct below its
meaning. Nothing outside it is accepted: a construct of another engine that is not listed is refused with a reason that
names it, never given another meaning.

| Construct | Meaning |
| --- | --- |
| a character | itself. `{` is itself unless it starts `{m}`, `{m,}` or `{m,n}` |
| `\` + a punctuation character | that character (`\.` `\\` `\-` ...); every character but an ASCII letter or digit may be escaped |
| `\n` `\r` `\t` `\f` `\v` | line feed, carriage return, tab, form feed, vertical tab |
| `\xHH` `\uHHHH` `\UHHHHHHHH` | the code point (exactly that many hexadecimal digits, at most 10FFFF) |
| `.` | any one character except a line feed |
| `[abc]` `[a-z]` `[^0-9]` | a class: members, ranges, and the escapes above and `\d \w \s \D \W \S` (and `\b` for a backspace); a `]` first is a member; a `-` first or last is a member; `[^...]` matches a line feed |
| `\d` `\w` `\s` and `\D` `\W` `\S` | ASCII only (D-021): `\d` is `0`-`9`, `\w` is `A`-`Z`, `a`-`z`, `0`-`9` and `_`, `\s` is the six ASCII whitespace characters of `[lib.text]`; the capitals are the complements (over every code point) |
| `\b` `\B` | the edge between a `\w` character and anything else (or the end of the text), and its negation. In an empty text `\b` fails and `\B` succeeds (Python's `re` fails both) |
| `^` `$` | the start of the text; the end of the text or just before a final line feed. Neither is "the start of a line": there is no multi-line mode |
| `( )` `(?: )` `(?P<name> )` | a capturing group (numbered by its opening parenthesis, from 1), a group that does not capture, a named capturing group (the name is ASCII letters, digits and `_`, not starting with a digit, and not used twice) |
| `a|b` | alternation: the first alternative that lets the whole pattern match wins |
| `* + ?` `{m}` `{m,}` `{m,n}` | repeat the item the given number of times, **greedy**: as many as possible, giving back as needed |
| `*? +? ?? {m,n}?` | the same, **lazy**: as few as possible |
| `(?i)` at the very start | ASCII case-insensitive matching for the whole pattern (`é` and `É` stay different) |

**Which match.** The match is the leftmost one and, at that place, the one a backtracking engine that tries
alternatives left to right and greedy repeats longest first would find (leftmost-first, as Perl, Python and RE2).
A repeat that matches nothing in one pass ends the repeat there, and what follows is tried from the same place (so
`(a|)*` cannot loop). For a pattern in which a repeated item can match the empty string, the **end** of the match and
the captures of the final pass may differ from Python's `re`; whether there is a match, and where it starts, do not.
Every other pattern gives exactly Python's span and groups (the differential fuzzer of `tests/std/test_regex.py` holds
this).

**Refused, with a reason that names them:** back-references and octal escapes (`\1`, `\0`), look-ahead (`(?=` `(?!`),
look-behind (`(?<=` `(?<!`), atomic groups, possessive quantifiers (`a*+`), conditional groups, comment groups, flags
other than a leading `(?i)`, `(?<name>` (write `(?P<name>`), `\A \Z` and every other letter escape, `{,n}` (write
`{0,n}`), a repeat of `^ $ \b \B` or of another repeat (`a**`), an unbalanced `(` or `)`, an unterminated class, a range
that ends before it starts, a class shortcut as the start of a range (`[\d-z]`), a pattern that ends with a backslash.

**Limits.** A pattern is at most 4,000 characters, has at most 1,000 groups, nests groups at most 100 deep, has repeat
counts of at most 1,000, and may expand (`a{1000}` is a thousand copies) to at most 20,000 instructions; past any of
these the pattern is a bad pattern whose reason says so.

**Time.** The matcher takes time proportional to the size of the pattern times the length of the text, **whatever the
pattern**: `(a+)+$` on a long run of `a` and a letter after it answers at once. The work is charged to the run: a
thread of the matcher at one character of the text costs one unit, and every 128 units cost one step of the budget
(`[sbx.limits]`, `steps`) and are counted by the time limit like the other long operations, so the limits end a run that
matches a large text with a large pattern. A host that cannot guarantee this MUST NOT claim the dialect.

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
  `1e+22`. A function is `TypeError: json.dumps() cannot represent a function`,
  and infinity or NaN is `TypeError: json.dumps() cannot represent NaN or infinity`,
  because JSON has no such numbers (D-022).
- `json.pretty(value)` is the same text with a line to every item and two spaces of
  indent per level; `[]` and `{}` stay on one line.
- Reading. `json.loads` accepts standard JSON: whitespace is space, tab, line feed
  and carriage return; strings take the usual escapes including `\uXXXX` pairs;
  `1`, `-0` and `5` are integers (`-0` is `0`) and anything with a point or an
  exponent is a float (`json.loads("1.0")` is the float `1.0`, which prints `1`);
  `null` is `nothing`. A repeated key keeps its first position and its last value.
  A number of more than 4,000 digits is `TypeError: json.loads(): that number has
  too many digits` (`[port.integers]`), and one too large for a float (`1e999`) is
  `TypeError: json.loads(): that number is too large`. `NaN`, `Infinity` and
  `-Infinity`, which Python's reader would accept, are refused: `TypeError:
  json.loads(): NaN is not valid JSON` (NovaLang has no `ValueError`; the errors of
  `json.loads` all carry the `TypeError` label). Text that is not JSON, or has anything after
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

## [lib.std-text] `std:text`

```
import "std:text" as text
```

Small text and path helpers (G-002, G-006, G-031, G-037, G-039), written in NovaLang over the
built-ins every profile has: no capability, every profile, deterministic. Every function takes
strings where it says `s`, `target`, `prefix`, `suffix` and `path`; anything else is
`the text for text.find() needs a string, but got number` (`boolean`, `list`, ... for other types, as `type` names them), naming the role (`text`, `target`,
`prefix`, `suffix`, `path`), the function and the type of the value, with the label `Error`.
Indexes are in code points, as `len` and slicing are.

- `text.find(s, target)` is the index of the first occurrence of `target` in `s`, or `-1`. An
  empty `target` is found at `0`.
- `text.find_from(s, target, start)` is the same looking from index `start` on, and the index
  is in `s`: `text.find_from("abcabc", "b", 2)` is `4`. A `start` below `0` is `0` and one
  past the end is the length, so `text.find_from("abc", "", 99)` is `3`. `start` MUST be a
  whole number: `the start for text.find_from() needs a whole number`.
- `text.starts_with(s, prefix)` and `text.ends_with(s, suffix)` are `true` when `s` begins or ends
  with the text; an empty one always matches and one longer than `s` never does.
- `text.is_number(s)` is `true` exactly when `num(s)` would succeed, and
  `text.parse_number(s, fallback)` is `num(s)`, or `fallback` when `num(s)` would fail.
  (`num` itself is unchanged and still raises.)
- `text.basename(path)` is what follows the last `/` or `\` in `path`, or `path` when it has
  neither; `text.basename("a/b/")` is `""`. Both separators end a part on every platform, so
  the result does not depend on where the program runs.
- `text.splitext(path)` is a list `[root, extension]` with `root + extension == path`. The
  extension is the last `.` of the last part of the path and what follows it, provided a
  character other than `.` comes before that dot in the part: `text.splitext("a/b/c.tar.gz")` is
  `["a/b/c.tar", ".gz"]`, and `.bashrc`, `a.b/c`, `..x` have no extension (`""`) while `x.` has
  the extension `"."`.

- `text.chr(n)` is the one-character string whose code point is `n`, a whole number from 0 to 1114111
  other than the surrogates 55296 to 57343 (the one place a program can get an escape character, `text.chr(27)`:
  `"\x1b"`, `"\u001b"` and `"\e"` are lexical errors, `[lex.escapes]`, G-004). Anything else is `the number for
  text.chr() needs a whole number from 0 to 1114111, other than 55296 to 57343 (the surrogates)`. What a program
  prints reaches its output as it is, so a program that prints an escape sequence does what the receiving
  terminal does with one.
- `text.ord(s)` is the code point of the one-character string `s` (G-005); a string of any other length is
  `the text for text.ord() needs exactly one character, but got 2`, a non-string `the text for text.ord() needs a string,
  but got number`. `text.ord(text.chr(n)) == n`. (`chr` and `ord` are native, `[mod.std]` 6.)

The module's exports are exactly the ten names above (`basename`, `chr`, `ends_with`, `find`,
`find_from`, `is_number`, `ord`, `parse_number`, `splitext`, `starts_with`); anything else in its file is
private.

## [lib.std-decimal] `std:decimal`

```
import "std:decimal" as dec
```

Exact base-10 arithmetic (G-043, G-044, G-045) over exact integers (`[port.integers]`), native
(`[mod.std]` 6: the first version, plain NovaLang, cost about 60 microseconds an operation): no capability, every
profile, deterministic. A **decimal** is the list
`[unscaled, scale]` and means `unscaled / 10^scale`: `[1999, 2]` is `19.99`. Both are whole
numbers and `scale` is 0 to 1000. A program makes decimals with this module's functions and
reads them with its functions; the layout is **not** part of the interface (it can change in
a minor release). Every function checks its arguments, so a list that is not a decimal is
`decimal.add() needs a decimal for the first argument, but got [1.5, 2]`, never a wrong answer.
There are **no operators**: `+` on two decimals joins the two lists, as it does for any lists.
An integer that would have more than 4,000 digits is the language's own error
(`[port.integers]`), and a result that would have a scale above 1000 is `decimal.mul() result
would have more than 1000 digits after the point`.

**Rounding modes** are strings, and a mode that is not one of them is `decimal.quantize() needs a
rounding mode: half_even, half_up, half_down, up, down, floor, ceiling`:

| Mode | A value that is not exact goes to |
| --- | --- |
| `half_even` | the nearest; a tie to the neighbour whose last digit is even |
| `half_up` | the nearest; a tie away from zero |
| `half_down` | the nearest; a tie towards zero |
| `up` | the neighbour away from zero |
| `down` | the neighbour towards zero |
| `floor` | the neighbour towards negative infinity |
| `ceiling` | the neighbour towards positive infinity |

**Making and reading.**

- `dec.parse(text)` is the decimal `text` writes: an optional `+` or `-`, digits, and optionally a point and
  more digits (`.5` and `7.` are fine). The scale is the number of digits after the point, so
  `dec.parse("1.50")` keeps its two places. Nothing else is allowed, no exponent, space or separator:
  `decimal.parse() cannot read a decimal from "1e5"`. More than 4,000 digits, or more than 1000 after the
  point, is the same error. A non-string is `decimal.parse() needs a string, but got number`.
- `dec.try_parse(text)` is the same, or `nothing` when the text is not a decimal.
- `dec.from_int(n)` is the decimal of a whole number, scale 0.
- `dec.from_float(x, places, mode)` is a number `x` read **as the number its text shows** (what `str(x)`
  prints, in the positional or exponent form), rounded to `places` digits after the point by `mode`:
  `dec.from_float(0.1, 2, "half_even")` is `0.10` and `dec.from_float(2.675, 2, "half_even")` is
  `2.68`, where `round(2.675, 2)` is `2.67` because that float is not exactly 2.675. Infinity and NaN
  are errors. `places` is a whole number from 0 to 1000.
- `dec.is_decimal(a)` is `true` when `a` is a decimal this module accepts; `dec.scale(a)` is its
  number of digits after the point.

**Arithmetic.**

- `dec.add(a, b)`, `dec.sub(a, b)` and `dec.mul(a, b)` are exact. The scale of a sum or difference is the larger
  of the two; the scale of a product is the sum of the two.
- `dec.div(a, b, places, mode)` is `a / b` rounded to `places` digits after the point by `mode`. `places` and
  `mode` are **required**: a quotient is usually not exact, and there is no default for the program to
  forget. A zero divisor is `decimal.div() cannot divide by zero`.
- `dec.quantize(a, places, mode)` is `a` with exactly `places` digits after the point: rounded by `mode` when
  digits are dropped, padded with zeros when they are added (never rounded then).
- `dec.negate(a)`, `dec.absolute(a)` and `dec.sign(a)` (`-1`, `0` or `1`). (Not `neg`, `abs`, as built-in names
  are reserved, `[scope.reserved]`.)
- `dec.cmp(a, b)` is `-1`, `0` or `1` by value, so `1.5` and `1.50` compare equal; `dec.eq`, `dec.lt` and
  `dec.le` are `true` or `false`. (Comparing two decimals with `==` compares the lists, so `1.5 == 1.50` is `false`:
  use `dec.eq`.)
- `dec.total(list)` is the exact sum of a list of decimals; the empty list is `0`.

**Out.**

- `dec.to_string(a)` is the text: every digit after the point kept (`1.50` stays `1.50`), never an exponent, and a
  minus sign only when the value is below zero (a zero is never `-0.00`).
- `dec.to_int(a, mode)` is `a` rounded to a whole number by `mode`.
- `dec.to_float(a)` is the nearest float to `a`.

The module's exports are exactly: `absolute`, `add`, `cmp`, `div`, `eq`, `from_float`, `from_int`, `is_decimal`,
`le`, `lt`, `mul`, `negate`, `parse`, `quantize`, `scale`, `sign`, `sub`, `to_float`, `to_int`, `to_string`,
`total`, `try_parse`. The conformance cases pin the rules above; `tests/std/test_decimal.py` checks the
arithmetic against Python's `decimal` module on random inputs on all three engines.

## [lib.std-math] `std:math`

```
import "std:math" as math
```

Numeric helpers (G-018, G-043, G-045), in NovaLang. A non-number is `the number for math.trunc() needs a
number, but got string`, naming the role.

- `math.trunc(x)` is `x` without its fractional part, towards zero: `math.trunc(-2.7)` is `-2` (where `floor`
  gives `-3`).
- `math.divmod(a, b)` is the list `[a // b, a % b]`: the floor quotient and the remainder with the sign of `b`, so
  `a == b * q + r`. A zero `b` is the language's own error, `integer division by zero`.
- `math.round_half(x, places, mode)` is `x` rounded to `places` digits after the point by a mode of
  `[lib.std-decimal]`, reading `x` as the number its text shows, and the nearest float to the result:
  `math.round_half(2.675, 2, "half_up")` is `2.68`. (`round` itself is unchanged: it rounds half to even and works on the
  binary value.)
- `math.exp(x)` is `pow(E, x)`.

The module's exports are exactly `divmod`, `exp`, `round_half`, `trunc`.

## [lib.std-format] `std:format`

```
import "std:format" as fmt
```

Number to text (G-007, G-008, G-048), in NovaLang.

- `fmt.fixed(x, places)` is the number `x` as text with exactly `places` digits after the point (0 to 1000), rounded half to
  even on the number's text as `[lib.std-decimal]` `from_float` reads it, and never in exponent form:
  `fmt.fixed(5, 2)` is `5.00`, `fmt.fixed(0.0000001, 8)` is `0.00000010` (`str` prints `1e-07`),
  `fmt.fixed(2.5, 0)` is `2` and `fmt.fixed(3.5, 0)` is `4`. A result of zero has no minus sign:
  `fmt.fixed(-0.001, 2)` is `0.00`.
- `fmt.grouped(text, sep)` is the text of a number (an optional sign, digits, an optional point and digits, as `fixed`
  makes it) with `sep` between groups of three digits of its whole part: `fmt.grouped("1234567.5", ",")` is
  `1,234,567.5`. Text that is not a number is `format.grouped() needs the text of a number such as "1234.5", but got "abc"`.
- `fmt.pad_zero(n, width)` is the whole number `n` as text padded on the left with zeros to `width` characters; a minus sign
  counts towards the width and stays in front: `fmt.pad_zero(-5, 4)` is `-005`. A number already as wide is returned as is.
  `width` is 0 to 100000.

`str` of a float is **unchanged** by this module: a small float still prints as `1e-07` (G-048) and `fmt.fixed` is the way out.
A float literal too large for a float is still infinity (G-052, decided: kept, and now documented here, because making the lexer
refuse it would break programs that run today). The module's exports are exactly `fixed`, `grouped`, `pad_zero`.

## [lib.std-files] `std:files`

```
import "std:files" as files
```

Reading files in pieces (G-030, G-032, G-036, G-041). The module declares the `files.read` capability
(`[mod.std]` 3): `import "std:files"` in a `restricted` run that was not granted it is `ImportError:
std:files needs the 'files.read' capability, which this run did not grant`. Every path is held to the granted
folders exactly as `read` is (`[sbx.paths]`: judged by its real location, before the file is touched, so the error
is the same whether or not the file exists), and a path outside them is
`FileError: <path> is outside the folders this program may use`. A path that is not a string is a type error
that names the function.

- `files.size(path)` is the size of the file in bytes. A folder is `FileError: <path> is a directory, not a file`, a missing file
  `FileNotFoundError: <path>`.
- `files.is_dir(path)` is `true` for a folder. `files.is_link(path)` is `true` when the path is a symbolic link, the
  link itself and not what it points at (the grant is still judged by where the link leads). Both are `false` for
  a path that does not exist.
- `files.lines(path)` is every line of the file as a list: a line ends at a line feed, a carriage return, or a
  carriage return followed by a line feed (one line end), nothing else does, and a last line end starts no
  new line (the rule of `split_lines`, `[lib.text]`). The file is read **in pieces** of at most 64 KiB (a longer line
  makes its piece grow, up to 16 MiB), so no string of the whole file is ever made and the string limit
  applies only to each line: a file of any size can be read in the `restricted` profile as long as its lines and the
  list of them fit the limits (`[sbx.limits]`, `string` and `list`). A line over the string limit is that limit's error,
  `a string cannot grow beyond <N> characters` (`[sbx.limits]`, `string`); a file that is not UTF-8 is
  `FileError: <path>: <reason>`.
- `files.each_line(path, handle)` calls `handle(line)` for every line, in order, the same lines, **without ever holding
  more than one piece and its lines**, and returns `nothing`; it is the way to read a file that is too large to hold as a
  list. An error in `handle` ends the loop and is the caller's.

**Nothing stays open.** Each piece is read by opening the file, reading from a byte offset and closing it, and the grant
is judged again for every piece, so a file replaced between two pieces is judged again, and a loop left by an error, by
`break` in the caller or by the end of the program leaves nothing behind. (Reading the same file while it is being written
gives whatever each piece found.)

The module's exports are exactly `each_line`, `is_dir`, `is_link`, `lines`, `size`. A lazily read `for line in ...` is not
part of this version.

## [lib.std-regex] `std:regex`

```
import "std:regex" as re
```

Regular expressions with captures (G-003), in the dialect of `[lib.regex]`. The module declares the `regex` capability
(`[mod.std]` 3): `import "std:regex"` in a `restricted` run that was not granted it is `ImportError: std:regex needs
the 'regex' capability, which this run did not grant`. (The capability stays while the matcher is new; `[sbx.capabilities]`.)
A pattern, replacement, text, count or limit of the wrong kind is a type error that names the function and the argument,
a bad pattern is `TypeError: regex.<function>(): bad pattern: <reason>` and a bad replacement is `TypeError:
regex.<function>(): bad replacement: <reason>`.

A **match** is a dictionary `{start, end, text, groups, named}`: `start` and `end` are offsets in **characters** (not
bytes), `text` is `text[start:end]`, `groups` has one entry for each capturing group in the order of their opening
parentheses (the text it matched in the last pass, or `nothing` for a group that took no part), and `named` maps each
`(?P<name>...)` group's name to the same value.

- `re.test(pattern, text)` is `regex(pattern, text)`.
- `re.match(pattern, text)` is the first match anywhere, or `nothing`. `re.match_from(pattern, text, start)` looks from
  character `start` on (`0` to the length of the text; `^` still means the start of the whole text).
- `re.find_all(pattern, text)` is every match, left to right and not overlapping, as a list. `re.find_n(pattern, text,
  limit)` is at most `limit` of them. After an empty match the next match must not be empty at the same place (so
  `find_all("a*", "baac")` has the texts `""`, `"aa"`, `""`, `""`), as in Python 3.7 and later. A list over the list limit is that limit's error.
- `re.sub(pattern, replacement, text)` is the text with every match replaced, and `re.sub_n(pattern, replacement, text,
  count)` with the first `count`. In the replacement `\1` to `\9`, `\g<number>` and `\g<name>` insert a group (the empty
  string for a group that took no part) and `\\` is a backslash; any other backslash is `bad replacement`, as is a group
  the pattern does not have. An empty match is replaced too (`sub("a*", "-", "baac")` is `-b--c-`). The result is held to the
  string limit while it is built.
- `re.pieces(pattern, text)` is the pieces of the text between the matches (the matches found as `find_all` finds them;
  the first piece starts at the start of the text and the last ends at its end), and `re.pieces_n(pattern, text,
  limit)` uses at most `limit` matches, so `limit + 1` pieces at most. (It cannot be called `split`: built-in names
  are reserved, `[scope.reserved]`.)
- `re.escape(text)` is the text with each of `\ . ^ $ * + ? { } [ ] ( ) | -` preceded by a backslash, so that as a
  pattern it matches exactly the text.

The module's exports are exactly `escape`, `find_all`, `find_n`, `match`, `match_from`, `pieces`, `pieces_n`, `sub`,
`sub_n`, `test`. Every function is a native of the module (`[mod.std]` 6) and its work is charged to the run as
`[lib.regex]` says. There are no optional arguments in NovaLang, so each of `find`, `sub` and `pieces` has a second form with
the count or limit (`find_n`, `sub_n`, `pieces_n`).

