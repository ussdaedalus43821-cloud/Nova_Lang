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
resolved against the working directory.

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

## [host.time] The clock

- `time()` is the seconds since 1970-01-01 00:00:00 UTC as a float. Two calls never
  go backwards unless the system clock was set back.
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
