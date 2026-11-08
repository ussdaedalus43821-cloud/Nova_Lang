#!/usr/bin/env python3
"""
test_differential.py - the bytecode VM against the tree-walker, everywhere.

    python3 tests/vm/test_differential.py        (also run_all.py station 11)
    NOVA_DIFF_SEEDS=5000 python3 tests/vm/test_differential.py   (a longer soak)

The tree-walker is the reference: it is what NovaLang has always been.
Every check here runs the same program on both engines and requires the
same stdout, the same stderr (error text, carets, stack traces) and the
same exit status, byte for byte. Timestamps that log() writes are the
only thing masked.

  1. Every .nova file in the repository, through the real CLI:
     `novalang.py FILE` against `novalang.py --tree-walk FILE`.
  2. Every example under --bootstrap on both engines - novalang.nova's
     own interpreter running on top of each.
  3. Seeded random programs from generator.py, in-process (300 by
     default), aimed at scopes, closures, try/finally and errors. A
     mismatch reports its seed and the program.
  4. The embedding API (Nova.exec/eval/call/compile/load_file) on both.
  5. Regressions: tests/vm/regressions/, the cases that once made the
     engines differ, each kept so it can never come back.
  6. Coverage: between them, the generated programs and the repository
     compile to every opcode there is, so no instruction goes untested.
"""

import concurrent.futures
import glob
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import differential  # noqa: E402
import generator  # noqa: E402
import novalang as nl  # noqa: E402

NOVALANG = os.path.join(ROOT, "novalang.py")
TIMESTAMP = re.compile(r"\[\d{4}-\d\d-\d\dT[0-9:.+-]+\]")
# Programs whose output differs between two runs of the same engine.
NONDETERMINISTIC = {"examples/reactor_sim.nova": "uses random()"}
# Programs that create files in the current directory (the repository
# root), and one that counts its entries: run alone, after everything
# else, so no other program changes the directory while one of them looks.
ALONE = {"examples/file_demo.nova", "examples/stdlib_demo.nova",
         "examples/stdlib_full_test.nova"}
SEEDS = int(os.environ.get("NOVA_DIFF_SEEDS", "300"))


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def nova_files():
    for path in sorted(glob.glob(os.path.join(ROOT, "**", "*.nova"), recursive=True)):
        if "/.nova_modules/" not in path:
            yield path


def cli(args):
    try:
        done = subprocess.run([sys.executable, NOVALANG] + args, cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=300)
    except subprocess.TimeoutExpired:
        return ("timeout", "", "")
    return (done.returncode, TIMESTAMP.sub("[time]", done.stdout),
            TIMESTAMP.sub("[time]", done.stderr))


def show(tree, vm):
    import difflib
    parts = []
    for label, a, b in (("stdout", tree[1], vm[1]), ("stderr", tree[2], vm[2])):
        if a != b:
            parts.append(label + ":\n" + "".join(difflib.unified_diff(
                a.splitlines(True), b.splitlines(True), "tree-walker", "vm"))[:1500])
    if tree[0] != vm[0]:
        parts.append("exit: tree-walker {}, vm {}".format(tree[0], vm[0]))
    return "\n".join(parts)


def same(tree, vm, name):
    if tree[0] == "timeout" or vm[0] == "timeout":
        return False
    return tree[0] == vm[0] if name in NONDETERMINISTIC else tree == vm


def both(args):
    """One file's runs, one after the other (some programs write files)."""
    return cli(["--tree-walk"] + args), cli(args)


def run_all_of(paths, prefix, on_result):
    """{path: (tree-walker, vm)}, in parallel except for the ALONE ones."""
    shared = [p for p in paths if rel(p) not in ALONE]
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        jobs = {pool.submit(both, prefix + [rel(path)]): path for path in shared}
        for future in concurrent.futures.as_completed(jobs):
            path = jobs[future]
            results[path] = future.result()
            on_result(path, results[path])
    for path in paths:
        if rel(path) in ALONE:
            results[path] = both(prefix + [rel(path)])
            on_result(path, results[path])
    return results


# Runs novalang.py as __main__ (argv: repository, novalang.py, its args),
# reporting on stderr the engine bootstrap builds its Interpreter with.
ENGINE_SPY = """
import runpy, sys
sys.path.insert(0, sys.argv[1])
import bootstrap
real = bootstrap.Interpreter
def spy(engine=None, allow_python=None):
    made = real(engine, allow_python=allow_python)
    sys.stderr.write("ENGINE=" + made.engine + "\\n")
    return made
bootstrap.Interpreter = spy
script = sys.argv[2]
sys.argv = [script] + sys.argv[3:]
runpy.run_path(script, run_name="__main__")
"""


def test_bootstrap_engine(check):
    """--bootstrap must run novalang.nova on the engine asked for. Run as
    the CLI runs it - novalang.py as __main__, so `import novalang` in
    bootstrap.py is a second copy of the module - with a spy reporting
    the engine bootstrap actually builds. (It once ignored --tree-walk,
    which made the bootstrap comparison below compare the VM with itself.)"""
    for flags, wanted in (([], "vm"), (["--tree-walk"], "tree")):
        done = subprocess.run(
            [sys.executable, "-c", ENGINE_SPY, ROOT, NOVALANG] + flags
            + ["--bootstrap", "examples/math.nova"],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        used = re.findall(r"ENGINE=(\w+)", done.stderr)
        check(used == [wanted], "{}--bootstrap runs novalang.nova on the {}".format(
            " ".join(flags) + " " if flags else "", "tree-walker" if wanted == "tree" else "VM"),
            "engines used: {}\n{}".format(used, done.stderr[-500:]))


def test_files(check):
    def record(path, result, suffix=""):
        tree, vm = result
        name = rel(path)
        check(same(tree, vm, name), "{}{}: the VM matches the tree-walker".format(name, suffix),
              "comparison timed out" if "timeout" in (tree[0], vm[0]) else show(tree, vm))

    paths = list(nova_files())
    results = run_all_of(paths, [], record)
    examples = sorted(glob.glob(os.path.join(ROOT, "examples", "*.nova")))
    run_all_of(examples, ["--bootstrap"],
               lambda path, result: record(path, result, " under --bootstrap"))
    check(len(results) > 70, "every .nova file was compared ({})".format(len(results)))


def tree_walker_stack_limited():
    """True where the tree-walker cannot be trusted to reach MAX_CALL_DEPTH.

    It spends about nine Python frames per NovaLang call, and before Python
    3.11 each of those also uses native stack. On Windows, whose stack is much
    smaller than Linux's or macOS's, a program that recurses to the 1200-call
    limit overflows it and kills the whole process (docs/CI.md, "Windows
    Python 3.7: stack overflow"). Python 3.11 and later do not have the
    problem, and neither does the VM, which keeps NovaLang calls on its own
    stack. Nothing here is detected by trying it: a native overflow cannot be
    caught."""
    return sys.platform == "win32" and sys.version_info < (3, 11)


DEPTH_ERROR = "call depth of {} exceeded".format(nl.MAX_CALL_DEPTH)


def test_generated(check, limited=None):
    """Seeded programs on both engines. Where the tree-walker is
    stack-limited (see above), the programs that end in the call-depth error
    are decided on the VM alone: it runs first, and a program that ends in
    that error is not given to the tree-walker. The skip is printed and
    recorded, so it is never silent, and capped, so it cannot grow into
    hiding programs."""
    limited = tree_walker_stack_limited() if limited is None else limited
    mismatches = []
    unfinished = []
    skipped = []
    for seed in range(SEEDS):
        source = generator.generate(seed)
        if limited:
            vm = differential.outcome(source, "vm")
            if DEPTH_ERROR in vm[1] and vm[2] == 1:
                skipped.append(seed)
                continue
            tree = differential.outcome(source, "tree")
            same = tree == vm and tree[2] != -1
        else:
            same, tree, vm = differential.compare(source)
        if tree[2] == -1 or vm[2] == -1:
            unfinished.append(seed)
        elif not same:
            mismatches.append((seed, source, tree, vm))
    check(not unfinished, "every generated program finishes on both engines",
          "seeds {}".format(unfinished[:10]))
    detail = ""
    if mismatches:
        seed, source, tree, vm = mismatches[0]
        detail = "first mismatch, seed {}:\n{}\n-- tree-walker: {!r}\n-- vm: {!r}".format(
            seed, source, tree, vm)
    if not limited:
        check(not mismatches, "{} generated programs run the same on both engines ({} differ)".format(
            SEEDS, len(mismatches)), detail)
        return
    compared = SEEDS - len(skipped)
    print("  SKIPPED: the tree-walker did not run {} of {} generated programs (seeds {}): "
          "each recurses to the call-depth limit, which overflows the native stack on "
          "Windows with Python {}.{}. The VM ran them all and ended each in the "
          "depth-limit error. Compared on both engines: {}/{}.".format(
              len(skipped), SEEDS, ", ".join(map(str, skipped)),
              sys.version_info[0], sys.version_info[1], compared, SEEDS))
    check(len(skipped) <= max(1, SEEDS // 10),
          "tree-walker skipped on {} depth-limit programs ({} compared of {}; Windows, "
          "Python 3.10 or older)".format(len(skipped), compared, SEEDS),
          "more than a tenth of the programs skipped: {}".format(skipped[:20]))
    check(not mismatches, "{} of {} generated programs run the same on both engines ({} differ)".format(
        compared, SEEDS, len(mismatches)), detail)


EMBEDDING = '''
def add(a, b) {
    return a + b
}
let history = []
def remember(x) {
    append(history, x)
    return len(history)
}
'''


def test_embedding(check):
    def session(engine):
        nova = nl.Nova(engine=engine)
        seen = []
        nova.exec(EMBEDDING)
        seen.append(nova.call("add", 2, 3))
        seen.append(nova.eval("if add(1, 1) == 2 { remember(7) } else { 0 }"))
        script = nova.compile("remember(add(1, 2))")
        seen.append([script.run(nova) for _ in range(3)])
        nova.expose_global("outside", 40)
        seen.append(nova.eval("outside + 2"))
        # A global made by an earlier input, assigned in a block: the
        # compiler cannot know it exists, so this is decided when it runs.
        nova.exec("count = 1")
        nova.exec("if true { count = count + 1 }")
        nova.exec("for i = 1 to 3 { count = count + i }")
        seen.append(nova.eval("count"))
        for bad in ("nowhere + 1", "add(1)", "try { break } finally { remember(0) }", "return 3"):
            try:
                nova.exec(bad)
                seen.append("no error")
            except nl.NovaLangError as error:
                seen.append(str(error))
        path = os.path.join(tempfile.mkdtemp(prefix="nova-embed-"), "script.nova")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("let made = 6 * 7\nmade\n")
        seen.append(nova.load_file(path))
        seen.append(nova.eval("history"))
        # A live Python object is a PythonObjectProxy, a dict subclass:
        # stores and deletes through it must reach the real object (M6's
        # fast paths take only exact dicts, so it keeps the slow path).
        class Thing:
            pass
        thing = Thing()
        thing.temp = 1
        nova.expose_global("thing", thing)
        nova.exec('thing["temp"] = 5\nthing.level = thing.temp + 1\ndelete thing["absent"]')
        seen.append((thing.temp, thing.level, nova.eval('thing["level"]')))
        for bad in ("thing[3] = 1", "delete thing[true]"):
            try:
                nova.exec(bad)
                seen.append("no error")
            except nl.NovaLangError as error:
                seen.append(str(error))
        return seen
    tree, vm = session("tree"), session("vm")
    check(tree == vm, "the embedding API gives the same results and errors on both engines",
          "tree-walker: {}\nvm: {}".format(tree, vm))


def test_regressions(check):
    """tests/vm/regressions/*.py: inputs that once made the engines differ,
    each run as consecutive inputs to one interpreter (CHUNKS), with the
    output both must give (EXPECTED). The .nova regressions there are
    already compared with every other .nova file."""
    import importlib.util
    import contextlib
    import io
    found = 0
    for path in sorted(glob.glob(os.path.join(HERE, "regressions", "*.py"))):
        spec = importlib.util.spec_from_file_location("regression", path)
        case = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(case)
        for engine in ("tree", "vm"):
            out = io.StringIO()
            interpreter = nl.Interpreter(engine)
            with contextlib.redirect_stdout(out):
                for chunk in case.CHUNKS:
                    nl.run(chunk, interpreter)
            check(out.getvalue() == case.EXPECTED, "{} on the {}".format(
                rel(path), "tree-walker" if engine == "tree" else "VM"),
                "expected {!r}, got {!r}".format(case.EXPECTED, out.getvalue()))
        found += 1
    check(found > 0, "the regression cases were run ({})".format(found))


def test_coverage(check):
    used = set()

    def walk(code):
        used.update(nl.OPCODES[op] for op in code.ops)
        for constant in code.constants:
            if isinstance(constant, nl.CodeObject):
                walk(constant)
    for seed in range(SEEDS):
        walk(nl.compile_source(generator.generate(seed)))
    for path in nova_files():
        try:
            walk(nl.compile_source(open(path, encoding="utf-8").read()))
        except nl.NovaError:
            pass
    missing = sorted(set(nl.OPCODES) - used)
    check(not missing, "the compared programs use every opcode", missing)


def run(check):
    for test in (test_bootstrap_engine, test_files, test_generated, test_embedding,
                 test_regressions, test_coverage):
        try:
            test(check)
        except Exception as problem:  # noqa: BLE001
            check(False, "{} raised {}: {}".format(test.__name__, type(problem).__name__, problem))


def main():
    failures = []

    def check(ok, label, detail=None):
        print("[{}] {}".format("ok" if ok else "FAILED", label))
        if not ok:
            failures.append(label)
            if detail:
                print("        " + str(detail)[:4000].replace("\n", "\n        "))
    run(check)
    print()
    print("All differential tests passed." if not failures else
          "{} differential test(s) failed.".format(len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
