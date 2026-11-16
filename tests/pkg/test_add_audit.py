"""nova-pkg add and audit (M14 L6 item 2, docs/spec/18-packages.md [pkg.add] and [pkg.audit]).

Built on the registry tests' helpers: a real signed directory registry, made with the real `keygen`, `publish`, `yank`
and `revoke` commands, and the real `nova-pkg.py`.
"""

import hashlib
import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_registry import ENGINES, NOVA, Registry, run, write  # noqa: E402


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as handle:
        return handle.read()


class Add(Registry):
    def manifest_text(self):
        return read(os.path.join(self.project, "nova.json"))

    def dependencies(self):
        return json.loads(self.manifest_text()).get("dependencies")

    def add(self, target, expect=0):
        code, out, err = self.nova_pkg(["add", target])
        self.assertEqual(code, expect, out + err)
        return out, err

    def test_without_a_range_the_newest_version_is_taken_as_a_caret_range_and_installed(self):
        self.published("acme/ledger", "1.0.0")
        self.published("acme/ledger", "1.2.0")
        self.app({})
        out, _ = self.add("acme/ledger")
        self.assertEqual(self.dependencies(), {"acme/ledger": "^1.2.0"})
        self.assertIn("added acme/ledger ^1.2.0 to nova.json", out)
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.2.0")
        self.assertTrue(os.path.isfile(os.path.join(self.project, ".nova_modules", "acme", "ledger", "main.nova")))

    def test_a_yanked_version_is_not_the_newest(self):
        self.published("acme/ledger", "1.0.0")
        folder, _ = self.published("acme/ledger", "1.2.0")
        code, out, err = self.nova_pkg(["yank", "1.2.0", "--registry", self.registry, "--key", self.keyfile], folder)
        self.assertEqual(code, 0, out + err)
        self.app({})
        self.add("acme/ledger")
        self.assertEqual(self.dependencies(), {"acme/ledger": "^1.0.0"})
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.0.0")

    def test_an_explicit_range_is_written_as_given(self):
        self.published("acme/ledger", "1.0.0")
        self.published("acme/ledger", "1.0.4")
        self.published("acme/ledger", "1.1.0")
        self.app({})
        self.add("acme/ledger@~1.0.0")
        self.assertEqual(self.dependencies(), {"acme/ledger": "~1.0.0"})
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.0.4")

    def test_other_dependencies_and_keys_stay_and_the_new_one_comes_last(self):
        self.published("acme/ledger", "1.0.0")
        self.published("acme/other", "2.0.0")
        self.app({"acme/ledger": "^1.0.0"}, description="kept")
        self.add("acme/other")
        document = json.loads(self.manifest_text())
        self.assertEqual(list(document["dependencies"].items()), [("acme/ledger", "^1.0.0"), ("acme/other", "^2.0.0")])
        self.assertEqual(document["description"], "kept")
        self.assertEqual(self.manifest_text()[-1], "\n")

    def test_a_project_without_dependencies_gets_the_key(self):
        self.published("acme/ledger", "0.3.1")
        write(os.path.join(self.project, "nova.json"), {"name": "app", "version": "1.0.0", "registry": "../registry",
                                                       "registryKeys": [self.public]})
        self.add("acme/ledger")
        self.assertEqual(self.dependencies(), {"acme/ledger": "^0.3.1"})      # for 0.x a caret keeps the minor

    def test_the_package_can_be_imported_afterwards_on_every_engine(self):
        self.published("acme/ledger", "1.0.0")
        self.app({})
        self.add("acme/ledger")
        write(os.path.join(self.project, "a.nova"), 'import "acme/ledger"\nprint(ledger.hello())')
        for name, flags in ENGINES:
            code, out, err = run(NOVA, flags + ["a.nova"], self.project)
            self.assertEqual((code, out), (0, "hello from acme/ledger\n"), (name, err))

    def test_a_dependency_that_is_already_there_is_refused_and_nothing_changes(self):
        self.published("acme/ledger", "1.0.0")
        self.app({"acme/ledger": "^1.0.0"})
        before = self.manifest_text()
        out, err = self.add("acme/ledger@^1.0.0", expect=1)
        self.assertIn('"acme/ledger" is already a dependency ("^1.0.0")', err)
        self.assertEqual(self.manifest_text(), before)
        self.assertFalse(os.path.exists(os.path.join(self.project, "nova.lock")))

    def test_a_failed_install_puts_nova_json_back_byte_for_byte(self):
        self.published("acme/reader", "1.0.0", source="export def load(p) { return read(p) }\n", capabilities=["files.read"])
        self.app({}, policy={"capabilities": []})
        before = self.manifest_text()
        out, err = self.add("acme/reader", expect=1)
        self.assertIn("which \"policy\" in nova.json does not allow", err)
        self.assertIn("nova.json was put back as it was: nothing was added", err)
        self.assertEqual(self.manifest_text(), before)
        self.assertFalse(os.path.exists(os.path.join(self.project, "nova.lock")))

    def test_a_package_the_registry_does_not_have_is_refused_and_nothing_changes(self):
        self.published("acme/ledger", "1.0.0")
        self.app({})
        before = self.manifest_text()
        out, err = self.add("acme/missing", expect=1)
        self.assertIn("is not in the registry", err)
        self.assertEqual(self.manifest_text(), before)

    def test_a_range_nothing_satisfies_is_refused_and_nothing_changes(self):
        self.published("acme/ledger", "1.0.0")
        self.app({})
        before = self.manifest_text()
        out, err = self.add("acme/ledger@^2.0.0", expect=1)
        self.assertIn("conflicting requirements", err)
        self.assertEqual(self.manifest_text(), before)

    def test_without_a_registry_the_message_says_what_to_set(self):
        write(os.path.join(self.project, "nova.json"), {"name": "app", "version": "1.0.0"})
        before = self.manifest_text()
        out, err = self.add("acme/ledger", expect=1)
        self.assertIn('none is set - add "registry" to nova.json or set $NOVA_REGISTRY', err)
        self.assertEqual(self.manifest_text(), before)

    def test_what_is_not_a_target_is_refused_before_anything_is_read(self):
        self.app({})
        before = self.manifest_text()
        for bad, needle in (("Acme/Ledger", "is not a package name"), ("acme/ledger@", "no range after it"),
                            ("std/thing", "reserved owner"), ("acme/ledger@^1.x", "is not a version"),
                            ("a b", "is not a package name"), ("app", "the project itself")):
            out, err = self.add(bad, expect=1)
            self.assertIn(needle, err, bad)
            self.assertEqual(self.manifest_text(), before, bad)

    def test_it_needs_exactly_one_target(self):
        self.app({})
        for argv in (["add"], ["add", "a/b", "c/d"], ["add", "a/b", "--frozen"]):
            code, out, err = self.nova_pkg(argv)
            self.assertEqual(code, 2, argv)
            self.assertIn("usage:", err)

    def test_an_unsigned_directory_registry_works_too(self):
        for version in ("1.0.0", "1.3.0"):
            folder = os.path.join(self.root, "plain", "math-utils", version)
            write(os.path.join(folder, "nova.json"), {"name": "math-utils", "version": version})
            write(os.path.join(folder, "main.nova"), "export def one() { return 1 }\n")
        write(os.path.join(self.project, "nova.json"), {"name": "app", "version": "1.0.0", "registry": "../plain"})
        self.add("math-utils")
        self.assertEqual(self.dependencies(), {"math-utils": "^1.3.0"})


class Audit(Registry):
    def audit(self, expect=0):
        code, out, err = self.nova_pkg(["audit"])
        self.assertEqual(code, expect, out + err)
        return out + err

    def installed(self, *packages, **more):
        for name, version in packages:
            self.published(name, version)
        self.app(dict((name, "^" + version) for name, version in packages), **more)
        self.install()

    def test_a_clean_project_lists_each_package_and_has_no_problems(self):
        self.installed(("acme/ledger", "1.0.0"), ("acme/other", "2.1.0"))
        text = self.audit()
        self.assertIn("2 package(s) in nova.lock", text)
        self.assertIn("acme/ledger 1.0.0   registry ", text)
        self.assertIn("acme/other 2.1.0   registry ", text)
        self.assertEqual(text.count("declares: nothing"), 2)
        self.assertEqual(text.count("registry: not yanked, not revoked"), 2)
        self.assertTrue(text.rstrip().endswith("audit: no problems found"))
        self.assertLess(text.index("acme/ledger"), text.index("acme/other"))        # sorted by name

    def test_a_declared_capability_is_listed(self):
        self.published("acme/reader", "1.0.0", source="export def load(p) { return read(p) }\n", capabilities=["files.read"])
        self.app({"acme/reader": "*"})
        self.install()
        self.assertIn("declares: files.read", self.audit())

    def test_a_yanked_version_is_reported_and_is_not_a_problem(self):
        folder, _ = self.published("acme/ledger", "1.0.0")
        self.app({"acme/ledger": "^1.0.0"})
        self.install()
        code, out, err = self.nova_pkg(["yank", "1.0.0", "--registry", self.registry, "--key", self.keyfile], folder)
        self.assertEqual(code, 0, out + err)
        text = self.audit(expect=0)
        self.assertIn("YANKED: ranges no longer choose it; the lock still installs it", text)
        self.assertIn("no problems found", text)

    def test_a_revoked_archive_is_a_problem_with_its_reason(self):
        folder, _ = self.published("acme/ledger", "1.0.0")
        self.app({"acme/ledger": "^1.0.0"})
        self.install()
        digest = self.lock()["packages"]["acme/ledger"]["archive"][len("sha256-"):]
        code, out, err = self.nova_pkg(["revoke", "--registry", self.registry, "--key", self.keyfile, "--archive", digest,
                                        "--reason", "contains a backdoor"], folder)
        self.assertEqual(code, 0, out + err)
        text = self.audit(expect=1)
        self.assertIn("REVOKED: contains a backdoor", text)
        self.assertTrue(text.rstrip().endswith("audit: 1 problem(s)"))

    def test_a_package_changed_after_install_is_a_problem(self):
        self.installed(("acme/ledger", "1.0.0"))
        write(os.path.join(self.project, ".nova_modules", "acme", "ledger", "main.nova"), "export let changed = 1\n")
        text = self.audit(expect=1)
        self.assertIn("CHANGED after it was installed", text)

    def test_a_capability_used_and_not_declared_is_a_problem(self):
        self.installed(("acme/ledger", "1.0.0"))
        write(os.path.join(self.project, ".nova_modules", "acme", "ledger", "main.nova"), "export def peek(p) { return read(p) }\n")
        text = self.audit(expect=1)
        self.assertIn("USES files.read and does not declare it", text)

    def test_capabilities_changed_in_the_installed_manifest_since_the_lock_are_named(self):
        self.installed(("acme/ledger", "1.0.0"))
        path = os.path.join(self.project, ".nova_modules", "acme", "ledger", "nova.json")
        manifest = json.loads(read(path))
        manifest["capabilities"] = ["clock"]
        write(path, manifest)
        text = self.audit(expect=1)
        self.assertIn("GAINED capabilities since the lock: clock (the lock recorded: nothing)", text)

    def edit_lock(self, name, **changes):
        path = os.path.join(self.project, "nova.lock")
        lock = json.loads(read(path))
        lock["packages"][name].update(changes)
        write(path, lock)

    def test_a_gained_capability_is_a_problem_even_when_the_files_match_the_lock(self):
        self.published("acme/reader", "1.0.0", source="export def load(p) { return read(p) }\n", capabilities=["files.read"])
        self.app({"acme/reader": "*"})
        self.install()
        self.edit_lock("acme/reader", capabilities=[])         # the lock now says it declared nothing; the files are untouched
        text = self.audit(expect=1)
        self.assertNotIn("CHANGED after it was installed", text)
        self.assertIn("GAINED capabilities since the lock: files.read (the lock recorded: nothing)", text)
        self.assertTrue(text.rstrip().endswith("audit: 1 problem(s)"))

    def test_a_capability_only_lost_since_the_lock_is_reported_and_is_not_a_problem(self):
        self.published("acme/reader", "1.0.0", source="export def load(p) { return read(p) }\n", capabilities=["files.read"])
        self.app({"acme/reader": "*"})
        self.install()
        self.edit_lock("acme/reader", capabilities=["files.read", "clock"])
        text = self.audit(expect=0)
        self.assertIn("capabilities lost since the lock: clock", text)
        self.assertNotIn("GAINED", text)
        self.assertTrue(text.rstrip().endswith("audit: no problems found"))

    def test_a_locked_version_missing_from_the_signed_index_is_a_problem(self):
        self.installed(("acme/ledger", "1.0.0"))
        self.edit_lock("acme/ledger", version="1.0.5")          # a version the registry never held
        text = self.audit(expect=1)
        self.assertIn("MISSING: 1.0.5 is not in the signed registry's index of this package", text)
        self.assertIn("could not be checked", text)
        self.assertTrue(text.rstrip().endswith("audit: 1 problem(s)"))

    def test_a_locked_package_the_signed_registry_has_no_index_for_is_a_problem(self):
        self.installed(("acme/ledger", "1.0.0"))
        path = os.path.join(self.project, "nova.lock")
        lock = json.loads(read(path))
        lock["packages"]["acme/ghost"] = lock["packages"].pop("acme/ledger")
        write(path, lock)
        text = self.audit(expect=1)
        self.assertIn("MISSING: 1.0.0 is not in the signed registry's index of this package", text)

    def test_a_newer_version_in_range_that_declares_more_is_reported_and_is_not_a_problem(self):
        self.installed(("acme/ledger", "1.0.0"))
        self.published("acme/ledger", "1.1.0", source="export def peek(p) { return read(p) }\n", capabilities=["files.read"])
        text = self.audit(expect=0)
        self.assertIn("newer: 1.1.0 (in your range ^1.0.0) declares files.read, which 1.0.0 does not; updating to it needs "
                      "install --accept-capabilities files.read", text)

    def test_a_newer_version_that_declares_nothing_new_is_not_mentioned(self):
        self.installed(("acme/ledger", "1.0.0"))
        self.published("acme/ledger", "1.1.0")
        self.assertNotIn("newer:", self.audit())

    def test_a_newer_version_outside_the_range_is_not_mentioned(self):
        self.installed(("acme/ledger", "1.0.0"))
        self.published("acme/ledger", "2.0.0", source="export def peek(p) { return read(p) }\n", capabilities=["files.read"])
        self.assertNotIn("newer:", self.audit())

    def test_a_registry_that_lost_its_registry_json_is_a_problem_and_says_so(self):
        self.installed(("acme/ledger", "1.0.0"))
        os.remove(self.registry_file("registry.json"))
        text = self.audit(expect=1)
        self.assertIn("has no registry.json, but nova.lock recorded archives it signed, so yanks and revocations were NOT checked", text)

    def test_a_signed_registry_whose_files_do_not_verify_is_a_problem_and_says_so(self):
        self.installed(("acme/ledger", "1.0.0"))
        path = self.registry_file("registry.json")
        document = json.loads(read(path))
        document["signed"]["serial"] += 1                      # the signature no longer matches what is signed
        write(path, document)
        text = self.audit(expect=1)
        self.assertIn("could not be read and verified, so yanks and revocations were NOT checked", text)

    def test_without_a_registry_set_the_listing_works_and_says_nothing_was_checked(self):
        self.installed(("acme/ledger", "1.0.0"))
        document = json.loads(read(os.path.join(self.project, "nova.json")))
        del document["registry"]
        write(os.path.join(self.project, "nova.json"), document)
        text = self.audit(expect=0)
        self.assertIn("no registry is set", text)
        self.assertIn("so yanks and revocations were not checked", text)

    def test_a_path_package_is_listed_without_registry_lines(self):
        write(os.path.join(self.root, "local-lib", "nova.json"), {"name": "local-lib", "version": "0.2.0"})
        write(os.path.join(self.root, "local-lib", "main.nova"), "export let x = 1\n")
        write(os.path.join(self.project, "nova.json"), {"name": "app", "version": "1.0.0",
                                                       "dependencies": {"local-lib": {"path": "../local-lib"}}})
        self.install()
        text = self.audit()
        self.assertIn("local-lib 0.2.0   path ../local-lib", text)
        self.assertNotIn("registry:", text)
        self.assertNotIn("UNVERIFIED", text)

    def test_a_git_package_is_marked_unverified(self):
        repo = os.path.join(self.root, "git-lib")
        write(os.path.join(repo, "nova.json"), {"name": "git-lib", "version": "0.3.0"})
        write(os.path.join(repo, "main.nova"), "export let x = 1\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@example.com")
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
            subprocess.run(["git"] + argv, cwd=repo, env=env, check=True, capture_output=True)
        write(os.path.join(self.project, "nova.json"), {"name": "app", "version": "1.0.0",
                                                       "dependencies": {"git-lib": {"git": "../git-lib", "ref": "HEAD"}}})
        self.install()
        text = self.audit(expect=0)
        self.assertIn("git-lib 0.3.0   git ../git-lib at ", text)
        self.assertIn("UNVERIFIED: a git source is pinned to a commit but signed by no one", text)

    def test_an_unsigned_directory_registry_says_it_has_no_yanks_to_check(self):
        for version in ("1.0.0",):
            folder = os.path.join(self.root, "plain", "math-utils", version)
            write(os.path.join(folder, "nova.json"), {"name": "math-utils", "version": version})
            write(os.path.join(folder, "main.nova"), "export def one() { return 1 }\n")
        write(os.path.join(self.project, "nova.json"), {"name": "app", "version": "1.0.0", "registry": "../plain",
                                                       "dependencies": {"math-utils": "^1.0.0"}})
        self.install()
        text = self.audit(expect=0)
        self.assertIn("is an unsigned registry: it has no yanks or revocations to check", text)

    def test_without_a_lock_there_is_nothing_to_audit(self):
        self.app({})
        code, out, err = self.nova_pkg(["audit"])
        self.assertEqual(code, 1)
        self.assertIn("there is no nova.lock - run install", err)

    def test_audit_takes_no_arguments_and_changes_nothing(self):
        self.installed(("acme/ledger", "1.0.0"))
        code, out, err = self.nova_pkg(["audit", "acme/ledger"])
        self.assertEqual(code, 2)
        before = {name: read(os.path.join(self.project, name), "rb") for name in ("nova.json", "nova.lock")}
        self.audit()
        for name, data in before.items():
            self.assertEqual(read(os.path.join(self.project, name), "rb"), data, name)


if __name__ == "__main__":
    unittest.main()
