#!/usr/bin/env python3
"""
bootstrap.py - loads novalang.nova (NovaLang's own Lexer, Parser and
Interpreter, written in NovaLang) and uses it to run a target .nova file.

This script does not implement any part of the language itself - that is
the point of self-hosting. All it does is:

    1. Read novalang.nova's source.
    2. Append one line calling its run_file(path) entry point with the
       target file's path.
    3. Hand the combined source to novalang.py's own Lexer/Parser/
       Interpreter, exactly as it would run any other .nova program.

novalang.nova then reads the target file itself (through the same `read()`
built-in any NovaLang program uses), tokenizes it, parses it and runs it -
using an interpreter written in NovaLang, not in Python. novalang.py's
engine is only ever asked to run novalang.nova; it never sees the target
program's source directly.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import novalang  # noqa: E402
from novalang import Interpreter, NovaError, run  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ENGINE = os.path.join(HERE, "novalang.nova")


def nova_string_literal(text):
    """Turn a Python string into a NovaLang double-quoted string literal."""
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return '"' + escaped + '"'


def run_bootstrap(target_path, engine_path=DEFAULT_ENGINE, script_args=None):
    """Run `target_path` through the self-hosted interpreter defined in
    `engine_path`. `script_args` become what the target's own args() call
    sees - the Stage 11 standard-library built-in, read from novalang.py's
    module-level SCRIPT_ARGS the same way a directly-run program's would be.
    Returns the process exit code."""
    novalang.SCRIPT_ARGS = list(script_args or [])
    try:
        with open(engine_path, "r", encoding="utf-8") as handle:
            engine_source = handle.read()
    except OSError as problem:
        print("bootstrap: cannot read {}: {}".format(engine_path, problem), file=sys.stderr)
        return 1

    target_path = os.path.abspath(target_path)
    program = engine_source + "\nrun_file({})\n".format(nova_string_literal(target_path))

    interpreter = Interpreter()
    # novalang.nova tracks "the directory of whichever file is currently
    # executing" itself, in its own FILE_STACK - run_file() pushes the
    # target's directory before running it, so the target's own relative
    # imports resolve against the target, not against novalang.nova. This
    # host-level Interpreter is only ever asked to run novalang.nova itself.
    try:
        run(program, interpreter)
    except NovaError as error:
        print(error.render(program), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n(stopped)", file=sys.stderr)
        return 130
    except RecursionError:
        print(
            "NovaError: the self-hosted interpreter ran out of stack "
            "(it supports shallower recursion than the host)",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv):
    if len(argv) < 2:
        print("usage: bootstrap.py <target.nova> [script args...]", file=sys.stderr)
        return 2
    target_path = argv[1]
    return run_bootstrap(target_path, script_args=argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
