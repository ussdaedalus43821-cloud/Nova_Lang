#!/usr/bin/env python3
"""examples/ecs_demo.py - the pygame side of the particle demo: window,
input, an FPS counter, particle-count controls, and rendering. All
simulation logic lives elsewhere - examples/ecs_particles.nova (NovaLang:
what should happen this frame) and examples/particle_engine.py (NumPy:
the 25,000-50,000 particles that actually happen to).

RUN particle_engine_selftest.py FIRST - see its docstring and
particle_engine.py's module docstring for why: this environment had no
numpy/pygame/network access to test any of the NumPy code below, so that
self-test (which needs only numpy, no display) is the first real
confirmation any of it works, on your actual machine.

Controls:
  Left mouse (hold)     attract particles
  Right mouse (hold)    repel particles
  1-5                    particle count presets (2k/10k/25k/40k/50k)
  Drag the count slider   fine-grained particle count
  G                       toggle gravity
  C                       toggle particle-particle collisions
  V                       cycle color mode (velocity / temperature / rainbow)
  F                       spawn a force field at the mouse (alternates attract/repel)
  X                       despawn the most recently spawned force field
  T                       cycle trail length (off / short / long)
  Q                       toggle fast (pixel-splat) vs quality (drawn circles) rendering
  R                       reset (clear particles, respawn from the default emitter)
  ESC                     quit
"""
import os
import sys
import time

import numpy as np
import pygame

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
from novalang import Nova, NovaLangError  # noqa: E402
from particle_engine import ParticleEngine  # noqa: E402

WIDTH, HEIGHT = 1000, 700
SIM_HEIGHT = HEIGHT - 60          # a strip at the bottom for the HUD/slider
CAPACITY = 55000
PRESETS = [2000, 10000, 25000, 40000, 50000]

BG_COLOR = (8, 8, 14)
HUD_BG = (18, 18, 26)
TEXT_COLOR = (225, 230, 235)

SLIDER_RECT = pygame.Rect(20, HEIGHT - 34, 500, 18)

COLD_COLOR = (60, 90, 255)
HOT_COLOR = (255, 230, 80)


class NovaSim:
    """The only class that touches Nova() - see ecs_particles.nova's own
    header for why every call here re-threads `sim` through the return
    value instead of holding a stale copy."""

    def __init__(self, width, height):
        self.nova = Nova()
        self.nova.load_file(os.path.join(HERE, "ecs_particles.nova"))
        self.sim = self.nova.call("particles_world_new", float(width), float(height))

    def step(self, dt, mouse_x, mouse_y, left_down, right_down):
        try:
            result = self.nova.call(
                "world_step", self.sim, dt, float(mouse_x), float(mouse_y), left_down, right_down
            )
        except NovaLangError as error:
            raise RuntimeError("NovaLang error in world_step(): {}".format(error)) from error
        self.sim = result["sim"]
        return result["directives"]

    def call(self, name, *args):
        try:
            self.sim = self.nova.call(name, self.sim, *args)
        except NovaLangError as error:
            raise RuntimeError("NovaLang error in {}(): {}".format(name, error)) from error


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def particle_count_from_slider(mouse_x):
    fraction = clamp((mouse_x - SLIDER_RECT.x) / SLIDER_RECT.width, 0.0, 1.0)
    return int(fraction * CAPACITY)


def draw_slider(surface, font, value):
    pygame.draw.rect(surface, (50, 54, 64), SLIDER_RECT, border_radius=6)
    fraction = clamp(value / CAPACITY, 0.0, 1.0)
    fill_w = int(SLIDER_RECT.width * fraction)
    pygame.draw.rect(surface, (90, 170, 240), (SLIDER_RECT.x, SLIDER_RECT.y, fill_w, SLIDER_RECT.height),
                      border_radius=6)
    pygame.draw.rect(surface, (10, 11, 15), SLIDER_RECT, 2, border_radius=6)
    label = font.render("particles: {} (drag, or press 1-5)".format(value), True, TEXT_COLOR)
    surface.blit(label, (SLIDER_RECT.x, SLIDER_RECT.y - 20))


def draw_particles_fast(canvas, positions, colors, width, height):
    """The path that actually reaches 25,000-50,000 particles: one
    vectorized write into the surface's own pixel buffer (a 2x2 splat
    per particle, so single particles are still visible at typical
    screen resolutions), no per-particle Python call at all. See
    particle_engine.py's docstring for why a Python-level per-particle
    draw call - even pygame's fast C-implemented ones - can't hit this
    particle count at 60fps the way a single batched array write can."""
    if len(positions) == 0:
        return
    arr = pygame.surfarray.pixels3d(canvas)  # direct view, shape (width, height, 3)
    xs = np.clip(positions[:, 0], 0, width - 2).astype(np.int32)
    ys = np.clip(positions[:, 1], 0, height - 2).astype(np.int32)
    arr[xs, ys] = colors
    arr[xs + 1, ys] = colors
    arr[xs, ys + 1] = colors
    arr[xs + 1, ys + 1] = colors
    del arr  # release the surface lock as soon as possible


def draw_particles_quality(canvas, positions, colors, radii):
    """Real drawn circles via pygame.draw.circle, one Python-level call
    per particle - looks nicer, costs real per-call overhead, so this is
    the mode for a few thousand particles, not fifty thousand. Toggle
    with Q to compare directly against the fast path at the same count."""
    for i in range(len(positions)):
        color = (int(colors[i, 0]), int(colors[i, 1]), int(colors[i, 2]))
        pygame.draw.circle(canvas, color, (int(positions[i, 0]), int(positions[i, 1])), max(1, int(radii[i])))


def apply_trail_fade(canvas, retain_256):
    """Fades the whole canvas toward black by retain_256/256 instead of
    clearing it - integer arithmetic throughout (no float<->uint8 cast)
    so this doesn't depend on numpy's implicit-casting rules, which this
    sandbox has no numpy to verify either way."""
    arr = pygame.surfarray.pixels3d(canvas)
    arr[:] = (arr.astype(np.uint16) * retain_256 // 256).astype(np.uint8)
    del arr


TRAIL_MODES = [0, 220, 245]  # 0 = fully cleared each frame, else retain_256 for the fade


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("NovaLang ECS Particles")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas,couriernew,monospace", 16)
    font_small = pygame.font.SysFont("consolas,couriernew,monospace", 13)

    canvas = pygame.Surface((WIDTH, SIM_HEIGHT))
    canvas.fill(BG_COLOR)

    sim = NovaSim(WIDTH, SIM_HEIGHT)
    engine = ParticleEngine(capacity=CAPACITY, width=WIDTH, height=SIM_HEIGHT)
    engine.set_capacity_used(PRESETS[1])

    fast_mode = True
    trail_index = 0
    dragging_slider = False
    prev_mouse = (WIDTH // 2, SIM_HEIGHT // 2)
    force_field_toggle = "attract"

    running = True
    while running:
        dt = clock.tick(60) / 1000.0
        dt = min(dt, 1.0 / 15.0)  # avoid a huge dt after a stall/breakpoint

        mouse_x, mouse_y = pygame.mouse.get_pos()
        mouse_y_sim = min(mouse_y, SIM_HEIGHT - 1)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5):
                    preset_index = event.key - pygame.K_1
                    engine.set_capacity_used(PRESETS[preset_index])
                elif event.key == pygame.K_g:
                    sim.call("toggle_gravity")
                elif event.key == pygame.K_c:
                    sim.call("toggle_collisions")
                elif event.key == pygame.K_v:
                    sim.call("cycle_color_mode")
                elif event.key == pygame.K_f:
                    sim.call("spawn_force_field", float(mouse_x), float(mouse_y_sim), force_field_toggle)
                    force_field_toggle = "repel" if force_field_toggle == "attract" else "attract"
                elif event.key == pygame.K_x:
                    sim.call("despawn_last_force_field")
                elif event.key == pygame.K_t:
                    trail_index = (trail_index + 1) % len(TRAIL_MODES)
                elif event.key == pygame.K_q:
                    fast_mode = not fast_mode
                elif event.key == pygame.K_r:
                    engine.despawn_all()
                    engine.set_capacity_used(PRESETS[1])
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if SLIDER_RECT.inflate(0, 16).collidepoint(mouse_x, mouse_y):
                    dragging_slider = True
                    engine.set_capacity_used(particle_count_from_slider(mouse_x))
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging_slider = False
            elif event.type == pygame.MOUSEMOTION and dragging_slider:
                engine.set_capacity_used(particle_count_from_slider(mouse_x))

        left_down, _, right_down = pygame.mouse.get_pressed()
        if dragging_slider:
            left_down = False  # dragging the slider shouldn't also attract particles

        directives = sim.step(dt, mouse_x, mouse_y_sim, left_down, right_down)

        for request in directives["spawn_requests"]:
            engine.spawn_burst(
                request["x"], request["y"], int(request["count"]),
                speed=request.get("speed", 120.0), hue=request.get("hue", 0.0),
            )

        engine.step(dt, directives)

        # ---- render ----
        retain = TRAIL_MODES[trail_index]
        if retain <= 0:
            canvas.fill(BG_COLOR)
        else:
            apply_trail_fade(canvas, retain)

        color_mode = directives["color_mode"]
        if color_mode == "temperature":
            colors = engine.colors_temperature(max_speed=600.0)
        elif color_mode == "rainbow":
            colors = engine.colors_rainbow(time.perf_counter())
        else:
            colors = engine.colors_by_velocity(COLD_COLOR, HOT_COLOR, max_speed=600.0)

        positions = engine.positions_int()
        if fast_mode:
            draw_particles_fast(canvas, positions, colors, WIDTH, SIM_HEIGHT)
        else:
            draw_particles_quality(canvas, positions, colors, engine.radius[: engine.n])

        screen.blit(canvas, (0, 0))

        pygame.draw.rect(screen, HUD_BG, (0, SIM_HEIGHT, WIDTH, HEIGHT - SIM_HEIGHT))
        draw_slider(screen, font_small, engine.n)

        fps = clock.get_fps()
        hud_lines = [
            "FPS: {:.1f}   particles: {}   mode: {}   gravity: {}   collisions: {}   color: {}".format(
                fps, engine.n, "fast" if fast_mode else "quality",
                "on" if directives["gravity"] > 0 else "off",
                "on" if directives["collisions_enabled"] else "off",
                color_mode,
            ),
        ]
        for i, line in enumerate(hud_lines):
            screen.blit(font.render(line, True, TEXT_COLOR), (20, HEIGHT - 56 + i * 18))

        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
