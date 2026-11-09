# 16. The sandbox profile: capabilities and limits

Status: **Owner-reviewed and Architect-reviewed, pending independent third-party audit.** This chapter is the
specification of milestone M11. **Implemented** on the bytecode VM, the tree-walker and the
self-hosted interpreter: the profiles, every capability, the path rules and every limit
(`[sbx.capabilities]`, `[sbx.paths]`, `[sbx.limits]`); every cell of the coverage matrix is covered
(`tests/security/matrix.py --strict`). **Also written:** the subprocess runner (`[sbx.runner]`, slice 5 of M11). The threat model is
[`../design/m11-threat-model.md`](../design/m11-threat-model.md) and the decision behind it is
[ADR 0003](../decisions/0003-security-stance.md).

**What this chapter claims, and what it does not.** It specifies *capability gating* (a
program reaches only what the embedder granted) and *resource limits* (a program uses no more
than the embedder allowed). It does **not** specify, and NovaLang does not claim, isolation:
the engine runs inside a Python process that is not a security boundary
(`[sbx.claims]`). Code you did not write should also run in a separate process or container.

`05-security.md` states the language's own properties (no ambient authority, no dynamic code,
no reflection). `10-host.md` says what the host functions do when they are present. This
chapter says when they are present, and what bounds a run.

## [sbx.profiles] Profiles

An engine runs a program under one of two profiles, chosen by the embedder when the engine is
created.

- **`trusted`** is the behaviour NovaLang has always had: every host function is defined, the
  Python bridge follows `[py.off]`, and only the limits of `[port.limits]` apply. It is the
  default of the command line and of an embedded engine, so nothing that runs today changes.
  It has no step budget, no time limit and no output limit, because a long-running trusted
  program is legitimate. **It must not be used for code you did not write.**
- **`restricted`** denies every capability of `[sbx.capabilities]` unless the embedder grants
  it, and applies every limit of `[sbx.limits]`. It is selected with `--profile restricted`
  on the command line and `Nova(profile="restricted", ...)` in a host program. The grants and
  the limits are the other arguments (below).

**Where the restricted profile starts.** It refuses to start on Windows with Python 3.7, with
`NovaLangError: the restricted profile needs Python 3.8 or later on Windows`: that Python does not follow
symbolic links when it resolves a path, so the path rules of `[sbx.paths]` would be weaker there without
saying so. No other combination is refused.

A profile applies to the whole engine: to the program, to every module it imports and to every
function the host calls into it. The profile cannot be changed from inside a program, and no
program can name a capability it was not given (`[sec.principles]`, `[sec.no-reflection]`).

**Configuration.** The command line takes `--allow-read DIR`, `--allow-write DIR`,
`--allow-import DIR`, `--allow-env NAME` (each repeatable), `--allow-clock`, `--allow-random`,
`--allow-stdin`, `--allow-process`, `--allow-regex`, `--allow-python-module MODULE` (repeatable) and
`--limit NAME=VALUE` (repeatable). The plain `--allow-python` of `[py.off]` opens the whole default
module list and is refused with `--profile restricted`. The embedding names are the same, with underscores:
`Nova(profile="restricted", read=[dir, ...], write=[...], import_from=[...], env=[name, ...],
clock=True, random=True, stdin=True, process=True, regex=True, python=[module, ...],
limits={"steps": 100000})`. In a conformance case the same settings are the `sandbox` object
(`tests/conformance/README.md`). An unknown name, or a value of the wrong kind, is refused
when the engine is created, not when the program runs: `NovaLangError: unknown sandbox
setting 'allow_reed'`. A grant that is empty (`read=[]`) is no grant.

## [sbx.capabilities] Capabilities

A **capability** is a group of names, or of forms of a name, that reach outside the program.
In `restricted` a capability is absent unless granted.

| Capability | What it defines | Grant | Notes |
| --- | --- | --- | --- |
| `files.read` | `read`, `exists`, `listdir` | folders | `[sbx.paths]` |
| `files.write` | `write`, `mkdir`, `remove`, `rename`, `copy`, the file form of `append` and the `delete` statement of a file | folders | `rename` and `copy` need `files.write` for both paths; `copy` also needs `files.read` for the source |
| `import` | `import` of a module | folders | modules are read from these folders only, `[sbx.paths]` |
| `env` | `env` | variable names | other names read as `nothing`, as an unset variable does |
| `clock` | `time`, `monotonic`, `now`, `sleep`, `format_time` | on or off | `format_time` reads the local time zone |
| `random` | `random`, `randint`, `choice`, `shuffle` | on or off | |
| `stdin` | `input` | on or off | |
| `process` | `exit`, `args`, `platform`, `cwd`, `abspath`, `realpath` | on or off | `exit` ends the run with that status and never ends the embedder's process; `cwd`, `abspath` and `realpath` reveal the layout of the machine |
| `regex` | `regex`, `replace_all` | on or off | a pattern can run for ever on a small input and no engine can interrupt it, so this is off unless granted, and a host that grants it must be able to stop the run from outside (`[sbx.limits]`, `time`) |
| `python` | the `python` bridge | module names | `[py.off]`, `[py.registry]`; a granted module is the embedder's decision. **The grant replaces the default import list of `[py.import]`**: only the modules named in it can be imported, because `re`, `random` and `datetime` are on the default list and would give back `regex`, `random` and `clock` |

There is **no network capability**: NovaLang has no network built-in, so nothing is defined
and nothing can be granted. A program reaches a network only through a Python module the
embedder granted under `python`, which is the embedder's decision and outside this
chapter's claims (`[sbx.claims]`).

Every other name is available in every profile, because it is a pure function of its
arguments or the language itself: `print`, `log`, `len`, `append` (list form), `pop`, `range`,
the string, list, dictionary and math functions, `sorted`, `map`, `filter`, `reduce`,
`assert`, `type`, `str`, `num`, `dirname`, `keys`, `values`, `sum`, `min`, `max`, the JSON
namespace and so on. `print` and `log` write only to the output of the run, which is limited
by `[sbx.limits]`.

**Denial.** A name that belongs to a capability that was not granted is *not defined*, exactly
as a name the program never declared: `undefined name 'read'`. This is the error of
`[err.name]`; it is catchable; it is the same on every engine; and it is not a partial or
pretend version of the function. The two forms that cannot be undefined because they are
syntax or share a name with a function that stays (the file form of `append`, the `delete`
statement of a file) fail with `NovaError: the 'files.write' capability is not granted`.
A program cannot tell a denied capability from a name that does not exist, except for those
two forms and for one more thing: **the names stay reserved** (`[scope.reserved]`) in every
profile, so `let read = 1` is refused with `'read' is a built-in function and cannot be used as a
variable name` whether or not `read` is granted. A program that compiles in `trusted` therefore
compiles in `restricted`, and the formatter, the linter and the parser need no profile. A module imported without the `import` capability fails with `ImportError: the
'import' capability is not granted`.

**The Python bridge** is the exception to "not defined": `python` is defined in every program
(`[py.off]`), and without a grant every member of it fails with the `PythonError` of
`[py.off]`. With a grant, `python.import` accepts only the modules named in the grant
(any other is the `PythonError` of `[py.import]` for a module not on the list).

**Grant.** With the capability granted, the functions are those of `10-host.md` and the
failures are theirs, unchanged: a file that is not there is `FileNotFoundError: <path>`.
What a grant of folders, names or modules covers is `[sbx.paths]` and the table above.
A grant never adds a name: it makes the names that `10-host.md` defines available.

**Granting `env` names.** `env("HOME")` with `HOME` granted is its value (or `nothing` when
the variable is not set); with `HOME` not granted it is `nothing`, as it would be for an unset
variable, so a program cannot tell a hidden variable from a missing one.

## [sbx.paths] Which paths a grant covers

A grant of folders (`files.read`, `files.write`, `import`) covers a path when **all** of these
hold. They apply to every path argument of every function of the capability, and to the path
of every module `import` opens.

1. The path is resolved to the real, absolute path it names, with every symbolic link in it
   followed, against the engine's working directory.
2. The real path is **inside** one of the granted folders, themselves resolved the same way.
   A folder is inside itself. `..` is resolved before the comparison, so `a/../../x` is
   outside a grant of `a`. A path that is *outside* is denied however it was written
   (relative, absolute, with `..`, through a symbolic link, with a different letter case on
   a file system that ignores case, with a drive letter or UNC prefix).
3. A path that does not exist is judged by its closest existing parent, so a program cannot
   create a file outside the granted folders by naming one that is not there yet.
4. A denied path fails with `FileError: <path> is outside the folders this program may use`
   (for an `import`, `ImportError: <path> is outside the folders this program may use`),
   with the path as the program wrote it. The error is the same whether or not the path
   exists (a program learns nothing about files it may not use), and it is raised before the
   file system is touched.
5. A path that is not a string is the error `10-host.md` gives, in the same order.

Each rule is a cell of the coverage matrix, and needs a case on every engine:

| Cell | Rule |
| --- | --- |
| `paths.inside` | a path inside a granted folder works, written with or without `./` |
| `paths.dotdot` | a path that leaves the folder through `..` is denied |
| `paths.absolute` | an absolute path outside the folders is denied |
| `paths.symlink` | a symbolic link inside a folder that points outside is denied |
| `paths.case` | an outside path is outside however its letters are cased |
| `paths.prefix` | a folder whose name starts with a granted folder's name (`data2` beside `data`) is outside |
| `paths.missing` | a path that does not exist is judged by its closest existing parent |
| `paths.same-error` | a denied path gives the same error whether or not it exists |
| `paths.import` | `import` follows the same grant |

The check and the use are two steps. A path that another process can change between them is
not defended (`[sbx.claims]`, threat model N5).

## [sbx.limits] Limits

Every limit is an error of the kind named, never a host failure (`[sec.error-boundary]`). The
**fixed** limits apply in every profile at the values of `[port.limits]` and below; the
**configurable** ones apply in `restricted` only, with the defaults shown, and an embedder may
lower any of them but not raise a fixed one. The cell column names the row in the coverage
matrix; each row needs a case that makes the limit trip, on every engine.

| Cell | Limit and default | Error | Kind |
| --- | --- | --- | --- |
| `depth` | nested calls: 1200 (self-hosted 60), minimum 50 | `call depth of <N> exceeded - is the recursion missing a base case?` | catchable |
| `nesting` | nesting of the program's own text (brackets, blocks), minimum 100 | `the interpreter ran out of stack - recursion too deep` | catchable |
| `integer` | digits of an integer: 4000 | `the result has too many digits - an integer cannot have more than 4000 digits` | catchable |
| `list.repeat` | items of a list made by `*`: 1,000,000 | `repeating that list <n> times would exceed <N> items` | catchable |
| `list.plus` | items of a list made by `+` | `a list cannot grow beyond <N> items` | catchable |
| `list.append` | items of a list grown by `append` | `a list cannot grow beyond <N> items` | catchable |
| `list.range` | items of a list made by `range` | `range() would build a list of <n> items, which is too large` | catchable |
| `list.split` | items of a list made by `split`, `split_lines`, `listdir`, `keys`, `values` | `a list cannot grow beyond <N> items` | catchable |
| `string.repeat` | characters of a string made by `*`: 1,000,000 | `repeating that string <n> times would be too long` | catchable |
| `string.plus` | characters of a string made by `+` | `a string cannot grow beyond <N> characters` | catchable |
| `string.join` | characters of the result of `join`, `pad`, `pad_left`, `replace_all`, `upper`, `lower` | `a string cannot grow beyond <N> characters` | catchable |
| `string.text` | characters of the text of a value (`str`, `print`, interpolation) | `a string cannot grow beyond <N> characters` | catchable |
| `string.read` | characters of what `read` and `input` return | `a string cannot grow beyond <N> characters` | catchable |
| `dict.entries` | entries of a dictionary, made by assignment or by `+` of two dictionaries: 1,000,000 | `a dictionary cannot hold more than <N> entries` | catchable |
| `steps` | steps of one run: 5,000,000 | `LimitError: step budget of <N> steps exhausted - is there a loop that never ends?` | **fatal** |
| `time` | milliseconds of wall-clock time of one run: 5,000 | `LimitError: time limit of <N> ms exceeded` | **fatal** |
| `time.sleep` | a `sleep` that would pass the time limit | `LimitError: time limit of <N> ms exceeded`, at once, without sleeping | **fatal** |
| `output` | bytes written by `print` and `log` in one run: 1,000,000 | `LimitError: output limit of <N> bytes exceeded` | **fatal** |

`<N>` is the limit in force and `<n>` the size the operation would have reached, as in
`[port.limits]`; a case matches such a message with a pattern. The names of the configurable
limits for `--limit` and `limits={...}` are `steps`, `time`, `output`, `list`, `string`,
`dict`, `depth`: `list` sets `<N>` of every `list.*` row, `string` of every `string.*` row.

**Fatal limits.** An error of kind `fatal` **cannot be caught**: `try`/`catch`/`finally` do
not see it, a `finally` block does not run, and it ends the run at once with that error and
exit status 1. Otherwise a program could catch the budget error and carry on looping. The
output written before it stays. The engine itself is usable again for the next run, whose
counters start from zero (`[emb.model]`). A catchable limit is an ordinary error
(`[err.try-catch]`) and a program can recover from it.

**Steps.** A step is **one pass of a loop** (`while`, `for`) **or one call** (of a function or of a
built-in). Straight-line code costs nothing, because it is bounded by the size of the program;
everything that can run for long is a loop or a recursion. The bytecode VM, the tree-walker and
the self-hosted interpreter count exactly this. Another host may count something else (the game
port's bytecode VM counts instructions, `[pol.limits]`), so the number of steps a program takes is
**not** portable across hosts, and what a host guarantees is a bound on work: with the default
step budget, a loop of 20,000 simple passes is within it and an endless loop always trips it. Whether
a run also finishes inside the default time limit depends on the machine and on the engine (the
self-hosted interpreter is the slowest, a few thousand passes a second on a small CI machine), so
an embedder who runs real work in the self-hosted engine sets `time` to suit. The
budget is per run, and per call a host makes into the program; a host function that calls back
into the script is part of the same run and cannot reset it.

**Time.** The clock is monotonic. The engine checks the limit at least once every 1,000 steps
and in every host function that can wait (`sleep`, `input`). The error may therefore come a
little after the limit, but never from a program that ends sooner. A host function that
cannot be interrupted while it runs (`regex`, a function the embedder wrote) is not covered
by the engine's own check, which is why `regex` is a capability and why the subprocess
runner (slice 5 of M11) stops a run from outside.

**Output.** The write that would take the total over the limit is **not made at all**: the
output never exceeds it. Output counts the bytes as written (UTF-8, with the line break), the number
`byte_length` gives (`[lib.text]`).

**Sizes.** A size limit is checked **before** the memory is used, from the operands, so a
program cannot build the object first and be refused afterwards. This covers every operation
that can make a value longer than its operands, listed in the cells above. Where an operation
cannot produce more than a small multiple of its operands (`upper`, `lower`, `split`, `keys`,
`values`, `listdir`, `read`, `input`) the check is made on the result: the memory used before it is
refused is at most that multiple of what the operands already held, and every value is within
its limit by induction. The text of a
list or dictionary is cut off the moment it passes the limit, so a structure that shares
parts with itself fails at once instead of running for ever. The total of all the values a
program holds is not limited (`[sbx.claims]`).

**The policy dialect** (`12-policy-syntax.md`) has its own limits table, `[pol.limits]`, and
is brought under this chapter in slice 7 of M11.

## [sbx.determinism] The deterministic mode

For simulation, tests and replay. Three settings, **in either profile** (a `trusted` engine may be
deterministic too): `deterministic` (on or off), `seed` (a whole number, default 0) and `clock_start` (seconds
since 1970, between the years 1 and 9999, default 0, at most nine decimals). On the command line
`--deterministic`, `--seed N` and `--clock-start T`; in a host program
`Nova(deterministic=True, seed=42, clock_start=1700000000.5)`. `seed` and `clock_start` without
`deterministic` are refused. The capabilities still decide which names exist: in the `restricted` profile
`random` and `clock` must be granted for the functions below to be defined.

**The generator.** Knuth's 64-bit linear congruential generator, so that every host, and a host written in
another language, draws the same numbers. The state starts as `seed` modulo 2**64. A *draw* sets
`state = (6364136223846793005 * state + 1442695040888963407) mod 2**64` and gives `k = state >> 11`, a whole
number below 2**53. Then, with exact whole-number arithmetic:

- `random()` is `k / 2**53` (a float, exact);
- `randint(a, b)` is `a + (k * (b - a + 1)) >> 53`, one draw;
- `choice(list)` is the item at index `(k * length) >> 53`, one draw;
- `shuffle(list)` goes from the last index `i` down to 1 and swaps the item at `i` with the one at
  `(k * (i + 1)) >> 53`, one draw each, and gives the list itself.

Arguments are checked first, with the errors of `[host.random]`, and a call that fails draws nothing.

**The clock.** There is no clock to read. The program sees a virtual time that starts at `clock_start` and
advances only when it sleeps: `sleep(ms)` adds `ms / 1000` seconds **without waiting** and gives `nothing`.
`time()` is `clock_start` plus the seconds slept, `monotonic()` is the seconds slept (0 at the start), and
`now()` is `time()` as an ISO 8601 string in UTC, with the fraction (six digits, rounded to the nearest
microsecond, ties to even) only when it is not zero: `2023-11-14T22:13:20.500000+00:00`,
`2023-11-14T22:13:22+00:00`. `format_time(t, format)` writes in **UTC** (not the local time zone) and supports
exactly the directives every host must (`[host.time]`): `%Y %m %d %H %M %S %j %y %%`; any other directive is
`TypeError: format_time(): '%A' is not supported in the deterministic mode`, a format that ends in `%` is
`TypeError: format_time(): a format cannot end with '%'`, and a time outside the years 1 to 9999 is
`TypeError: now(): that time is out of range` (`format_time()` for the other function).

**The guarantee.** The same program, the same `seed` and `clock_start`, and the same inputs (files read,
standard input, environment, arguments) give the same output, the same error and the same exit status on the
bytecode VM, the tree-walker and the self-hosted interpreter. It is **not** a guarantee about: the real time
limit of `[sbx.limits]` (it measures the machine's clock, so a run near the limit can pass once and fail
another time), `platform()`, `cwd()` and `abspath()` (they describe the machine; do not grant `process` to a
replay), a granted Python module (`[sbx.claims]`), and the order in which a host function the embedder wrote
is called. Granting only `random` and `clock` makes a program deterministic.

Each row is a cell of the coverage matrix and needs a case on every engine:

| Cell | What it pins |
| --- | --- |
| `det.random` | `random()` draws the specified sequence |
| `det.randint` | `randint` draws the specified numbers, including a range of one and a negative low end |
| `det.choice` | `choice` picks the specified items |
| `det.shuffle` | `shuffle` makes the specified permutation, in place |
| `det.seed` | the same seed repeats, another seed differs, a negative or huge seed is taken modulo 2**64 |
| `det.time` | `time`, `monotonic` and `now` start at `clock_start` |
| `det.sleep` | `sleep` advances the virtual clock and does not wait |
| `det.format` | `format_time` writes UTC with the specified directives and refuses the others |
| `det.range` | a time outside the years 1 to 9999 is the specified error |
| `det.profiles` | it works in the `trusted` profile, and does not define a name the profile does not grant |

## [sbx.runner] The subprocess runner

The limits of `[sbx.limits]` are checked by the engine, so they cannot stop a call that never returns to it:
a pattern that backtracks for ever inside `regex`, or a host function the embedder wrote. The **runner** adds a
check from outside. It starts the interpreter in a separate process, watches the clock and the output from the
parent, and kills the child when a limit is passed.

`novalang.py --isolate [flags] program.nova` runs the program with the same flags in a separate process; in a
host program `run_isolated(source, path=None, engine="vm", bootstrap=False, args=(), input_text=None, wall_ms=None,
memory_mb=1024, output_cap=None, pass_env=(), profile="restricted", **settings)` takes the settings of
`Nova()` and gives an `IsolatedResult` (`stdout`, `stderr`, `status`, `killed` and the `error` line the runner
added). The flags `--wall-ms`, `--memory-mb`, `--output-cap` and `--pass-env NAME` tune it and are refused
without `--isolate`. A mistake in the settings is refused before anything starts.

The child:

- has an **empty environment**, except for what the platform needs to start (on Windows `SYSTEMROOT` and a
  few others) and the variables named with `--pass-env` / `pass_env`; a program that was granted `env` reads
  `nothing` for any other name;
- runs in **the caller's working directory**, so a relative grant (`--allow-read data`) means the same folder;
- has a **closed standard input**, unless the `stdin` capability is granted: then the caller's standard input
  (on the command line) or `input_text` (in `run_isolated`, with `stdin=True`) is passed through;
- is started with `python -I`, which ignores `PYTHON*` environment variables and the user's site folders;
- on **Linux** has an address-space limit of `memory_mb` MB (`RLIMIT_AS`, default 1024) and a CPU-time limit
  from the operating system; elsewhere those two are not applied (macOS does not enforce `RLIMIT_AS`, Windows
  has no equivalent in the standard library) and `[sbx.claims]` says so.

The parent kills the child when:

- it outlives `wall_ms` (by default the run's `time` limit plus two seconds; none for the `trusted` profile):
  `LimitError: time limit of <N> ms exceeded`;
- it writes more than `output_cap` bytes in all (by default twice the run's `output` limit plus 64 KiB):
  `LimitError: output limit of <N> bytes exceeded`;

and the child itself reports a `MemoryError` that reaches the top as
`LimitError: memory limit of <N> MB exceeded`. In every case the exit status is 1; what the child wrote before
being killed is kept, and how much of it arrives is not specified. A run that ends by itself gives exactly the
output, error and exit status it gives in-process: the runner changes where the program runs, not what it
means.

**What the runner is not.** It is not a container. The child runs as the same user, on the same file system
(inside the folders granted to it), with the same network, and a bug in CPython or in the operating system's
limits is outside the claims of `[sbx.claims]`. It narrows the damage of a bug in the in-process checks and
ends what the in-process checks cannot see. Code you did not write should still also run in a container.

Each row is a cell of the coverage matrix and needs a case on every engine:

| Cell | Kinds | What it pins |
| --- | --- | --- |
| `runner.time` | trip | a `regex` that never returns, and an endless loop of the `trusted` profile, are killed from outside |
| `runner.output` | trip | a flood is cut off at the cap |
| `runner.memory` | trip | a program that allocates past `memory_mb` ends with the memory error (Linux only) |
| `runner.env` | deny grant | the child's environment is empty, and `pass_env` hands a named variable over |
| `runner.same` | replay | a run that ends by itself gives the same output, error and exit status as in-process |

## [sbx.errors] The shape of the errors

1. A denied capability is `undefined name '<name>'` or one of the two fixed forms of
   `[sbx.capabilities]`; a denied path is the `FileError` of `[sbx.paths]`.
2. A limit is the error of its row in `[sbx.limits]`. The three fatal ones carry the label
   `LimitError`; the others keep the label the engine gives that operation today.
3. A failure of the host's machinery, a Python `MemoryError` or `RecursionError` or a C
   stack overflow, is never what a program sees (`[sec.error-boundary]`): it is turned into
   the error of the nearest row. A program that ends with a host traceback instead of one of
   these errors is a defect in the engine and its fix comes with a case.
4. The error's line is the line of the construct that went over, as `[err.model]` says. The
   fatal limits may be reported at the line the engine had reached, and the nesting error has no
   line (it ends the lexing or the parsing of the whole text).
5. Setting `profile` to `restricted` changes no error text of a program that stays within its
   grants and limits.

## [sbx.claims] What is and is not guaranteed

This is the only place that says what the profile guarantees. The README and the other
chapters quote it and may not say more.

**Guaranteed, on the bytecode VM, the tree-walker and the self-hosted interpreter, when
this chapter is implemented and every cell of the coverage matrix is covered:**

- a `restricted` program defines no name of a capability it was not granted, and reaches
  files, imports and environment variables only inside the grants;
- no program of the `restricted` profile writes more output, takes more steps or time, or builds
  a longer string, list or dictionary than the limits allow, and a fatal limit cannot be
  caught;
- every one of these is reported as a NovaLang error, not as a failure of the host.

**Not guaranteed:**

- isolation. The engine runs in the same process as the embedder, on a Python that is not a
  security boundary; a bug there, in the standard library or in CPython is out of scope;
- the total memory a program uses, the number of values it keeps alive, or the time `==`
  takes on structures that share parts of themselves;
- anything about a granted Python module, or a host function the embedder wrote;
- paths in folders another process can change while the program runs;
- side channels (timing, caches, error text shown to a user);
- the `trusted` profile, which has no limits.

**Words.** Until every cell of the coverage matrix is covered and an independent reviewer has
read the threat model, no NovaLang document may describe the `restricted` profile as a
sandbox guarantee, as safe, or as a security boundary. The allowed description is "capability
gating and resource limits". The state of the review is in the threat model.

**Added since:** the runner (`[sbx.runner]`) narrows two of the "not guaranteed" items below: a hang inside
a call the engine cannot interrupt is ended by the parent, and on Linux the address space of the child is
limited. It does not make the child a container.
