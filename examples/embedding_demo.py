#!/usr/bin/env python3
"""
examples/embedding_demo.py - the Python side of Stage 12's embedding demo.

Run: python3 examples/embedding_demo.py
(from the repository root, or anywhere - it locates novalang.py itself)

Loads examples/embedding.nova with a "host" object exposed to it, so the
file's `python.call("host.greet", ...)` succeeds this time (it fails
gracefully, inside its own try/catch, when that file is run standalone).
Afterwards, calls a function *defined inside* embedding.nova back from
Python with Nova.call() - the other half of the bridge.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from novalang import Nova, NovaLangError  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


class Host:
    """A small Python object exposed to the NovaLang script - stand-in for
    whatever a real embedding program (Reactor Sim, Daedalus, ...) exposes."""

    def greet(self, who):
        return "Hello from Python, {}!".format(who)


def main():
    nova = Nova()
    # embedding.nova reaches this through python.call("host.greet", ...),
    # the explicit-registry form of the bridge, so it needs expose() here
    # rather than expose_global() - see reactor_sim_integration.py for the
    # other style, where expose_global() lets the script write bare
    # `reactor.temp` and `reactor.scram()` with no python.* wrapper at all.
    nova.expose("host", Host())

    script_path = os.path.join(HERE, "embedding.nova")
    nova.load_file(script_path)

    # Now call a function embedding.nova defined, from Python, with a
    # Python argument, getting a Python value back.
    fahrenheit = nova.call("celsius_to_fahrenheit", 0)
    print("Python called celsius_to_fahrenheit(0) ->", fahrenheit)

    # A Python-side error inside a Python function NovaLang calls arrives
    # in NovaLang as a catchable PythonError (see embedding.nova's own
    # try/catch); a NovaLang-side error surfaces here as NovaLangError,
    # not a raw NovaError, so this file need not import NovaLang's own
    # error type to handle it - demonstrated with a deliberate mistake:
    try:
        nova.eval("this is not valid NovaLang (")
    except NovaLangError as error:
        print("caught a NovaLang-side error as a Python exception:", error)


if __name__ == "__main__":
    main()
