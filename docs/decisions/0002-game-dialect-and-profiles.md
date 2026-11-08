# 0002: How the game dialect relates to NovaLang

Status: **Superseded** by [0004](0004-policy-dialect-after-measurement.md) on
2026-11-08. It was accepted on 2026-11-07; measuring the dialect at the start of M10
met its own reconsideration triggers. The text below is kept as it was.

## Context

The two game repositories run a language that looks like NovaLang but is not
the language `novalang.py` runs. It was measured against v2.0.1, not assumed.

Syntax:

| | NovaLang 2.0.1 | Game dialect |
| --- | --- | --- |
| Function keyword | `def` | `func` |
| Loops | `while`, `for ... to`, `for ... in` | `while` only |
| Errors | `try`/`catch`/`finally`, `throw` | none |
| Strings | f-strings, slicing | concatenation with `+` |
| Types | optional annotations | none |
| Extra declarations | none | `reactor`, `params`, `effects`, `signals`, `rule`, `fault`, `set`, and the `held()` timer |

Semantics (the harder part):

| | NovaLang 2.0.1 | Game dialect |
| --- | --- | --- |
| `1 / 0`, `7 % 0` | error | `0` |
| `if 1 { }`, `if "" { }` | error: condition must be true or false | truthiness (`0`, `""`, `[]`, `{}`, `null` are false) |
| `"a" + 1` | error | `"a1"` |
| Missing list index or dict key | error | error |
| Runaway code | call-depth limit (1200); no step or time limit, so `while true { }` never stops | call-depth limit (128) and a per-tick step budget (500,000) |

The dialect has its own Python reference, a recorded oracle (51 programs plus a
900-step reactor trace), and a GDScript implementation checked against it. Every
shipped game script is written in it.

## Options

**A. Profiles of one language.** NovaLang defines a small, enumerated set of
profile switches (keyword aliases, total division, truthiness, string coercion,
the rule-engine declarations as an extension). The game dialect is the "policy"
profile. One spec, one corpus with profile tags, one set of tools.

**B. Migrate the games to the official language.** Rewrite game scripts to
`def`, explicit booleans and explicit string conversion; implement the rule
engine as a host library over the core language. One semantics, but every
script, the oracle and its goldens change, and behavior in the games can shift.

**C. Keep the dialect as a separate, named language** that shares code with
NovaLang but is specified and versioned on its own. Least disruption now; the
ecosystem then has two languages to document, tool and secure.

## Recommendation

Option A, limited to the differences in the tables above, each one a named,
individually tested switch. It preserves the games and their parity harness,
keeps one corpus and one security model, and makes the cost visible: the
profile list is the dialect's entire surface.

Reconsider (toward C) if the switch list grows beyond what can be tested
exhaustively, or if a switch would change the meaning of existing official
programs. Option B is attractive only if the project wants the games to become
ordinary NovaLang programs more than it wants them to keep their present
behavior.

## Consequences

- The conformance corpus gains profile tags; each host declares the profiles it
  implements.
- The GDScript port is checked against the shared corpus for its profile.
- The rule engine is specified as an extension.
- Existing game scripts keep working under A or C; under B they are migrated.

## Decision

Accepted as recommended, by the project owner, on 2026-11-07: Option A. The game
dialect becomes a "policy" profile of NovaLang, defined as a small enumerated
list of switches (keyword aliases, total division, truthiness, string
coercion, the rule-engine declarations as an extension). Each switch is named
and individually tested, and the list in the Context tables is the dialect's
entire surface.

The reconsideration triggers in the Recommendation stand: revisit toward
Option C if the switch list grows beyond what can be tested exhaustively, or
if a switch would change the meaning of existing official programs. A change
of course is a new record that supersedes this one.
