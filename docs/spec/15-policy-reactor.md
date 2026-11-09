# 15. The policy dialect: the reactor host

`14-policy-engine.md` says what the rule engine does with whatever host drives it. This
chapter says what **one particular host**, the reactor game's, gives the engine and takes from
it. That contract is what the shipping policy (`godot/scripts/reactor_rules.nova` in the game's
repository) is written against, and it is what the Python reference host (`reactor_host.py`) and
the Godot bridge (`nova_bridge.gd`) both implement. It is specified here, as folklore in neither,
and the corpus selects it with `"host": "reactor"` in a case's `engine` field.

The plant itself is not part of this chapter. The physics (a fixed-step integration of the core)
and the drives that move the rods produce the **measurements** a policy reads; a case supplies
them as inputs, recorded from the reference host, and the engine is checked on what it does with
them.

## [pol.host-reactor] What the reactor host is

A reactor host runs the engine once per physics step (0.05 s) of a simulated plant. Each step it:

1. moves the rods and integrates the core, which gives the measurements;
2. builds the inputs of `[pol.host-inputs]` and calls `tick(dt, inputs, faults_enabled, overrides)`, where
   `overrides` holds the values the operator is forcing by hand (the game's manual valve positions
   `flow_frac` and `load_frac`, when set) and is otherwise empty (`[pol.overrides]`);
3. if the tick succeeded, reads the policy's outputs back (`[pol.host-inputs]`, "Read back") and
   does the bookkeeping of `[pol.host-latch]`;
4. if the tick failed, stops the step there: the error is shown to the operator (`CONTROL LOGIC
   FAULT -- ` and the error), and **none of the bookkeeping of step 3 happens**.

The policy talks to the host through eight **host functions** (`[pol.host-functions]`), which are
ordinary host functions in the sense of `[pol.calls]`: a variable of the same name does not hide
them, and a function the program defines with the same name does.

## [pol.host-inputs] What the policy is given and what it hands back

On every tick the host sets these globals (`[pol.tick]`), besides `dt`:

| Name | Meaning | From |
| --- | --- | --- |
| `t` | simulated seconds since the start | plant |
| `flux_pct` | neutron flux, 100 is rated power | plant |
| `fuel_temp_c`, `mod_temp_c`, `out_temp_c` | fuel, moderator and outlet temperatures, °C | plant |
| `pressure_mpa` | primary pressure | plant |
| `reactivity_pcm` | total reactivity | plant |
| `decay_heat_pct` | decay heat, 0 unless scrammed | plant |
| `rod_a`, `rod_b` | actual rod bank positions, % withdrawn | plant |
| `rod_target_a`, `rod_target_b` | where the operator (or the policy) wants the banks | host |
| `operator_scram` | `true` on the tick the operator presses SCRAM and `false` otherwise (a case that leaves it out gets `false`; any other value is turned into a boolean) | operator |
| `scram` | is the plant latched in SCRAM | host (`[pol.host-latch]`) |
| `scram_elapsed` | seconds since the trip, 0 if not scrammed | host |
| `game_over`, `victory`, `meltdown` | the run has ended, and how | host |

**Read back.** After a successful tick the host reads these globals: the effects `flow_frac` and
`load_frac` (fractions of the nominal coolant flow and load), `xenon_pcm`, `stuck_bank` (`"A"`,
`"B"` or `""`), `state` (the operating state as text), and `rod_target_a` and `rod_target_b`, which
the policy may set (an autopilot) and which the host uses as the banks' new targets. A global that is
not defined reads as 1 for the two fractions, 0 for `xenon_pcm`, `""` for `stuck_bank` and
`"STARTUP"` for `state`, and the targets stay where they were.

## [pol.host-functions] The eight host functions

Each call is recorded by the corpus as `name(arguments in display text)` in `host_calls`, whether or
not it has an effect. `reason` and `text` are shown to the operator as an event.

- `log(text)` adds `text` to the operator's event log. No effect on the engine.
- `alarm(level, text)` raises the alarm tier shown on the panel; the highest `level` of a tick
  wins. No effect on the engine.
- `scram(reason)` trips the plant. If the plant is **not already latched** (the input `scram` of this
  tick is false) it records the request and **at once sets the global `scram` to `true`**, so rules
  that run later in the same tick see a scrammed plant. If the plant is latched, it does nothing.
  Calling it twice in one tick does the same thing twice (the plant is not latched until the end of
  the tick).
- `reset_trip()` asks to clear the trip: it records the request and **at once sets the global
  `scram` to `false`**. It does not check whether the plant is latched.
- `meltdown(text)` ends the run badly. If the host's meltdown flag is not yet set it sets it and
  ends the run (below); otherwise it does nothing. The flag was the input `meltdown` at the start of
  the tick and changes inside it, so a second call in the same tick does nothing.
- `victory(text)` ends the run well, in the same way with the host's victory flag.
- **Ending the run** sets the host's game-over flag and, at once, the globals `game_over` (`true`),
  `meltdown` and `victory` (the host's two flags as they now are) and `running` (`false`).
- `inject_fault(name)` starts the fault with that name now (`[pol.fault-api]`), `name` turned into
  text; with no argument it does nothing. A name that is not a declared fault is ignored (the tick
  does not fail). `clear_fault()` ends the active fault.

## [pol.host-latch] The host's bookkeeping between ticks

The host keeps the latch (`scram`), the time it latched, and the three run flags. They start
cleared, and a **reset** clears them again (together with the engine, `[pol.reset]`).

Before each tick the host clears two per-tick marks, "scram requested" and "trip reset requested".
It builds `scram` from the latch, `scram_elapsed` as the tick's `t` minus the time of the latch (0 if
not latched), and `game_over`, `victory` and `meltdown` from the flags. `scram()` sets the first mark,
`reset_trip()` the second.

After a tick that **succeeded**:

- if a scram was requested and the plant is not latched, the plant **latches**: the latch is set and
  its time is this tick's `t`;
- otherwise, if a trip reset was requested and the plant is latched, the latch is **cleared**.

So `scram()` and `reset_trip()` in the same tick on an unlatched plant latch it (the request wins),
although the global `scram` ends the tick `false`; on the next tick the global is `true` again from
the input. After a tick that **failed** nothing is latched or cleared, even if `scram()` ran before the
failure, and the next tick's `scram` input is the old latch.

## [pol.host-trace] The 900-step trace

The game's recorded trace (`godot/scripts/nova/conformance.json`, `reactor_trace`) is the whole
stack in one run: `reactor_rules.nova` driven by a scripted rod program with faults off. The rods
rise to 74 % over 40 s, hold for 2 s, and are then driven to 100 %, which takes the plant through
the states `STARTUP`, `POWER ASCENSION`, `STEADY` and `OVERHEAT` and trips it automatically with a
`SCRAM`. The corpus holds it as a case whose steps are the 900 ticks, with the plant's measurements
as inputs, recorded from the reference host, and whose results are, per tick, the policy's outputs
(`flow_frac`, `load_frac`, `xenon_pcm`, `stuck_bank`, `state`, `rod_target_a`, `rod_target_b`, and
`scram`, `game_over`, `meltdown`, `victory`, `running`) and the host functions it called (58 calls,
all in the last 26 ticks, `alarm`, `log` and `scram`). The host's own inputs are not recorded: they
come from the bookkeeping above, so the trace checks that too.

A second case runs 500 ticks in which the operator presses SCRAM on tick 300: the edge rule
`operator_scram` calls `scram("MANUAL SCRAM INITIATED")` once, and the plant stays scrammed.
