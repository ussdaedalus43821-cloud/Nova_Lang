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

## [1.0.0] - 2026-09-02 — First Stable Release

Stage 13. Polish and documentation, and the line drawn under Stages 1–12:
NovaLang is a complete, self-hosting, embeddable scripting language with a
standard library and a two-way Python bridge. No language, standard-library,
or embedding-API behavior changes in this release — every example and test
from the pre-release verification pass (core regression, the full Stage 11
stdlib suite, and the Stage 12 embedding suite) was re-confirmed green
immediately beforehand.

### Added

- **`README.md`** — the project's front door: what NovaLang is, quick
  start, full language syntax, standard library reference, the embedding
  API, a tour of `examples/`, measured performance numbers, the security
  model, and how to contribute.
- **`CONTRIBUTING.md`** — guidelines for extending the language: the
  Lexer → Parser → AST → Interpreter pipeline contract, the host/
  self-hosted parity rule (`novalang.py` and `novalang.nova` must agree,
  byte-for-byte, on every example), the scope-barrier rule, coding style
  (no `eval`/`exec`, no parser generators, no regexes in the core
  pipeline), and the testing expectations for a change before it merges.
- This changelog entry, and the `v1.0.0` git tag marking the release.

### Changed

- Version banner and `__version__` bumped from `0.12.0` to `1.0.0` in both
  `novalang.py` (the REPL welcome banner, the `help` text's version line,
  and the module docstring's stage list) and `novalang.nova` (header
  comment), across the board — this is the same codebase Stage 12 shipped,
  now versioned and documented as a stable release rather than an
  in-progress build.

### Notes for integrators

- Summarizing the pre-release verification pass: all 10 Stage 1–9 example
  files are byte-identical between direct execution and `--bootstrap`; the
  new `examples/stdlib_full_test.nova` exercises the entire Stage 11
  standard library and passes identically on both engines; the Stage 12
  embedding demos (`embedding_demo.py`, `reactor_sim_integration.py`,
  `daedalus_integration.py`) all behave as documented; `nova.call()`
  throughput measured at ~2,200 calls/sec, comfortably inside a 60fps
  frame budget. See `README.md`'s Performance and Security sections for
  the numbers and the sandboxing model in context.
- The one open naming note from that pass still applies: a blocked
  `python.import(...)` raises `NovaError`/`NovaLangError` labeled
  `PythonError`, not `ModuleNotAllowedError` — the restricted-bridge
  *design* was explicitly confirmed during Stage 12 and is unchanged in
  this release; only the label name differs from an earlier guess at it.

---

## [0.12.0] - 2026-09-01 — Embedding & Integration

Stage 12. NovaLang as a scripting engine inside a Python program, in both
directions - and a design departure from what was asked for, explained
below, because the literal request was a sandbox escape.

### Added

- **`Nova`, the Python-side embedding class**: `eval(code)`, `exec(code)`,
  `load_file(path)`, `call(name, *args)`, each converting between Python
  and NovaLang values and raising `NovaLangError` - never a raw
  `NovaError` - on trouble in the NovaLang code, so calling code never has
  to import `novalang` to handle failures.
- **`compile(code)`**, returning a `CompiledScript` whose `run()` skips
  lexing and parsing on every call - the precompile option for a script
  invoked every frame. `eval()`/`exec()` also cache by source text
  automatically, so calling either with an unchanged script string every
  frame (a game loop's condition script, typically) costs no repeated
  parsing even without calling `compile()` yourself.
  `examples/daedalus_integration.py` measures this concretely: 15
  `nova.call()`s to an already-loaded function in 0.007s on this machine,
  about 2,200 calls/sec - far inside a 60fps frame budget (16.7ms/frame).
- **`Nova.expose(name, value)`**, registering a Python value so
  `python.get/call/set("name...")` can reach it from NovaLang;
  **`expose_module(module)`**, allowing `python.import()` to succeed for a
  module beyond the built-in allowlist; **`expose_global(name, value)`**,
  binding a value directly as a NovaLang global, so a script can write
  `reactor.temp` and `reactor.scram()` with no `python.*` wrapper at all.
- **`python.import`, `python.call`, `python.get`, `python.set`** on the
  NovaLang side - a namespace dict like `json`, not new syntax.
  `python.import` only succeeds on its own for a short, fixed allowlist of
  pure-computation stdlib modules (`math`, `random`, `statistics`,
  `itertools`, `functools`, `string`, `re`, `datetime`, `json`,
  `collections`); anything else needs `Nova.expose_module()` first.
  `python.call`/`get`/`set` resolve a dotted name against what the
  embedding program has explicitly exposed - there is no path from
  `python.*` to anything the host did not choose to hand over.
- **`PythonObjectProxy`**, a `dict` subclass wrapping a live Python object.
  NovaLang's member/index access already only ever calls `in`, `[]` and
  iteration on a dict-typed value (`isinstance(x, dict)`, true for a
  subclass) - overriding those four is all it took for `reactor.temp` to
  read the real attribute, `reactor.temp = x` to write it, and
  `reactor.scram` to resolve to a real, callable method, with no changes
  needed anywhere else in the interpreter. Passing a plain Python object
  as an argument to `Nova.call()` wraps it the same way automatically.
- Self-hosted parity: `novalang.nova` binds the same `python` namespace
  and delegates each case straight to the host's real `python.*` -
  `novalang.nova` is itself NovaLang code running under that host, so its
  own `python` global already is the live, registry-backed one; nothing
  needed duplicating. Verified byte-identical, `examples/embedding.nova`
  included.
- `examples/embedding.nova` and its companion `examples/embedding_demo.py`
  - calling Python module functions, a Python object's methods, a blocked
  import, and a NovaLang function called back from Python. `examples/
  reactor_script.nova` and `examples/reactor_sim_integration.py` - a
  control script scramming a (mock) reactor through a live proxy every
  simulation tick. `examples/daedalus_waves.nova` and `examples/
  daedalus_integration.py` - `spawn_wave`/`spawn_level_wave` returning
  enemy data for a (mock) game loop to spawn, with the throughput numbers
  above. The reactor and Daedalus integrations are self-contained mocks
  with the same shape (`temp`/`power`/`scram()`, `spawn_wave(n, kind)`)
  real ones would have - there is no actual Reactor Sim or Daedalus
  source in this repository to integrate with, so these demonstrate the
  pattern to adapt, not a drop-in connection to your real projects.
- The banner reads `NOVALANG v0.12.0`; `help` gains an Embedding section.

### Changed from what was asked

**`python.import`/`call`/`get`/`set` were specified as unrestricted access
to any Python module or function.** That is not what got built, on
purpose: a NovaLang script is meant to be things like a level script, a
mod, someone else's config logic - exactly the kind of content a real
embedding boundary should not trust with `python.call("os.system", ...)`.
The allowlist-plus-explicit-registry design above satisfies every example
in the request (`python.get("math.pi")`, `reactor.scram()`) while keeping
a script unable to reach anything the host did not choose to expose. This
is standard practice for embedded scripting (Lua, JS-in-browser both work
this way) and was worth doing even though it means the built API is
narrower than literally specified.

### Note

A Python exception raised inside a function NovaLang calls (`python.call`,
or a value exposed with `expose`/`expose_global`) is caught and re-raised
as a NovaError labelled `PythonError` - catchable with an ordinary
`try { ... } catch e { ... }`, same as any other NovaLang error. The
reverse direction (`Nova.eval`/`exec`/`load_file`/`call`, and a NovaLang
function value handed to Python) always raises `NovaLangError`, whether
the underlying problem was a parse error, a runtime error, or a stray
`return`/`break`/`continue` outside anything that would catch it.

`python.call`'s NovaLang-facing arity is capped at five extra arguments
(six including the name) in the self-hosted interpreter, since NovaLang
has no argument-spread syntax to forward an arbitrary-length list to
another variadic call - `novalang.nova`'s own `call_builtin` has to
enumerate each arity by hand, the same way it already does for `range()`
and `pow()`. The host side has no such limit.

---

## [0.11.0] - 2026-09-01 — Standard Library

Stage 11. Batteries included: over 40 global functions, no import needed,
identical under `--bootstrap`.

### Added

- **Time**: `time()`, `sleep(ms)`, `now()` (an ISO-8601 timestamp),
  `format_time(timestamp, fmt)` (strftime-style codes).
- **Random**: `random()`, `randint(a, b)` (inclusive), `choice(list)`,
  `shuffle(list)` (in place).
- **Math**: `abs`, `round` (an optional second argument sets the decimal
  places), `floor`, `ceil`, `sqrt`, `pow`, `sin`, `cos`, `tan`, `ln`,
  `log10`, plus the constants `PI` and `E`, and `min` / `max` / `sum`,
  each accepting either several numbers or one list of them.
- **System**: `env(key)` (the variable's value, or nothing if it is unset),
  `exit(code)`, `args()` (extra words after the script's own name on the
  command line - `novalang.py file.nova a b` and
  `novalang.py --bootstrap file.nova a b` both give the target `["a", "b"]`),
  `platform()`.
- **JSON**: `json.dumps`, `json.loads`, `json.pretty` - a namespace, not new
  syntax. `json` is an ordinary predefined dictionary whose values are
  callable, so `json.dumps(x)` is exactly the dot-call Stage 6 already had.
- **Filesystem**: `cwd()`, `mkdir(path)` (creates intermediate directories,
  and does not mind if the path already exists), `remove(path)` (a file or
  an empty directory), `rename(old, new)`, `copy(src, dst)`.
- **Strings**: `regex(pattern, text)` (true/false), `replace_all`,
  `split_lines` (handles `\n`, `\r\n` and `\r` alike), `pad` / `pad_left`
  (space-pad to a length), `reverse` (a string or a list), and `sorted`
  (ascending, or descending with a second argument of `true`).
- **Debugging**: `assert(condition)` and `assert(condition, message)`;
  `log(x, ...)`, which writes to stderr with a timestamp rather than to
  stdout.
- **Higher-order functions**: `map(f, list)`, `filter(f, list)`,
  `reduce(f, list)` and `reduce(f, list, start)`. `f` may be a function you
  wrote or a built-in - `map(str, [1, 2, 3])` and `reduce(max, numbers)`
  both work, since a built-in is a callable value like any other.
- `examples/stdlib_demo.nova`, exercising every function above, including a
  small `filter` → `map` → `reduce` pipeline.

### Changed

- **`BuiltinFunction` gained an opt-in `needs_interpreter` flag**, used only
  by `map`/`filter`/`reduce`: calling back into a function value passed as
  an argument needs the interpreter itself, not just the already-evaluated
  arguments every other built-in works with. `visit_CallNode`'s calling
  logic is now `Interpreter.call_value`, a small reusable method - the
  refactor that made this possible.
- The self-hosted interpreter needed no such change: `map`/`filter`/`reduce`
  are ordinary NovaLang functions inside `novalang.nova`'s `call_builtin`,
  calling back through `call_target_value` - the dispatcher a `Call` node
  already used. Nothing new to build there.
- `examples/strings.nova`'s Stage 5 hand-rolled `reverse(text)` is retired
  in favor of the new built-in of the same name, which does the same thing.
  Two other examples had incidental local names that collided with new
  built-ins and were renamed: `sum` to `running_total` in `lists.nova`,
  `log` to `log_file` in `file_demo.nova`.
- The banner reads `NOVALANG v0.11.0`; `help` gains a Standard library
  section.

### Note

Every new built-in type-checks its arguments and raises a `NovaError`
labelled `TypeError` on a bad one (`catch e` then sees e.g.
`"TypeError: sqrt() needs a number, but got a string"`) - the same labelling
`FileNotFoundError` introduced in v0.7.0, applied here for the first time
to argument-type mistakes rather than file trouble. `assert()`'s failures
are labelled `AssertionError` instead. Built-ins from earlier stages keep
their original bare `NovaError` wording; this labelling is new to Stage 11's
functions, not applied retroactively.

`round()` inherits Python's own rounding: `round(2.5)` is `2`, not `3`
(round-half-to-even, not round-half-up) - correct and intentional, since it
is exactly what `round()` does on both engines, but worth knowing if you
expected the more common convention.

Two of the largest built-ins by far - the self-hosted interpreter's own
`env`, `args`, `min`, `max`, `sum`, and about three dozen others - forced a
mechanical but wide rename inside `novalang.nova` itself: `env` (the
universal scope parameter throughout the interpreter, ~130 occurrences) to
`scope`, and `args` (the evaluated-arguments parameter used everywhere a
function is called, ~40 occurrences) to `call_args`. Every new built-in
name is now checked against `novalang.nova`'s own identifiers before it is
added, the same discipline `step` already required back in Stage 9.

---

## [0.10.0] - 2026-09-01 — Self-Hosting

Stage 10. NovaLang can now run NovaLang.

### Added

- **`novalang.nova`**, a second complete Lexer, Parser and Interpreter for
  the language - written in NovaLang itself, roughly 2,000 lines, with no
  classes (the language has none), so tokens, AST nodes, scopes, and even
  user-defined functions are represented as tagged dictionaries
  (`{kind: "Number", value: 5}`, `{kind: "function", params:, body:,
  closure:}`) threaded through explicit state, the same way you would write
  an interpreter in any language without objects.
- **`bootstrap.py`**, a small Python script that loads `novalang.nova`,
  appends one line calling its `run_file(path)` entry point with a target
  file's path, and hands the combined program to novalang.py's engine -
  which only ever runs `novalang.nova` itself. `novalang.nova` then reads
  the *target* file (through the ordinary `read()` built-in), and lexes,
  parses and runs it using the Lexer, Parser and Interpreter defined in
  NovaLang, not in Python.
- **`novalang.py --bootstrap file.nova`**, the same thing from the usual
  entry point.
- `examples/self_host_test.nova`, 34 checks across arithmetic, strings,
  lists, dictionaries, control flow, recursion, closures and try/catch,
  meant to be run both ways and diffed:
  ```
  python3 novalang.py examples/self_host_test.nova
  python3 novalang.py --bootstrap examples/self_host_test.nova
  ```
  A stricter check - the self-hosted interpreter parsing and running its
  *own* ~2,000-line source - is `python3 bootstrap.py novalang.nova`.
- Two small built-ins, `abspath` and `dirname`, exposed to `novalang.nova`'s
  own module loader for canonicalizing import paths (so `"math.nova"` and
  `"./math.nova"` are recognized as the same file for caching and circular-
  import detection) - internal plumbing, not part of the documented
  language surface, the same way `novalang.nova` itself is not.

### Changed

- **Every existing example passes under `--bootstrap` with byte-identical
  output to running it directly** - `examples/fib.nova`, `loops.nova`,
  `lists.nova`, `strings.nova`, `dicts.nova`, `file_demo.nova`,
  `errors.nova` and `modules.nova` all verified.
- `MAX_CALL_DEPTH` rises from 200 to 1200, and Python's own recursion limit
  from 10,000 to 20,000. A self-hosted call costs several host-level calls
  in turn (eval an argument, dispatch on its AST kind, run its body,
  dispatch each statement...), so a target-level recursion of only 20 -
  `fib(20)`, say - was hitting the old ceiling well before doing anything
  unreasonable. Both numbers were raised empirically, tested against where
  CPython's own stack actually becomes a concern, with comfortable margin
  either side; this also means direct (non-bootstrapped) programs can now
  recurse considerably deeper than before, a purely permissive change.
- The banner reads `NOVALANG v0.10.0`; `help` mentions `--bootstrap`.

### Note

Three known compromises:

- **An uncaught error in a target program run under `--bootstrap` points
  into `novalang.nova`'s own source, not the target's.** `print(1/0)`
  reports "division by zero" correctly, but the caret lands on the line in
  the self-hosted interpreter that evaluates `/`, with a call stack of the
  interpreter's own functions (`eval_binop`, `eval_expr`, ...) rather than
  the target program's. This is a real limitation of a tree-walking
  meta-circular interpreter without its own separate traceback machinery.
  A *caught* error is unaffected - `catch e` binds exactly the right
  message text either way, since that was always just the thrown string.

Two more, both because NovaLang has no classes and no `nonlocal`:

- A target-language function value is a plain dictionary tagged
  `{kind: "function", ...}`. Printing one directly (not calling it) shows a
  hand-formatted `<function name(params)>`, matching the host - but a
  function value buried inside a *list or dictionary* that then gets
  printed will show that raw tagged dictionary instead, since the
  recursive formatter that handles that case is the host's own `str()`,
  which does not know about the tagging convention. None of the example
  files do this.
- The interpreter's own mutable bookkeeping - the call-depth counter, the
  module cache, the lexer and parser's position trackers - is carried in
  dictionaries mutated in place (`state["index"] = ...`) rather than plain
  local variables, and every helper function takes that state as an
  explicit parameter. This is not a style choice: a plain assignment inside
  a NovaLang function can never reach an enclosing function's locals (every
  call is a scope barrier, by design since v0.3.0), so a shared, mutated
  container is the only way to carry state across calls - `novalang.nova`
  is simply the largest program yet to run into that rule, and the fix a
  target program would already need to reach for.

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

[0.12.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.11.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
[0.10.0]: https://github.com/ussdaedalus43821-cloud/Nova_Lang
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
