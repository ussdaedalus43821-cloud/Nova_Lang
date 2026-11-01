#!/usr/bin/env python3
"""
tests/run_all.py - the Andon cord. Any failure stops the line (exit 1).

    python3 tests/run_all.py            everything
    python3 tests/run_all.py --quick    skip the slow bootstrap stations (4-5)

Stations, in order:

  1. fmt golden     tests/fmt/X.nova formats to exactly X.expected.nova,
                    and every expected file is already a fixed point.
  2. lint golden    tests/lint/X.nova lints to exactly X.expected.
  3. fmt poka-yoke  every .nova file in the repo formats with all of the
                    formatter's own checks passing (same AST, same
                    comments, idempotent).
  4. parity         every example gives the same stdout and exit status
                    run directly and through --bootstrap (CONTRIBUTING.md).
  5. formatted      the whole repo is formatted into a scratch copy, and
     parity         every example is re-run there - directly, and through
                    the *formatted* novalang.nova - and must match the
                    original runs. This is the proof that formatting the
                    self-hosted interpreter keeps bootstrap parity.

  6. python        every runnable Python program under examples/ - the
     programs     embedding demos and the embedding-template test suites -
                  exits 0. Any other .py file there must be listed in
                  PYTHON_EXEMPT with the reason it is not run, so a new
                  script cannot slip past the line unnoticed.

  7. types        nova-typecheck's operator and built-in rules agree with
                  the real interpreter (tests/typecheck/crosscheck.py);
                  tests/typecheck/pass/ checks clean and runs the same on
                  both engines; every tests/typecheck/fail/ file gives
                  exactly its .expected findings and is refused - without
                  running a single line - by every way in: the CLI,
                  --bootstrap, an import from an untyped file, and the
                  embedding API; and every other annotated .nova file in
                  the repo checks clean, so none can bypass the checker.

Stations 4-5 compare output byte for byte; timestamps that `log()` stamps
on stderr are the only thing masked, and only stdout is compared, because
the two engines word their error messages (stderr) differently on purpose.
"""

import concurrent.futures
import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOLS = os.path.join(ROOT, "tools")
sys.path.insert(0, TOOLS)

import importlib.util  # noqa: E402


def load(filename):
    spec = importlib.util.spec_from_file_location(
        filename[:-3].replace("-", "_"), os.path.join(TOOLS, filename)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fmt = load("nova-fmt.py")
lint = load("nova-lint.py")

# Examples whose stdout legitimately differs between two runs of the *same*
# engine, so only their exit status is compared.
NONDETERMINISTIC = {
    "examples/reactor_sim.nova": "uses random()",
}

# Python programs the line runs (each from its own directory, as their
# docs say to run them) and that must exit 0.
PYTHON_PROGRAMS = [
    "examples/embedding_demo.py",
    "examples/reactor_sim_integration.py",
    "examples/daedalus_integration.py",
    "examples/embedding_templates/reactor_game/test_reactor_logic.py",
    "examples/embedding_templates/daedalus_game/test_game_logic.py",
    "examples/particle_engine_selftest.py",
]

# Python files under examples/ that the line does not run, and why.
PYTHON_EXEMPT = {
    "examples/ecs_demo.py": "interactive pygame window",
    "examples/embedding_templates/reactor_game/main.py": "interactive pygame window",
    "examples/embedding_templates/daedalus_game/main.py": "interactive pygame window",
    "examples/embedding_templates/reactor_game/nova_bridge.py": "library, tested by its suite",
    "examples/embedding_templates/daedalus_game/nova_bridge.py": "library, tested by its suite",
    "examples/embedding_templates/reactor_game/reactor.py": "library, tested by its suite",
    "examples/particle_engine.py": "library, tested by particle_engine_selftest.py",
}

TIMESTAMP = re.compile(r"\[\d{4}-\d\d-\d\dT[0-9:.+-]+\]")


class Line:
    def __init__(self):
        self.failures = []
        self.passed = 0

    def check(self, ok, label, detail=""):
        if ok:
            self.passed += 1
        else:
            self.failures.append(label)
            print("  ANDON  " + label)
            if detail:
                for row in detail.rstrip().splitlines()[:20]:
                    print("         " + row)


def read(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def nova_files(base):
    found = [os.path.join(base, "novalang.nova")]
    for folder in ("examples", "lib"):
        found += sorted(glob.glob(os.path.join(base, folder, "**", "*.nova"), recursive=True))
    return found


def rel(path, base=ROOT):
    return os.path.relpath(path, base).replace(os.sep, "/")


# -- stations 1-3 ------------------------------------------------------------

def station_fmt_golden(line):
    print("1. formatter golden files")
    for source_path in sorted(glob.glob(os.path.join(HERE, "fmt", "*.nova"))):
        if source_path.endswith(".expected.nova"):
            continue
        expected_path = source_path[:-len(".nova")] + ".expected.nova"
        expected = read(expected_path)
        try:
            actual = fmt.format_source(read(source_path))
        except Exception as problem:  # noqa: BLE001 - any failure stops the line
            line.check(False, rel(source_path), repr(problem))
            continue
        line.check(actual == expected, rel(source_path) + " matches its .expected.nova",
                   diff(expected, actual))
        line.check(fmt.format_source(expected) == expected,
                   rel(expected_path) + " is a fixed point")


def station_lint_golden(line):
    print("2. linter golden files")
    for source_path in sorted(glob.glob(os.path.join(HERE, "lint", "*.nova"))):
        expected = read(source_path[:-len(".nova")] + ".expected")
        findings, parsed = lint.lint_source(read(source_path))
        actual = "".join(
            lint.format_finding(rel(source_path), parsed, finding) + "\n" for finding in findings
        )
        line.check(actual == expected, rel(source_path) + " gives its .expected findings",
                   diff(expected, actual))


def station_fmt_repo(line):
    print("3. formatter self-checks on every .nova file in the repo")
    for path in nova_files(ROOT):
        try:
            fmt.format_source(read(path))
            line.check(True, rel(path))
        except Exception as problem:  # noqa: BLE001
            line.check(False, rel(path) + " formats safely", str(problem))


def diff(expected, actual):
    import difflib
    return "".join(difflib.unified_diff(
        expected.splitlines(True), actual.splitlines(True), "expected", "actual"
    ))


# -- stations 4-5 ------------------------------------------------------------

BOOTSTRAP_WITH_ENGINE = (
    "import sys; sys.path.insert(0, sys.argv[1]); import bootstrap; "
    "sys.exit(bootstrap.run_bootstrap(sys.argv[2], engine_path=sys.argv[3]))"
)


def run(command, cwd):
    try:
        done = subprocess.run(
            command, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return ("timeout", "")
    return (done.returncode, TIMESTAMP.sub("[time]", done.stdout))


def host(example, base):
    return run([sys.executable, os.path.join(ROOT, "novalang.py"), example], base)


def bootstrap(example, base, engine):
    return run([sys.executable, "-c", BOOTSTRAP_WITH_ENGINE, ROOT, example, engine], base)


def same(a, b, example):
    if example in NONDETERMINISTIC:
        return a[0] == b[0]
    return a == b


def examples(base):
    return sorted(rel(path, base) for path in glob.glob(os.path.join(base, "examples", "*.nova")))


def formatted_copy():
    """A scratch mirror of the whole repo (examples look around their
    working directory, e.g. listdir("."), so nothing may be missing), with
    every .nova file in it rewritten by the formatter."""
    scratch = os.path.join(tempfile.mkdtemp(prefix="nova-fmt-parity-"), "repo")
    shutil.copytree(ROOT, scratch, symlinks=True)
    for path in nova_files(scratch):
        source = read(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(fmt.format_source(source))
    return scratch


def station_parity(line):
    print("4. host vs --bootstrap parity, and 5. the same on a formatted repo")
    scratch = formatted_copy()
    original_engine = os.path.join(ROOT, "novalang.nova")
    formatted_engine = os.path.join(scratch, "novalang.nova")
    jobs = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            # One example's four runs go one after another (some examples
            # write files, so two of its runs must never overlap); different
            # examples run side by side.
            def four_runs(example):
                return {
                    "host": host(example, ROOT),
                    "boot": bootstrap(example, ROOT, original_engine),
                    "fmt host": host(example, scratch),
                    "fmt boot": bootstrap(example, scratch, formatted_engine),
                }
            for example in examples(ROOT):
                jobs[example] = pool.submit(four_runs, example)
            for example, future in jobs.items():
                results = future.result()
                reference = results["host"]
                for name in ("boot", "fmt host", "fmt boot"):
                    line.check(
                        same(reference, results[name], example),
                        "{}: host == {}".format(example, name),
                        "host exit {}, {} exit {}\n".format(
                            reference[0], name, results[name][0]
                        ) + diff(reference[1], results[name][1]),
                    )
            stdlib = jobs["examples/stdlib_full_test.nova"].result()["fmt boot"][1]
            line.check(
                "All standard library tests passed." in stdlib,
                "stdlib_full_test passes through the formatted novalang.nova",
            )
    finally:
        shutil.rmtree(os.path.dirname(scratch), ignore_errors=True)


def station_python(line):
    print("6. Python programs under examples/")
    present = {
        rel(path) for path in glob.glob(os.path.join(ROOT, "examples", "**", "*.py"), recursive=True)
    }
    for path in sorted(present - set(PYTHON_PROGRAMS) - set(PYTHON_EXEMPT)):
        line.check(False, path + " is neither run by the line nor listed in PYTHON_EXEMPT")
    for path in sorted((set(PYTHON_PROGRAMS) | set(PYTHON_EXEMPT)) - present):
        line.check(False, path + " is listed in run_all.py but no longer exists")

    def run_one(program):
        folder, name = os.path.split(os.path.join(ROOT, program))
        try:
            done = subprocess.run(
                [sys.executable, name], cwd=folder, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            return "timeout", ""
        return done.returncode, done.stdout + done.stderr

    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        results = dict(zip(PYTHON_PROGRAMS, pool.map(run_one, PYTHON_PROGRAMS)))
    for program, (status, output) in results.items():
        line.check(status == 0, "{} exits 0".format(program),
                   "exit {}\n{}".format(status, output[-2000:]))


SENTINEL = "this line must never run"

EMBED_LOAD = (
    "import sys; sys.path.insert(0, sys.argv[1]); import novalang\n"
    "try:\n"
    "    novalang.Nova().load_file(sys.argv[2])\n"
    "except novalang.NovaLangError as error:\n"
    "    print(error, file=sys.stderr)\n"
    "    sys.exit(1)\n"
)


def annotated(path):
    sys.path.insert(0, ROOT)
    import novalang
    source = read(path)
    return novalang.Parser(novalang.Lexer(source).tokenize()).parse().annotated


def station_types(line):
    print("7. type checker")
    sys.path.insert(0, os.path.join(HERE, "typecheck"))
    import crosscheck
    crosscheck.check(line)

    novalang_py = os.path.join(ROOT, "novalang.py")

    def python(*args):
        done = subprocess.run([sys.executable] + list(args), cwd=ROOT,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=600)
        return done.returncode, done.stdout, done.stderr

    def cli(*args):
        return python(novalang_py, *args)

    def embed(path):
        return python("-c", EMBED_LOAD, ROOT, path)

    for path in sorted(glob.glob(os.path.join(HERE, "typecheck", "pass", "*.nova"))):
        name = rel(path)
        status, out, err = cli("--typecheck", name)
        line.check(status == 0 and not out, name + " type-checks clean", out + err)
        direct = cli(name)
        booted = cli("--bootstrap", name)
        line.check(direct[0] == 0, name + " runs", direct[2])
        line.check(direct[:2] == booted[:2], name + " runs the same under --bootstrap",
                   diff(direct[1], booted[1]) + booted[2])

    scratch = tempfile.mkdtemp(prefix="nova-typecheck-")
    try:
        for path in sorted(glob.glob(os.path.join(HERE, "typecheck", "fail", "*.nova"))):
            name = rel(path)
            expected = read(path[:-len(".nova")] + ".expected")
            status, out, err = cli("--typecheck", name)
            line.check(status == 1 and out == expected, name + " gives its .expected findings",
                       diff(expected, out) + err)
            line.check(SENTINEL in read(path), name + " starts with the never-run sentinel")

            wrapper = os.path.join(scratch, "imports_it.nova")
            with open(wrapper, "w", encoding="utf-8") as handle:
                handle.write('import "{}" as checked\n'.format(path.replace("\\", "/")))
            doors = {
                "run directly": cli(name),
                "run with --bootstrap": cli("--bootstrap", name),
                "imported by an untyped file": cli(wrapper),
                "loaded through the embedding API": embed(path),
            }
            for door, (status, out, err) in doors.items():
                line.check(
                    status == 1 and SENTINEL not in out and "TypeCheckError" in err,
                    "{} is refused when {}".format(name, door),
                    "exit {}\nstdout: {}\nstderr: {}".format(status, out[-500:], err[-500:]),
                )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    fail_dir = os.path.join(HERE, "typecheck", "fail") + os.sep
    for path in sorted(glob.glob(os.path.join(ROOT, "**", "*.nova"), recursive=True)):
        if path.startswith(fail_dir) or not annotated(path):
            continue
        status, out, err = cli("--typecheck", rel(path))
        line.check(status == 0, rel(path) + " has annotations, so it must type-check clean",
                   out + err)


def main(argv):
    quick = "--quick" in argv[1:]
    line = Line()
    station_fmt_golden(line)
    station_lint_golden(line)
    station_fmt_repo(line)
    if not quick:
        station_parity(line)
    station_python(line)
    station_types(line)
    print()
    if line.failures:
        print("ANDON: {} failed, {} passed - the line is stopped.".format(
            len(line.failures), line.passed))
        return 1
    print("GREEN: all {} checks passed.".format(line.passed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
