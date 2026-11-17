# GAPS.md - gaps found in NovaLang itself, outside the proof-of-concept apps

The proof-of-concept apps keep their own logs: Nova_Stats G-001 to G-026, Nova_Sort G-027 to G-035, Nova_Log G-036 to G-042 and
Nova_Data G-043 to G-050 (see [`ROADMAP.md`](ROADMAP.md), M13, "Requirements from the Proof-of-Concept Apps"). This file continues the same numbering
for gaps found any other way, here in M12 work, so the ecosystem keeps one list. The next free number is **G-057**.

**How to read an entry.** *Tried* is what was done and the exact result. *Why it matters* says what promise it touches. *Fix* says where it is planned.
*Probe* is a check in `tests/` that passes while the gap exists and fails the day it is fixed, as in the proof-of-concept repositories.

**Severity:** LIMIT - BLOCKER - FRICTION - TRAP - minor. A **PORTABILITY** gap is one that appears only on a host the project does not yet support.

| # | Gap | Severity | Planned |
| --- | --- | --- | --- |
| G-056 | The deprecation mechanism warns only for a call of a deprecated **built-in function**. A deprecated `std:` export, a capability, a manifest field or a flag does not warn yet at import, install or startup, and a package version cannot carry a `deprecated` message in the registry index that `install` prints (M13 plan, 6.3, points 2 and 5). Nothing is deprecated, so nothing is owed today | FRICTION | **Open**, to be built with the first real deprecation; not scheduled |
| G-055 | `nova-pkg audit` does not report a package whose minor release **removed an export** that the previous version had (M13 plan 6.2: "a compare of exports, from the static scan"). Not built in M14 L6 item 2: it needs choices the plans leave open, and it makes `audit` download and unpack versions you never installed | FRICTION | **Open**, owner to decide the choices in the entry below; not scheduled |
| G-054 | **TOCTOU in the `restricted` path gate:** `check_path` resolves a path's symbolic links and approves it, then the file is opened from the *same path string* in a later syscall, following links again. An attacker who controls a granted directory can swap a symbolic link between the two steps and have the sandbox open a file outside the grant | **Part A fixed; parent-component race open (Phase 6)** | **Final-component swap closed 2026-11-15** (M14): every restricted file open uses `O_NOFOLLOW` (Windows: open-then-verify by handle), so a terminal symbolic link is refused — the measured read/write exploit rates drop to 0 (`[sbx.toctou]`, threat model N5). A parent directory swapped for a link is **not** closed and is deferred to Phase 6. Surfaced 2026-11-14 |
| G-053 | The text readers carry a NUL byte through as an ordinary field/line character instead of refusing it (a NUL means the bytes are not text: a truncated binary or the wrong encoding) | TRAP | `std:csv` **closed 2.4.0** (M14, this entry); `read()` deferred — refusing a NUL where it is accepted is a MAJOR change to a stable builtin |
| G-052 | A float literal too large for a binary64 is silently infinity (a 400-digit `1000...0.0`), and `inf - inf` of two of them is `nan` | TRAP (minor) | M13, with the number work: **decided 2026-11-14 (slice 2): keep and document** (`[lib.std-format]`); the lexer is not changed |
| G-051 | On PyPy a deeply nested program crashes the interpreter (segmentation fault) instead of getting the named nesting error; the nesting limit depends on the host's `RecursionError` | PORTABILITY, and a TRAP: the same setting crashes at 20,000 and silently runs at 10,000 | **Closed 2026-11-17** (M14 L6, item 4): the parser counts the nesting (1000 brackets and blocks, a tree 5000 deep), the same on every host; PyPy gets the named error; `[port.limits]`, D-048 |
| G-017 | `import` (and a type annotation) needs files beside `novalang.py` that nothing documented, and a lone `novalang.py` ended in a Python `FileNotFoundError` traceback (first logged in the Nova_Log/Nova_Data proof-of-concept apps, carried by the M13 plan, appendix A) | FRICTION | **Closed 2026-11-16** (M14 L6, item 1): the program ends with an `ImportError` that names the missing files and what to copy; README and `[emb.model]` list what an installation contains. Measured: three Python files for the type check (`tools/nova-typecheck.py`, `nova_ast.py`, `nova_scope.py`), plus `lib/std/` for `std:` imports |
| G-015 | An embedded program could not be given its `args()`; `args()` read a module-wide global shared by every engine in the process (M13 plan, appendix A) | FRICTION | **Closed 2026-11-16** (M14 L6, item 1): `Nova(args=[...])`, per engine, `[emb.args]` |

## G-056 The deprecation warning covers built-in functions only - FRICTION
- **Found:** 2026-11-17, building the deprecation mechanism (M14 L6, item 3).
- **What exists:** the warning for a call of a built-in function listed in `docs/spec/DEPRECATIONS.md`, `--warnings=warn|error|off`, the embedding `warning` callback and
  `Nova.warning_log`, on all three engines ([`[host.warnings]`](spec/10-host.md)).
- **What does not:** the M13 plan (6.3) also says a deprecated *capability*, *manifest field* or *flag* warns "at install or startup", a deprecated `std:` export warns when it is
  called, and a package may mark a version `deprecated` in the registry index with a message that `install` prints. None of these has anything to warn about today, and each needs a
  decision of its own (for example, whether a warning at install is once per package or once per run).
- **Also open, and smaller:** the line of a warning for a call inside a function that was defined in an imported file and called later is the line in the main program, as an
  error's line is; a call made when a host calls a function (`Nova.call`) has no line.
- **Fix:** build each when the first real item is deprecated, with the same flags and the same `DeprecationError`.

## G-055 `audit` cannot report a minor release that removed an export - FRICTION
- **Found:** 2026-11-16, building `nova-pkg audit` (M14 L6, item 2). The M13 plan, 6.2, says `audit` "reports a package whose minor release **removed** an export that the
  previous one had (a compare of exports, from the static scan)". The rest of 6.2 and 6.3 is built; this part is not.
- **Why it was not built in that pull request.** Two reasons, both are the owner's to decide and neither is settled by the plans:
  1. **Choices the plans leave open.** (a) What is "an export" of a package: the exports of its entry file (`main`) only, or of every `.nova` file a program can import by path
     (`import "pkg/file.nova"`). (b) Which two versions are compared: the locked one and the one before it, every consecutive pair in the registry, or the locked one and the newest in range.
     (c) Versions below 1.0.0, where a minor release is allowed to break by the caret rule: whether they are compared at all. (d) Whether a yanked version can be the baseline.
     (e) Whether finding one is a problem (exit status 1) or only a report. The plan says "reports"; the other findings in `audit` that are reports do not change the exit status.
  2. **A new cost and trust surface.** `audit` today reads the registry's signed index and the installed copy. Comparing exports needs the archive of a version that is not installed,
     fetched, checked against its recorded hash and the revocation list, and unpacked into a scratch folder, which is code `audit` has never run on files you did not choose to install.
- **What exists to build it on:** `scan_package` already parses every `.nova` file of a package into its syntax tree, and an export is an `ExportNode` wrapping a function or a `let`; the
  registry client already fetches and verifies archives for `install`.
- **Fix:** decide (a) to (e), then build it as a finding of `audit` with a test per choice. Until then `audit` does not say whether an export disappeared; the `std:` modules are
  covered by the stable-surface test, which does fail on a removed export.

## G-051 The nesting limit depends on the host's recursion limit, and PyPy breaks it - PORTABILITY
- **Found:** 2026-11-14, running NovaLang's own test suite on PyPy 3.10.16 to see whether the 9x to 14x speedup of the benchmark suite
  ([`benchmarks.md`](benchmarks.md), "D7, first measurement") could be a supported engine.
- **Tried:** a program that is one long chain, `print(true and true and ... and true)` with 20,000 operands.
  - **CPython 3.9.6:** `NovaError: the interpreter ran out of stack - recursion too deep`, exit status 1. This is the behaviour the specification
    asks for ([`spec/06-portability.md`](spec/06-portability.md) `[port.limits]`, [`spec/05-security.md`](spec/05-security.md)).
  - **PyPy 3.10.16, as it ships:** the interpreter is killed by a **segmentation fault** (exit status 139), under `trusted` and under `restricted`, with no
    output. It aborts the sandbox unit tests at the first such case and the conformance run (`sbx-limit-nesting`, `esc-parser-nesting-*`).
  - **PyPy with the recursion limit capped at 10,000** (a `sitecustomize` hook outside the repository; `novalang.py` unchanged): the crash is gone, all 256
    sandbox unit tests pass, and the conformance corpus fails **2 cases**, in which PyPy neither raises the nesting error nor crashes: the program runs and prints its result.
- **Why it matters:** `novalang.py` does `sys.setrecursionlimit(20000)` and turns the host's `RecursionError` into NovaLang's nesting error. That means the
  limit is *whatever the host's recursion limit means*: on CPython it is a frame count the C stack can hold; on PyPy the same number either overruns the C
  stack or is not counted the way the corpus expects. A language limit that a host can silently change into a crash, or into no limit at all, is not a limit.
  It does not break the supported configurations (CPython 3.7 to 3.13); it is why **PyPy is a measurement and not a supported engine**, and why the
  `restricted` profile must not be offered on it (M12 plan, slice 8: a new engine may not carry the name until the 201-cell matrix passes on it).
- **Workaround:** none in the program. Do not run NovaLang on PyPy.
- **Closed 2026-11-17 (M14 L6, item 4).** The nesting is counted by the parser and not by the host: 1000 brackets, braces and blocks open at once
  and a syntax tree 5000 deep (a chain of operators, of `not`, of `else if`, of `x[0][0]`), each refused with the same error before anything runs
  (`novalang.py`: `NESTING_LIMIT`, `TREE_DEPTH_LIMIT`, `check_tree_depth`, which the compiler and the tree-walker also call; the artifact loader already counted, V1).
  On PyPy, and on Windows with Python before 3.11 (found by the Windows 3.7 row of CI: the main thread's 1 MB stack overflows at the new limits), the interpreter runs a program in a thread with a large stack (`run_with_room`; an embedding host on those hosts has to do the same), and `tests/portability/test_pypy_nesting.py` is now the check that the
  crash is gone and the limits are the same on PyPy 3.10.16 and on CPython, in the trusted and the restricted profile. The self-hosted interpreter stays at 100 ([`D-048`](spec/DIVERGENCES.md)).
  The limits **narrow** what ran before (CPython took about 2000 parentheses, 5000 blocks and 10,000 operands): declared in [`STABLE.md`](spec/STABLE.md).
  PyPy is still a measurement and not a supported engine: the whole suite was not run on it.
- **The fix as it was planned (decided 2026-11-14: slice 6 or earlier):** make the nesting depth **explicit**: a counter in the parser, the compiler and the tree-walker (and the
  loader of the bytecode chapter, [`spec/17-bytecode.md`](spec/17-bytecode.md) V1), with a stated maximum and the same
  error text, independent of the host's recursion limit; then raise `sys.setrecursionlimit` only as far as that maximum needs, and re-run the two failing conformance cases and the
  suite on PyPy. The explicit limit is worth having on CPython too: it is the same on every host, as the portability chapter wants.
- **Probe:** [`tests/portability/test_pypy_nesting.py`](../tests/portability/test_pypy_nesting.py) (`test_G051_*`). It needs a PyPy interpreter, which CI does not have, so it is skipped
  unless `NOVA_PYPY` names one: `NOVA_PYPY=$(uv python find pypy@3.10) python3 -m unittest tests.portability.test_pypy_nesting -v`. It passes while PyPy crashes and fails the day it gives the named
  error.

## G-052 A float literal that overflows is silently infinity - TRAP (minor)
- **Found:** 2026-11-14, writing the constants section of the bytecode specification ([`spec/17-bytecode.md`](spec/17-bytecode.md) `[bc.constants]`, finding F3 of [`design/m12-bytecode-notes.md`](design/m12-bytecode-notes.md)):
  a constant pool can hold `inf`, and no source can make a NaN constant, which led to asking what *can* make an infinite one.
- **Tried:** `print(1` followed by 400 zeros and `.0)` prints `inf`; two such literals subtracted print `nan`. The same on the VM, the tree-walker and the self-hosted interpreter.
- **Why it matters:** [`spec/06-portability.md`](spec/06-portability.md) `[port.floats]` says an overflowing float *result* is infinity, not an error, so a literal that overflows
  follows the same rule; but integers that are too large are an error ("never a wrong answer ... or infinity"), so a long literal that is a whole number with a `.0` behaves
  differently from the same digits without it. It is a literal nobody writes on purpose, and `inf` is not otherwise reachable from source.
- **Decided (owner, 2026-11-14):** the bytecode format accepts positive infinity as a float constant so every program that compiles can be written; whether the lexer should refuse
  such a literal is decided in M13 with the number-formatting and decimal work (G-008, G-044).
- **Probe:** [`tests/portability/test_float_literal.py`](../tests/portability/test_float_literal.py): the three engines print `inf` and `nan`; it fails the day that changes.

## G-053 A NUL byte rides through a text reader as an ordinary character - TRAP
- **Found:** 2026-11-14, stress-testing the product pilots with hostile input (Nova_Data's chaos suite, a CSV row with a `\0` in a description). A NUL
  byte is not text: it is what a truncated binary, a file in the wrong encoding, or a half-written download looks like when it is read as text. Nothing
  in the pipeline noticed it.
- **Tried:** a `Date,Description,Amount,Category` file with a good row and a row whose description is `Null\0byte`.
  - **`std:csv`:** `csv.parse("a\0b,c")` returned `[["a\0b", "c"]]` — the NUL was carried through as a field character (it is not a quote, a delimiter or a
    line end, so the unquoted-field scan swallowed it). The amount on the row still parsed, so the row counted toward the total.
  - **`read(path)`:** returns the whole file as a string with the `\0` in it; the program then works on text that is not text.
- **Why it matters:** a value that contains a NUL is almost never what the program means to process; letting it through turns "this file is not CSV / not
  text" into a silent wrong answer (a counted row, a mis-split field) far from where the bad bytes entered. Refusing it at the reader, with a message that
  names the line, turns a silent corruption into a clean, located error — the kind of fix that benefits every consumer of the module, not one app.
- **Decided (owner ruling, 2026-11-14):**
  - **`std:csv` — fixed in 2.4.0 (this release).** `csv.parse`, `parse_with` and `parse_lines` refuse a NUL in any field with `found a null byte in a field
    on line N; a null byte is not text, so the input is not a CSV record`, named like the other malformed-input errors. `std:csv` is a provisional module
    (added 2.4.0), so hardening it before it is ever released is a minor change (`docs/spec/STABLE.md`). This is what lets Nova_Data reject the *row* and keep
    the rest of the file: its per-line `read_record` catches the error and turns it into a rejected row with a reason, exactly as it already does for an
    unclosed quote.
  - **`read()` — deferred, a MAJOR change.** `read()` is a stable global builtin that today returns a string with the NUL in it; making it refuse a NUL
    would change accepted input into an error, which `docs/spec/STABLE.md` makes a MAJOR change. It is held for the next major release, where the text
    builtins' handling of non-text bytes can be settled together (a NUL, and perhaps invalid UTF-8's error text).
- **Probe:** `std:csv` part — [`tests/std/test_csv.py`](../tests/std/test_csv.py) `Errors.test_a_null_byte_in_a_field_is_refused_and_names_the_line` (a
  regression: it passes now and fails the day csv stops refusing NUL). `read()` part — no probe yet; it is added with the fix, asserting `read()` of a file
  with a NUL is refused, and it fails until then.

## G-054 The path gate approves a path, then a later syscall opens it again - a TOCTOU - BLOCKER (security)
- **Found:** 2026-11-14, Tier 2 of the product-pilot stress test ("can the `restricted` sandbox be made to read a file outside its grant with a crafted
  symbolic link?"). The answer is **yes**, through a time-of-check / time-of-use race, so this is a critical sandbox-escape, not a near miss.
- **The hole, in the code (not a timing artefact — the structure is the bug):**
  - The gate is `Capabilities.check_path` (`novalang.py`): it calls `real_path(path)` → `os.path.realpath(path)`, which **follows every symbolic link** and
    gives the real target, then approves the call if that target is inside a granted root.
  - The open is separate and later. `open_file(path, ...)` (and `native_files_next_lines`, `builtin_write`, `native_files_size`, `is_dir`, `sha256_file`,
    `listdir`, `mkdir`, `rename`, `exists`) opens the **original path string again** with a plain `open()` / `os.*` call, which **follows symbolic links a
    second time**. Nothing checks that the inode opened is the inode that was approved.
  - Between the two steps the path can resolve to two different files. A program running in a granted directory it can write (Nova_Sort sorts such a
    directory; Nova_Log is pointed at one) replaces a name it owns with a symbolic link after the check and before the open: at check time the name is an
    ordinary in-grant file (approved), at open time it is a link to `~/.ssh/id_rsa` or `/etc/passwd` (opened). `realpath` resolving links is exactly what
    lets the swap escape — the approved real path and the opened real path differ.
- **Reproduced (symlink-swap race; the probe to be added runs it in a loop under a stopwatch):**
  - **Nova_Log** (read grant on a directory): a helper that flips a name between a benign file and a link to a secret, in a tight loop, led the sandboxed
    reader to read the **out-of-grant secret hundreds of times in a 60 s window** — the approved path and the opened path were different files.
  - **Nova_Sort** (write grant): the same flip let a `rename()`/open land on a target **outside the grant hundreds of times in 60 s** — a write where no
    write was granted. The sandbox's promise ("this program may only touch this one folder") does not hold against an attacker who shares that folder.
- **Why it matters:** `[sbx.paths]` is the sandbox's central promise: a `restricted` program reaches only the granted folders. A check that resolves links
  and an open that resolves them again, with a writable directory in between, is the textbook TOCTOU; it voids the promise for the two pilots that most
  need it (both operate inside a user-writable directory). This is the "sell it to the military / critical bug" line of the Tier 2 brief, on the critical side.
- **Fix — Part A, shipped 2026-11-15 (M14):** the final component of every file open in the restricted profile is opened with `O_NOFOLLOW`, so the kernel
  refuses a terminal symbolic link in the open itself — the open *is* the check for the last component, with no window. `read`, `write`, `append`, `copy`
  (both ends), `files.lines`/`files.each_line` and `files.sha256_file` are covered; `remove`/`rename` act on the final name, never a link's target (they use
  `lstat`, not `isdir`, to decide dir-or-file, so a swapped link cannot misdirect them). On Windows, which has no `O_NOFOLLOW`, the handle's real path is read
  back with `GetFinalPathNameByHandleW` and refused unless it still resolves in-grant. The guard is restricted-only: the trusted profile has no grant to
  escape and still follows links. A symbolic link at the final component is now refused **even when it points in-grant**, because the kernel cannot tell an
  honest link from the attacker's swap (`docs/spec/16-sandbox.md [sbx.toctou]`; a behaviour change, named in the CHANGELOG Security section and STABLE Row 44).
- **Residual — Part B, Phase 6:** `O_NOFOLLOW` guards only the **last** component. A **parent directory** swapped for a symbolic link between the check and
  the open is still a race the final-component guard does not close; closing it needs `openat`/`O_NOFOLLOW` per segment (a directory-fd walk) and a larger
  change to the sandbox core and its security matrix. Until then the posture is exactly: *Static attacks are refused; concurrent modification of the granted
  directory is mitigated by `O_NOFOLLOW` (final component) but remains vulnerable to parent-component races until Phase 6.*
- **Probe:** the swap is exercised two ways. [`tests/std/test_files.py`](../tests/std/test_files.py)`::Restricted` asserts, statically, that a final-component
  link (in- or out-of-grant) is refused by every reader and writer. [`tests/security/test_toctou_chaos.py`](../tests/security/test_toctou_chaos.py) re-runs the
  original loop exploit under a stopwatch — a background thread swaps the final name between an in-grant file and an out-of-grant link while a sandboxed program
  reads (or writes) it thousands of times — and asserts both that the race really landed (the link was placed many times) and that the sandboxed program touched
  the out-of-grant target **zero** times, where before it read it ~590×/min and wrote it ~825×/min. The same loop runs in each pilot's `tests/test_chaos.py`
  once the fixed interpreter is re-vendored.
