#!/usr/bin/env python3
"""Fill in or verify a case's recorded behavior against the reference engine.

    python3 tests/conformance/record.py --build FILE.py OUT.json   (authoring)
    python3 tests/conformance/record.py --missing                  fill absent expectations
    python3 tests/conformance/record.py --check                    reference == recorded?

The reference engine is the bytecode VM. Recording is for writing the corpus:
a recorded value is then reviewed against the specification text, and where
the two disagree the case keeps the specification's value and records the
engine's under `divergences` (docs/spec/DIVERGENCES.md).
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import conformance  # noqa: E402
import engines  # noqa: E402


def dump(path, area, cases):
    ordered = []
    for case in cases:
        first = ("name", "spec", "profile", "source", "output", "error", "error_like",
                 "error_line", "exit", "host_calls", "files", "env", "stdin", "args", "allow_python", "embedding", "results", "deep")
        entry = {key: case[key] for key in first if key in case}
        entry.update({key: value for key, value in case.items() if key not in entry and not key.startswith("_")})
        ordered.append(entry)
    path.write_text(json.dumps({"area": area, "version": 1, "cases": ordered}, indent=1,
                               ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv):
    mode = argv[1] if len(argv) > 1 else "--check"
    if mode == "--build":
        import importlib.util
        spec = importlib.util.spec_from_file_location("authored", argv[2])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cases = []
        for name, sections, source in module.CASES:
            result = engines.run(source, "vm")
            cases.append({"name": name, "spec": sections, "profile": "core", "source": source,
                          "output": result["output"], "error": result["error"],
                          "error_line": result["error_line"], "exit": result["exit"], "host_calls": []})
        dump(Path(argv[3]), Path(argv[3]).stem, cases)
        print("wrote {} cases to {}".format(len(cases), argv[3]))
        return 0
    status = 0
    for path in sorted(conformance.CASES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for case in data["cases"]:
            result = engines.run_case(case, "vm")
            for key in ("output", "error", "error_line", "exit") + (
                    ("host_calls", "results") if "embedding" in case else ()):
                if key not in case:
                    if mode == "--missing":
                        case[key] = result[key]
                        changed = True
                elif mode == "--check" and case[key] != result[key] \
                        and not ("vm" in case.get("divergences", {})):
                    print("{}: {}: recorded {!r}, reference {!r}".format(path.name, case["name"], case[key], result[key]))
                    status = 1
        if changed:
            dump(path, data.get("area", path.stem), data["cases"])
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
