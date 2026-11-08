"""Run one conformance case on one of the three engines and report what it did.

The three engines are the bytecode VM and the tree-walker (both in
novalang.py, run in-process) and the self-hosted interpreter (novalang.nova,
run through `novalang.py --bootstrap`, in a subprocess). All three are reduced
to the same observable result:

    {"output": [lines printed], "error": "Label: message" or "",
     "error_line": 1-based line of the error's position, or None,
     "exit": process exit status}

The error is the label and message only. The source excerpt, the caret and
the stack trace that follow it are a report format, not part of the language
(docs/spec/04-errors.md), and the self-hosted interpreter's differ.
"""

import contextlib
import io
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang  # noqa: E402

ENGINES = ("vm", "tree", "bootstrap", "policy")

# The policy dialect is a separate language (ADR 0004): its cases run only on the
# policy engine, and the three NovaLang engines run no case of that profile.
POLICY_DIRECTORY = ROOT / "dialects" / "policy"

# A report's headline: "NovaError: division by zero", "PythonError: ...".
HEADLINE = re.compile(r"^([A-Za-z][A-Za-z0-9]*): (.*)$")


def line_of(source, position):
    """The 1-based line that character offset `position` is on."""
    if position is None:
        return None
    spans = novalang.line_spans(source)
    position = max(0, min(position, len(source)))
    number = 0
    while number < len(spans) - 1 and position >= spans[number + 1][0]:
        number += 1
    return number + 1


def lines_of(text):
    """Printed text as a list of lines; the newline that ends the last is not
    an extra empty line."""
    if text == "":
        return []
    parts = text.split("\n")
    if parts[-1] == "":
        parts.pop()
    return parts


def write_files(folder, source, files):
    """The case's module files and its program (main.nova) in `folder`."""
    for name, text in dict(files or {}, **{"main.nova": source}).items():
        path = Path(folder).joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


@contextlib.contextmanager
def patched_environment(env):
    """The case's `env` variables set for the run, and put back after it."""
    saved = {name: os.environ.get(name) for name in (env or {})}
    try:
        for name, value in (env or {}).items():
            os.environ[name] = value
        yield
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def run_in_process(source, engine, files=None, env=None, stdin="", args=None, allow_python=False):
    with patched_environment(env):
        if files is None:
            return run_in_process_in(source, engine, None, stdin, args, allow_python)
        with tempfile.TemporaryDirectory(prefix="nova-conformance-") as folder:
            write_files(folder, source, files)
            here = os.getcwd()
            os.chdir(folder)
            try:
                return run_in_process_in(source, engine, os.path.realpath(folder), stdin, args,
                                         allow_python)
            finally:
                os.chdir(here)


def run_in_process_in(source, engine, folder, stdin="", args=None, allow_python=False):
    out = io.StringIO()
    error, line, status = "", None, 0
    interpreter = novalang.Interpreter(engine, allow_python=allow_python)
    if folder is not None:
        interpreter.file_stack.append(folder)       # as run_source does for a file
    real_stdin, real_args = sys.stdin, novalang.SCRIPT_ARGS
    sys.stdin = io.StringIO(stdin or "")
    novalang.SCRIPT_ARGS = list(args or [])
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                novalang.run(source, interpreter)
            except novalang.NovaError as problem:
                message = problem.message
                if problem.label == "ImportError":
                    # What follows the first line names places on this machine
                    # (the folders searched, a nested report): host-defined.
                    message = message.split("\n")[0]
                error = "{}: {}".format(problem.label, message)
                line = line_of(source, problem.position)
                status = 1
            except SystemExit as stop:
                status = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
            except RecursionError:
                error, status = "NovaError: the interpreter ran out of stack", 1
            except Exception as problem:  # noqa: BLE001 - a Python error is a finding, shown as one
                error = "InternalError: {}: {}".format(type(problem).__name__, problem)
                status = 70
    finally:
        sys.stdin, novalang.SCRIPT_ARGS = real_stdin, real_args
    return {"output": lines_of(out.getvalue()), "error": error, "error_line": line, "exit": status}


def run_bootstrap(source, files=None, env=None, stdin="", args=None, allow_python=False, timeout=120):
    with tempfile.TemporaryDirectory(prefix="nova-conformance-") as folder:
        path = Path(folder) / "case.nova"
        if files is None:
            path.write_bytes(source.encode("utf-8"))
        else:
            path = Path(folder) / "main.nova"
            write_files(folder, source, files)
        try:
            done = subprocess.run(
                [sys.executable, str(ROOT / "novalang.py")] + (["--allow-python"] if allow_python else [])
                + ["--bootstrap", str(path)] + list(args or []),
                cwd=folder, input=(stdin or "").encode("utf-8"), capture_output=True, timeout=timeout,
                env=dict(os.environ, PYTHONUTF8="1", **(env or {})),
            )
        except subprocess.TimeoutExpired:
            return {"output": [], "error": "InternalError: timed out", "error_line": None, "exit": 70}
    stderr = done.stderr.decode("utf-8", "replace")
    error = ""
    for line in stderr.splitlines():
        match = HEADLINE.match(line)
        if match and not line.startswith(" "):
            error = line
            break
    if "Traceback (most recent call last)" in stderr:
        error = "InternalError: " + stderr.strip().splitlines()[-1]
    return {"output": lines_of(done.stdout.decode("utf-8", "replace").replace("\r\n", "\n")),
            "error": error, "error_line": None, "exit": done.returncode}


def run(source, engine, files=None, env=None, stdin="", args=None, allow_python=False):
    """`files` maps relative paths (with `/`) to text: the modules the program
    imports, or any file it reads, written beside it (as main.nova) in a folder
    of their own that is the working directory. `env` sets environment
    variables, `stdin` is what `input()` reads, `args` is what `args()` returns."""
    if engine == "bootstrap":
        return run_bootstrap(source, files, env, stdin, args, allow_python)
    return run_in_process(source, engine, files, env, stdin, args, allow_python)


def run_policy(case):
    """A policy-dialect case on the policy engine (dialects/policy/).

    The result has the same shape as for NovaLang. The error is the engine's own
    text, `line N: message` (docs/spec/12-policy-syntax.md, [pol.errors]); `error_line` is
    not used. `host_functions` names the host functions the case binds; each one
    records its call as `name(arguments as print writes them)` in `host_calls`
    and returns nothing. `files` are the modules `import` can find."""
    import random
    if str(POLICY_DIRECTORY) not in sys.path:
        sys.path.insert(0, str(POLICY_DIRECTORY))
    import nova_evaluator
    import nova_vm
    files = case.get("files") or {}
    machine = nova_vm.NovaVM(random.Random(case.get("seed", 12345)), module_reader=files.get)
    calls = []
    for name in case.get("host_functions", []):
        machine.register_function(
            name, (lambda n: lambda args: calls.append(
                n + "(" + ", ".join(nova_evaluator.text(a) for a in args) + ")"))(name))
    ok = machine.eval(case["source"], case["name"])
    return {"output": machine.drain_output(), "error": machine.error, "error_line": None,
            "exit": 0 if ok else 1, "host_calls": calls}


def policy_value(value):
    """A policy value as JSON: a function is its display text, nothing else changes."""
    import nova_evaluator
    if isinstance(value, nova_evaluator.NovaFunction):
        return nova_evaluator.text(value)
    if isinstance(value, list):
        return [policy_value(item) for item in value]
    if isinstance(value, dict):
        return {key: policy_value(item) for key, item in value.items()}
    return value


class ReactorModel:
    """The reactor game's host, as far as the rule engine can tell (docs/spec/15-policy-reactor.md).

    It registers the eight host functions with their effects on the engine, and keeps the few
    pieces of host state that decide the inputs the policy sees on the next tick: the scram latch,
    the time it latched, and the game-over, victory and meltdown flags. What the case supplies as
    inputs is what the plant and the operator provide (time, the measurements, the rods,
    `operator_scram`); `scram`, `scram_elapsed`, `game_over`, `victory` and `meltdown` are the
    host's and are added here."""

    NAMES = ("log", "alarm", "scram", "reset_trip", "meltdown", "victory", "inject_fault", "clear_fault")

    def __init__(self, machine, calls, text):
        self.machine, self.calls, self.text = machine, calls, text
        self.reset()
        for name in self.NAMES:
            machine.register_function(name, self.make(name))

    def reset(self):
        self.scram, self.scram_t = False, 0.0
        self.game_over = self.victory = self.meltdown = False
        self.scram_requested = self.trip_reset = False

    def make(self, name):
        effect = getattr(self, "fn_" + name, None)

        def call(args):
            self.calls.append(name + "(" + ", ".join(self.text(a) for a in args) + ")")
            if effect is not None:
                effect(args)
            return None
        return call

    def end_run(self):
        self.game_over = True
        for key, value in (("game_over", True), ("meltdown", self.meltdown), ("victory", self.victory),
                           ("running", False)):
            self.machine.set_global(key, value)

    def fn_scram(self, args):
        if not self.scram:
            self.scram_requested = True
            self.machine.set_global("scram", True)

    def fn_reset_trip(self, args):
        self.trip_reset = True
        self.machine.set_global("scram", False)

    def fn_meltdown(self, args):
        if not self.meltdown:
            self.meltdown = True
            self.end_run()

    def fn_victory(self, args):
        if not self.victory:
            self.victory = True
            self.end_run()

    def fn_inject_fault(self, args):
        if args:
            self.machine.inject_fault(self.text(args[0]))

    def fn_clear_fault(self, args):
        self.machine.clear_fault()

    def tick(self, dt, inputs, faults):
        given = dict(inputs)
        given.update({"scram": self.scram, "scram_elapsed": (given.get("t", 0.0) - self.scram_t) if self.scram else 0.0,
                      "game_over": self.game_over, "victory": self.victory, "meltdown": self.meltdown})
        given["operator_scram"] = bool(given.get("operator_scram", False))
        self.scram_requested = self.trip_reset = False
        ok = self.machine.tick(dt, given, faults)
        if ok:
            if self.scram_requested and not self.scram:
                self.scram, self.scram_t = True, given.get("t", 0.0)
            elif self.trip_reset and self.scram:
                self.scram = False
        return ok


def run_policy_engine(case):
    """A policy-dialect case that drives the rule engine step by step
    (docs/spec/14-policy-engine.md). `engine` is {"seed": n, "watch": [global names],
    "steps": [...]}; a step is one of
        {"tick": {"dt": s, "inputs": {...}, "faults": bool}}
        {"inject_fault": name}   {"clear_fault": true}   {"reset": seed}
        {"call": [name, args...]}   {"set": {name: value}}   {"describe": true}
    and, with `"host": "reactor"`, the engine runs under the reactor game's host model (ReactorModel,
    below) in place of the plain recording host functions. The case's `results` has one entry per step:
        {"ok": bool, "error": text, "output": [...], "host_calls": [...],
         "watch": {name: value}, "value": result of a call}
    The case's own output, error, exit and host_calls are those of loading the program."""
    import copy
    import random
    if str(POLICY_DIRECTORY) not in sys.path:
        sys.path.insert(0, str(POLICY_DIRECTORY))
    import nova_evaluator
    import nova_vm
    spec = copy.deepcopy(case["engine"])   # scripts change the lists and dictionaries they are given
    files = case.get("files") or {}
    machine = nova_vm.NovaVM(random.Random(spec.get("seed", 12345)), module_reader=files.get)
    calls = []
    reactor = None
    if spec.get("host") == "reactor":
        reactor = ReactorModel(machine, calls, nova_evaluator.text)
    else:
        for name in case.get("host_functions", []):
            machine.register_function(
                name, (lambda n: lambda args: calls.append(
                    n + "(" + ", ".join(nova_evaluator.text(a) for a in args) + ")"))(name))
    ok = machine.eval(case["source"], case["name"])
    result = {"output": machine.drain_output(), "error": machine.error, "error_line": None,
              "exit": 0 if ok else 1, "host_calls": list(calls)}
    del calls[:]
    results = []
    if ok:
        for step in spec.get("steps", []):
            entry = {"ok": True, "value": None}
            if "tick" in step:
                tick = step["tick"]
                if reactor is not None:
                    entry["ok"] = reactor.tick(tick.get("dt", 0.05), dict(tick.get("inputs", {})),
                                               tick.get("faults", True))
                else:
                    entry["ok"] = machine.tick(tick.get("dt", 0.05), dict(tick.get("inputs", {})),
                                               tick.get("faults", True))
            elif "inject_fault" in step:
                entry["ok"] = machine.inject_fault(step["inject_fault"])
            elif "clear_fault" in step:
                machine.clear_fault()
            elif "reset" in step:
                entry["ok"] = machine.reset(step["reset"])
                if reactor is not None:
                    reactor.reset()
            elif "call" in step:
                machine.error = ""
                entry["value"] = policy_value(machine.call_function(step["call"][0], list(step["call"][1:])))
                entry["ok"] = machine.error == ""
            elif "describe" in step:
                entry["value"] = policy_value(machine.describe())
            elif "set" in step:
                for name, value in step["set"].items():
                    machine.set_global(name, value)
            entry["error"] = "" if entry["ok"] else machine.error
            entry["output"] = machine.drain_output()
            entry["host_calls"] = list(calls)
            del calls[:]
            entry["watch"] = {name: policy_value(machine.get_global(name)) for name in spec.get("watch", [])}
            if "value" in entry and "call" not in step and "describe" not in step:
                del entry["value"]
            results.append(entry)
    result["results"] = results
    return result


def run_case(case, engine):
    if engine == "policy":
        return run_policy_engine(case) if "engine" in case else run_policy(case)
    files = case.get("files")
    if files is None and case.get("profile") in ("host", "modules"):
        files = {}      # these cases touch the file system: a folder of their own
    if "embedding" in case:
        return run_embedding(case, engine)
    return run(case["source"], engine, files, case.get("env"),
               case.get("stdin", ""), case.get("args"), bool(case.get("allow_python")))


def render_argument(value):
    """How a host function's argument is written in `host_calls`: as print writes it,
    and a function as `<function>` (how a host names its callables is its own)."""
    if callable(value):
        return "<function>"
    return novalang.format_value(novalang.to_nova_value(value))


def decode(value):
    """A fixture value as the host would hold it. `{"$digits": n}` is the integer
    10 ** (n - 1), which has n digits, so a case can hand over a huge number
    without writing it out."""
    if isinstance(value, dict) and list(value) == ["$digits"]:
        return 10 ** (value["$digits"] - 1)
    return value


def python_object(attributes, methods, name, calls):
    """A host object: plain attributes, and methods that record their calls."""
    obj = types.SimpleNamespace(**{key: decode(value) for key, value in attributes.items()})
    for method, spec in (methods or {}).items():
        setattr(obj, method, host_function("{}.{}".format(name, method), spec, calls))
    return obj


def host_function(name, spec, calls):
    """A function the host provides, as the case describes it, that records each call.
    spec: {"returns": value} | {"echo": true} | {"sum": true} | {"raises": text}
    | {"apply": n} (calls its first argument on its second, n times, and returns the result)."""
    def function(*arguments):
        calls.append("{}({})".format(name, ", ".join(render_argument(a) for a in arguments)))
        if "raises" in spec:
            raise RuntimeError(spec["raises"])
        if spec.get("echo"):
            return arguments[0] if arguments else None
        if spec.get("sum"):
            return sum(arguments)
        if "apply" in spec:
            value = arguments[1]
            for _ in range(spec["apply"]):
                value = arguments[0](value)
            return value
        return spec.get("returns")
    return function


def encode(value):
    """A result as the case records it: an integer too long to write out becomes
    `{"$digits": n}`, the counterpart of decode()."""
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) >= 10 ** 30:
        return {"$digits": len(str(abs(value)))}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    return value


def nova_error_text(problem):
    return "{}: {}".format(problem.nova_error.label, problem.nova_error.message)


def run_steps(nova, steps, results):
    """What the host does after the program: call a script function, evaluate source, or
    run a compiled script several times. Each step adds an entry to `results`."""
    for step in steps:
        try:
            if step[0] == "call":
                results.append({"value": encode(nova.call(step[1], *[decode(a) for a in step[2:]]))})
            elif step[0] == "run_compiled":
                compiled = nova.compile(step[1])
                results.append({"value": [encode(compiled.run(nova)) for _ in range(step[2])]})
            else:
                results.append({"value": encode(nova.eval(step[1]))})
        except novalang.NovaLangError as problem:
            results.append({"error": nova_error_text(problem)})
        except SystemExit as stop:
            results.append({"exit": stop.code if isinstance(stop.code, int) else 0})


def run_embedding(case, engine):
    """Run a case the way a host that embeds the language would: bind what the
    case's `embedding` fixture says, run the program, then do what its `after`
    list says, recording the host functions called and each step's result."""
    fixture, calls, results = case["embedding"], [], []
    out = io.StringIO()
    error, status = "", 0
    nova = novalang.Nova(engine, allow_python=bool(case.get("allow_python")))
    try:
        for name, value in fixture.get("globals", {}).items():
            nova.expose_global(name, decode(value))
        for name, spec in fixture.get("functions", {}).items():
            nova.expose_global(name, host_function(name, spec, calls))
        for name, item in fixture.get("objects", {}).items():
            nova.expose_global(name, python_object(item.get("attrs", {}), item.get("methods"), name, calls))
        for module in fixture.get("modules", []):
            nova.expose_module(module)
        for name, item in fixture.get("registry", {}).items():
            nova.expose(name, python_object(item.get("attrs", {}), item.get("methods"), name, calls))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                nova.exec(case["source"])
            except novalang.NovaLangError as problem:
                error, status = nova_error_text(problem), 1
            except SystemExit as stop:
                status = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)
            run_steps(nova, fixture.get("after", []), results)
            if "other_engine_after" in fixture:
                run_steps(novalang.Nova(engine), fixture["other_engine_after"], results)
    except novalang.NovaLangError as problem:
        error, status = nova_error_text(problem), 1
    return {"output": lines_of(out.getvalue()), "error": error, "error_line": None, "exit": status,
            "host_calls": calls, "results": results}
