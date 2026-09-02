#!/usr/bin/env python3
"""test_reactor_logic.py - the testing strategy from the embedding plan,
made concrete: exercise the ported NovaLang logic against the SAME
Reactor class the real game uses, with no pygame involved at all.

Two things this checks, deliberately kept separate:

1. Structural/invariant checks (deterministic, exact-value asserts are
   fine): power clamps to [0, 100], scram() zeroes power and sets the
   flag, the alarm thresholds fire at the documented temperatures.
2. A "golden trace" comparison for the physics, which has real randomness
   (`random()` inside tick()) and therefore CANNOT be asserted against
   exact numbers run to run. Instead this seeds Python's own random
   module and drives the ported logic through many ticks, asserting
   invariants that must hold regardless of the exact jitter each run
   draws (temperature never goes below the floor, power-off means no
   heating), which is the general answer to "how do I test ported logic
   that calls random()": test the invariants the ORIGINAL code was
   supposed to guarantee, not one specific numeric trace.

If you have the original, not-yet-ported Python physics code still
sitting around during the migration, the strongest check is a THIRD kind
- a real golden-trace diff: feed both implementations the identical
sequence of pre-rolled jitter values (pass them in as an argument instead
of letting either side call its own RNG) and assert the resulting temp
sequences match exactly. That is the most reliable way to know a port is
behavior-preserving, not just "seems reasonable" - see the note in
run_golden_trace_template() below for the shape of it.

Run: python3 test_reactor_logic.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nova_bridge import NovaEngine  # noqa: E402
from reactor import Reactor  # noqa: E402


def make_engine():
    engine = NovaEngine(scripts=["reactor_physics.nova", "reactor_control.nova"])
    reactor = Reactor()
    engine.expose("reactor", reactor)
    return engine, reactor


def check(label, condition):
    status = "ok" if condition else "FAILED"
    print("[{}] {}".format(status, label))
    return condition


def test_power_clamps():
    engine, reactor = make_engine()
    reactor.set_power(200)
    engine.call("operator_increase_power")
    ok = check("power clamps to 100 even after increasing past it", reactor.power == 100)
    reactor.set_power(-50)
    ok &= check("Reactor.set_power() itself clamps negative input to 0", reactor.power == 0)
    return ok


def test_scram_zeroes_power_and_sets_flag():
    engine, reactor = make_engine()
    reactor.temp = 3000.0
    result = engine.call("check_reactor")
    ok = check("check_reactor() reports 'scrammed' above 2800C", result == "scrammed")
    ok &= check("scram() sets reactor.scrammed", reactor.scrammed is True)
    ok &= check("scram() zeroes reactor.power", reactor.power == 0)
    return ok


def test_thresholds():
    engine, reactor = make_engine()
    ok = True

    reactor.temp, reactor.power, reactor.scrammed = 2500.0, 80, False
    ok &= check("2500C -> reduced_power", engine.call("check_reactor") == "reduced_power")
    ok &= check("reducing power actually lowers it", reactor.power == 70)

    reactor.temp, reactor.power, reactor.scrammed = 1500.0, 50, False
    ok &= check("1500C, power on -> nominal", engine.call("check_reactor") == "nominal")

    reactor.temp, reactor.power, reactor.scrammed = 200.0, 50, False
    ok &= check("200C with power still on -> cold_alarm", engine.call("check_reactor") == "cold_alarm")

    reactor.temp, reactor.power, reactor.scrammed = 200.0, 0, False
    ok &= check("200C with power off -> nominal (not a false alarm)", engine.call("check_reactor") == "nominal")
    return ok


def test_physics_invariants():
    """No exact-value asserts here - tick() calls NovaLang's random(),
    so the numbers differ every run by design. What must hold regardless
    is the CONTRACT: temp never drops below the 20C floor, and a scrammed
    reactor only ever cools (never reheats) until stopped."""
    engine, reactor = make_engine()
    reactor.temp, reactor.power, reactor.scrammed = 1800.0, 70, False
    floor_held = True
    for _ in range(200):
        engine.call("tick", 0.5)
        if reactor.temp < 20.0:
            floor_held = False
            break
    ok = check("temp never dropped below the 20C floor across 200 ticks", floor_held)

    reactor.scram()
    previous = reactor.temp
    only_cooled = True
    for _ in range(50):
        engine.call("tick", 0.5)
        if reactor.temp > previous:
            only_cooled = False
            break
        previous = reactor.temp
    ok &= check("a scrammed reactor only cooled across 50 ticks, never reheated", only_cooled)
    return ok


def run_golden_trace_template():
    """Not run by default - a template for the strongest form of check,
    useful while the ORIGINAL Python tick() still exists side by side
    with the ported nova/reactor_physics.nova version:

        jitters = [python_random.uniform(-15, 25) for _ in range(n)]

        # old path: call the original Python tick(), passing each jitter in
        # new path: call engine.call("tick", dt, jitter) - a tick(dt, jitter)
        #           variant that uses the given value instead of calling
        #           NovaLang's own random()
        # assert the two temperature sequences match exactly.

    Once the Python original is deleted, this stops being possible (there
    is nothing left to diff against) - which is exactly why it is worth
    running once, right when a piece of logic is first ported, before its
    Python original is removed.
    """
    pass


def main():
    results = [
        test_power_clamps(),
        test_scram_zeroes_power_and_sets_flag(),
        test_thresholds(),
        test_physics_invariants(),
    ]
    print()
    if all(results):
        print("All reactor logic tests passed.")
        return 0
    print("SOME TESTS FAILED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
