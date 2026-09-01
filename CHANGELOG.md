# Changelog

All notable changes to NovaLang are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and NovaLang uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every release is a single self-contained file, `novalang.py`, run with
`python3 novalang.py` for the REPL or `python3 novalang.py program.nova` for a
script. The implementation is a hand-written pipeline throughout — no `eval()`,
no `exec()`, no parser generators, no regular expressions:

```
source text  ->  Lexer       ->  tokens
tokens       ->  Parser      ->  AST (Abstract Syntax Tree)
AST          ->  Interpreter ->  a value
```

---

## [0.5.0] - 2026-09-01 — Strings & Text Processing

Stage 5. Strings stop being opaque blobs and become something you can take
apart, measure, search and rebuild.

### Added

- **Indexing and slicing for strings**, sharing the syntax lists already use:
  `"Hello"[0]` is `"H"`, `"Hello"[-1]` is `"o"`, and `"Hello"[1:4]` is
  `"ell"`. Either end of a slice may be left out — `[2:]`, `[:3]`, `[:]` —
  and out-of-range ends clamp rather than fail, so `"Hello"[1:99]` is
  `"ello"`. Lists slice too, producing a new list.
- **String repetition**: `"Ha" * 3` is `"HaHaHa"`, with the count on either
  side.
- **f-strings**: `f"Hello, {name}!"`. Each placeholder holds a full
  expression — `f"{age + 1}"`, `f"{upper(name)}"`, `f"{[1, 2]}"` — and is
  lexed into parts, then parsed through the same parser as everything else.
  Write `{{` and `}}` for literal braces. Positions inside a placeholder are
  mapped back to the real line, so an error caret points at the right column.
- **The `in` operator** at comparison precedence: `"ell" in "Hello"` and
  `3 in [1, 2, 3]`. On lists it uses the same element-wise equality as `==`.
- **Built-in functions** `upper`, `lower`, `trim`, `split`, `join`, `str`,
  `num` and `type`. `split(s, sep)` cuts a string into a list and `split(s)`
  splits on whitespace; `join(a, sep)` glues a list back together, converting
  items to text as it goes; `str` and `num` convert between numbers and
  strings; `type` names a value's kind for debugging.
- New AST nodes `SliceNode` and `InterpolationNode`, both rendered by `tree`;
  new tokens for `:` and for f-strings.
- `examples/strings.nova`, working up to title-casing, vowel counting,
  reversal and a palindrome check.

### Changed

- Writing to a string index is refused with a clear message: strings are
  immutable, so `s[0] = "J"` tells you to build a new string instead.
- Index errors now say whether the target was a string or a list, and count
  characters rather than items for strings.
- The eight new built-ins are reserved like `print`, so they cannot be used
  as variable, parameter or function names.
- `help` covers the string syntax and every built-in; the banner reads
  `NOVALANG v0.5.0`.

### Note

Lexicographic string comparison (`"apple" < "banana"`), string concatenation,
escape sequences and `len` on a string already worked — they arrived in
Stages 2 and 4 and are unchanged here.

---

## [0.4.0] - 2026-09-01 — Lists, Indexing & Integer Math

Stage 4. The language gets a data structure and the arithmetic to walk it.

### Added

- **Lists**, written `[1, 2, 3]` or `[]`, and able to span several lines.
  A list holds one kind of item: mixing types is rejected when the list is
  built, when an element is replaced, when `append` adds to it, and when two
  lists are joined.
  ```
  let a = [1, 2, 3, 4, 5]
  let grid = [[1, 2], [3, 4]]
  ```
- **Indexing**, for reading and writing, with negative indexes counting back
  from the end: `a[0]`, `a[-1]`, `a[0] = 10`, `grid[1][0]`. Out-of-range
  access names the index, the size, and the valid range.
- **`let`**, which declares a name in the current block, shadowing any outer
  one. Plain assignment keeps its v0.3 meaning — it updates an existing
  binding out to the nearest function boundary and only creates a name when
  none exists.
- **Built-in functions** `len`, `append`, `pop` and `range`, joining `print`.
  `len` also works on strings; `pop(a)` removes the last item and `pop(a, i)`
  the item at `i`; `range(n)`, `range(a, b)` and `range(a, b, step)` build a
  list, and `step` may be negative.
- **`%` (remainder) and `//` (integer division)**, sharing the precedence
  level of `*` and `/`. Both round the way Python does: `//` towards negative
  infinity, and the sign of `%` follows the right-hand side.
- **List concatenation and repetition**: `[1, 2] + [3, 4]` and `[1, 2] * 3`
  (either operand order). Both produce a new list.
- **`for x in <list>`**, alongside the numeric `for i = a to b`. It walks a
  snapshot of the list, so appending inside the loop cannot make it run
  forever, and it supports `break`, `continue` and the same `else` clause.
- Equality compares lists element by element, so `[1, 2] == [1, 2]` is `true`.
- New AST nodes `ListNode`, `IndexNode`, `IndexAssignNode`, `LetNode` and
  `ForInNode`, all rendered by `tree`. The new built-ins are ordinary
  functions rather than syntax, so they appear as `CallNode` in a tree.
- New keywords `let` and `in`; new tokens `[`, `]`, `%` and `//`.
- `examples/lists.nova`, exercising every feature above.

### Changed

- Assignment is parsed by reading the left side as an expression and then
  looking for `=`, which is what lets `a[i] = v` and `x = v` share one rule.
- `len`, `append`, `pop` and `range` are reserved alongside `print`, so they
  cannot be used as variable, parameter or function names.
- Built-in functions now receive the call position, so their errors carry a
  caret like every other error.
- `range()` and list repetition refuse to build more than 1,000,000 items.
- Printing a list that contains itself shows `[...]` rather than recursing.
- The REPL keeps prompting while a `[` is unclosed, so list literals can be
  typed across several lines.
- `help` covers the new syntax; the banner reads `NOVALANG v0.4.0`.

### Note

`//` is integer division, so comments remain `#` only — a line starting with
`//` is a syntax error, not a comment.

---

## [0.3.0] - 2026-09-01 — Loops, Logic & Block Scoping

Stage 3. Iteration, short-circuit logic, and a real scoping model.

### Added

- **`while` loops**, with an optional `else` block that runs only when the
  loop was never broken out of (Python's semantics).
  ```
  while x < 5 {
      print(x)
      x = x + 1
  } else {
      print("Loop completed without break")
  }
  ```
- **`for` loops** counting up with `to` or down with `downto`, and an optional
  `step`: `for i = 0 to 100 step 10 { ... }`. The iteration count is computed
  once at loop entry, the way `range` does, so float steps do not drift and
  reassigning the loop variable inside the body cannot derail the loop.
- **`break` and `continue`**, implemented as `BreakSignal` / `ContinueSignal`
  exceptions caught by the innermost loop.
- **`and`, `or`, `not`** with genuine short-circuit evaluation — the right-hand
  side of `and`/`or` is never evaluated when the left side already decides the
  answer. They sit between assignment and comparison in the precedence table,
  so `not done and i < 10 or i == 99` groups as
  `((not done) and (i < 10)) or (i == 99)` without parentheses.
- **Block scoping.** Loop bodies, `if` bodies, and the `for` variable each get
  their own scope. A name first assigned inside a block dies with the block.
- New AST nodes: `WhileNode`, `ForNode`, `BreakNode`, `ContinueNode`,
  `LogicalOpNode`, `NotNode` — all rendered by the existing `tree` command.
- New keywords: `while`, `for`, `to`, `downto`, `step`, `break`, `continue`,
  `and`, `or`, `not`.
- `examples/loops.nova`, exercising every feature above.
- `__version__`, hard-coded alongside the banner and the file header comment.

### Changed

- **Assignment now walks outward** to find an existing binding, stopping at the
  nearest *barrier* scope; only an unbound name is created locally. Function
  frames and the global scope are barriers, blocks are transparent. This is
  what lets `x = x + 1` inside a loop update the outer `x` (so the loop
  terminates) while a new name inside the same block stays local — and it
  preserves the v0.2 guarantee that a function cannot rewrite a global by
  assignment.
- The REPL keeps prompting after a `while`, `for`, `if`, or `def` header, not
  just after an unclosed `{`.
- `Ctrl-C` during execution stops a runaway loop and returns to the prompt
  instead of killing the REPL.
- An opening `{` may sit on the line after the statement header.
- `help` rewritten to cover the full v0.3 syntax; the welcome banner reads
  `NOVALANG v0.3.0`.
- A stray `break` or `continue` inside a function body is reported as an error
  rather than escaping into a loop in the caller.

---

## [0.2.0] - 2026-09-01 — Functions, Control Flow & the Call Stack

Stage 2. The language gains abstraction and branching.

### Added

- **Function definitions and calls**, with recursion:
  ```
  def fib(n) {
      if n < 2 {
          return n
      } else {
          return fib(n - 1) + fib(n - 2)
      }
  }
  ```
- **`return` statements**, unwinding through a `ReturnSignal` exception.
- **A real call stack**, with a depth limit (200) that reports
  "is the recursion missing a base case?" instead of a Python `RecursionError`,
  and a stack trace on errors raised inside nested calls.
- **Local scoping.** Each call gets a fresh scope whose parent is where the
  function was *defined*, not where it was called — lexical scoping. Parameters
  and locals never leak to the global scope.
- **`if` / `else`**, including `else if` chains. Conditions are strict: only
  `true` or `false` are accepted, never a truthy number or string.
- **Comparison operators** `<`, `>`, `<=`, `>=`, `==`, `!=`. Equality never
  crosses types, so `true == 1` is `false` rather than an error. Chained
  comparisons such as `a < b < c` are rejected with an explicit message.
- **Boolean literals** `true` and `false`, printing lowercase.
- **String literals** in single or double quotes, with `\n`, `\t` and quote
  escapes, plus `+` for concatenation.
- **The built-in `print`**, reserved at parse time so it cannot be shadowed by
  a variable, parameter, or function name.
- `#` line comments, and `;` as an alternative statement separator.
- Multi-line REPL input: an unclosed `{` (or a trailing `def`) keeps the prompt
  open as `  ... ` until the block closes; `Ctrl-C` discards the draft.
- Running a program from a file: `python3 novalang.py program.nova`.
- `examples/fib.nova`, covering recursion, scoping, `else if` and comparisons.

### Changed

- Newlines and `;` became statement-separator tokens, so a program is now a
  sequence of statements rather than a single expression.
- A statement ending in `}` is self-terminating, so `if c { ... } return x`
  works on one line.
- Errors now report the offending line with a caret beneath it, and a
  multi-line source gains line numbers in the gutter.
- The `tree` command prints an indented tree rather than a flat `repr`.

---

## [0.1.0] - 2026-09-01 — The REPL & Math Engine

Stage 1. The pipeline, end to end, in its smallest useful form.

### Added

- **Lexer** reading integers and floats, `+ - * / ( )`, and identifiers,
  recording a source position on every token for error reporting.
- **Recursive-descent parser** over the precedence grammar
  `expression -> term -> unary -> primary`, producing an AST. Because `+` and
  `-` are parsed in an outer loop and `*` and `/` in an inner one,
  multiplication binds tighter — which is why `5 + 10 * 2` is `25`, not `30`.
- **Tree-walking interpreter** dispatching on node type, with
  integer-preserving division (`10 / 2` is `5`, not `5.0`) and a
  division-by-zero check.
- **Variables**: `x = 5`, then `x * 3`. Right-associative chains (`a = b = 3`)
  work.
- Unary plus and minus.
- **The REPL**, with the welcome banner, the `nova>` prompt, and the commands
  `vars`, `tree <expr>`, `help`, and `exit` / `quit`.
- One-shot evaluation from the command line: `python3 novalang.py "5 + 10 * 2"`.
- Errors reported as a caret under the offending character rather than a Python
  traceback.

[0.5.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.4.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.3.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.2.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.1.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
