"""
differential.py - run one NovaLang program on both engines and compare.

    outcome(source, engine) -> (stdout, rendered error or "", exit code)

In-process and fresh each time: a new Interpreter, stdout captured, and an
error rendered exactly as novalang.py would show it. A wall-clock alarm
turns a program that does not finish into a reported failure, not a hang.
"""

import contextlib
import io
import os
import signal
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import novalang as nl  # noqa: E402


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout()


CHUNK = "\n# --- chunk ---\n"


def outcome(source, engine, seconds=20):
    """A program split by CHUNK lines runs as consecutive inputs to one
    interpreter, the way the REPL and Nova.exec() run them: each chunk is
    compiled on its own, so the globals earlier chunks made are only known
    when it runs. An error ends its chunk (shown in the output, as the REPL
    shows it), and the next chunk carries on."""
    captured = io.StringIO()
    error = ""
    status = 0
    previous = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(seconds)
    chunks = source.split(CHUNK)
    try:
        interpreter = nl.Interpreter(engine)
        with contextlib.redirect_stdout(captured):
            for index, chunk in enumerate(chunks):
                try:
                    nl.run(chunk, interpreter)
                except nl.NovaError as problem:
                    if index < len(chunks) - 1:
                        print("<chunk error>", problem.render(chunk))
                    else:
                        error = problem.render(chunk)
                        status = 1
                except (nl.VMError, Timeout):
                    raise
                except Exception as problem:  # noqa: BLE001 - a Python error is an outcome too
                    # Not a NovaError (e.g. printing an integer too long for
                    # Python): both engines must still fail the same way.
                    error = "<python {}: {}>".format(type(problem).__name__, problem)
                    status = 2
                    break
    except Timeout:
        error, status = "<did not finish in {} s>".format(seconds), -1
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return captured.getvalue(), error, status


def compare(source):
    """(same?, tree-walker outcome, VM outcome)."""
    tree = outcome(source, "tree")
    vm = outcome(source, "vm")
    return tree == vm and tree[2] != -1, tree, vm
