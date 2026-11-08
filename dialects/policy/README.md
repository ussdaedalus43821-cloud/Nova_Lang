# The policy dialect engine

The reference engine for the policy dialect ([ADR 0004](../../docs/decisions/0004-policy-dialect-after-measurement.md),
specified in `docs/spec/12-*.md` onwards). It is the language half of the game's
control-policy runtime: the lexer, parser, tree-walking evaluator and VM façade
(with the rule engine).

Origin: `reference/nova_{lexer,parser,evaluator,vm}.py` of the Reactor-Game repository
at commit `fae228deb55c318d65089df34bfe1c549917c170`, copied unchanged. The file
names and the flat imports (`from nova_lexer import ...`) are kept so the
Reactor-Game copy and this one can be diffed.

Rules:

- **The specification is normative** (ADR 0001). This engine is the policy
  dialect's first conforming implementation, not its definition. Where it
  disagrees with `docs/spec/`, the disagreement is a logged divergence
  (`docs/spec/DIVERGENCES.md`, ids `P-nnn`) and, once decided, a fix here.
- **Any change is made here first** and then carried to Reactor-Game's
  `reference/` and to the GDScript port, so the three never drift. A change that
  alters behaviour needs a corpus case.
- It is not NovaLang. `novalang.py` does not import it, and nothing in
  `dialects/policy/` imports NovaLang. The conformance station runs it for the
  `policy` profile only.
