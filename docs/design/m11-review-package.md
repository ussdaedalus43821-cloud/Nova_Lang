# M11 hand-off package for the independent reviewer

Status: **Owner-reviewed and Architect-reviewed, pending independent third-party audit.**
Written 2026-11-09 as slice 8 of M11 ([plan](m11-security-plan.md), [threat model](m11-threat-model.md),
[ADR 0003](../decisions/0003-security-stance.md), [ADR 0005](../decisions/0005-m11-profile-defaults-and-scope.md)).

This is the document to hand to a reviewer who has not seen the project. It says what is claimed, where to read it, what
the tests prove and how to run them yourself, what has already gone wrong and was found, and, at length, what is **not**
defended. Nothing here is a statement that the `restricted` profile is a security boundary. It is not one until a reviewer
outside the project has read the threat model, the specification and this package and the review table at the end has an
outcome.

## 1. What is claimed, and what is not

The claim is **capability gating and resource limits**, on three engines: the bytecode VM and the tree-walker (both in
`novalang.py`) and the self-hosted interpreter (`novalang.nova`, run by the VM through `bootstrap.py`).

> A program in `restricted` can reach only what the embedder granted, and cannot use more steps, time, output or collection
> size than the embedder allowed, and every limit and refusal is a NovaLang error, never a failure of the host.

The exact words, including the list of what is not guaranteed, are `[sbx.claims]` in
[`16-sandbox.md`](../spec/16-sandbox.md). The README and every other document may quote that section and may not say more;
`tests/security/test_wording.py` fails if a document uses a stronger word without a negation next to it.

**Not claimed:** isolation of the Python process; total memory; side channels; a granted Python module or host function;
folders another process changes while a program runs; the `trusted` profile (no limits, today's behaviour, the default).
The full list is section 6.

## 2. Reading order (about two hours)

| # | Document | Why |
| --- | --- | --- |
| 1 | [`m11-threat-model.md`](m11-threat-model.md) (103 lines) | assets, actors, what is **not** defended (N1 to N12), threats T1 to T16 |
| 2 | [`16-sandbox.md`](../spec/16-sandbox.md) (393 lines) | the normative text: profiles, the capability table, path rules, the limit table, determinism, the runner, errors, claims |
| 3 | [ADR 0003](../decisions/0003-security-stance.md), [ADR 0005](../decisions/0005-m11-profile-defaults-and-scope.md) | why capability gating and not isolation; the owner's decisions |
| 4 | [`05-security.md`](../spec/05-security.md), [`python-bridge-hardening.md`](python-bridge-hardening.md) | the language-level guarantees `restricted` builds on; the Python bridge gate |
| 5 | this document, sections 3 to 8 | where it is enforced, what proves it, what is open |

## 3. Where each guarantee is enforced

All line counts are as of this document; the names are what to search for.

| Guarantee | Python engines (`novalang.py`) | Self-hosted (`novalang.nova`) |
| --- | --- | --- |
| Denied names are undefined, even as values | `Capabilities`, `CAPABILITY_OF` (27 gated built-ins), the `LOAD_BUILTIN` opcode resolves a gated name at run time, so compiled code is the same for both profiles | `cap_has`, the same table in its global scope set-up |
| File, import and environment grants | `real_path` (resolves links, then `..`), `inside_folder` (`commonpath`, `normcase`), `Capabilities.check_path`, `Interpreter.resolve_import`; a null byte and a Windows device name are never inside a grant (`names_a_device`) | `check_path`, `sandbox_inside`, built on the host `realpath()` |
| Fatal limits (`steps`, `time`, `output`) | `FatalLimit(BaseException)`, so `try` cannot catch it; `Interpreter.step`, `check_time`, `write_output`; counters in `Interpreter.running()` so a host callback cannot reset the budget | `count_step`, the `LimitError:` prefix and `exec_try` rethrow |
| Catchable limits (string, list, dict, depth, nesting, integer digits) | `binary_operation(..., limits)`, `index_assign`, `check_call_arguments`, `check_result_size`, `text_would_exceed` | `check_binop_limits`, `check_dict_entry`, `LIMITS`, the depth guard |
| Determinism | `Determinism` (Knuth MMIX generator, virtual clock, UTC `format_time`) | `det_*` functions |
| Subprocess runner | `run_isolated`, `supervise`, `RUNNER_LAUNCHER`, `RLIMIT_AS` and `RLIMIT_CPU` on Linux | (runs the same launcher with `--bootstrap`) |

The three decisions that carry the most weight, because a mistake in them is a hole in everything else:

1. **Names, not checks, are the barrier for capabilities.** A denied function does not exist (`undefined name 'read'`); there
   is no runtime check to forget. The names stay reserved (`let read = 1` is an error), so a program cannot shadow one.
2. **A path is judged before it is touched, by its real path.** The same error text is produced whether or not the path
   exists, so a program cannot learn what exists outside its grants. `realpath` follows links first and applies `..` after
   them, the order the kernel uses.
3. **A fatal limit is a `BaseException`.** `try`/`catch`/`finally` in NovaLang do not see it, whichever syntactic position
   the `try` is in (the escape corpus has fourteen step-budget cases, five for output and four for time).

## 4. Test inventory

### 4.1 Stations (all run in CI on every job)

| Station | What | Count |
| --- | --- | ---: |
| `conformance` | the whole specification's corpus on the VM, the tree-walker and the self-hosted interpreter; 179 of the cases are `sandbox-*` | 1,570 cases |
| `security` | unit tests: configuration errors, every limit, one compiled script run under both profiles, `exit()`, paths and links, the Python grant, command-line flags, the runner, determinism, Windows names, the escape corpus checked against the file system, the fuzzers | 216 tests |
| `security-matrix` | the coverage matrix and the classification check, strict | 3 checks |
| (all stations) | `python3 tests/run_all.py` | 1,951 checks |

### 4.2 The coverage matrix (`tests/security/matrix.py --strict`)

The matrix is **derived from the specification's tables**, not written by hand: a row of the capability table gives a denial cell
and a grant cell; a row of the limit table gives a trip cell (and an `uncatchable` cell for a fatal limit); the path rules,
determinism and runner rows give theirs. 67 rows by 3 engines = **201 cells, all covered**. A cell is covered only when a
conformance case cites it and the engine produces what the specification says in that case. `pending.json` lists what is not
covered and why, and is `{}`: the station fails both for a hole it does not explain and for an excuse that is no longer needed.

| Kind | Rows |
| --- | ---: |
| capability (deny and grant) | 20 |
| limit (trip and uncatchable) | 22 |
| path rules | 9 |
| determinism (replay) | 10 |
| runner | 6 |

The matrix also fails when a built-in function is neither gated by a capability (`CAPABILITY_OF`) nor listed as pure in
`tests/security/pure_builtins.json` (41 pure names), when a gated name is not in the capability table of the specification,
or when no sandbox case shows it undefined without its grant. A new built-in that touches the machine cannot be added
without someone deciding which it is.

### 4.3 The adversarial tests

* **Escape corpus** (`tests/conformance/cases/sandbox-escape.json`, 90 cases, all three engines): foreign and denied names,
  every spelling of a path that leaves a grant (27), write/rename/copy forms, null bytes, links (out, chained, `..` through a
  link, a link in an imported module), modules reaching for `read`, `env` or an outside import, guessable environment names,
  fatal limits caught in every position, size evasion, parser and stack depth (eleven shapes), the Python bridge with one module
  granted, Windows device names (a Windows-only case).
* **Filesystem oracle** (`tests/security/test_escape.py`): runs the same programs in a temporary tree and compares a snapshot
  of every file and link before and after. The file system, not the engine's message, is the judge: nothing outside the
  folders a case may write to may change, and no text of a file outside the grant may reach the output.
* **Fuzzers** (`tests/security/fuzz.py`, seeded): random type-aware hostile programs on the VM and the tree-walker with small
  limits; random file operations on random path spellings in a tree with links that lead out. Findings: a Python exception
  reaching the caller, a run that outlives its limit, output past its limit, a change on disk outside the grant, outside content
  in the output, the two engines disagreeing. About 6,000 programs and 6,000 path operations were run clean on the final code.
* **Proof that the tests can see** (`test_fuzz.py`, `test_escape.py`): they put a hole back (a path check that lets everything
  in, one that ignores links, the old `for` count, a Python whose `os.path` raises for a null byte) and require a finding. A test
  that has never failed proves nothing.
* **The platform matrix:** 12 CI jobs on every push: Ubuntu with Python 3.7 to 3.13, macOS, and Windows with 3.7 and 3.12.
  Windows with Python 3.7 refuses to start `restricted` (it does not follow links when resolving a path; ADR 0005) and those
  cases skip there with a printed notice.

### 4.4 Reproducing it yourself

```sh
python3 tests/run_all.py --station security          # 216 tests, about 30 s
python3 tests/run_all.py --station security-matrix   # the matrix, strict
python3 tests/run_all.py --station conformance       # all three engines (the self-hosted one is slow)
python3 tests/security/fuzz.py programs --seed 7 --count 2000
python3 tests/security/fuzz.py paths --seed 7 --count 3000
python3 tests/run_all.py                             # everything, 1,951 checks, about 15 minutes
```

Start the full suite in the foreground, or see [`docs/CI.md`](../CI.md) ("Starting the suite from a background job"): a
background job inherits an ignored SIGINT and the REPL station's Ctrl-C tests then time out.

## 5. What the adversarial testing found (evidence about the process, not a claim of completeness)

The corpus and the fuzzers were written to break the sandbox, and they did, at once, in places the earlier tests had missed. All
were fixed, each with a regression case:

| Found by | Defect |
| --- | --- |
| recording the first cases (slice 1) | a case pinned the content of a host file (`/etc/passwd`) and the text of operating-system errors; the recorder now refuses non-reproducible output and host data |
| fuzzer | a `for` bound beyond the range of a float raised Python's `OverflowError` (also in `trusted`) |
| fuzzer | `""` or `[]` repeated by a huge count raised `OverflowError` |
| fuzzer | `+` on two dictionaries passed the dictionary limit (also on the self-hosted interpreter) |
| fuzzer | `round(5, -100000000)` took minutes in one uninterruptible C call: a hole in every time limit (also in `trusted`) |
| full suite, self-hosted | `realpath()` of a path with a null byte raised `ValueError` (also in `trusted`) |
| CI matrix, Python 3.7/3.8 and Windows | a null byte passed `realpath()`, so the folder check passed and the open raised `ValueError`; the import resolver and the type checker called `os.path.isfile` on one first |
| CI matrix, Windows | device names (`CON`, `NUL`, `COMn`) are devices in every folder, so a name inside a granted folder was not inside it |

Read this table both ways. It shows the method works, and it shows that the first version of each of these walls had a hole.
The fuzzers found nothing further in the final runs; that is evidence of absence only for what they generate.

## 6. Known gaps

Each is stated in the threat model or the specification; this is the consolidated list a reviewer should test the claim against.

| Gap | Where stated | Notes for the reviewer |
| --- | --- | --- |
| The Python process is not isolated (N1) | threat model N1, `[sbx.claims]` | the central limit of the whole design; the runner narrows it, a container closes it |
| **Memory in total (N2)** | N2 | the limits bound each list and string, not how many a program keeps; measured: one fuzz program grew 450 MB inside 30,000 steps and 2,000-item limits; with default limits the bound is far above any machine. Answer: the runner's `RLIMIT_AS` (Linux only) or a container |
| **Time is checked between steps** | `[sbx.limits]`, N2 | a single call that does not return cannot be interrupted in-process. `round(5, -100000000)` was one; it is fixed, and `regex` is the other known one (denied by default; only the runner can stop a backtracking pattern). The fuzzers found no further one; a reviewer should look for operations whose cost grows with a *value* rather than a size |
| **D-045 (closed): the self-hosted interpreter had no type gate in `restricted`** | `DIVERGENCES.md` D-045 | **closed in 2.2.0, after this package was drafted.** The self-hosted launcher used to skip its type check under `restricted` (its walk would read modules before any grant is consulted); the walk now takes the import grants and judges every module by its real path before opening it, and the type gate applies in both profiles on all three engines (two conformance cases, `tests/security/test_type_gate.py`, three of whose six tests fail without the fix). The reviewer should read that walk (`Program(allow=...)` in `tools/nova-typecheck.py`, `bootstrap.py`) as part of the path rules |
| Self-hosted limits differ in number | `[sbx.limits]` | call depth 60 (VM 1200) and parser nesting 100; cases print only the start of the message so they hold on all three engines |
| Tree-walker stack on Windows Python 3.7 | `docs/CI.md` | overflows the native stack on runaway recursion; deep cases skip there |
| TOCTOU in a shared folder (N5) | N5 | the check resolves the path and the use opens it as two steps; a folder another process can change is not safe |
| Hard links, bind mounts, other aliases inside a granted folder (N11) | N11 | no path check can tell; grant only folders you built for the purpose |
| Windows names beyond the corpus (N12) | N12 | 8.3 short names, alternate data streams, junctions and mounted folders are **not** separately tested; only device names and `\\.\` prefixes are. `os.path.realpath` is trusted for the rest on Windows 3.8 and later |
| Case-insensitive file systems | `[sbx.paths]` | handled with `normcase` after `realpath`; not tested on a case-insensitive volume other than the macOS runner's default |
| The Python bridge once a module is granted (N8) | N8, `python-bridge-hardening.md` | the bridge's own gate (private names, writes, submodules) is tested; a granted module extends the program to whatever the module can do |
| `RLIMIT_AS` is Linux only | `[sbx.runner]` | macOS does not enforce it and Windows has no equivalent; the runner still kills on wall-clock and output overrun there |
| The fuzzers are bounded by their generator | section 4.3 | they know the built-ins and the path alphabet; they will not invent a new class of input |
| The `trusted` profile | N7 | unchanged and unlimited by design; it received six leak fixes of the same classes as `restricted` while the corpus was written, which is a reason to read it as unreviewed |
| Side channels, error text shown to a user (N3) | N3 | not modelled |

## 7. Questions for the reviewer

1. Is the path rule in `[sbx.paths]` (real path first, `..` after links, judged before touching the file system, one error whether
   or not the path exists) complete for POSIX? What does it miss on a file system with case folding or Unicode normalisation?
2. Is making a fatal limit a Python `BaseException` sufficient in every embedding? Look for a host callback, a `finally` in the
   embedder, or a generator that can swallow it (`contextlib.suppress(BaseException)`, `except BaseException` in a host).
3. Which operations in the built-in library cost time proportional to a *value* rather than a size, as `round(n, -k)` did? Each one is
   a way past the time limit.
4. Is "capability gating and resource limits" an honest name for what was built, and does every sentence of the README section
   "Running a program you did not write" stay inside it?
5. Is the deterministic mode a risk in its own right (a predictable generator for a program that expects secrets)? It is opt-in and
   not a security feature, and `restricted` does not grant `random` by default; is that enough?
6. The runner passes an empty environment, closed stdin and `python -I` to the child. What else would you pass or refuse?

## 8. Review status

| Reviewer | Date | Scope | Outcome |
| --- | --- | --- | --- |
| Project owner | 2026-11-08 | the plan | Reviewed |
| Project owner and architect | 2026-11-08 | threat model and `16-sandbox.md` | Reviewed |
| Independent third party | none | this package, the threat model, the specification, the tests | **Pending.** No "security boundary" wording before this row has an outcome |
