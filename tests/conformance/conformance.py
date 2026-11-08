#!/usr/bin/env python3
"""The conformance corpus: load it, validate it, run it on every engine.

    python3 tests/conformance/conformance.py            run it (also run_all.py's
                                                        `conformance` station)
    python3 tests/conformance/conformance.py --engine vm --verbose

A case is data (tests/conformance/cases/*.json), host-neutral:

    {"name": ..., "spec": ["lex.numbers", ...], "profile": "core",
     "source": ..., "output": [lines], "error": "Label: message" or "",
     "error_line": 1-based line or null, "exit": status, "host_calls": [],
     "divergences": {"bootstrap": {"id": "D-003", "output": ..., ...}}}

`output`, `error` and `exit` are what the specification says (docs/spec/),
checked against the reference engine by record.py. `divergences` records, per
engine, what an implementation does instead when it disagrees with the
specification; it must name an entry in docs/spec/DIVERGENCES.md, and the
station requires the engine to do exactly that (so it cannot drift further)
and to stop doing it once the divergence is fixed.

Mechanical rules checked here, in addition to running the cases:
  - every case cites at least one spec section, and every cited section exists;
  - every spec section is cited by at least one case;
  - every divergence id in a case is in the log, every open entry in the log
    is used by at least one case, and no resolved entry is.
"""

import argparse
import concurrent.futures
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))

import engines  # noqa: E402

CASES_DIR = HERE / "cases"
SPEC_DIR = ROOT / "docs" / "spec"
DIVERGENCE_LOG = SPEC_DIR / "DIVERGENCES.md"

PROFILES = ("core", "host", "modules")
REQUIRED = ("name", "spec", "profile", "source", "output", "error", "exit")

SECTION = re.compile(r"^#{2,4} \[([a-z][a-z0-9.-]*)\] ", re.M)
ENTRY = re.compile(r"^### (D-\d+) ", re.M)
STATUS = re.compile(r"^Status: (open|normalized|resolved)\b", re.M)
UNTESTED = re.compile(r"^Untested: ", re.M)

# D-001: the self-hosted interpreter reports lexical and syntax errors as
# "Error: LexError@12: message" (a kind and a character offset in front of the
# message) and uses the label "Error" where the host says "NovaError". The
# message text is what is compared; see docs/spec/DIVERGENCES.md. A failure
# the host labels ImportError or TypeError arrives the same way ("Error:
# TypeError: message") and is read as the label it names.
BOOTSTRAP_PREFIX = re.compile(r"^(?:LexError|ParseError)@\d+: ")


def load_cases():
    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data["cases"]:
            case["_file"] = path.name
            cases.append(case)
    return cases


def spec_sections():
    sections = {}
    for path in sorted(SPEC_DIR.glob("*.md")):
        for found in SECTION.findall(path.read_text(encoding="utf-8")):
            sections.setdefault(found, path.name)
    return sections


def divergence_log():
    """{id: status} from docs/spec/DIVERGENCES.md."""
    if not DIVERGENCE_LOG.exists():
        return {}
    text = DIVERGENCE_LOG.read_text(encoding="utf-8")
    parts = ENTRY.split(text)
    log = {}
    for index in range(1, len(parts), 2):
        status = STATUS.search(parts[index + 1])
        found = status.group(1) if status else "?"
        # An entry that cannot be tested portably says why on an `Untested:` line
        # and is then exempt from needing a case.
        log[parts[index]] = "untested" if found == "open" and UNTESTED.search(parts[index + 1]) else found
    return log


def validate(cases, sections, log):
    """Problems with the corpus itself, as a list of strings."""
    problems, names, cited, used = [], set(), set(), set()
    for case in cases:
        where = "{}: {}".format(case.get("_file"), case.get("name"))
        for key in REQUIRED:
            if key not in case:
                problems.append("{} has no {!r}".format(where, key))
        if case.get("name") in names:
            problems.append("{} is a duplicate name".format(where))
        names.add(case.get("name"))
        if case.get("profile") not in PROFILES:
            problems.append("{} has profile {!r}".format(where, case.get("profile")))
        if not case.get("spec"):
            problems.append("{} cites no spec section".format(where))
        for name, text in (case.get("files") or {}).items():
            if not isinstance(text, str) or name.startswith("/") or "\\" in name or ":" in name \
                    or name == "main.nova" or any(part in ("", ".", "..") for part in name.split("/")):
                problems.append("{} has a files entry {!r} that is not a plain relative path to text".format(where, name))
        for section in case.get("spec", []):
            cited.add(section)
            if section not in sections:
                problems.append("{} cites {!r}, which is not a spec section".format(where, section))
        for engine, observed in case.get("divergences", {}).items():
            if engine not in engines.ENGINES:
                problems.append("{} has a divergence for unknown engine {!r}".format(where, engine))
            used.add(observed.get("id"))
            if observed.get("id") not in log:
                problems.append("{} cites {}, which is not in the divergence log".format(
                    where, observed.get("id")))
            elif log[observed["id"]] not in ("open",):
                problems.append("{} cites {}, which is {}".format(where, observed["id"], log[observed["id"]]))
    for section, filename in sorted(sections.items()):
        if section not in cited:
            problems.append("spec section [{}] ({}) is cited by no case".format(section, filename))
    for case in cases:
        if "error_like" in case:
            try:
                if not re.fullmatch(case["error_like"], case["error"]):
                    problems.append("{}: error_like does not match the recorded error".format(case["name"]))
            except re.error as problem:
                problems.append("{}: error_like is not a regular expression ({})".format(case["name"], problem))
    for entry, status in sorted(log.items()):
        if status == "open" and entry not in used:
            problems.append("divergence {} is open but no case records it".format(entry))
    return problems


def normalize(engine, expected_error, result):
    """The observed result, with the documented self-hosted differences (D-001)
    removed from the error line, and the line number dropped for an engine that
    does not report one."""
    result = dict(result)
    if engine == "bootstrap":
        label, _, message = result["error"].partition(": ")
        if result["error"]:
            message = BOOTSTRAP_PREFIX.sub("", message)
            if label == "Error" and expected_error.startswith("NovaError: "):
                label = "NovaError"
            if label == "Error":
                # A labelled failure of the language's own (ImportError,
                # TypeError) carries its label in the message text.
                inner, _, rest = message.partition(": ")
                if inner in ("ImportError", "TypeError", "AssertionError"):
                    label, message = inner, rest
            result["error"] = label + ": " + message
        result["error_line"] = None
    return result


def differences(wanted, got, engine):
    out = []
    for key in ("output", "error", "exit"):
        if key == "error" and wanted.get("error_like"):
            # Part of the message is a host-defined limit (the call depth).
            if not re.fullmatch(wanted["error_like"], got["error"]):
                out.append("error: expected a match for {!r}, got {!r}".format(wanted["error_like"], got["error"]))
        elif wanted[key] != got[key]:
            out.append("{}: expected {!r}, got {!r}".format(key, wanted[key], got[key]))
    if engine != "bootstrap" and wanted.get("error_line") is not None \
            and wanted["error_line"] != got["error_line"]:
        out.append("error_line: expected {!r}, got {!r}".format(wanted["error_line"], got["error_line"]))
    return out


def judge(case, engine, result):
    """[] if the engine behaves as the corpus says it should, else the reasons."""
    got = normalize(engine, case["error"], result)
    spec = {key: case[key] for key in ("output", "error", "exit")}
    spec["error_line"] = case.get("error_line")
    spec["error_like"] = case.get("error_like")
    recorded = case.get("divergences", {}).get(engine)
    if recorded is None:
        return differences(spec, got, engine)
    if not differences(spec, got, engine):
        return ["{} is recorded but the engine now follows the specification: "
                "remove the divergence and mark {} resolved".format(recorded["id"], recorded["id"])]
    if recorded.get("unstable"):
        # The disagreement is a stack overflow, which ends differently on
        # different Pythons (a message on 3.11 and later, a crash with no
        # output or message on older ones). Any failure with no output will do.
        if got["exit"] != 0 and not got["output"]:
            return []
        return ["expected a failure with no output, got exit {} and {!r}".format(got["exit"], got["output"])]
    expected = {key: recorded.get(key, spec[key]) for key in ("output", "error", "exit")}
    expected["error_line"] = recorded.get("error_line", spec["error_line"])
    return differences(expected, got, engine)


def tree_walker_stack_limited():
    """The tree-walker cannot run deep recursion on Windows before Python 3.11:
    it overflows the native stack and ends the process (docs/CI.md). Cases marked
    `deep` are not given to it there; see tests/vm/test_differential.py."""
    return sys.platform == "win32" and sys.version_info < (3, 11)


def run_engine(cases, engine, workers=4):
    """{name: result} for one engine."""
    if engine == "bootstrap":
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {case["name"]: pool.submit(engines.run, case["source"], engine, case.get("files")) for case in cases}
            return {name: future.result() for name, future in futures.items()}
    return {case["name"]: engines.run(case["source"], engine, case.get("files")) for case in cases}


def check_all(check, selected=engines.ENGINES, verbose=False):
    """Run everything; `check(ok, label, detail)` records each result."""
    cases = load_cases()
    sections, log = spec_sections(), divergence_log()
    problems = validate(cases, sections, log)
    check(not problems, "conformance: the corpus is well-formed and cites every spec section "
          "({} cases, {} sections, {} divergences open)".format(
              len(cases), len(sections), sum(1 for s in log.values() if s in ("open", "untested"))),
          "\n".join(problems[:40]))
    if problems:
        return
    # Start the slow engine first so it overlaps the in-process ones.
    pending = {}
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    if "bootstrap" in selected:
        pending["bootstrap"] = pool.submit(run_engine, cases, "bootstrap")
    names = {"vm": "the bytecode VM", "tree": "the tree-walker", "bootstrap": "the self-hosted interpreter"}
    for engine in selected:
        runnable = cases
        if engine == "tree" and tree_walker_stack_limited():
            runnable = [case for case in cases if not case.get("deep")]
            print("  SKIPPED: the tree-walker did not run {} of {} conformance cases (marked deep): "
                  "on Windows with Python {}.{} it overflows the native stack on runaway recursion "
                  "(docs/CI.md). Run on the other engines.".format(
                      len(cases) - len(runnable), len(cases), sys.version_info[0], sys.version_info[1]))
        results = pending[engine].result() if engine in pending else run_engine(runnable, engine)
        failures = []
        for case in cases:
            if case["name"] not in results:
                continue
            for reason in judge(case, engine, results[case["name"]]):
                failures.append("{} [{}]: {}".format(case["name"], ", ".join(case["spec"]), reason))
        check(not failures, "conformance: {} passes the corpus ({} cases)".format(names[engine], len(cases)),
              "\n".join(failures[:30]) + ("\n... {} more".format(len(failures) - 30) if len(failures) > 30 else ""))
        if verbose:
            print("  {}: {} failing".format(engine, len(failures)))
    pool.shutdown()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--engine", action="append", choices=engines.ENGINES)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv[1:])
    failed = []

    def check(ok, label, detail=None):
        print("[{}] {}".format("ok" if ok else "FAILED", label))
        if not ok:
            failed.append(label)
            if detail:
                print("        " + detail.replace("\n", "\n        "))

    check_all(check, tuple(args.engine) if args.engine else engines.ENGINES, args.verbose)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
