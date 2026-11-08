# 6. Portability

NovaLang is meant to run on a server, in a browser, on a phone and, in a
constrained form, on a microcontroller, and to compile itself. For that to be
possible every rule that a host might reasonably read two ways has to be
written down. This chapter fixes the ones the first implementation had settled
by accident (often by what Python does), says which are **host-defined** and
within what bounds, and says what a smaller host must do when it cannot meet a
rule.

A host that cannot meet a rule MUST refuse the program with an error as
`[sec.error-boundary]` describes. It MUST NOT wrap around, truncate or return
a different answer.

## [port.integers] Integers

An integer has at most **4,000 decimal digits**: its magnitude is below
10<sup>4000</sup>. The bound belongs to the language, not to a host, so that a
program that runs on one host runs on every host, from a server to a browser to
a microcontroller (4,000 digits is about 1.7 KB of storage). Arithmetic on
integers inside the bound is exact.

An operation whose integer result would reach 10<sup>4000</sup> in magnitude is
an error, never a wrong answer, a wrapped value or infinity:
`the result has too many digits - an integer cannot have more than 4000 digits`.
It applies to `+`, `-` and `*`; to `pow()` (refused before it is computed, so
`pow(2, 1000000000)` answers at once); to `sum()` and to `round()` with a
negative digit count; and to an integer handed in from outside the language
(`TypeError: json.loads(): that number has too many digits`, or the embedding
bridge). `//`, `%`, unary `-`, `abs`, `min` and `max` cannot leave the bound.

A number literal, and the text `num()` reads, may contain at most 4,000 digits,
counted on both sides of the point and including leading zeros:
`this number has too many digits` and `num(): that number has too many digits`.
A decimal of fewer digits whose value is too large for a float is not an error
but infinity (`[port.floats]`).

Where an integer meets a float the integer is converted to a float first. An
integer too large to be one (beyond about `1.8e308`) cannot be, so these are
errors and not infinity:

- `integer + float`, `-`, `*`, `//` and `%`, when the integer cannot be converted;
- `/`, when the quotient of two integers is too large to be a float;
- a built-in that takes a float, such as `sqrt`, given such an integer
  (`TypeError: sqrt(): a number is too large for this function`).

Comparisons are exact and never convert: `9007199254740993 > 9007199254740992.0`
is `true`. `//` and `%` of two integers are exact however large.

## [port.floats] Floating-point numbers

A float is an IEEE 754 binary64 value and its arithmetic is IEEE's: operations
round to nearest, an overflowing result is infinity (not an error, unlike an
integer that is too large), and `inf - inf` is NaN.

`inf`, `-inf` and `nan` are values of kind number. They have no literal; they
arise from `num("1" + "0" * 400 + ".0")` (a decimal string too long for a float),
from float overflow, and from the host's own functions. NaN is unequal to
everything including itself, and every ordering comparison with it is `false`.
`inf == inf` is `true`.

A function that needs a whole number or a finite one rejects them: `floor`,
`ceil` and `round` (with no digit count), and `sleep`, refuse infinity and NaN
with `TypeError: floor() needs a finite number, but got inf`; `sin`, `cos` and
`tan` refuse infinity; and a `for` header refuses them
(`the end of a 'for' range must be a finite number, but this is inf`).
`round(x, digits)` and `sin(nan)` do not raise and return NaN or infinity unchanged.

**How a float prints** (`[val.display]`) is part of the contract, because a
program's output must be the same on every host. The rule does not depend on any
language's or library's own formatting:

- `inf`, `-inf` and `nan` print as those words.
- A float with a whole value prints as the exact decimal expansion of that value,
  with no point and no exponent: `1000000000000 * 1000000000000 * 1.0` prints
  `999999999999999983222784`, the value the float really holds. Negative zero
  prints `0`.
- Any other float prints in two steps, **digits** and then **layout**.

  *Digits.* Of all decimal digit strings that read back as exactly this float
  (read as the nearest float, ties to even), take the shortest. If more than one
  has that length, take the one closest to the float's exact value; if two are
  equally close, the one whose last digit is even. Drop trailing zeros. Write the
  result as `d.ddd` times 10<sup>x</sup>, `d` being its first digit.

  *Layout.* If `x` is from -4 to 15, print it positionally: `0.0001`, `0.5`,
  `100.25`, `3.3000000000000003`. If `x` is below -4 print the digits as `d` or
  `d.ddd`, then `e`, a sign and at least two exponent digits: `1e-05`,
  `1.23456e-05`, `5e-324`, `2.2250738585072014e-308`. (A float that is not whole
  is below 2<sup>52</sup>, so `x` above 15 does not occur.)

To compute the digits, try 1, 2, 3 ... digits and for each take the exact value
rounded to nearest and, failing that, rounded up; the first that reads back is
the answer. The rounding up matters: the floats just above a power of two are twice as far
apart as those just below, so the nearest short decimal can fall outside what
rounds to the float while the next one up is inside. 2<sup>-1017</sup> prints
`7.120236347223045e-307`; the nearest 16-digit decimal, `7.120236347223044e-307`,
does not read back as it.

## [port.text] Text

A string is a sequence of Unicode code points. `len`, indexing and slicing
count code points: `len("😀")` is 1 and `len("日本語")` is 3. A letter with a
combining accent written as two code points has length 2, and is not equal to
the same letter written as one: the language does no normalization, so `"é"`
(U+00E9) and `"é"` (e, then U+0301) differ and have lengths 1 and 2.

Strings compare by code point, not by any language's alphabet: `"Z" < "a"`,
`"é" > "z"`, and `"😀" > "z"` are all `true`. Source files and program output are
UTF-8, and a line of output ends in a line feed.

The case conversions `upper` and `lower` follow Unicode and are not specified
further here.

## [port.order] Order and determinism

A program in the `core` profile is deterministic: the same source gives the same
output, on any host.

- A dictionary keeps the order its keys were first inserted in. `keys`, `values`,
  printing and `for k, v in d` all follow it; assigning to an existing key keeps
  its place, and a new key goes last. `a + b` has the keys of `a` in order, then
  those of `b` that `a` lacks, with the values of `b`.
- Operands and arguments are evaluated left to right, and so are the items of a
  list and the entries of a dictionary literal. A call evaluates the function,
  then its arguments, then runs.
- Nothing in the core profile varies from run to run. The clock, randomness, the
  environment and the command line are in the `host` profile.

## [port.limits] Limits a host must have

A host MUST bound these, and report the bound as an error (`[sec.error-boundary]`)
and not as a crash. The values are the reference host's and a smaller host may
use smaller ones, but not below the **minimum** in the last column, which the
corpus relies on.

| What | Error | Reference | Minimum |
| --- | --- | --- | --- |
| Depth of nested calls | `call depth of <N> exceeded - is the recursion missing a base case?` | 1200 | 50 |
| Items in a list made by `*` | `repeating that list <n> times would exceed 1000000 items` | 1,000,000 | 1,000,000 |
| Characters in a string made by `*` | `repeating that string <n> times would be too long` | 1,000,000 | 1,000,000 |
| Items in a list grown by `append` | `a list cannot grow beyond 1000000 items` | 1,000,000 | 1,000,000 |
| Items in a list made by `range` | `range() would build a list of <n> items, which is too large` | 1,000,000 | 1,000,000 |

`<N>` is the host's own bound, so the corpus matches that message with a
pattern. The self-hosted interpreter's call depth is 60, because each NovaLang
call costs it several of the host's. Runaway recursion ends the program with that error,
status 1, or is caught by a `try` (`[err.try-catch]`).

Lengths and sizes above the table's minimum are not promised to work: a host
with less memory is allowed to refuse a 1,000,000-item list only if its limit is
documented. The reference's numbers are the ones the corpus tests exactly.
