# M10: where the GDScript port is expected to differ from the policy specification

Status: a working list, written 2026-11-08 while specifying `13-policy-values.md`.
Nothing here has been run: Godot is checked against the corpus in its own slice
(owner's instruction: after the specification is complete). Each item is a place where
reading `godot/scripts/nova/*.gd` and `reference/*.py` shows the two disagreeing with
each other or with the specification. The oracle (51 programs, 900-step trace) passes in
Godot (`parity OK -- 90 checks`, 2026-11-08), so none of these is in it; they are the
edges the new cases reach.

**How to use it.** When the GDScript host runs `tests/conformance/cases/policy-*.json`,
every failure should be one of these or a new finding. Fix the port, not the case.

| # | Behaviour (spec section) | Python engine now | GDScript port (from reading the source) | Case that will show it |
| --- | --- | --- | --- | --- |
| 1 | `int(x)` of a number beyond 64-bit, infinity, NaN (`pol.lib-math`) | unchanged (already whole / non-finite) | `float(int(x))`: GDScript `int()` overflows or is undefined | `policy_conv_int_non_finite`, `policy_conv_int_large` |
| 2 | An infinite or NaN index, `slice` bound, `remove_at` index, `range` argument (`pol.index`) | `expected a finite number, got inf` | `int()` of it: undefined | `policy_index_list_infinity`, `policy_coll_range_infinity`, and the `nan` cases |
| 3 | `num("12abc")`, `num("1_0")`, `num("inf")`, other-script digits (`pol.lib-convert`) | `0` for all | `String.to_float()` reads a leading number out of text and has its own rules for the rest | `policy_conv_num_unreadable_is_zero`, `policy_conv_num_not_words`, `policy_conv_num_unicode_digits` |
| 4 | `upper`/`lower` beyond ASCII (`pol.lib-text`) | full Unicode mapping | per character | not tested (D-033) |
| 5 | Numbers of magnitude 1e22 and above (`pol.num-display`) | exact decimal digits | Godot's own `%.6f`, which may not print the exact digits of a large double | `policy_num_large_whole` stops at `1e22` |
| 6 | `pick`, `rand` sequences (`pol.lib-random`) | Python's generator | Godot's generator | not comparable; the cases test the range only |
| 7 | `floor`, `round`, `pow`, `exp` at the edges (`pol.lib-math`) | now as the specification | `floor`, `round`, `pow` are already the same by reading; `exp` clamps the same way | `policy_math_*` |
| 8 | Dictionary key and module path in messages (`pol.index`, `pol.import`) | now `'text'` | `'%s'` already | `policy_index_dict_missing_key_with_quote` |
| 9 | Rules of equal priority run in written order (`pol.decl-rule`) | Python's sort is stable | `Array.sort_custom` in `nova_parser.gd` is not guaranteed stable, so ties can run in another order | `policy_rules_ties_keep_declaration_order` |
| 10 | An error in a signal (`pol.decl-signals`, D-034) | now the signal's own error | the tree-walker backend (`_tick_tree_walker`) still blames the next rule's condition or loses it; the bytecode backend (`_tick_vm2`) already reports it plainly | `policy_signals_error_*` |
| 11 | The engine reading `t`, a fault duration, `fault_*` parameters as numbers (`pol.engine-errors`, D-035) | `expected a number, got string` | `float(...)` of a string is 0.0 and of `null` is an error or 0 | `policy_fault_duration_not_a_number`, `policy_fault_timing_param_not_a_number`, `policy_fault_time_input_not_a_number` |
| 12 | `inject_fault` of a fault whose duration fails (`pol.fault-api`) | returns false, fault does not start | not read | `policy_fault_inject_duration_error` |
| 13 | `fault_first_min_s` etc. defaults, the draw order at reset (`pol.reset`) | one `uniform` draw at reset | not read | not comparable across generators; cases use equal bounds |

**The Reactor-Game Python reference** (`reference/nova_*.py`) has the Python-side
defects fixed here (D-030 to D-032) and must get the same changes
(`dialects/policy/README.md`, "Changes from the origin"), so the two Python copies and
the GDScript port stay one language. That change is made in the Reactor-Game
repository, and only when the owner says to touch it.

**Also noted, not a divergence.** `range(n)` builds the whole list however large `n` is,
and the step budget does not count what a built-in builds, so `range(1000000000)` can
exhaust a host's memory and a game's frame time before any guard stops it. The
specification says so (`[pol.lib-collections]`); a bound is a decision for the owner, as
it would change what a script can do.
