# NovaLang

**NovaLang** is a simple, embeddable scripting language, implemented twice
over: once in Python (`novalang.py`), as a bytecode compiler and virtual
machine, and once again in NovaLang itself (`novalang.nova`) — a
self-hosted implementation that the Python engine can load and run under. The language itself has no
dependencies beyond the Python standard library, a real standard library
of its own, and a two-way embedding API for calling between Python and
NovaLang. (One example — the [ECS particle demo](#ecs--particle-engine) —
needs NumPy and pygame; nothing else in this repo does.)

```
source text  ->  Lexer     ->  tokens
tokens       ->  Parser    ->  AST
AST          ->  Compiler  ->  bytecode
bytecode     ->  VM        ->  a value
```

No `eval()`. No `exec()`. No parser generators. Every stage is built by
hand. See [Architecture](#architecture) for how the pieces fit, and for
the tree-walking interpreter that is kept as the fallback and reference.

**Current release: v2.2.0.** See [`CHANGELOG.md`](CHANGELOG.md) for the
full history, from the 14 build stages of 1.x to the bytecode VM.

## Contents

- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Language syntax](#language-syntax)
- [Standard library](#standard-library)
- [Self-hosting](#self-hosting)
- [Toolchain: formatter & linter](#toolchain-formatter--linter)
- [Type annotations](#type-annotations)
- [Packages](#packages)
- [Editor support](#editor-support)
- [Embedding NovaLang in Python](#embedding-novalang-in-python)
- [ECS & particle engine](#ecs--particle-engine)
- [Examples](#examples)
- [Performance](#performance)
- [Security](#security)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Quick start

Requires Python 3.7+. Nothing else — no `pip install`, no build step.
CI runs the full suite on Linux for Python 3.7 through 3.13, on macOS for 3.12
and on Windows for 3.12. Windows with Python 3.7 also passes, but only with the
tree-walker's deepest recursions skipped in one comparison (see
[`docs/CI.md`](docs/CI.md)), so it is reported, not required.

```bash
git clone <this repository>
cd Nova_Lang

# The REPL
python3 novalang.py

# Run a script
python3 novalang.py examples/fib.nova

# Run a one-liner (an argument that is not a readable file is run as code)
python3 novalang.py "1 + 2 * 3"

# Run the same script through the self-hosted interpreter instead
python3 novalang.py --bootstrap examples/fib.nova
```

The REPL collects blocks and list literals across lines. Blank lines inside
open blocks and lists stay in the draft. A blank line after a bare block
header submits it for a syntax diagnostic. The REPL also has a few commands:

```
nova> help              # full syntax and built-in reference
nova> vars               # list the globals you've defined
nova> tree 1 + 2 * 3      # show the AST instead of running it
nova> exit               # or quit, or Ctrl-D
```

## Architecture

Every way of running NovaLang — the command line, the REPL, `import`,
`--bootstrap` and the embedding API — goes through the same pipeline in
`novalang.py`:

```
source text ──Lexer──▶ tokens ──Parser──▶ AST ──type gate──▶ (refused, or)
                                               │
                                               ├──Compiler──▶ bytecode ──VM──▶ value    default
                                               └──Interpreter (tree-walker)──▶ value     --tree-walk
```

1. **Lexer** (`Lexer`) turns source text into tokens, tracking the
   position of each so every error can point at its line and column.
2. **Parser** (`Parser`) is recursive descent: tokens become an AST of
   `*Node` objects. Annotations (`x: int`, `-> string`) are parsed here
   and ignored at run time.
3. **Type gate** (`type_gate`). A program with annotations, or one that
   imports modules, is checked by `tools/nova-typecheck.py` before a
   single statement runs, and refused with a `TypeCheckError` if it
   breaks a contract (see [Type annotations](#type-annotations)). Each
   interpreter remembers what it has checked, so an import graph is
   checked once per load. A program with neither skips the checker.
4. **Compiler**, in two passes over the AST:
   - `Resolver` decides where every name lives. Module globals stay a
     dictionary. Other bindings get numbered frame slots, or cells when a
     closure captures them. A name whose binding can only be known when
     the program runs (a closure reading a variable that may be defined
     later, or a REPL input assigning a global an earlier input made) is
     compiled to a check that decides at run time, exactly as the
     tree-walker would.
   - `Compiler` emits about 60 opcodes for a stack machine into a
     `CodeObject` (instructions, constants, names, line positions). Each
     function body is its own `CodeObject`. `try`/`catch`/`finally` uses
     an exception table in the style of CPython 3.11, so a `try` costs
     nothing until something is thrown; a `finally` is copied onto each
     way out of its block.
   - `verify()` checks the result before it runs: every jump lands on an
     instruction, every slot and constant exists, and the stack depth
     agrees wherever two paths meet.

   `python3 novalang.py --dis file.nova` prints the bytecode. A parsed
   program is compiled once and the result kept on its AST, so a
   `Nova.compile()` script, or a source string `eval()`/`exec()` has
   already seen, is never compiled again.
5. **VM** (`execute`) runs bytecode in a single loop. A call from one
   NovaLang function to another pushes a `Frame` (its slots, its value
   stack, its closure cells) rather than recursing in Python, so the
   call depth limit (1200) is NovaLang's own. The hottest operations
   (integer and float arithmetic, comparisons, indexing) take an inline
   fast path when both operands have the same exact type; every other
   case, and every error, goes through the same shared operation
   functions the tree-walker uses.

### The tree-walker: fallback and reference

The `Interpreter` class that ran every program up to v1.1.0 still ships,
unchanged in behavior. It evaluates the AST directly, node by node:

```bash
python3 novalang.py --tree-walk program.nova
python3 novalang.py --tree-walk --bootstrap program.nova
```

```python
Nova(engine="tree")          # or Interpreter("tree")
```

It is kept for two reasons. It is a fallback if a VM bug is ever found
in the field. And it is the reference the VM is held to:
`tests/run_all.py` station 11 runs every `.nova` file in the repository,
every example under `--bootstrap`, 300 seeded random programs and the
embedding API on both engines, and requires the same stdout, stderr and
exit status, byte for byte. Both engines call the same functions for
what an operation means (`binary_operation`, `compare_operation`,
`index_operation` and the rest), so they cannot disagree about
semantics, only about control flow, and that is what station 11 tests.

**Known limitation: deep recursion under `--tree-walk` on Windows.** The
tree-walker spends about nine Python frames on each NovaLang call, and before
Python 3.11 each of those also uses native stack. Windows has far less of it
than Linux or macOS, so a program that recurses toward the 1200-call limit
can overflow the native stack there and end the whole process, instead of
printing `call depth of 1200 exceeded`. This was observed on Windows with
Python 3.7; Python 3.8 to 3.10 on Windows are expected to behave the same but
are not tested, and Python 3.11 and later are not affected. The default
engine is the VM, which keeps NovaLang calls on its own stack and is not
affected. To keep the comparison honest, station 11 does not give the
tree-walker the 16 of its 300 generated programs that reach the limit on those
platforms: it decides them on the VM, prints a `SKIPPED:` line and compares the
other 284 on both engines (`docs/CI.md`). A larger-stack thread for the
tree-walker would remove the limitation; it has not been decided.

### Around the core

- `novalang.nova` is the self-hosted implementation: a lexer, parser and
  tree-walking interpreter written in NovaLang, which itself runs on the
  host's VM (see [Self-hosting](#self-hosting)).
- `tools/` holds what reads NovaLang without running it: the formatter,
  linter and type checker share one front end (`tools/nova_ast.py`, the
  real Lexer and Parser with comments and spans kept) and one set of
  scope rules (`tools/nova_scope.py`). The language server
  (`tools/nova-lsp.py`) builds on all three, and `tools/nova-pkg.py`
  installs packages.
- `bootstrap.py` runs `novalang.nova` on whichever engine was asked for.

## Language syntax

```nova
# variables
let x = 10                 # declares x in this block
x = x + 1                  # assignment (updates an outer x if one exists)

# functions
def add(a, b) {
    return a + b
}

# conditionals
if x > 10 {
    print("big")
} else if x > 0 {
    print("small")
} else {
    print("non-positive")
}

# loops
while x < 20 {
    x = x + 1
}
for i = 0 to 10 { print(i) }          # counts 0..10; inclusive on both ends
for i = 10 downto 0 { print(i) }      # counts 10..0, also inclusive
for i = 0 to 100 step 10 { print(i) } # 0, 10, ... 100
# `to` and `downto` include the last value; range(n) does not:
# range(3) is [0, 1, 2], while `for i = 0 to 3` visits 0, 1, 2 and 3.
for item in [1, 2, 3] { print(item) }
for key, value in {a: 1, b: 2} { print(key, value) }
break                                    # leave a loop early
continue                                 # jump to the next turn

# lists and dictionaries
let a = [1, 2, 3]
a[0] = 10
let person = {name: "Ada", age: 36}
person.age = 37
delete person.age

# strings
let name = "world"
print(f"Hello, {name}!")               # f-strings
print("Hello"[1:4])                     # slicing

# error handling
try {
    throw("something went wrong")
} catch e {
    print("caught:", e)
} finally {
    print("always runs")
}

# modules
import "./utils.nova"                   # utils.<exported name>
import "./utils.nova" as u               # u.<exported name>
import "./utils.nova" with helper         # helper, straight into scope
export def helper() { return 1 }         # mark a name as importable
export let VERSION = "1.0"
```

Full syntax reference, including every operator and built-in, is available
at any time from the REPL with `help`.

### Scoping

A name first assigned inside a block belongs to that block and disappears
when the block ends. Assigning a name that already exists updates it —
*unless* it lives in an enclosing **function's** locals: a plain
assignment can never reach across a function boundary. Only the contents
of a shared mutable value (a list or dictionary passed in, or a global)
can carry state across separate calls:

```nova
let state = {count: 0}
def increment() {
    state["count"] = state["count"] + 1   # OK - mutates a shared dict
}
increment()
increment()
print(state["count"])   # 2
```

## Standard library

Every function below is a global — no `import` needed — and behaves
identically whether the script runs directly (`novalang.py`) or through
the self-hosted interpreter (`novalang.py --bootstrap`).

| Area | Functions |
|---|---|
| **Time** | `time()` `sleep(ms)` `now()` `format_time(t, fmt)` |
| **Random** | `random()` `randint(a, b)` `choice(a)` `shuffle(a)` |
| **Math** | `abs` `round` `floor` `ceil` `sqrt` `pow` `sin` `cos` `tan` `ln` `log10`, plus the constants `PI` and `E`; `min(...)` `max(...)` `sum(...)` |
| **System** | `env(key)` `exit(code)` `args()` `platform()` |
| **JSON** | `json.dumps(v)` `json.loads(s)` `json.pretty(v)` |
| **Filesystem** | `read(path)` `write(path, text)` `append(path, text)` `exists(path)` `listdir(path)` `delete(path)` `cwd()` `mkdir(p)` `remove(p)` `rename(a, b)` `copy(a, b)` |
| **Strings** | `upper` `lower` `trim` `split(s, sep)` `join(a, sep)` `str(x)` `num(s)` `regex(pat, s)` `replace_all(s, a, b)` `split_lines(s)` `pad(s, n)` `pad_left(s, n)` `reverse(x)` `sorted(a)` `sorted(a, true)` |
| **Core collections** | `len(a)` `append(a, v)` `pop(a)` / `pop(a, i)` `range(n)` / `range(a, b)` / `range(a, b, step)` `type(x)` `keys(d)` `values(d)` |
| **Debugging** | `assert(c)` / `assert(c, msg)` `log(x, ...)` (like `print`, to stderr with a timestamp) |
| **Higher-order** | `map(f, a)` `filter(f, a)` `reduce(f, a)` / `reduce(f, a, start)` — `f` may be a NovaLang function or any built-in |
| **I/O** | `print(x, ...)` `input(prompt)` |

`examples/stdlib_demo.nova` walks through these with commentary, and
`examples/stdlib_full_test.nova` is an exhaustive regression test — every
function above, checked against its expected return value.

## Self-hosting

`novalang.nova` is a second, complete Lexer/Parser/Interpreter for
NovaLang — written in NovaLang itself, and loaded by the Python engine
rather than run standalone (NovaLang compiles to bytecode for its own VM,
not to an executable, so something has to host it):

```bash
python3 novalang.py --bootstrap program.nova [args...]
# equivalently:
python3 bootstrap.py program.nova [args...]
```

`bootstrap.py` reads `novalang.nova`'s source, appends a call to its
`run_file(path)` entry point naming your target file, and hands the
combined program to `novalang.py`'s own engine — which only ever sees
`novalang.nova`, never your target file's source directly.
`examples/self_host_test.nova` exists specifically to be run both ways and
diffed; every example in this repository is held to the same standard:
identical output, byte-for-byte, direct vs. `--bootstrap`.

## Toolchain: formatter & linter

```bash
python3 novalang.py --check program.nova    # lint without running
python3 novalang.py --typecheck program.nova  # check type annotations
python3 novalang.py --format program.nova   # rewrite in the standard layout
python3 tests/run_all.py                    # the full regression suite
python3 tests/run_all.py --station compiler # one station; repeat --station for several
python3 tests/run_all.py --station cli      # command-line modes, diagnostics and exit codes
python3 tests/run_all.py --station embedding # callbacks, value conversion and host errors
python3 tests/run_all.py --station repl      # interactive transcripts on both engines
python3 tests/run_all.py --station input-errors # formatter refusal and malformed tool input
python3 tests/run_all.py --report checks.jsonl # flush each result for long audit runs
```

The complete suite records 1,951 parent checks. The REPL station contributes
one check for 46 tests, the input-errors station one for six tests with
parameterized cases, the portability station one for 14 tests that simulate
Windows on any platform, and the conformance station five checks (the corpus
is well-formed, then one per engine, the policy dialect's engine included).

Statement and branch coverage, including Python subprocesses, can be measured
with `python3 tests/run_coverage.py` after installing the optional coverage tool.
See [coverage instructions](docs/COVERAGE.md) for setup, report scope and limitations.

**`--check`** (`tools/nova-lint.py`) reads the program with the real
Lexer and Parser and never executes it. It reports undefined names
(`E001`, exit status 1), and variables that are assigned but never read
(`W001`) or code after a `return` / `break` / `continue` / `throw`
(`W002`) as warnings; `--strict` makes warnings fail too. Its scope model
is the interpreter's: a name first assigned inside a block is gone after
it, and loop variables do not leak. A script for an embedding host can
declare the names the host provides with `# nova-lint: globals a, b`.

**`--format`** (`tools/nova-fmt.py`) applies one layout: 4-space indents,
`{` on the header line, `} else {`, one statement per line, spaces around
binary operators, at most one blank line in a row, lists and dictionaries
on one line when they fit in 100 columns. It never changes how a literal
is spelled and keeps every comment. Before writing anything it re-parses
its own output and refuses to proceed unless the AST is unchanged, every
comment survived, and a second run would change nothing. Run it directly
with `--check` to fail CI when a file is not formatted. Calls and long
expressions are never wrapped, because NovaLang's grammar does not allow
them to span lines.

## Type annotations

Annotations are optional, and NovaLang stays dynamic wherever they are
left out. Where they are written, they are contracts, checked **before the
program runs**:

```nova
def add(a: int, b: int) -> int {
    return a + b
}
let name: string = "nova"
add(1, "two")        # refused before anything runs:
                     # T002 argument 2 of add() must be an int, but this is a string
```

The types are `int`, `float`, `string`, `bool`, `list`, `dict` and `any`.
An `int` is a whole number and fits wherever a `float` is expected
(NovaLang has one number type at run time; `int` promises it is whole).
Anything unannotated is `any`, and `any` fits everything, so it is the
escape hatch.

- **What is checked:** argument types and counts, return values against
  `-> type`, a typed function that can reach its end without returning,
  reassignments of declared variables, and operators, conditions, indexes
  and fields wherever the types are known. Built-ins with clear signatures
  (`upper`, `sqrt`, `len`, ...) are checked too.
- **When:** `python3 novalang.py --typecheck file.nova` checks a file and
  everything it imports. Running a program checks it automatically; this
  covers direct runs, `--bootstrap`, imports and the embedding API. A
  program with type errors is refused without running a single line.
- **Untyped files** run exactly as before. A file with no annotations and
  no imports never even loads the checker. A file with no annotations
  that imports a typed module has only its calls into that module checked,
  so the module's contracts cannot be bypassed.
- **At run time** annotations are ignored, so annotated code runs at
  exactly the speed of the same code without them.

See `examples/types.nova` and `tools/nova-typecheck.py` (its docstring
lists every error code).

## Packages

A project lists its dependencies in a `nova.json` at its root:

```json
{
  "name": "my-project",
  "version": "1.0.0",
  "registry": "../registry",
  "dependencies": {
    "math-utils": "^1.0.0",
    "local-lib": {"path": "../local-lib"},
    "remote-lib": {"git": "https://example.com/remote-lib.git", "ref": "v1.2.0"}
  }
}
```

```bash
python3 tools/nova-pkg.py install            # resolve, write nova.lock, install
python3 tools/nova-pkg.py install --frozen   # install exactly nova.lock (for CI)
python3 tools/nova-pkg.py verify             # check nothing in .nova_modules was edited
```

Then any file in the project can write `import "math-utils"`, which binds
`math_utils` (`as` still picks another name). A plain lowercase name is a
package. Anything ending in `.nova`, or with a `/` in it, is a file, and
resolves exactly as it always has.

- **Sources.** Version ranges (`1.2.3`, `^1.2.3`, `~1.2.3`, `*`) come from
  a local registry: `"registry"` in `nova.json` or `$NOVA_REGISTRY`, laid
  out as `<registry>/<name>/<version>/`. Path and git dependencies point
  at a directory or a repository.
- **Flat install.** There is one version of each package, in
  `.nova_modules/<name>/`, found by walking up from the importing file as
  Node does. If two packages need versions no single version satisfies,
  `install` stops and names them, instead of installing two copies.
- **`nova.lock`** records each package's exact version, its source (a git
  commit, not a tag) and a SHA-256 of its files. Commit it.
  `.nova_modules` carries its own `.gitignore`, so it is never committed.
- **Stop the line.** The interpreter refuses to import a package when
  `nova.json` has changed since `nova.lock` was written, when `nova.lock`
  is missing, or when the installed packages are not the ones it records.
  The error says to run `nova-pkg.py install`.
- **A package** is a directory with its own `nova.json`, whose `"main"`
  names its entry file (default `main.nova`). Its own relative imports
  work as usual.

## Editor support

`tools/nova-lsp.py` is a Language Server Protocol server, using only the
Python standard library. Any LSP-capable editor gets, for `.nova` files:

- **diagnostics** from `nova-lint` and `nova-typecheck`, as you type,
  underlining the whole problem;
- **formatting** with `nova-fmt`;
- **go-to-definition** for locals, parameters, functions, imported names,
  module members and packages;
- **hover** showing types, e.g. `def add(a: int, b: int) -> int`.

`editors/vscode/` is a ready-made VS Code extension: a thin client for that
server, plus a syntax-highlighting grammar. See its
[README](editors/vscode/README.md) for installing it.

## Embedding NovaLang in Python

Stage 12 added a `Nova` class for running NovaLang scripts from a Python
program, and reaching back into Python from NovaLang through an explicit,
narrow bridge — not unrestricted process access.

```python
from novalang import Nova, NovaLangError

nova = Nova()                           # add allow_python=True to give scripts python.* (see Security)
nova.load_file("script.nova")
result = nova.call("add", 2, 3)          # call a NovaLang function
value = nova.eval("1 + 2 * 3")            # evaluate an expression
nova.exec("let x = 10")                    # run for effect

try:
    nova.eval("this is not valid (")
except NovaLangError as error:
    print("caught:", error)                # every failure raises this, never a raw exception
```

| Method | Purpose |
|---|---|
| `Nova(engine=None, allow_python=False)` | A fresh interpreter — nothing is shared between instances. `python.*` is **off** unless `allow_python=True` |
| `eval(code)` / `exec(code)` | Run a string of NovaLang, returning its value (or discarding it) — cached by source text, so calling the same script every frame costs no repeated parsing |
| `compile(code)` | Lex and parse once, returning a `CompiledScript` you can `run()` repeatedly yourself |
| `load_file(path)` | Read and run a `.nova` file; its own relative imports resolve against its directory |
| `call(name, *args)` | Call an already-defined NovaLang function by name with Python arguments |
| `expose(name, value)` | Make a Python value reachable from NovaLang as `python.get/call/set("name...", ...)` |
| `expose_global(name, value)` | Bind a Python value as a NovaLang **global**, so a script writes `name.field` directly, no `python.*` wrapper |
| `expose_module(module)` | Allow `python.import("name")` to succeed for a module beyond the built-in allowlist |

Passing a plain Python **object** (a class instance) as an argument to a
NovaLang function (via `call()`, or as an argument from `expose_global`)
wraps it as a **live proxy**: reading and writing its attributes from
NovaLang reads and writes the real object, with no copying and no
pre-registration needed.

A plain Python **dict or list**, though, is a different story:
`to_nova_value()` converts it into a *new* NovaLang value each time it
crosses the boundary — a one-time copy, not a live reference. So if you
`call()` a NovaLang function that mutates a dict argument and expect the
Python-held original to reflect that mutation afterward, it won't:
mutations only show up in whatever that call *returns*. The fix is the
same pattern used throughout `examples/` (`reactor_sim.nova`'s `reactor`,
`daedalus_sim.nova`'s `enemies`, `ecs_particles.nova`'s `sim`): every
function that mutates such a value returns it, and the Python caller
reassigns — `state = nova.call("update", state, ...)` — every time, not
just on the calls where you remember a mutation happened.

A NovaLang function returned through `eval()`, `call()`, or a compiled script
becomes a Python callable tied to its interpreter. Functions inside returned
lists and dictionaries are converted too. Exposed Python functions and methods
can accept these NovaLang functions as callback arguments:

```python
nova.exec("def twice(x) { return x * 2 }")
callback = nova.eval("twice")
assert callback(21) == 42
nova.expose_global("apply", lambda fn, value: fn(value))
assert nova.eval("apply(twice, 21)") == 42
```

Callback failures surface in Python as `NovaLangError`. Ordinary exceptions from
exposed functions or object properties become `PythonError` diagnostics that a
NovaLang `try`/`catch` can handle. Host `SystemExit` and `KeyboardInterrupt`
remain control-flow signals. A failed operation does not roll back host mutations
that already happened.

From the NovaLang side, the `python` namespace reaches back into Python — once the
host has asked for it with `Nova(allow_python=True)` (without that, every `python.*`
call refuses with a `PythonError`):

```nova
python.import("math")                # only succeeds for an allowlisted module
python.call("math.sqrt", 2)           # call a Python function by dotted name
python.get("math.pi")                 # read a Python value by dotted name
python.set("computed", 6 * 7)          # write one back, or define a fresh entry
```

See [Security](#security) below for exactly what `python.*` can and can't
reach, and `examples/embedding.nova` / `examples/embedding_demo.py` for a
complete, runnable walkthrough of both directions together.

## ECS & particle engine

`lib/ecs.nova` is a real Entity-Component-System — entities, components,
`query()` by component combination, `spawn_entity()`/`despawn_entity()`
at runtime — and `lib/spatial_hash.nova` is a grid-based spatial hash
with O(1) average insert/query. Both are genuinely fast at what
NovaLang's interpreter can actually do.

What they are *not* is where `examples/ecs_particles.nova`'s
25,000–50,000 simulated particles live. That decision is worth
explaining rather than just asserting, because it's a direct answer to
"why isn't the physics system just NovaLang, like the spec asked for":

**Measured, before writing any of it** — a bare NovaLang arithmetic loop
runs at ~162,000 iterations/sec; a realistic per-particle physics update
(reading/writing dict fields, the natural way to represent a particle in
NovaLang) runs at ~41,000–66,000 particles/sec. At 50,000 particles, the
movement update *alone* costs ~750ms — 45x an entire 16.7ms frame budget
at 60fps — before collision detection, which costs *more* per particle
than movement, touches anything. That's a constant-factor ceiling from
tree-walking interpretation itself (every `+`, every dict lookup is a
Python function call walking an AST node), not an algorithmic one — a
spatial hash fixes O(n²) *complexity*, and complexity was never the
bottleneck at these counts.

So the split is: **NovaLang owns the ECS and everything at gameplay
scale** — emitters, force fields, the mouse's current interaction mode,
spawn timing — using `lib/ecs.nova` for real, with entities numbering in
the tens to low hundreds, comfortably inside its real throughput.
**Python owns the particle data itself**, tens of thousands of positions
and velocities as contiguous NumPy arrays (struct-of-arrays, not 50,000
Python objects), updated with vectorized array operations —
`examples/particle_engine.py`. `examples/ecs_particles.nova`'s
`world_step()` is called once a frame, not once per particle, and
returns a small "directives" dict (gravity, active force fields, spawn
requests, mouse mode) that Python applies to all 50,000 particles in one
shot. NovaLang decides *what*; NumPy does it, to everything, at once.

The same "pass state in, get new state back" pattern from
`examples/embedding_templates/` applies here too, with a sharper edge:
every `ecs_particles.nova` function that takes `sim` returns it, and the
caller must reassign `sim = nova.call(...)` every time — see the caveat
in [Embedding NovaLang in Python](#embedding-novalang-in-python) above
about dicts/lists being copied, not proxied, across the boundary. This
was caught by testing the file, not by inspection.

**Run `examples/particle_engine_selftest.py` before trusting any FPS
number.** The environment this was built in had no NumPy, no pygame, and
no network access to install either — so while `lib/ecs.nova`,
`lib/spatial_hash.nova`, and `examples/ecs_particles.nova` were fully
tested (their self-tests pass, host and `--bootstrap`), the NumPy
collision code in `particle_engine.py` was validated only as an
algorithm — checked against a brute-force O(n²) reference as a
plain-Python prototype (no NumPy needed to run that check) — not
executed. The self-test re-runs that exact cross-check against your real
NumPy on the real `ParticleEngine` class; if it passes, the
transcription was faithful.

```bash
pip3 install numpy pygame        # only ecs_demo.py needs these - the language itself needs neither
python3 examples/particle_engine_selftest.py   # run this first - no display needed
python3 examples/ecs_demo.py                    # the real demo
```

In `ecs_demo.py`: drag the slider or press 1–5 for particle-count
presets, hold left/right mouse to attract/repel, `G`/`C`/`V` toggle
gravity/collisions/cycle color mode, `F`/`X` spawn/despawn a force field
at the mouse, `Q` toggles the fast (vectorized pixel-splat) render path
against a slower "quality" one (real drawn circles) so you can see the
difference directly.

## Examples

All in `examples/`, runnable directly or with `--bootstrap`:

| File | Demonstrates |
|---|---|
| `fib.nova` | Recursion, `def`/`return`, the spec's own example |
| `loops.nova` | `while`, `for ... to/downto/step`, `break`/`continue` |
| `lists.nova` | Lists, indexing, slicing |
| `strings.nova` | String literals, escapes, f-strings, slicing |
| `dicts.nova` | Dictionary literals, dot/bracket access, `delete` |
| `file_demo.nova` | File I/O in a self-cleaning scratch folder |
| `errors.nova` | `try`/`catch`/`finally`, `throw` |
| `modules.nova` + `math.nova` | Every form of `import`, `export` |
| `circular_a.nova` / `circular_b.nova` | Circular-import detection |
| `self_host_test.nova` | Run directly and with `--bootstrap`; diff the output |
| `stdlib_demo.nova` | A guided tour of the Stage 11 standard library |
| `stdlib_full_test.nova` | An exhaustive standard-library regression test |
| `embedding.nova` + `embedding_demo.py` | `python.*` from NovaLang, `Nova`/`expose()` from Python, together |
| `reactor_script.nova` + `reactor_sim_integration.py` | A live Python object (`reactor.temp`, `reactor.scram()`) driven from NovaLang each simulation tick |
| `daedalus_waves.nova` + `daedalus_integration.py` | `nova.call()` from inside a Python game loop, with a throughput benchmark |
| `ecs_self_test.nova` | Exhaustive test of `lib/ecs.nova`: spawn/despawn, masks, queries |
| `spatial_hash_self_test.nova` | Exhaustive test of `lib/spatial_hash.nova`, including a moving-across-cell-boundary case |
| `ecs_particles.nova` + `particle_engine.py` + `ecs_demo.py` | The ECS/NumPy particle engine — see [ECS & particle engine](#ecs--particle-engine) |
| `particle_engine_selftest.py` | Cross-checks the vectorized collision code against a brute-force reference — run this first |

## Performance

The VM is the default because it was faster on every benchmark in
`tests/bench/` when these numbers were taken (`python3 tests/bench/run_bench.py [--tree-walk]`). Whole
process, best of 5, on the same machine:

| Benchmark | VM | Tree-walker |
|---|---|---|
| fib(22) | 0.212 s | 0.406 s |
| examples/fib.nova | 0.133 s | 0.192 s |
| examples/fib.nova --bootstrap | 4.130 s | 10.573 s |
| self_host_test --bootstrap | 0.632 s | 1.071 s |
| loops (200k iterations) | 0.961 s | 2.546 s |
| closures (100k closure calls) | 0.493 s | 0.694 s |
| index_assign (550k stores and deletes)¹ | 2.483 s | 2.823 s |

¹ Measured for 2.0.1, after the assignment fast paths; the other rows are from 2.0.0.

These rows were not re-measured for 2.2.0, and the machine is not recorded, so read them as a ratio between
the two engines, not as absolute times. `tests/benchmarks/run.py` is the newer harness: it records the machine,
the Python version, the commit and every raw sample, and it separates start-up, compiling, a steady-state loop
and the embedding API. An independent same-machine comparison on Linux with Python 3.13 found 2.2.0 slower
than 2.0.0 to start (an empty program about 28% slower) and on a 200,000-iteration loop (about 14% slower).
The `restricted` profile adds a few percent to the loop. There is no hard real-time guarantee: single
calls into NovaLang occasionally take several hundred microseconds.

Compiling costs a little at load time; a program that loads many modules
and runs briefly gains less than one that loops.

`examples/daedalus_integration.py` benchmarks `nova.call()` — 15 calls
into a NovaLang wave-spawning script from a simulated game loop — and
prints its own throughput:

```
15 spawn_level_wave() calls in 0.0067s (2242 calls/sec) - comfortably
inside a 60fps frame budget (16.7ms) even before compile() or eval()'s
automatic per-source caching.
```

Measured at about **2,800-3,700 calls/sec** on the VM (about 2,200 on
1.1.0's tree-walker, on other hardware) — comfortably inside a 60fps (16.7ms-per-frame) budget for a game
or simulation calling into NovaLang once or a few times per frame.
`eval()`/`exec()` cache by source text automatically (`compile()` is
available if you want to hold the parsed form yourself), so a script
string reused every frame costs no repeated lexing/parsing beyond the
first call.

## Security

`python.*` is a **deliberate, narrow bridge**, not unrestricted access to
the host process:

- **`python.import(name)`** only auto-succeeds for a short, fixed
  allowlist: `math`, `random`, `statistics`, `itertools`, `functools`,
  `string`, `re`, `datetime`, `json`, `collections`. Anything else raises
  an error (labeled `PythonError`) — an embedding program must explicitly
  opt a module in with `Nova.expose_module(...)` first.
- **`python.call` / `python.get` / `python.set`** only ever reach names
  the embedding Python program chose to hand over with `Nova.expose()` (or
  a module already allowlisted/exposed) — there is no way for a NovaLang
  script to reach an arbitrary Python name on its own.
- **`expose_global()`** and passing a Python object as a function argument
  both wrap it as a *live proxy*: NovaLang can read and write only the
  attributes that object already exposes (`dir()`-visible, non-private
  names) — not import new modules, not reach outside the object it was
  given.
- There is **no transaction/rollback**: if a NovaLang script mutates an
  exposed object and then errors partway through, the mutations already
  made stay made. This is expected behavior, not corruption — treat each
  `python.set`/attribute write as taking effect immediately, not as part
  of an atomic batch.
- **`python.*` is off by default.** Without `--allow-python` on the command
  line, or `Nova(allow_python=True)` in an embedding host, `python.import`,
  `call`, `get` and `set` all refuse with a `PythonError`. A host that runs
  scripts it did not write should leave it off and hand over what it means
  to with `expose_global()`.
- **Names that start with `_` are unreachable** through `python.*` and
  through a proxy, for reading *and* writing, so `json.__builtins__`,
  `obj.__class__` and an object's private state are all out of reach.
- **A module alias is not a way round the allowlist.** An attribute whose
  value is a module is visible only if that module is itself allowed, by its
  exact name (on the list, or exposed with `expose_module`). Submodules are
  not granted with their package: a host that needs `os.path` exposes it
  (`nova.expose_module(os.path)`) as well as `os`. `re.enum.bltns`, `json.codecs` and
  `statistics.sys` would otherwise lead to `builtins` and `sys`. A module
  that is handed over stays a proxy, and printing one shows
  `<python object module>`. A test walks every path the gate allows from each
  allowed module, on every Python the CI matrix covers, and fails if one
  reaches a forbidden module or a builtin such as `eval` or `open`.
- **Scripts cannot write to modules, classes or functions.** `python.set` and
  assignment through a proxy work only on object instances the host exposed;
  `python.set("json.dumps", 5)` would otherwise replace `json.dumps` for the
  whole process. Give scripts an object, not a module, for settings they may
  change.
- This is **capability gating, not a sandbox.** Run code you did not write in
  a separate process or container as well; see
  [`docs/decisions/0003-security-stance.md`](docs/decisions/0003-security-stance.md)
  and [`docs/design/python-bridge-hardening.md`](docs/design/python-bridge-hardening.md).

This changed in 2.1.0 (issue 1): before it, `python.*` was on everywhere and
reachable names included private attributes and module aliases.

This design was a deliberate departure from an earlier, broader spec
(unrestricted access to any Python module/function) — see
[`CHANGELOG.md`](CHANGELOG.md)'s `[0.12.0]` entry for the full reasoning.
If your embedding program needs more, opt it in explicitly with
`expose()` / `expose_module()` / `expose_global()`; don't loosen the
allowlist itself without deciding that's actually what you want.

## Running a program you did not write: the `restricted` profile

Status: **Owner-reviewed and Architect-reviewed, pending independent third-party audit.** The words below are the
whole claim; [`docs/spec/16-sandbox.md`](docs/spec/16-sandbox.md) (`[sbx.claims]`) is the only place that may say more.

NovaLang has two profiles. `trusted` (the default) is the language as it has always behaved. `restricted` is opt-in and
is **capability gating plus resource limits**: the program can reach only what the embedder grants, and cannot use more
steps, time, output or collection size than the embedder allows.

```sh
python3 novalang.py --profile restricted --allow-read data --allow-write out --limit steps=100000 --limit time=2000 prog.nova
python3 novalang.py --profile restricted --deterministic --seed 42 --clock-start 1700000000 prog.nova   # replayable
python3 novalang.py --isolate --profile restricted --allow-regex --wall-ms 3000 prog.nova               # in a child process
```

```python
from novalang import Nova
nova = Nova(profile="restricted", read=["data"], env=["HOME_NAME"], limits={"steps": 100_000, "time": 2000})
nova.exec('print(read("data/in.txt"))')       # fine
nova.exec('print(read("/etc/hosts"))')        # FileError: /etc/hosts is outside the folders this program may use
nova.exec('print(env("PATH"))')               # nothing: PATH was not granted
```

What is guaranteed, on the bytecode VM, the tree-walker and the self-hosted interpreter, apart from the known gaps
listed next: a `restricted` program defines no
name of a capability it was not granted (files, imports, environment, clock, random, stdin, process, regex, the Python
bridge), and reaches files, imports and environment variables only inside the grants; it writes no more output, takes no
more steps or time, and builds no longer string, list or dictionary than the limits allow, and a fatal limit (steps, time,
output) cannot be caught by the program; each of these is a NovaLang error, never a failure of the host.

Known gaps, found in a review of 2.2.0 and not yet fixed: `copy(file, folder)` does not re-check where the copy
will land, so a symbolic link inside the granted folder that is named like the source file and points elsewhere
lets the copy write outside the grant; the clock is read about once every 1,000 steps, so a single very expensive
operation (searching a list of a million items, say) can run well past the time limit before it is noticed; and a
blocking read from stdin is not interrupted by the in-process time limit (the wall-clock limit of `--isolate` is
the control for that). Until these are fixed, do not rely on a `restricted` run alone to contain a program you do
not trust.

What is **not** guaranteed: isolation (the engine runs in your process, on a Python that is not a security boundary);
the total memory a program uses; anything about a Python module or host function you grant; paths in folders that
another process can change while the program runs; side channels; hard links and mounts inside a granted folder;
Windows-only file names beyond the tested ones; and the `trusted` profile, which has no limits. `--isolate` /
`run_isolated()` adds a child process that is killed on a wall-clock or output overrun (and, on Linux only, an
address-space limit): it is not a container. Run code you do not trust in a container or a separate machine as well.
The threat model, the test inventory and the known gaps are in
[`docs/design/m11-review-package.md`](docs/design/m11-review-package.md).

## Specification

[`docs/spec/`](docs/spec/README.md) is the written, normative description of the
language, still a draft: lexical structure, values, expressions, scoping, the error
catalogue, the security properties and the policy dialect, with more chapters being added. Its host-neutral test corpus, [`tests/conformance/`](tests/conformance/README.md),
runs on every engine (`python3 tests/run_all.py --station conformance`), and
[`docs/spec/DIVERGENCES.md`](docs/spec/DIVERGENCES.md) lists where an
implementation does not yet follow it.

## Roadmap

[`docs/ROADMAP.md`](docs/ROADMAP.md) sets out the milestones after M6, from
continuous verification and a written language specification through a security
model, runtime work and a package registry, and what each product in the wider
Nova ecosystem needs before it can start. Decisions that need the project
owner are recorded in [`docs/decisions/`](docs/decisions/README.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the pipeline architecture,
the host/self-hosted parity rule, coding style, and what to test before
sending a change.

## License

MIT — see [`LICENSE`](LICENSE).
