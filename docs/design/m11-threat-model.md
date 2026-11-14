# M11 threat model

Status: **Owner-reviewed and Architect-reviewed, pending independent third-party audit.**
Written 2026-11-08 as
slice 1 of M11 ([plan](m11-security-plan.md), [ADR 0003](../decisions/0003-security-stance.md)).
This document says what NovaLang's sandbox profile is meant to defend, and, first, what it
does not. Anything not listed as defended is not defended.

## What is claimed

NovaLang claims **capability gating and resource limits**. It does not claim isolation.
It does not claim that a program running in the `restricted` profile cannot harm the host.
The claim is narrower and testable: *a program in `restricted` can reach only what the
embedder granted, and cannot use more steps, time, output or collection size than the
embedder allowed, on any of the three engines.* The specification is
[`16-sandbox.md`](../spec/16-sandbox.md).

## What is not defended (read this first)

| # | Not defended | Why, and what to do instead |
| --- | --- | --- |
| N1 | The Python process the engine runs in. | CPython has no strong in-process isolation. A bug in the interpreter, in the standard library it uses, or in CPython itself is outside the model. Run untrusted code in a separate process or container as well. |
| N2 | Memory in total. | The size limits bound each list, string and dictionary. They do not bound how many of them a program keeps. A program can still use a lot of memory: with limits of 2,000 items and 30,000 steps the fuzzer saw one grow by about 450 MB in 4 s, and two thousand lists of two thousand items take 130 MB in 2,000 steps; with the defaults (1,000,000 items, 5,000,000 steps) the bound is far above any machine. The subprocess runner adds an address-space limit on Linux only; that, or a container, is the answer to this threat. |
| N3 | Side channels: timing, cache, resource contention, the content of error messages the embedder shows. | Not modelled. |
| N4 | A host function the embedder writes badly. | A granted host function runs with the embedder's authority. The sandbox gates *whether* a script can call it, not what it does. |
| N5 | Time between a path check and the use of the path (TOCTOU) in a folder that another process can change. | The check resolves the real path and the use opens it, as two steps. A folder shared with a hostile process is not safe. Grant only folders you control. |
| N6 | A hostile embedder, a hostile operating system, a hostile Python installation or modified source files of the engine. | The embedder is the trusted party. |
| N7 | The `trusted` profile. | It is today's behaviour and has no limits, by design. Never run code you did not write in it. |
| N8 | The Python bridge once the embedder grants a module. | A granted module is the embedder's decision and extends what the program can do to whatever that module can do (`socket`, `os`, `subprocess` are never to be granted to code you do not trust). The bridge's own gate (private names, writes) is defended and tested ([python-bridge-hardening](python-bridge-hardening.md)). |
| N9 | The policy dialect's host functions. | They are host-registered by definition (N4). Its limits are in scope in slice 7. |
| N10 | Anything about the editor tools, the package registry or the REPL. | Out of M11. Packages declare capabilities in M13. |
| N11 | Hard links, bind mounts and other aliases of a file that the file system itself presents as a path inside a granted folder. | A hard link is the same file under a second name; no path check can tell. A folder that holds a hard link to a file you did not mean to share, or a mount of another volume, is a granted folder that contains that file. Grant only folders you have built for the purpose. |
| N12 | The file system names that only Windows has (short 8.3 names, alternate data streams, reserved device names such as `CON` and `NUL`) beyond what the corpus tests there. | The corpus has a Windows case for device names and the CI matrix runs it; names beyond it are not tested. Where it matters, run the program on a system whose paths you control. |

## Assets

| Asset | Where it lives |
| --- | --- |
| A1 Files the embedder did not grant | host file system |
| A2 Environment variables (secrets in them) | host process |
| A3 The network | host machine |
| A4 CPU time of the host | host process |
| A5 Memory of the host | host process |
| A6 The host's output channel (a log, a terminal, a response) | host process |
| A7 Other engines' state | the embedder's other engines in the same process |
| A8 The ability to stop the program (liveness of the host) | the embedder's thread |
| A9 Determinism of a replay | simulation and test embedders |

## Actors

| Actor | Intent | In scope? |
| --- | --- | --- |
| Hostile script author | Reads or writes what was not granted, uses unbounded resources, hangs the host. | **Yes**, the main actor. |
| Careless script author | A bug: an endless loop, a runaway string, a recursion. | **Yes**, the same limits stop it. |
| Hostile data a script reads | A file or input with a crafted size or content (a huge line, a `..` path inside a data file). | **Yes**, size limits apply to what `read` and `input` return. |
| Hostile module | A module that is imported and runs with the importing program's authority. | **Yes**: the grant for `import` names the folders modules may come from. |
| Embedder | Configures the sandbox. | **Trusted** (N6). |
| Another process on the host | Changes files while a script runs. | No (N5). |

## Threats, defences and the tests that prove them

Each row becomes cases in the corpus and a cell of the coverage matrix
(`tests/security/`, `docs/spec/16-sandbox.md`).

| Threat | Defence in `restricted` | Spec section | Residual risk |
| --- | --- | --- | --- |
| T1 A script reads or writes a file | The file functions are not defined unless granted. A grant names folders. | `sbx.capabilities`, `sbx.paths` | N5 |
| T2 A script escapes a granted folder with `..`, an absolute path, a symbolic link or a name that differs only in case | The real path of every argument must lie inside a granted folder. | `sbx.paths` | N5 |
| T3 A script imports a module from anywhere | `import` is a file read and follows the same folder grant. | `sbx.capabilities`, `sbx.paths` | N5 |
| T4 A script reads secrets from the environment | `env` is not defined unless granted; a grant names the variables. | `sbx.capabilities` | none known |
| T5 A script ends or stalls the host process | `exit`, `input`, `sleep` are not defined unless granted; `exit` ends the run, never the embedder's process. | `sbx.capabilities` | none known |
| T6 A script uses the network | NovaLang has no network built-in. The Python bridge is off, and a granted module is N8. | `sbx.capabilities` | N8 |
| T7 A script runs for ever | Step budget and wall-clock limit end the run with an error a `try` cannot catch. | `sbx.limits` | a built-in that cannot be interrupted (T8) |
| T8 A pattern makes `regex` run for ever on a small input | `regex` is a separate capability, denied by default (`replace_all` left it in M13). Since M13 slice 4 the matcher is the one of `[lib.regex]`, written for NovaLang: a Pike machine whose time is the pattern times the text whatever the pattern, charged to the step budget and the time limit, so the engine's own limits end the run and the runner is no longer the only stop. Pattern size, groups, nesting and repeat counts are limited. Kept as a capability until a release of fuzzing. | `sbx.capabilities`, `sbx.limits`, `lib.regex` | N1, N2 |
| T9 A script builds a huge string, list or dictionary | A size limit on every operation that can grow one, including `+`. The error is a NovaLang error. | `sbx.limits` | N2 |
| T10 A script writes unbounded output | Output limit; the write that would pass it is not made. | `sbx.limits` | none known |
| T11 A script exhausts the call stack or the parser | Call depth limit; parser nesting limit; both are NovaLang errors. | `sbx.limits` | none known |
| T12 A script catches a limit error and carries on | The budget, time and output errors cannot be caught. | `sbx.limits`, `sbx.errors` | none known |
| T13 A host failure reaches the program as a Python traceback | `[sec.error-boundary]` extends to every limit in the table: a limit is an error of the specified kind, never the host's report. | `sec.error-boundary`, `sbx.errors` | an unknown leak is a bug, fixed with a case |
| T14 A replay differs from the original | Deterministic mode: a seeded generator, a virtual clock and a UTC `format_time`. | `sbx.determinism` | none known |
| T15 One engine is looser than another | Every capability and limit is tested on all three engines. | `sbx.claims` | the coverage matrix reports any cell without a test |
| T16 A hostile input finds a hole the cases did not think of | The escape corpus (`sandbox-escape.json`, about seventy programs: names, path spellings, links, modules, fatal limits in every syntactic position, size evasion, parser and stack depth, the Python bridge) and two seeded fuzzers (`tests/security/fuzz.py`: random hostile programs; random operations on random path spellings, judged by what changed on disk). The fuzzers found one host leak when first run (a `for` bound beyond a float), fixed with its case. | `sbx.claims` | whatever neither the corpus nor the fuzzers reach: a fuzzer is evidence of absence only for what it generates |
| T17 A poisoned compiled-artifact cache: a file another account (or a program) planted in the cache directory is read instead of a program's own compilation | The directory must be the user's own and not writable by group or others, an entry must be a regular file the user owns and others cannot write, and none is read through a link; the loader reads a closed set of constant types and makes every check of `[bc.verify]`, so a file that is accepted can do what a program can do under the running profile and no more (gated built-ins are named, never pointed at, and a gated name in a file is refused); a restricted run uses no cache unless the embedder names a directory; the type gate and the profile's name gating run on a hit exactly as on a miss; any doubt is a miss, never a failure. | `bc.cache`, `bc.verify`, `bc.constants`, `bc.profile` | an entry need not be the compilation of its source, so anyone who can write the user's cache directory can change what that user's programs do: the directory rules are the only defence, and they are not verified on Windows (the cache is off there); a file that passes verification but is wrong at run time ends as `InternalError`, never a traceback |

## How a claim is made

1. A capability or limit is written in `16-sandbox.md` with an id.
2. The coverage matrix derives one cell per (capability or limit, test kind, engine) from
   that text. A capability needs a *denial* case and a *grant* case; a limit needs a *trip*
   case; each on the bytecode VM, the tree-walker and the self-hosted interpreter.
3. A cell is **covered** only when a case cites it and the engine follows the specification
   in that case. A case in which the engine still disagrees is recorded in the divergence log
   and the cell stays **pending**.
4. `restricted` is not described as a sandbox, as safe, or as a boundary anywhere until every
   cell is covered and an independent reviewer has read this document. See the "claims"
   section of the specification for the exact words allowed.

## Review status

| Reviewer | Date | Scope | Outcome |
| --- | --- | --- | --- |
| Project owner | 2026-11-08 | The plan ([m11-security-plan](m11-security-plan.md)) | Reviewed. |
| Project owner and architect | 2026-11-08 | This document and `16-sandbox.md` | **Reviewed** (owner and architect). |
| Independent third party | none | none | **Pending.** No "security boundary" wording before this row has an outcome. |
| (none yet) | 2026-11-14 | Threat T17, added after the review above | **Not reviewed.** Written with the compiled-artifact cache (M12 slice 5); the reviewer of M11 is also asked to read the loader. |
| (none yet) | 2026-11-13 | `replace_all` moved out of the `regex` capability (G-050; M13 slice 1) and the capability rule for standard modules (`[mod.std]`) | **Not reviewed.** A relaxation of `[sbx.capabilities]`: `replace_all` is a plain substring replacement that was grouped with `regex` by mistake, and the string limit already bounds it. The reviewer of M11 is asked to read both. |
| (none yet) | 2026-11-14 | The regex matcher of M13 slice 4 (`[lib.regex]`, `[lib.std-regex]`) and the amended `regex` row of `[sbx.capabilities]` | **Not reviewed.** The one engine whose work is written here instead of borrowed from the host, run on untrusted patterns and texts: the reviewer of M11 is asked to read `RegexParser`, `RegexProgram` and `regex_search` in `novalang.py`, the limits of `[lib.regex]`, and the differential fuzzer. The capability is kept for this reason. |
