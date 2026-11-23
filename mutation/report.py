#!/usr/bin/env python3
"""Scores and survivors of a mutation run. Read-only.

    python3 mutation/report.py                                   # mutation/mutants.json and mutation/results/results.jsonl
    python3 mutation/report.py --mutants mutation/mutants_exhaustive.json --results slice-*.jsonl --markdown

A mutant counts as caught when a test station failed on it (and, with `run_mutants.py --confirm`, failed again) or timed out. A failure that did
not repeat is listed as flaky and is not a catch. Timeouts are counted apart, because a mutant that makes the program loop forever is caught by the
clock and not by an assertion.
"""
import argparse, collections, glob, json, os

MUT = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mutants", default=os.path.join(MUT, "mutants.json"))
    parser.add_argument("--results", nargs="+", default=[os.path.join(MUT, "results", "results.jsonl")], help="results files (globs allowed)")
    parser.add_argument("--markdown", action="store_true", help="a Markdown report (for a job summary)")
    args = parser.parse_args()
    data = json.load(open(args.mutants))
    by_id = {m["id"]: m for m in data["mutants"]}
    results = {}
    for pattern in args.results:
        for path in sorted(glob.glob(pattern)) or [pattern]:
            if not os.path.exists(path):
                continue
            for line in open(path, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    results[r["id"]] = r
    rows = [(by_id[i], r) for i, r in sorted(results.items()) if i in by_id]
    missing = sorted(set(by_id) - set(results))
    total = len(rows)
    caught = sum(r["caught"] for _, r in rows)
    out = []
    say = out.append
    h = (lambda t: say("\n### " + t + "\n")) if args.markdown else (lambda t: say("\n" + t))
    say("overall: %d caught of %d = %.1f%%  (%d survived%s)" % (caught, total, 100.0 * caught / max(total, 1), total - caught,
                                                              ", %d not run" % len(missing) if missing else ""))
    areas = collections.OrderedDict()
    for m, r in rows:
        a = areas.setdefault(m["area"], [0, 0])
        a[1] += 1
        a[0] += r["caught"]
    h("per area")
    for area, (c, t) in areas.items():
        say("- %-8s %4d / %4d = %5.1f%%   survivors %d" % (area, c, t, 100.0 * c / t, t - c))
    how = collections.Counter((r["how"] or "survived") for _, r in rows)
    say("\nhow caught: %s" % dict(how))
    stations = collections.Counter(r["station"] for _, r in rows if r["caught"])
    say("caught by station: %s" % dict(stations.most_common()))
    flaky = [(m, r) for m, r in rows if r.get("flaky")]
    say("failures that did not repeat (flaky, not counted as catches): %d mutants" % len(flaky))
    timeouts = [m["id"] for m, r in rows if r["how"] == "timeout"]
    say("caught only by a timeout (a runaway loop or an overloaded runner): %d  %s" % (len(timeouts), " ".join(timeouts[:40])))
    controls = [(i, "FAIL" if r["caught"] else "pass") for i, r in sorted(results.items()) if i.startswith("C")]
    say("controls (unchanged code; every one must pass): %s" % controls)
    h("survivors")
    for m, r in rows:
        if not r["caught"]:
            say("%s  %-8s %s:%d  [%s]\n      before: %s\n      after:  %s" % (m["id"], m["area"], m["file"], m["line"], m["kind"],
                                                                         m["line_before"][:150], m["line_after"][:150]))
    if flaky:
        h("flaky failures (a station failed once and passed on repeat)")
        for m, r in flaky:
            say("%s  %-8s %s:%d  %s  %s" % (m["id"], m["area"], m["file"], m["line"], "caught anyway" if r["caught"] else "SURVIVED",
                                          [f["station"] for f in r["flaky"]]))
    text = "\n".join(out)
    print("```\n" + text + "\n```" if args.markdown else text)


if __name__ == "__main__":
    main()
