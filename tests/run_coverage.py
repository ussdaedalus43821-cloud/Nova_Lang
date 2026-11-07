#!/usr/bin/env python3
"""Measure the existing suite in a scratch copy, including Python children.

Requires coverage.py (baseline measured with 7.6.1). Optional --coverage-path
allows an isolated installation without changing the language's dependencies.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]

DRIVER = '''import os, sys
import coverage
sys.path.insert(0, sys.argv[1] + "/tests")
import run_all

def instrument(name, station):
    def measured(line):
        os.environ["NOVA_COVERAGE_STATION"] = name
        coverage.Coverage.current().switch_context(name)
        station(line)
    return measured

run_all.STATIONS = [(name, instrument(name, station))
                    for name, station in run_all.STATIONS]
sys.exit(run_all.main(["run_all.py"] + sys.argv[2:]))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="coverage-output")
    parser.add_argument("--coverage-path", help="directory containing an isolated coverage installation")
    parser.add_argument("--station", action="append", help="measure selected stations instead of the full suite")
    args = parser.parse_args()
    if args.coverage_path:
        sys.path.insert(0, str(Path(args.coverage_path).resolve()))
    try:
        import coverage
    except ImportError:
        parser.error("install coverage.py first (baseline version: 7.6.1)")

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error("use an empty output directory so previous data cannot contaminate this run")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="nova-coverage-") as temporary:
        work = Path(temporary).resolve()
        source = work / "source"

        def ignore(folder, names):
            return [name for name in names if name in (".git", "__pycache__", "coverage-output")
                    or (Path(folder) / name).resolve() == output]

        shutil.copytree(ROOT, source, ignore=ignore, symlinks=True)
        manifest = {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(source.rglob("*"))
                    if path.is_file() and path.suffix != ".pyc"}
        (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        raw = output / "raw"
        raw.mkdir()
        config = work / "coverage.ini"
        config.write_text(
            "[run]\nbranch = True\nparallel = True\n"
            "source = " + str(source) + "\n"
            "data_file = " + str(raw / ".coverage") + "\n"
            "context = ${NOVA_COVERAGE_STATION}\n"
            "[paths]\nproject =\n    " + str(ROOT) + "\n    " + str(source) + "\n"
        )
        hook = work / "hook"
        hook.mkdir()
        (hook / "sitecustomize.py").write_text("import coverage\ncoverage.process_startup()\n")
        driver = work / "driver.py"
        driver.write_text(DRIVER)
        env = dict(os.environ)
        env["COVERAGE_PROCESS_START"] = str(config)
        env["NOVA_COVERAGE_STATION"] = ""
        # Use the actual imported package's parent, not a global Python change.
        env["PYTHONPATH"] = os.pathsep.join(
            [str(hook), str(Path(coverage.__file__).resolve().parent.parent)]
            + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        command = [sys.executable, "-u", str(driver), str(source),
                   "--report", str(output / "checks.jsonl")]
        for station in args.station or []:
            command.extend(["--station", station])
        print("Measuring suite; progress log:", output / "suite.log", flush=True)
        with (output / "suite.log").open("w") as log:
            done = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
        raw_files = list(raw.glob(".coverage.*"))
        combined = coverage.Coverage(config_file=str(config), data_file=str(output / ".coverage"))
        combined.combine(data_paths=[str(raw)], keep=True, strict=True)
        combined.save()
        # Analyze against the preserved workspace paths, including unexecuted files.
        source_dirs = sorted({str(path.parent) for path in ROOT.rglob("*.py")
                              if "__pycache__" not in path.parts})
        report = coverage.Coverage(data_file=str(output / ".coverage"), source=source_dirs,
                                   branch=True, config_file=False)
        report.load()
        # Reporting alone does not discover untouched files in directories
        # without __init__.py. Keep them in the denominator explicitly.
        report.get_data().touch_files([str(ROOT / name) for name in manifest
                                       if name.endswith(".py")])
        report.save()
        report.json_report(outfile=str(output / "coverage.json"), show_contexts=True)
        report.html_report(directory=str(output / "html"), show_contexts=True)
        with (output / "coverage.txt").open("w") as summary:
            report.report(file=summary, show_missing=True)
        contexts = sorted(report.get_data().measured_contexts())
        for station in contexts:
            if not station:
                continue
            report.json_report(outfile=str(output / ("station-" + station + ".json")),
                               contexts=["^" + station + "$"], show_contexts=False)
        checks = [json.loads(line) for line in (output / "checks.jsonl").read_text().splitlines()]
        metadata = {
            "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
            "coverage_version": coverage.__version__, "elapsed_seconds": time.monotonic() - started,
            "suite_exit_status": done.returncode, "selected_stations": args.station,
            "checks_passed": sum(bool(row["passed"]) for row in checks),
            "checks_failed": sum(not row["passed"] for row in checks),
            "process_data_files": len(raw_files), "contexts": contexts,
            "scope": "Python files only; .nova and JavaScript source are not instrumented",
        }
        (output / "run.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps(metadata, indent=2))
    return done.returncode


if __name__ == "__main__":
    sys.exit(main())
