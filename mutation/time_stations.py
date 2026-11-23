"""Time each station of the quick tier on the unmutated code (serial), so the mutation runner can order them."""
import json, subprocess, sys, time, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import run_all
names = [n for n, _ in run_all.STATIONS if n != "parity"]
out = {}
for name in names:
    t = time.time()
    done = subprocess.run([sys.executable, "-u", "tests/run_all.py", "--quick", "--station", name], cwd=ROOT,
                          capture_output=True, text=True)
    out[name] = {"seconds": round(time.time() - t, 1), "ok": done.returncode == 0}
    print(name, out[name], flush=True)
json.dump(out, open(os.path.join(ROOT, "mutation", "results", "station_times.json"), "w"), indent=1)
print("total", round(sum(v["seconds"] for v in out.values()), 1))
