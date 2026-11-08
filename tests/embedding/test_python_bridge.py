"""The python.* bridge is closed unless asked for, and what it hands over is
bounded (issue 1; docs/design/python-bridge-hardening.md).

Four things are pinned here:
  - python.* is off unless Nova(allow_python=True);
  - names that start with "_" are unreachable, to read and to write;
  - a module reached through an attribute is hidden unless it is allowed, so
    `re.enum.bltns` and its kin do not lead to builtins or sys;
  - every path the gate allows, from every allowlisted module, avoids the
    modules and builtins that would give a script code execution. That walk
    runs on each Python in the CI matrix, because module internals change
    between releases.
"""

import builtins
import contextlib
import io
from pathlib import Path
import sys
import types
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl

# What a script must never be able to reach, by identity.
FORBIDDEN_BUILTINS = ("eval", "exec", "compile", "open", "__import__", "getattr", "setattr",
                      "delattr", "globals", "locals", "vars", "input", "breakpoint", "exit", "quit")
FORBIDDEN_MODULES = ("builtins", "sys", "os", "posix", "nt", "subprocess", "importlib", "ctypes",
                     "io", "codecs", "shutil", "socket", "pickle", "marshal", "signal",
                     "multiprocessing", "threading", "_thread", "gc", "inspect")


class Private:
    def __init__(self):
        self.visible = 1
        self._secret = "private state"
        self.os = sys.modules["os"]          # a public name holding a module


def bridge(engine, **options):
    return nl.Nova(engine, allow_python=True, **options)


class BridgeContract:
    def setUp(self):
        self.nova = bridge(self.engine)

    def refuses(self, code, fragment):
        with self.assertRaises(nl.NovaLangError) as caught:
            self.nova.exec(code)
        self.assertIn(fragment, str(caught.exception))
        self.assertEqual(caught.exception.nova_error.label, "PythonError")
        self.assertEqual(self.nova.eval("6 * 7"), 42)

    # -- off by default ------------------------------------------------------

    def test_python_is_off_unless_asked_for(self):
        host = nl.Nova(self.engine)
        for call in ('python.import("math")', 'python.call("math.sqrt", 4)',
                     'python.get("math.pi")', 'python.set("x", 1)'):
            with self.subTest(call=call):
                with self.assertRaises(nl.NovaLangError) as caught:
                    host.exec(call)
                self.assertEqual(caught.exception.nova_error.label, "PythonError")
                self.assertIn("python.* is disabled", str(caught.exception))
                self.assertIn("allow_python=True", str(caught.exception))
        # The name still exists, so a script and the linter see a `python`
        # global; it only refuses. Nothing else about the host changed.
        self.assertEqual(host.eval("type(python)"), "dict")
        host.expose_global("box", Private())
        self.assertEqual(host.eval("box.visible"), 1)
        self.assertEqual(host.eval("6 * 7"), 42)

    def test_allow_python_false_is_the_same_as_not_asking(self):
        with self.assertRaises(nl.NovaLangError):
            nl.Nova(self.engine, allow_python=False).exec('python.import("math")')

    # -- the report's payloads ------------------------------------------------

    def test_dunder_walks_from_an_allowed_module_are_refused(self):
        self.nova.exec('python.import("json")')
        for path in ("json.__builtins__", "json.__loader__", "json.__spec__", "json.__dict__",
                     "json.dumps.__globals__", "json.JSONDecoder.__init__"):
            with self.subTest(path=path):
                self.refuses('python.get("{}")'.format(path), "has no attribute")
        self.refuses('python.call("json.__builtins__")', "has no attribute")
        self.refuses('python.set("json.__doc__", "x")', "private attribute")
        self.refuses('python.set("json.__builtins__.x", 1)', "has no attribute")

    def test_public_module_aliases_do_not_lead_to_builtins_or_sys(self):
        self.nova.exec('python.import("re")\npython.import("json")\npython.import("statistics")'
                       '\npython.import("collections")')
        for path in ("re.enum", "re.enum.bltns", "json.codecs", "json.codecs.builtins",
                     "json.codecs.sys", "statistics.sys", "statistics.sys.modules",
                     "collections.abc.sys"):
            with self.subTest(path=path):
                self.refuses('python.get("{}")'.format(path), "has no attribute")

    def test_nothing_ran_and_nothing_was_written(self):
        # The report's payload, harmless: it would have printed 42.
        with self.assertRaises(nl.NovaLangError):
            self.nova.exec('python.import("re")\nlet b = python.get("re.enum.bltns")\nb["eval"]("6 * 7")')
        # What does work still works.
        self.nova.exec('python.import("math")')
        self.assertEqual(self.nova.eval('python.call("math.sqrt", 81)'), 9)
        self.assertEqual(self.nova.eval('python.get("math.pi")'), __import__("math").pi)

    # -- proxies ---------------------------------------------------------------

    def test_proxy_private_names_cannot_be_read_or_written(self):
        thing = Private()
        self.nova.expose_global("thing", thing)
        self.assertEqual(self.nova.eval("thing.visible"), 1)
        for name in ("_secret", "__class__", "__dict__", "__init__"):
            with self.subTest(name=name):
                with self.assertRaises(nl.NovaLangError):
                    self.nova.eval('thing["{}"]'.format(name))
                self.assertEqual(self.nova.eval('"{}" in thing'.format(name)), False)
                self.refuses('thing["{}"] = "overwritten"'.format(name), "private attribute")
        self.assertEqual(thing._secret, "private state")
        self.assertIs(type(thing), Private)
        self.nova.exec('thing.visible = 5')
        self.assertEqual(thing.visible, 5)

    def test_proxy_hides_an_attribute_that_holds_a_module(self):
        thing = Private()
        self.nova.expose_global("thing", thing)
        self.assertEqual(self.nova.eval('"os" in thing'), False)
        self.assertEqual(self.nova.eval("keys(thing)"), ["visible"])
        with self.assertRaises(nl.NovaLangError):
            self.nova.eval("thing.os")
        self.assertIs(thing.os, sys.modules["os"])

    def test_a_module_arriving_inside_a_value_is_refused(self):
        self.nova.expose("make", lambda: {"m": sys.modules["os"]})
        self.refuses('python.call("make")', "cannot be handed to a script")
        self.nova.expose("make_list", lambda: [sys])
        self.refuses('python.call("make_list")', "cannot be handed to a script")

    def test_modules_the_host_exposes_are_granted_and_others_are_not(self):
        inner = types.ModuleType("nova_test_inner")
        inner.answer = lambda: 42
        outer = types.ModuleType("nova_test_outer")
        outer.inner = inner
        outer.shout = lambda: "hi"
        self.nova.expose_module(outer)
        self.nova.exec('python.import("nova_test_outer")')
        self.assertEqual(self.nova.eval('python.call("nova_test_outer.shout")'), "hi")
        self.refuses('python.get("nova_test_outer.inner")', "has no attribute")
        self.nova.expose_module(inner)
        self.assertEqual(self.nova.eval('python.call("nova_test_outer.inner.answer")'), 42)

    def test_printing_a_module_proxy_is_shallow(self):
        # It once recursed until the stack ran out.
        import json
        self.nova.expose_global("tool", json)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.nova.exec("print(tool)")
        self.assertEqual(out.getvalue(), "<python object module>\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.nova.exec("print([tool, 1])")
        self.assertEqual(out.getvalue(), "[<python object module>, 1]\n")


class VmBridgeTests(BridgeContract, unittest.TestCase):
    engine = "vm"


class TreeBridgeTests(BridgeContract, unittest.TestCase):
    engine = "tree"


class ReachabilityTests(unittest.TestCase):
    """Walk every path the gate allows and look for what must stay out of reach."""

    DEPTH = 4
    LIMIT = 30000

    def walk(self, gated):
        interpreter = nl.Interpreter("vm", allow_python=True)
        forbidden_objects = {id(getattr(builtins, name)): name for name in FORBIDDEN_BUILTINS
                             if hasattr(builtins, name)}
        found, seen, frontier = [], set(), []
        for name in nl.PYTHON_IMPORT_ALLOWLIST:
            module = __import__(name)
            seen.add(id(module))
            frontier.append((name, module))
        for depth in range(self.DEPTH):
            following = []
            for path, owner in frontier:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    try:
                        names = [n for n in dir(owner) if not n.startswith("_")]
                    except Exception:
                        continue
                    for name in names:
                        try:
                            if gated:
                                value = nl.bridge_lookup(owner, name, interpreter)
                                if value is nl._MISSING:
                                    continue
                            else:
                                value = getattr(owner, name)
                        except Exception:
                            continue
                        where = path + "." + name
                        if id(value) in forbidden_objects:
                            found.append("{} is builtins.{}".format(where, forbidden_objects[id(value)]))
                        if isinstance(value, types.ModuleType) and \
                                value.__name__.split(".")[0] in FORBIDDEN_MODULES:
                            found.append("{} is the module {}".format(where, value.__name__))
                        if id(value) in seen or len(seen) > self.LIMIT:
                            continue
                        if isinstance(value, (types.ModuleType, type)):
                            seen.add(id(value))
                            following.append((where, value))
            frontier = following
        return found

    def test_no_allowed_path_reaches_a_forbidden_module_or_builtin(self):
        self.assertEqual(self.walk(gated=True), [])

    def test_the_walk_would_notice_one(self):
        """Without the gate the same walk finds routes (json.codecs, ...), so a
        pass above means something. If a future Python removes every public
        alias this fails, and the hole it guarded is closed by the interpreter
        itself: delete the test then, not before."""
        routes = self.walk(gated=False)
        self.assertTrue(routes, "no ungated route to a forbidden module on this Python")


if __name__ == "__main__":
    unittest.main()
