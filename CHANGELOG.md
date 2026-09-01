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

## [0.9.0] - 2026-09-01 — Modules & Imports

Stage 9. A NovaLang program can now be split across files.

### Added

- **`import "path.nova"`** runs a file once and binds its exports under a
  name inferred from the filename: `import "math.nova"` gives you `math.fib`,
  `math.PI`, and so on.
- **`import "path.nova" as name`** binds the same exports under a chosen
  name instead of the inferred one.
- **`import "path.nova" with a, b`** skips the module namespace and binds
  the named exports directly into scope, so `fib(10)` works with no prefix.
  Importing a name that was not exported names what was.
- **`export def f() { }` and `export let x = 1`** mark a definition as
  visible to importers. Anything not marked `export` is private to the file
  it is written in, even though it is a perfectly ordinary function or
  variable while that file runs.
- **Relative imports**: `import "./utils.nova"` resolves against the
  importing file's own directory. `import "utils.nova"` (no `./`) resolves
  the same way when there is a current file, and both then fall back to the
  process's current directory - this is the one search order the language
  uses, so an explicit `./` and a bare name behave alike when they name the
  same file.
- **A module cache, keyed by resolved path.** A file is read and run at most
  once per program, however many places import it or under however many
  names; every importer shares the same exports, so a module behaves like a
  singleton the way it does in Python or JavaScript, not like a fresh copy
  per import.
- **Circular import detection.** Importing a file that is already in the
  middle of loading is reported as `circular import: a.nova -> b.nova ->
  a.nova` rather than recursing forever.
- New AST nodes `ImportNode` and `ExportNode`, both rendered by `tree`; new
  keywords `import`, `export`, `as` and `with`.
- `examples/math.nova`, a module exporting `fib`, `factorial` and `PI` with
  one private helper; `examples/modules.nova`, importing it all four ways and
  catching a circular import; `examples/circular_a.nova` and
  `examples/circular_b.nova`, which exist only to import each other.

### Changed

- **`NovaError` can now carry a fully-rendered inner report as its message.**
  An error raised while loading a module - a syntax error in it, or a
  runtime error at its top level - is caught at the import boundary and
  re-reported as `while loading module "path": <the module's own error,
  correctly captioned against the module's own source>`, so a caret always
  points into the file it belongs to, never into the importer's. A runtime
  error from *calling* an already-loaded module's function is unaffected and
  reports exactly as it would for a local function.
- The REPL's rule for waiting on an unfinished statement is more precise: it
  now recognizes `export def f()` as needing an eventual `{` without
  mistaking `export let x = 5` for the same thing, and a bug from v0.8.0 is
  fixed along the way - `try` followed by `{` on the next line now correctly
  waits for the block, matching `if`, `while`, `for` and `def`.
- `help` covers import and export; the banner reads `NOVALANG v0.9.0`.

### Note

A module namespace is, under the hood, an ordinary dictionary of its
exports - `math.fib` is exactly the dot access Stage 6 already had, `type(math)`
answers `"dict"`, and `keys(math)` lists what it exports. Nothing new was
built for that part; Stage 6 already covered it.

`import` and `export` are one-line statements, like `let` and `throw`: unlike
a block header, `as name` and `with a, b` do not wait for more input if left
unfinished on one line - they simply report what is missing.

---

## [0.8.0] - 2026-09-01 — Error Handling

Stage 8. A program can now recover from an error instead of stopping at it.

### Added

- **`try` / `catch` / `finally`.** Either `catch` or `finally` is required;
  both together are fine. A `catch` may bind the message to a name, which is
  always a string:
  ```
  try {
      read("missing.txt")
  } catch e {
      print("Error: " + e)
  } finally {
      print("this runs either way")
  }
  ```
  The bound text carries a label only when it adds something:
  `throw("boom")` gives `"boom"`, while a missing file gives
  `"FileNotFoundError: data.txt"`.
- **`throw(message)`**, which raises an error of your own. Uncaught, it stops
  the program with `Error: your message` and the usual caret and call stack.
- **Every error in the language is catchable**: division by zero, an index out
  of range, a missing dictionary key, an undefined name, a type mismatch and
  file trouble all arrive in `catch` the same way.
- New AST nodes `TryNode` and `ThrowNode`, rendered by `tree`; new keywords
  `try`, `catch`, `finally` and `throw`.
- `examples/errors.nova`, which catches one of each kind of error, retries a
  flaky function until it succeeds, and cleans up after itself with `finally`.

### Changed

- The REPL now survives anything, including a bug in the interpreter itself,
  which reports as `InternalError: ...` and returns you to the prompt rather
  than ending the session.
- `help` gains the try/catch/finally and throw lines; the banner reads
  `NOVALANG v0.8.0`.

### Note

`catch` catches errors, not control flow. A `return`, `break` or `continue`
passing through a `try` is not an error and is never caught, and neither is
Ctrl-C — but `finally` still runs on the way out in every one of those cases,
so cleanup happens even when a loop is broken or the program is interrupted.
`throw` takes a string; use `str()` to convert a value first.

---

## [0.7.0] - 2026-09-01 — File I/O

Stage 7. NovaLang programs can now read and write the world outside the
process.

### Added

- **`read(path)`** returns a whole file as one string, and **`write(path,
  text)`** replaces a file's contents. Both use UTF-8.
- **`append(path, text)`** adds to the end of a file. This is the same
  `append` that grows a list — a list first argument grows the list, a string
  first argument grows the file.
- **`exists(path)`** answers `true` or `false` for any path.
- **`listdir(path)`** returns the names inside a directory, sorted so two
  runs agree.
- **`delete(path)`** removes a file, and does nothing if it is already gone.
  The parentheses are what separate it from the Stage 6 statement:
  `delete(x)` removes the file named by `x`, while `delete d.key` and
  `delete d["key"]` remove a dictionary entry. That distinction is made at
  parse time, so `delete(files[0])` deletes the named file rather than trying
  to remove a list entry.
- **`input(prompt)`** prints a prompt and reads one typed line, returning it
  as a string. The prompt is optional.
- **Errors carry their own label.** A missing file reports itself as
  `FileNotFoundError: data.txt`, with the usual caret and call stack beneath
  it; other trouble reports as `FileError` with the operating system's
  reason. Everything else still reports as `NovaError`.
- New AST node `DeleteFileNode`, rendered by `tree`.
- `examples/file_demo.nova`, which writes a scratch file, appends to it,
  lists the directory, round-trips a list through a file, builds a log line
  by line, counts words in what it wrote, and deletes everything it made.

### Changed

- `read`, `write`, `exists`, `listdir` and `input` join the reserved built-in
  names.
- `help` gains a Files and input section; the banner reads `NOVALANG v0.7.0`.

### Note

`delete` on a missing file is harmless, matching the Stage 6 decision that
deleting an absent dictionary key is not an error.

---

## [0.6.1] - 2026-09-01 — Lists Hold Anything

### Changed

- **Lists may now hold a mix of value types.** The one-type rule introduced
  in v0.4.0 is gone: a list literal can mix kinds, an item can be replaced by
  a value of a different kind, `append` accepts anything, and two lists of
  different kinds join with `+`.
  ```
  let mixed = [1, "two", true, [3], {k: "v"}]
  append(mixed, 3.5)
  print([1, 2] + ["a", true])     # [1, 2, "a", true]
  ```
  Dictionaries already held any mix of values, and this removes the seam
  between the two: `values(d)` now returns an ordinary list that behaves like
  any other, including through `join`, `in`, `==`, indexing and iteration.
- `help` describes lists as holding any mix of values.

### Removed

- The internal element-type check that enforced the one-type rule, along with
  the four error sites that reported it.

---

## [0.6.0] - 2026-09-01 — Dictionaries

Stage 6. Named fields, so a value can be a record rather than a position in
a list.

### Added

- **Dictionary literals**: `{name: "Alice", age: 30}` and `{}`. Keys are
  written bare when they are plain names, or quoted when they are not
  (`{"first name": "Ada"}`); keywords are allowed as keys. A literal may
  spread over several lines, and a repeated key is rejected at parse time.
  Unlike lists, a dictionary holds any mix of value types.
- **Dot and bracket access**, which mean the same thing: `person.name` and
  `person["name"]`. Reading a key that is not there names the keys that are.
- **Assignment through both forms**, including new keys: `person.name = "Bob"`,
  `person["age"] = 31`, `person.country = "USA"`.
- **`delete`**: `delete person.country` or `delete person["job"]`. Deleting a
  key that is not there is harmless, so `delete` is safe to repeat.
- **`in` for dictionaries**, asking about keys: `"name" in person`.
- **`keys()` and `values()`** built-ins, both returning lists.
- **Iteration**, in three shapes: `for key in d` walks the keys,
  `for key, value in d` walks the pairs, and the same two-name form over a
  list or string yields index and item.
- **Nested dictionaries**, with chains like `person.address.street` and
  `employee["address"]["zip"]` reading and writing through as expected.
- **Merging with `+`**: `{x: 1, y: 2} + {y: 3, z: 4}` is
  `{x: 1, y: 3, z: 4}`, leaving both operands untouched.
- `len()` counts entries and `type()` answers `"dict"`; `==` compares
  dictionaries by content.
- New AST nodes `DictNode`, `DictEntryNode`, `MemberNode`,
  `MemberAssignNode` and `DeleteNode`, all rendered by `tree`; new tokens
  for `.` and the `delete` keyword.
- `examples/dicts.nova`, ending with a word-frequency counter.

### Changed

- A `{` in expression position now opens a dictionary. Blocks are unaffected:
  `{` is never an infix operator, so the condition in `if x { ... }` still
  ends at the brace, and blocks are always read by the statement rules.
- `keys` and `values` join the reserved built-in names.
- `help` covers dictionaries; the banner reads `NOVALANG v0.6.0`.

### Note

`values()` returns whatever the dictionary holds, so the list it hands back
could be mixed even though a list you built yourself had to hold one kind of
item. That seam was removed one release later — see v0.6.1, which lets every
list hold a mix.

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

[0.9.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.8.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.7.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.6.1]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.6.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.5.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.4.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.3.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.2.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.1.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
