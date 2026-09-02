# NovaLang

**NovaLang** is a simple, embeddable scripting language, implemented twice
over: once as a hand-written Python interpreter (`novalang.py`), and once
again in NovaLang itself (`novalang.nova`) — a self-hosted implementation
that the Python engine can load and run under. It has no dependencies
beyond the Python standard library, a real standard library of its own,
and a two-way embedding API for calling between Python and NovaLang.

```
source text  ->  Lexer       ->  tokens
tokens       ->  Parser      ->  AST (Abstract Syntax Tree)
AST          ->  Interpreter ->  a value
```

No `eval()`. No `exec()`. No parser generators. Every stage — lexer,
parser, AST, tree-walking interpreter — is built by hand, in both the
Python engine and the self-hosted one.

**Current release: v1.0.0.** See [`CHANGELOG.md`](CHANGELOG.md) for the
full history across all 13 build stages.

## Contents

- [Quick start](#quick-start)
- [Language syntax](#language-syntax)
- [Standard library](#standard-library)
- [Self-hosting](#self-hosting)
- [Embedding NovaLang in Python](#embedding-novalang-in-python)
- [Examples](#examples)
- [Performance](#performance)
- [Security](#security)
- [Contributing](#contributing)
- [License](#license)

## Quick start

Requires Python 3.7+. Nothing else — no `pip install`, no build step.

```bash
git clone <this repository>
cd Nova_Lang

# The REPL
python3 novalang.py

# Run a script
python3 novalang.py examples/fib.nova

# Run a one-liner
python3 novalang.py "1 + 2 * 3"

# Run the same script through the self-hosted interpreter instead
python3 novalang.py --bootstrap examples/fib.nova
```

The REPL accepts multi-line input (an unclosed `{` keeps the prompt open),
and has a few of its own commands:

```
nova> help              # full syntax and built-in reference
nova> vars               # list the globals you've defined
nova> tree 1 + 2 * 3      # show the AST instead of running it
nova> exit               # or quit, or Ctrl-D
```

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
for i = 0 to 10 { print(i) }          # counts 0..9; `downto` counts down
for i = 0 to 100 step 10 { print(i) }
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
rather than run standalone (NovaLang has no compiler of its own to turn
itself into an executable):

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

## Embedding NovaLang in Python

Stage 12 added a `Nova` class for running NovaLang scripts from a Python
program, and reaching back into Python from NovaLang through an explicit,
narrow bridge — not unrestricted process access.

```python
from novalang import Nova, NovaLangError

nova = Nova()
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
| `Nova()` | A fresh, isolated interpreter — nothing is shared between instances |
| `eval(code)` / `exec(code)` | Run a string of NovaLang, returning its value (or discarding it) — cached by source text, so calling the same script every frame costs no repeated parsing |
| `compile(code)` | Lex and parse once, returning a `CompiledScript` you can `run()` repeatedly yourself |
| `load_file(path)` | Read and run a `.nova` file; its own relative imports resolve against its directory |
| `call(name, *args)` | Call an already-defined NovaLang function by name with Python arguments |
| `expose(name, value)` | Make a Python value reachable from NovaLang as `python.get/call/set("name...", ...)` |
| `expose_global(name, value)` | Bind a Python value as a NovaLang **global**, so a script writes `name.field` directly, no `python.*` wrapper |
| `expose_module(module)` | Allow `python.import("name")` to succeed for a module beyond the built-in allowlist |

Passing a plain Python object as an argument to a NovaLang function (via
`call()`, or as an argument from `expose_global`) wraps it as a **live
proxy**: reading and writing its attributes from NovaLang reads and writes
the real object, with no copying and no pre-registration needed.

From the NovaLang side, the `python` namespace reaches back into Python:

```nova
python.import("math")                # only succeeds for an allowlisted module
python.call("math.sqrt", 2)           # call a Python function by dotted name
python.get("math.pi")                 # read a Python value by dotted name
python.set("computed", 6 * 7)          # write one back, or define a fresh entry
```

See [Security](#security) below for exactly what `python.*` can and can't
reach, and `examples/embedding.nova` / `examples/embedding_demo.py` for a
complete, runnable walkthrough of both directions together.

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

## Performance

`examples/daedalus_integration.py` benchmarks `nova.call()` — 15 calls
into a NovaLang wave-spawning script from a simulated game loop — and
prints its own throughput:

```
15 spawn_level_wave() calls in 0.0067s (2242 calls/sec) - comfortably
inside a 60fps frame budget (16.7ms) even before compile() or eval()'s
automatic per-source caching.
```

Measured consistently around **~2,200 calls/sec** on ordinary developer
hardware — comfortably inside a 60fps (16.7ms-per-frame) budget for a game
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
- None of this matters when running `novalang.py` directly — the `python`
  namespace only exists for a script running *inside* an embedding Python
  program via the `Nova` class.

This design was a deliberate departure from an earlier, broader spec
(unrestricted access to any Python module/function) — see
[`CHANGELOG.md`](CHANGELOG.md)'s `[0.12.0]` entry for the full reasoning.
If your embedding program needs more, opt it in explicitly with
`expose()` / `expose_module()` / `expose_global()`; don't loosen the
allowlist itself without deciding that's actually what you want.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the pipeline architecture,
the host/self-hosted parity rule, coding style, and what to test before
sending a change.

## License

MIT — see [`LICENSE`](LICENSE).
