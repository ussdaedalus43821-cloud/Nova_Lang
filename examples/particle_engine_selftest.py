#!/usr/bin/env python3
"""particle_engine_selftest.py - RUN THIS FIRST, before the full demo.

particle_engine.py's collision code could not be executed in the
environment that wrote it (no numpy, no network access to install it -
see that file's module docstring for the full disclosure). What WAS
validated there is the underlying algorithm, as plain-Python prototypes
against a brute-force O(n^2) reference. This script re-runs that same
cross-check against your actual installed NumPy, on the actual
ParticleEngine class the demo uses - so if this passes, the transcription
from validated algorithm to NumPy code was faithful; if it fails, that's
real, actionable signal about where.

No pygame needed - just numpy.

Run: python3 particle_engine_selftest.py
"""
import sys

import numpy as np

from particle_engine import ParticleEngine


def brute_force_collision_dvel(pos, vel, radius, mass, spring_k):
    """O(n^2) reference: every pair, no grid, obviously correct - what
    _resolve_collisions()'s vectorized grid version is checked against."""
    n = len(pos)
    dvel = np.zeros_like(vel)
    for i in range(n):
        for j in range(i + 1, n):
            delta = pos[i] - pos[j]
            dist = float(np.sqrt(np.sum(delta * delta)))
            min_dist = radius[i] + radius[j]
            overlap = min_dist - dist
            if overlap <= 0.0:
                continue
            dist_safe = max(dist, 1e-6)
            direction = delta / dist_safe
            force_mag = spring_k * overlap
            impulse = direction * force_mag
            total_mass = mass[i] + mass[j]
            dvel[i] += impulse * (mass[j] / total_mass)
            dvel[j] -= impulse * (mass[i] / total_mass)
    return dvel


def make_engine(positions, velocities, radii, masses, width=800.0, height=600.0):
    n = len(positions)
    engine = ParticleEngine(capacity=n, width=width, height=height)
    engine.n = n
    engine.pos[:n] = positions
    engine.vel[:n] = velocities
    engine.radius[:n] = radii
    engine.mass[:n] = masses
    return engine


def check(label, condition):
    print("[{}] {}".format("ok" if condition else "FAILED", label))
    return condition


def run_trial(n, width, height, seed, cell_size, max_per_cell, spring_k, cramped=False):
    rng = np.random.default_rng(seed)
    if cramped:
        # force lots of same-cell and overflow cases: everyone packed
        # into a small region relative to cell_size
        positions = rng.uniform(0, cell_size * 3, size=(n, 2)) + np.array([width / 2, height / 2])
    else:
        positions = rng.uniform(0, min(width, height), size=(n, 2))
    velocities = rng.uniform(-50, 50, size=(n, 2))
    radii = rng.uniform(2.0, 5.0, size=n)
    masses = rng.uniform(0.5, 2.0, size=n)

    engine = make_engine(positions, velocities, radii, masses, width, height)
    directives = {
        "gravity": 0.0, "wind": 0.0, "damping": 1.0, "mouse_mode": "none",
        "restitution": 0.7, "collisions_enabled": True,
        "collision_cell_size": cell_size, "collision_max_per_cell": max_per_cell,
        "collision_spring_k": spring_k,
    }
    # Isolate collision resolution: call it directly rather than the
    # full step(), so boundary handling and gravity don't muddy the diff.
    pos_view = engine.pos[:n].copy()
    vel_before = engine.vel[:n].copy()
    engine._resolve_collisions(engine.pos[:n], engine.vel[:n], engine.radius[:n], engine.mass[:n], directives)
    grid_dvel = engine.vel[:n] - vel_before

    ref_dvel = brute_force_collision_dvel(pos_view, vel_before, radii, masses, spring_k)

    diff = np.abs(grid_dvel - ref_dvel)
    max_diff = float(np.max(diff)) if diff.size else 0.0
    tolerance = 1e-6 * max(1.0, float(np.max(np.abs(ref_dvel))) if ref_dvel.size else 1.0)
    return max_diff, tolerance, n


def main():
    print("Cross-checking ParticleEngine._resolve_collisions() (vectorized grid) "
          "against a brute-force O(n^2) reference, using your installed NumPy {}.\n"
          .format(np.__version__))

    trials = [
        dict(n=50, width=800, height=600, seed=1, cell_size=20.0, max_per_cell=12, spring_k=4000.0),
        dict(n=200, width=800, height=600, seed=2, cell_size=15.0, max_per_cell=12, spring_k=4000.0),
        dict(n=200, width=800, height=600, seed=3, cell_size=15.0, max_per_cell=4, spring_k=4000.0),  # small cap -> overflow
        dict(n=400, width=1000, height=800, seed=4, cell_size=25.0, max_per_cell=16, spring_k=2500.0),
        dict(n=150, width=800, height=600, seed=5, cell_size=20.0, max_per_cell=12, spring_k=4000.0, cramped=True),
        dict(n=2, width=800, height=600, seed=6, cell_size=20.0, max_per_cell=12, spring_k=4000.0),
    ]

    all_ok = True
    for trial in trials:
        max_diff, tolerance, n = run_trial(**trial)
        ok = max_diff <= tolerance
        all_ok &= check(
            "n={} cell_size={} max_per_cell={} cramped={}: max diff {:.2e} (tolerance {:.2e})".format(
                trial["n"], trial["cell_size"], trial["max_per_cell"], trial.get("cramped", False),
                max_diff, tolerance),
            ok,
        )

    # A quick, separate sanity check that spawn/step/boundary don't crash
    # at a realistic size, and that particles stay on screen.
    engine = ParticleEngine(capacity=5000, width=800, height=600)
    engine.spawn_burst(400, 300, count=5000, speed=150.0)
    directives = {
        "gravity": 500.0, "wind": 0.0, "damping": 0.999, "mouse_mode": "attract",
        "mouse_x": 400.0, "mouse_y": 300.0, "mouse_radius": 200.0, "mouse_strength": 3000.0,
        "restitution": 0.7, "collisions_enabled": True,
        "collision_cell_size": 16.0, "collision_max_per_cell": 12, "collision_spring_k": 4000.0,
    }
    for _ in range(120):
        engine.step(1.0 / 60.0, directives)
    in_bounds = np.all(
        (engine.pos[: engine.n, 0] >= -1) & (engine.pos[: engine.n, 0] <= engine.width + 1)
        & (engine.pos[: engine.n, 1] >= -1) & (engine.pos[: engine.n, 1] <= engine.height + 1)
    )
    no_nan = not np.any(np.isnan(engine.pos[: engine.n])) and not np.any(np.isnan(engine.vel[: engine.n]))
    all_ok &= check("5000 particles, 120 steps with gravity+mouse+collision: stay in bounds", bool(in_bounds))
    all_ok &= check("5000 particles, 120 steps: no NaN/inf positions or velocities", no_nan)

    print()
    if all_ok:
        print("All particle_engine self-tests passed.")
        return 0
    print("SOME TESTS FAILED - see above before trusting the full demo's performance or behavior.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
