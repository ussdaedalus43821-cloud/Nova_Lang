#!/usr/bin/env python3
"""main.py - the pygame side: window, input, rendering, the frame loop.

Same shape as reactor_game/main.py: this is the only file that imports
pygame, and everything it calls into (nova_bridge.NovaEngine) is
pygame-free and already exercised by test_game_logic.py with no display.

One call per frame: update(dt, controls) does everything (movement,
spawning, collision, damage) and returns a plain dict/list snapshot for
rendering. See the embedding plan's Performance section for why this
stays as one call rather than several smaller ones.

Cannot run in a headless sandbox with no display - needs pygame and a
real window. The Nova usage itself is real and tested via
test_game_logic.py, using this exact NovaEngine/script pair.
"""
import sys

import pygame

from nova_bridge import NovaEngine

WIDTH, HEIGHT = 900, 500
WORLD_TO_PIXELS = 40   # world units (roughly meters) -> pixels, for drawing only

ENEMY_COLORS = {
    "fast": (240, 200, 80),
    "tank": (120, 160, 240),
    "boss": (230, 60, 60),
    "normal": (200, 200, 200),
}


def to_screen(x, y):
    return int(WIDTH - x * WORLD_TO_PIXELS), int(80 + y * WORLD_TO_PIXELS)


def draw(screen, font, state):
    screen.fill((10, 10, 18))

    px, py = to_screen(state["player_x"], state["player_y"])
    pygame.draw.circle(screen, (80, 220, 120), (px, py), 12)

    for enemy in state["enemies"]:
        ex, ey = to_screen(enemy["x"], enemy["y"])
        color = ENEMY_COLORS.get(enemy["kind"], ENEMY_COLORS["normal"])
        pygame.draw.circle(screen, color, (ex, ey), 8)

    hud = [
        "hp: {}".format(state["player_hp"]),
        "score: {}".format(state["score"]),
        "level: {}".format(state["level"]),
        "enemies: {}".format(len(state["enemies"])),
        "",
        "Arrow keys to move  |  R: reset  |  ESC: quit",
    ]
    for i, line in enumerate(hud):
        screen.blit(font.render(line, True, (230, 230, 230)), (16, 16 + i * 24))

    if state["game_over"]:
        over = font.render("GAME OVER - press R to restart", True, (255, 90, 90))
        screen.blit(over, (WIDTH // 2 - over.get_width() // 2, HEIGHT // 2))

    pygame.display.flip()


def read_controls(keys_pressed):
    return {
        "left": keys_pressed[pygame.K_LEFT],
        "right": keys_pressed[pygame.K_RIGHT],
        "up": keys_pressed[pygame.K_UP],
        "down": keys_pressed[pygame.K_DOWN],
    }


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Daedalus (NovaLang-driven)")
    font = pygame.font.SysFont("monospace", 18)
    clock = pygame.time.Clock()

    engine = NovaEngine(scripts=["enemy_waves.nova", "game_logic.nova"])

    running = True
    state = None
    while running:
        dt = clock.tick(60) / 1000.0

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    engine.call("reset_game")

        # Reading the keyboard never leaves Python; the raw booleans are
        # what crosses into NovaLang, which then decides what they mean
        # (movement speed, whether input even matters while dead, etc).
        controls = read_controls(pygame.key.get_pressed())

        state = engine.call("update", dt, controls)

        draw(screen, font, state)

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
