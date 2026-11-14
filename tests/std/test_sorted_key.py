"""sorted(list, key) and sorted(list, key, descending) (M14 slice P1, L3, G-038, docs/spec/09-library.md [lib.collections]): ordering
by a key, stable on the three engines, checked against Python's sorted() on seeded random lists; and the old forms unchanged."""

import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINES = (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"]))


def nova(flags, program, folder):
    path = os.path.join(folder, "main.nova")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(program)
    return subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True,
                          timeout=600, stdin=subprocess.DEVNULL, cwd=folder, env=dict(os.environ, NOVALANG_CACHE="off"))


class Ordering(unittest.TestCase):
    def test_against_python_on_seeded_lists_on_three_engines(self):
        rng = random.Random(38)
        lists = []
        for _ in range(40):
            n = rng.randrange(0, 30)
            lists.append([[rng.randrange(0, 5), rng.choice("abcde"), i] for i in range(n)])     # many ties: stability shows
        program = "let lists = " + json.dumps(lists) + "\n" + (
            'def first(r) { return r[0] }\n'
            'def second(r) { return r[1] }\n'
            'for l in lists {\n'
            '  print(json.dumps([sorted(l, first), sorted(l, first, true), sorted(l, second), sorted(l, second, false),\n'
            '                    sorted(sorted(l, second), first)]))\n'
            '}\n')
        want = []
        for l in lists:
            want.append(json.dumps([sorted(l, key=lambda r: r[0]), sorted(l, key=lambda r: r[0], reverse=True),
                                    sorted(l, key=lambda r: r[1]), sorted(l, key=lambda r: r[1]),
                                    sorted(sorted(l, key=lambda r: r[1]), key=lambda r: r[0])]))
        with tempfile.TemporaryDirectory() as folder:
            for name, flags in ENGINES:
                done = nova(flags, program, folder)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                got = [json.dumps(json.loads(line)) for line in done.stdout.splitlines()]
                self.assertEqual(got, want, name)

    def test_keys_errors_and_the_old_forms_on_three_engines(self):
        program = ('def t(f) { try { print(f()) } catch e { print(e) } }\n'
                   'def age(p) { return p.age }\n'
                   'def name(p) { return p.n }\n'
                   'def neg(x) { return -x }\n'
                   'def big(x) { return x > 1 }\n'
                   'def head(r) { return r[0] }\n'
                   'def same(x) { return x }\n'
                   'let people = [{n: "b", age: 30}, {n: "a", age: 25}, {n: "c", age: 30}]\n'
                   'print(map(name, sorted(people, age)))\n'
                   'print(map(name, sorted(people, age, true)))\n'
                   'print(sorted(["bb", "a", "ccc"], len), sorted([3, 1, 2], neg))\n'
                   'print(sorted([3, 2, 1], big), sorted([], len), sorted([[2, "b"], [1, "z"]], head))\n'
                   'print(sorted([3, 1, 2]), sorted([3, 1, 2], true), sorted(["b", "a"], false))\n'
                   'def e1() { return sorted([1, "a"], same) }\nt(e1)\n'
                   'def e2() { return sorted([[1], [2]], same) }\nt(e2)\n'
                   'def e3() { return sorted([1], len, "x") }\nt(e3)\n'
                   'def e4() { return sorted([1], true, false) }\nt(e4)\n'
                   'def e5() { return sorted([1], len, true, 4) }\nt(e5)\n'
                   'def e6() { return sorted([1], 5) }\nt(e6)\n'
                   'def e7() { return sorted(5, len) }\nt(e7)\n'
                   'def e8() { return sorted(["a", 5], len) }\nt(e8)\n'
                   'let calls = []\n'
                   'def logged(x) {\n  append(calls, x)\n  return x\n}\n'
                   'print(sorted([3, 1, 2], logged), calls)\n')
        want = ['["a", "b", "c"]', '["b", "c", "a"]', '["a", "bb", "ccc"] [3, 2, 1]', "[1, 3, 2] [] [[1, \"z\"], [2, \"b\"]]",
                "[1, 2, 3] [3, 2, 1] [\"a\", \"b\"]",
                "TypeError: sorted()'s key function must return values that can be compared with each other",
                "TypeError: sorted()'s key function must return values that can be compared with each other",
                "TypeError: sorted()'s third argument must be true or false",
                "sorted() takes a list and an optional true or false",
                "sorted() takes a list and an optional true or false",
                "TypeError: sorted()'s second argument must be true or false",
                "TypeError: sorted() needs a list, but got a number",
                "len() needs a list, a string or a dictionary, but got a number",
                "[1, 2, 3] [3, 1, 2]"]
        with tempfile.TemporaryDirectory() as folder:
            for name, flags in ENGINES:
                done = nova(flags, program, folder)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                self.assertEqual(done.stdout.splitlines(), want, name)


if __name__ == "__main__":
    unittest.main()
