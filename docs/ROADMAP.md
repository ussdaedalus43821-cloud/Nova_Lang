# NovaLang roadmap

This is the plan for taking NovaLang from a well-tested language implementation
to the foundation of a wider Nova ecosystem. It continues the milestone
numbering already used in the history (M0 toolchain through M6 fast paths; see
`CHANGELOG.md`).

It is a plan, not a promise. Milestones are ordered by dependency, not by date,
and carry no calendar commitments. Anything that needs a decision from the
project owner is marked **Decision** and has a record in
[`decisions/`](decisions/README.md).

Last reviewed against NovaLang v2.2.0.

The ecosystem-wide view (the master plan, its architecture, the Phase 0 to 9
roadmap and the NovaFinance design) is in [`vision/`](vision/MASTER_PLAN.md).

## Vision

NovaLang is the shared language underneath a family of products: simulation,
agents, security and connectivity services, device and home automation, desktop
and mobile tools. The product names below come from the ecosystem graphic and
are **aspirations, not existing software**. The repositories that exist today
use NovaLang as an embedded policy and scripting layer:

| Today | What it shows |
| --- | --- |
| `Nova_Lang` | The language: Python bytecode VM, tree-walker reference, self-hosted interpreter, formatter, linter, type checker, packages, language server |
| `Reactor-Game` | A reactor-control game whose rules are NovaLang, running on a GDScript port of the language inside Godot |
| `DaedalusGodot` | A ship-combat game using the same GDScript port for balance data and combat math |
| NovaDrive (not in these repositories) | A separate application whose source is to be integrated; see M14 |

## Where we are

Established, with evidence (the full suite is 1,951 checks; it passes locally, and CI has run it green on the head
commit of 2.2.0 across the Linux, macOS and Windows jobs described in [`CI.md`](CI.md)):

- One language implemented three ways that must agree: the Python bytecode VM
  (default), the Python tree-walker (reference), and `novalang.nova`
  (self-hosted). A differential station requires byte-identical output, and a
  review of 2.2.0 found no disagreement over 12,640 generated expressions.
- A formatter, linter, gradual type checker, package manager with a lockfile,
  and an LSP server with a VS Code extension.
- Regression stations for the command line, the embedding API, the REPL and
  malformed input.
- A written, normative specification with a conformance corpus that runs on every engine
  ([`spec/`](spec/README.md); a few divergences are still logged open in
  [`spec/DIVERGENCES.md`](spec/DIVERGENCES.md)).
- A `restricted` profile (capability gating and resource limits) with a threat model, an escape-attempt corpus, a
  coverage matrix and a subprocess runner. It is **capability gating, not isolation**.
- Integer `/` is exact when the quotient is whole, however large. It gave a wrong integer above 2^53 on all three
  engines in 2.2.0, which the differential station could not see because they share one helper; the conformance
  corpus now pins it.
- The GDScript port is verified against its references (M8): `parity_check.gd` and `corpus_check.gd` pass on the
  bytecode VM and on the tree-walker, on the owner's Mac and in CI under Godot 4.7.2
  ([run](https://github.com/ussdaedalus43821-cloud/Reactor-Game/actions/runs/43113071481), 778 corpus cases).
- One language for the games too: the policy dialect is a profile with its own spec chapters (M10).

Not established:

- **The restricted profile still has known gaps, and has not been independently reviewed.** A review of 2.2.0
  found that `copy(file, folder)` could write outside the granted folders through a symbolic link already in the
  destination, that the time limit could be passed by minutes because it was read only every 1,000 steps, and that
  the runner's deadline could be delayed by a large input; those are fixed after 2.2.0 (see the changelog). Left:
  a blocking read from stdin is outside the in-process time limit, and the time limit can still be passed by the
  time of one operation on the largest collection allowed. The profile is not described as a security boundary.
- **The GDScript port has no benchmark and no shared copy.** The tree-walker against VM measurement was not
  made, and `DaedalusGodot` holds its own copy of the runtime files with nothing checking that the two copies
  stay the same (they were identical on 2026-11-11). Both were M8 deliverables and are carried forward.
- **Releases are not signed or reproducible.** `v2.2.0` is a lightweight, unsigned tag with no checksums, bill of
  materials or provenance.
- **Only Linux has been exercised by hand with the latest review.** Windows and macOS rest on CI runs.
- No native backend, no remote package registry, no public API stability policy, no hard real-time guarantee,
  and no simulation libraries (units, numerics, integrators).

## Milestone overview

| # | Milestone | Status | Needs | Size |
| --- | --- | --- | --- | --- |
| M0–M6 | Toolchain, typing, packages, editor, bytecode VM, fixes, fast paths | Done | | |
| M7 | Continuous verification | Done | | M |
| M8 | Verify and finish the GDScript VM | **Done** (2026-11-11; both checks green on both backends, on a Mac and in CI; the benchmark and the shared copy are carried forward) | M7 for CI | M |
| M9 | Language specification and conformance corpus | **Done** (v2.2.0; [`spec/`](spec/README.md), the `conformance` station on all three engines) | M7 | L |
| M10 | One language: dialects become profiles | **Done** (2026-11-08; ADR 0004, `pol.*` chapters 12-15) | M8, M9 | L |
| M11 | Security model and sandbox | **Done (pending independent review)** (v2.2.0; slices 1 to 8; [hand-off package](design/m11-review-package.md)). Not described as a security boundary until the review has an outcome | M9 | XL |
| M12 | Runtime: bytecode format and performance | **Plan drafted** ([plan](design/m12-runtime-plan.md)), awaiting decisions | M9 | L |
| M13 | Platform libraries, registry and API stability | Planned | M9, M11 | L |
| M14 | Product pilots | Horizon | M10, M11, M13 | per product |

Sizes are relative effort (S, M, L, XL), not durations.

```
M7 CI ──┬── M8 GDScript VM ──┐
        └── M9 Spec ─────────┼── M10 One language
                  │          │
                  ├── M11 Security ── M13 Libraries/registry ── M14 Products
                  └── M12 Runtime
```

## Working agreement for every milestone

Each milestone follows the practice already used for M0–M6:

1. A branch and a pull request titled `Mn: <title>`.
2. A new test station in `tests/run_all.py` (or an extension of one) that fails
   without the work and passes with it. A milestone without a failing-first
   test is not done.
3. A `### Mn:` section in `CHANGELOG.md`, and `DEVELOPMENT_STATUS.md` updated.
4. The hard constraints in `CONTRIBUTING.md` hold: host and self-hosted parity,
   the scope barrier, the curated `python.*` bridge.
5. Stop the line: a failing check blocks the milestone; it is not skipped,
   quarantined or loosened.
6. Claims in docs are measured, not asserted. A number goes in a document only
   with the command that reproduces it.

---

## M7 — Continuous verification

**Goal.** Make "the suite is green" a fact a machine reports on every change,
on every supported platform.

**Why first.** Everything after this changes the language or its runtimes.
Without CI, each change is re-verified by hand on whatever machine is at hand.

**Deliverables**

- GitHub Actions workflow running `tests/run_all.py` on Linux, macOS and
  Windows across the supported Python versions, with NumPy and Node installed
  for the stations that need them.
- A decision on the Python floor: either make 3.7+ true (test it) or raise the
  stated minimum to the oldest version that passes. The README must match.
- A fast tier (`--quick`, under a few minutes) required on every pull request
  and the full suite on merge to the main branch.
- Branch protection requiring the fast tier.
- The known REPL gaps closed or ticketed: a `{` inside a quoted string in a
  draft, `help` transcript, Ctrl-C. (Closed: the first was a bug and is fixed;
  `help` and Ctrl-C had no bug and now have transcript tests.)
- Windows-specific fixes the matrix exposes (paths, file URIs, newlines, the
  time limit; `chmod` was a guess that the first run disproved).

**Status (2026-11-08).** Done. The workflow (a fast tier and a full matrix with
required rows and one probe row), SHA-pinned actions with Dependabot updates,
and [`CI.md`](CI.md). `fast` passes on pull requests in about 1 m 45 s and is
required by the repository's CI Gate ruleset. The full matrix on the default
branch (run 22) passed on all ten rows: Linux 3.7 to 3.13, macOS 3.12 and
Windows 3.12, each 1,921 checks, and Windows 3.7 (a probe) at 1,922. The first
Windows run found four portability bugs, now fixed and pinned by the
`portability` station. Windows with Python before 3.11 cannot run the
tree-walker on the 16 of 300 generated programs that recurse to the call-depth
limit (a native stack overflow), so the comparison skips them, visibly, and
compares 284; a larger-stack thread for the tree-walker is a deferred decision.
The three REPL gaps are closed.

Exit criteria, checked: a pull request cannot merge without `fast` (the CI Gate
ruleset); the full suite passes on the declared matrix; the README states the
versions CI covers.

**Exit criteria**

- A pull request cannot merge with a red required check.
- The full suite passes on the declared matrix, or the declared matrix is
  reduced to what passes.
- README and `CONTRIBUTING.md` state the same supported versions as CI.

**Out of scope.** Coverage thresholds as release gates (coverage is evidence for
choosing tests; see `docs/COVERAGE.md`).

**Risks.** Some stations are slow (bootstrap runs, 300 generated differential
programs); the fast tier needs a deliberate cut. The matrix may reveal real
platform bugs, which is the point.

## M8 — Verify and finish the GDScript VM

**Goal.** The Godot port of the bytecode VM is proven equal to the tree-walker
and to the Python reference, measured, and shared by both games.

**State: closed by the project owner on 2026-11-11.** `NovaVM2`, the resolver and the compiler run in Godot
4.7.2. `parity_check.gd` (the recorded Python oracle and the 900-step reactor trace) and `corpus_check.gd` (the
specification's policy corpus) pass on the bytecode VM and on the tree-walker: on the owner's Mac (238 parity
checks; 768 corpus cases, the corpus before the ten `overrides` cases) and in CI on Linux on the 778-case corpus
([run](https://github.com/ussdaedalus43821-cloud/Reactor-Game/actions/runs/43113071481)). The first runs in Godot found real bugs, as the risk below expected (a compile error in NovaVM2, a
parser crash, module globals, NaN handling, float comparison); they were fixed on 2026-11-08.

What closing it did and did not include, against the lists below:

| Item | Status at closing |
| --- | --- |
| `parity_check.gd` green in headless Godot, both backends | Done |
| The policy corpus (`corpus_check.gd`, added by M10) green, both backends | Done |
| `nova_compiler_test.gd` green | Not recorded: it is not one of the two checks that were run for the closing, and it is not in the CI job |
| A headless-Godot CI job in `Reactor-Game` | Written and green ([pull request 6](https://github.com/ussdaedalus43821-cloud/Reactor-Game/pull/6)); it runs `parity_check.gd` and `corpus_check.gd` |
| Benchmark of tree-walker against VM, committed with its command | **Not done; carried forward to M12** |
| The port shared by both games, or a check that the copies match | **Not done; carried forward.** The copies were byte-identical on 2026-11-11, by hand |
| Both games run the VM by default with the tree-walker as the flagged fallback | Not checked for the closing |
| The two narrow divergences (signal-error attribution, shared call-depth budget) fixed or recorded as accepted | Not recorded |

The milestone is closed by decision, with the verification done and the rows marked otherwise still open.

**Deliverables**

- `nova_compiler_test.gd` and `parity_check.gd` run green in headless Godot,
  both backends, against the recorded Python oracle (51 cases, the 900-step
  reactor trace, the Daedalus data, AI and weapons checks).
- A headless-Godot CI job in `Reactor-Game` running both scripts.
- A benchmark script comparing tree-walker and VM on microbenchmarks, the
  reactor tick, and Daedalus combat calls, with the measured speedup recorded.
  The expected 2–4x is a hypothesis until measured.
- The port copied to `DaedalusGodot`, plus a mechanical check that the two
  copies stay identical, or a decision to vendor it once as a shared addon.
- The two known narrow divergences from the tree-walker (signal-error
  attribution, call-depth budget shared across a nested import) either fixed or
  recorded as accepted.

**Exit criteria**

- Parity green on both backends, in CI.
- Benchmark results committed with the command that produced them.
- Both game repositories run the VM by default with the tree-walker as the
  flagged fallback.

**Risks.** The port was written without being executable in the authoring
environment, so the first real run will find bugs. That is expected; budget for
a fix cycle.

## M9 — Language specification and conformance corpus

**Goal.** Make the language a written, testable contract that any host can be
checked against, instead of "whatever `novalang.py` does".

**Deliverables**

- `docs/spec/`: lexical grammar, grammar, evaluation and scoping rules, the
  value model, the error-message catalogue, the standard library as profiles
  (core, host I/O, embedding), and a versioning rule (what a major, minor and
  patch change means for the language).
- `tests/conformance/`: a host-neutral corpus (source, expected output, expected
  error text, expected host calls, profile tags), generated from the reference
  engine and committed as data, in the same shape `Reactor-Game` already uses
  for its 51 cases.
- A `conformance` station running the corpus on the VM, the tree-walker and the
  self-hosted interpreter.
- A rule that every spec section is cited by at least one corpus case, checked
  mechanically.
- A divergence log: where the implementations disagree with the written spec,
  each item is classified spec bug or implementation bug and resolved.

**Exit criteria**

- All three Python engines pass the corpus.
- The `Reactor-Game` oracle cases are expressible as corpus cases under a named
  profile.
- Someone who has not read `novalang.py` could implement a conforming host from
  the spec and corpus (reviewed by actually attempting a small one).

**Decided.** The specification and corpus are normative; the reference
implementation is the first conforming host
([ADR 0001](decisions/0001-specification-is-normative.md), accepted).

**Status (2026-11-08).** Three slices written. [`spec/`](spec/README.md) has 105
sections in eleven chapters: lexical structure, values, expressions, scoping, the
error catalogue, the security properties of the language, the rules a portable
host must follow, statements, modules, the core library, the host library, and embedding with the Python bridge. [`tests/conformance/`](../tests/conformance/README.md)
has 606 cases citing them, run by the `conformance` station on the VM, the
tree-walker and the self-hosted interpreter; a case can ship its own module files
(the `modules` profile). The station enforces that every section is cited and
every divergence is logged. The log ([`spec/DIVERGENCES.md`](spec/DIVERGENCES.md))
has 29 entries; all but three are resolved, and the open one that is a real decision is D-025 (case conversion beyond ASCII). Non-ASCII names and digits are refused by the
host (decided 2026-11-08); the self-hosted interpreter was brought into line on
nine implementation bugs (scoping, reserved names, duplicate parameters, top-level
control flow, function equality, argument counts, message wording) and on its
imports and `delete`; the integer limit is the language's own, 4,000 digits on
every host (D-012, D-013); floats print by a written rule instead of Python's
`repr` (D-014); and modules start with the same predefined names as a program
(D-018). Two self-hosted differences remain: error headlines, handled by a
documented normalization (D-001), and how one syntax error names a whole float
(D-015). Host failures the spec work exposed are fixed: `print(²)`, `num("²")`,
integers too large for a float, and numbers with thousands of digits leaked a raw
Python exception. Not yet written: packages (`nova.json`, `.nova_modules`), the
type annotations, and the game dialect as profiles (the game's own `host_calls` convention
needs the dialect, not just the embedding profile). The `Reactor-Game` oracle cases (`conformance.json`
in that repository) need those last two, not the host library: they use `func`,
`null`, truthiness, `"n=" + 42` and a six-digit number format
([ADR 0002](decisions/0002-game-dialect-and-profiles.md)), which is M10's work.

**Risks.** Writing the spec will expose undocumented behavior and inconsistent
error text. That cost is the value of the milestone.

## M10 — One language: dialects become profiles

**Goal.** Resolve the split between the official language (`def`, types,
`for`, `try`, f-strings) and the game dialect (`func`, a rule engine, a small
builtin set, division by zero yields 0, no `for` or `try`).

**Decided.** [ADR 0004](decisions/0004-policy-dialect-after-measurement.md)
(accepted 2026-11-08, Option C) supersedes ADR 0002. The game dialect is its own
specified language, the *policy dialect*, that shares NovaLang's corpus format,
runner, profile tags and security stance. It was measured before it was named:
about 60 independent differences from NovaLang plus the rule engine, against the
11 in ADR 0002's tables, and only 12 of the 51 recorded oracle programs agreed
with NovaLang after a purely syntactic translation
([`design/m10-dialect-inventory.md`](design/m10-dialect-inventory.md)).

**Status.** Slices 1 to 3 are done: source, syntax, statements, scopes, calls, modules,
limits and error text (`docs/spec/12-policy-syntax.md`, 23 sections); values, operators
and the 33 built-in functions (`13-policy-values.md`, 18 sections); the game's reference
engine in `dialects/policy/`; and the rule engine (`14-policy-engine.md`, 15 sections); and 710 cases on the game's reference
engine as the `policy` profile, including all 51 of the game's recorded oracle programs. Still to
come, one slice each, ending in a green matrix and a PR: the reactor host contract and the 900-step
reactor trace; then the GDScript host checked against the corpus (`design/m10-gdscript-gaps.md`
lists where it is expected to differ).

**Deliverables**

- The policy dialect specified (`12-` to `14-policy-*.md`), its Python engine
  in the repository (`dialects/policy/`), and the `policy` profile recorded in
  the conformance corpus.
- The `Reactor-Game` and `DaedalusGodot` scripts running either unchanged or
  through a documented, tested migration.
- The GDScript host passing the shared corpus for the profile it implements,
  with unsupported features rejected the same way everywhere.
- The rule engine (`rule`, `fault`, `effects`, `signals`, `held`) specified as
  an extension, not as folklore in a game repository.

**Exit criteria**

- One written answer to "is a game script a NovaLang program", enforced by
  tests.
- No syntax or behavior difference between hosts that is not declared by a
  profile.

## M11 — Security model and sandbox

**Goal.** Let a host run code it does not trust, with stated and tested limits.
NovaSecurity, NovaConnect and NovaAgent are not credible without this.

**Honest starting point.** The `python.*` allowlist is a curated bridge, and
the Python process is not a security boundary. This milestone must not claim
more than it builds; see
[ADR 0003](decisions/0003-security-stance.md).

**Deliverables**

- A written threat model: assets, actors, what is and is not defended.
- A capability model: file read and write (by path), network, clock, environment,
  process, and the Python bridge, each denied by default in a sandbox profile and
  granted explicitly by the embedder. Existing behavior stays available as an
  explicit "trusted" profile so current users are not broken.
- Resource limits enforced identically on both engines: step budget, call depth,
  collection and string size, output size, and wall-clock time. The game port's
  step and depth guards are the precedent.
- A deterministic mode (seeded randomness, no clock) for simulation and replay.
- An optional subprocess runner so isolation does not depend on in-process
  checks alone.
- An escape-attempt station: a corpus of programs trying to exceed capabilities
  and limits, plus fuzzing on top of the existing generated-program harness.
- Independent review of the model before anything is described as a security
  boundary.

**Exit criteria**

- Every capability has a test proving denial and a test proving a grant.
- Every limit has a test that it trips with the specified error on both engines.
- The documentation states exactly what is and is not guaranteed.

**Risks.** CPython offers no strong in-process isolation, so the realistic
claim is capability gating plus resource limits plus an optional process
boundary. Over-claiming here is the main risk to the whole ecosystem.

## M12 — Runtime: bytecode format and performance

**Goal.** Make execution fast, repeatable and portable, and decide, with
evidence, whether a native runtime is warranted.

**Deliverables**

- A versioned bytecode format with a specification, load-time `verify()` (the
  verifier already exists), and a compiled-artifact cache.
- A benchmark suite tracked over time in CI, with regression alerts. Benchmark
  numbers in the README are generated by that suite.
- A profile of where VM time goes, and the next round of targeted fast paths.
- A written evaluation of native or alternative runtimes: what the ecosystem
  would gain, what it would cost, and a recommendation. This milestone ends in
  a decision document, not a new runtime.

**Exit criteria**

- Bytecode produced by one version is accepted or cleanly rejected by another.
- Benchmarks reproducible from one command, in CI.

## M13 — Platform libraries, registry and API stability

**Goal.** Make it safe for other people, and other Nova products, to depend on
NovaLang.

**Deliverables**

- A published list of the stable public API (the language, the standard
  library, the embedding API, the package manifest and lockfile formats), a
  semantic-versioning policy for them, and a deprecation policy.
- A remote package registry protocol, a static-index reference implementation,
  and `nova-pkg publish`, building on the existing lockfile and SHA-256
  integrity checks. Packages declare the capabilities they require (M11).
- Standard-library additions that need the outside world (HTTP, richer time
  zones, structured data validation), each gated by a capability.
- A conformance and compatibility test for packages across NovaLang versions.

**Exit criteria**

- A package can be published, installed from the registry, and verified end to
  end, in a test.
- A breaking change to the declared stable surface fails a test.

## M14 — Product pilots

Products are built in their own repositories on top of the foundation. This
milestone defines when each may start, not what it contains.

A product enters this milestone with a one-page charter stating its owner, the
NovaLang capabilities it needs, the hosts it targets, and its first measurable
outcome. Entry also requires the prerequisites below.

| Product (from the vision graphic) | Needs before starting | Precedent today |
| --- | --- | --- |
| NovaDrive | M8, M10 | External source to integrate; reproducible build and independent numerical reference checks first |
| NovaSim | M10, M12 | The reactor and Daedalus simulations |
| NovaAgent | M11, M13 | None |
| NovaSecurity, NovaConnect | M11, M13 | None |
| NovaHome, NovaLife, NovaWear | M11, M12, M13 | None; device hosts are unevaluated |
| NovaOS, NovaDesk, NovaMobile, NovaFinance | M13 and a per-product charter | None |

Products with no precedent stay on the horizon until a charter exists. Nothing
in this roadmap commits to building them.

---

## Decisions needed

| # | Decision | Needed by | Record |
| --- | --- | --- | --- |
| 1 | Is the written specification or the reference implementation normative? | Start of M9 | [ADR 0001](decisions/0001-specification-is-normative.md): **accepted**, the specification |
| 2 | How the game dialect relates to NovaLang | Start of M10 | [ADR 0002](decisions/0002-game-dialect-and-profiles.md): **accepted**, a profile; **re-opened** by measurement, see [ADR 0004](decisions/0004-policy-dialect-after-measurement.md) (proposed) |
| 3 | What NovaLang claims about security | Start of M11 | [ADR 0003](decisions/0003-security-stance.md): **accepted**, capability gating and limits, not isolation |
| 4 | Python support floor | M7 | Decided in M7 by what CI shows |

## Maintaining this document

Update it in the same pull request that finishes or re-scopes a milestone:
change the status table, move the state described under "Where we are", and
record why in the changelog. A milestone that changes scope after starting gets
a dated note here rather than a silent edit.
