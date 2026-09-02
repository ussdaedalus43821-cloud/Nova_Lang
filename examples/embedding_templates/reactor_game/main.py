#!/usr/bin/env python3
"""main.py - the pygame side: window, input, rendering, the frame loop.

This is the ONLY file in the template that imports pygame. Everything it
calls into (nova_bridge.NovaEngine) is pygame-free, which is what let
test_reactor_logic.py exercise the same logic with no display at all.

This file cannot run in a headless sandbox with no display - it needs
pygame installed and a real window. Structure and Nova usage are real and
tested (via test_reactor_logic.py, using this exact NovaEngine/Reactor
pair); the pygame calls themselves are standard pygame, adapted to your
actual project's window size, fonts, and asset loading.
"""
import sys

import pygame

from nova_bridge import NovaEngine
from reactor import Reactor

WIDTH, HEIGHT = 800, 600
BASE_TEMP_FOR_BAR = 3200.0   # the bar's full-scale reading, for drawing only


def draw(screen, font, reactor, result):
    screen.fill((12, 12, 20))

    bar_height = int(HEIGHT * min(reactor.temp / BASE_TEMP_FOR_BAR, 1.0))
    bar_color = (220, 60, 60) if reactor.temp > 2400 else (60, 200, 120)
    pygame.draw.rect(screen, bar_color, (60, HEIGHT - bar_height, 80, bar_height))

    lines = [
        "temp: {:.1f}C".format(reactor.temp),
        "power: {}%".format(reactor.power),
        "scrammed: {}".format(reactor.scrammed),
        "status: {}".format(result),
        "",
        "UP/DOWN: operator power  |  R: reset  |  ESC: quit",
    ]
    for i, line in enumerate(lines):
        screen.blit(font.render(line, True, (230, 230, 230)), (180, 40 + i * 28))

    pygame.display.flip()


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Reactor Sim (NovaLang-driven)")
    font = pygame.font.SysFont("monospace", 20)
    clock = pygame.time.Clock()

    engine = NovaEngine(scripts=["reactor_physics.nova", "reactor_control.nova"])
    reactor = Reactor()
    engine.expose("reactor", reactor)

    result = "nominal"
    running = True
    while running:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    reactor.temp, reactor.power, reactor.scrammed = 1800.0, 70, False

        # Input decides WHAT the player is asking for; NovaLang decides
        # whether/how much that request is honored (the clamping in
        # operator_increase_power/operator_decrease_power). Keyboard
        # reading itself never leaves Python.
        pressed = pygame.key.get_pressed()
        if pressed[pygame.K_UP]:
            engine.call("operator_increase_power")
        if pressed[pygame.K_DOWN]:
            engine.call("operator_decrease_power")

        # One call per frame for physics, one for the rule check - see
        # the embedding plan's Performance section for why this stays at
        # two small calls rather than either merging them into one "do
        # everything" call or splitting further.
        engine.call("tick", dt)
        result = engine.call("check_reactor")

        draw(screen, font, reactor, result)

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
