# 11. Embedding

A *host program* can run NovaLang inside itself: give a script some of its own
values and functions, run it, read what it produces, and call back into it. This
is how a game runs its rules or a service runs its configuration logic. The first
half of this chapter (`emb.*`) says what an embedding host MUST offer, in terms
that do not depend on the host's language; the reference host is a Python library
(`Nova` in `novalang.py`) and its names are used for the operations. The second
half (`py.*`) is the bridge a script can use to reach Python itself. It exists only
in the reference host, is off unless the host turns it on, and is the `python`
profile (`README.md`).

The self-hosted interpreter has no host program to embed it, so the `embedding`
cases do not apply to it.

## [emb.model] Engines, running and state

A host creates an **engine**. An engine has its own global scope, its own loaded
modules and its own bound host values; **two engines share nothing**, so two
levels of a game or two simulations run in full isolation.

`eval(source)` and `exec(source)` run a program in the engine's global scope. What
the program defines (`let`, `def`, `import`) **stays** in the engine, so a later
`eval` or `call` sees it. `eval` returns the value of the program's last
top-level statement when that is an expression or a `let` or an assignment (the
value assigned), and `nothing` when the program is empty or ends in a statement
that has no value; `exec` returns nothing. What `print` writes goes to the host's
standard output as it does for a program (`[val.display]`).

`compile(source)` parses and checks a program once and returns a script that can
be `run` any number of times, on any engine, without parsing again. Running it is
the same as `eval` of its source.

## [emb.values] Values across the boundary

Every value that crosses, in either direction, is converted:

| NovaLang | Host (Python) | Notes |
| --- | --- | --- |
| `nothing` | `None` | |
| boolean | `bool` | |
| integer | `int` | within 4,000 digits both ways (`[port.integers]`) |
| float | `float` | infinity and NaN cross unchanged |
| string | `str` | |
| list | `list` | a **copy**: changing the copy does not change the original |
| dictionary | `dict` | a copy; keys are strings |
| function | a callable | called with positional arguments, below |

From the host, a `tuple` becomes a list; a `dict` whose keys are not strings has
them turned into text (two keys that become the same text keep the later one, and
which text a non-string becomes is the host's); an object that is none of the above
(an instance of a class, a set, a generator) becomes a **live object**: the script
reads its attributes and calls its methods, and assigning to an attribute changes
the host's object (it crosses by reference, unlike a list). A live object in a
script has the type `dictionary` and prints as `<python object Name>`
(`[val.display]`, host-defined text). A number outside the language's bound
(`[port.integers]`) is refused when it crosses: `the result has too many digits -
an integer cannot have more than 4000 digits`.

## [emb.globals] Giving a script host values

`expose_global(name, value)` defines `name` as a global of the engine with the
converted value. A script reads it like any global; a function the host passes is
called like a script function, a live object is used with `.` (`reactor.temp`,
`reactor.scram()`). The binding is an ordinary global: a script may assign to it
(`limit = 99`), shadow it with `let`, and a later `expose_global` of the same name
replaces it. The name is checked as any global name is: a built-in's name is
refused with `NovaLangError: 'print' is a built-in function and cannot be used as a
global name` (`[scope.reserved]`), and a value the language cannot hold (a number
beyond its bound, a module the host did not grant, `[py.registry]`) is refused with
the same error kind as a script would get.

A host function is called with the script's arguments converted, and what it
returns is converted back. The number of arguments is the host function's business:
the engine passes exactly what the script wrote, and a mismatch is the host
function's own failure (`[emb.errors]`).

## [emb.calls] The host calling the script

`call(name, arguments...)` calls a global function of the engine by name with the
arguments converted, and returns its result converted. `call("nope")` is
`undefined name 'nope'`, calling a global that is not a function is `'counter' is
not a function`, and a wrong number of arguments is `add() expects 2 argument(s)
but got 1` (`[err.call]`). A script function handed to the host (the result of
`eval("add")`, or an argument to a host function) is a callable that does the same
call: the host calls it with positional arguments, and the count is checked as for
any call.

## [emb.errors] Errors across the boundary

Every failure of the script reaches the host as **one kind of error**
(`NovaLangError`), carrying the script error's label and message
(`NovaLangError.nova_error`) and, as text, what `catch` would bind
(`[err.try-catch]`): `division by zero`, `AssertionError: nope`,
`FileNotFoundError: nofile`. That includes a syntax error, which is found when the
source is compiled, before any statement of it runs, and a failure of a call the
host makes (`call`) or of exposing a value. **No other exception type may leave
`eval`, `exec`, `call`, `compile` or `expose_global`** because of the script
(`[sec.error-boundary]`); the host's own bugs excepted.

The other direction. A host function that fails (raises) is, to the script, an error
with the label `PythonError` and a message that carries the host's own words
(`PythonError: ValueError: kaboom`); a `try` catches it like any error
(`[err.try-catch]`). A script error inside a script function that a host function
called back is likewise a `PythonError` to the script, naming the original.

`exit(n)` in a script is **not an error**: it propagates out of `eval`, `exec` or
`call` as the host's exit signal (`SystemExit` with the status), and `finally`
blocks of the `try` statements it leaves run first (`[host.process]`). The same
goes for a host function that asks to exit. After an exit the engine can still be
used. Running out of call depth is the ordinary error of `[port.limits]`.

## [py.off] The Python bridge is off by default

A script reaches Python only through the global `python`, and only if the host
asked for it (`--allow-python` on the command line, `Nova(allow_python=True)` for
an embedding host). Otherwise `python` is a stub whose every member fails with
`PythonError: python.* is disabled: run novalang.py with --allow-python, or create
the embedding host with Nova(allow_python=True)` (the words after the first colon
are the host's). `python` is defined in every program and module alike
(`[mod.scope]`), and a module gains no reach the program lacked
([ADR 0003](../decisions/0003-security-stance.md)). Exposing a value with
`expose_global` does not need the bridge.

## [py.import] `python.import`, `call`, `get` and `set`

- `python.import("math")` makes a module available by name and returns `nothing`.
  Only these may be imported on the script's own say: `math`, `random`,
  `statistics`, `itertools`, `functools`, `string`, `re`, `datetime`, `json`,
  `collections`; any other is `PythonError: "os" is not on the list of modules
  python.import() allows on its own (...)`. A host may allow more with
  `expose_module`. The argument MUST be a string (`python.import() needs a string,
  but got a number`).
- `python.call("math.sqrt", 16)` calls the function reached by the dotted name
  with the converted arguments and returns the converted result (`4`).
  `python.get("math.pi")` reads a value. A name that does not exist is
  `PythonError: "obj.zzz" has no attribute "zzz"`, and calling something that is
  not callable is `"obj.v" is not callable`. A function that raises is
  `PythonError: ValueError: math domain error`.
- `python.set("flag", 5)` with a name that has no dot defines an entry of this
  engine's registry that `python.get("flag")` reads back.

## [py.access] What a script can reach through the bridge

The bridge is a narrow door, not access to the process. Every name that a script
reads or writes through `python.get`, `call`, `set`, or a live object goes through
one gate:

1. **A name that starts with `_` is never visible**, for reading, writing or
   calling, on every object (`"obj._p" has no attribute "_p"`; `cannot set private
   attribute "_p"`). This hides `__builtins__`, `__class__`, `__globals__` and the
   private state of the host's own objects.
2. **A module is visible only if it was granted**: its exact name is on the
   import list above, or the host exposed it. A package does not carry its
   submodules (`json.decoder`, `collections.abc` and `os.path` stay hidden unless
   granted), and a module that a granted module holds under a public name
   (`re.enum.bltns`, which is Python's `builtins`) is hidden too. A hidden name
   behaves as if it did not exist: `PythonError: "json" is not available to this
   script` or `... has no attribute ...`.
3. Everything else is visible: the functions, classes and constants of a granted
   module, and the public attributes of the host's objects.

## [py.write] Writing

A script may write only to **an object instance the host exposed**: `python.set`
and assignment through a live object work for an attribute of an instance
(`obj.v = 9`), and `python.set("obj.v", 9)` is the same write. It MUST NOT write to
a module, a class or a function, whose changes would be shared by the whole
process: `python.set("math.pi", 3)` is `PythonError: cannot modify the module
"math": python.set and assignment through a proxy only write to objects the host
exposed, not to modules, classes or functions`. A write to a name that starts with
`_` is refused as above.

## [py.registry] What the host grants

`expose(name, value)` makes `value` reachable as `python.get`/`call`/`set` with a
dotted name that starts with `name`; `expose_module(module)` additionally allows
`python.import` of a module beyond the list; `expose_global` binds a value as a
global and grants a module it is given. **Nothing is exposed automatically**: a
module the host did not hand over, or that the import list does not name, cannot
be handed to a script, directly, inside a list or dictionary, or as the result of a
call: `PythonError: the module "os" cannot be handed to a script: it is not on the
python.import() list and the embedding program did not expose it`.

The bridge is a deny-by-default door and not a sandbox: a script that must be
untrusted still needs a separate process or container ([ADR 0003](../decisions/0003-security-stance.md)).
Resource use by an allowed module (a regular expression that backtracks badly, a
huge `random` draw) is not bounded here (`[sec.limits]`).
