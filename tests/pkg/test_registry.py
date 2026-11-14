"""The registry (M13 slice 6, docs/spec/18-packages.md [pkg.registry]): Ed25519, the archive format and its hardened reader,
the signed static index, publishing, yanking, revoking, and an install from a directory registry and from an HTTPS server,
end to end. Each row of the supply-chain table (plan 5.5) that says "test" has one here.

The tests build registries in temporary folders and run the real `nova-pkg.py` and the real interpreter. The HTTPS test
starts a local server with a test-only certificate (tests/pkg/fixtures) and certificate verification stays on.
"""

import hashlib
import http.server
import json
import os
import random
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import nova_registry as nr  # noqa: E402

PKG = os.path.join(ROOT, "tools", "nova-pkg.py")
NOVA = os.path.join(ROOT, "novalang.py")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ENGINES = (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"]))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text if isinstance(text, str) else json.dumps(text, indent=2) + "\n")


def run(command, argv, cwd, env=None):
    done = subprocess.run([sys.executable, command] + argv, cwd=cwd, capture_output=True, text=True, timeout=300,
                          stdin=subprocess.DEVNULL, env=dict(os.environ, NOVALANG_CACHE="off", NOVA_REGISTRY="", **(env or {})))
    return done.returncode, done.stdout, done.stderr


class Ed25519(unittest.TestCase):
    VECTORS = [   # RFC 8032 section 7.1: secret key, public key, message, signature
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ]

    def test_the_rfc_8032_vectors(self):
        for seed, public, message, signature in self.VECTORS:
            seed, message = bytes.fromhex(seed), bytes.fromhex(message)
            self.assertEqual(nr.ed25519_public_key(seed).hex(), public)
            self.assertEqual(nr.ed25519_sign(seed, message).hex(), signature)
            self.assertTrue(nr.ed25519_verify(bytes.fromhex(public), message, bytes.fromhex(signature)))

    def test_what_is_not_a_valid_signature_is_refused(self):
        seed, public, message, signature = self.VECTORS[1]
        public, message, signature = bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)
        self.assertFalse(nr.ed25519_verify(public, message + b"x", signature))
        self.assertFalse(nr.ed25519_verify(public, message, signature[:-1] + bytes([signature[-1] ^ 1])))
        self.assertFalse(nr.ed25519_verify(public, message, bytes([signature[0] ^ 1]) + signature[1:]))
        self.assertFalse(nr.ed25519_verify(nr.ed25519_public_key(b"\x01" * 32), message, signature))
        self.assertFalse(nr.ed25519_verify(public, message, signature[:63]))
        self.assertFalse(nr.ed25519_verify(public[:31], message, signature))
        self.assertFalse(nr.ed25519_verify(b"\xff" * 32, message, signature))            # not a point
        # malleability: s + L is the same point, and must be refused (s must be below L)
        s = int.from_bytes(signature[32:], "little") + nr._L
        self.assertFalse(nr.ed25519_verify(public, message, signature[:32] + s.to_bytes(32, "little")))

    def test_random_keys_agree_with_the_cryptography_package_when_it_is_installed(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.skipTest("the cryptography package is not installed")
        rng = random.Random(8032)
        for _ in range(8):
            seed = bytes(rng.randrange(256) for _ in range(32))
            message = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 200)))
            key = Ed25519PrivateKey.from_private_bytes(seed)
            public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self.assertEqual(nr.ed25519_public_key(seed), public)
            self.assertEqual(nr.ed25519_sign(seed, message), key.sign(message))
            self.assertTrue(nr.ed25519_verify(public, message, key.sign(message)))


def raw_entry(name, data=b"", kind=b"0", size=None, magic=b"ustar\0", checksum_ok=True):
    """One ustar entry written by hand, so that hostile ones can be made."""
    block = bytearray(512)
    encoded = name.encode("utf-8")
    block[0:len(encoded[:100])] = encoded[:100]
    block[100:108] = b"0000644\0"
    block[124:136] = ("%011o" % (len(data) if size is None else size)).encode("ascii") + b"\0"
    block[148:156] = b"        "
    block[156:157] = kind
    block[257:263] = magic
    block[263:265] = b"00"
    total = sum(block) if checksum_ok else 12345
    block[148:156] = ("%06o" % total).encode("ascii") + b"\0 "
    return bytes(block) + data + b"\0" * (-len(data) % 512)


END = b"\0" * 1024


class Archives(unittest.TestCase):
    def test_the_same_files_give_the_same_bytes_whatever_the_order(self):
        files = {"main.nova": b"export let x = 1\n", "nova.json": b"{}", "src/a.nova": b"a", "LICENSE": b"MIT", "README.md": b"hi"}
        first = nr.build_archive(files)
        self.assertEqual(first, nr.build_archive(dict(reversed(list(files.items())))))
        self.assertEqual(nr.read_archive(first), files)
        self.assertEqual(len(first) % 512, 0)
        self.assertEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(nr.build_archive(files)).hexdigest())
        # no time, no owner, no mode other than 0644 in any header
        position = 0
        while first[position:position + 512] != b"\0" * 512:
            header = first[position:position + 512]
            self.assertEqual((header[100:108], header[108:116], header[116:124], header[136:148]),
                             (b"0000644\0", b"0000000\0", b"0000000\0", b"00000000000\0"))
            size = int(header[124:135], 8)
            position += 512 + size + (-size % 512)

    def test_a_long_path_round_trips(self):
        name = "/".join(["folder%02d" % i for i in range(12)]) + "/deep.nova"
        self.assertGreater(len(name), 100)
        self.assertEqual(nr.read_archive(nr.build_archive({name: b"x", "nova.json": b"{}"}))[name], b"x")

    def hostile(self):
        good = raw_entry("nova.json", b"{}")
        return {
            "an absolute path": raw_entry("/etc/passwd.json", b"x"),
            "a parent folder": raw_entry("../outside.nova", b"x"),
            "a parent folder in the middle": raw_entry("a/../../b.nova", b"x"),
            "a backslash": raw_entry("a\\b.nova", b"x"),
            "a drive letter": raw_entry("C:evil.nova", b"x"),
            "a dot part": raw_entry("./a.nova", b"x"),
            "an empty part": raw_entry("a//b.nova", b"x"),
            "a trailing slash": raw_entry("a/", b"", kind=b"5"),
            "a control character": raw_entry("a\x01b.nova", b"x"),
            "a symbolic link": raw_entry("link.nova", b"", kind=b"2"),
            "a hard link": raw_entry("link.nova", b"", kind=b"1"),
            "a directory": raw_entry("dir", b"", kind=b"5"),
            "a character device": raw_entry("dev.nova", b"", kind=b"3"),
            "a block device": raw_entry("dev.nova", b"", kind=b"4"),
            "a fifo": raw_entry("fifo.nova", b"", kind=b"6"),
            "a pax header": raw_entry("pax.nova", b"x", kind=b"x"),
            "a GNU long name": raw_entry("long.nova", b"x", kind=b"L"),
            "a file that is not a package file": raw_entry("run.sh", b"#!/bin/sh"),
            "a Python file": raw_entry("evil.py", b"x"),
            "a name twice": good + raw_entry("a.nova", b"1") + raw_entry("a.nova", b"2"),
            "a name twice in another case": raw_entry("A.nova", b"1") + raw_entry("a.nova", b"2"),
            "a damaged checksum": raw_entry("a.nova", b"x", checksum_ok=False),
            "not ustar": raw_entry("a.nova", b"x", magic=b"GNUtar"),
            "a file over the limit": raw_entry("big.nova", b"", size=nr.MAX_FILE_BYTES + 1),
            "a path over 255 bytes": raw_entry(("a" * 120 + "/") * 3 + "x.nova", b"x"),
            "an entry that runs past the end": raw_entry("a.nova", b"", size=5000),
            "data after the end marker": good + END + b"x" * 512,
            "no end marker": good,
            "a half end marker": good + b"\0" * 512,
        }

    def test_the_hostile_corpus_is_refused_before_anything_is_written(self):
        for name, body in self.hostile().items():
            data = body if name in ("data after the end marker", "no end marker", "a half end marker") or name == "an entry that runs past the end" else body
            if name not in ("data after the end marker", "no end marker", "a half end marker"):
                data = raw_entry("nova.json", b"{}") + data + END
            with self.subTest(name):
                with self.assertRaises(nr.RegistryError):
                    nr.read_archive(data)
                folder = tempfile.mkdtemp(prefix="nova-hostile-")
                try:
                    target = os.path.join(folder, "out")
                    with self.assertRaises(nr.RegistryError):
                        nr.extract_archive(data, target)
                    self.assertEqual(os.listdir(folder), [], "nothing is left behind")
                finally:
                    shutil.rmtree(folder, ignore_errors=True)

    def test_too_many_files_and_too_many_bytes_are_refused(self):
        many = b"".join(raw_entry("f%04d.nova" % i, b"x") for i in range(nr.MAX_FILES + 1)) + END
        with self.assertRaises(nr.RegistryError) as caught:
            nr.read_archive(many)
        self.assertIn("more than {} files".format(nr.MAX_FILES), str(caught.exception))
        chunk = b"x" * nr.MAX_FILE_BYTES
        total = b"".join(raw_entry("c%02d.nova" % i, chunk) for i in range(17)) + END
        with self.assertRaises(nr.RegistryError) as caught:
            nr.read_archive(total)
        self.assertIn("more than", str(caught.exception))
        with self.assertRaises(nr.RegistryError):
            nr.read_archive(b"\0" * (nr.MAX_ARCHIVE_BYTES + 1))

    def test_extraction_never_overwrites_and_never_follows_a_link(self):
        folder = tempfile.mkdtemp(prefix="nova-extract-")
        self.addCleanup(shutil.rmtree, folder, True)
        data = nr.build_archive({"nova.json": b"{}", "main.nova": b"x"})
        target = os.path.join(folder, "pkg")
        nr.extract_archive(data, target)
        self.assertEqual(sorted(os.listdir(target)), ["main.nova", "nova.json"])
        with self.assertRaises(nr.RegistryError):
            nr.extract_archive(data, target)                      # it exists now
        os.mkdir(os.path.join(folder, "outside"))
        if hasattr(os, "symlink"):
            try:
                os.symlink(os.path.join(folder, "outside"), os.path.join(folder, "linked"))
            except (OSError, NotImplementedError):
                return
            with self.assertRaises(nr.RegistryError):
                nr.extract_archive(data, os.path.join(folder, "linked"))
            self.assertEqual(os.listdir(os.path.join(folder, "outside")), [])

    def test_a_file_that_pack_would_write_but_the_reader_refuses_does_not_exist(self):
        for name in ("../x.nova", "/x.nova", "a\\b.nova", "x.py", "run.sh", "a//b.nova"):
            with self.assertRaises(nr.RegistryError):
                nr.build_archive({name: b"x"})


class Registry(unittest.TestCase):
    """A directory registry, made with the real commands."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="nova-reg-")
        self.addCleanup(shutil.rmtree, self.root, True)
        self.registry = os.path.join(self.root, "registry")
        self.project = os.path.join(self.root, "app")
        self.state = os.path.join(self.root, "state.json")
        os.makedirs(self.project)
        self.env = {"NOVA_PKG_STATE": self.state}
        self.keyfile = os.path.join(self.root, "registry.key")
        code, out, err = self.nova_pkg(["keygen", "--out", self.keyfile], self.root)
        self.assertEqual(code, 0, err)
        self.public = [line.split(": ")[1] for line in out.splitlines() if line.startswith("public key")][0]

    def nova_pkg(self, argv, cwd=None, env=None):
        return run(PKG, argv, cwd or self.project, dict(self.env, **(env or {})))

    def make_package(self, name, version, source="export def hello() { return \"hello from \" + %r }\n", capabilities=(),
                     extra=None, files=None):
        folder = os.path.join(self.root, "src-" + name.replace("/", "-") + "-" + version)
        manifest = {"name": name, "version": version, "license": "MIT", "capabilities": list(capabilities)}
        manifest.update(extra or {})
        write(os.path.join(folder, "nova.json"), manifest)
        write(os.path.join(folder, "main.nova"), source if "%r" not in source else source % name)
        for relative, text in (files or {}).items():
            write(os.path.join(folder, relative), text)
        return folder

    def publish(self, folder, keys=None, extra_args=(), registry=None):
        argv = ["publish", "--registry", registry or self.registry]
        for key in keys or [self.keyfile]:
            argv += ["--key", key]
        return self.nova_pkg(argv + list(extra_args), folder)

    def published(self, name, version, **more):
        folder = self.make_package(name, version, **more)
        code, out, err = self.publish(folder)
        self.assertEqual(code, 0, out + err)
        return folder, out

    def app(self, dependencies, **more):
        manifest = {"name": "app", "version": "1.0.0", "registry": "../registry", "registryKeys": [self.public],
                    "dependencies": dependencies}
        manifest.update(more)
        write(os.path.join(self.project, "nova.json"), manifest)

    def install(self, *argv, expect=0):
        code, out, err = self.nova_pkg(["install"] + list(argv))
        self.assertEqual(code, expect, out + err)
        return out, err

    def lock(self):
        with open(os.path.join(self.project, "nova.lock"), encoding="utf-8") as handle:
            return json.load(handle)

    def registry_file(self, relative):
        return os.path.join(self.registry, *relative.split("/"))

    def refuses(self, needle, *argv):
        out, err = self.install(*argv, expect=1)
        self.assertIn(needle, err)


class EndToEnd(Registry):
    def test_publish_install_import_and_verify_on_every_engine(self):
        self.published("acme/ledger", "1.0.0")
        self.published("acme/ledger", "1.1.0")
        self.app({"acme/ledger": "^1.0.0"})
        out, err = self.install()
        self.assertIn("acme/ledger 1.1.0", out)
        lock = self.lock()
        entry = lock["packages"]["acme/ledger"]
        self.assertEqual(lock["lockfile_version"], 2)
        self.assertEqual((entry["version"], entry["resolved"]), ("1.1.0", "archive/acme/ledger/1.1.0.tar"))
        with open(self.registry_file("archive/acme/ledger/1.1.0.tar"), "rb") as handle:
            self.assertEqual(entry["archive"], "sha256-" + hashlib.sha256(handle.read()).hexdigest())
        self.assertEqual(entry["signedBy"], [nr.key_id(self.public)])
        self.assertTrue(os.path.isfile(os.path.join(self.project, ".nova_modules", "acme", "ledger", "main.nova")))
        code, out, err = self.nova_pkg(["verify"])
        self.assertEqual((code, out.strip()), (0, "all packages match nova.lock"), err)
        write(os.path.join(self.project, "a.nova"), 'import "acme/ledger"\nprint(ledger.hello())\nimport "acme/ledger" as l2\nprint(l2.hello())')
        for name, flags in ENGINES:
            code, out, err = run(NOVA, flags + ["a.nova"], self.project)
            self.assertEqual((code, out), (0, "hello from acme/ledger\nhello from acme/ledger\n"), (name, err))

    def test_an_installed_scoped_package_is_still_held_to_its_capabilities_on_every_engine(self):
        self.published("acme/reader", "1.0.0", source='export def load(p) { return read(p) }\n', capabilities=["files.read"])
        self.app({"acme/reader": "*"})
        self.install()
        self.assertEqual(self.lock()["packages"]["acme/reader"]["capabilities"], ["files.read"])
        path = os.path.join(self.project, ".nova_modules", "acme", "reader", "nova.json")
        manifest = json.load(open(path))
        manifest["capabilities"] = []
        write(path, manifest)
        write(os.path.join(self.project, "a.nova"), 'import "acme/reader"\nprint(reader.load("nova.json"))')
        for name, flags in ENGINES:
            code, out, err = run(NOVA, flags + ["a.nova"], self.project)
            self.assertEqual(code, 1, name)
            self.assertIn('ImportError: package "acme/reader": main.nova uses read, which needs the files.read capability', out + err, name)

    def test_frozen_install_uses_the_lock_and_the_pinned_archive(self):
        self.published("acme/ledger", "1.0.0")
        self.app({"acme/ledger": "*"})
        self.install()
        before = open(os.path.join(self.project, "nova.lock"), encoding="utf-8").read()
        shutil.rmtree(os.path.join(self.project, ".nova_modules"))
        self.install("--frozen")
        self.assertEqual(open(os.path.join(self.project, "nova.lock"), encoding="utf-8").read(), before)
        self.published("acme/ledger", "1.2.0")
        self.install("--frozen")
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.0.0")      # a new version changes nothing

    def test_publishing_a_version_twice_is_refused_and_changes_nothing(self):
        folder, _ = self.published("acme/ledger", "1.0.0")
        before = {name: open(self.registry_file(name), "rb").read() for name in ("registry.json", "index/acme/ledger.json", "archive/acme/ledger/1.0.0.tar")}
        write(os.path.join(folder, "main.nova"), "export let changed = 1\n")
        code, out, err = self.publish(folder)
        self.assertEqual(code, 1)
        self.assertIn("is already published; a published version is never changed", err)
        for name, data in before.items():
            self.assertEqual(open(self.registry_file(name), "rb").read(), data, name)

    def test_the_serial_goes_up_with_every_change_and_expiry_is_set(self):
        self.published("acme/ledger", "1.0.0")
        first = json.load(open(self.registry_file("registry.json")))["signed"]
        self.published("acme/ledger", "1.0.1")
        second = json.load(open(self.registry_file("registry.json")))["signed"]
        self.assertEqual((first["serial"], second["serial"]), (1, 2))
        self.assertEqual(sorted(second["snapshot"]), ["index/acme/ledger.json", "revoked.json"])
        self.assertGreater(second["expires"], "2026-")

    def test_dry_run_writes_nothing(self):
        folder = self.make_package("acme/ledger", "1.0.0")
        code, out, err = self.publish(folder, extra_args=["--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("would write archive/acme/ledger/1.0.0.tar", out)
        self.assertIn("would write registry.json", out)
        self.assertFalse(os.path.exists(self.registry))

    def test_yank_stops_ranges_choosing_a_version_but_a_lock_still_installs_it(self):
        self.published("acme/ledger", "1.0.0")
        self.published("acme/ledger", "1.1.0")
        self.app({"acme/ledger": "^1.0.0"})
        self.install()
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.1.0")
        folder = self.make_package("acme/ledger", "1.1.0")
        code, out, err = self.nova_pkg(["yank", "1.1.0", "--registry", self.registry, "--key", self.keyfile], folder)
        self.assertEqual(code, 0, err)
        shutil.rmtree(os.path.join(self.project, ".nova_modules"))
        self.install("--frozen")                                                    # still installs from the lock
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.1.0")
        os.unlink(os.path.join(self.project, "nova.lock"))
        self.install()                                                              # a fresh resolution skips it
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.0.0")
        code, out, err = self.nova_pkg(["unyank", "1.1.0", "--registry", self.registry, "--key", self.keyfile], folder)
        self.assertEqual(code, 0, err)
        os.unlink(os.path.join(self.project, "nova.lock"))
        self.install()
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["version"], "1.1.0")

    def test_revoking_an_archive_refuses_it_everywhere_even_from_a_lock(self):
        self.published("acme/ledger", "1.0.0")
        self.app({"acme/ledger": "*"})
        self.install()
        digest = self.lock()["packages"]["acme/ledger"]["archive"]
        code, out, err = self.nova_pkg(["revoke", "--registry", self.registry, "--key", self.keyfile, "--archive", digest,
                                        "--reason", "it phones home"])
        self.assertEqual(code, 0, err)
        shutil.rmtree(os.path.join(self.project, ".nova_modules"))
        self.refuses("was revoked: it phones home", "--frozen")
        os.unlink(os.path.join(self.project, "nova.lock"))
        self.refuses("was revoked: it phones home")

    def test_a_revoked_key_can_no_longer_sign_the_index(self):
        self.published("acme/ledger", "1.0.0")
        second = os.path.join(self.root, "second.key")
        self.assertEqual(self.nova_pkg(["keygen", "--out", second], self.root)[0], 0)
        self.app({"acme/ledger": "*"})
        code, out, err = self.nova_pkg(["revoke", "--registry", self.registry, "--key", self.keyfile, "--keyid",
                                        nr.key_id(self.public), "--reason", "stolen"])
        self.assertEqual(code, 0, err)
        self.refuses("is not signed by enough trusted keys")


class Tampering(Registry):
    """Rows R5 to R9 of the supply-chain table: every file of a registry, altered, is refused."""

    def setUp(self):
        super().setUp()
        self.published("acme/ledger", "1.0.0")
        self.app({"acme/ledger": "*"})

    def alter(self, relative, change):
        path = self.registry_file(relative)
        with open(path, "rb") as handle:
            data = handle.read()
        with open(path, "wb") as handle:
            handle.write(change(data))

    def test_an_altered_registry_json(self):
        def forge(data):
            envelope = json.loads(data)
            envelope["signed"]["expires"] = "2999-01-01T00:00:00Z"
            return json.dumps(envelope).encode()
        self.alter("registry.json", forge)
        self.refuses("registry.json is not signed by enough trusted keys")

    def test_an_altered_index(self):
        def forge(data):
            envelope = json.loads(data)
            envelope["signed"]["versions"]["1.0.0"]["size"] += 1
            return json.dumps(envelope).encode()
        self.alter("index/acme/ledger.json", forge)
        self.refuses("does not match the hash that registry.json")

    def test_an_altered_revoked_json(self):
        self.alter("revoked.json", lambda data: data.replace(b'"archives"', b'"archivez"'))
        self.refuses("does not match the hash that registry.json")

    def test_an_altered_archive(self):
        self.alter("archive/acme/ledger/1.0.0.tar", lambda data: data[:600] + bytes([data[600] ^ 1]) + data[601:])
        self.refuses("does not match the hash and size that the signed index records")

    def test_an_archive_swapped_for_another_one_with_the_right_name(self):
        other = nr.build_archive({"nova.json": b'{"name":"acme/ledger","version":"1.0.0"}', "main.nova": b"print(1)\n"})
        self.alter("archive/acme/ledger/1.0.0.tar", lambda data: other)
        self.refuses("does not match the hash and size")

    def test_a_missing_file(self):
        os.unlink(self.registry_file("archive/acme/ledger/1.0.0.tar"))
        self.refuses("has no archive/acme/ledger/1.0.0.tar")

    def test_mix_and_match_an_old_index_with_a_new_registry_json(self):
        old_index = open(self.registry_file("index/acme/ledger.json"), "rb").read()
        self.published("acme/ledger", "1.1.0")
        with open(self.registry_file("index/acme/ledger.json"), "wb") as handle:
            handle.write(old_index)
        self.refuses("does not match the hash that registry.json")

    def test_a_rollback_to_an_older_registry_json_after_the_client_saw_a_newer_one(self):
        old = {name: open(self.registry_file(name), "rb").read() for name in ("registry.json", "revoked.json", "index/acme/ledger.json")}
        self.published("acme/ledger", "1.1.0")
        self.install()                                                      # the client has now seen serial 2
        for name, data in old.items():
            with open(self.registry_file(name), "wb") as handle:
                handle.write(data)
        self.refuses("is at serial 1, but this machine has seen serial 2")

    def test_a_frozen_registry_that_has_expired(self):
        shutil.rmtree(self.registry)
        folder = self.make_package("acme/ledger", "1.0.0")
        self.assertEqual(self.publish(folder, extra_args=["--expires-days", "-1"])[0], 0)
        self.refuses("expired on")

    def test_a_registry_signed_by_other_keys(self):
        other = os.path.join(self.root, "other.key")
        self.nova_pkg(["keygen", "--out", other], self.root)
        shutil.rmtree(self.registry)
        self.assertEqual(self.publish(self.make_package("acme/ledger", "1.0.0"), keys=[other])[0], 0)
        self.refuses("is not signed by enough trusted keys")

    def test_a_signed_registry_with_no_trusted_keys_is_not_used(self):
        self.app({"acme/ledger": "*"})
        manifest = json.load(open(os.path.join(self.project, "nova.json")))
        del manifest["registryKeys"]
        write(os.path.join(self.project, "nova.json"), manifest)
        self.refuses("trusts no keys for it")

    def test_threshold_two_of_three(self):
        keys = [self.keyfile] + [os.path.join(self.root, "k%d.key" % i) for i in (2, 3)]
        for path in keys[1:]:
            self.nova_pkg(["keygen", "--out", path], self.root)
        publics = [nr.read_key_file(path)["public"] for path in keys]
        shutil.rmtree(self.registry)
        # registry.json is signed by the keys given; two of three must sign what a client trusts at threshold 2
        self.assertEqual(self.publish(self.make_package("acme/ledger", "1.0.0"), keys=keys[:2])[0], 0)
        self.app({"acme/ledger": "*"}, registryKeys=publics, registryThreshold=2)
        self.install()
        self.app({"acme/ledger": "*"}, registryKeys=publics, registryThreshold=3)
        os.unlink(os.path.join(self.project, "nova.lock"))
        self.refuses("is not signed by enough trusted keys (2 valid of the 3 required)")

    def test_a_dependency_cannot_name_another_registry(self):
        """R2: the registry of a dependency's manifest is ignored; every package comes from the project's registry."""
        evil = os.path.join(self.root, "evil")
        evil_key = os.path.join(self.root, "evil.key")
        self.nova_pkg(["keygen", "--out", evil_key], self.root)
        self.assertEqual(self.publish(self.make_package("acme/other", "9.9.9", source='export let who = "evil"\n'), keys=[evil_key],
                                      registry=evil)[0], 0)
        self.published("acme/other", "1.0.0", source='export let who = "good"\n')
        self.published("acme/uses", "1.0.0", source='import "acme/other" as other\nexport let who = other.who\n',
                       extra={"registry": evil, "dependencies": {"acme/other": "*"}})
        self.app({"acme/uses": "*"})
        self.install()
        self.assertEqual(self.lock()["packages"]["acme/other"]["version"], "1.0.0")
        write(os.path.join(self.project, "a.nova"), 'import "acme/uses"\nprint(uses.who)')
        self.assertEqual(run(NOVA, ["a.nova"], self.project)[1], "good\n")


class Publishing(Registry):
    def test_pack_is_deterministic_and_lists_exactly_the_allowed_files(self):
        folder = self.make_package("acme/ledger", "1.0.0", extra={"files": ["main.nova", "src/**/*.nova", "README.md"]},
                                   files={"src/a/b.nova": "export let x = 1\n", "README.md": "hi", "notes.md": "private",
                                          "script.py": "print(1)", "other.nova": "export let y = 2\n"})
        hashes = []
        for _ in range(2):
            code, out, err = self.nova_pkg(["pack", "--out", os.path.join(self.root, "out")], folder)
            self.assertEqual(code, 0, err)
            hashes.append(out.strip().splitlines()[-1])
            os.utime(os.path.join(folder, "main.nova"), (1, 1))                # a different time must change nothing
        self.assertEqual(hashes[0], hashes[1])
        with open(os.path.join(self.root, "out", "acme-ledger-1.0.0.tar"), "rb") as handle:
            data = handle.read()
        self.assertEqual("sha256-" + hashlib.sha256(data).hexdigest(), hashes[0])
        self.assertEqual(sorted(nr.read_archive(data)), ["README.md", "main.nova", "nova.json", "src/a/b.nova"])

    def test_a_file_that_looks_like_a_secret_is_refused(self):
        for name in (".env", ".env.production", "server.pem", "id_rsa", "credentials.json", "secrets.json", "x.secret.json", "deploy.key"):
            with self.subTest(name):
                shutil.rmtree(os.path.join(self.root, "src-acme-ledger-1.0.0"), ignore_errors=True)
                folder = self.make_package("acme/ledger", "1.0.0", files={name: "TOKEN=1"})
                code, out, err = self.nova_pkg(["pack", "--out", os.path.join(self.root, "out")], folder)
                if name in ("credentials.json", "secrets.json", "x.secret.json"):
                    self.assertEqual(code, 1, name)
                    self.assertIn("looks like a secret", err)
                else:
                    self.assertEqual(code, 0, (name, err))            # not a kind of file a package holds: left out, never packed
                    with open(os.path.join(self.root, "out", "acme-ledger-1.0.0.tar"), "rb") as handle:
                        self.assertNotIn(name, nr.read_archive(handle.read()))

    def test_publish_refuses_a_package_that_uses_an_undeclared_capability(self):
        folder = self.make_package("acme/ledger", "1.0.0", source='export def go() { return read("x") }\n')
        code, out, err = self.publish(folder)
        self.assertEqual(code, 1)
        self.assertIn("uses read, which needs files.read", err)
        self.assertFalse(os.path.exists(self.registry))

    def test_publish_needs_an_owner_a_key_and_a_registry_folder(self):
        folder = self.make_package("unscoped", "1.0.0")
        code, out, err = self.publish(folder)
        self.assertEqual(code, 1)
        self.assertIn('needs a name with an owner, "owner/name"', err)
        folder = self.make_package("acme/ledger", "1.0.0")
        self.assertEqual(self.nova_pkg(["publish", "--registry", self.registry], folder)[0], 1)
        code, out, err = self.nova_pkg(["publish", "--registry", "https://example.org/r", "--key", self.keyfile], folder)
        self.assertEqual(code, 1)
        self.assertIn("publish writes to a registry folder", err)

    def test_a_key_that_is_not_the_registrys_cannot_publish_to_it(self):
        self.published("acme/ledger", "1.0.0")
        other = os.path.join(self.root, "other.key")
        self.nova_pkg(["keygen", "--out", other], self.root)
        code, out, err = self.publish(self.make_package("acme/ledger", "1.0.1"), keys=[other])
        self.assertEqual(code, 1)
        self.assertIn("is not signed by enough trusted keys", err)

    def test_look_alike_names_are_refused(self):
        """R1: typosquatting."""
        self.published("acme/ledger", "1.0.0")
        for name, needle in (("evil/ledgr", "one letter away from acme/ledger"), ("evil/ledgerr", "one letter away"),
                             ("evil/ledher", "one letter away"), ("evil/ledegr", "one letter away"),
                             ("evil/led.ger", "differ only in case or in - _ ."), ("acme/led-ger", "differ only in case or in - _ ."),
                             ("evil/ledger", "differ only")):
            with self.subTest(name):
                code, out, err = self.publish(self.make_package(name, "1.0.0"))
                self.assertEqual(code, 1, (name, out))
                self.assertIn(needle, err)
        code, out, err = self.publish(self.make_package("acme/payments", "1.0.0"))        # unrelated: fine
        self.assertEqual(code, 0, err)
        code, out, err = self.publish(self.make_package("acme/ledger", "1.0.1"))          # the same package, a new version: fine
        self.assertEqual(code, 0, err)

    def test_the_keygen_never_overwrites_a_key(self):
        code, out, err = self.nova_pkg(["keygen", "--out", self.keyfile], self.root)
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        mode = os.stat(self.keyfile).st_mode & 0o777
        if os.name == "posix":
            self.assertEqual(mode, 0o600)

    def test_nothing_in_a_package_is_ever_executed_by_install(self):
        """R11: a manifest has no key for a script or a hook, and a package's code is parsed, never run, at install."""
        marker = os.path.join(self.root, "ran")
        self.published("acme/ledger", "1.0.0", source='write(%s, "x")\nexport let x = 1\n' % json.dumps(marker), capabilities=["files.write"])
        self.app({"acme/ledger": "*"})
        self.install()
        self.assertFalse(os.path.exists(marker))


class Https(Registry):
    """Install from an HTTPS registry served by a local server with a test-only certificate. Verification stays on."""

    def serve(self, directory, handler=None):
        root = directory

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=root, **kwargs)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler(root) if handler else Quiet)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(os.path.join(FIXTURES, "localhost.pem"), os.path.join(FIXTURES, "localhost.key"))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return "https://localhost:%d" % server.server_address[1]

    def test_install_from_an_https_registry_end_to_end(self):
        self.published("acme/ledger", "1.0.0")
        url = self.serve(self.registry)
        self.app({"acme/ledger": "*"}, registry=url)
        code, out, err = self.nova_pkg(["install"], env={"NOVA_PKG_CA_FILE": os.path.join(FIXTURES, "localhost.pem")})
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.lock()["packages"]["acme/ledger"]["source"], {"registry": url})
        write(os.path.join(self.project, "a.nova"), 'import "acme/ledger"\nprint(ledger.hello())')
        self.assertEqual(run(NOVA, ["a.nova"], self.project)[1], "hello from acme/ledger\n")

    def test_certificate_verification_cannot_be_turned_off(self):
        self.published("acme/ledger", "1.0.0")
        url = self.serve(self.registry)
        self.app({"acme/ledger": "*"}, registry=url)
        code, out, err = self.nova_pkg(["install"])                     # no extra trusted certificate: the test one is not trusted
        self.assertEqual(code, 1)
        self.assertIn("cannot fetch", err)
        self.assertTrue("CERTIFICATE_VERIFY_FAILED" in err or "certificate" in err.lower(), err)
        for variable in ("PYTHONHTTPSVERIFY", "SSL_CERT_FILE"):
            code, out, err = self.nova_pkg(["install"], env={variable: "0"})
            self.assertEqual(code, 1, variable)

    def test_http_and_credentials_in_the_address_are_refused(self):
        for address, needle in (("http://localhost:1", "is not https"), ("https://user:pw@localhost:1", "user name or password")):
            self.app({"acme/ledger": "*"}, registry=address)
            code, out, err = self.nova_pkg(["install"])
            self.assertEqual(code, 1, address)
            self.assertIn(needle, err)

    def test_a_response_larger_than_the_limit_is_refused(self):
        class Flood(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(10 ** 9))
                self.end_headers()

            def log_message(self, *args):
                pass

        url = self.serve(self.registry, handler=lambda root: Flood)
        with self.assertRaises(nr.RegistryError) as caught:
            os.environ[nr.CA_ENV] = os.path.join(FIXTURES, "localhost.pem")
            try:
                nr.fetch(url, "registry.json", 1000)
            finally:
                del os.environ[nr.CA_ENV]
        self.assertIn("1000", str(caught.exception))

    def test_a_redirect_to_another_host_or_to_http_is_refused(self):
        class Redirect(http.server.BaseHTTPRequestHandler):
            target = "http://localhost:1/x"

            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", self.target)
                self.end_headers()

            def log_message(self, *args):
                pass

        url = self.serve(self.registry, handler=lambda root: Redirect)
        os.environ[nr.CA_ENV] = os.path.join(FIXTURES, "localhost.pem")
        self.addCleanup(os.environ.pop, nr.CA_ENV, None)
        for target in ("http://localhost:1/x", "https://example.org/x"):
            Redirect.target = target
            with self.assertRaises(nr.RegistryError) as caught:
                nr.fetch(url, "registry.json", 1000)
            self.assertIn("not https on the same host", str(caught.exception))

    def test_no_proxy_is_used(self):
        self.published("acme/ledger", "1.0.0")
        url = self.serve(self.registry)
        self.app({"acme/ledger": "*"}, registry=url)
        code, out, err = self.nova_pkg(["install"], env={"NOVA_PKG_CA_FILE": os.path.join(FIXTURES, "localhost.pem"),
                                                         "HTTPS_PROXY": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9"})
        self.assertEqual(code, 0, out + err)

    def test_the_fetch_core_cannot_be_reached_from_novalang(self):
        """D6: nothing of the fetch core is a NovaLang name, a built-in or a native."""
        sys.path.insert(0, ROOT)
        import novalang
        for name in ("fetch", "http", "net", "download", "get_url", "urlopen"):
            self.assertNotIn(name, novalang.BUILTINS)
        self.assertNotIn("net", novalang.CAPABILITY_OF.values())
        self.assertNotIn("nova_registry", open(os.path.join(ROOT, "novalang.py"), encoding="utf-8").read())


class Limits(unittest.TestCase):
    def test_the_fetch_core_reads_a_folder_and_stops_at_the_limit(self):
        folder = tempfile.mkdtemp(prefix="nova-fetch-")
        self.addCleanup(shutil.rmtree, folder, True)
        write(os.path.join(folder, "a.json"), "x" * 100)
        self.assertEqual(len(nr.fetch(folder, "a.json", 100)), 100)
        with self.assertRaises(nr.RegistryError):
            nr.fetch(folder, "a.json", 99)
        with self.assertRaises(nr.RegistryError):
            nr.fetch(folder, "../a.json", 1000)
        with self.assertRaises(nr.RegistryError):
            nr.fetch(folder, "/etc/passwd", 1000)
        with self.assertRaises(nr.RegistryError):
            nr.fetch(folder, "missing.json", 1000)
        self.assertEqual(len(nr.fetch("file://" + folder, "a.json", 100)), 100)

    def test_signed_files_with_the_wrong_shape_are_refused(self):
        key = nr.generate_key()
        trusted = {nr.key_id(key["public"]): key["public"]}
        for envelope in ([], {}, {"signed": {}}, {"signed": [], "signatures": []}, {"signed": {}, "signatures": "x"},
                         {"signed": {}, "signatures": [{"keyid": "a", "sig": "00"}]}, {"signed": {}, "signatures": [1]},
                         {"signed": {}, "signatures": [], "extra": 1}):
            with self.assertRaises(nr.RegistryError):
                nr.verify_envelope(envelope, trusted, 1, "x")
        good = nr.sign_envelope({"a": 1}, [dict(key, seed=key["seed"])])
        self.assertEqual(nr.verify_envelope(good, trusted, 1, "x"), [nr.key_id(key["public"])])
        doubled = {"signed": good["signed"], "signatures": good["signatures"] * 2}
        with self.assertRaises(nr.RegistryError):
            nr.verify_envelope(doubled, trusted, 2, "x")            # the same key twice is one signature

    def test_edit_distance(self):
        for a, b, expected in (("ledger", "ledgr", True), ("ledger", "ledgerr", True), ("ledger", "ledher", True), ("ledger", "ledegr", True),
                               ("ledger", "ledger", True), ("ledger", "ledg", False), ("ledger", "payments", False), ("abcd", "badc", False)):
            self.assertEqual(nr.edit_distance_one(a, b), expected, (a, b))


if __name__ == "__main__":
    unittest.main()
