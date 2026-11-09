# 14. The policy dialect: the rule engine

A policy file is more than statements. It also declares the **parameters** of a
control policy, the **signals** computed from what the host measures, the
**effects** it writes back, the **rules** that fire on a condition, and the
**faults** that a scheduler injects. A host loads the file once and then drives it
with `tick`, one control cycle at a time. This chapter says what each declaration
means and what one tick does, in what order. The language they are written in is
`12-policy-syntax.md` and `13-policy-values.md`.

The functions a particular game gives its scripts (`scram()`, `alarm()`, ...) and the
reactor host that supplies them are the next slice of M10 and are not specified here.
Everything in this chapter works with the plain host functions of the cases, which
record their calls and return `null`.

## [pol.engine] The engine and the host's side of it

An **engine** holds one loaded program and its state: the global scope, the timers of
`held`, the flags of each rule, the active fault and the time of the next one, and a
random generator. A host creates it with a generator, may register **host functions**
(`[pol.calls]`) and gives it a way to find modules (`[pol.import]`). Its operations:

| Operation | What it does |
| --- | --- |
| `eval(source)` | parse the program and then `reset(0)`; a syntax error fails before anything runs |
| `reset(seed)` | `[pol.reset]` |
| `tick(dt, inputs, faults, overrides)` | `[pol.tick]`, `[pol.overrides]`; true if the cycle ran without error. `overrides` is optional |
| `call_function(name, args)` | `[pol.host-api]` |
| `get_global(name, fallback)`, `set_global(name, value)` | read or define a global |
| `inject_fault(name)`, `clear_fault()` | `[pol.fault-api]` |
| `drain_output()` | the entries `print` has written since the last drain, and forgets them |
| `describe()` | `[pol.host-api]` |

Each operation that can fail leaves the text of the error in the engine's `error`
(`[pol.engine-errors]`). The corpus drives an engine with a list of steps (the
`engine` field of a case, `tests/conformance/README.md`) and records, after each step,
whether it succeeded, the error, what was printed, which host functions were called,
and the values of the globals the case watches. Cases with an `engine` field are the
examples in this chapter.

```
reactor "DEMO" version 1
params { limit = 5 }
effects { alarm_on = false }
rule over_limit { when x > limit then set alarm_on = true  log("over") }
```

With the input `x = 3` a tick does nothing; with `x = 6` it sets `alarm_on` to true and
calls `log("over")`; the next tick puts `alarm_on` back to false before the rules run.

## [pol.decl-reactor] `reactor`

`reactor "TITLE"` or `reactor "TITLE" version N` gives the policy a name and a version
number, which `describe()` reports (`title`, `version`). The title is a string literal
and the version a number literal, of which the whole part is kept (`version 2.9` is 2).
The declaration is optional (the defaults are `UNNAMED REACTOR` and 1), may be written
anywhere a statement may, and may be repeated: a later title replaces an earlier one,
and a later version replaces an earlier one, but a `reactor` without `version` leaves
the version as it was. It has no effect on a run.

## [pol.decl-params] `params`

`params { name = expr  name = expr ... }` defines **parameters**: ordinary global
variables that a script treats as constants and a tuner changes. There is no separator
between the entries, each name is a plain name (a keyword is refused, `expected 'ident',
got 'label'`), and the block is closed by `}` (`unterminated block` at the end of the
source). A file may have several `params` blocks, which add up.

The expressions are evaluated **when the engine resets** (`[pol.reset]`), after the
program's own top-level statements, in the order written, so a parameter sees the
program's `let`s and the earlier parameters, but the program's top-level statements
cannot see a parameter (`unknown identifier 'p'`). A parameter is a global like any
other: a rule may `set` it, and `reset` restores it. An error in an expression is an
error of the load or reset, `line N: message`.

## [pol.decl-effects] `effects`

`effects { name = expr [persistent]  ... }` defines the variables the policy **writes
for the host to read**. Each has a default, an expression evaluated at reset like a
parameter (after the parameters, so it may use them). At the start of **every tick**
each effect that is not marked `persistent` goes back to its default; a `persistent`
effect keeps whatever value it has. So a rule that sets an effect decides it for one
cycle only, unless the effect is persistent. The inputs the host provides are applied
after the defaults and win over them (`[pol.tick]`). `describe()` lists the effect
names in order.

## [pol.decl-signals] `signals`

`signals { name = expr ... }` defines values **derived on every tick** from the inputs,
the effects and the faults: after the fault scheduler and before any rule, each signal
expression is evaluated in the order written (after the host's overrides, `[pol.overrides]`) and the result assigned to a global of that
name, so a signal sees earlier signals and a rule sees all of them. A signal is a
snapshot for the cycle: a rule that changes a variable the signal was computed from does
not change the signal until the next tick. Blocks add up, and a name defined twice takes
the later expression's value. An error in a signal expression stops the tick, with the
error of that expression's own line (`line 3: unknown identifier 'nope'`), not an error
attributed to a rule.

## [pol.decl-rule] `rule`

```
rule NAME [priority N] [once] [edge] { when expr then statements }
```

`NAME` is any word, a keyword included (`rule if { ... }`). The modifiers may come in any
order and be repeated (the last `priority` wins), and `N` is a number literal: a sign is
not part of a literal, so `priority -1` is `expected 'number', got '-'`, and the default
is 0. Both `when` and `then` are required, and the statements after `then` may be none.

Rules are ordered by **priority, highest first; rules with the same priority keep the
order in which they are written**. `describe()` lists the rule names in that order.

## [pol.decl-fault] `fault`

```
fault NAME [weight N] [duration expr] [label "TEXT"] { statements }
```

A fault is a named disturbance the scheduler (or the host) can switch on for a while.
`NAME` is any word. The modifiers may come in any order. `weight` is a number literal
(default 1) that sets how likely the scheduler is to pick it; `duration` is an
**expression**, evaluated each time the fault starts (default 30), in seconds; `label` is
a string (default: the name with each `_` replaced by a space, in upper case, so
`rod_stuck` is `ROD STUCK`). The statements are the **body**, run once per tick while the
fault is active (`[pol.fault-schedule]`).

## [pol.reset] Reset

`reset(seed)` puts the engine into its starting state and runs the load. In this order:

1. If `seed` is not 0, the engine's random generator is reseeded with it; 0 leaves the
   generator as it is.
2. The global scope is replaced by an empty one, the timers of `held` are zeroed (there is
   one per call of `held` in the text, `[pol.held]`) and the output buffer is emptied.
3. The program's top-level statements run, in order.
4. The `params` expressions are evaluated and assigned.
5. The `effects` defaults are evaluated, remembered, and assigned.
6. Every rule's fired and was-true flags are cleared (`[pol.rule-fire]`).
7. No fault is active, and the time of the first scheduled fault is drawn: a random number
   from `fault_first_min_s` up to `fault_first_max_s`, two globals (normally parameters)
   that default to 45 and 90.

An error in any step stops the reset and is its result (`reset` returns false). After a
reset the global scope holds only what steps 3 to 5 made: **the inputs of earlier ticks
are gone**, and so is anything a rule created (`made` is `null`). `eval` is a parse
followed by `reset(0)`, so the first load is a reset.

## [pol.tick] One control cycle

`tick(dt, inputs, faults_enabled, overrides)` runs one cycle. `dt` is the number of seconds the cycle
stands for, `inputs` a set of named values from the host and `overrides` (optional, none by
default) a second set of named values that the host forces (`[pol.overrides]`). In this order:

1. The guards of `[pol.limits]` start from zero, and `dt` is remembered for `held`.
2. Every effect that is not `persistent` is set to its default.
3. The globals `dt` and one for each input are set (an input replaces what the effect
   default or an earlier tick left).
4. `active_fault`, `fault_label`, `fault_elapsed` and `fault_duration` are defined, as
   `""`, `""`, 0 and 0, if they are not yet.
5. The fault scheduler runs, and then the body of the active fault, if any
   (`[pol.fault-schedule]`).
6. The overrides are set as globals (`[pol.overrides]`).
7. The signals are evaluated in order.
8. The rules are tried in order (`[pol.rule-fire]`).

The tick succeeds if nothing failed. What the host reads afterwards is the globals (the
effects, above all), the host functions that were called, and the output. **The engine
reads the global `t`, the time in seconds, as "now"** (0 if the host gave none); it must
be a number, or the tick fails with `expected a number, got string`.

## [pol.overrides] Overrides

`overrides` is how a host puts its hand on a value whatever the policy and the active fault
say: the operator holding a valve open, a test forcing a measurement. Each name in it is
set as a global with its value, exactly as an input is (`tick` step 3), but **later**: after
the fault scheduler and the fault body (step 5) and before the signals (step 7). So:

- An override **beats a fault**. A fault body that sets the same name has run already, and the
  override replaces what it set.
- **Signals and rules see the overridden value**, so every condition that reads it sees the plant
  as the host says it is.
- An override replaces whatever the name held: the effect's default, an input of the same name,
  the value a fault set, or what an earlier tick left in a `persistent` effect.
- An override is **not a lock.** It is a value set before the signals and the rules run. A rule
  whose body sets the name changes it for the rest of the cycle, and a signal with the same name
  is evaluated after the override and replaces it. The host that wants the value held passes it
  again on every tick.
- Overrides are **not remembered.** A name that is not overridden on the next tick is back to
  what the effect's default, the inputs and the policy make it (a `persistent` effect keeps the
  value it was last left with, which is the override's value if nothing set it since).
- The engine reads the global `t` for the fault scheduler in step 5, before the overrides: an
  override of `t` reaches the signals and the rules but not the scheduler.
- A name the program never declared is defined by the override like any other global. An empty
  or missing `overrides` changes nothing, and the cycle is then the one of `[pol.tick]` without
  step 6.

```
reactor "DEMO" version 1
effects { valve = 0.5 }
signals { open_enough = valve >= 0.4 }
fault stuck { duration 5  body { set valve = 0.0 } }
```

With the fault `stuck` active, a tick without overrides ends with `valve` at 0.0 and
`open_enough` false; the same tick with the override `valve = 0.9` ends with `valve` at 0.9 and
`open_enough` true.

## [pol.rule-fire] When a rule fires

For each rule, in order:

- A rule marked `once` that has fired is skipped for good (until a reset), and its
  edge memory is cleared.
- Otherwise its condition is evaluated and its truthiness taken (`[pol.truthiness]`).
- The rule **fires** if the condition is true, and, for an `edge` rule, was false the
  last time the rule was tried: `edge` means "on the tick the condition becomes true". An
  `edge` rule whose condition is already true on the first tick fires on that tick. The remembered value is
  updated to the new condition whether or not the rule fired.
- Firing marks the rule as fired and runs its statements in a new scope below the globals:
  a `let` there is local to the body, a `set` of an unknown name makes a global (`[pol.assign]`),
  and `return` or `break` end the body, not the tick.

Rules run one after another in the same cycle, so a later rule's condition sees the globals
an earlier rule's body set. A rule condition may have side effects (a call to a function that
prints or calls the host). `once` and `edge` combine: a `once edge` rule fires the first time
the condition is true and never again.

## [pol.held] `held(condition, seconds)`

`held(cond, seconds)` is a timer for "this has been true for long enough". It looks like a
function call and is a **special form**: unless a *function* is bound to the name `held`
(`[pol.calls]`), a call is handled by the engine, which evaluates its arguments itself.

Each place in the program text where `held` is called has **its own timer**, zero at a reset.
When the call is evaluated: if `cond` is true (`[pol.truthiness]`) the timer grows by `dt`, the
seconds of the current tick; otherwise the timer returns to zero; and the call is `true` when
the timer has reached `seconds` and `false` otherwise. So with a tick of 0.05 s, `held(x > 0,
0.15)` first becomes true on the third tick in a row with `x > 0`, and stays true while
`x > 0`. The timer advances **only when the call is evaluated**: in `x > 0 and held(...)` it
does not move on ticks where `x > 0` is false (it keeps its value), which is how a guard
"pauses" it. Its arguments are the condition and a number of seconds (`expected a number, got
string`); another number of arguments is `held(cond, seconds) takes 2 argument(s), got 1`. A
call of `held` inside a function or a signal has its own timer like any other. Timers count
sums of `dt` as 64-bit floats, so `0.05 + 0.05 + 0.05` is `0.15000000000000002`, and the
comparison `>=` is exact.

Timers are numbered by the order of the calls in the *main* program's text. A call to `held`
in an imported module has its own numbering and is not supported.

## [pol.fault-schedule] Faults and their scheduler

On every tick, if no fault is active and the host enabled faults (`faults_enabled`) and the
time `t` has reached the time of the next scheduled fault, the scheduler **starts one**,
chosen at random with probability proportional to its weight; faults whose weight is zero are
never chosen, and if there are none with a positive weight nothing starts. To start
a fault, the engine:

1. works out the time `t` and the fault's `duration` expression (an error here, or either not
   being a number, fails the tick and the fault does **not** start);
2. makes the fault active and sets the globals `active_fault` (its name), `fault_label`,
   `fault_elapsed` (0) and `fault_duration`;
3. calls the host function `log` with `"ALARM: "` and the label, if the host registered one.

While a fault is active, each tick sets `fault_elapsed` to `t` minus the time it started; if
that has reached `fault_duration` the fault **ends**; otherwise its body runs (after the
inputs and effect defaults of the tick, before the signals). Ending a fault calls `log` with
the label and `" CLEARED"`, resets the four globals to `""`, `""`, 0 and 0, and schedules the
next one: `t` plus a random number from `fault_gap_min_s` to `fault_gap_max_s`, two globals
(normally parameters) that default to 45 and 90. The body does not run on the tick that ends
the fault. Because effects return to their defaults at the start of every tick, whatever a
fault body sets lasts exactly as long as the fault.

The **times are drawn from the engine's random generator**, so which tick a scheduled fault
starts on depends on the generator, and a fault picked among several with positive weights
too. Equal minimum and maximum make the draw certain (`fault_first_min_s = fault_first_max_s =
1.0` starts the first fault at `t = 1`); with the defaults and at least one fault of positive weight, a tick at `t` below 45 never starts
a fault and one at `t = 90` or later always does (`[pol.lib-random]`).

## [pol.fault-api] Starting and ending a fault from outside

`inject_fault(name)` starts the fault with that name now, as the scheduler would, whatever the
time and whether or not the scheduler is enabled; with a name that is not declared it fails
with `no such fault 'nope'` and starts nothing. If a fault is already active, it does nothing
and succeeds. If the fault's duration cannot be worked out, it fails with that error and starts
nothing. `clear_fault()` ends the active fault as the scheduler would (the `CLEARED` message,
the globals back, the next fault scheduled from now) and does nothing if none is active. A
host function may call them from inside a rule, which is how a game's `inject_fault(name)`
works.

## [pol.host-api] Calling in, setting, describing

- `call_function(name, args)` calls the global function `name` with the arguments, with the
  guards of `[pol.limits]` starting from zero for that call, and returns its value. A name
  that is not defined is `no such function 'nope'`; one that is not a function is `'z' is
  not a function`; a wrong number of arguments is `f() takes 1 argument(s), got 0`; any
  error of the function is `line N: message`. Output and host calls it makes are the engine's
  as usual, and it sees the globals as the last tick left them. A function that returns
  nothing returns `null`.
- `set_global(name, value)` defines or replaces a global. The next tick's inputs replace it
  if they have the same name.
- `get_global(name, fallback)` reads one (`fallback`, or `null`, if it is not defined).
- `describe()` reports `title`, `version`, and the names of the `params`, `effects` and
  `signals` in order, the `rules` in priority order, the `faults`, the number of top-level
  `statements`, the `exports`, and `held_slots`, the number of `held` calls in the text.

## [pol.engine-errors] Errors in the engine

An error stops the operation it happens in and is its result; the engine remains usable, and
the next tick or call starts its guards from zero. The texts:

- **During a reset or load:** the error of the statement or expression, `line N: message`.
- **In a signal, or the body of a fault, or a fault's duration:** `line N: message`, with the
  line inside that expression or body.
- **In a rule's condition or body:** `rule 'name': line N: message`, the rule's name quoted
  plainly. The effects and variables set by earlier rules in the same tick stay set.
- **In a function called by a rule,** the same, with the line inside the function.
- **From the engine's own reading of a number** (the time `t`, a fault's duration, or the
  timing parameters `fault_first_*` and `fault_gap_*`): `expected a number, got string` (no
  line).
- **From the budget:** the step budget and call depth limit of `[pol.limits]` count per
  tick, per call and per load, not per program: `rule 'r': line 1: step budget exhausted
  (500000) -- runaway loop?`.

A failed tick may have fired some rules and called some host functions before it failed; those
stay done. The engine does not roll anything back.
