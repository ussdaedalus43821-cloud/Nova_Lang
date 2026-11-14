"""std:hash and files.sha256_file (M14 slice P1, docs/spec/09-library.md [lib.std-hash]): the NIST vectors, the files of every size around a
piece, the read grant, and the three engines."""

import hashlib
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import novalang  # noqa: E402

RESTRICTED_UNSUPPORTED = sys.platform == "win32" and sys.version_info < (3, 8)
ENGINES = (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"]))


def nova(flags, program, folder):
    path = os.path.join(folder, "main.nova")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(program)
    return subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True,
                          timeout=600, stdin=subprocess.DEVNULL, cwd=folder, env=dict(os.environ, NOVALANG_CACHE="off"))


class Vectors(unittest.TestCase):
    def test_the_nist_vectors(self):      # FIPS 180-4 / RFC 6234 examples
        for text, digest in (("", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
                             ("abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
                             ("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"),
                             ("a" * 1000000, "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")):
            self.assertEqual(novalang.native_hash_sha256([text], None), digest, text[:20])

    def test_a_string_is_hashed_as_utf_8(self):
        for text in ("héllo", "日本語", "😀 emoji", "line\nbreak\r\n", "\0 nul"):
            self.assertEqual(novalang.native_hash_sha256([text], None), hashlib.sha256(text.encode("utf-8")).hexdigest())

    def test_what_is_not_text_is_an_error_that_names_the_function(self):
        for value in (5, [], None, True, {}):
            with self.assertRaises(novalang.NovaError) as caught:
                novalang.native_hash_sha256([value], None)
            self.assertIn("the text for hash.sha256() needs a string", caught.exception.message)
        with self.assertRaises(novalang.NovaError):
            novalang.native_hash_sha256(["\ud800"], None)          # a lone surrogate has no UTF-8


class Files(unittest.TestCase):
    def hashed(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "f.bin")
            with open(path, "wb") as handle:
                handle.write(data)
            return novalang.NATIVE_FUNCTIONS["files"]["sha256_file"].implementation([path], None, _Interpreter()), hashlib.sha256(data).hexdigest()

    def test_sizes_around_a_piece(self):
        rng = random.Random(6234)
        for size in (0, 1, 63, 64, 65, 65535, 65536, 65537, 131071, 131072, 131073, 300001):
            got, want = self.hashed(bytes(rng.randrange(256) for _ in range(size)))
            self.assertEqual(got, want, size)

    def test_binary_and_line_ends_are_not_changed(self):
        for data in (b"\r\n", b"\n", b"\r", b"\xff\xfe\x00\x01", b"a\r\nb\n"):
            got, want = self.hashed(data)
            self.assertEqual(got, want, data)

    def test_a_folder_and_a_missing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            for path, label in ((folder, "FileError"), (os.path.join(folder, "nope"), "FileNotFoundError")):
                with self.assertRaises(novalang.NovaError) as caught:
                    novalang.NATIVE_FUNCTIONS["files"]["sha256_file"].implementation([path], None, _Interpreter())
                self.assertEqual(caught.exception.label, label)

    def test_the_native_carries_the_read_grant_like_the_other_file_natives(self):
        self.assertEqual(novalang.NATIVE_FUNCTIONS["files"]["sha256_file"].paths, ((0, "read"),))
        self.assertEqual(novalang.NATIVE_FUNCTIONS["hash"]["sha256"].paths, ())


class _Interpreter:
    counting = False

    def step(self, position=None):
        pass

    def charge(self, units, position=None):
        pass


class Engines(unittest.TestCase):
    def test_three_engines_hash_the_same_file_as_sha256sum(self):
        with tempfile.TemporaryDirectory() as folder:
            data = bytes(random.Random(1).randrange(256) for _ in range(150000))
            with open(os.path.join(folder, "in.bin"), "wb") as handle:
                handle.write(data)
            want = hashlib.sha256(data).hexdigest()
            program = 'import "std:files" as files\nimport "std:hash" as hash\nprint(files.sha256_file("in.bin"))\nprint(hash.sha256("abc"))\n'
            for name, flags in ENGINES:
                done = nova(flags, program, folder)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                self.assertEqual(done.stdout.split(), [want, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"], name)

    @unittest.skipIf(RESTRICTED_UNSUPPORTED, "the restricted profile needs Python 3.8 or later on Windows")
    def test_a_file_outside_the_grant_or_through_a_link_is_refused_and_one_inside_is_hashed(self):
        with tempfile.TemporaryDirectory() as folder:
            os.mkdir(os.path.join(folder, "data"))
            with open(os.path.join(folder, "data", "in.txt"), "wb") as handle:
                handle.write(b"inside\n")
            with open(os.path.join(folder, "secret.txt"), "wb") as handle:
                handle.write(b"outside\n")
            program = ('import "std:files" as files\n'
                       'print(files.sha256_file("data/in.txt"))\n'
                       'try { print(files.sha256_file("secret.txt")) } catch e { print(e) }\n'
                       'try { print(files.sha256_file("data/../secret.txt")) } catch e { print(e) }\n')
            links = hasattr(os, "symlink")
            if links:
                try:
                    os.symlink(os.path.join(folder, "secret.txt"), os.path.join(folder, "data", "link.txt"))
                    program += 'try { print(files.sha256_file("data/link.txt")) } catch e { print(e) }\n'
                except (OSError, NotImplementedError):
                    links = False
            for name, flags in ENGINES:
                done = nova(["--profile", "restricted", "--allow-read", "data"] + flags, program, folder)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                lines = done.stdout.splitlines()
                self.assertEqual(lines[0], hashlib.sha256(b"inside\n").hexdigest(), name)
                self.assertEqual(lines[1:3], ["FileError: secret.txt is outside the folders this program may use",
                                              "FileError: data/../secret.txt is outside the folders this program may use"], name)
                if links:
                    self.assertEqual(lines[3], "FileError: data/link.txt is outside the folders this program may use", name)
                self.assertNotIn(hashlib.sha256(b"outside\n").hexdigest(), done.stdout, name)

    @unittest.skipIf(RESTRICTED_UNSUPPORTED, "the restricted profile needs Python 3.8 or later on Windows")
    def test_std_files_still_needs_the_read_grant_to_be_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            done = nova(["--profile", "restricted"], 'import "std:files" as files\nprint(1)\n', folder)
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("std:files needs the 'files.read' capability", done.stdout + done.stderr)
            done = nova(["--profile", "restricted"], 'import "std:hash" as hash\nprint(hash.sha256("x")[0:8])\n', folder)
            self.assertEqual((done.returncode, done.stdout.strip()), (0, "2d711642"), done.stderr)      # hashing a string needs no grant


if __name__ == "__main__":
    unittest.main()
