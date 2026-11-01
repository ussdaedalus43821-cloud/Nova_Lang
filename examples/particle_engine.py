"""examples/particle_engine.py - the NumPy-vectorized particle simulation
core: positions, velocities, physics integration, boundary collision,
mouse interaction, and particle-particle collision via a uniform spatial
grid. No pygame here - see examples/ecs_demo.py for the display side.

WHY THIS EXISTS IN PYTHON, NOT NOVALANG - read lib/ecs.nova's header for
the full explanation with numbers; the short version: NovaLang's
tree-walking interpreter runs at roughly 40,000-160,000 simple operations
per second, and 25,000-50,000 particles at 60fps needs tens of millions
of operations per second. Only vectorized array math closes that gap.
NovaLang (examples/ecs_particles.nova) decides WHAT this engine should
do each frame - gravity strength, whether the mouse attracts or repels,
where to spawn a new burst - by returning a small "directives" dict from
one world_step() call; this file is what actually moves 50,000 particles
in response, using contiguous NumPy arrays instead of 50,000 per-particle
Python objects (an array-of-structs would still be slow-ish in a Python
loop - this is struct-of-arrays specifically so every operation below is
a single vectorized call over the whole population, not a Python loop
over particles at all).

A NOTE ON TESTING - this file was first written where NumPy was not
available, with only the algorithm validated as plain-Python prototypes.
When particle_engine_selftest.py first ran against real NumPy (2.5.3) it
caught a genuine bug: particles beyond max_per_cell in a crowded cell were
dropped from collision, so dense pockets passed through each other. Dense
cells are now handled exactly (see _resolve_collisions), and the self-test,
which tests/run_all.py runs, checks every trial against an O(n^2)
brute-force reference, including trials that really do overflow a cell.

Coordinate convention: +x right, +y down (matching pygame's screen
space), so "gravity" is a positive y-acceleration.
"""
import math

import numpy as np

# Neighbor cell offsets covering full 8-connectivity while visiting each
# unordered pair of adjacent cells exactly once (validated in
# rank_trick_prototype.py / grid_algorithm_prototype.py).
NEIGHBOR_OFFSETS = [(0, 0), (1, 0), (0, 1), (1, 1), (-1, 1)]


def lerp_color(c0, c1, t):
    t = np.clip(t, 0.0, 1.0)
    return c0 + (c1 - c0) * t[:, None]


class ParticleEngine:
    """Struct-of-arrays particle store + vectorized physics/collision.

    capacity: the array size to preallocate. Spawning beyond capacity is
    a no-op (silently capped) rather than reallocating mid-simulation -
    predictable performance beats surprise pauses for a real-time demo.
    """

    def __init__(self, capacity, width, height, seed=0):
        self.capacity = capacity
        self.width = float(width)
        self.height = float(height)
        self.n = 0
        self.rng = np.random.default_rng(seed)

        self.pos = np.zeros((capacity, 2), dtype=np.float64)
        self.vel = np.zeros((capacity, 2), dtype=np.float64)
        self.radius = np.full(capacity, 3.0, dtype=np.float64)
        self.mass = np.ones(capacity, dtype=np.float64)
        # A free per-particle scalar (0..1) for color variety within a
        # spawn burst - carries no physical meaning on its own.
        self.hue_seed = np.zeros(capacity, dtype=np.float64)

        # Rendering-only: fixed capacity trail history, a ring buffer of
        # the last `trail_length` positions per particle. Filled lazily
        # (see set_trail_length) so trails cost nothing when unused.
        self.trail_length = 0
        self.trail_pos = None
        self.trail_index = 0

    # ---- spawning ---------------------------------------------------

    def spawn_burst(self, x, y, count, speed=120.0, spread=6.0, radius=3.0, mass=1.0, hue=0.0):
        """Spawns up to `count` particles near (x, y) with randomized
        outward velocity - the one operation NovaLang's emitter system
        calls into, once per spawn event (not once per particle)."""
        count = min(count, self.capacity - self.n)
        if count <= 0:
            return 0
        start, end = self.n, self.n + count

        angle = self.rng.uniform(0.0, 2.0 * math.pi, size=count)
        speed_jitter = self.rng.uniform(0.4, 1.0, size=count) * speed
        self.pos[start:end, 0] = x + self.rng.uniform(-spread, spread, size=count)
        self.pos[start:end, 1] = y + self.rng.uniform(-spread, spread, size=count)
        self.vel[start:end, 0] = np.cos(angle) * speed_jitter
        self.vel[start:end, 1] = np.sin(angle) * speed_jitter
        self.radius[start:end] = radius
        self.mass[start:end] = mass
        self.hue_seed[start:end] = hue

        self.n = end
        return count

    def despawn_all(self):
        self.n = 0

    def set_capacity_used(self, count):
        """Grows/shrinks the active population toward `count`, spawning
        randomly across the field to reach it or truncating to reach it
        - what the demo's particle-count control calls."""
        count = max(0, min(count, self.capacity))
        if count > self.n:
            missing = count - self.n
            start, end = self.n, self.n + missing
            self.pos[start:end, 0] = self.rng.uniform(0, self.width, size=missing)
            self.pos[start:end, 1] = self.rng.uniform(0, self.height, size=missing)
            angle = self.rng.uniform(0.0, 2.0 * math.pi, size=missing)
            speed = self.rng.uniform(20.0, 120.0, size=missing)
            self.vel[start:end, 0] = np.cos(angle) * speed
            self.vel[start:end, 1] = np.sin(angle) * speed
            self.radius[start:end] = 3.0
            self.mass[start:end] = 1.0
            self.hue_seed[start:end] = self.rng.uniform(0.0, 1.0, size=missing)
        self.n = count

    # ---- trails -------------------------------------------------------

    def set_trail_length(self, length):
        if length == self.trail_length:
            return
        self.trail_length = length
        if length <= 0:
            self.trail_pos = None
            return
        self.trail_pos = np.tile(self.pos[:, None, :], (1, length, 1))
        self.trail_index = 0

    def _push_trail(self):
        if self.trail_length <= 0:
            return
        self.trail_pos[: self.n, self.trail_index, :] = self.pos[: self.n]
        self.trail_index = (self.trail_index + 1) % self.trail_length

    # ---- the per-frame step -------------------------------------------

    def step(self, dt, directives):
        """Advances the simulation by dt seconds. `directives` is the
        plain dict examples/ecs_particles.nova's world_step() returns -
        see that file for the exact keys. Every array operation below
        touches self.pos[:n]/self.vel[:n] etc. as a whole - no Python
        loop over particles anywhere in this method."""
        n = self.n
        if n == 0:
            return

        pos = self.pos[:n]
        vel = self.vel[:n]
        radius = self.radius[:n]
        mass = self.mass[:n]

        gravity = directives.get("gravity", 0.0)
        wind = directives.get("wind", 0.0)
        damping = directives.get("damping", 1.0)

        vel[:, 1] += gravity * dt
        vel[:, 0] += wind * dt
        vel *= damping

        self._apply_mouse(pos, vel, mass, directives, dt)
        self._apply_force_fields(pos, vel, mass, directives, dt)

        pos += vel * dt

        self._resolve_boundary(pos, vel, radius, directives)

        if directives.get("collisions_enabled", True):
            self._resolve_collisions(pos, vel, radius, mass, directives)

        self._push_trail()

    def _apply_mouse(self, pos, vel, mass, directives, dt):
        mode = directives.get("mouse_mode", "none")
        if mode == "none":
            return
        mx = directives.get("mouse_x", 0.0)
        my = directives.get("mouse_y", 0.0)
        radius = directives.get("mouse_radius", 250.0)
        strength = directives.get("mouse_strength", 4000.0)

        delta = np.array([mx, my]) - pos
        dist = np.sqrt(np.sum(delta * delta, axis=1))
        dist_safe = np.maximum(dist, 1e-6)
        direction = delta / dist_safe[:, None]
        within = dist < radius

        if mode == "attract":
            accel = strength / (dist_safe[:, None] * 0.02 + 1.0)
            vel += np.where(within[:, None], direction * accel * dt, 0.0)
        elif mode == "repel":
            accel = strength / (dist_safe[:, None] * 0.02 + 1.0)
            vel -= np.where(within[:, None], direction * accel * dt, 0.0)
        elif mode == "follow":
            mvx = directives.get("mouse_vx", 0.0)
            mvy = directives.get("mouse_vy", 0.0)
            pull = strength * 0.15 / (dist_safe[:, None] * 0.02 + 1.0)
            target_vel = direction * pull + np.array([mvx, mvy]) * 0.5
            blend = np.where(within[:, None], 0.08, 0.0)
            vel += (target_vel - vel) * blend

    def _apply_force_fields(self, pos, vel, mass, directives, dt):
        fields = directives.get("force_fields", [])
        for field in fields:
            fx, fy = field["x"], field["y"]
            radius = field.get("radius", 150.0)
            strength = field.get("strength", 2000.0)
            kind = field.get("kind", "attract")

            delta = np.array([fx, fy]) - pos
            dist = np.sqrt(np.sum(delta * delta, axis=1))
            dist_safe = np.maximum(dist, 1e-6)
            within = dist < radius
            direction = delta / dist_safe[:, None]
            accel = strength / (dist_safe[:, None] * 0.05 + 1.0)
            signed = accel if kind == "attract" else -accel
            vel += np.where(within[:, None], direction * signed * dt, 0.0)

    def _resolve_boundary(self, pos, vel, radius, directives):
        restitution = directives.get("restitution", 0.7)

        below_left = pos[:, 0] < radius
        pos[below_left, 0] = radius[below_left]
        vel[below_left, 0] = -vel[below_left, 0] * restitution

        above_right = pos[:, 0] > self.width - radius
        pos[above_right, 0] = self.width - radius[above_right]
        vel[above_right, 0] = -vel[above_right, 0] * restitution

        below_top = pos[:, 1] < radius
        pos[below_top, 1] = radius[below_top]
        vel[below_top, 1] = -vel[below_top, 1] * restitution

        above_bottom = pos[:, 1] > self.height - radius
        pos[above_bottom, 1] = self.height - radius[above_bottom]
        vel[above_bottom, 1] = -vel[above_bottom, 1] * restitution

    # ---- collision: uniform grid, vectorized ---------------------------
    #
    # See the module docstring's testing note. The technique: bucket
    # particles into occupied grid cells (a dense (num_occupied_cells x
    # max_per_cell) array, built via sort + cumsum "rank within cell" -
    # no Python loop over particles or cells), then for each of 5 fixed
    # neighbor offsets, compare every occupied cell's bucket against its
    # neighbor's bucket with one broadcasted NumPy operation covering
    # every cell at once. Cells holding more than max_per_cell particles
    # are compared separately at full width, so the result is exact
    # however dense a pocket gets (particle_engine_selftest.py checks this
    # against an O(n^2) reference); max_per_cell only decides which cells
    # count as dense.

    @staticmethod
    def collide_buckets(self_bucket, other_bucket, same_cell, pos, radius, mass, spring_k, total_dvel):
        """Collide every particle in each row of `self_bucket` (k, cap) with
        every particle in the same row of `other_bucket`, adding the spring
        impulses into total_dvel. -1 marks an empty slot."""
        idx_a = self_bucket[:, :, None]                        # (k, cap, 1)
        idx_b = other_bucket[:, None, :]                       # (k, 1, cap)

        valid_pair = (idx_a != -1) & (idx_b != -1)
        if same_cell:
            # Within one cell, keeping only idx_a < idx_b counts each pair
            # once and never pairs a particle with itself.
            valid_pair &= idx_a < idx_b
        if not np.any(valid_pair):
            return

        flat_valid = valid_pair.reshape(-1)
        flat_a = np.broadcast_to(idx_a, valid_pair.shape).reshape(-1)[flat_valid]
        flat_b = np.broadcast_to(idx_b, valid_pair.shape).reshape(-1)[flat_valid]

        delta = pos[flat_a] - pos[flat_b]
        dist = np.sqrt(np.sum(delta * delta, axis=1))
        dist_safe = np.maximum(dist, 1e-6)
        overlap = radius[flat_a] + radius[flat_b] - dist
        colliding = overlap > 0.0
        if not np.any(colliding):
            return

        direction = delta[colliding] / dist_safe[colliding, None]
        force_mag = spring_k * overlap[colliding]
        ma = mass[flat_a[colliding]]
        mb = mass[flat_b[colliding]]
        total_mass = ma + mb
        impulse = direction * force_mag[:, None]

        np.add.at(total_dvel, flat_a[colliding], impulse * (mb / total_mass)[:, None])
        np.add.at(total_dvel, flat_b[colliding], -impulse * (ma / total_mass)[:, None])

    def _resolve_collisions(self, pos, vel, radius, mass, directives):
        n = len(pos)
        if n < 2:
            return

        cell_size = directives.get("collision_cell_size")
        if not cell_size or cell_size <= 0:
            cell_size = max(8.0, float(np.mean(radius)) * 4.0)
        max_per_cell = int(directives.get("collision_max_per_cell", 12))
        spring_k = directives.get("collision_spring_k", 4000.0)

        cx = np.clip((pos[:, 0] // cell_size).astype(np.int64), 0, 1 << 20)
        cy = np.clip((pos[:, 1] // cell_size).astype(np.int64), 0, 1 << 20)
        grid_w = int(self.width // cell_size) + 2
        cell_id = cy * grid_w + cx

        order = np.argsort(cell_id, kind="stable")
        sorted_id = cell_id[order]
        sorted_cx = cx[order]
        sorted_cy = cy[order]

        change = np.empty(n, dtype=bool)
        change[0] = True
        change[1:] = sorted_id[1:] != sorted_id[:-1]
        group_id = np.cumsum(change) - 1
        num_groups = int(group_id[-1]) + 1

        cell_start_pos = np.nonzero(change)[0]
        rank_in_cell = np.arange(n) - cell_start_pos[group_id]

        counts = np.bincount(group_id, minlength=num_groups)
        dense = counts > max_per_cell

        # Tier 1 - pairs of ordinary cells: every cell's particles fit in a
        # (num_groups x max_per_cell) bucket, compared with one broadcast
        # per neighbor offset. Dense cells are left out of the bucket here
        # and handled exactly by tier 2 instead.
        keep = (rank_in_cell < max_per_cell) & ~dense[group_id]
        bucket = np.full((num_groups, max_per_cell), -1, dtype=np.int64)
        bucket[group_id[keep], rank_in_cell[keep]] = order[keep]

        group_cx = sorted_cx[cell_start_pos]
        group_cy = sorted_cy[cell_start_pos]

        grid_h_bound = int(self.height // cell_size) + 4
        grid_w_bound = grid_w + 4
        lookup = np.full((grid_h_bound, grid_w_bound), -1, dtype=np.int64)
        lookup[group_cy + 2, group_cx + 2] = np.arange(num_groups)

        total_dvel = np.zeros_like(vel)
        all_groups = np.arange(num_groups)
        widest = int(counts.max())

        def full_rows(groups):
            """Every particle of each cell in `groups`, one row per cell,
            padded with -1 to the widest cell's count."""
            columns = np.arange(widest)[None, :]
            index = np.minimum(cell_start_pos[groups][:, None] + columns, n - 1)
            return np.where(columns < counts[groups][:, None], order[index], -1)

        for (dx, dy) in NEIGHBOR_OFFSETS:
            neighbor_group = lookup[group_cy + 2 + dy, group_cx + 2 + dx]
            has_neighbor = neighbor_group != -1
            safe_neighbor = np.maximum(neighbor_group, 0)
            same_cell = (dx, dy) == (0, 0)

            ordinary = has_neighbor & ~dense & ~dense[safe_neighbor]
            if np.any(ordinary):
                self.collide_buckets(
                    bucket[ordinary], bucket[neighbor_group[ordinary]], same_cell,
                    pos, radius, mass, spring_k, total_dvel,
                )

            # Tier 2 - any cell pair involving a dense cell, at full width:
            # exact however crowded the pocket, and only as many rows as
            # there are such pairs.
            crowded = has_neighbor & (dense | dense[safe_neighbor])
            if np.any(crowded):
                self.collide_buckets(
                    full_rows(all_groups[crowded]), full_rows(neighbor_group[crowded]), same_cell,
                    pos, radius, mass, spring_k, total_dvel,
                )

        vel += total_dvel

    # ---- data for rendering ---------------------------------------------
    #
    # There's no separate physical "temperature" field in this model
    # (nothing here simulates heat) - colors_temperature() is speed-based
    # too, just mapped through a black -> red -> yellow -> white "heat"
    # gradient instead of colors_by_velocity()'s two-stop one, so the two
    # modes read as genuinely different at a glance. colors_rainbow()
    # is the one mode that ignores velocity entirely, cycling each
    # particle's fixed per-spawn hue_seed over time instead.

    def colors_by_velocity(self, cold, hot, max_speed):
        n = self.n
        speed = np.sqrt(np.sum(self.vel[:n] ** 2, axis=1))
        t = np.clip(speed / max_speed, 0.0, 1.0)
        cold_arr = np.array(cold, dtype=np.float64)
        hot_arr = np.array(hot, dtype=np.float64)
        colors = lerp_color(cold_arr, hot_arr, t)
        return colors.astype(np.uint8)

    _HEAT_STOPS = np.array(
        [[10, 10, 10], [180, 30, 20], [255, 200, 40], [255, 255, 255]], dtype=np.float64
    )

    def colors_temperature(self, max_speed):
        n = self.n
        speed = np.sqrt(np.sum(self.vel[:n] ** 2, axis=1))
        t = np.clip(speed / max_speed, 0.0, 1.0)
        return self._gradient(t, self._HEAT_STOPS)

    def colors_rainbow(self, time_s, cycle_seconds=6.0):
        n = self.n
        hue = (self.hue_seed[:n] + time_s / cycle_seconds) % 1.0
        return self._hsv_to_rgb(hue)

    @staticmethod
    def _gradient(t, stops):
        """t: (n,) in [0,1]. stops: (k,3) evenly-spaced color anchors."""
        k = len(stops) - 1
        scaled = t * k
        idx = np.clip(scaled.astype(np.int32), 0, k - 1)
        frac = (scaled - idx)[:, None]
        c0 = stops[idx]
        c1 = stops[idx + 1]
        return (c0 + (c1 - c0) * frac).astype(np.uint8)

    @staticmethod
    def _hsv_to_rgb(hue):
        """hue: (n,) in [0,1). Full saturation and value."""
        h6 = hue * 6.0
        i = np.floor(h6).astype(np.int32) % 6
        f = h6 - np.floor(h6)
        q = 1.0 - f
        masks = [i == k for k in range(6)]
        r = np.select(masks, [np.ones_like(f), q, np.zeros_like(f), np.zeros_like(f), f, np.ones_like(f)])
        g = np.select(masks, [f, np.ones_like(f), np.ones_like(f), q, np.zeros_like(f), np.zeros_like(f)])
        b = np.select(masks, [np.zeros_like(f), np.zeros_like(f), f, np.ones_like(f), np.ones_like(f), q])
        rgb = np.stack([r, g, b], axis=1) * 255.0
        return rgb.astype(np.uint8)

    def positions_int(self):
        return self.pos[: self.n].astype(np.int32)
