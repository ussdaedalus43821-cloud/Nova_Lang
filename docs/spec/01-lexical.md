# 1. Lexical structure

A program is turned into *tokens* before it is parsed. A lexical error stops the
program before any statement runs (`[err.lexical]`).

## [lex.source] Source text

A program is a sequence of Unicode characters. Source files are UTF-8. The empty
program, and a program of only whitespace, comments and line ends, is valid and
does nothing.

Any character may appear inside a string and inside a comment. Outside them the
characters allowed are those in the sections below.

```
print(len("héllo"), upper("é"), "日本語"[1], len("😀"))   # 5 É 本 1
```

String length and indexing count characters (code points), not bytes.

## [lex.newlines] Line ends and statement separators

A line ends at LF (`\n`), CRLF (`\r\n`) or a lone CR (`\r`); a CRLF is one line
end. Statements are separated by a line end or by `;`. Empty statements are
allowed anywhere statements are, so blank lines and runs of `;` are harmless.

```
print(1); print(2)        # two statements
;;print(1);;              # the same, with empty statements around it
```

Two statements on one line with no separator are an error:
`expected a new line between statements, found 'print'`.

A `;` inside a string or comment is text. Where a line end does not separate
statements, see `[expr.newlines]`.

## [lex.whitespace] Whitespace

The space and the tab separate tokens and are otherwise ignored. Indentation has
no meaning.

## [lex.comments] Comments

`#` outside a string starts a comment that runs to the end of the line (LF or
CR). A comment is not a statement separator by itself: the line end that follows
it is.

```
print(1) # trailing
print("# not a comment")
```

## [lex.identifiers] Names

A name is an ASCII letter or `_`, followed by any number of ASCII letters,
digits and `_`. Names are case-sensitive. A character outside strings and
comments that cannot begin any token is an error, `unexpected character 'é'`,
and that includes letters and digits that are not ASCII.

A name cannot start with a digit: `let 1a = 2` is
`expected a name after 'let', found 1`.

`f` followed directly by a quote starts an f-string (`[lex.fstrings]`); `f` on
its own is an ordinary name.

> Divergence **D-002**: `novalang.py` accepts any Unicode letter in a name and
> any Unicode decimal digit in a number. The self-hosted interpreter follows
> this section.

## [lex.keywords] Keywords

These words are reserved and cannot be used as names of variables, functions or
parameters:

```
def return if else true false while for to downto step break continue
and or not let in delete try catch finally throw import export as with
```

A keyword MAY be used as a dictionary key, in a literal (`{if: 1}`) or after a
dot (`d.if`). Keywords are lower case: `True` and `null` are ordinary names, and
since nothing defines them they are `undefined name` errors. There is no literal
for the value `nothing` (`[val.types]`).

## [lex.numbers] Numbers

A number literal is decimal digits (`0`-`9`), optionally with one decimal
point: `42`, `3.14`, `.5`, `5.`. A literal with a point is a float, one without
is an integer; leading zeros are allowed and have no meaning (`007` is 7).

A literal has no sign (`-5` is the operator `-` applied to 5), no exponent, no
hexadecimal or binary form and no digit separators. A letter or `_` straight
after the digits starts a new token, so `1e3`, `0x10` and `1_000` are syntax
errors, and so is a number split by a space (`1 .5`).

A second decimal point is a lexical error: `a number cannot have two decimal
points`.

A literal has at most 4,000 digits, counting both sides of the point and any
leading zeros: `this number has too many digits` (`[port.integers]`).

## [lex.strings] Strings

A string literal is delimited by `"` or `'`, and the closing quote MUST match.
It MUST end on the line it starts on. The other quote character needs no
escape inside it (`"it's"`, `'say "hi"'`). Two literals side by side are not
joined. An empty string is `""`.

```
print("double", 'single', "it's", 'say "hi"')    # double single it's say "hi"
```

A string that is not closed before the end of the line or input is an error:
`this string is never closed`.

## [lex.escapes] Escape sequences

Inside a string (and an f-string) a backslash starts an escape:

| Escape | Character |
| --- | --- |
| `\n` | line feed |
| `\t` | tab |
| `\r` | carriage return |
| `\0` | the null character |
| `\\` | backslash |
| `\"` | double quote |
| `\'` | single quote |

Any other character after a backslash is an error, `unknown escape '\q'`. There
are no `\x` or `\u` escapes.

`\0` is the null character and nothing more, so a decimal digit straight after
it is an error too, `unknown escape '\03'` (the `\0` and the digit that follows).
Without the rule `"\033"` would read as a null character followed by the text
`33`: quietly not the octal escape for ESC that a C programmer means. NovaLang
has no octal escapes. To write a null character followed by a digit, join two
literals: `"\0" + "3"`. `"\0a"`, `"\0\0"` and `"\0 1"` are unchanged.

## [lex.fstrings] Formatted strings

`f"..."` or `f'...'` is a string with embedded expressions. `{` starts a
placeholder that runs to the matching `}`, in which quotes are respected, so
`f"x{"a" + "b"}y"` is `xaby`. The text of a placeholder is an expression,
evaluated in the scope of the f-string, and its value is converted to text as
`str()` does (`[val.display]`). `{{` and `}}` are literal braces. The escapes of
`[lex.escapes]` apply to the text parts.

```
let n = 3
print(f"n is {n}, double is {n * 2}")      # n is 3, double is 6
print(f"{{x}} and {{}}")                   # {x} and {}
```

Errors, all lexical: `this f-string is never closed`; `this f-string placeholder
is empty`; `this f-string placeholder needs a closing '}'`; and a lone `}` in the
text, `a '}' inside an f-string must be written '}}'`. A placeholder is on one
line.

## [lex.operators] Operators and punctuation

```
+  -  *  /  //  %          arithmetic
== != <  >  <=  >=         comparison
=                          assignment and declaration
(  )  [  ]  {  }  ,  .  :  ;
```

and the keyword operators `and`, `or`, `not` and `in`. There is no `**`, `<>`,
`&&`, `||`, `++` or `+=`. A `!` that is not part of `!=` is an error:
`'!' on its own is not an operator - did you mean '!=' or 'not'?`. Any other
character is `unexpected character '@'`.
