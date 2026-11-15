"""The final-component TOCTOU race, run under a stopwatch ([sbx.toctou], G-054 Part A).

`[sbx.paths]` resolves a path's real name, then the file function opens that same path in a later
syscall. A process that can write the granted folder may swap the final name for a symbolic link out
of the grant between the two steps. This test *is* that process: a background thread flips an in-grant
name between a benign file and a link to an out-of-grant secret, in a tight loop, while a sandboxed
`restricted` program reads (or writes) the name thousands of times.

Before the fix the sandboxed reader read the secret, and the sandboxed writer wrote outside the grant,
hundreds of times a minute. With the final component opened `O_NOFOLLOW` (POSIX) or verified by handle
(Windows), a terminal symbolic link is refused in the open, so the count is **zero** however the two
threads interleave. The test asserts both that the race really happened (the swapper placed the
out-of-grant link many times) and that not one read leaked or one write escaped.

The guard is a host native (the bytecode VM and the tree-walker, i.e. the embedding API and
`--profile restricted`); the self-hosted engine does not apply it (divergence D-047), so this probe
drives the command-line interpreter, which runs on the VM. It needs real symbolic links, so it is
skipped where the platform or the file system cannot make them (Windows developer mode is off in CI).
"""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NOVA = os.path.join(ROOT, "novalang.py")

ITERATIONS = 4000           # enough for the race to land many times; a few hundred ms per victim


def _symlinks_work():
    if os.name == "nt":
        return False
    try:
        with tempfile.TemporaryDirectory() as folder:
            os.symlink("target", os.path.join(folder, "link"))
        return True
    except (OSError, NotImplementedError):
        return False


READ_VICTIM = """\
let hits = 0
let i = 0
while i < {n} {{
    try {{
        let t = read("target")
        if t == "SECRET" {{ hits = hits + 1 }}
    }} catch e {{ }}
    i = i + 1
}}
print(hits)
"""

WRITE_VICTIM = """\
let i = 0
while i < {n} {{
    try {{ write("target", "PWNED") }} catch e {{ }}
    i = i + 1
}}
print("done")
"""


def _run_victim(program, grant, flag):
    path = os.path.join(grant, "main.nova")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(program.format(n=ITERATIONS))
    argv = [sys.executable, NOVA, "--profile", "restricted", flag, ".", path]
    return subprocess.run(argv, capture_output=True, text=True, timeout=600, cwd=grant)


@unittest.skipUnless(_symlinks_work(), "the file system cannot make symbolic links (e.g. Windows without developer mode)")
class Toctou(unittest.TestCase):
    """A symbolic link swapped in for the final path component is refused, not followed, mid-race."""

    def setUp(self):
        self.grant = tempfile.mkdtemp(prefix="toctou_grant_")
        self.outside = tempfile.mkdtemp(prefix="toctou_outside_")
        self.addCleanup(self._clean)

    def _clean(self):
        import shutil
        shutil.rmtree(self.grant, ignore_errors=True)
        shutil.rmtree(self.outside, ignore_errors=True)

    def test_a_read_never_follows_a_final_link_swapped_in_during_the_race(self):
        secret = os.path.join(self.outside, "secret")
        with open(secret, "w", encoding="utf-8") as handle:
            handle.write("SECRET")                         # the out-of-grant payload a leak would return
        target = os.path.join(self.grant, "target")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("benign")
        stop = threading.Event()
        swaps = [0]

        def swapper():
            while not stop.is_set():
                try:
                    os.remove(target)
                    os.symlink(secret, target)             # the swap: the final name is now a link out
                    swaps[0] += 1
                    os.remove(target)
                    with open(target, "w", encoding="utf-8") as back:
                        back.write("benign")
                except OSError:
                    pass

        thread = threading.Thread(target=swapper, daemon=True)
        thread.start()
        done = _run_victim(READ_VICTIM, self.grant, "--allow-read")
        stop.set()
        thread.join(timeout=5)
        tail = done.stdout.strip().splitlines()
        leaks = int(tail[-1]) if tail and tail[-1].lstrip("-").isdigit() else -1
        self.assertGreater(swaps[0], 0, "the race never placed the out-of-grant link; the probe proved nothing")
        self.assertEqual(leaks, 0,
                         "a restricted read followed a final-component symbolic link out of the grant "
                         "{} time(s) during the race (stdout={!r}, stderr={!r})".format(leaks, done.stdout, done.stderr))

    def test_a_write_never_follows_a_final_link_swapped_in_during_the_race(self):
        escaped = os.path.join(self.outside, "escaped")    # the out-of-grant file a write must never reach
        target = os.path.join(self.grant, "target")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("ok")
        stop = threading.Event()
        swaps = [0]
        escapes = [0]

        def swapper():
            while not stop.is_set():
                try:
                    if os.path.lexists(target):
                        os.remove(target)
                    os.symlink(escaped, target)            # the swap: a write would land on `escaped`
                    swaps[0] += 1
                    if os.path.lexists(escaped):
                        with open(escaped, encoding="utf-8") as check:
                            if check.read() == "PWNED":
                                escapes[0] += 1
                        os.remove(escaped)
                    os.remove(target)
                    with open(target, "w", encoding="utf-8") as back:
                        back.write("ok")
                except OSError:
                    pass

        thread = threading.Thread(target=swapper, daemon=True)
        thread.start()
        _run_victim(WRITE_VICTIM, self.grant, "--allow-write")
        stop.set()
        thread.join(timeout=5)
        if os.path.lexists(escaped):
            try:
                with open(escaped, encoding="utf-8") as check:
                    if check.read() == "PWNED":
                        escapes[0] += 1
            except OSError:
                pass
        self.assertGreater(swaps[0], 0, "the race never placed the out-of-grant link; the probe proved nothing")
        self.assertEqual(escapes[0], 0,
                         "a restricted write followed a final-component symbolic link and wrote outside the "
                         "grant {} time(s) during the race".format(escapes[0]))


if __name__ == "__main__":
    unittest.main()
