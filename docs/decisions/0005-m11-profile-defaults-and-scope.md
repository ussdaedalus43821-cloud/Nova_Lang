# 0005: M11 defaults, scope and review

Status: **Accepted** on 2026-11-08 by the project owner, in answer to the four questions at the end
of the [M11 plan](../design/m11-security-plan.md), plus the review label.

## Context

[ADR 0003](0003-security-stance.md) chose capability gating and resource limits, not isolation. The
plan for M11 left four decisions open: what an embedded `Nova()` does by default, whether the limits
apply to the `trusted` profile, whether the self-hosted interpreter takes part, and who reviews.

## Decision

1. **Defaults.** An embedded `Nova()` stays `trusted`; `restricted` is opt-in (`Nova(profile="restricted",
   ...)`). **`restricted` becomes the default in a future 3.0 release**, announced in the changelog before
   it happens. The command line stays `trusted` by default, and `--profile restricted` is how an
   untrusted script is run.
2. **Limits.** The step budget, the time limit and the output limit apply to `restricted` only. A
   long-running trusted program is legitimate and is not killed. The fixed size and depth limits of
   `[port.limits]` apply in both profiles, as they do today.
3. **Self-hosted interpreter.** Every capability and limit lands there in M11. It is a reference
   implementation of the specification, security included, and a coverage-matrix cell is needed on it
   like on the other two engines.
4. **Review.** The project owner is the primary reviewer for now. Slice 8 prepares the package for an
   independent reviewer, and **every document says "owner-reviewed, pending independent third-party
   audit"**, never more.

## Consequences

- `16-sandbox.md` `[sbx.profiles]` states 1 and 2; the plan's slice order stands; the coverage matrix
  (`tests/security/`) has a cell for each engine, the self-hosted one included, and turns strict at the
  end of M11.
- A 3.0 release that flips the default is a breaking change and needs its own decision when the time comes.
- Practice proposed by the author of this record, **not** part of the owner's decision: a document carries
  the label "owner-reviewed" once the owner has read that text. Until then the slice 1 documents say
  "draft, owner review pending". The owner can change this by editing the status lines.
- No document describes `restricted` as a sandbox guarantee, as safe, or as a security boundary until the
  matrix is fully covered and an independent reviewer has read the threat model.
