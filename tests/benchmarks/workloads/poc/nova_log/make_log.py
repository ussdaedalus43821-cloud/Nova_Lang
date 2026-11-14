"""Synthetic web-server access log in the combined format, seeded so it is reproducible.
usage: python3 make_log.py OUT_PATH [megabytes]"""
import random, sys

out = sys.argv[1]
target = int(float(sys.argv[2]) * 1024 * 1024) if len(sys.argv) > 2 else 50 * 1024 * 1024
rng = random.Random(20261112)

STATUS = [(200, 62.0), (304, 14.0), (301, 4.0), (302, 3.0), (404, 9.0), (403, 1.5), (400, 0.8),
          (401, 1.0), (500, 2.2), (502, 0.8), (503, 0.5), (206, 0.7), (429, 0.5)]
CODES = [c for c, _ in STATUS]
WEIGHTS = [w for _, w in STATUS]
METHODS = ["GET"] * 85 + ["POST"] * 10 + ["HEAD"] * 3 + ["PUT"] * 1 + ["DELETE"] * 1
PATHS = ["/", "/index.html", "/about", "/api/v1/users", "/api/v1/orders", "/static/app.js", "/static/site.css",
         "/images/logo.png", "/login", "/logout", "/search?q=nova+lang", "/products/%d", "/blog/post-%d", "/favicon.ico"]
AGENTS = ["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
          "curl/8.4.0", "Googlebot/2.1 (+http://www.google.com/bot.html)", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"]
REFERRERS = ["-", "-", "https://example.com/", "https://www.google.com/", "https://news.example.org/story/42"]
MONTHS = ["Nov"]

written, n = 0, 0
with open(out, "w", encoding="utf-8", newline="\n") as f:
    while written < target:
        n += 1
        ip = "%d.%d.%d.%d" % (rng.randint(1, 223), rng.randint(0, 255), rng.randint(0, 255), rng.randint(1, 254))
        sec = n % 86400
        stamp = "%02d/Nov/2026:%02d:%02d:%02d +0000" % (1 + (n // 86400) % 28, sec // 3600, sec // 60 % 60, sec % 60)
        path = rng.choice(PATHS)
        if "%d" in path:
            path = path % rng.randint(1, 9999)
        status = rng.choices(CODES, WEIGHTS)[0]
        size = 0 if status in (301, 302, 304) else rng.randint(120, 90000)
        user = "-" if rng.random() < 0.97 else "alice"
        # a few awkward lines on purpose: a quote inside the request, a bare dash for the size, a short line
        roll = rng.random()
        if roll < 0.0005:
            line = '%s - %s [%s] "GET /odd\\"path HTTP/1.1" %d %d "-" "%s"' % (ip, user, stamp, status, size, rng.choice(AGENTS))
        elif roll < 0.001:
            line = '%s - - [%s] "-" 408 - "-" "-"' % (ip, stamp)
        elif roll < 0.0012:
            line = "garbage line %d with no structure" % n
        else:
            line = '%s - %s [%s] "%s %s HTTP/1.1" %d %d "%s" "%s"' % (
                ip, user, stamp, rng.choice(METHODS), path, status, size, rng.choice(REFERRERS), rng.choice(AGENTS))
        f.write(line + "\n")
        written += len(line.encode("utf-8")) + 1
print("%d lines, %.1f MB -> %s" % (n, written / 1048576, out))
