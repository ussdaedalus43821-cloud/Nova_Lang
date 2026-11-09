#!/usr/bin/env python3
"""The sandbox coverage matrix: which capability and limit is proved, on which engine.

    python3 tests/security/matrix.py            the table, and the verdict
    python3 tests/security/matrix.py --strict   also fail while any cell is pending
                                                (M11's exit criterion; CI turns it on at the end)

The cells come from the specification, not from this file: one row of the `[sbx.capabilities]`
table gives `<capability>:deny` and `<capability>:grant`, each row of the `[sbx.limits]` table
gives `<cell>:trip` (and `<cell>:uncatchable` for a *fatal* limit), and each row of the path table
in `[sbx.paths]` gives `paths.x:deny` (`paths.inside:grant`). Each cell is needed on the bytecode VM,
the tree-walker and the self-hosted interpreter.

A conformance case claims cells with `"matrix": ["files.read:deny", ...]`. A cell is

  covered  a case claims it and the engine follows the specification in that case;
  pending  a case claims it, but the engine still disagrees (the case records the divergence
           id); or no case exists yet and tests/security/pending.json says why.

What fails the station, in addition to a case claiming a cell the specification does not have:
a cell with no case that pending.json does not explain, and an entry of pending.json whose cell
now has a case. So a hole cannot appear unnoticed, and the list of excuses cannot go stale.
`--strict` fails on pending cells too, which is how "every capability has a denial test and a grant
test on each engine" becomes something CI can fail on.
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPEC = ROOT / "docs" / "spec" / "16-sandbox.md"
CASES = ROOT / "tests" / "conformance" / "cases"
PENDING = HERE / "pending.json"
ENGINES = ("vm", "tree", "bootstrap")


def section(text, name):
    """The text of one `## [name] ...` section of the specification."""
    match = re.search(r"^## \[{}\][^\n]*\n(.*?)(?=^## \[|\Z)".format(re.escape(name)), text, re.M | re.S)
    return match.group(1) if match else ""


def table_rows(text):
    """The cells of every row of every table in `text`, as lists of strings (header and rule skipped)."""
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return [row for row in rows if row and row[0] not in ("Capability", "Cell")]


def derive_cells(spec_text=None):
    """{cell: {"row": kind of row}} for every cell the specification asks for, in order."""
    text = spec_text if spec_text is not None else SPEC.read_text(encoding="utf-8")
    cells = {}
    for row in table_rows(section(text, "sbx.capabilities")):
        name = row[0].strip("`")
        if re.fullmatch(r"[a-z]+(\.[a-z]+)?", name):
            cells["{}:deny".format(name)] = "capability"
            cells["{}:grant".format(name)] = "capability"
    for row in table_rows(section(text, "sbx.limits")):
        name = row[0].strip("`")
        if re.fullmatch(r"[a-z]+(\.[a-z]+)?", name) and len(row) >= 4:
            cells["{}:trip".format(name)] = "limit"
            if "fatal" in row[-1] and "catchable" not in row[-1].replace("fatal", ""):
                cells["{}:uncatchable".format(name)] = "limit"
    for row in table_rows(section(text, "sbx.determinism")):
        name = row[0].strip("`")
        if re.fullmatch(r"det\.[a-z]+", name):
            cells["{}:replay".format(name)] = "determinism"
    for row in table_rows(section(text, "sbx.runner")):
        name = row[0].strip("`")
        if re.fullmatch(r"runner\.[a-z]+", name) and len(row) >= 2:
            for kind in row[1].split():
                cells["{}:{}".format(name, kind)] = "runner"
    for row in table_rows(section(text, "sbx.paths")):
        name = row[0].strip("`")
        if name.startswith("paths."):
            cells["{}:{}".format(name, "grant" if name == "paths.inside" else "deny")] = "path"
    return cells


def load_cases():
    out = []
    for path in sorted(CASES.glob("*.json")):
        for case in json.loads(path.read_text(encoding="utf-8"))["cases"]:
            case["_file"] = path.name
            out.append(case)
    return out


def evaluate(cells, cases, pending):
    """(status, problems): status[cell][engine] is 'covered', 'pending' or 'missing'."""
    claims = {cell: [] for cell in cells}
    problems = []
    for case in cases:
        for cell in case.get("matrix", []):
            if cell not in cells:
                problems.append("{} claims {!r}, which the specification does not ask for".format(case["name"], cell))
            else:
                claims[cell].append(case)
    status = {}
    for cell in cells:
        if not claims[cell]:
            if cell not in pending:
                problems.append("{} has no case and tests/security/pending.json does not explain why".format(cell))
            status[cell] = {engine: "missing" for engine in ENGINES}
            continue
        if cell in pending:
            problems.append("{} has a case now: remove it from tests/security/pending.json".format(cell))
        status[cell] = {}
        for engine in ENGINES:
            divergent = [c for c in claims[cell] if engine in c.get("divergences", {})]
            status[cell][engine] = "pending" if divergent else "covered"
    for cell in pending:
        if cell not in cells:
            problems.append("pending.json explains {!r}, which is not a cell".format(cell))
    return status, problems


def summary(status):
    total = sum(len(row) for row in status.values())
    covered = sum(1 for row in status.values() for s in row.values() if s == "covered")
    return covered, total


def render(cells, status):
    lines = ["{:<30} {:<9} {}".format("cell", "kind", "  ".join("{:<8}".format(e) for e in ENGINES))]
    for cell, row in status.items():
        marks = {"covered": "ok", "pending": "pending", "missing": "no case"}
        lines.append("{:<30} {:<9} {}".format(cell, cells[cell],
                                              "  ".join("{:<8}".format(marks[row[e]]) for e in ENGINES)))
    covered, total = summary(status)
    lines.append("{} of {} cells covered".format(covered, total))
    return "\n".join(lines)


def classification_problems(cases):
    """Drift between the code and the specification: a built-in nobody classified, a gated name the
    specification does not list, a gated name no case shows to be denied."""
    sys.path.insert(0, str(ROOT))
    import novalang
    problems = []
    pure = set(json.loads((HERE / "pure_builtins.json").read_text(encoding="utf-8"))["pure"])
    gated = set(novalang.CAPABILITY_OF)
    builtins = set(novalang.BUILTINS)
    for name in sorted(builtins - gated - pure):
        problems.append("the built-in {!r} is neither gated by a capability nor listed in "
                        "tests/security/pure_builtins.json: decide which it is".format(name))
    for name in sorted(pure - builtins):
        problems.append("pure_builtins.json lists {!r}, which is not a built-in".format(name))
    for name in sorted(pure & gated):
        problems.append("{!r} is both gated and listed as pure".format(name))
    text = SPEC.read_text(encoding="utf-8")
    listed = set()
    for row in table_rows(section(text, "sbx.capabilities")):
        if len(row) >= 2:
            listed |= set(re.findall(r"`([a-z_]+)`", row[1]))
    for name in sorted(gated - listed):
        problems.append("the gated built-in {!r} is not in the capability table of 16-sandbox.md".format(name))
    denied = set()
    for case in cases:
        if case["profile"] == "sandbox":
            for line in case.get("output", []):
                denied |= set(re.findall(r"^undefined name '([a-z_]+)'$", line))
    for name in sorted(gated - denied):
        problems.append("no sandbox case shows the gated built-in {!r} to be undefined without its capability".format(name))
    return problems


def check_all(check, strict=False, verbose=False):
    cells = derive_cells()
    pending = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else {}
    status, problems = evaluate(cells, load_cases(), pending)
    covered, total = summary(status)
    check(not problems, "security matrix: every claim is a cell of the specification and every hole is "
          "explained ({} cells, {} of {} covered)".format(len(cells), covered, total),
          "\n".join(problems))
    classification = classification_problems(load_cases())
    check(not classification, "security matrix: every built-in is classified, listed and shown to be denied",
          "\n".join(classification))
    if strict:
        open_cells = ["{} on {}".format(cell, engine) for cell, row in status.items()
                      for engine, s in row.items() if s != "covered"]
        check(not open_cells, "security matrix (strict): every cell is covered", "\n".join(open_cells[:40]))
    elif verbose:
        print(render(cells, status))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strict", action="store_true", help="fail while any cell is pending")
    arguments = parser.parse_args()
    cells = derive_cells()
    pend = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else {}
    st, probs = evaluate(cells, load_cases(), pend)
    print(render(cells, st))
    for problem in probs:
        print("PROBLEM:", problem)
    failed = bool(probs) or (arguments.strict and summary(st)[0] != summary(st)[1])
    sys.exit(1 if failed else 0)
