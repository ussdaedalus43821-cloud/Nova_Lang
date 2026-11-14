"""The stable-surface test (docs/spec/STABLE.md, M13 plan section 6.1).

tests/api/stable-surface.json is the recorded public surface (tests/api/surface.py builds the live one
from the source). This test compares the two:

* **A removal, or a change to something stable, fails the test unless the major version moved** since
  the record was written. That is what makes "removed only in a major release" a rule a build can
  fail, not a promise.
* **Any other difference fails too** (an addition, a change to a `provisional` standard module, a new
  default) until the record is rewritten in the same change with `--update`, so every change to the
  surface is something a reviewer sees in the diff of stable-surface.json.

    python3 tests/api/test_stable_surface.py --update     rewrite the record from the source
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import surface  # noqa: E402

RECORD = os.path.join(HERE, "stable-surface.json")


def major(version):
    return int(version.split(".")[0])


def flatten(value, path=()):
    """{path: leaf} for every leaf of nested dicts; lists are leaves compared as a whole."""
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            out.update(flatten(inner, path + (key,)))
        return out
    return {path: value}


def compare(recorded, live):
    """(breaking, other): paths removed or changed in a stable part, and paths added or changed in a provisional part."""
    old, new = flatten(recorded), flatten(live)
    old.pop(("version",), None)
    new.pop(("version",), None)
    provisional = {name for name, entry in recorded.get("std_modules", {}).items() if entry["tier"] == "provisional"}
    provisional |= {name for name, entry in live.get("std_modules", {}).items() if entry["tier"] == "provisional"}

    def is_provisional(path):
        return len(path) >= 2 and path[0] == "std_modules" and path[1] in provisional

    breaking, other = [], []
    for path in sorted(set(old) | set(new)):
        if old.get(path, KeyError) == new.get(path, KeyError):
            continue
        if is_provisional(path):
            other.append(path)
        elif path == ("manifest_keys",) and set(old[path]) <= set(new.get(path, [])):
            other.append(path)            # a key the tool now reads is an addition; a key it stopped reading is not
        elif path not in new or path in old:
            breaking.append(path)         # removed, or present before and different now
        else:
            other.append(path)            # added
    return breaking, other


def dotted(paths):
    return ["/".join(p) for p in paths]


class StableSurface(unittest.TestCase):
    def test_the_live_surface_agrees_with_the_record(self):
        with open(RECORD, encoding="utf-8") as handle:
            recorded = json.load(handle)
        live = surface.build()
        breaking, other = compare(recorded, live)
        if breaking and major(live["version"]) == major(recorded["version"]):
            self.fail("breaking change to the stable surface without a new major version "
                      "(recorded for {}, running {}): {}".format(recorded["version"], live["version"], ", ".join(dotted(breaking))))
        if breaking or other:
            self.fail("the public surface changed; review it and run `python3 tests/api/test_stable_surface.py --update` "
                      "in the same change: {}".format(", ".join(dotted(breaking + other))))

    def test_the_predefined_names_are_the_ones_recorded(self):
        # The list of predefined globals and json members is written by hand in surface.py;
        # the interpreter itself says whether it is true.
        import tempfile
        program = 'print(json.dumps(sorted(keys(json))))\nprint(PI > 3, E > 2)\n'
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "p.nova")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(program)
            done = subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py"), path],
                                  capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stderr)
        first, second = done.stdout.splitlines()
        self.assertEqual(json.loads(first), surface.build()["json_members"])
        self.assertEqual(second, "true true")

    def test_a_removal_is_breaking_and_an_addition_is_not(self):
        base = {"version": "2.2.0", "builtins": {"a": {"arity": 1}, "b": {"arity": 2}}, "std_modules": {}}
        removed = {"version": "2.2.0", "builtins": {"a": {"arity": 1}}, "std_modules": {}}
        changed = {"version": "2.2.0", "builtins": {"a": {"arity": 2}, "b": {"arity": 2}}, "std_modules": {}}
        added = {"version": "2.2.0", "builtins": {"a": {"arity": 1}, "b": {"arity": 2}, "c": {"arity": 0}}, "std_modules": {}}
        self.assertEqual(compare(base, removed)[0], [("builtins", "b", "arity")])
        self.assertEqual(compare(base, changed)[0], [("builtins", "a", "arity")])
        self.assertEqual(compare(base, added), ([], [("builtins", "c", "arity")]))
        self.assertEqual(compare(base, base), ([], []))

    def test_a_provisional_module_may_change_but_a_stable_one_may_not(self):
        def mod(tier, exports):
            return {"version": "2.2.0", "std_modules": {"m": {"tier": tier, "capabilities": [], "exports": exports}}}
        self.assertEqual(compare(mod("provisional", ["a"]), mod("provisional", ["b"]))[0], [])
        self.assertTrue(compare(mod("stable", ["a", "b"]), mod("stable", ["a"]))[0])
        # promoting a module changes its tier, which is an addition of stability, not a break of the exports
        self.assertEqual(compare(mod("provisional", ["a"]), mod("stable", ["a"]))[0], [])


if __name__ == "__main__":
    if "--update" in sys.argv:
        with open(RECORD, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(surface.build(), indent=1, ensure_ascii=False, sort_keys=True) + "\n")
        print("wrote", RECORD)
    else:
        unittest.main()
