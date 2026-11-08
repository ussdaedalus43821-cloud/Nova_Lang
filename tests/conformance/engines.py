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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang  # noqa: E402

ENGINES = ("vm", "tree", "bootstrap")

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


def run_in_process(source, engine):
    out = io.StringIO()
    error, line, status = "", None, 0
    interpreter = novalang.Interpreter(engine)
    real_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                novalang.run(source, interpreter)
            except novalang.NovaError as problem:
                error = "{}: {}".format(problem.label, problem.message)
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
        sys.stdin = real_stdin
    return {"output": lines_of(out.getvalue()), "error": error, "error_line": line, "exit": status}


def run_bootstrap(source, timeout=120):
    with tempfile.TemporaryDirectory(prefix="nova-conformance-") as folder:
        path = Path(folder) / "case.nova"
        path.write_bytes(source.encode("utf-8"))
        try:
            done = subprocess.run(
                [sys.executable, str(ROOT / "novalang.py"), "--bootstrap", str(path)],
                cwd=folder, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                env=dict(os.environ, PYTHONUTF8="1"),
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


def run(source, engine):
    if engine == "bootstrap":
        return run_bootstrap(source)
    return run_in_process(source, engine)
