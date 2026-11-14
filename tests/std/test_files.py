"""std:files beyond the conformance cases (M13 slice 3): chunk boundaries, a file the restricted
profile cannot read whole, a link that leads out of the grant, and the natives called directly."""

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


def nova(flags, program, folder):
    path = os.path.join(folder, "main.nova")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(program)
    done = subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True,
                          timeout=600, stdin=subprocess.DEVNULL, cwd=folder, env=dict(os.environ, NOVALANG_CACHE="off"))
    return done


def pieces(path, size):
    """Every line of the file through the native, `size` bytes at a time."""
    lines, offset = [], 0
    while True:
        chunk, offset, at_end = novalang.native_files_next_lines([path, offset, size], None)
        lines.extend(chunk)
        if at_end:
            return lines


class Chunks(unittest.TestCase):
    """The native that reads a piece: whatever the piece size, the lines are the lines of the whole text."""

    def check(self, data, sizes=(1, 2, 3, 5, 7, 16, 64, 4096)):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "f.txt")
            with open(path, "wb") as handle:
                handle.write(data)
            want = novalang.builtin_split_lines([data.decode("utf-8")], None) if data else []
            for size in sizes:
                self.assertEqual(pieces(path, size), want, "chunk size {} for {!r}".format(size, data[:40]))

    def test_the_small_files(self):
        for data in (b"", b"\n", b"\n\n", b"a", b"a\n", b"a\nb", b"a\r\nb\r\n", b"a\rb\rc", b"a\r\n\r\nb", b"\r", b"\r\n", b"x\n\r\ny\r\rz\n"):
            with self.subTest(data=data):
                self.check(data)

    def test_multibyte_characters_never_straddle_a_piece(self):
        self.check("é€😀\nñ\r\n日本語\nend".encode("utf-8"))
        self.check((("é" * 50 + "\n") * 20 + "😀" * 40).encode("utf-8"), sizes=(1, 3, 4, 5, 63))

    def test_a_crlf_on_a_piece_boundary_is_one_line_end(self):
        for size in range(1, 12):
            self.check(b"aaa\r\nbbb\r\nccc\r\nddd", sizes=(size,))

    def test_random_files(self):
        rng = random.Random(13)
        alphabet = ["a", "bc", "\n", "\r\n", "\r", "é", "😀", " ", "\n\n"]
        for _ in range(150):
            data = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 60))).encode("utf-8")
            self.check(data, sizes=(1, 4, 9, 50))

    def test_a_line_longer_than_a_piece_grows_the_piece(self):
        self.check(b"short\n" + b"L" * 5000 + b"\nafter\n", sizes=(10, 100, 4096))

    def test_a_file_that_is_not_utf8_is_a_file_error(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "bad.bin")
            with open(path, "wb") as handle:
                handle.write(b"ok\n\xff\xfe\n")
            with self.assertRaises(novalang.NovaError) as caught:
                pieces(path, 64)
            self.assertEqual(caught.exception.label, "FileError")
            self.assertIn("bad.bin", caught.exception.message)


@unittest.skipIf(RESTRICTED_UNSUPPORTED, "the restricted profile refuses to start on Windows with Python 3.7")
class Restricted(unittest.TestCase):
    def test_a_file_over_the_string_limit_reads_in_pieces_but_not_whole(self):
        with tempfile.TemporaryDirectory() as folder:
            os.mkdir(os.path.join(folder, "data"))
            rows = ["%06d,%s" % (i, "x" * 40) for i in range(30000)]       # about 1.4 MB: over the 1,000,000 character limit
            with open(os.path.join(folder, "data", "big.csv"), "w", encoding="utf-8", newline="") as handle:
                handle.write("\n".join(rows) + "\n")
            program = ('import "std:files" as files\n'
                       'try { read("data/big.csv") } catch e { print(e) }\n'
                       'let all = files.lines("data/big.csv")\nprint(len(all), all[0][0:6], all[29999][0:6])\n'
                       'let n = 0\ndef count(line) { n = n + 1 }\nfiles.each_line("data/big.csv", count)\n'
                       'let seen = [0]\ndef bump(line) { seen[0] = seen[0] + 1 }\nfiles.each_line("data/big.csv", bump)\nprint(seen[0])\n')
            for flags in ([], ["--tree-walk"]):
                with self.subTest(flags=flags):
                    done = nova(["--profile", "restricted", "--allow-read", "data", "--allow-clock"] + flags, program, folder)
                    self.assertEqual(done.returncode, 0, done.stderr[-1500:])
                    self.assertEqual(done.stdout.splitlines(), ["a string cannot grow beyond 1000000 characters", "30000 000000 029999", "30000"])

    @unittest.skipIf(sys.platform == "win32", "symbolic links need privileges on Windows")
    def test_a_link_that_leads_out_of_the_grant_is_refused_by_every_function(self):
        with tempfile.TemporaryDirectory() as folder:
            os.mkdir(os.path.join(folder, "data"))
            with open(os.path.join(folder, "secret.txt"), "w") as handle:
                handle.write("top secret\n")
            os.symlink(os.path.join(folder, "secret.txt"), os.path.join(folder, "data", "link.txt"))
            program = ('import "std:files" as files\n'
                       'def note(line) { print("LEAK " + line) }\n'
                       'try { files.lines("data/link.txt") } catch e { print(e) }\n'
                       'try { files.each_line("data/link.txt", note) } catch e { print(e) }\n'
                       'try { files.size("data/link.txt") } catch e { print(e) }\n'
                       'try { files.is_link("data/link.txt") } catch e { print(e) }\n')
            for flags in ([], ["--tree-walk"], ["--bootstrap"]):
                with self.subTest(flags=flags):
                    done = nova(["--profile", "restricted", "--allow-read", "data"] + flags, program, folder)
                    self.assertEqual(done.returncode, 0, done.stderr[-1500:])
                    self.assertNotIn("LEAK", done.stdout)
                    self.assertEqual(done.stdout.splitlines(), ["FileError: data/link.txt is outside the folders this program may use"] * 4)


class Natives(unittest.TestCase):
    def test_every_listed_native_exists_and_every_native_is_listed(self):
        import json
        with open(os.path.join(ROOT, "lib", "std", "modules.json"), encoding="utf-8") as handle:
            modules = json.load(handle)["modules"]
        for name, descriptor in modules.items():
            with self.subTest(module=name):
                self.assertEqual(sorted(novalang.NATIVE_FUNCTIONS.get(name, {})), sorted(descriptor.get("native", [])))
        self.assertEqual(sorted(novalang.NATIVE_FUNCTIONS), sorted(n for n, d in modules.items() if d.get("native")))

    def test_the_file_natives_are_held_to_the_read_grant(self):
        for name, function in novalang.NATIVE_FUNCTIONS["files"].items():
            with self.subTest(native=name):
                self.assertEqual(function.paths, ((0, "read"),))
        for module in ("decimal", "text"):
            for name, function in novalang.NATIVE_FUNCTIONS[module].items():
                self.assertEqual(function.paths, (), "{}.{} takes no path".format(module, name))

    def test_natives_are_not_global_built_ins(self):
        for module, table in novalang.NATIVE_FUNCTIONS.items():
            for name in table:
                self.assertNotIn("{}.{}".format(module, name), novalang.BUILTINS)
        self.assertNotIn("native", novalang.BUILTINS)
        self.assertNotIn("native_call", novalang.BUILTINS)


if __name__ == "__main__":
    unittest.main()
