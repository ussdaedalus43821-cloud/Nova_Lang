#!/usr/bin/env python3
"""Copy the policy dialect's conformance corpus to a game repository's Godot project.

    python3 tools/export_policy_corpus.py PATH/TO/Reactor-Game/godot/scripts/nova/policy_corpus

The corpus (tests/conformance/cases/policy-*.json) is written here and run on the Python engine by the
conformance station. The GDScript interpreter is checked against the same files by corpus_check.gd in the
game repository, so the game keeps a copy. This writes the copy (replacing the old policy-*.json there) and a
SOURCE.txt that says which Nova_Lang commit it came from, so a stale copy can be told from a fresh one.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "conformance" / "cases"


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    dest = Path(argv[1])
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("policy-*.json"):
        old.unlink()
    total = 0
    for path in sorted(CASES.glob("policy-*.json")):
        shutil.copyfile(str(path), str(dest / path.name))
        total += len(json.loads(path.read_text(encoding="utf-8"))["cases"])
    try:
        commit = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], universal_newlines=True).strip()
    except Exception:
        commit = "unknown"
    (dest / "SOURCE.txt").write_text(
        "The policy dialect conformance corpus of the Nova_Lang repository, tests/conformance/cases/policy-*.json.\n"
        "Copied by tools/export_policy_corpus.py at Nova_Lang commit {}.\n"
        "{} cases in {} files. Do not edit these files: change them in Nova_Lang and export again.\n".format(
            commit, total, len(list(dest.glob("policy-*.json")))), encoding="utf-8")
    print("{} cases from {} files -> {}".format(total, len(list(dest.glob("policy-*.json"))), dest))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
