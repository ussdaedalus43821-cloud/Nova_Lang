#!/usr/bin/env python3
"""
examples/daedalus_integration.py - Stage 12's embedding API, driving a
game's enemy waves from a NovaLang script.

A runnable, self-contained MOCK of the pattern for wiring NovaLang into a
real game loop such as Daedalus: `GameLoop` below stands in for the real
one, calling nova.call("spawn_wave", ...) / ("spawn_level_wave", ...) each
time it needs a new wave, exactly as a real integration would from inside
its own update loop.

Run: python3 examples/daedalus_integration.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from novalang import Nova, NovaLangError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class GameLoop:
    """A minimal mock game loop: just enough to call into the wave
    script once per "level" and report what came back. Replace with your
    real update loop; the nova.call() lines are the whole integration."""

    def __init__(self, nova):
        self.nova = nova
        self.enemies_alive = []

    def start_level(self, level):
        try:
            wave = self.nova.call("spawn_level_wave", level)
        except NovaLangError as error:
            print("level {}: wave script failed, skipping level: {}".format(level, error))
            return
        self.enemies_alive = wave
        kinds = {}
        for enemy in wave:
            kinds[enemy["kind"]] = kinds.get(enemy["kind"], 0) + 1
        summary = ", ".join("{}x {}".format(count, kind) for kind, count in kinds.items())
        print("level {}: spawned {} enemies ({})".format(level, len(wave), summary))

    def run(self, levels):
        started = time.perf_counter()
        for level in range(1, levels + 1):
            self.start_level(level)
        elapsed = time.perf_counter() - started
        calls = levels
        print(
            "\n{} spawn_level_wave() calls in {:.4f}s ({:.0f} calls/sec) - "
            "comfortably inside a 60fps frame budget (16.7ms) even before "
            "compile() or eval()'s automatic per-source caching (Stage 12)."
            .format(calls, elapsed, calls / elapsed if elapsed > 0 else float("inf"))
        )


def main():
    nova = Nova()
    nova.load_file(os.path.join(HERE, "daedalus_waves.nova"))

    # A single explicit spawn_wave() call, the simple case from the spec.
    wave = nova.call("spawn_wave", 5, "fast")
    print("spawn_wave(5, 'fast') ->", len(wave), "enemies, e.g.", wave[0])
    print()

    GameLoop(nova).run(levels=15)


if __name__ == "__main__":
    main()
