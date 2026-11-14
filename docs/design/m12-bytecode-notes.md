# M12 bytecode format: notes, decisions and the cache design

The format itself is specified in [`../spec/17-bytecode.md`](../spec/17-bytecode.md) (normative, with conformance cases). This file keeps what is not
specification: where the format's rules came from, the facts about the compiler and the VM that shaped it, the questions the owner answered, and the compiled-artifact **cache**
(slice 5), whose rules are now in the specification. It was the draft of that chapter until
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

## The cache, as built (slice 5)

The rules are `[bc.cache]` of [chapter 17](../spec/17-bytecode.md). What is not specification:

* The cache is `ArtifactCache` in `novalang.py`, reached from `run()` through `interpreter.artifact_cache`; `run_source` sets it for a command-line program and a module
  import uses the same interpreter. `cache_for_run()` makes the decisions of "When it is on". `NOVALANG_CACHE_DEBUG=1` prints one line per decision to standard error
  (`novalang cache: hit|miss|rejected|stored <12 digits of the key>`); the tests read it.
* **Nothing evicts** (Q6, decided): the directory grows with the number of distinct sources run. A size cap and eviction are a candidate for M13.
* **The test suite and the benchmarks turn the cache off** (`NOVALANG_CACHE=off` in `tests/run_all.py` and in `tests/benchmarks/run.py`) so they neither fill a user's directory nor
  change a baseline; `tests/bytecode/test_cache.py` and the conformance cases name a directory of their own.
* **Threat T17** (a poisoned cache) is a row of the [M11 threat model](m11-threat-model.md).

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
3. The chapter moved to `docs/spec/17-bytecode.md` on 2026-11-14. **`[bc.cache]` stayed here** until slice 5 built the cache: a case is a program and its result, and a cache is a directory
   the host reads and writes, so no case could cite it before. Slice 5 built it, added the `cache` fields to the `bytecode` profile (17 cases), and moved the section into the chapter.
