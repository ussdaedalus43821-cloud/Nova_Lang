"""
differential.py - run one NovaLang program on both engines and compare.

    outcome(source, engine) -> (stdout, rendered error or "", exit code)

In-process and fresh each time: a new Interpreter, stdout captured, and an
error rendered exactly as novalang.py would show it. A wall-clock alarm
turns a program that does not finish into a reported failure, not a hang.
"""

import contextlib
import ctypes
import io
import os
import signal
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

import novalang as nl  # noqa: E402


class Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise Timeout()


# SIGALRM does not exist on Windows. Tests set this False to take that path
# on any platform.
HAS_SIGALRM = hasattr(signal, "SIGALRM")


@contextlib.contextmanager
def thread_deadline(seconds):
    """Raise Timeout in the calling thread once `seconds` of wall-clock time
    pass, with no signals: a timer thread asks the interpreter to raise it
    in this one, between two bytecodes. Unlike SIGALRM it cannot break into
    one long C call such as time.sleep(); the engines are pure Python, so a
    program that spins is interrupted."""
    target = ctypes.c_ulong(threading.get_ident())
    lock = threading.Lock()
    state = {"done": False, "fired": False}

    def fire():
        with lock:
            if not state["done"]:
                state["fired"] = True
                ctypes.pythonapi.PyThreadState_SetAsyncExc(target, ctypes.py_object(Timeout))

    timer = threading.Timer(seconds, fire)
    timer.daemon = True
    timer.start()
    try:
        yield
    finally:
        with lock:
            state["done"] = True
            timer.cancel()
            if state["fired"]:
                # Finished at the same instant: do not let the exception
                # surface later, in code that is no longer being timed.
                ctypes.pythonapi.PyThreadState_SetAsyncExc(target, None)


@contextlib.contextmanager
def deadline(seconds):
    """Raise Timeout if the body outlasts `seconds`."""
    if HAS_SIGALRM:
        previous = signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    else:
        with thread_deadline(seconds):
            yield


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
    chunks = source.split(CHUNK)
    try:
        with deadline(seconds):
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
    return captured.getvalue(), error, status


def compare(source):
    """(same?, tree-walker outcome, VM outcome)."""
    tree = outcome(source, "tree")
    vm = outcome(source, "vm")
    return tree == vm and tree[2] != -1, tree, vm
