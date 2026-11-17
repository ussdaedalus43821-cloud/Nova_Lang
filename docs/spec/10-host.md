# 10. The host library

The functions that reach outside the program: files, the clock, randomness, the
environment and the process. They are the `host` profile (`README.md`). A program
that uses none of them is a `core` program and is deterministic (`[port.order]`);
one that does depends on the machine it runs on, and this chapter says exactly how
far: what is the same on every host, and what each host decides. Calls and errors
follow `[lib.calls]`; every name here is reserved (`[scope.reserved]`).

## [host.files] Files and folders

A path is a string in the host's own syntax; the chapter's examples use relative
paths made of ASCII letters, digits, `.`, `_` and `/` (which every host accepts),
resolved against the working directory. Whether two names that differ only in case
(`a.txt`, `A.txt`) are one file is the host's: Windows and macOS usually say yes.

- `read(path)` is the text of a file, decoded as UTF-8, with every `\r\n` and every
  lone `\r` turned into `\n`. `write(path, text)` replaces the file's contents with the
  UTF-8 bytes of `text`, creating it if needed, **exactly as given**: a `\n` is one
  byte on every platform. `append(path, text)` adds to the end of the file, creating
  it if needed (the same function as `append(list, value)`, told apart by its first
  argument, `[lib.collections]`). `write` and `append` need a string for the text
  (`the text for write() needs a string, but got a number`; the text for `append`
  is `the text appended to a file`).
- `exists(path)` is `true` for a file or a folder and `false` otherwise. It never
  fails except for a path that is not a string.
- `listdir(path)` is the names in a folder, **sorted by code point**, without `.` and
  `..`. `mkdir(path)` makes a folder and any missing folders above it, and is not an
  error if it already exists.
- `remove(path)` removes a file, or an **empty** folder. `delete(path)` removes a file
  and is not an error if there is none (deleting twice is fine); given a folder it is
  `FileError: <path> is a directory - delete() only removes files`.
- `rename(old, new)` renames a file or folder; `copy(src, dst)` copies a file's
  contents and metadata. Renaming onto an existing file is host-defined.
- `realpath(path)` is `abspath(path)` with every symbolic link in it followed: the path the
  operating system would really open. A part that does not exist is kept as written (after the
  parts that do exist were resolved), so `realpath` of a name that is not there is still a path.
  The sandbox checks a program's paths against its grants with it (`16-sandbox.md`
  `[sbx.paths]`).
- `cwd()` is the working directory as a string. `abspath(path)` is the absolute,
  normalized form of a path and `dirname(path)` is everything before its last
  separator (`""` if none). Both are helpers for tools such as the module resolver
  and give host-syntax paths.

Errors. A file or folder that is not there is `FileNotFoundError: <path>` (the label
and the path as written, nothing else). The other failures are `FileError`:

| Call | Message |
| --- | --- |
| `read`, `write` or `append` on a folder | `FileError: <path> is a directory, not a file` |
| `listdir` on a file | `FileError: <path> is a file, not a directory` |
| `delete` on a folder | `FileError: <path> is a directory - delete() only removes files` |
| `read` of bytes that are not UTF-8 | `FileError: <path>: <the host's reason>` |
| `mkdir`, `remove`, `rename`, `copy` that fail | `FileError: <function>(): ...` followed by the operating system's own words |

Only the part before the operating system's words is specified: `remove` of a
folder that is not empty is `FileError: remove(): ` and then the system's text,
which differs between platforms. A path argument that is not a string is `read()
needs a string, but got a number` (`the file name for write()`, `the old name for
rename()`, `the source for copy()`, `delete() needs a file name, but got a number`).

A path with a null character in it is not a path any file function can use: `exists` is `false` and every other file function, and the `delete` statement, fails with `FileError: <path>: the path contains a null character` (the character shown as `\0`), never with the host's own report.

## [host.time] The clock

- `time()` is the seconds since 1970-01-01 00:00:00 UTC as a float. Two calls never
  go backwards unless the system clock was set back.
- `monotonic()` is a float, in seconds, from a clock that never goes backwards and starts at an
  arbitrary moment: only the difference of two calls means anything. Use it, not `time()`, to measure how long
  something took, because `time()` follows the system clock and a clock that is set back makes it jump.
- `now()` is the current UTC time as an ISO 8601 string,
  `2026-11-08T05:00:00.123456+00:00`; the fraction `.dddddd` is left out when it is
  zero, so the length varies.
- `sleep(ms)` pauses for at least `ms` milliseconds and returns `nothing`. `ms` MUST
  be a finite number that is not negative (`TypeError: sleep() cannot pause for a
  negative time`, `[port.floats]`).
- `format_time(t, format)` writes the timestamp `t` (as `time()` gives) in the
  host's **local time zone**, following the directives of C's `strftime`. The
  directives every host MUST support are `%Y` (year), `%m`, `%d`, `%H`, `%M`, `%S`
  (two digits each), `%j` (day of the year, three digits), `%y` and `%%` (a percent
  sign); text without a `%` is copied. Names of days and months, `%p`, `%c` and the
  rest depend on the host and its locale. A `t` that is not a number is `TypeError:
  format_time() needs a number, but got a string`, a format that is not a string
  is `the format for format_time() needs a string, but got a number`, and a time the
  host cannot represent is `TypeError: format_time(): ...`.

## [host.random] Randomness

Random values come from a generator the host chooses and seeds; two runs differ,
and the language offers no way to seed or repeat one.

- `random()` is a float with `0 <= r < 1`.
- `randint(a, b)` is a whole number with `a <= n <= b`, **both ends included**, each
  equally likely. `a` and `b` MUST be whole numbers (`randint() needs a whole number,
  but got 1.5`) and `a` MUST NOT exceed `b` (`TypeError: randint() needs its first
  argument no greater than its second`).
- `choice(list)` is one item of the list, each equally likely (`TypeError: choice()
  needs a list, but got a number`; `choice() cannot pick from an empty list`).
- `shuffle(list)` puts the items of the list itself in a random order, in place, and
  returns that same list (`TypeError: shuffle() needs a list, but got a string`).

## [host.process] The environment and the process

- `env(name)` is the value of an environment variable as a string, or `nothing` if
  it is not set (`env() needs a string, but got a number`).
- `args()` is a new list of the strings given to the program after its file name
  on the command line, or `[]` when there are none.
- `platform()` is a non-empty string naming the operating system. The reference host
  gives `"Linux"`, `"Darwin"` or `"Windows"`; other values are the host's own.
- `print` writes to standard output, as in `[val.display]`. `log(x, ...)` writes the
  values, separated by spaces like `print`, to **standard error** after an
  ISO 8601 UTC timestamp in square brackets, and returns `nothing`; it never writes
  to standard output.
- `input()` and `input(prompt)` write the prompt (if any) to standard output without
  a line end, read one line from standard input and return it without its line end
  (`print(input())` with an empty line gives an empty string; a last line with no
  line end is returned as it is). When there is nothing more to read it is `input()
  found no more input to read` (a prompt already written stays written). The prompt
  MUST be a string (`input() needs a string, but got a number`) and `input` takes at
  most one argument (`input() takes an optional prompt and nothing else`).
- `exit()` and `exit(code)` end the program at once with that status (0 when none).
  `code` MUST be a whole number (`exit() needs a whole number, but got a string`)
  and the statuses 0 to 255 are portable. Output already printed stays printed;
  nothing after the call runs, a `catch` does not see it, and `finally` blocks of
  the `try` statements it leaves **do** run first (`[err.finally]`). `exit` takes at
  most one argument (`exit() takes an optional status code and nothing else`).

## [host.warnings] Deprecation warnings

A function that [`DEPRECATIONS.md`](DEPRECATIONS.md) lists is **deprecated**: it still works, and a call of it says so. This section is
what the call does; the rules for how long the function stays are in [`STABLE.md`](STABLE.md).

1. **The warning.** The first time a given **call site** runs, in a run, the engine writes one line to **standard error**:

       warning: NAME() is deprecated since SINCE; use REPLACEMENT (removal not before REMOVAL) (line N)

   `NAME`, `SINCE`, `REPLACEMENT` and `REMOVAL` are the four columns of the list. `N` is the 1-based line of the call in the file being run (the main
   program, or the module while it loads), counted as an error's line is; a call made from inside a function that was defined in another file is
   given the line of the main program, as an error there is. A call site is one place in the source: a call in a loop, or in a function called many
   times, warns once. **Standard output and the exit status are not changed by a warning.**
2. **`--warnings=MODE`** (also `--warnings MODE`) chooses what a call does: `warn` (the default: point 1), `off` (nothing is written), or `error`
   (the run ends at the first call, every time, with `DeprecationError: ` and the text of the warning without its `warning: ` prefix, exit status 1).
   A `DeprecationError` is **not catchable**: no `try` of the program sees it and no `finally` block runs, as with a fatal limit
   ([`[sbx.limits]`](16-sandbox.md)). Any other value is a usage error, exit status 2.
3. **The deterministic mode** ([`[sbx.determinism]`](16-sandbox.md)) writes no warning to standard error; the warnings are kept (by the embedding API,
   [`[emb.warnings]`](11-embedding.md)).
4. **What this covers.** A call of a deprecated **built-in function**. Deprecated standard-module exports, capabilities, manifest fields and
   flags, and the `deprecated` mark on a package version in a registry index, warn the same way when they are built (open gap G-056).
5. **The three engines agree**: the same lines, with the same line numbers, and the same `DeprecationError`.

## [host.probe] The test hook of the deprecation mechanism

Nothing is deprecated, so nothing could exercise [`[host.warnings]`](10-host.md). A function named `_deprecated_probe` exists only to do that:
it takes no argument, returns nothing, and is listed as deprecated since 2.4, replaced by nothing, removable from 3.0. It is **not** in
`DEPRECATIONS.md`, because it is not part of the language.

1. **A program cannot reach it.** The function is not a built-in. An engine defines it in a program's global scope only when its **host** asked for
   it by name: `Nova(_deprecation_probe=True)` for the embedding API, `--_deprecation-probe` on the command line. Without the request the name
   is undefined, exactly like any other name the program never wrote: `NovaError: undefined name '_deprecated_probe'`.
2. **The restricted profile refuses the request.** `Nova(profile="restricted", _deprecation_probe=True)` and `--profile restricted --_deprecation-probe`
   both fail before any program runs (a sandbox error, and exit status 2). No grant, setting or limit of a restricted engine makes the name visible.
3. A program cannot make the request itself: it is a setting of the engine, made by whoever starts it, and no function of the language changes
   the settings of the engine it runs on. (A program that starts a second NovaLang process needs the `process` capability, and what that process
   does is a run of its own.)
