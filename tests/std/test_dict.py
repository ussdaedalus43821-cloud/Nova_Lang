"""std:dict (M14 slice P1, L4, decision D-P6, docs/spec/09-library.md [lib.std-dict]): a missing value without a new global name or
a `nothing` literal, on the three engines."""

import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import novalang  # noqa: E402

ENGINES = (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"]))
DICT = novalang.NATIVE_FUNCTIONS["dict"]


class _Interpreter:
    counting = False


def call(name, *args):
    return DICT[name].implementation(list(args), None, _Interpreter())


def nova(flags, program, folder):
    path = os.path.join(folder, "main.nova")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(program)
    return subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True,
                          timeout=600, stdin=subprocess.DEVNULL, cwd=folder, env=dict(os.environ, NOVALANG_CACHE="off"))


class Get(unittest.TestCase):
    def test_a_present_key_gives_its_value_and_a_missing_one_the_fallback(self):
        d = {"a": 1, "b": None, "c": [1]}
        self.assertEqual(call("get", d, "a", 0), 1)
        self.assertEqual(call("get", d, "x", 0), 0)
        self.assertEqual(call("get", d, "x", "none"), "none")
        self.assertIs(call("get", d, "c", None), d["c"])           # the value itself, not a copy
        self.assertEqual(call("get", {}, "", 7), 7)

    def test_a_stored_value_wins_over_the_fallback_whatever_it_is(self):
        for value in (0, "", False, [], {}):
            self.assertEqual(call("get", {"k": value}, "k", "fallback"), value)

    def test_errors(self):
        for bad in (5, "s", [], None, True):
            with self.assertRaises(novalang.NovaError) as caught:
                call("get", bad, "k", 0)
            self.assertIn("dict.get() needs a dictionary, but got", caught.exception.message)
            self.assertEqual(caught.exception.label, "TypeError")
        with self.assertRaises(novalang.NovaError) as caught:
            call("get", {}, 1, 0)
        self.assertEqual(caught.exception.message, "dict.get() needs a string for the key, but got a number")


class GetPath(unittest.TestCase):
    def test_nested_fields(self):
        event = {"user": {"name": "ana", "geo": {"country": "PT"}}, "tags": ["x"]}
        self.assertEqual(call("get_path", event, ["user", "geo", "country"], "?"), "PT")
        self.assertEqual(call("get_path", event, ["user", "geo", "city"], "?"), "?")
        self.assertEqual(call("get_path", event, ["nope", "geo"], "?"), "?")
        self.assertEqual(call("get_path", event, ["tags", "0"], "?"), "?")             # only dictionaries are walked
        self.assertEqual(call("get_path", event, ["user", "name", "first"], "?"), "?")  # a string has no fields
        self.assertIs(call("get_path", event, [], "?"), event)

    def test_errors(self):
        with self.assertRaises(novalang.NovaError) as caught:
            call("get_path", [], ["a"], 0)
        self.assertIn("dict.get_path() needs a dictionary, but got a list", caught.exception.message)
        with self.assertRaises(novalang.NovaError) as caught:
            call("get_path", {}, "a", 0)
        self.assertEqual(caught.exception.message, "dict.get_path() needs a list of keys for the path, but got a string")
        with self.assertRaises(novalang.NovaError) as caught:
            call("get_path", {"a": {}}, ["a", 2], 0)
        self.assertEqual(caught.exception.message, "dict.get_path() needs the keys of the path to be strings, and key 2 is a number")


class Engines(unittest.TestCase):
    def test_three_engines(self):
        program = ('import "std:dict" as dict\n'
                   'let line = {ip: "10.0.0.1", user: {name: "ana"}}\n'
                   'print(dict.get(line, "ip", "-"), dict.get(line, "status", "-"), dict.get(line, "status", 0) + 1)\n'
                   'print(dict.get_path(line, ["user", "name"], "?"), dict.get_path(line, ["user", "id"], "?"))\n'
                   'print(type(dict), sorted(keys(dict)))\n'
                   'try { dict.get([], "a", 0) } catch e { print(e) }\n'
                   'let get = 5\nprint(get)\n')
        with tempfile.TemporaryDirectory() as folder:
            for name, flags in ENGINES:
                done = nova(flags, program, folder)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                self.assertEqual(done.stdout.splitlines(), ["10.0.0.1 - 1", "ana ?", 'dict ["get", "get_path"]',
                                                            "TypeError: dict.get() needs a dictionary, but got a list", "5"], name)


if __name__ == "__main__":
    unittest.main()
