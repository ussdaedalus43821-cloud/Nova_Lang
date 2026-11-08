# M11 plan: security model and sandbox

Status: **Owner-reviewed and Architect-reviewed, pending independent third-party audit** (the plan and the specification, 2026-11-08); decisions recorded in [ADR 0005](../decisions/0005-m11-profile-defaults-and-scope.md).
Slice 1 is written (see the end of this file); nothing here changes the language yet.
It applies [ADR 0003](../decisions/0003-security-stance.md) (accepted: capability gating and
resource limits, **not** isolation) with the method of M10: the specification first, a
conformance corpus that cites it, and every claim tested on every engine.

## What "zero trust" means here, and what it does not

`docs/spec/05-security.md` already uses "zero trust" for one property: **a program has no
authority it was not given** (`[sec.principles]`). That is the property M11 builds and tests.
It is not a claim of isolation. ADR 0003 forbids the words "security boundary" and "sandbox
guarantee" until an independent review has happened, so this plan, the specification and the
README say **capability gating and limits**, and say that code you did not write should also run
in a separate process or container.

## Where we start: measured on 2026-11-08, not assumed

Each line was run against `d54a1f3`.

| # | Finding | What it means |
| --- | --- | --- |
| 1 | `[sec.principles]` says host abilities are "present only if the host provides it". In fact **every host function is a built-in** (`BUILTINS` in `novalang.py`): `python3 novalang.py` and an embedded `Nova().eval('read("/etc/hostname")')` both read any file. `write`, `remove`, `env`, `cwd`, `time`, `sleep`, `input`, `exit` likewise. | The spec states a property the implementation does not have. The `host` profile is a test label, not a gate. This is the main work of M11. |
| 2 | A module imports from **outside** its own folder (`import "../outside.nova"` ran). | `import` is a file read and needs the same path rules as `read`. |
| 3 | `s = s + s` forty times and `l = l + l` forty times end with a raw Python `MemoryError` (the guard covers `*`, `append` and `range`, not `+`). | Breaks `[sec.error-boundary]`: a host failure reaches the program as the host's report. |
| 4 | `regex("(a+)+$", "aaaa…!")` runs for more than 10 s (Python `re` backtracking). | A wall-clock limit alone is not enough in-process: nothing can interrupt `re`. This is an argument for the subprocess runner. |
| 5 | A dictionary grows to 3,000,000 entries; a program prints 33 MB. There is no step budget, no wall-clock limit and no output cap on the Python engines. | `[sec.limits]` says so; M11 closes it. The GDScript port and the policy dialect already have a step budget. |

The Python bridge is the part that was already done (2.1.0: off unless asked, one gate, a test
that walks every allowed path).

## Slices

Each slice is one branch and one PR, merged only on the owner's go-ahead, with one matrix per
pushed commit. The same rules as M10.

### Slice 1: threat model and specification (no code)

- `docs/design/m11-threat-model.md`: assets (host files, environment, network, host memory and
  CPU time, other engines' state, the embedder's secrets), actors (a script author who is
  hostile, a script author who is careless, a hostile module, a hostile data file read by a
  script, a hostile embedder is out of scope), and a table **defended / partly / not defended**.
  Not defended, stated first: the Python process itself, side channels, a host function the
  embedder writes badly, memory in total, TOCTOU on paths in shared folders.
- `docs/spec/16-sandbox.md`, section ids `sbx.*`:
  - `sbx.profiles`: `trusted` (today's behaviour), `restricted` (every capability denied unless
    granted) and the `deterministic` switch of slice 4.
  - `sbx.capabilities`: one entry per capability with the exact grant syntax, the exact denial
    (`undefined name 'read'`, as `[sec.principles]` already says, never a partial function) and
    what the grant covers.
  - `sbx.paths`: how a path is checked (below).
  - `sbx.limits`: one table, each limit with its error text, its reference value and the
    **minimum** a host must keep, as `[port.limits]` does.
  - `sbx.runner`: the subprocess runner's contract.
  - `sbx.claims`: the list of what is and is not guaranteed, written once, quoted by the README.
- Amend `[sec.principles]` and `[sec.limits]` to point at it. Corpus: `security-*.json` cases for
  `profile: "sandbox"`, cited sections, same station rules as the rest.
- `docs/decisions/0005`: the open decisions below, once answered.

### Slice 2: capability gating (tree-walker and VM)

- A `Capabilities` object chosen when the engine is created. A denied host function is **not
  defined**, so the denial is the ordinary `undefined name` of `[err.name]`, catchable, identical
  on both Python engines. Existing `trusted` behaviour is untouched.
- Capabilities, each with a denial test and a grant test on each engine:
  `files.read` and `files.write` (by path root), `import` (module search roots), `env` (names),
  `clock` (`time`, `now`, `sleep`, `format_time`), `random`, `stdin` (`input`), `process`
  (`exit`, `args`, `platform`, `cwd`), `python` (already exists, folded into the same object).
  **Network:** NovaLang has no network built-in, so the capability is "absent", tested by
  asserting that no name exists and that the Python bridge cannot import `socket` and friends
  unless the embedder grants the module.
- **Path rules** (`sbx.paths`), each a case: resolved against the real path (symlinks followed),
  must be inside a granted root, `..` and absolute paths outside the roots denied, a symlink
  inside a root that points out is denied, case-insensitive file systems compared case-folded,
  Windows drive and UNC forms denied unless granted, a denial never reveals whether the target
  exists. The check and the use are two steps; the residual TOCTOU race is listed under "not
  defended" rather than hidden.
- CLI: `--profile restricted --allow-read DIR --allow-write DIR --allow-env NAME ...`.
  Embedding: `Nova(profile="restricted", read=[...], ...)`.

### Slice 3: resource limits, identical on both engines

Lesson from M10, applied here: an **exact step count is not portable** (the bytecode VM counted
instructions, the tree-walker counted nodes). The specification guarantees *bounds*, not counts:
a loop of 20,000 passes completes, one of 1,000,000 fails, an endless loop always fails.

- New: **step budget**, **wall-clock limit** (monotonic clock, checked at the same points as the
  budget; `sleep` counts), **output size** (bytes `print` and `log` may write per run),
  collection and string size on **every** operation that can grow one (`+`, `join`, `pad`,
  `replace_all`, `str` of a structure, dictionary entries), and the raw `MemoryError` of
  finding 3 becomes the specified error.
- Existing and kept: call depth, list and string repetition, `append`, `range`, integer digits.
- A table in `sbx.limits`: limit, error, reference, minimum. Every row has a case that trips it
  on the tree-walker, the VM and the self-hosted interpreter. The self-hosted interpreter is
  slower and has a shallower call depth, so its minimums are written separately, as
  `[port.limits]` already does.
- The default for `trusted` stays unlimited unless the owner decides otherwise (decision 2).

### Slice 4: deterministic mode

- `deterministic=true`: `random`, `randint`, `choice`, `shuffle` draw from a **specified**
  generator (algorithm and seeding written in the spec so the tree-walker, VM, self-hosted
  interpreter and the GDScript port give the same sequence; the policy dialect already has a
  seeded generator and fixes the style), and `time`, `now`, `sleep` read an embedder-supplied
  clock or are absent. Combined with no `env`, `input` or file access, the same program, seed and
  inputs give the same output on every engine, which is the replay the roadmap asks for.
- Cases run each program on all engines and compare the whole output.

### Slice 5: the subprocess runner

- `run_isolated(source, profile, limits, ...)` and `novalang.py --isolate`: a child interpreter
  started with `python -I`, an emptied environment, a fresh working directory, standard input
  closed, output captured and capped, killed on the wall-clock limit. On POSIX it also sets
  `RLIMIT_CPU` and `RLIMIT_AS`; **Windows has no equivalent in the standard library**, so the
  specification says what Windows does not get rather than implying it.
- This is the answer to finding 4: a hung `regex` is stopped by killing the process, with the
  specified `time limit` error, instead of by hoping the engine can interrupt `re`.
- It narrows the damage of a bug in the in-process checks. It is still not a container; the
  documentation says to add one.

### Slice 6: escape-attempt station and fuzzing

- `tests/security/` and a conformance group `security-escape-*`: programs that try to exceed a
  capability or a limit, each with the specified denial. Includes path tricks, import tricks,
  names that should not exist, every built-in called with hostile arguments, parser nesting
  depth, huge literals, and the ReDoS pattern above.
- A fuzzer on top of the generated-program harness (`tests/differential`): random programs run
  under `restricted` with small limits on every engine, asserting three things only: it never
  escapes a capability, never ends with a host traceback, and all engines agree.
- A **coverage matrix** station: it reads the capability and limit tables from the specification
  and fails if any (capability or limit) x (engine) cell has no denial/grant or trip test. This
  turns the exit criteria into something CI can fail on, like the rule that every spec section is
  cited.

### Slice 7: the game's dialect and the GDScript port

- Record the policy dialect in the same limits table (steps, depth, list and string size already
  exist there). Close or state the two items M10 left unbounded: **dictionary entries** and the
  time `==` takes on structures that share parts with themselves.
- Reactor-Game mods are real untrusted code, so this is where the model meets a user: check the
  moddable entry points (`MODDING_REACTOR.md`) against the table.
- Port only the limit and capability changes that apply to the game's host; the GDScript engine
  has no files or network to gate.

### Slice 8: review package and wording audit

- A hand-off document for an independent reviewer: threat model, specification, test inventory,
  known gaps. The review itself is the owner's to arrange; **no "boundary" wording is added
  before it happens**.
- A wording audit of the README, `CONTRIBUTING.md`, the roadmap and the spec for any sentence
  that over-claims, with a test that greps for the forbidden phrases.

## Exit criteria (from the roadmap, made checkable)

1. Every capability has a denial test and a grant test on each engine (the coverage matrix).
2. Every limit has a test that it trips with the specified error on each engine.
3. `trusted` behaviour is unchanged: the existing 1,926 checks pass without edits.
4. The documentation states what is and is not guaranteed, in one place (`sbx.claims`).

## Decisions (answered 2026-11-08, ADR 0005)

1. **Default of an embedded `Nova()`.** Today it is fully trusted. (a) Keep it trusted and make
   `restricted` opt-in (nothing breaks; the safe path is one argument away), or (b) deny by
   default in a 3.0 release (safer, breaks embedders). Recommendation: **(a) now, announce (b)**.
   The command-line tool stays trusted either way, since it runs your own scripts.
2. **Limits in `trusted`.** Should the step budget, wall-clock limit and output cap apply to
   `trusted` runs (with generous defaults and an off switch), or only to `restricted`?
   Recommendation: only `restricted`, because a long-running trusted script is legitimate.
3. **Scope of the self-hosted interpreter.** It is the slowest and shallowest engine. Must every
   limit and capability land there in M11 (my default, because the roadmap says "both engines"
   and the corpus runs on all three), or may it be `trusted`-only until M12?
4. **Who reviews.** Slice 8 prepares the package; an independent reviewer has to be found by you.
   Until then the documents say "not independently reviewed".

## Size and order

Slice 1 is documents only and unblocks the rest. Slices 2 and 3 can overlap once the
specification is accepted. Slice 6's matrix should be written early (as soon as slice 1 lands)
so that slices 2 to 5 are measured against it as they go. This is the roadmap's XL: expect
about the same number of PRs as M10 (8 to 10).

## Decided: answers to the four questions

1. `Nova()` and the command line stay `trusted`; `restricted` is opt-in and becomes the default in a future 3.0.
2. Step, time and output limits apply to `restricted` only.
3. The self-hosted interpreter gets every capability and limit in M11.
4. The owner reviews for now; slice 8 labels every document "owner-reviewed, pending independent third-party audit".

## Slice 1: done (drafts, 2026-11-08)

Written: the [threat model](m11-threat-model.md), [`16-sandbox.md`](../spec/16-sandbox.md), 58 cases, the divergences
D-040 to D-044 and the coverage matrix (`tests/security/matrix.py`, station `security-matrix`). Two decisions were made while
writing that the plan did not contain, for the owner to confirm or reverse:

- **`regex` is a capability of its own**, denied by default (with `replace_all`). A pattern such as `(a+)+$` ran for more than ten seconds on
  a short text, no engine can interrupt Python's `re`, and a time limit cannot be honest about it. Where granted, only the subprocess
  runner can stop it.
- **A grant of Python modules replaces the default import list** of `[py.import]`. The default list holds `re`, `random` and `datetime`,
  which would hand back the `regex`, `random` and `clock` capabilities through the bridge.
- **Fatal limits.** Steps, time and output end the run with a `LimitError` that `try`/`catch`/`finally` cannot see; otherwise a program could catch
  the budget error and carry on looping.
- **Steps are specified as bounds, not counts** (the lesson of M10): 20,000 simple passes complete, an endless loop always trips.
