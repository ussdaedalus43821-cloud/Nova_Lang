# M12 bytecode format: notes, decisions and the cache design

The format itself is specified in [`../spec/17-bytecode.md`](../spec/17-bytecode.md) (normative, with conformance cases). This file keeps what is not
specification: where the format's rules came from, the facts about the compiler and the VM that shaped it, the questions the owner answered, and the rules for
the compiled-artifact **cache** (slice 5), which join the specification with their cases when the cache is built. It was the draft of that chapter until
2026-11-14; its history is the history of this file.

**Where the content comes from, so you can tell what to trust:**

* **Decided on 2026-11-14 (D1 to D7 of the [plan](m12-runtime-plan.md)):** a purpose-built, versioned, length-prefixed binary, not `pickle` or `marshal` (D1,
  corrected: no list or dictionary constants); a format version, an opcode-set hash and the compiler version in the header, reject with a named error and recompile
  (D2); the format is not part of the M13 stable API (D3); the cache location and who may write it, off by default in `restricted` (D4); no shared format with the
  GDScript port (D5).
* **Approved on 2026-11-11 for the earlier draft of the chapter (recorded in the register; that draft is not on this computer):** a trailing checksum; no list or
  dictionary constants; names inline and integers fixed-width `u32`; an `InternalError` containment rule; the limit values; the compiler-version information. The
  chapter re-derives them from the owner's list, not from the lost draft.
* **Decided by the owner on 2026-11-14 (the nine questions below):** all as recommended; Q2 (embed the source) and Q5 (no cache on Windows by default) were the owner's own.
* **Found by reading the compiler and the VM:** the findings below.

## [bc.cache] The compiled-artifact cache (slice 5; joins chapter 17 with its cases)

* **Key.** SHA-256 over: the format version, the opcode-set hash, the compiler version string, and the source text (as UTF-8), each preceded by its length
  as a `u32`. Not the profile, not the limits, not the working directory, not the path of the file (M11: code is profile-independent). The file is
  named `<key as 64 hex digits>.novac`.
* **Where (D4).** A per-user cache directory: `$XDG_CACHE_HOME/novalang` when set, else `~/.cache/novalang` on Linux; `~/Library/Caches/novalang` on macOS;
  `%LOCALAPPDATA%\novalang\cache` on Windows. `--cache-dir DIR` and `NOVALANG_CACHE=off` override. (The exact subdirectory was left open in the draft
  guide; this is the proposal.)
* **Who may write it.** The directory is created with mode 0700 and files with 0600. A loader **refuses to use** a directory that is not owned by the current
  user or is writable by group or others (checked with `lstat`, not through a link), and never follows a symbolic link for the file.
  **On Windows the cache is off by default** (the owner's answer to Q5) and stays off until directory ownership and ACLs can be verified reliably, in a later milestone;
  this draft reads that as off **even with `--cache-dir`**, and the owner may say if an explicit `--cache-dir` should be allowed as an opt-in.
* **Reading.** The size is checked against the *artifact* limit before reading; then the full `[bc.reject]` checks, with the source given, so the embedded source
  must be identical to the source being run. **Any rejection means: ignore the file, compile from the source, and replace the entry when the directory is writable.**
  A cache problem never fails the program.
* **Writing.** To a temporary file in the same directory (created exclusively), then an atomic replace. A read-only directory or a full disk is ignored.
  Concurrent runs may both write the same key; they write the same bytes (`[bc.determinism]`).
* **Defaults.** On for `trusted` command-line runs; **off in `restricted`** unless the embedder passes a cache directory (a restricted program must not choose where
  it is written); off for programs read from standard input and for the REPL. `--no-cache` and `NOVALANG_CACHE=off` always win.
* **Never cached:** standard input, the REPL, and a program whose code objects exceed a limit.
* **Size:** an entry holds the source as well as the code (about the size of the source again, plus the code); it is the same format as a standalone artifact.
* **What it saves:** lexing, parsing and compiling, **not execution** (D4's caveat, measured: 0.1% to 5% of the proof-of-concept programs' run time;
  7% of Nova_Stats' because it loads 21 modules). A warm start of a module-heavy program is the exit measure.
* **Growth:** nothing removes an entry (no cache-clear command in M12). `[bc.questions]` Q6.
* **Threat T17, a poisoned cache** (to be added to the M11 threat model with slice 5): a file another account can write is a way to inject code, which the
  directory rule prevents; a file that gets through anyway can do what a program can do under the loader's profile, no more, because of `[bc.verify]` and
  `[bc.constants]`; the cache stays an input the embedder keeps private.

## [bc.findings] Facts about the current implementation that shape this chapter

1. **F1. The compiler's pool holds Python objects the format cannot store as constants:** tuples and lists (`BUILD_DICT` keys, `NEW_CELLS` and `RESET_SLOTS` slots, a
   `LOAD_CHAIN` chain, the `(side, operator)` of `CHECK_BOOL`, the `(message, label)` of `FAIL`, the `(name, path)` of `IMPORT_NAME`), strings used as flags (the
   `if`/`while` of `JUMP_IF_NOT_TRUE`, the loop roles, the stray keyword), and **`BuiltinFunction` objects**. The format therefore encodes these as arguments
   (`[bc.ops]`) and as tag 6, and the loader rebuilds the in-memory pool; the in-memory representation does not change.
2. **F2. Ungated built-ins are constants.** `print`, `len` and every built-in not in `CAPABILITY_OF` compile to `LOAD_CONST` of the function object, not to a lookup
   (`e_VarNode`). A file cannot hold the object, so it holds a name (tag 6), and V13 is what stops a name from reaching a gated function. This is a new
   security-relevant rule: without V13 an artifact could carry `read` into an engine with no `files.read` grant.
3. **F3. A very long float literal compiles to infinity.** `1` followed by 400 zeros and `.0` is a valid float constant equal to `inf`. The format accepts
   positive infinity so every compiled program can be written; whether the lexer should accept such a literal is a separate question for the language
   (`[bc.questions]` Q3). A NaN cannot be written by any source and is rejected.
4. **F4. `verify()` does not check what the VM trusts.** It does not check that a pool index exists or has the right type, that the slots inside a chain, a `NEW_CELLS`
   list or a loop state exist, that a `free` index is within the closure, that a closure entry is within the parent, or that `ITER_NEXT`'s slot was prepared. The VM
   indexes with these values directly, so a bad value is an `IndexError` or a `TypeError`, which the VM's own handler turns into a Python traceback.
   V2, V3, V5, V8, V9 and V10 close that. They should also run on compiled code in the test suite, so the compiler cannot regress.
5. **F5. Nesting depth leans on the host's recursion limit.** `novalang.py` sets `sys.setrecursionlimit(20000)` and relies on `RecursionError` for "recursion too
   deep". On PyPy 3.10 that setting crashes the interpreter with a segmentation fault on a long enough chain, and at 10,000 the same program runs instead of
   being refused (measured, [`docs/benchmarks.md`](../benchmarks.md)). The loader must therefore count depth itself (V1, `[bc.limits]` *depth*), and the same
   explicit counter should be added to the parser, the compiler and the tree-walker (a proposed addition to slice 6 or 8).
6. **F6. Positions are offsets into the source, and an error prints the offending line from the source text.** Hence the owner's decision to embed the source (Q2).

## [bc.questions] Decisions of the owner

All nine questions were answered on 2026-11-14 ("accept all" for the recommendations); nothing is open.

| # | Question | Decision |
| ---: | --- | --- |
| Q1 | The limits of `[bc.limits]` | accepted as proposed |
| Q2 | A standalone `.novac` | **embeds the source text and is self-contained** (`[bc.header]`, `[bc.profile]`, `[bc.provenance]`) |
| Q3 | The float literal that is infinity | the format accepts +infinity; logged as G-052 ([`docs/GAPS.md`](../GAPS.md)); the lexer is decided with the number work in M13 |
| Q4 | Is `InternalError` language-visible? | no: `catch` cannot see it; the program ends with `InternalError: <text>` on standard error, no traceback, **exit status 70** |
| Q5 | Windows | **the cache is off by default**, until ownership and ACLs can be verified (`[bc.cache]`) |
| Q6 | Cache growth | no eviction in M12; stated in the cache's documentation; revisit in M13 |
| Q7 | The format version number | **development builds write 0**, the first release writes 1, and a release rejects 0 (a loader accepts only its own version, `[bc.header]`) |
| Q8 | Compression of the embedded source | **none** in format 1: stored raw, so bytes are reproducible and no decompression limit is needed |
| Q9 | `novalang.py --check-artifact FILE` | **yes**: recompile the embedded source and compare the bytes (`[bc.provenance]`) |

## How this became chapter 17

1. Slice 4 built `dump_artifact` and `load_artifact`, the test that regenerates the table (`tests/compiler/test_bytecode_draft.py`), and the fixtures
   `tests/bytecode/fixtures/v1/` (19 golden artifacts that together contain every opcode, the output each printed, and 16 damaged files with the name of the error each
   must give; "v1" names this format generation, whose development-build version number is 0).
2. The conformance harness gained the `bytecode` profile (`tests/conformance/`), and `cases/bytecode.json` cites every section of the chapter.
3. The chapter moved to `docs/spec/17-bytecode.md` on 2026-11-14. **`[bc.cache]` stayed here:** a case is a program and its result, and a cache is a directory the host
   reads and writes, so no case could cite it before slice 5 builds it. When it does, the section moves to the chapter and the cases that pin it are added, as the rule of
   the conformance station requires.
