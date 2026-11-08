# 0004: The policy dialect, after measuring it

Status: **Accepted** on 2026-11-08 (Option C). Written the same day at the start
of M10. Supersedes [0002](0002-game-dialect-and-profiles.md).

## Context

ADR 0002 accepted Option A: the game dialect becomes a "policy" profile of
NovaLang, a small enumerated list of individually tested switches, with "the list
in the Context tables" as its entire surface. It also wrote down when to
reconsider: if the list outgrows exhaustive testing, or a switch changes the
meaning of existing official programs.

M10's first task was to turn that list into switches. Counting it first
([`docs/design/m10-dialect-inventory.md`](../design/m10-dialect-inventory.md)):

- The tables held 11 differences. Measured against the game's own lexer, parser,
  evaluator, VM and host, the dialect differs from NovaLang 2.1.0 in about **60
  independent behaviours** (5 lexical, 11 syntax, 15 values and operators, about
  25 builtins, 4 limits/error rules) plus the rule engine.
- Translating the 51 recorded oracle programs to NovaLang by **syntax alone**,
  the most generous translation, only **12 (24%)** then print the same output.
  Twelve more cannot be written in NovaLang at all (`null`, anonymous
  functions, computed dict keys, bare `import`).
- Several differences are not missing features but opposite meanings of the same
  text: `//` is a comment in the dialect and the division operator in NovaLang;
  `{ let x = 2 }` is a block in one and a failing dict literal in the other;
  each side's reserved words are the other side's legal names.
- The switches are not independent. Newline-free statements (S2), truthiness
  (V2) and number display (V7) sit in the lexer, parser and formatter that every
  official program also passes through, in three engines.

Both reconsideration triggers are, to different degrees, met: the first plainly;
the second only as a *risk* (no official program changes meaning while `core` is
the default, but 1,925 checks would depend on a lexer and parser carrying a
second grammar).

## Options

**A. Keep Option A as accepted.** About 60 switches inside the tree, VM and
self-hosted engines, behind a `policy` profile. Honours ADR 0002 to the letter.
Cost: three engines each gain a second lexer/parser/number-formatter mode and the
whole builtin table gets a second definition; the testable unit is the bundle,
not the switch, so "each switch individually tested" cannot be literally true;
every future change to core has to be checked against the bundle.

**C. The policy dialect is its own specified language that shares the project's
tooling.** One repository, one conformance format, one runner, one security
stance (ADR 0003), one set of profile tags, but the dialect has its own spec
chapter(s) (written as a complete description plus a table of differences from
core, so a reader can see both), its own engine, and a `policy` corpus profile.
The engine is the game's reference (four Python files, about 900 lines, already
the oracle the GDScript port is checked against), kept in this repository. Core's
three engines report `policy` cases as NOT APPLICABLE exactly as they already do
for `embedding`; the GDScript host declares the `policy` profile and is checked
against the same JSON. The 51 oracle programs and the 900-step trace become
corpus cases, the first time the game's behaviour is under the spec station's
rules (every case cites a section, every section is cited, divergences are
logged).

**B. Migrate the games to core NovaLang.** Needs anonymous functions, a `null`
literal, truthiness and several builtins in core or in a library, rewrites every
game script, and changes the oracle and its 900-step trace. 12 of 51 programs
agree today. Attractive only if the project wants the games to become ordinary
NovaLang more than it wants them unchanged.

## Recommendation

**Option C**, with the sharing in the previous paragraph made explicit. It keeps
the things ADR 0002 wanted from A (one corpus, one runner, profile tags, hosts
declaring profiles, the GDScript port checked against shared cases, the rule
engine specified) without putting a second grammar into the engines every
official program depends on. It costs maintaining two implementations, but one of
them already exists, is the oracle the game is tested against, and does not
change when core does.

If the owner prefers A, the first step would be the smallest self-contained
group (L1-L4, S1-S6, S9) behind one front-end flag, with the measured count above
as the budget.

## Consequences if C is accepted

- ADR 0002 becomes **Superseded** by this record.
- ROADMAP M10 is reworded: "profile switches" becomes "the policy dialect
  specification and its engine"; the deliverables otherwise stand (spec chapter,
  corpus, GDScript host passing the shared corpus, no undeclared host
  differences, game scripts unchanged).
- Work, in order: (1) the lexical and syntax chapter of the dialect; (2) values,
  operators and the builtin table; (3) the rule engine; (4) the oracle programs
  and trace as corpus cases; (5) the engine brought into this repository and run
  by the station. Each slice follows the M9 loop and ends in a green matrix and a
  PR.
- Godot remains paused until the owner has run `nova_compiler_test.gd` and
  `parity_check.gd` on the Mac.

## Decision

Accepted as recommended, by the project owner, on 2026-11-08: Option C.

1. ADR 0002 is superseded by this record.
2. The game dialect is its own specified language. It shares the corpus format, the
   runner, the profile tags and the security stance ([ADR 0003](0003-security-stance.md))
   with NovaLang.
3. M10 proceeds under Option C: write the specification of the policy dialect,
   bring the game's Python reference engine into this repository
   (`dialects/policy/`), and convert the 51 oracle programs and the 900-step
   reactor trace into corpus cases under the `policy` profile.
