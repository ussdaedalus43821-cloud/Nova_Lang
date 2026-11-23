#!/usr/bin/env python3
"""Run the mutants against the fast test suite (the quick tier of tests/run_all.py, the same as the required `fast` check).

    python3 mutation/generate.py                      # choose the mutants (seed 20261117, 200 of them)
    python3 mutation/run_mutants.py --workers 4       # run them; resumes where it stopped
    python3 mutation/generate.py --exhaustive sandbox,steps,nesting --out mutation/mutants_exhaustive.json   # EVERY mutant of those areas
    python3 mutation/run_mutants.py --confirm --mutants mutation/mutants_exhaustive.json --slice 3/14 --results out.jsonl   # one of 14 shares (CI: .github/workflows/mutation.yml)
    python3 mutation/report.py                        # the scores and the survivors

Each worker has its own copy of the repository in mutation/work/. A mutant is written into that copy, the quick tier's stations are run one
at a time (the ones most likely to notice first), and the run stops at the first station that fails (CAUGHT) or ends when every station
passed (SURVIVED). The original file is put back after every mutant and the repository itself is never touched. `--controls N` adds N runs
of the unchanged code, at the same load, to show how often a test fails by itself (it should be 0).
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUT = os.path.join(ROOT, "mutation")
WORK = os.path.join(MUT, "work")
RESULTS = os.path.join(MUT, "results", "results.jsonl")
CONFIRM = False
sys.path.insert(0, MUT)
import generate  # noqa: E402

PRIORITY = {
    "sandbox": ["security", "conformance", "security-matrix", "embedding", "std", "packages", "pkg-capabilities"],
    "nesting": ["security", "conformance", "portability", "compiler"],
    "steps": ["security", "conformance", "std", "embedding"],
    "parser": ["conformance", "compiler", "differential", "types", "fmt-golden", "lint-golden", "editor"],
    "vm": ["compiler", "differential", "conformance", "bytecode"],
    "date": ["std", "conformance"],
    "control": [],
}
COPY_IGNORE = shutil.ignore_patterns(".git", "mutation", "mutation-*", "__pycache__", "*.pyc", "out", ".DS_Store")
lock = threading.Lock()


def station_order(area, times):
    """Cheap stations first, so a mutant that is caught is caught early: the stations most likely to notice this area, if they are cheap (under 100 s),
    then every other station from the quickest to the slowest. Which station comes first changes how long a run takes and never the verdict:
    a mutant is CAUGHT if any station fails."""
    first = [name for name in PRIORITY.get(area, []) if name in times and times[name]["seconds"] <= 100]
    rest = sorted((name for name in times if name not in first), key=lambda name: times[name]["seconds"])
    return first + rest


def prepare_tree(index):
    path = os.path.join(WORK, "w%d" % index)
    if os.path.exists(path):
        shutil.rmtree(path)
    shutil.copytree(ROOT, path, ignore=COPY_IGNORE)
    return path


def clean_caches(tree):
    for folder, dirs, _ in os.walk(tree):
        for name in list(dirs):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(folder, name), ignore_errors=True)
                dirs.remove(name)


def run_station(tree, station, limit_seconds):
    started = time.time()
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    try:
        done = subprocess.run([sys.executable, "-u", "tests/run_all.py", "--quick", "--station", station], cwd=tree, capture_output=True,
                              text=True, timeout=limit_seconds, env=environment)
    except subprocess.TimeoutExpired as problem:
        text = (problem.stdout or b"")
        text = text.decode("utf-8", "replace") if isinstance(text, bytes) else (text or "")
        return "timeout", time.time() - started, text[-600:]
    return ("ok" if done.returncode == 0 else "failed"), time.time() - started, (done.stdout + done.stderr)


def failing_lines(output):
    keep = [line.strip() for line in output.splitlines() if line.strip().startswith(("FAIL:", "ERROR:", "ANDON", "[FAILED]", "AssertionError", "Traceback", "NovaError", "SyntaxError", "ImportError"))]
    return keep[:4]


def run_one(tree_index, trees, mutant, times, sources):
    tree = trees[tree_index]
    started = time.time()
    path = os.path.join(tree, mutant["file"]) if mutant.get("file") else None
    pristine = None
    if path:
        pristine = sources[mutant["file"]]
        candidate = (mutant["file"], mutant["line"], mutant["col"], mutant["end"], mutant["old"], mutant["new"], mutant["kind"])
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(generate.apply(pristine, candidate))
    clean_caches(tree)
    result = {"id": mutant["id"], "caught": False, "station": None, "how": None, "lines": [], "stations_run": []}
    try:
        for station in station_order(mutant["area"], times):
            limit = max(120, int(times[station]["seconds"] * 4) + 90)
            status, seconds, output = run_station(tree, station, limit)
            result["stations_run"].append([station, status, round(seconds, 1)])
            if status == "failed" and CONFIRM:
                # a catch counts only if the same station fails a second time on the same mutant: a failure that does not repeat is noise
                again, seconds2, output2 = run_station(tree, station, limit)
                result["stations_run"].append([station + " (repeat)", again, round(seconds2, 1)])
                if again == "ok":
                    result.setdefault("flaky", []).append({"station": station, "lines": failing_lines(output)})
                    continue
                result["confirmed"] = True
            if status != "ok":
                result.update(caught=True, station=station, how="timeout" if status == "timeout" else "test failed", lines=failing_lines(output))
                break
    finally:
        if path:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(pristine)
    result["seconds"] = round(time.time() - started, 1)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0, help="run only the first N mutants (of the slice, if --slice is given): a trial")
    parser.add_argument("--controls", type=int, default=3)
    parser.add_argument("--only", help="comma-separated mutant ids")
    parser.add_argument("--mutants", help="the mutants file to run (default mutation/mutants.json)")
    parser.add_argument("--confirm", action="store_true", help="repeat a failing station once: a catch counts only if it fails twice (a failure that does not repeat is recorded as flaky)")
    parser.add_argument("--slice", help="I/N: run only every Nth mutant starting at the Ith (0-based), so N machines can share one mutants file; the slices together are the whole file")
    parser.add_argument("--results", help="write to (and resume from) this results file instead of results/results.jsonl, e.g. to re-run the survivors after new tests")
    args = parser.parse_args()
    global RESULTS, CONFIRM
    CONFIRM = args.confirm
    if args.results:
        RESULTS = os.path.abspath(args.results)
    data = json.load(open(args.mutants or os.path.join(MUT, "mutants.json")))
    times = json.load(open(os.path.join(MUT, "results", "station_times.json")))
    mutants = data["mutants"]
    if args.only:
        wanted = set(args.only.split(","))
        mutants = [m for m in mutants if m["id"] in wanted]
    if args.slice:
        index, count = (int(part) for part in args.slice.split("/"))
        assert 0 <= index < count, "--slice I/N needs 0 <= I < N"
        mutants = mutants[index::count]                 # interleaved, so every slice has a mix of the areas and of cheap and dear mutants
    if args.limit:
        mutants = mutants[:args.limit]
    controls = [{"id": "C%d" % (i + 1), "area": "control", "file": None} for i in range(args.controls)]
    # the controls are spread through the run, at the same load as the mutants
    queue = list(mutants)
    for i, control in enumerate(controls):
        queue.insert(min(len(queue), (i + 1) * len(queue) // (len(controls) + 1)), control)
    done_ids = set()
    if os.path.exists(RESULTS):
        for line in open(RESULTS, encoding="utf-8"):
            done_ids.add(json.loads(line)["id"])
    queue = [m for m in queue if m["id"] not in done_ids]
    os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
    sources = {path: generate.read(path) for path in (generate.PY, generate.NOVA, generate.DATE)}
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    trees = [prepare_tree(i) for i in range(args.workers)]
    free = list(range(args.workers))
    started = time.time()
    print("mutants to run: %d (workers %d)" % (len(queue), args.workers), flush=True)

    def job(mutant):
        with lock:
            index = free.pop()
        try:
            return run_one(index, trees, mutant, times, sources)
        finally:
            with lock:
                free.append(index)

    count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for result in pool.map(job, queue):
            count += 1
            with open(RESULTS, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(result) + "\n")
            print("%3d/%d %-5s %-8s %s  %.0fs  elapsed %.0f min" % (count, len(queue), result["id"], "CAUGHT" if result["caught"] else "SURVIVED",
                                                                 result["station"] or "", result["seconds"], (time.time() - started) / 60), flush=True)
    shutil.rmtree(WORK, ignore_errors=True)
    print("done in %.1f minutes" % ((time.time() - started) / 60))


if __name__ == "__main__":
    main()
