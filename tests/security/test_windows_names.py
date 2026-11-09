"""Windows-only names and null bytes in a path, tested on any system ([sbx.paths]).

The conformance case `esc-paths-windows-device-names-are-outside` runs on Windows only. This forces the
Windows answer so the rule is tested everywhere, and checks that other systems keep ordinary names.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import novalang as nl  # noqa: E402


class WindowsNames(unittest.TestCase):
    def test_device_names_are_recognised_in_every_spelling(self):
        for path in ("CON", "con", "data/CON", "data\\nul", "NUL", "data/aux.txt", "data/COM1", "data/LPT9.log",
                     "PRN", "CON ", "data/con.txt", "CONIN$", "CONOUT$", "\\\\.\\COM1", "//./CON", "\\\\?\\GLOBALROOT",
                     "a/b/Nul.tar.gz", "data/CON:stream"):
            self.assertTrue(nl.names_a_device(path, windows=True), path)

    def test_ordinary_names_are_not(self):
        for path in ("data/in.txt", "console.txt", "data/connect", "COM10", "LPT0", "data/communication", "nullable",
                     "auxiliary/x", "data/prn_notes.txt"):
            self.assertFalse(nl.names_a_device(path, windows=True), path)

    def test_other_systems_keep_the_names(self):
        for path in ("CON", "data/nul", "\\\\.\\COM1"):
            self.assertFalse(nl.names_a_device(path, windows=False), path)

    def test_a_null_byte_is_never_a_path(self):
        self.assertIsNone(nl.real_path("data/in.txt\0"))
        self.assertIsNone(nl.real_path("\0"))

    def test_realpath_refuses_both(self):
        for path in ("a\0b",):
            with self.assertRaises(nl.NovaError):
                nl.builtin_realpath([path], None)


if __name__ == "__main__":
    unittest.main()
