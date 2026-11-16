# Using NovaLang bytecode files

**Status** — Developer guide for the bytecode artifact and its cache, which shipped in v2.3.0 (M12). Checked against `develop` at `34a6256`. The rules come from the specification, [`spec/17-bytecode.md`](spec/17-bytecode.md) (`[bc.cache]`, `[bc.provenance]`); where this guide and the specification disagree, the specification wins. The artifact format is **not** a stable interface: any minor release may change it, and the only promise is that an artifact is accepted or cleanly rejected, never misread. **If you change a command or a cache rule, update this guide in the same pull request.**

## Compile and run a `.novac` file

From the NovaLang checkout, compile a source file to an explicit output path, then run that artifact directly.

```sh
python3 novalang.py --compile program.nova -o program.novac
python3 novalang.py program.novac
```

`--compile` writes the artifact and runs nothing. An artifact is self-contained: it carries the source text it was compiled from, so it runs without the original `.nova` file. Still keep the source, so you can rebuild after editing the program or upgrading NovaLang; re-run `--compile` whenever you want the standalone file to reflect an edit.

Before running, the loader checks the format version and the opcode-set hash and verifies the bytecode. An artifact made by a different NovaLang version is refused with an error that names the compiler that made it. Development builds write format version 0.

To confirm that an artifact really is the compilation of the source it carries:

```sh
python3 novalang.py --check-artifact program.novac
```

It recompiles the embedded source and compares the bytes (compilation is deterministic). A plain run does not do this, because it costs a compile.

An artifact is a cache of a compilation, **not a security boundary and not an authenticity check**: its checksum catches accidents, not tampering. It runs under the same profile, limits and grants as its source would.

To look at the bytecode without writing a file: `python3 novalang.py --dis program.nova`.

## Use the automatic cache

Run the source file and let NovaLang manage the cache. With the cache on, the first run compiles the source and stores the result; later runs of the same source reuse it. Each imported module is cached separately, keyed on its own source.

```sh
python3 novalang.py program.nova                              # uses the cache
python3 novalang.py --no-cache program.nova                   # bypass it for one run
python3 novalang.py --cache-dir ./private-cache program.nova  # use a directory you name
```

**When it is on**

- On by default for `trusted` runs.
- Off for `restricted` runs unless a cache directory is named with `--cache-dir`: a restricted program must not choose where anything is written.
- Off with `--no-cache`, or with `NOVALANG_CACHE` set to `off`, `0`, `false` or `no` in the environment. These win over everything else.
- **Off on Windows**, whatever directory is named (NovaLang says so once, on standard error), until it can verify who owns a directory there.
- Only on the bytecode VM, the default engine; never with `--tree-walk` or the self-hosted interpreter.
- Never used for a program read from standard input, the REPL, code given on the command line, a program too large for the artifact limits (it runs from source instead), or a program the type checker refuses.

**Where it lives**

- `$XDG_CACHE_HOME/novalang` when `XDG_CACHE_HOME` is set to an absolute path.
- Otherwise `~/Library/Caches/novalang` on macOS, and `~/.cache/novalang` on Linux and other POSIX systems.
- Or the directory you name with `--cache-dir`.

NovaLang creates the directory with mode `0700` if it is missing. It refuses a directory that is a symbolic link, is not owned by you, or is writable by group or others; the program then simply runs without the cache.

**What a cache hit saves.** Lexing, parsing and compiling, and nothing else. The type check still runs when the source has annotations or imports, the profile still gates names, step limits count the same steps, and an error points at the same line.

## Troubleshoot

| Symptom | What to do |
| --- | --- |
| You changed the main file or an imported module | Run the `.nova` entry point again. The edited file's source changes its key, so its old entry is not used. If you launch a standalone `.novac`, rebuild it from the edited source first. |
| The first run after an upgrade is slower | Expected. A new compiler version, format version or opcode set changes every key, so each program recompiles once. |
| An automatic cache entry is corrupt, truncated or for the wrong source | Nothing to do. Any entry that fails the checks is ignored, the program runs from source, and the entry is replaced when the directory is writable. A cache never makes a program fail. |
| A standalone `.novac` is refused | Read the loader's error: it names the problem and the compiler that made the file. Rebuild from source with the NovaLang version that will run it, or run the `.nova` file. |
| The cache never warms up | Check for `--no-cache`, `NOVALANG_CACHE=off`, a `restricted` run without `--cache-dir`, Windows, or `--tree-walk`. Check the directory too: it must be yours and not writable by others. A read-only directory stops new entries from being saved, but the program still runs. Set `NOVALANG_CACHE_DEBUG=1` to print each cache decision (hit, miss, rejected, stored) to standard error. |
| You want to know whether the cache affects a failure | Run the same source and arguments with `--no-cache` and compare output and errors. To test a fresh cache, run twice with `--cache-dir` pointing to a new private directory. |
| The cache directory keeps growing | There is no command to clear it in this version, and nothing removes entries: it grows with the number of different sources you run. You can delete the directory by hand; it is recreated on the next run. |

**The cache key** is the SHA-256 of four parts: the bytecode format version, the opcode-set hash, the compiler version and the source text. Changing the profile, the limits, the file's path or the working directory does not change the key, because compiled code does not depend on them. The layout of the cache directory and the debug output are not stable and may change in any minor release.
