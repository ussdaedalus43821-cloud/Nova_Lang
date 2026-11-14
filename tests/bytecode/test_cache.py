"""The compiled-artifact cache (docs/spec/17-bytecode.md [bc.cache]): what it names, where it writes, what it refuses, and that it never changes a run.

Every test runs the real command line with `--cache-dir` pointing at a folder of its own (or with XDG_CACHE_HOME there), and reads the cache's own
account of what it did from NOVALANG_CACHE_DEBUG (`novalang cache: hit|miss|stored|rejected <key>` on standard error). The suite's environment turns
the cache off for everything else (NOVALANG_CACHE=off); these tests take that out of the environment they give the child."""
import os
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from common import ROOT, nl

PROGRAM = 'def f(n) { return n * 2 }\nlet total = 0\nfor i = 1 to 5 { total = total + f(i) }\nprint("total", total)\n'
POSIX = sys.platform != "win32"


def environment(**extra):
    env = {k: v for k, v in os.environ.items() if k not in ("NOVALANG_CACHE", "NOVALANG_CACHE_DEBUG", "XDG_CACHE_HOME")}
    env["NOVALANG_CACHE_DEBUG"] = "1"
    env.update(extra)
    return env


@unittest.skipUnless(POSIX, "the cache is off on Windows (a decision of the owner, [bc.cache])")
class Cache(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.work = self.root / "work"
        self.work.mkdir()

    def write(self, name, text):
        path = self.work / name
        path.write_text(text, encoding="utf-8")
        return path

    def nova(self, *args, env=None, cwd=None, cache=True, stdin=None):
        flags = ["--cache-dir", str(self.cache)] if cache is True else []
        done = subprocess.run([sys.executable, str(ROOT / "novalang.py"), *flags, *args], cwd=str(cwd or self.work), capture_output=True, text=True,
                              env=env or environment(), stdin=subprocess.DEVNULL if stdin is None else None, input=stdin, timeout=120)
        notes = [line.split(" ", 3)[2:] for line in done.stderr.splitlines() if line.startswith("novalang cache: ")]
        rest = "".join(line + "\n" for line in done.stderr.splitlines() if not line.startswith("novalang cache: "))
        return done.returncode, done.stdout, rest, [" ".join(n) for n in notes]

    def entries(self):
        return sorted(p.name for p in self.cache.glob("*")) if self.cache.exists() else []

    def key(self, text):
        return nl.cache_key(text)

    # -- the basic life of an entry
    def test_bc_cache_cold_then_warm(self):
        program = self.write("p.nova", PROGRAM)
        first = self.nova(str(program))
        second = self.nova(str(program))
        third = self.nova(str(program))
        self.assertEqual(first[:3], (0, "total 30\n", ""))
        self.assertEqual(second[:3], first[:3])
        self.assertEqual(third[:3], first[:3])
        self.assertEqual([n.split(" ")[0] for n in first[3]], ["miss", "stored"])
        self.assertEqual([n.split(" ")[0] for n in second[3]], ["hit"])
        self.assertEqual([n.split(" ")[0] for n in third[3]], ["hit"])
        self.assertEqual(self.entries(), [self.key(PROGRAM) + ".novac"])

    def test_bc_cache_the_entry_is_a_valid_artifact_of_the_source_and_private(self):
        program = self.write("p.nova", PROGRAM)
        self.nova(str(program))
        path = self.cache / (self.key(PROGRAM) + ".novac")
        loaded = nl.load_artifact(path.read_bytes(), PROGRAM)
        self.assertEqual(loaded.source, PROGRAM)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0, "files are written 0600")
        self.assertEqual(stat.S_IMODE(self.cache.stat().st_mode), 0o700, "the directory is made 0700")
        self.assertEqual(path.read_bytes(), nl.compile_artifact(PROGRAM), "the entry is exactly what --compile writes")

    def test_bc_cache_the_key_is_the_source_and_nothing_else(self):
        a = self.write("a.nova", PROGRAM)
        other_folder = self.root / "elsewhere"
        other_folder.mkdir()
        b = other_folder / "renamed.nova"
        b.write_text(PROGRAM, encoding="utf-8")
        self.nova(str(a))
        again = self.nova(str(b), cwd=other_folder)              # another path, another name, another working directory
        self.assertEqual([n.split(" ")[0] for n in again[3]], ["hit"])
        self.assertEqual(len(self.entries()), 1)
        trusted_with_limits = self.nova("--profile", "restricted", str(b))     # the profile is not part of the key
        self.assertEqual([n.split(" ")[0] for n in trusted_with_limits[3]], ["hit"])
        changed = self.write("a.nova", PROGRAM + "# a comment is a different source\n")
        self.assertEqual([n.split(" ")[0] for n in self.nova(str(changed))[3]], ["miss", "stored"])
        self.assertEqual(len(self.entries()), 2)

    def test_bc_cache_the_key_depends_on_version_format_and_instruction_set(self):
        base = self.key("x")
        for name, replacement in (("ARTIFACT_FORMAT", 9), ("__version__", "9.9.9")):
            with self.subTest(name):
                saved = getattr(nl, name)
                setattr(nl, name, replacement)
                try:
                    self.assertNotEqual(nl.cache_key("x"), base)
                finally:
                    setattr(nl, name, saved)
        saved = nl.ARTIFACT_TABLE
        nl.ARTIFACT_TABLE = (("LOAD_CONST", "const", "+2"),) + tuple(saved[1:])
        try:
            self.assertNotEqual(nl.cache_key("x"), base)
        finally:
            nl.ARTIFACT_TABLE = saved
        self.assertEqual(nl.cache_key("x"), base)
        self.assertEqual(len(base), 64)

    # -- a hit never changes a run
    def test_bc_cache_a_hit_gives_the_same_output_errors_and_lines(self):
        cases = {"ok": PROGRAM, "error": "let a = 1\nprint(a / 0)\n", "exit": 'print("bye")\nexit(3)\n',
                 "caught": 'try { throw("x") } catch e { print("caught", e) }\n',
                 "args": "print(args())\n"}
        for name, source in cases.items():
            with self.subTest(name):
                path = self.write(name + ".nova", source)
                uncached = self.nova(str(path), "p", "q", cache=False, env=environment(NOVALANG_CACHE="off"))
                cold = self.nova(str(path), "p", "q")
                warm = self.nova(str(path), "p", "q")
                self.assertEqual(cold[:3], uncached[:3])
                self.assertEqual(warm[:3], uncached[:3])
                self.assertEqual(warm[3][0].split(" ")[0], "hit")

    def test_bc_cache_the_benchmark_programs_run_the_same_from_the_cache(self):
        micro = sorted((ROOT / "tests" / "benchmarks" / "workloads" / "micro").glob("*.nova"))
        self.assertGreaterEqual(len(micro), 8)
        for path in micro:
            if path.name in ("arithmetic.nova", "float_math.nova"):
                continue                         # the longest; the others use the same instructions
            with self.subTest(path.name):
                uncached = self.nova(str(path), cache=False, env=environment(NOVALANG_CACHE="off"), cwd=path.parent)
                cold = self.nova(str(path), cwd=path.parent)
                warm = self.nova(str(path), cwd=path.parent)
                self.assertEqual(uncached[0], 0)
                self.assertEqual((cold[0], cold[1]), (uncached[0], uncached[1]))
                self.assertEqual((warm[0], warm[1]), (uncached[0], uncached[1]))

    def test_bc_cache_a_hit_still_runs_the_type_gate(self):
        failing = next((ROOT / "tests" / "typecheck" / "fail").glob("*.nova"))
        source = failing.read_text(encoding="utf-8")
        program = self.write("typed.nova", source)
        refused = self.nova(str(program))
        self.assertNotEqual(refused[0], 0)
        self.assertEqual(self.entries(), [], "a program the type gate refuses is not cached")
        # an entry for that source, written by hand: the gate must still refuse it
        self.cache.mkdir(mode=0o700, exist_ok=True)       # the refused run made the (empty) directory
        (self.cache / (self.key(source) + ".novac")).write_bytes(nl.compile_artifact(source))
        again = self.nova(str(program))
        self.assertEqual(again[0], refused[0])
        self.assertEqual(again[2], refused[2])
        self.assertEqual(again[3][0].split(" ")[0], "hit")

    def test_bc_cache_the_profile_still_gates_names_on_a_hit(self):
        program = self.write("p.nova", 'print(read("data.txt"))\n')
        (self.work / "data.txt").write_text("hello", encoding="utf-8")
        cold = self.nova(str(program))
        restricted = self.nova("--profile", "restricted", "--cache-dir", str(self.cache), str(program), cache=False)
        self.assertEqual(cold[:2], (0, "hello\n"))
        self.assertEqual(restricted[0], 1)
        self.assertIn("undefined name 'read'", restricted[2])
        self.assertEqual(restricted[3][0].split(" ")[0], "hit")

    # -- modules
    def test_bc_cache_each_module_is_keyed_on_its_own_text(self):
        util = 'export def double(n) { return n * 2 }\n'
        self.write("util.nova", util)
        main = self.write("main.nova", 'import "util.nova" as util\nprint(util.double(21))\n')
        first = self.nova(str(main))
        self.assertEqual(first[:2], (0, "42\n"))
        self.assertEqual(len(self.entries()), 2)
        second = self.nova(str(main))
        self.assertEqual([n.split(" ")[0] for n in second[3]], ["hit", "hit"])
        self.write("util.nova", 'export def double(n) { return n * 3 }\n')
        third = self.nova(str(main))
        self.assertEqual(third[:2], (0, "63\n"))
        self.assertEqual(sorted(n.split(" ")[0] for n in third[3]), ["hit", "miss", "stored"])
        self.assertEqual(len(self.entries()), 3)

    # -- what makes it ignore an entry
    def test_bc_cache_a_damaged_entry_is_ignored_and_replaced(self):
        program = self.write("p.nova", PROGRAM)
        self.nova(str(program))
        path = self.cache / (self.key(PROGRAM) + ".novac")
        good = path.read_bytes()
        for label, data in (("garbage", b"not an artifact at all" * 20), ("empty", b""), ("cut", good[:len(good) // 2]),
                            ("a flipped byte", good[:50] + bytes((good[50] ^ 1,)) + good[51:])):
            with self.subTest(label):
                path.write_bytes(data)
                os.chmod(str(path), 0o600)
                run = self.nova(str(program))
                self.assertEqual(run[:3], (0, "total 30\n", ""))
                self.assertEqual([n.split(" ")[0] for n in run[3] if n.split(" ")[0] in ("miss", "hit", "rejected", "stored")][0:1], ["rejected"])
                self.assertEqual(path.read_bytes(), good, "the entry was replaced")
                self.assertEqual(self.nova(str(program))[3][0].split(" ")[0], "hit")

    def test_bc_cache_an_entry_made_for_another_source_is_refused(self):
        program = self.write("p.nova", PROGRAM)
        self.nova(str(program))
        path = self.cache / (self.key(PROGRAM) + ".novac")
        path.write_bytes(nl.compile_artifact('print("somebody else")\n'))
        os.chmod(str(path), 0o600)
        run = self.nova(str(program))
        self.assertEqual(run[:2], (0, "total 30\n"))
        self.assertIn("rejected", run[3][0])
        self.assertEqual(nl.load_artifact(path.read_bytes()).source, PROGRAM)

    def test_bc_cache_an_entry_from_another_format_or_instruction_set_is_refused(self):
        program = self.write("p.nova", PROGRAM)
        self.nova(str(program))
        path = self.cache / (self.key(PROGRAM) + ".novac")
        good = path.read_bytes()
        from common import fields, mutate
        f = fields(good)
        for label, data in (("format version", mutate(good, f["format"][0], 7)), ("instruction set", mutate(good, f["opcode_hash"][0], good[f["opcode_hash"][0]] ^ 255))):
            with self.subTest(label):
                path.write_bytes(data)
                os.chmod(str(path), 0o600)
                run = self.nova(str(program))
                self.assertEqual(run[:2], (0, "total 30\n"))
                self.assertIn("rejected", run[3][0])
                self.assertEqual(path.read_bytes(), good)

    def test_bc_cache_a_symbolic_link_is_never_followed(self):
        program = self.write("p.nova", PROGRAM)
        self.cache.mkdir(mode=0o700)
        decoy = self.root / "decoy.novac"
        decoy.write_bytes(nl.compile_artifact(PROGRAM))          # a perfectly good artifact, one step away
        link = self.cache / (self.key(PROGRAM) + ".novac")
        os.symlink(str(decoy), str(link))
        before = decoy.read_bytes()
        run = self.nova(str(program))
        self.assertEqual(run[:2], (0, "total 30\n"))
        self.assertNotIn("hit", [n.split(" ")[0] for n in run[3]], "the link was followed")
        self.assertEqual(decoy.read_bytes(), before, "what the link points at is not written")
        self.assertFalse(link.is_symlink(), "the link itself was replaced by a regular file")

    def test_bc_cache_a_directory_others_can_write_is_not_used(self):
        program = self.write("p.nova", PROGRAM)
        self.cache.mkdir()
        os.chmod(str(self.cache), 0o770)
        run = self.nova(str(program))
        self.assertEqual(run[:3], (0, "total 30\n", ""))
        self.assertEqual(self.entries(), [], "nothing was written")
        self.assertTrue(any("cannot be used" in n for n in run[3]) or run[3] == [], run[3])
        os.chmod(str(self.cache), 0o707)
        self.assertEqual(self.nova(str(program))[:2], (0, "total 30\n"))
        self.assertEqual(self.entries(), [])

    def test_bc_cache_an_entry_others_can_write_is_not_read(self):
        program = self.write("p.nova", PROGRAM)
        self.nova(str(program))
        path = self.cache / (self.key(PROGRAM) + ".novac")
        os.chmod(str(path), 0o666)
        run = self.nova(str(program))
        self.assertEqual(run[:2], (0, "total 30\n"))
        self.assertIn("rejected", run[3][0])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can write to a read-only directory")
    def test_bc_cache_a_read_only_directory_does_not_fail_the_program(self):
        program = self.write("p.nova", PROGRAM)
        self.cache.mkdir(mode=0o700)
        os.chmod(str(self.cache), 0o500)
        self.addCleanup(os.chmod, str(self.cache), 0o700)
        run = self.nova(str(program))
        self.assertEqual(run[:3], (0, "total 30\n", ""))
        self.assertEqual(self.entries(), [])

    def test_bc_cache_no_temporary_files_are_left_behind(self):
        for i in range(6):
            self.nova(str(self.write("p{}.nova".format(i), PROGRAM + "print({})\n".format(i))))
        self.assertEqual([n for n in self.entries() if not n.endswith(".novac")], [])
        self.assertEqual(len(self.entries()), 6)

    def test_bc_cache_concurrent_runs_of_one_new_program_agree(self):
        program = self.write("p.nova", PROGRAM)
        results = []

        def go():
            results.append(self.nova(str(program)))

        threads = [threading.Thread(target=go) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 8)
        for result in results:
            self.assertEqual(result[:3], (0, "total 30\n", ""))
        self.assertEqual(self.entries(), [self.key(PROGRAM) + ".novac"])
        self.assertEqual(nl.load_artifact((self.cache / self.entries()[0]).read_bytes(), PROGRAM).source, PROGRAM)

    # -- when it is off
    def test_bc_cache_off_with_the_flag_and_with_the_environment(self):
        program = self.write("p.nova", PROGRAM)
        flagged = self.nova("--no-cache", str(program))
        self.assertEqual(flagged[:3], (0, "total 30\n", ""))
        self.assertEqual(flagged[3], [])
        env = self.nova(str(program), env=environment(NOVALANG_CACHE="off"))
        self.assertEqual(env[3], [])
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.nova("--no-cache", "--cache-dir", str(self.cache), str(program), cache=False)[3], [], "the flag wins over a directory")

    def test_bc_cache_off_for_the_restricted_profile_unless_a_directory_is_named(self):
        program = self.write("p.nova", PROGRAM)
        xdg = self.root / "xdg"
        env = environment(XDG_CACHE_HOME=str(xdg))
        quiet = self.nova("--profile", "restricted", str(program), cache=False, env=env)
        self.assertEqual(quiet[:3], (0, "total 30\n", ""))
        self.assertEqual(quiet[3], [])
        self.assertFalse(xdg.exists(), "a restricted run does not even choose a directory")
        named = self.nova("--profile", "restricted", str(program))
        self.assertEqual([n.split(" ")[0] for n in named[3]], ["miss", "stored"])

    def test_bc_cache_on_by_default_for_the_trusted_profile_in_the_users_directory(self):
        program = self.write("p.nova", PROGRAM)
        xdg = self.root / "xdg"
        env = environment(XDG_CACHE_HOME=str(xdg), HOME=str(self.root / "home"))
        first = self.nova(str(program), cache=False, env=env)
        self.assertEqual([n.split(" ")[0] for n in first[3]], ["miss", "stored"])
        self.assertEqual([p.name for p in (xdg / "novalang").glob("*")], [self.key(PROGRAM) + ".novac"])
        self.assertEqual(nl.default_cache_directory({"XDG_CACHE_HOME": "/x", "HOME": "/h"}), "/x/novalang")
        if sys.platform == "darwin":
            self.assertEqual(nl.default_cache_directory({"HOME": "/h"}), "/h/Library/Caches/novalang")
        else:
            self.assertEqual(nl.default_cache_directory({"HOME": "/h"}), "/h/.cache/novalang")

    def test_bc_cache_not_for_standard_input_the_repl_or_code_on_the_command_line(self):
        run = self.nova("1 + 2")
        self.assertEqual((run[0], run[1], run[3]), (0, "3\n", []))
        repl = self.nova(cache=True, stdin="1 + 1\n")
        self.assertEqual(repl[3], [])
        self.assertEqual(self.entries(), [])

    def test_bc_cache_an_isolated_child_follows_the_parents_decision(self):
        program = self.write("p.nova", PROGRAM)
        xdg = self.root / "xdg"
        env = environment(XDG_CACHE_HOME=str(xdg), HOME=str(self.root / "home"), NOVALANG_CACHE="off")
        off = self.nova("--isolate", str(program), cache=False, env=env)
        self.assertEqual(off[:2], (0, "total 30\n"), off[2])
        self.assertFalse(xdg.exists(), "the child has a clean environment: it must be told that the cache is off")
        on = self.nova("--isolate", str(program))                 # --cache-dir is forwarded to the child
        self.assertEqual(on[:2], (0, "total 30\n"), on[2])
        self.assertEqual(self.entries(), [self.key(PROGRAM) + ".novac"])

    def test_bc_cache_not_for_the_other_engines(self):
        program = self.write("p.nova", PROGRAM)
        tree = self.nova("--tree-walk", str(program))
        self.assertEqual(tree[:2], (0, "total 30\n"))
        self.assertEqual(tree[3], [])
        self.assertEqual(self.entries(), [])

    def test_bc_cache_a_program_too_large_to_write_runs_from_source(self):
        depth = nl.ARTIFACT_LIMITS["depth"] + 2
        source = "".join("def f{}() {{\n".format(i) for i in range(depth)) + "print(1)\n" + "".join("}\n" for _ in range(depth))
        program = self.write("deep.nova", source)
        run = self.nova(str(program))
        if run[0] != 0 and "recursion" in run[2]:
            self.skipTest("the parser refuses this nesting before the cache has to")
        self.assertEqual(self.entries(), [])

    def test_bc_cache_windows_has_no_cache(self):
        import contextlib
        import io
        saved = nl.sys.platform
        nl.sys.platform = "win32"
        notice = io.StringIO()
        try:
            with contextlib.redirect_stderr(notice):
                self.assertIsNone(nl.cache_for_run(nl.Capabilities(), str(self.cache), {}))
            self.assertIsNone(nl.default_cache_directory({"HOME": "/h"}))
        finally:
            nl.sys.platform = saved
            nl.CACHE_SETTINGS.pop("warned", None)
        self.assertIn("not available on Windows", notice.getvalue())
        self.assertIsNotNone(nl.cache_for_run(nl.Capabilities(), str(self.cache), {}))


if __name__ == "__main__":
    unittest.main()
