"""Packages, part 1 (M13 slice 5, docs/spec/18-packages.md): the manifest of version 2, the static capability
check of decision D9 at install and at import on every engine, the project's policy, escalation protection and the
version-2 lockfile.

Every case builds a small project and registry in a temporary folder and runs the real `nova-pkg.py` and the real
interpreter on it.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import novalang as nl  # noqa: E402

RESTRICTED = unittest.skipIf(nl.SANDBOX_UNSUPPORTED, "the restricted profile needs Python 3.8 or later on Windows")
PKG = os.path.join(ROOT, "tools", "nova-pkg.py")
NOVA = os.path.join(ROOT, "novalang.py")
ENGINES = (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"]))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text if isinstance(text, str) else json.dumps(text, indent=2) + "\n")


def run(command, argv, cwd):
    done = subprocess.run([sys.executable, command] + argv, cwd=cwd, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL, env=dict(os.environ, NOVALANG_CACHE="off", NOVA_REGISTRY=""))
    return done.returncode, done.stdout, done.stderr


class Project(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nova-caps-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.project = os.path.join(self.root, "app")
        self.registry = os.path.join(self.root, "registry")
        os.makedirs(self.project)

    def publish(self, name, version, source, capabilities=(), extra=None, files=None):
        manifest = {"name": name, "version": version, "capabilities": list(capabilities)}
        manifest.update(extra or {})
        folder = os.path.join(self.registry, name, version)
        write(os.path.join(folder, "nova.json"), manifest)
        write(os.path.join(folder, "main.nova"), source)
        for relative, text in (files or {}).items():
            write(os.path.join(folder, relative), text)

    def manifest(self, dependencies, **more):
        manifest = {"name": "app", "version": "1.0.0", "registry": "../registry", "dependencies": dependencies}
        manifest.update(more)
        write(os.path.join(self.project, "nova.json"), manifest)

    def pkg(self, *argv):
        return run(PKG, ["--project", self.project] + list(argv), self.project)

    def installed(self, *argv):
        code, out, err = self.pkg("install", *argv)
        self.assertEqual(code, 0, out + err)
        return out

    def lock(self):
        with open(os.path.join(self.project, "nova.lock"), encoding="utf-8") as handle:
            return json.load(handle)


READER = 'export def load(path) { return read(path) }\n'
CLOCK = 'export def stamp() { return time() }\n'
PURE = 'export def twice(x) { return x * 2 }\n'


class Manifest(Project):
    def refuses(self, manifest, needle):
        write(os.path.join(self.project, "nova.json"), manifest)
        code, out, err = self.pkg("install")
        self.assertEqual(code, 1, out + err)
        self.assertIn(needle, err)

    def test_a_complete_manifest_is_accepted(self):
        self.manifest({}, description="d", license="MIT", authors=["A <a@example.org>"], repository="https://example.org/x",
                      nova="^2.0.0", main="main.nova", files=["main.nova", "src/**/*.nova", "README.md", "LICENSE"],
                      capabilities=["files.read", "clock"], policy={"capabilities": ["files.read", "clock"]})
        self.manifest({}, **{"x-note": 1, "nova": "*"})
        self.installed()

    def test_what_is_refused_says_what_to_do(self):
        base = {"name": "app", "version": "1.0.0"}
        table = [
            (dict(base, scripts={"post": "rm -rf /"}), 'unknown key "scripts"'),
            (dict(base, hooks={}), 'unknown key "hooks"'),
            (dict(base, capabilities=["files.read", "files.read"]), "lists a capability twice"),
            (dict(base, capabilities=["files.reed"]), '"files.reed", which is not a capability'),
            (dict(base, capabilities="files.read"), '"capabilities" must be a list'),
            (dict(base, capabilities=[1]), '"capabilities" must be a list'),
            (dict(base, policy={"capabilities": ["nope"]}), '"policy.capabilities" lists "nope"'),
            (dict(base, policy={"other": []}), '"policy" has one key'),
            (dict(base, nova=">=2.0.0 <3.0.0"), "is not a version"),
            (dict(base, nova=2), '"nova" must be a version range'),
            (dict(base, main="../main.nova"), 'not a path inside the package'),
            (dict(base, main="/etc/main.nova"), 'not a path inside the package'),
            (dict(base, main="main.txt"), 'must name a .nova file'),
            (dict(base, files=["../x.nova"]), 'not a path inside the package'),
            (dict(base, files=["a\\b.nova"]), 'not a path inside the package'),
            (dict(base, files=["tool.py"]), "a package holds only .nova, .json and .md files"),
            (dict(base, files=["run.sh"]), "a package holds only"),
            (dict(base, files="main.nova"), '"files" must be a list'),
            (dict(base, description=1), '"description" must be text'),
            (dict(base, authors="me"), '"authors" must be a list'),
            (dict(base, name="std/text"), '"std" is a reserved owner'),
            (dict(base, name="nova/x"), '"nova" is a reserved owner'),
            (dict(base, name="Acme"), '"name" must be a lowercase package name'),
            (dict(base, name="a/b/c"), '"name" must be a lowercase package name'),
            (dict(base, dependencies={"std/text": "*"}), '"std" is a reserved owner'),
            (dict(base, dependencies={"Bad": "*"}), "is not a valid package name"),
            (dict(base, version="1.0"), "is not a version"),
        ]
        for manifest, needle in table:
            with self.subTest(needle=needle, keys=sorted(manifest)):
                self.refuses(manifest, needle)

    def test_a_scoped_project_name_is_valid_for_the_project(self):
        write(os.path.join(self.project, "nova.json"), {"name": "acme/app", "version": "1.0.0"})
        self.installed()

    def test_a_scoped_dependency_needs_a_registry(self):
        write(os.path.join(self.project, "nova.json"), {"name": "app", "version": "1.0.0", "dependencies": {"acme/lib": "*"}})
        code, out, err = self.pkg("install")
        self.assertEqual(code, 1)
        self.assertIn("needs a package from a registry, but none is set", err)

    def test_the_nova_range_is_held_against_the_running_version(self):
        self.publish("lib", "1.0.0", PURE, extra={"nova": "^9.0.0"})
        self.manifest({"lib": "*"})
        code, out, err = self.pkg("install")
        self.assertEqual(code, 1)
        self.assertIn("works with NovaLang ^9.0.0", err)
        self.publish("lib", "1.0.0", PURE, extra={"nova": "*"})
        self.installed()

    def test_a_dependencys_registry_and_policy_are_ignored(self):
        self.publish("lib", "1.0.0", PURE, extra={"registry": "../elsewhere", "policy": {"capabilities": []}})
        self.manifest({"lib": "*"})
        self.installed()                   # lib's own "registry" did not redirect anything

    def test_init_writes_a_version_2_manifest(self):
        code, out, err = run(PKG, ["init", "math-utils"], self.project)
        self.assertEqual(code, 0, err)
        with open(os.path.join(self.project, "nova.json"), encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual((written["name"], written["version"], written["capabilities"], written["dependencies"], written["main"]),
                         ("math-utils", "0.1.0", [], {}, "main.nova"))
        self.assertTrue(written["nova"].startswith("^2."))
        self.installed()                   # what init wrote is a manifest install accepts
        code, out, err = run(PKG, ["init"], self.project)
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        code, out, err = run(PKG, ["init", "Bad Name"], os.path.join(self.root))
        self.assertEqual(code, 1)
        self.assertIn("is not a package name", err)


class Install(Project):
    def test_a_package_that_uses_an_undeclared_gated_name_is_refused_at_install(self):
        for source, name, capability in ((READER, "read", "files.read"), (CLOCK, "time", "clock"),
                                         ('export def go() { write("x", "y") }\n', "write", "files.write"),
                                         ('export def go() { return regex("a", "a") }\n', "regex", "regex"),
                                         ('export def go() { return env("HOME") }\n', "env", "env"),
                                         ('export def go(path) { return f"{read(path)}" }\n', "read", "files.read"),
                                         ('export def go() { return python.import("math") }\n', "python", "python")):
            with self.subTest(name=name):
                shutil.rmtree(self.registry, ignore_errors=True)
                self.publish("lib", "1.0.0", source)
                self.manifest({"lib": "*"})
                code, out, err = self.pkg("install")
                self.assertEqual(code, 1, out + err)
                self.assertIn("lib/main.nova uses {}, which needs {}, which its nova.json does not declare".format(name, capability), err)
                self.assertFalse(os.path.exists(os.path.join(self.project, ".nova_modules")))

    def test_a_file_in_a_subfolder_is_scanned_too(self):
        self.publish("lib", "1.0.0", PURE, files={"src/deep/store.nova": 'export def go() { return exit(1) }\n'})
        self.manifest({"lib": "*"})
        code, out, err = self.pkg("install")
        self.assertEqual(code, 1)
        self.assertIn("lib/src/deep/store.nova uses exit, which needs process", err)

    def test_a_declared_capability_passes_and_is_recorded_in_the_lock(self):
        self.publish("lib", "1.0.0", READER, capabilities=["files.read"])
        self.publish("pure", "1.0.0", PURE)
        self.manifest({"lib": "*", "pure": "*"})
        self.installed()
        lock = self.lock()
        self.assertEqual(lock["lockfile_version"], 2)
        self.assertEqual(lock["packages"]["lib"]["capabilities"], ["files.read"])
        self.assertEqual(lock["packages"]["pure"]["capabilities"], [])
        self.assertNotIn("time", json.dumps(lock))           # a lockfile has no timestamps

    def test_names_that_are_not_references_are_not_uses(self):
        source = ('let table = {read: 1, time: 2}\nexport def go(x) { return x.read + table.time + table["env"] }\n'
                  'export def named(read_count, time_left) { return read_count + time_left }\n')
        self.publish("lib", "1.0.0", source)
        self.manifest({"lib": "*"})
        self.installed()

    def test_declaring_more_than_is_used_is_a_warning(self):
        self.publish("lib", "1.0.0", PURE, capabilities=["clock", "env"])
        self.manifest({"lib": "*"})
        out = self.installed()
        self.assertIn("lib declares clock, which none of its files uses", out)
        self.assertIn("lib declares env", out)

    def test_the_policy_is_the_most_a_dependency_may_need(self):
        self.publish("lib", "1.0.0", READER + CLOCK, capabilities=["clock", "files.read"])
        self.manifest({"lib": "*"}, policy={"capabilities": ["files.read"]})
        code, out, err = self.pkg("install")
        self.assertEqual(code, 1, out)
        self.assertIn("package lib 1.0.0 needs clock", err)
        self.assertIn("allows: files.read", err)
        self.manifest({"lib": "*"}, policy={"capabilities": ["files.read", "clock"]})
        self.installed()
        self.manifest({"lib": "*"}, policy={"capabilities": []})
        code, out, err = self.pkg("install")
        self.assertEqual(code, 1)
        self.assertIn("allows: nothing", err)

    def test_a_new_version_that_declares_more_is_not_installed_without_consent(self):
        self.publish("lib", "1.0.0", PURE)
        self.publish("other", "1.0.0", PURE)
        self.manifest({"lib": "^1.0.0"})
        self.installed()
        self.publish("lib", "1.1.0", READER, capabilities=["files.read"])
        # adding a dependency makes install resolve again, and it would move lib to 1.1.0
        self.manifest({"lib": "^1.0.0", "other": "*"})
        code, out, err = self.pkg("install")
        self.assertEqual(code, 1, out)
        self.assertIn("package lib 1.1.0 declares files.read, which the locked lib 1.0.0 did not", err)
        self.assertIn("install --accept-capabilities files.read", err)
        self.assertEqual(self.lock()["packages"]["lib"]["version"], "1.0.0")            # nothing changed
        code, out, err = self.pkg("install", "--accept-capabilities", "clock")        # the wrong capability
        self.assertEqual(code, 1)
        self.installed("--accept-capabilities", "files.read")
        self.assertEqual(self.lock()["packages"]["lib"]["version"], "1.1.0")
        self.assertEqual(self.lock()["packages"]["lib"]["capabilities"], ["files.read"])

    def test_accepting_a_name_that_is_not_a_capability_is_a_usage_error(self):
        self.manifest({})
        code, out, err = self.pkg("install", "--accept-capabilities", "everything")
        self.assertEqual(code, 1)
        self.assertIn('"everything", which is not a capability', err)

    def test_a_version_1_lockfile_is_read_and_written_as_version_2(self):
        self.publish("lib", "1.0.0", READER, capabilities=["files.read"])
        self.manifest({"lib": "*"})
        self.installed()
        lock = self.lock()
        lock["lockfile_version"] = 1
        for entry in lock["packages"].values():
            del entry["capabilities"]
        write(os.path.join(self.project, "nova.lock"), lock)
        code, out, err = self.pkg("install", "--frozen")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.lock()["lockfile_version"], 1)                 # frozen writes nothing
        self.installed()
        self.assertEqual(self.lock()["lockfile_version"], 2)
        self.assertEqual(self.lock()["packages"]["lib"]["capabilities"], ["files.read"])

    def test_frozen_install_refuses_a_changed_capability(self):
        self.publish("lib", "1.0.0", READER, capabilities=["files.read"])
        self.manifest({"lib": "*"})
        self.installed()
        lock = self.lock()
        lock["packages"]["lib"]["capabilities"] = []
        write(os.path.join(self.project, "nova.lock"), lock)
        code, out, err = self.pkg("install", "--frozen")
        self.assertEqual(code, 1)
        self.assertIn("declares files.read, which the locked lib 1.0.0 did not", err)
        lock["packages"]["lib"]["capabilities"] = ["files.read", "clock"]               # and the other way round
        write(os.path.join(self.project, "nova.lock"), lock)
        code, out, err = self.pkg("install", "--frozen")
        self.assertEqual(code, 1)
        self.assertIn("declares ['files.read'] now", err)

    def test_the_capabilities_command_shows_declared_and_used(self):
        self.publish("lib", "1.0.0", READER + CLOCK, capabilities=["files.read", "clock"])
        self.publish("pure", "1.0.0", PURE)
        self.manifest({"lib": "*", "pure": "*"}, policy={"capabilities": ["files.read", "clock"]})
        self.installed()
        code, out, err = self.pkg("capabilities")
        self.assertEqual(code, 0, err)
        self.assertIn("lib 1.0.0\n  declares: clock, files.read\n  uses:     clock (time in main.nova)\n  uses:     files.read (read in main.nova)", out)
        self.assertIn("pure 1.0.0\n  declares: nothing\n  uses:     nothing", out)
        self.assertIn("the packages need: clock, files.read\npolicy: clock, files.read", out)
        code, out, err = self.pkg("capabilities", "pure")
        self.assertEqual(code, 0)
        self.assertNotIn("lib 1.0.0", out)
        code, out, err = self.pkg("capabilities", "missing")
        self.assertEqual(code, 1)
        self.assertIn('"missing" is not an installed package', err)

    def test_the_capabilities_command_flags_a_file_edited_after_install(self):
        self.publish("lib", "1.0.0", PURE)
        self.manifest({"lib": "*"})
        self.installed()
        write(os.path.join(self.project, ".nova_modules", "lib", "main.nova"), CLOCK)
        code, out, err = self.pkg("capabilities")
        self.assertEqual(code, 0)
        self.assertIn("NOT DECLARED: clock", out)


class Import(Project):
    """The same check when the file is imported, on every engine: it holds even when install was not the one that
    ran (a package edited after install, a lockfile and folder made by hand)."""

    def program(self, text):
        write(os.path.join(self.project, "a.nova"), text)

    def imports(self, flags, extra=()):
        return run(NOVA, list(extra) + list(flags) + ["a.nova"], self.project)

    def test_a_compliant_package_runs_on_every_engine(self):
        self.publish("lib", "1.0.0", READER, capabilities=["files.read"])
        self.manifest({"lib": "*"})
        self.installed()
        self.program('import "lib"\nprint(len(lib.load("nova.json")) > 0)')
        for name, flags in ENGINES:
            code, out, err = self.imports(flags)
            self.assertEqual((code, out), (0, "true\n"), (name, err))

    def test_an_edit_after_install_is_caught_at_import(self):
        self.publish("lib", "1.0.0", PURE)
        self.manifest({"lib": "*"})
        self.installed()
        write(os.path.join(self.project, ".nova_modules", "lib", "main.nova"), READER)
        self.program('import "lib"\nprint(lib.load("nova.json"))')
        expected = 'ImportError: package "lib": main.nova uses read, which needs the files.read capability, and its nova.json does not declare it'
        for name, flags in ENGINES:
            code, out, err = self.imports(flags)
            self.assertEqual(code, 1, name)
            self.assertIn(expected, out + err, name)
            self.assertEqual(out, "", name)

    def test_a_nested_file_is_checked_when_it_is_imported(self):
        self.publish("lib", "1.0.0", 'import "src/inner.nova" as inner\nexport def go() { return inner.go() }\n',
                     files={"src/inner.nova": 'export def go() { return time() }\n'})
        # install refuses it, so the project is made by hand: the import is the second line of defence
        self.manifest({"lib": "*"})
        folder = os.path.join(self.project, ".nova_modules", "lib")
        shutil.copytree(os.path.join(self.registry, "lib", "1.0.0"), folder)
        lock = {"lockfile_version": 2, "requires": {"lib": "*"}, "packages": {"lib": {
            "version": "1.0.0", "source": {"registry": "../registry"}, "integrity": "x", "capabilities": [], "dependencies": {}}}}
        text = json.dumps(lock, indent=2, sort_keys=True) + "\n"
        write(os.path.join(self.project, "nova.lock"), text)
        write(os.path.join(self.project, ".nova_modules", ".installed.lock"), text)
        self.program('import "lib"\nprint(lib.go())')
        for name, flags in ENGINES:
            code, out, err = self.imports(flags)
            self.assertEqual(code, 1, name)
            self.assertIn('ImportError: package "lib": src/inner.nova uses time, which needs the clock capability', out + err, name)

    @RESTRICTED
    def test_declared_capabilities_must_be_granted_by_the_run(self):
        self.publish("lib", "1.0.0", READER, capabilities=["files.read"])
        self.manifest({"lib": "*"})
        self.installed()
        self.program('import "lib"\nprint(len(lib.load("nova.json")) > 0)')
        for name, flags in ENGINES:
            if name == "bootstrap" and sys.platform == "win32":
                continue
            denied = self.imports(flags, ["--profile", "restricted", "--allow-import", "."])
            self.assertEqual(denied[0], 1, name)
            self.assertIn("ImportError: package \"lib\" needs the 'files.read' capability, which this run did not grant",
                          denied[1] + denied[2], name)
            granted = self.imports(flags, ["--profile", "restricted", "--allow-import", ".", "--allow-read", "."])
            self.assertEqual((granted[0], granted[1]), (0, "true\n"), (name, granted[2]))

    @RESTRICTED
    def test_a_package_that_declares_nothing_needs_no_grant(self):
        self.publish("lib", "1.0.0", PURE)
        self.manifest({"lib": "*"})
        self.installed()
        self.program('import "lib"\nprint(lib.twice(21))')
        for name, flags in ENGINES:
            code, out, err = self.imports(flags, ["--profile", "restricted", "--allow-import", "."])
            self.assertEqual((code, out), (0, "42\n"), (name, err))

    def test_a_declared_capability_that_is_not_one_is_refused_at_import(self):
        self.publish("lib", "1.0.0", PURE)
        self.manifest({"lib": "*"})
        self.installed()
        manifest_path = os.path.join(self.project, ".nova_modules", "lib", "nova.json")
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["capabilities"] = ["everything"]
        write(manifest_path, manifest)
        self.program('import "lib"\nprint(lib.twice(1))')
        for name, flags in ENGINES:
            code, out, err = self.imports(flags)
            self.assertEqual(code, 1, name)
            self.assertIn('package "lib": nova.json declares "everything", which is not a capability', out + err, name)

    def test_net_is_never_granted_yet(self):
        self.publish("lib", "1.0.0", PURE, capabilities=["net"])
        self.manifest({"lib": "*"})
        self.installed()
        self.program('import "lib"\nprint(lib.twice(1))')
        for name, flags in ENGINES:
            code, out, err = self.imports(flags)
            self.assertEqual(code, 1, name)
            self.assertIn("package \"lib\" needs the 'net' capability, which this run did not grant", out + err, name)


if __name__ == "__main__":
    unittest.main()
