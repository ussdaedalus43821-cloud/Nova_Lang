# The policy dialect engine

The reference engine for the policy dialect ([ADR 0004](../../docs/decisions/0004-policy-dialect-after-measurement.md),
specified in `docs/spec/12-*.md` onwards). It is the language half of the game's
control-policy runtime: the lexer, parser, tree-walking evaluator and VM façade
(with the rule engine).

Origin: `reference/nova_{lexer,parser,evaluator,vm}.py` of the Reactor-Game repository
at commit `fae228deb55c318d65089df34bfe1c549917c170`, copied unchanged and then changed
only where the specification required it (below). The file
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

## Changes from the origin

Each is a divergence the specification found (`docs/spec/DIVERGENCES.md`), fixed here
first. **The same changes have to reach Reactor-Game's `reference/` and the GDScript
port**, which the corpus will then check (`docs/design/m10-gdscript-gaps.md`).

| Divergence | Change |
| --- | --- |
| (limit) | No list may hold more than 1,000,000 items: `MAX_LIST_ITEMS`, checked by `range`, `append` and list `+` (`nova_evaluator.py`); a decision of the owner, not a divergence. |
| (limit) | No string may have more than 1,000,000 characters: `MAX_STRING_CHARS`, `text_checked` (a budgeted `text`) and `Evaluator._etext`; a decision of the owner. |
| D-030 | Messages quote names, keys and module paths as `'` text `'`, not with Python's `repr` (`nova_evaluator.py`, `nova_vm.py`). |
| D-031 | `floor`, `round`, `int` return infinity and NaN unchanged; `pow` is C `pow` (`c_pow`); index, `slice`, `remove_at` and `range` arguments go through `_int`, which refuses infinity and NaN with `expected a finite number, got inf`. |
| D-032 | `num("text")` reads the one grammar of `[pol.lib-convert]` (`read_number`). |
| D-034 | An error in a signal stops the tick as the signal's own error (`nova_vm.py`, `_tick`). |
| D-035 | The engine's own reads of a number (`t`, a fault duration, the `fault_*` timing parameters) go through `_number`/`_as_number` and fail with an ordinary error; a fault starts only once its duration is known; `inject_fault` reports the error. |
