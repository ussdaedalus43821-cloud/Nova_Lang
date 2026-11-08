"""Public embedding contracts, exercised independently on both engines."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bootstrap
import novalang as nl


class Box:
    def __init__(self, value=7):
        self.value = value
        self.child = types.SimpleNamespace(value=11)

    def apply(self, callback, value):
        return callback(value)


class ReadOnly:
    @property
    def value(self):
        return 7


class RejectingWrite:
    def __init__(self, error=ValueError):
        self.error = error
        self.attempts = 0

    @property
    def value(self):
        return 7

    @value.setter
    def value(self, value):
        self.attempts += 1
        raise self.error("write rejected")


class RejectingRead:
    @property
    def value(self):
        raise ValueError("read rejected")


class EmbeddingContract:
    def setUp(self):
        self.nova = nl.Nova(self.engine, allow_python=True)

    def assert_nova_error(self, operation, fragment, label=None):
        with self.assertRaises(nl.NovaLangError) as caught:
            operation()
        self.assertIn(fragment, str(caught.exception))
        self.assertIsInstance(caught.exception.nova_error, nl.NovaError)
        if label is not None:
            self.assertEqual(caught.exception.nova_error.label, label)
        self.assertEqual(self.nova.interpreter.call_stack, [])
        self.assertEqual(self.nova.eval("6 * 7"), 42)

    def test_returned_callback_accepts_nested_python_values(self):
        self.nova.exec("def identity(value) { return value }")
        callback = self.nova.eval("identity")
        value = {"data": (1, 2, 3), "flag": True, "empty": None, 4: "four"}
        expected = {"data": [1, 2, 3], "flag": True, "empty": None, "4": "four"}
        self.assertEqual(callback(value), expected)
        self.assertEqual(self.nova.call("identity", value), expected)
        self.assertIs(callback(True), True)
        self.assertIsNone(callback(None))

    def test_returned_callbacks_keep_their_closures(self):
        self.nova.exec("def make(base) { def add(x) { return base + x } return add }")
        first = self.nova.call("make", 10)
        second = self.nova.call("make", 100)
        self.assertEqual([first(3), second(3), first(4)], [13, 103, 14])

    def test_callbacks_are_converted_inside_returned_containers(self):
        self.nova.exec("def inc(x) { return x + 1 }\n"
                       "def bundle() { return {one: inc, many: [inc]} }")
        for value in (self.nova.call("bundle"), self.nova.compile("bundle()").run(self.nova)):
            self.assertEqual(value["one"](6), 7)
            self.assertEqual(value["many"][0](8), 9)

    def test_builtin_can_be_returned_as_a_python_callback(self):
        callback = self.nova.eval("sqrt")
        self.assertEqual(callback(81), 9)
        self.assert_nova_error(lambda: callback(), "argument")

    def test_callback_arity_and_runtime_failures_are_wrapped(self):
        self.nova.exec("def divide(x) { return 12 / x }")
        callback = self.nova.eval("divide")
        self.assert_nova_error(lambda: callback(), "argument")
        self.assert_nova_error(lambda: callback(0), "zero")
        self.assertEqual(callback(3), 4)

    def test_callback_errors_do_not_leak_state_between_instances(self):
        program = "let state = {count: 0}\ndef next() { state.count = state.count + 1; return state.count }"
        other = nl.Nova(self.engine, allow_python=True)
        self.nova.exec(program)
        other.exec(program)
        first = self.nova.eval("next")
        second = other.eval("next")
        self.assert_nova_error(lambda: first(99), "argument")
        self.assertEqual([first(), first(), second(), first()], [1, 2, 1, 3])

    def test_exposed_python_function_can_accept_nova_callback(self):
        self.nova.exec("def twice(x) { return x * 2 }")
        self.nova.expose_global("apply", lambda callback, value: callback(value))
        self.assertEqual(self.nova.eval("apply(twice, 5)"), 10)

    def test_registry_function_can_accept_nova_callback(self):
        self.nova.exec("def twice(x) { return x * 2 }")
        self.nova.expose("apply", lambda callback, value: callback(value))
        self.assertEqual(self.nova.eval('python.call("apply", twice, 6)'), 12)

    def test_nested_callbacks_reach_python_functions(self):
        self.nova.exec("def inc(x) { return x + 1 }")
        self.nova.expose_global("use", lambda payload: payload["callbacks"][0](40))
        self.assertEqual(self.nova.eval("use({callbacks: [inc]})"), 41)

    def test_python_argument_callable_can_accept_a_nova_callback(self):
        self.nova.exec("def inc(x) { return x + 1 }\n"
                       "def run_host(host) { return host(inc, 8) }")
        self.assertEqual(self.nova.call("run_host", lambda callback, value: callback(value)), 9)

    def test_python_method_can_accept_a_nova_callback(self):
        self.nova.exec("def inc(x) { return x + 1 }")
        self.nova.expose_global("box", Box())
        self.assertEqual(self.nova.eval("box.apply(inc, 3)"), 4)

    def test_python_host_can_catch_a_callback_failure_and_recover(self):
        self.nova.exec('def fail() { throw("callback failed") }')
        def recover(callback):
            try:
                callback()
            except nl.NovaLangError as error:
                self.assertIn("callback failed", str(error))
                return 42
            self.fail("callback did not fail")
        self.nova.expose_global("recover", recover)
        self.assertEqual(self.nova.eval("recover(fail)"), 42)
        self.assertEqual(self.nova.interpreter.call_stack, [])

    def test_uncaught_callback_failure_can_be_caught_by_nova(self):
        self.nova.exec('def fail() { throw("callback failed") }')
        self.nova.expose_global("invoke", lambda callback: callback())
        result = self.nova.eval('let message = ""\ntry { invoke(fail) } catch e { message = e }\nmessage')
        self.assertIn("callback failed", result)
        self.assertEqual(self.nova.interpreter.call_stack, [])

    def test_returned_python_callable_keeps_callback_support(self):
        self.nova.exec("def inc(x) { return x + 1 }")
        self.nova.expose_global("factory", lambda: lambda callback, value: callback(value))
        self.assertEqual(self.nova.eval("factory()(inc, 10)"), 11)

    def test_returned_python_object_can_store_a_nova_callback(self):
        box = Box()
        self.nova.expose_global("factory", lambda: box)
        self.nova.exec("def inc(x) { return x + 1 }\nlet made = factory()\nmade.callback = inc")
        self.assertEqual(box.callback(8), 9)
        self.assertIs(self.nova.eval("made"), box)

    def test_registry_get_object_can_store_a_nova_callback(self):
        box = Box()
        self.nova.expose("box", box)
        self.nova.exec('def inc(x) { return x + 1 }')
        self.nova.exec('let made = python.get("box")\nmade.callback = inc')
        self.assertEqual(box.callback(8), 9)

    def test_plain_python_data_is_copied_but_objects_remain_live(self):
        self.nova.exec('def update(data, box) { data["items"][0] = 99; box.value = 12; return data }')
        original = {"items": [1, 2]}
        box = Box()
        self.assertEqual(self.nova.call("update", original, box), {"items": [99, 2]})
        self.assertEqual(original, {"items": [1, 2]})
        self.assertEqual(box.value, 12)

    def test_registry_nested_reads_and_writes(self):
        box = Box()
        self.nova.expose("box", box)
        self.assertEqual(self.nova.eval('python.get("box.child.value")'), 11)
        self.nova.exec('python.set("box.child.value", 23)')
        self.assertEqual(box.child.value, 23)
        self.nova.exec('python.set("answer", {items: [1, 2]})')
        self.assertEqual(self.nova.registry["answer"], {"items": [1, 2]})

    def test_missing_attributes_and_registry_roots_are_controlled(self):
        self.nova.expose("box", Box())
        self.nova.expose_global("box", Box())
        for source, fragment in [('box.missing', 'missing'),
                                 ('python.get("box.missing")', 'no attribute'),
                                 ('python.set("box.missing.value", 1)', 'no attribute'),
                                 ('python.get("absent.value")', 'not available'),
                                 ('python.set("absent.value", 1)', 'not available')]:
            with self.subTest(source=source):
                self.assert_nova_error(lambda: self.nova.eval(source), fragment)
        self.assertNotIn("absent", self.nova.registry)

    def test_read_only_property_writes_are_wrapped(self):
        box = ReadOnly()
        self.nova.expose("box", box)
        self.nova.expose_global("box", box)
        for source in ('box.value = 1', 'box["value"] = 1', 'python.set("box.value", 1)'):
            with self.subTest(source=source):
                self.assert_nova_error(lambda: self.nova.exec(source), "PythonError:", "PythonError")
                self.assertEqual(box.value, 7)

    def test_rejected_property_writes_are_catchable_and_attempted_once(self):
        for error in (ValueError, RuntimeError):
            for source in ('box.value = 1', 'box["value"] = 1', 'python.set("box.value", 1)'):
                with self.subTest(error=error, source=source):
                    box = RejectingWrite(error)
                    self.nova.expose("box", box)
                    self.nova.expose_global("box", box)
                    result = self.nova.eval('let message = ""\ntry { ' + source
                                            + ' } catch e { message = e }\nmessage')
                    self.assertIn("PythonError:", result)
                    self.assertIn("write rejected", result)
                    self.assertEqual(box.attempts, 1)
                    self.assertEqual(box.value, 7)

    def test_failed_property_reads_are_wrapped(self):
        box = RejectingRead()
        self.nova.expose("box", box)
        self.nova.expose_global("box", box)
        for source in ('box.value', 'box["value"]', 'python.get("box.value")'):
            with self.subTest(source=source):
                self.assert_nova_error(lambda: self.nova.eval(source), "read rejected", "PythonError")

    def test_failed_intermediate_property_access_during_write_is_wrapped(self):
        self.nova.expose("box", RejectingRead())
        self.assert_nova_error(lambda: self.nova.exec('python.set("box.value.child", 1)'),
                               "read rejected", "PythonError")

    def test_python_callable_errors_have_consistent_wrapping(self):
        def fail():
            raise ValueError("host failed")
        self.nova.expose_global("fail", fail)
        self.nova.expose("fail", fail)
        for source in ('fail()', 'python.call("fail")'):
            with self.subTest(source=source):
                self.assert_nova_error(lambda: self.nova.eval(source), "ValueError: host failed", "PythonError")

    def test_python_control_flow_exceptions_are_not_swallowed(self):
        def stop():
            raise SystemExit(7)
        self.nova.expose_global("stop", stop)
        with self.assertRaises(SystemExit) as caught:
            self.nova.eval("stop()")
        self.assertEqual(caught.exception.code, 7)
        self.assertEqual(self.nova.interpreter.call_stack, [])

    def test_nan_and_infinity_reach_the_host_as_nova_errors(self):
        """floor/ceil/round/sleep/sin of NaN or infinity once leaked a raw
        ValueError or OverflowError to the host (issue 3). The values come from
        num() of a decimal too long for a float; json.loads refuses them (D-022)."""
        inf = 'num("1" + "0" * 400 + ".0")'
        nan = '({0} - {0})'.format(inf)
        for call in ("floor", "ceil", "round", "sleep"):
            for value, shown in ((nan, "nan"), (inf, "inf")):
                with self.subTest(call=call, value=shown):
                    self.assert_nova_error(lambda: self.nova.eval("{}({})".format(call, value)),
                                           "{}() needs a finite number, but got {}".format(call, shown),
                                           "TypeError")
        for call in ("sin", "cos", "tan"):
            with self.subTest(call=call):
                self.assert_nova_error(lambda: self.nova.eval("{}({})".format(call, inf)),
                                       "{}() needs a finite number, but got inf".format(call), "TypeError")
        for header in ("0 to " + inf, nan + " to 3", "0 to 3 step " + nan):
            with self.subTest(header=header):
                self.assert_nova_error(lambda: self.nova.exec("for i = {} {{ break }}".format(header)),
                                       "must be a finite number")
        self.assertEqual(self.nova.eval("floor(2.5) + ceil(2.5) + round(2.6)"), 8)

    def test_allowlist_and_explicit_module_exposure_are_preserved(self):
        for name in ("os", "subprocess", "nova_test_service"):
            with self.subTest(name=name):
                self.assert_nova_error(lambda: self.nova.exec('python.import("' + name + '")'),
                                       "not on the list", "PythonError")
                self.assertNotIn(name, self.nova.registry)
        self.nova.exec('python.import("math")\npython.import("math")')
        self.assertEqual(self.nova.eval('python.call("math.sqrt", 81)'), 9)
        module = types.ModuleType("nova_test_service")
        module.answer = lambda: 42
        self.nova.expose_module(module)
        self.nova.exec('python.import("nova_test_service")')
        self.assertEqual(self.nova.eval('python.call("nova_test_service.answer")'), 42)


class VmEmbeddingTests(EmbeddingContract, unittest.TestCase):
    engine = "vm"


class TreeEmbeddingTests(EmbeddingContract, unittest.TestCase):
    engine = "tree"


class BootstrapBoundaryTests(unittest.TestCase):
    def test_property_failures_match_direct_and_bootstrap(self):
        source = '''let message = ""
try { python.set("box.value", 1) } catch e { message = e }
print(message)
'''
        expected = "PythonError: python.set(): ValueError: write rejected\n"
        with tempfile.TemporaryDirectory(prefix="nova-embed-bootstrap-") as folder:
            path = Path(folder) / "boundary.nova"
            path.write_text(source, encoding="utf-8")
            for engine in ("vm", "tree"):
                with self.subTest(engine=engine):
                    direct = nl.Nova(engine, allow_python=True)
                    direct.expose("box", RejectingWrite())
                    out = io.StringIO()
                    with contextlib.redirect_stdout(out):
                        direct.exec(source)
                    self.assertEqual(out.getvalue(), expected)
                    def make_interpreter(selected=None, allow_python=None):
                        interpreter = nl.Interpreter(selected, allow_python=allow_python)
                        interpreter.python_registry["box"] = RejectingWrite()
                        return interpreter
                    out = io.StringIO()
                    with patch.object(bootstrap, "Interpreter", make_interpreter), \
                            contextlib.redirect_stdout(out):
                        status = bootstrap.run_bootstrap(str(path), engine=engine, allow_python=True)
                    self.assertEqual(status, 0)
                    self.assertEqual(out.getvalue(), expected)


if __name__ == "__main__":
    unittest.main()
