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


def type_check_graph(target_path, allow=None):
    """Lines describing every type error in `target_path` and the modules
    it imports, or [] if there are none (or the target cannot be read or
    parsed - novalang.nova reports those problems itself). `allow(path)`
    limits which modules the walk may read (the restricted profile's import grants)."""
    try:
        with open(target_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        ast = novalang.Parser(novalang.Lexer(source).tokenize()).parse()
    except (OSError, UnicodeDecodeError, NovaError, RecursionError):
        return []          # novalang.nova reports a text it cannot read, or one nested too deeply, itself
    if not (ast.annotated or ast.imports):
        return []
    lines = novalang.typecheck_tool().check_file_graph(target_path, allow)
    return ["TypeCheckError: " + line for line in lines]


def nova_literal(value):
    """A Python value (str, bool, int, list, dict) as NovaLang source text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return nova_string_literal(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(nova_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join("{}: {}".format(nova_string_literal(key), nova_literal(item))
                               for key, item in value.items()) + "}"
    raise TypeError("cannot write {!r} as NovaLang".format(value))


def sandbox_config(settings):
    """The engine's sandbox settings (Capabilities.settings) as the dictionary novalang.nova's
    configure_sandbox() reads: every setting present, so the engine need not default any."""
    config = {"profile": settings.get("profile", "trusted"), "limits": settings.get("limits", {}),
              "deterministic": bool(settings.get("deterministic", False)),
              "seed": settings.get("seed", 0),
              "clock_start": "{:.9f}".format(float(settings.get("clock_start", 0.0)))}
    for name in ("read", "write", "import_from", "env", "python"):
        config[name] = list(settings.get(name, ()))
    for name in ("clock", "random", "stdin", "process", "regex"):
        config[name] = bool(settings.get(name, False))
    return config


def run_bootstrap(target_path, engine_path=DEFAULT_ENGINE, script_args=None, engine=None,
                  allow_python=False, sandbox=None):
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

    # The self-hosted interpreter reads the target and its imports itself,
    # out of sight of novalang.py's type gate, so the whole import graph
    # is type-checked here, before novalang.nova ever sees it.
    # In the restricted profile the walk reads only what the program could itself import: the
    # target, and modules whose real path lies inside an import grant, judged before the file is
    # opened (the same rule the engine applies, [sbx.paths]). A module outside the grants is left
    # unchecked here and refused by the engine when the program imports it (D-045).
    restricted = bool(sandbox) and sandbox.get("profile") == "restricted"
    configured = restricted or bool(sandbox and sandbox.get("deterministic"))
    if restricted:
        roots = novalang.Capabilities(**sandbox).roots["import"]

        def granted(path):
            real = novalang.real_path(path)
            return real is not None and any(novalang.inside_folder(real, root) for root in roots)

        refusal = type_check_graph(target_path, granted)
    else:
        refusal = type_check_graph(target_path)
    if refusal:
        print("\n".join(refusal), file=sys.stderr)
        return 1

    program = engine_source
    # Where the engine finds the standard modules (`import "std:..."`), the one place it needs the host's layout.
    program += "\nSTD[\"dir\"] = {}\n".format(nova_string_literal(novalang.STD_DIR))
    if configured:
        program += "\nconfigure_sandbox({})\n".format(nova_literal(sandbox_config(sandbox)))
    program += "\nrun_file({})\n".format(nova_string_literal(target_path))

    # `engine` ("vm" or "tree") is passed in, never read from novalang's
    # DEFAULT_ENGINE: when novalang.py runs as a script it is __main__, and
    # `import novalang` here is a second copy that never saw --tree-walk.
    # `allow_python` is passed in for the same reason as `engine`: the flag was
    # read by the __main__ copy of novalang.py, not by this module's copy.
    # novalang.nova forwards python.* to this interpreter's own `python`, so
    # the one switch covers the program it runs.
    if restricted:
        # The engine that runs novalang.nova stays trusted (it reads files for the program), but
        # the Python bridge it forwards to the program is limited to the granted modules.
        allow_python = bool(sandbox.get("python"))
    interpreter = Interpreter(engine, allow_python=allow_python)
    if restricted:
        interpreter.python_override = tuple(sandbox.get("python", ()))
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
        print("usage: bootstrap.py [--allow-python] <target.nova> [script args...]", file=sys.stderr)
        return 2
    args = argv[1:]
    allow_python = False
    if args and args[0] == "--allow-python":
        allow_python = True
        args = args[1:]
        if not args:
            print("usage: bootstrap.py [--allow-python] <target.nova> [script args...]", file=sys.stderr)
            return 2
    return run_bootstrap(args[0], script_args=args[1:], allow_python=allow_python)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
