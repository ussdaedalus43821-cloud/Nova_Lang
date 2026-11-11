# 0006: The Founder's Charter as a governance document

Status: **Proposed** on 2026-11-11. The charter it adopts is itself a draft
("Proposed — Not Yet Ratified", awaiting the Founder's signature and legal
review), so this record stays Proposed until the Founder ratifies it. On
ratification, a one-line change marks it Accepted with the date.

## Context

[The Nova Founder's Charter](../governance/001-founder-charter.md)
(NOVA-GOV-001, v0.3, Integrated Founder's Review Draft) was drafted by OpenAI,
as the Visionary / CPO of the Nova AI Team ([`AI_WORKFLOW.md`](../AI_WORKFLOW.md)),
for the Founder's adoption. It sets out:

- the meaning of the name (creation, connection, individual control);
- **Article 0, the Triad of Governance**: authority decides who makes a
  decision, evidence whether it is justified, responsibility whether it is
  carried out;
- founder sovereignty (Article I), vision before commercialization (II),
  evidence over consensus (III), users as the purpose (IV), collaboration
  without surrender (V);
- an **open-core model** (6.1): the language specification, reference
  implementation and conformance corpus under an OSI-approved license, with
  the official ecosystem, registry and commercial applications under the
  Founder's authority;
- **the Nova Engineering Doctrine** (6.2);
- amendment by the Founder (Article VII).

The repository had no governance document; its decisions lived in ADRs and
its engineering rules in `CONTRIBUTING.md`, `docs/ROADMAP.md` and
`docs/AI_WORKFLOW.md`.

## Decision (proposed)

1. Adopt the Founder's Charter as Nova's foundational governance document,
   kept in `docs/governance/`, and link it from the Master Plan.
2. The **Nova Engineering Doctrine** becomes part of the official engineering
   culture. Its three practices come from the Toyota Production System:

   | Charter | Toyota term | Already enforced in this repository |
   | --- | --- | --- |
   | Stop the Line (6.2.1) | *Jidoka*: anyone may halt the line on a defect | A red required check blocks the merge; it is fixed, never skipped, quarantined or loosened (`CONTRIBUTING.md`, "Continuous integration"; `docs/ROADMAP.md`, working agreement item 5; the CI Gate ruleset requires `fast`) |
   | Go and See (6.2.2) | *Genchi genbutsu*: go to the source and observe | Claims in docs are measured, with the command that reproduces them; "no imaginary completion"; M8 stays in progress until a green Godot run is recorded; agreement among AI systems is not verification (`AI_WORKFLOW.md`, rule 5, matching 6.2.2 item 5) |
   | Continuous Improvement (6.2.3) | *Kaizen* | Differential and fuzz testing, the conformance corpus and divergence log, the security escape corpus and coverage matrix, the weekly full CI run |

3. Where the charter and an ADR disagree, the charter governs once ratified;
   ADRs remain the record of individual technical decisions.

## Consistency with the repository

- **License (6.1).** NovaLang is MIT-licensed (`LICENSE`), which satisfies
  6.1's OSI requirement and its example list.
- **Security claims (3.2, 6.2.2).** Consistent with
  [ADR 0003](0003-security-stance.md) and [ADR 0005](0005-m11-profile-defaults-and-scope.md):
  the `restricted` profile is not called a security boundary until an
  independent review has an outcome.
- **AI collaboration (5.1, 6.2.2).** Consistent with `AI_WORKFLOW.md`: the
  Founder decides what merges; AI output passes the same gates.

## Open issues before ratification

These are flagged, not decided. The charter's own closing note says
enforceable protections need legal documents and review.

1. **Equity holders and the Charter (1.2.1).** Anyone granted equity must sign
   an agreement adopting the Charter and acknowledging the Founder's ultimate
   authority. This would apply to seed investors (the pitch deck asks for a
   $6M seed round), and investors may not accept it. Needs counsel before any
   raise.
2. **Trademark (5.3.1).** The charter states that the "Nova" name and logo are
   the Founder's exclusive property. Trademark rights depend on registration
   and use, and "Nova" is a widely used name. Needs a trademark search and
   counsel.
3. **Copyright holder.** `LICENSE` reads "Copyright (c) 2026 NovaLang
   Contributors", while 1.2 and 5.3 describe founder ownership with documented
   provenance. A contributor agreement or a decision on the copyright line may
   be needed.
4. **Naming (6.1).** The charter calls the package registry "NovaForge";
   [`vision/ARCHITECTURE.md`](../vision/ARCHITECTURE.md) uses NovaForge for the
   build toolchain and places the registry in M13. Minor; align on
   ratification.
5. **Version label.** The source file was named v0.2; its content and footer
   are v0.3, which is what is recorded.

## Consequences

- Contributors, human or AI, can cite the Doctrine when they stop a release
  or challenge a claim, and are not penalized for a good-faith hold (6.2.1).
- Material amendments to the charter come with a written explanation (7.2),
  recorded as a new ADR, consistent with how decisions are changed here.
