# NovaLang roadmap

This is the plan for taking NovaLang from a well-tested language implementation
to the foundation of a wider Nova ecosystem. It continues the milestone
numbering already used in the history (M0 toolchain through M6 fast paths; see
`CHANGELOG.md`).

It is a plan, not a promise. Milestones are ordered by dependency, not by date,
and carry no calendar commitments. Anything that needs a decision from the
project owner is marked **Decision** and has a proposed record in
[`decisions/`](decisions/README.md).

Last reviewed against NovaLang v2.0.1 plus the "Unreleased" changelog entry.

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

Established, with evidence (the full suite is 1,919 checks, all passing):

- One language implemented three ways that must agree: the Python bytecode VM
  (default), the Python tree-walker (reference), and `novalang.nova`
  (self-hosted). A differential station requires byte-identical output.
- A formatter, linter, gradual type checker, package manager with a lockfile,
  and an LSP server with a VS Code extension.
- Regression stations for the command line, the embedding API, the REPL and
  malformed input.

Not established:

- **No continuous integration.** Every verification so far was run by hand, on
  one or two machines. The advertised Python 3.7+ range and non-Mac platforms
  are untested.
- **The GDScript port is unverified.** The bytecode VM for Godot is written and
  pushed, but has not yet been run against its parity harness.
- **There is no specification.** The Python implementation is the definition of
  the language, and the games run a different dialect (`func`, a rule engine,
  no `for` or `try`).
- **No security boundary.** `python.*` is a curated bridge, not a sandbox, and
  resource limits exist only in the game port.
- No native backend, no remote package registry, no public API stability policy.

## Milestone overview

| # | Milestone | Status | Needs | Size |
| --- | --- | --- | --- | --- |
| M0–M6 | Toolchain, typing, packages, editor, bytecode VM, fixes, fast paths | Done | | |
| M7 | Continuous verification | Planned | | M |
| M8 | Verify and finish the GDScript VM | In progress | M7 for CI | M |
| M9 | Language specification and conformance corpus | Planned | M7 | L |
| M10 | One language: dialects become profiles | Planned, **Decision** | M8, M9 | L |
| M11 | Security model and sandbox | Planned, **Decision** | M9 | XL |
| M12 | Runtime: bytecode format and performance | Planned | M9 | L |
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
  draft, `help` transcript, Ctrl-C.
- Windows-specific fixes the matrix exposes (paths, newlines, `chmod`).

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

**State.** `NovaVM2`, the resolver and the compiler are written in
`Reactor-Game` and pushed, with a dual-backend parity check. They have not been
run in Godot.

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

**Decision.** Which is normative when they disagree: the spec or the reference
implementation. Proposed in
[ADR 0001](decisions/0001-specification-is-normative.md).

**Risks.** Writing the spec will expose undocumented behavior and inconsistent
error text. That cost is the value of the milestone.

## M10 — One language: dialects become profiles

**Goal.** Resolve the split between the official language (`def`, types,
`for`, `try`, f-strings) and the game dialect (`func`, a rule engine, a small
builtin set, division by zero yields 0, no `for` or `try`).

**Why a decision.** The options are mutually exclusive and each has a cost to
existing code and to the parity harness. See
[ADR 0002](decisions/0002-game-dialect-and-profiles.md) for the options and a
recommendation; nothing is built until that is accepted.

**Deliverables (once decided)**

- The chosen mechanism implemented in the Python engine (for example a named
  profile selecting syntax aliases and the rule-engine declarations), with the
  profile recorded in the conformance corpus.
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
| 1 | Is the written specification or the reference implementation normative? | Start of M9 | [ADR 0001](decisions/0001-specification-is-normative.md) |
| 2 | How the game dialect relates to NovaLang | Start of M10 | [ADR 0002](decisions/0002-game-dialect-and-profiles.md) |
| 3 | What NovaLang claims about security | Start of M11 | [ADR 0003](decisions/0003-security-stance.md) |
| 4 | Python support floor | M7 | Decided in M7 by what CI shows |

## Maintaining this document

Update it in the same pull request that finishes or re-scopes a milestone:
change the status table, move the state described under "Where we are", and
record why in the changelog. A milestone that changes scope after starting gets
a dated note here rather than a silent edit.
