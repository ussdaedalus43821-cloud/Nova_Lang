"""The sandbox profile through the embedding API and the command line, on both Python engines.

What the conformance cases cannot say: the shape of the configuration errors, that one compiled script
is right for a trusted and a restricted engine, what exit() does inside a host program, that two engines
share no grants, and what the command line refuses (docs/spec/16-sandbox.md).
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import novalang as nl  # noqa: E402

ENGINES = ("vm", "tree")


class SandboxFolder(unittest.TestCase):
    def setUp(self):
        if nl.SANDBOX_UNSUPPORTED:
            self.skipTest("the restricted profile needs Python 3.8 or later on Windows")
        self.folder = tempfile.TemporaryDirectory(prefix="nova-sandbox-")
        self.addCleanup(self.folder.cleanup)
        self.root = os.path.realpath(self.folder.name)
        os.makedirs(os.path.join(self.root, "data"))
        with open(os.path.join(self.root, "data", "in.txt"), "w") as handle:
            handle.write("hello")
        with open(os.path.join(self.root, "secret.txt"), "w") as handle:
            handle.write("top secret")
        self.here = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.here)


class Configuration(unittest.TestCase):
    def setUp(self):
        if nl.SANDBOX_UNSUPPORTED:
            self.skipTest("the restricted profile needs Python 3.8 or later on Windows")

    def test_unknown_settings_are_refused_when_the_engine_is_made(self):
        for settings in ({"reed": ["x"]}, {"limits": {"stepz": 5}}, {"limits": {"steps": 0}},
                         {"clock": "yes"}, {"read": "data"}):
            with self.assertRaises(nl.NovaLangError, msg=settings):
                nl.Nova(profile="restricted", **settings)

    def test_trusted_takes_no_grants(self):
        with self.assertRaises(nl.NovaLangError):
            nl.Nova(profile="trusted", read=["data"])
        with self.assertRaises(nl.NovaLangError):
            nl.Nova(profile="paranoid")

    def test_the_default_is_trusted_and_nothing_changes(self):
        for engine in ENGINES:
            self.assertIs(nl.Nova(engine).interpreter.caps, nl.TRUSTED)
            self.assertEqual(nl.Nova(engine).eval("1 + 1"), 2)


class Gating(SandboxFolder):
    def test_a_denied_name_is_undefined_even_as_a_value(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted")
            for source in ('read("data/in.txt")', "let f = read", "let g = [time, now]", "print(env)"):
                with self.assertRaises(nl.NovaLangError, msg=(engine, source)) as caught:
                    nova.eval(source)
                self.assertIn("undefined name", str(caught.exception))

    def test_one_compiled_script_is_right_for_both_profiles(self):
        script = nl.Nova().compile('read("data/in.txt")')
        trusted, restricted = nl.Nova(), nl.Nova(profile="restricted", read=["data"])
        denied = nl.Nova(profile="restricted")
        self.assertEqual(script.run(trusted), "hello")
        self.assertEqual(script.run(restricted), "hello")
        with self.assertRaises(nl.NovaLangError):
            script.run(denied)

    def test_two_engines_share_no_grants(self):
        a = nl.Nova(profile="restricted", read=["data"])
        b = nl.Nova(profile="restricted")
        self.assertEqual(a.eval('read("data/in.txt")'), "hello")
        with self.assertRaises(nl.NovaLangError):
            b.eval('read("data/in.txt")')

    def test_a_function_the_host_calls_is_gated_like_the_program(self):
        nova = nl.Nova(profile="restricted", read=["data"])
        nova.exec('def peek(path) { return read(path) }')
        self.assertEqual(nova.call("peek", "data/in.txt"), "hello")
        with self.assertRaises(nl.NovaLangError) as caught:
            nova.call("peek", "secret.txt")
        self.assertIn("outside the folders", str(caught.exception))

    def test_map_and_friends_cannot_smuggle_a_denied_function(self):
        nova = nl.Nova(profile="restricted", read=["data"])
        with self.assertRaises(nl.NovaLangError):
            nova.eval('map(["secret.txt"], def(p) { return read(p) })')

    def test_exit_ends_the_run_not_the_embedders_process(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", process=True)
            with self.assertRaises(nl.ProgramExit) as stop:
                nova.eval("exit(3)")
            self.assertEqual(stop.exception.code, 3)
            self.assertEqual(nova.eval("1 + 1"), 2)            # the engine is usable again

    def test_trusted_exit_is_unchanged(self):
        with self.assertRaises(SystemExit):
            nl.Nova().eval("exit(3)")


class Paths(SandboxFolder):
    def test_the_grant_is_the_real_path_not_the_spelling(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", read=["data"])
            self.assertEqual(nova.eval('read("data/../data/./in.txt")'), "hello")
            for path in ("data/../secret.txt", self.root + "/secret.txt", "data2/x", "../" + os.path.basename(self.root)):
                with self.assertRaises(nl.NovaLangError, msg=(engine, path)) as caught:
                    nova.eval('read("{}")'.format(path))
                self.assertIn("outside the folders", str(caught.exception))

    def test_a_granted_folder_may_be_named_by_a_symlink_but_not_escaped_by_one(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symbolic links")
        try:
            os.symlink("../secret.txt", os.path.join(self.root, "data", "out.txt"))
            os.symlink("data", os.path.join(self.root, "alias"))
        except (OSError, NotImplementedError):
            self.skipTest("this machine cannot make a symbolic link")
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", read=["alias"])
            self.assertEqual(nova.eval('read("alias/in.txt")'), "hello")
            self.assertEqual(nova.eval('read("data/in.txt")'), "hello")      # same real folder
            with self.assertRaises(nl.NovaLangError):
                nova.eval('read("alias/out.txt")')

    def test_a_missing_path_is_judged_by_its_parent(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", read=["data"], write=["data"])
            with self.assertRaises(nl.NovaLangError):
                nova.eval('write("../made.txt", "x")')
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.root), "made.txt")))
            nova.eval('write("data/made.txt", "x")')
            self.assertTrue(os.path.exists(os.path.join(self.root, "data", "made.txt")))

    def test_a_path_with_a_nul_is_denied_not_a_crash(self):
        nova = nl.Nova(profile="restricted", read=["data"])
        with self.assertRaises(nl.NovaLangError):
            nova.eval('read("data/\\u0000")')

    def test_import_follows_the_grant(self):
        os.makedirs(os.path.join(self.root, "lib"))
        with open(os.path.join(self.root, "lib", "m.nova"), "w") as handle:
            handle.write("export let x = 1")
        with open(os.path.join(self.root, "outside.nova"), "w") as handle:
            handle.write("export let y = 2")
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", import_from=["lib"])
            nova.exec('import "lib/m.nova" as m')
            self.assertEqual(nova.eval("m.x"), 1)
            with self.assertRaises(nl.NovaLangError) as caught:
                nl.Nova(engine, profile="restricted", import_from=["lib"]).exec('import "outside.nova" as o')
            self.assertIn("outside the folders", str(caught.exception))


class Python(SandboxFolder):
    def test_the_grant_replaces_the_default_list(self):
        for engine in ENGINES:
            nova = nl.Nova(engine, profile="restricted", python=["math"])
            nova.exec('python.import("math")')
            self.assertEqual(nova.eval('python.call("math.sqrt", 16)'), 4)
            for module in ("re", "random", "datetime", "os"):
                with self.assertRaises(nl.NovaLangError, msg=module):
                    nova.exec('python.import("{}")'.format(module))

    def test_without_a_grant_the_bridge_refuses(self):
        with self.assertRaises(nl.NovaLangError) as caught:
            nl.Nova(profile="restricted").exec('python.import("math")')
        self.assertIn("disabled", str(caught.exception))


class CommandLine(SandboxFolder):
    def run_cli(self, *argv, source='print(read("data/in.txt"))'):
        with open(os.path.join(self.root, "prog.nova"), "w") as handle:
            handle.write(source)
        return subprocess.run([sys.executable, str(ROOT / "novalang.py")] + list(argv) + ["prog.nova"],
                              cwd=self.root, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)

    def test_restricted_runs_with_a_grant_and_stops_without_one(self):
        ok = self.run_cli("--profile", "restricted", "--allow-read", "data")
        self.assertEqual((ok.returncode, ok.stdout.strip()), (0, "hello"))
        denied = self.run_cli("--profile", "restricted")
        self.assertEqual(denied.returncode, 1)
        self.assertIn("undefined name 'read'", denied.stderr)

    def test_trusted_is_still_the_default(self):
        done = self.run_cli()
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "hello"))

    def test_exit_status_comes_through(self):
        done = self.run_cli("--profile", "restricted", "--allow-process", source="exit(5)")
        self.assertEqual(done.returncode, 5)

    def test_mistakes_in_the_flags_are_refused_before_anything_runs(self):
        for argv in (["--allow-read", "data"],                      # a grant with no profile: trusted takes none
                     ["--profile", "restricted", "--allow-python"],  # the whole default list is not a grant
                     ["--profile", "restricted", "--limit", "steps=lots"],
                     ["--profile", "restricted", "--limit", "stepz=5"],
                     ["--profile", "paranoid"]):
            done = self.run_cli(*argv)
            self.assertEqual(done.returncode, 2, msg=argv)
            self.assertEqual(done.stdout, "", msg=argv)


if __name__ == "__main__":
    unittest.main()
