# Embedding NovaLang into Reactor Sim and Daedalus

Two working, tested templates for offloading game logic from a Pygame
project into NovaLang, keeping rendering/input/the main loop in Python.
Both templates run end-to-end in this repo (their `test_*.py` files are
real, passing tests, no pygame required); `main.py` in each is a pygame
skeleton to adapt into your actual project, not something that can run in
a headless sandbox.

```
embedding_templates/
  reactor_game/
    main.py                 # pygame: window, input, rendering, the loop
    nova_bridge.py           # pygame-free: wraps Nova, no dependencies
    reactor.py                # the Reactor class (state only, no rules)
    test_reactor_logic.py      # run it: python3 test_reactor_logic.py
    nova/
      reactor_physics.nova     # tick() - temperature physics
      reactor_control.nova      # check_reactor() - warn/scram/cold-alarm rules
  daedalus_game/
    main.py
    nova_bridge.py
    test_game_logic.py          # run it: python3 test_game_logic.py
    nova/
      enemy_waves.nova           # spawn_wave/spawn_level_wave (unchanged data)
      game_logic.nova             # player, enemies, movement, collision, rules
```

## 1. The plan

**Where the NovaLang files go**: a `nova/` subfolder next to your existing
game code, one script per concern (`reactor_physics.nova`,
`reactor_control.nova`, or however you want to split it - a single file
works too, this is organizational, not required). Vendor `novalang.py`
itself into your project (it's one file, zero dependencies) rather than
reaching across repos; `nova_bridge.py` in each template has a comment
marking the one line to adjust.

**Initializing the interpreter**: once, at startup - `Nova()` is not free
to construct and there's no reason to make more than one per running
game. `nova_bridge.py`'s `NovaEngine.__init__` does this and loads every
`.nova` script with `load_file()` up front, so parsing happens once, not
per frame.

**Exposing game state** - this is the one decision that matters most, and
it depends on what your state actually *is*:

- **Pattern A - your object is already a Python class** (a `Reactor`,
  `Player` with real methods): `engine.expose("name", the_object)` (which
  calls `Nova.expose_global()`) gives NovaLang a **live, zero-copy
  proxy**. `reactor.temp`, `reactor.scram()` read and write - and call -
  the real object; nothing is converted, and both sides always agree.
  This is what `reactor_game` does.
- **Pattern B - your state is plain dicts/lists** (a `list` of enemy
  dicts, say): passing these into NovaLang - as a call argument, or via
  `expose_global`/`expose` - **converts them into new NovaLang values**.
  It's a one-time copy, not a proxy: mutating the NovaLang copy does
  nothing to the Python original, and vice versa. For state like this,
  don't fight the copy - let NovaLang own the canonical version outright
  (declare it there, mutate it there), and have Python pull a **snapshot**
  back each frame for rendering. This is what `daedalus_game` does with
  `enemies`.

Check which one your actual `Reactor`/`enemies` are before picking - it's
a five-minute look at your existing class definitions, and picking wrong
means either silently-stale state (Pattern B state exposed like Pattern
A) or needless per-frame copying (Pattern A state routed through B).

**Calling from the game loop**: `engine.call("update", dt, controls)` (or
several smaller calls - see Performance below) inside your existing
`while running:` loop, in place of whatever Python currently computes
that frame's logic.

**Input**: reading the keyboard/mouse never leaves Python - `pygame.key`,
`pygame.event.get()` stay exactly where they are. What crosses into
NovaLang is a plain dict of what's currently true (`{"left": True, ...}`),
built fresh each frame from pygame's key state. NovaLang then decides
what that input *means* (movement speed, whether it's even honored during
game-over, how far an operator can nudge reactor power) - see
`handle_input()` / `operator_increase_power()` in the templates. Keep the
dict's key named something other than `input` - it's a NovaLang built-in
(reads a line at the REPL) and can't be used as a parameter name; both
templates use `controls`.

## 2. The code

Both templates are complete and tested - read `reactor_game/main.py` and
`daedalus_game/main.py` for the full pygame-loop shape, and their
`nova/*.nova` files for the logic side. A few things worth calling out
explicitly:

- `reactor_control.nova` is **`examples/reactor_script.nova` unchanged in
  substance** - `reactor.scram()` works as a method call because Pattern
  A gives you a real bound Python method underneath. Don't rewrite this
  into free functions the way `examples/reactor_sim.nova` had to -
  that rewrite was only necessary there because that version's reactor
  had no Python object behind it at all.
- `game_logic.nova` reads Python's `nova.get`/`python.set` are **not
  used** in either template - `expose_global` covers everything both
  games need (a live object for the reactor, an owned-outright world for
  Daedalus). `python.get("mod.name")` / `python.set(...)` earn their
  keep for a different case: reaching a **Python-side utility your game
  logic wants to call by name without a pre-bound object** - e.g. a
  NovaLang script triggering `python.call("audio.play_sound", "explosion")`
  against an `audio` module you've registered with
  `nova.expose_module(audio)`. Add that if/when your logic needs to
  trigger a Python-owned side effect (sound, particle spawn, save-file
  write) - `expose_module()` is already wired into `daedalus_game`'s
  `NovaEngine` for exactly this, just unused by the template as shipped.
- **The scope barrier bites here, for real.** An early draft of
  `game_logic.nova` had `level = level + 1` inside `maybe_spawn_wave()`
  and it silently never incremented - a plain assignment inside a
  function can't reach a name declared outside it, even a top-level
  `let`, even though it reads like an ordinary global. The fix (visible
  in the current file) is keeping anything that needs reassigning-from-
  elsewhere as a **dict field** (`world.level = world.level + 1`) rather
  than a bare variable, and mutating lists in place (`pop()` everything,
  `append()` the survivors back) rather than rebinding them. Your real
  Reactor Sim/Daedalus almost certainly have bare counters like this
  (score, level, a timer) - budget time to catch this while porting each
  one, and lean on the testing strategy below to catch it when you don't.

## 3. Separation of concerns

| Stays in Python | Moves to NovaLang |
|---|---|
| Window creation, the pygame event loop | Game rules: thresholds, win/lose conditions |
| Reading keyboard/mouse state | What input *means* (speed, whether it's honored right now) |
| Drawing - sprites, shapes, HUD text, sound | Physics/movement math |
| Asset loading (images, sounds, fonts) | Enemy spawning, wave composition, AI/targeting |
| Frame timing (`clock.tick(60)`) | Collision detection and its consequences (damage, death) |
| Anything genuinely Pygame-API-shaped | Scoring, leveling, state transitions |

The dividing line in one sentence: if it touches a pygame object
(`Surface`, `Rect`, `Sound`, an event), it's Python's; if it's a decision
about what happens in the game world, it's NovaLang's.

## 4. Performance

Measured in this sandbox, with the actual templates (not the old
Stage 12 microbenchmark):

- `daedalus_game`'s `update(dt, controls)` - movement, the spawn check,
  an O(n²) collision pass, damage resolution, and building the full
  return snapshot - averaged **~0.34ms/call** (≈2,960 calls/sec) with a
  handful of enemies on screen. That's ~2% of a 60fps frame's 16.7ms
  budget.
- `reactor_game`'s two small calls (`tick()` then `check_reactor()`)
  together averaged **~0.10ms/frame** combined.

**Call once per frame with one entry point that does everything that
frame** (`update(dt, controls)`), rather than many small calls. Each
`nova.call()` has fixed dispatch overhead (a global lookup, argument
conversion); doing five small calls a frame pays that fixed cost five
times for no benefit, since NovaLang code calling its own other functions
internally is free of that overhead. Split calls out only when you
genuinely need Python to intervene *between* two phases (e.g. showing a
level-up screen between `advance_wave()` and `spawn_next_wave()`) - not
as a default structure.

The bigger performance lever than call count is **what crosses the
boundary**: Pattern A (a live proxy) costs nothing extra per frame beyond
the call itself. Pattern B (NovaLang-owned state, Python reads a
snapshot) pays a real conversion cost proportional to how much data comes
back - the measurement above already includes that cost for a few
enemies and it's negligible, but if a wave ever grows into the hundreds,
consider returning only what changed, or only what's on-screen, rather
than the full list every frame.

## 5. Testing strategy

Both `test_reactor_logic.py` and `test_game_logic.py` are real,
runnable, pygame-free tests - `python3 test_reactor_logic.py` /
`python3 test_game_logic.py` from inside each template folder. The
pattern, to apply to your own port:

1. **Keep `nova_bridge.py`-style code pygame-free.** This is what makes
   any of the rest possible - if game logic can only be exercised by
   running the actual game, you can't write a fast, deterministic test
   for it.
2. **Structural/invariant assertions for anything involving randomness.**
   `tick()` calls NovaLang's `random()`, which has no seed built-in - so
   don't assert exact numbers. Assert the *contract* instead: temperature
   never drops below the physical floor, a scrammed reactor only cools,
   power always stays in [0, 100]. See `test_physics_invariants()`.
3. **Exact-value assertions for anything deterministic.** Thresholds,
   clamping, spawn timing, and reset all produce exact, repeatable
   results - test them with real `==` checks, as most of both test files
   do.
4. **A golden-trace diff while the Python original still exists.** The
   strongest possible check, for the transition window only: pass the
   *same* pre-rolled random values into both the old Python function and
   the new NovaLang one (an extra parameter instead of letting either
   side call its own RNG), and assert their output sequences match
   exactly. `test_reactor_logic.py`'s `run_golden_trace_template()` shows
   the shape of this - do it once per piece of logic, right when you port
   it, before you delete the Python original you're diffing against.
5. **Re-run after every port**, not just once at the end - both test
   files are fast (well under a second) specifically so this is cheap
   enough to do continuously as you migrate more logic over.

## Doing this incrementally

Both templates are already scoped to "one small piece of logic" -
temperature physics for Reactor Sim, enemy spawning + movement +
collision for Daedalus - specifically so you can drop either one in
alongside your *existing* Python logic, running side by side, and migrate
function-by-function:

1. Pick one function (e.g. `Reactor.tick()`).
2. Port it to a `.nova` file, write a test for it (pygame-free) that
   checks it against the invariants/values the Python version guaranteed.
3. Wire `main.py` to call the NovaLang version instead of the Python one.
4. Play it. Confirm it feels the same.
5. Delete the now-dead Python version (or keep it commented for one
   commit as a diff reference), and pick the next function.

Repeat until `main.py` is rendering/input/the loop and nothing else -
which is exactly the shape both templates are already in.
