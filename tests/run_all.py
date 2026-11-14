#!/usr/bin/env python3
"""
tests/run_all.py - the Andon cord. Any failure stops the line (exit 1).

    python3 tests/run_all.py            everything
    python3 tests/run_all.py --quick    skip the slow bootstrap stations (4-5)
    python3 tests/run_all.py --station compiler --station types
    python3 tests/run_all.py --report checks.jsonl    save each completed check

Stations, in order:

  0. harness        timeout handling, segmented reports and timezone regressions.
  0b. cli           formatter/linter modes, disassembly and bootstrap launchers;
                    real subprocess output, exit codes and filesystem effects.
  0c. embedding     callbacks, conversions, property errors and import permissions
                    on both engines, plus bootstrap error-boundary parity.
  0d. repl          multiline input, error recovery, EOF and session state
                    through the real interactive entry points.
  0e. input-errors  formatter refusal and malformed package/LSP input.
  0f. portability   behavior that must not depend on the platform (Windows
                    paths, file URIs, newlines, the time limit), tested on
                    every platform by simulating the one that differs.

  12. conformance   the host-neutral corpus in tests/conformance/ (cases that
                    cite the sections of docs/spec/) run on the VM, the
                    tree-walker and the self-hosted interpreter; every spec
                    section must be cited, every divergence logged.

  13. security-matrix  the sandbox coverage matrix (tests/security/matrix.py):
                    one cell per capability, limit and path rule of
                    docs/spec/16-sandbox.md per engine; every case claim must
                    be a real cell and every hole explained. Strict mode
                    (all cells covered) is M11's exit criterion.

  1. fmt golden     tests/fmt/X.nova formats to exactly X.expected.nova,
                    and every expected file is already a fixed point.
  2. lint golden    tests/lint/X.nova lints to exactly X.expected.
  3. fmt poka-yoke  every .nova file in the repo formats with all of the
                    formatter's own checks passing (same AST, same
                    comments, idempotent).
  3b. line breaks  "\n", "\r\n" and a lone "\r" all end a line, as in
                  editors and the Language Server Protocol: the same
                  program written with each lexes to the same tokens (in
                  both lexers, handed the raw text as an editor would), runs
                  the same on both engines, ends comments and refuses
                  open strings at the break, and reports errors on the
                  same line.
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
                  The gate checks an import graph once per load: on a
                  heavily shared graph, one checker run per file
                  (tests/typecheck/gate_cache.py), and never a stale one.

  8. packages     tests/pkg/ is copied to a scratch directory (sources/
                  git-lib becomes a real git repo there) and nova-pkg is
                  driven through every case: install from a registry, a
                  path and a git ref; the lock, its determinism and the
                  git commit it records; .nova_modules kept out of git;
                  the project run on both engines; and each failure -
                  package not installed, not in the registry, a version
                  conflict, a package cycle, --frozen without a lock or
                  with a stale one, tampering, a source changed after
                  locking, a typed package's contract, and the
                  interpreter refusing a stale install.

  9. editor       tests/lsp/test_lsp.py drives tools/nova-lsp.py over real
                  JSON-RPC: the protocol and its error handling,
                  diagnostics with exact ranges (UTF-16 and UTF-32, "\r\n"
                  and lone "\r"), formatting, definition and hover; and
                  checks the VS Code extension - its manifest, its grammar
                  against the language's own words (the drift guard), and
                  extension.js under Node.

 10. compiler     tests/compiler/test_compiler.py: golden --dis output for
                  closures and try/catch/finally among others; every .nova
                  file compiles and passes verify(); every AST node has a
                  handler; verify() refuses broken bytecode; and the
                  resolver agrees with nova_scope on every name read.

 11. differential the bytecode VM against the tree-walker, which is the
                  reference: every .nova file through the CLI, every
                  example under --bootstrap, 300 seeded random programs
                  (tests/vm/generator.py) aimed at scopes, closures,
                  try/finally and errors, and the embedding API - same
                  stdout, stderr and exit status, byte for byte - and
                  together they use every opcode.

Stations 4-5 compare output byte for byte; timestamps that `log()` stamps
on stderr are the only thing masked, and only stdout is compared, because
the two engines word their error messages (stderr) differently on purpose.
"""

import argparse
import concurrent.futures
import glob
import json
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
typecheck = load("nova-typecheck.py")

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

# Examples that create files in the current directory, and one that counts
# its entries: each runs alone (see station_parity).
ALONE = {"examples/file_demo.nova", "examples/stdlib_demo.nova",
         "examples/stdlib_full_test.nova"}

TIMESTAMP = re.compile(r"\[\d{4}-\d\d-\d\dT[0-9:.+-]+\]")


class Line:
    def __init__(self, report=None):
        self.failures = []
        self.passed = 0
        self.report = report

    def check(self, ok, label, detail=""):
        if self.report is not None:
            self.report.write(json.dumps({"passed": bool(ok), "label": label,
                                          "detail": detail}, default=str) + "\n")
            self.report.flush()
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
        check_spans(line, source_path, read(source_path), findings)
        actual = "".join(
            lint.format_finding(rel(source_path), parsed, finding) + "\n" for finding in findings
        )
        line.check(actual == expected, rel(source_path) + " gives its .expected findings",
                   diff(expected, actual))


# Exact underlines an editor will show for a few findings (code, text).
EXPECTED_SPANS = {
    "tests/lint/undefined.nova": [("E001", "missing")],
    "tests/lint/unused.nova": [("W001", "let never_read")],
    "tests/lint/unreachable.nova": [("W002", 'print("after return")')],
    "tests/typecheck/fail/operators.nova": [("T007", "s - n"), ("T007", "n in s")],
    "tests/typecheck/fail/returns.nova": [("T004", "return"), ("T005", "def sometimes")],
    "tests/typecheck/fail/arguments.nova": [("T002", '"two"'), ("T003", "add")],
    "tests/typecheck/fail/unknown_types.nova": [("T001", "integer")],
}


def check_spans(line, path, source, findings):
    """Every finding knows where it ends, after it starts and on its line
    - an editor underlines exactly that - and the spot checks match."""
    for finding in findings:
        text = source[finding.position:finding.end] if finding.end is not None else None
        line.check(
            text is not None and finding.end > finding.position and "\n" not in text,
            "{}: {} at {} has a one-line end".format(rel(path), finding.code, finding.position),
            repr(text),
        )
    shown = [(f.code, source[f.position:f.end]) for f in findings if f.end is not None]
    for wanted in EXPECTED_SPANS.get(rel(path), []):
        line.check(wanted in shown, "{}: {} underlines {!r}".format(rel(path), *wanted),
                   repr(shown))


def station_fmt_repo(line):
    print("3. formatter self-checks on every .nova file in the repo")
    for path in nova_files(ROOT):
        try:
            fmt.format_source(read(path))
            line.check(True, rel(path))
        except Exception as problem:  # noqa: BLE001
            line.check(False, rel(path) + " formats safely", str(problem))


LINE_BREAK_PROGRAM = [
    'let greeting = "hi"  # a comment that must end at the break',
    "print(greeting)",
    "",
    "def twice(x) {",
    "    return x * 2",
    "}",
    "print(twice(21))",
]


def station_line_breaks(line):
    print("3b. line breaks")
    sys.path.insert(0, ROOT)
    import novalang
    variants = {name: brk.join(LINE_BREAK_PROGRAM) + brk
                for name, brk in (("\\n", "\n"), ("\\r\\n", "\r\n"), ("lone \\r", "\r"))}

    def tokens(source):
        return [(t.type, t.value) for t in novalang.Lexer(source).tokenize()]

    # Files reach both lexers through Python's text mode, which already
    # turns "\r\n" and a lone "\r" into "\n" - so running files cannot
    # tell whether a lexer handles "\r". Editor buffers (over LSP), exec()
    # strings and the REPL never pass through a file, so each lexer is
    # also handed the raw text directly: the host's, and novalang.nova's own.
    self_hosted = novalang.Interpreter()
    novalang.run(read(os.path.join(ROOT, "novalang.nova")), self_hosted)
    self_hosted_tokenize = self_hosted.globals.get("tokenize")

    def self_hosted_tokens(source):
        found = self_hosted.call_value(self_hosted_tokenize, [source], 0)
        return [(token["kind"], token["value"]) for token in found]

    reference = tokens(variants["\\n"])
    scratch = tempfile.mkdtemp(prefix="nova-breaks-")
    try:
        outputs = {}
        for name, source in variants.items():
            line.check(tokens(source) == reference, "{} lexes like \\n".format(name))
            line.check(self_hosted_tokens(source) == self_hosted_tokens(variants["\\n"]),
                       "{} lexes like \\n in novalang.nova too".format(name))
            path = os.path.join(scratch, "program.nova")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
            for engine in ([], ["--bootstrap"]):
                done = subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")]
                                      + engine + [path], capture_output=True, text=True,
                                      timeout=600)
                outputs[(name, tuple(engine))] = (done.returncode, done.stdout)
            line.check(fmt.format_source(source) == variants["\\n"],
                       "{} formats to the \\n layout".format(name))
            for brk_name, brk in (("string", '"open'), ("f-string", 'f"open'),
                                  ("f-string hole", 'f"{open')):
                if name == "\\n":
                    continue
                broken = "let s = " + brk + ("\r" if "lone" in name else "\r\n") + '"\n'
                try:
                    novalang.Lexer(broken).tokenize()
                    refused = False
                except novalang.NovaError:
                    refused = True
                line.check(refused, "a {} cannot run across a {}".format(brk_name, name))
            error = None
            try:
                novalang.run(source.replace("twice(21)", "twice(missing)"), novalang.Interpreter())
            except novalang.NovaError as problem:
                error = problem.render(source.replace("twice(21)", "twice(missing)"))
            line.check(error is not None and "  7 | print(twice(missing))" in error,
                       "{}: errors point at the right line".format(name), error or "")
        expected = (0, "hi\n42\n")
        for key, result in sorted(outputs.items()):
            line.check(result == expected, "{} runs{}".format(
                key[0], " under --bootstrap" if key[1] else ""), str(result))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


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
    if a[0] == "timeout" or b[0] == "timeout":
        return False
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
            # Programs that change the current directory run alone, after
            # the rest, so none changes it while another (file_demo) counts
            # its entries.
            for example in examples(ROOT):
                if example not in ALONE:
                    jobs[example] = pool.submit(four_runs, example)
            for example, future in list(jobs.items()):
                future.result()
            for example in examples(ROOT):
                if example in ALONE:
                    jobs[example] = pool.submit(four_runs, example)
                    jobs[example].result()
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
    import gate_cache
    gate_cache.run(line.check)

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
            _, module = typecheck.check_source(read(path), path)
            check_spans(line, path, read(path), module.findings)
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


def station_packages(line):
    print("8. packages")
    pkg = os.path.join(ROOT, "tools", "nova-pkg.py")
    novalang_py = os.path.join(ROOT, "novalang.py")
    scratch = tempfile.mkdtemp(prefix="nova-pkg-test-")
    try:
        work = os.path.join(scratch, "pkg")
        shutil.copytree(os.path.join(HERE, "pkg"), work)

        def sh(args, cwd):
            done = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=600)
            return done.returncode, done.stdout, done.stderr

        def git(args, cwd):
            return sh(["git", "-c", "user.name=nova", "-c", "user.email=nova@example.com"]
                      + args, cwd)

        # git-lib: v0.3.0 is tagged, then the branch moves on, so a lock that
        # recorded the ref instead of the commit would drift.
        git_lib = os.path.join(work, "sources", "git-lib")
        git(["init", "-q"], git_lib)
        git(["add", "-A"], git_lib)
        git(["commit", "-qm", "v0.3.0"], git_lib)
        git(["tag", "v0.3.0"], git_lib)
        tagged = git(["rev-parse", "HEAD"], git_lib)[1].strip()
        with open(os.path.join(git_lib, "main.nova"), "a", encoding="utf-8") as handle:
            handle.write("# a later, untagged change\n")
        git(["commit", "-qam", "later"], git_lib)

        def project(name):
            return os.path.join(work, "projects", name)

        def install(name, *flags):
            return sh([sys.executable, pkg, "install"] + list(flags), project(name))

        def run(name, script, *flags):
            return sh([sys.executable, novalang_py] + list(flags) + [script], project(name))

        def both(name, script):
            return run(name, script), run(name, script, "--bootstrap")

        def check(ok, label, result=None):
            detail = "" if result is None else "exit {}\nstdout: {}\nstderr: {}".format(
                result[0], result[1][-800:], result[2][-800:])
            line.check(ok, "pkg: " + label, detail)

        # -- the happy path --------------------------------------------------
        app = project("app")
        git(["init", "-q"], app)                # a project under version control
        result = install("app")
        check(result[0] == 0, "app installs", result)
        lock_path = os.path.join(app, "nova.lock")
        check(os.path.isfile(lock_path), "install writes nova.lock")
        modules = os.path.join(app, ".nova_modules")
        check(sorted(os.listdir(modules)) == [".gitignore", ".installed.lock", "git-lib",
                                              "local-lib", "math-utils", "str-tools"],
              "install creates .nova_modules with every package, flat",
              (0, str(sorted(os.listdir(modules))), ""))
        status = git(["status", "--porcelain", "--untracked-files=all"], app)
        check(status[0] == 0 and ".nova_modules" not in status[1] and "nova.lock" in status[1],
              "git ignores .nova_modules but not nova.lock", status)
        lock = json.loads(read(lock_path))
        check(lock["packages"]["math-utils"]["version"] == "1.2.0",
              "^1.0.0 picks the newest 1.x (1.2.0, not 2.0.0)")
        check(lock["packages"]["git-lib"]["source"] == {"git": "../../sources/git-lib",
                                                        "commit": tagged},
              "the lock pins git-lib to the tag's commit", (0, json.dumps(lock["packages"]), ""))
        first_lock = read(lock_path)
        expected = read(os.path.join(app, "expected.txt"))
        direct, booted = both("app", "src/main.nova")
        check(direct == (0, expected, ""), "app runs with its packages", direct)
        check(booted == direct, "app runs the same under --bootstrap", booted)
        result = sh([sys.executable, pkg, "verify"], app)
        check(result[0] == 0, "verify passes after install", result)
        result = install("app", "--frozen")
        check(result[0] == 0 and read(lock_path) == first_lock, "install --frozen reuses the lock",
              result)
        os.remove(lock_path)
        shutil.rmtree(modules)
        install("app")
        check(read(lock_path) == first_lock, "resolving again writes the identical lock")

        # -- the interpreter stops the line on a stale install ----------------
        def refused(label, needle):
            for result in both("app", "src/main.nova"):
                check(result[0] == 1 and needle in result[2] and "nova-pkg.py install" in result[2],
                      label, result)

        manifest_path = os.path.join(app, "nova.json")
        manifest_text = read(manifest_path)
        with open(manifest_path, "w", encoding="utf-8") as handle:
            handle.write(manifest_text.replace('"^1.0.0"', '"~1.2.0"'))
        refused("nova.json edited without an install is refused",
                "nova.json has changed since nova.lock was written")
        result = install("app", "--frozen")
        check(result[0] == 1 and "out of date" in result[2], "--frozen refuses a stale lock", result)
        with open(manifest_path, "w", encoding="utf-8") as handle:
            handle.write(manifest_text)
        os.remove(os.path.join(modules, ".installed.lock"))
        refused("an unfinished install is refused", "not installed from the current nova.lock")
        install("app")
        os.remove(lock_path)
        refused("a deleted nova.lock is refused", "there is no nova.lock")
        result = install("app", "--frozen")
        check(result[0] == 1 and "there is no nova.lock" in result[2],
              "--frozen refuses a missing lock", result)
        result = install("app")
        check(result[0] == 0 and run("app", "src/main.nova")[0] == 0,
              "install without --frozen recreates a missing lock", result)

        # -- tampering ------------------------------------------------------
        with open(os.path.join(modules, "str-tools", "tools.nova"), "a", encoding="utf-8") as handle:
            handle.write("# edited by hand\n")
        result = sh([sys.executable, pkg, "verify"], app)
        check(result[0] == 1 and '"str-tools" was changed after it was installed' in result[1],
              "verify catches an edited package", result)
        install("app")
        check(sh([sys.executable, pkg, "verify"], app)[0] == 0, "install repairs it")
        registry_file = os.path.join(work, "registry", "str-tools", "0.1.0", "tools.nova")
        original = read(registry_file)
        with open(registry_file, "a", encoding="utf-8") as handle:
            handle.write("# republished without a version bump\n")
        result = install("app")
        check(result[0] == 1 and "no longer matches nova.lock" in result[2],
              "a package changed at its source after locking is refused", result)
        with open(registry_file, "w", encoding="utf-8") as handle:
            handle.write(original)

        # -- resolution failures ---------------------------------------------
        result = run("cycle", "main.nova")
        check(result[0] == 1 and 'cannot find package "cyc-a"' in result[2],
              "a package that was never installed is reported", result)
        result = install("cycle")
        check(result[0] == 0, "a dependency cycle (cyc-a <-> cyc-b) still resolves", result)
        for result in both("cycle", "main.nova"):
            check(result[0] == 1 and "circular import: cyc-a/main.nova -> cyc-b/main.nova" in
                  result[2], "...and running it reports the circular import, naming packages",
                  result)
        result = install("missing")
        check(result[0] == 1 and 'package "no-such-package"' in result[2]
              and "is not in the registry" in result[2],
              "a package missing from the registry is reported", result)
        result = install("conflict")
        check(result[0] == 1 and 'conflicting requirements for "math-utils"' in result[2]
              and "conflict wants ^1.0.0" in result[2] and "needs-two@1.0.0 wants ^2.0.0" in result[2],
              "a version conflict names both requirers", result)
        check(not os.path.exists(os.path.join(project("conflict"), "nova.lock")),
              "a failed install writes no lock")

        # -- types through packages -----------------------------------------
        install("typed")
        for result in both("typed", "main.nova"):
            check(result[0] == 1 and "TypeCheckError" in result[2] and SENTINEL not in result[1],
                  "a typed package's contract binds an untyped importer", result)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def station_editor(line):
    print("9. editor (language server and VS Code extension)")
    sys.path.insert(0, os.path.join(HERE, "lsp"))
    import test_lsp
    test_lsp.run(lambda ok, label, detail=None: line.check(
        ok, "lsp: " + label, "" if detail is None else repr(detail)[:1500]))


def station_compiler(line):
    print("10. compiler (AST -> bytecode)")
    sys.path.insert(0, os.path.join(HERE, "compiler"))
    import test_compiler
    test_compiler.run(lambda ok, label, detail=None: line.check(
        ok, "compiler: " + label, "" if detail is None else str(detail)[:3000]))
    import test_bytecode_draft              # the draft of chapter 17 stays in step with OPCODES (M12 slice 3)
    test_bytecode_draft.run(lambda ok, label, detail=None: line.check(
        ok, "compiler: " + label, "" if detail is None else str(detail)[:3000]))


def station_differential(line):
    print("11. differential (VM against the tree-walker)")
    sys.path.insert(0, os.path.join(HERE, "vm"))
    import test_differential
    test_differential.run(lambda ok, label, detail=None: line.check(
        ok, "vm: " + label, "" if detail is None else str(detail)[:4000]))


def station_harness(line):
    print("0. test harness regressions")
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                           os.path.join(HERE, "harness")],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    line.check(done.returncode == 0, "test harness regressions pass",
               done.stdout + done.stderr)


def station_cli(line):
    print("0b. command-line regression tests")
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                           os.path.join(HERE, "cli"), "-v"],
                          cwd=ROOT, capture_output=True, text=True, timeout=180)
    line.check(done.returncode == 0, "command-line regressions pass",
               done.stdout + done.stderr)


def station_embedding(line):
    print("0c. embedding boundary regressions")
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                           os.path.join(HERE, "embedding"), "-v"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    line.check(done.returncode == 0, "embedding boundary regressions pass",
               done.stdout + done.stderr)


def station_repl(line):
    print("0d. interactive REPL regressions")
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                           os.path.join(HERE, "repl"), "-v"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    line.check(done.returncode == 0, "interactive REPL regressions pass",
               done.stdout + done.stderr)


def station_input_errors(line):
    print("0e. formatter refusal and malformed input regressions")
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                           os.path.join(HERE, "input_errors"), "-v"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    line.check(done.returncode == 0, "malformed input regressions pass",
               done.stdout + done.stderr)


def station_portability(line):
    print("0f. platform-independence regressions")
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                           os.path.join(HERE, "portability"), "-v"],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    line.check(done.returncode == 0, "platform-independence regressions pass",
               done.stdout + done.stderr)


def station_conformance(line):
    print("12. conformance (the specification's corpus on every engine)")
    sys.path.insert(0, os.path.join(HERE, "conformance"))
    import conformance
    conformance.check_all(line.check)


def station_security(line):
    print("13a. security (the sandbox profile through the embedding API and the command line)")
    # Not -v: a failure is what the report should show, not 60 lines of passes.
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                           os.path.join(HERE, "security")],
                          cwd=ROOT, capture_output=True, text=True, timeout=300)
    line.check(done.returncode == 0, "sandbox capability, path, limit, determinism, runner and command-line tests pass",
               done.stdout + done.stderr)


def station_security_matrix(line):
    print("13. security matrix (which capability and limit is proved on which engine)")
    sys.path.insert(0, os.path.join(HERE, "security"))
    import matrix
    matrix.check_all(line.check, strict=True)           # M11's exit criterion: every cell is covered


QUICK = False       # set by main() for --quick


def station_bytecode(line):
    print("0g. bytecode artifacts (.novac): format, rejection, corruption, the round trip over the conformance corpus, golden fixtures")
    env = dict(os.environ)
    if QUICK:
        env["NOVA_BYTECODE_QUICK"] = "1"        # a tenth of the corpus in the round trip
    done = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", os.path.join(HERE, "bytecode")],
                          cwd=ROOT, capture_output=True, text=True, timeout=600, env=env, stdin=subprocess.DEVNULL)
    line.check(done.returncode == 0, "bytecode artifact tests pass", done.stdout + done.stderr)


STATIONS = [
    ("harness", station_harness),
    ("cli", station_cli),
    ("embedding", station_embedding),
    ("repl", station_repl),
    ("bytecode", station_bytecode),
    ("input-errors", station_input_errors),
    ("portability", station_portability),
    ("fmt-golden", station_fmt_golden),
    ("lint-golden", station_lint_golden),
    ("fmt-repo", station_fmt_repo),
    ("line-breaks", station_line_breaks),
    ("parity", station_parity),
    ("python", station_python),
    ("types", station_types),
    ("packages", station_packages),
    ("editor", station_editor),
    ("compiler", station_compiler),
    ("differential", station_differential),
    ("conformance", station_conformance),
    ("security", station_security),
    ("security-matrix", station_security_matrix),
]


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="skip parity stations 4-5")
    parser.add_argument("--station", action="append", choices=[name for name, _ in STATIONS],
                        help="run only this station; repeat to select several")
    parser.add_argument("--report", help="write and flush each check to a JSON Lines file")
    args = parser.parse_args(argv[1:])
    if args.quick and args.station and "parity" in args.station:
        parser.error("--quick cannot be combined with --station parity")
    global QUICK
    QUICK = args.quick
    line = Line()
    try:
        if args.report:
            line.report = open(args.report, "w", encoding="utf-8")
        for name, station in STATIONS:
            if args.station and name not in args.station:
                continue
            if args.quick and name == "parity":
                continue
            station(line)
    finally:
        if line.report is not None:
            line.report.close()
    print()
    if line.failures:
        print("ANDON: {} failed, {} passed - the line is stopped.".format(
            len(line.failures), line.passed))
        return 1
    print("GREEN: all {} checks passed.".format(line.passed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
