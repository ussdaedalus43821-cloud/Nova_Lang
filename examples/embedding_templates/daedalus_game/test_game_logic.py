#!/usr/bin/env python3
"""test_game_logic.py - drives nova/game_logic.nova through many frames
with no pygame at all, using synthetic input dicts exactly like the ones
main.py builds from real pygame key state - the same golden-trace-style
strategy as reactor_game/test_reactor_logic.py, adapted to a system with
an authoritative NovaLang-side list instead of an exposed Python object.

Run: python3 test_game_logic.py
"""
import sys

from nova_bridge import NovaEngine

NO_INPUT = {"left": False, "right": False, "up": False, "down": False}


def check(label, condition):
    print("[{}] {}".format("ok" if condition else "FAILED", label))
    return condition


def make_engine():
    return NovaEngine(scripts=["enemy_waves.nova", "game_logic.nova"])


def test_player_moves_with_input():
    engine = make_engine()
    state = engine.call("update", 1.0, {"left": False, "right": True, "up": False, "down": False})
    ok = check("player.x increases when 'right' is held", state["player_x"] > 10.0)
    ok &= check("player.y unchanged when only 'right' is held", state["player_y"] == 5.0)
    return ok


def test_wave_spawns_after_delay():
    engine = make_engine()
    state = engine.call("update", 1.0, NO_INPUT)
    ok = check("no wave yet before the spawn delay elapses", len(state["enemies"]) == 0)
    state = engine.call("update", 5.0, NO_INPUT)                # crosses wave_delay = 5.0
    ok &= check("a wave spawns once the delay elapses", len(state["enemies"]) > 0)
    ok &= check("level advanced after the first wave", state["level"] == 2)
    return ok


def test_enemies_advance_toward_the_player():
    engine = make_engine()
    engine.call("update", 5.0, NO_INPUT)                        # spawn a wave
    first = engine.call("update", 0.1, NO_INPUT)
    starting_x = [e["x"] for e in first["enemies"]]
    second = engine.call("update", 0.1, NO_INPUT)
    later_x = [e["x"] for e in second["enemies"]]
    return check(
        "every surviving enemy's x decreased (moving toward the player)",
        all(b <= a for a, b in zip(starting_x, later_x[:len(starting_x)])),
    )


def test_player_takes_damage_on_contact():
    """Places two stationary enemies exactly on the player, so contact is
    certain on the very next update - no waiting on random spawn heights -
    and checks its exact cost: each hit takes that enemy's damage, adds 10
    to the score, and destroys the enemy."""
    engine = make_engine()
    for damage in (8, 5):
        engine.nova.exec(
            "append(enemies, {{x: player.x, y: player.y, hp: 40, speed: 0.0, damage: {}}})"
            .format(damage)
        )
    state = engine.call("update", 0.0, NO_INPUT)
    ok = check("each contact costs that enemy's damage (100 - 8 - 5 = 87)", state["player_hp"] == 87)
    ok &= check("each contact scores exactly 10 (two hits = 20)", state["score"] == 20)
    ok &= check("an enemy that hits the player is destroyed", len(state["enemies"]) == 0)
    return ok


def test_game_over_flag():
    engine = make_engine()
    game = engine.nova
    # Force the condition directly rather than waiting on random placement:
    # exercises the same game_over computation update() does, without
    # depending on timing.
    game.exec("player.hp = 0")
    state = engine.call("update", 0.1, NO_INPUT)
    return check("game_over is true once player.hp reaches 0", state["game_over"] is True)


def test_reset_restores_initial_state():
    engine = make_engine()
    engine.call("update", 5.0, NO_INPUT)
    engine.nova.exec("player.hp = 10")
    engine.nova.exec("player.score = 70")
    engine.call("reset_game")
    state = engine.call("update", 0.0, NO_INPUT)
    ok = check("reset_game() restores player.hp to 100", state["player_hp"] == 100)
    ok &= check("reset_game() clears any leftover enemies", len(state["enemies"]) == 0)
    ok &= check("reset_game() sets the score back to 0", state["score"] == 0)
    return ok


def main():
    results = [
        test_player_moves_with_input(),
        test_wave_spawns_after_delay(),
        test_enemies_advance_toward_the_player(),
        test_player_takes_damage_on_contact(),
        test_game_over_flag(),
        test_reset_restores_initial_state(),
    ]
    print()
    if all(results):
        print("All Daedalus game logic tests passed.")
        return 0
    print("SOME TESTS FAILED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
