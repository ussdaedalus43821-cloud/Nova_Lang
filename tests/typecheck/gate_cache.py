"""
gate_cache.py - the type gate checks an import graph once per load.

    (run by tests/run_all.py station 7)

Every program that imports something passes the type gate, and the gate
type-checks it with everything it reaches. Before 2.0.0 each gate started
from nothing, so a module imported by many others was checked again for
every one of them: OmniCalc's 37 module loads ran the checker 159 times,
and startup tripled. The interpreter now keeps the results for its
lifetime, one per absolute module path.

This counts real checker runs (typechecker Program.check calls) on a
heavily shared graph - every module imports every module below it - and
requires exactly one per file. It also proves the cache never lets a
program through that a fresh check would refuse:

  * a contract broken deep in the shared graph is still refused, at the
    module that breaks it, on both engines and through the embedding API;
  * after a failed load, a fixed file is checked again, and so is every
    module that was checked against its old version.
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import novalang as nl  # noqa: E402

LAYERS = 8      # m0 .. m7; m_i imports every m_j with j < i


def write(directory, name, text):
    with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
        handle.write(text)


def shared_graph(directory, broken=None):
    """m0 exports a typed function; m_i imports all of m0..m_(i-1) and
    calls it. `broken` names the layer whose call breaks the contract.
    main.nova imports every layer. Returns main's path."""
    write(directory, "m0.nova", "export def scale(x: int) -> int {\n    return x * 2\n}\n")
    for i in range(1, LAYERS):
        lines = ['import "m{}.nova" as m{}'.format(j, j) for j in range(i)]
        argument = '"oops"' if i == broken else str(i)
        lines.append("export let v{} = m0.scale({})".format(i, argument))
        write(directory, "m{}.nova".format(i), "\n".join(lines) + "\n")
    lines = ['import "m{}.nova" as m{}'.format(i, i) for i in range(LAYERS)]
    lines.append("print(m{}.v{})".format(LAYERS - 1, LAYERS - 1))
    write(directory, "main.nova", "\n".join(lines) + "\n")
    return os.path.join(directory, "main.nova")


@contextlib.contextmanager
def counting():
    """Count typechecker Program.check calls - one per file checked."""
    program = nl.typecheck_tool().Program
    real = program.check
    calls = []

    def spy(self, source, path, *args, **kwargs):
        calls.append(path)
        return real(self, source, path, *args, **kwargs)
    program.check = spy
    try:
        yield calls
    finally:
        program.check = real


def quiet(action):
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            action()
        return out.getvalue(), None
    except nl.NovaError as error:
        return out.getvalue(), error
    except nl.NovaLangError as error:
        return out.getvalue(), error


def run_file(engine, path):
    interpreter = nl.Interpreter(engine)
    interpreter.file_stack.append(os.path.dirname(path))
    return quiet(lambda: nl.run(open(path, encoding="utf-8").read(), interpreter))


def run(check):
    scratch = tempfile.mkdtemp(prefix="nova-gate-cache-")
    try:
        main = shared_graph(scratch)
        files = LAYERS + 1
        for engine in ("vm", "tree"):
            label = "VM" if engine == "vm" else "tree-walker"
            with counting() as calls:
                out, error = run_file(engine, main)
            check(error is None and out == "{}\n".format(2 * (LAYERS - 1)),
                  "gate cache: the shared graph runs on the " + label, (out, error))
            check(len(calls) == files,
                  "gate cache: {} files are type-checked exactly {} times on the {} ({} runs)".format(
                      files, files, label, len(calls)),
                  sorted(str(p) for p in calls))
            check(len(set(calls)) == len(calls),
                  "gate cache: no file is checked twice on the " + label,
                  sorted(str(p) for p in calls))

        # One embedding session: later inputs reuse what earlier ones checked.
        nova = nl.Nova()
        with counting() as calls:
            quiet(lambda: nova.load_file(main))
            first = len(calls)
            quiet(lambda: nova.exec('import "{}" as again\nprint(again.v3)'.format(
                os.path.join(scratch, "m3.nova").replace("\\", "/"))))
        check(first == files and len(calls) == files + 1,
              "gate cache: a later input in the same session checks only itself",
              (first, len(calls)))

        # A cached result answers only for the exact source it was checked from.
        cache = nl.typecheck_tool().GateCache()
        path = os.path.join(scratch, "m0.nova")
        good = "export def scale(x: int) -> int {\n    return x * 2\n}\n"
        bad = 'export def scale(x: int) -> int {\n    return "no"\n}\n'
        with counting() as calls:
            first = cache.module(good, path, scratch)
            again = cache.module(good, path, scratch)
            changed = cache.module(bad, path, scratch)
        check(first is again and len(calls) == 2 and changed.findings and not first.findings,
              "gate cache: the same source is answered from the cache, a changed one is checked",
              (len(calls), changed.findings))

        # ... and a module whose source changed takes with it every result
        # checked against its old version: here a.nova's verdict flips.
        dependent = tempfile.mkdtemp(dir=scratch)
        write(dependent, "b.nova", "export def f(x: int) -> int {\n    return x\n}\n")
        a_source = 'import "b.nova" as b\nexport let y = b.f(1)\n'
        write(dependent, "a.nova", a_source)
        a_path, b_path = (os.path.join(dependent, name) for name in ("a.nova", "b.nova"))
        cache = nl.typecheck_tool().GateCache()
        before = cache.module(a_source, a_path, dependent)
        b_new = "export def f(x: string) -> string {\n    return x\n}\n"
        write(dependent, "b.nova", b_new)
        cache.module(b_new, b_path, dependent)
        after = cache.module(a_source, a_path, dependent)
        check(not before.findings and [f.code for f in after.findings] == ["T002"],
              "gate cache: a changed module discards the results checked against it",
              (before.findings, after.findings))

        # A contract broken in the middle of the shared graph is still refused.
        broken = tempfile.mkdtemp(dir=scratch)
        shared_graph(broken, broken=3)
        for engine in ("vm", "tree"):
            out, error = run_file(engine, os.path.join(broken, "main.nova"))
            text = str(error)
            check(error is not None and "TypeCheckError" in text and "m3.nova" in text
                  and "T002" in text and out == "",
                  "gate cache: a broken contract deep in a shared graph is refused on the "
                  + ("VM" if engine == "vm" else "tree-walker"), text[-800:])

        # After a failed load, a fixed file - and what was checked against
        # its old version - is checked again, not answered from the cache.
        stale = tempfile.mkdtemp(dir=scratch)
        write(stale, "b.nova", "export def f(x: int) -> int {\n    return x\n}\nlet crash = [][0]\n")
        write(stale, "a.nova", 'import "b.nova" as b\nexport let y = b.f(1)\n')
        importer = 'import "{}" as a\nprint(a.y)'.format(
            os.path.join(stale, "a.nova").replace("\\", "/"))
        nova = nl.Nova()
        _, error = quiet(lambda: nova.exec(importer))
        check(error is not None and "TypeCheckError" not in str(error),
              "gate cache: the stale-cache case starts with a runtime load failure", str(error))
        write(stale, "b.nova", "export def f(x: string) -> string {\n    return x\n}\n")
        out, error = quiet(lambda: nova.exec(importer))
        check(error is not None and "TypeCheckError" in str(error) and "a.nova" in str(error),
              "gate cache: after a failed load, a module checked against the old version of "
              "an import is checked again", (out, str(error)[-600:]))
        write(stale, "a.nova", 'import "b.nova" as b\nexport let y = b.f("fixed")\n')
        out, error = quiet(lambda: nova.exec(importer))
        check(error is None and out == "fixed\n",
              "gate cache: once fixed, the same session runs it", (out, str(error)[-600:]))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    failures = []

    def check(ok, label, detail=None):
        print("[{}] {}".format("ok" if ok else "FAILED", label))
        if not ok:
            failures.append(label)
            if detail is not None:
                print("        " + str(detail)[:2000])
    run(check)
    sys.exit(1 if failures else 0)
