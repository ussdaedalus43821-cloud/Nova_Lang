"""A small fixed-seed budget of the fuzzers (tests/security/fuzz.py) on every run, and proof that they can see.

A fuzzer that finds nothing is only evidence if it would have found something. The last two tests put a hole
back (a path check that lets everything in, the `for` count that used to leak Python's OverflowError) and
require the fuzzer to report it.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import fuzz  # noqa: E402
import novalang as nl  # noqa: E402


def links_available():
    try:
        with tempfile.TemporaryDirectory() as folder:
            os.symlink("target", os.path.join(folder, "link"))
    except (OSError, NotImplementedError, AttributeError):
        return False
    return True


class Fuzzers(unittest.TestCase):
    def setUp(self):
        if nl.SANDBOX_UNSUPPORTED:
            self.skipTest("the restricted profile needs Python 3.8 or later on Windows")

    def test_random_hostile_programs_leave_no_finding(self):
        found = fuzz.fuzz_programs("ci", 120, report=lambda text: None)
        self.assertEqual([(index, found_text) for index, _, _, found_text in found], [])

    def test_random_paths_leave_no_finding(self):
        found = fuzz.fuzz_paths("ci", 200, report=lambda text: None, links=links_available())
        self.assertEqual([(index, found_text) for index, _, found_text in found], [])

    def test_the_path_fuzzer_sees_a_check_that_lets_everything_in(self):
        original = nl.inside_folder
        # the hole is confined to the test's own temporary tree: a folder is taken to be its parent
        nl.inside_folder = lambda real, root: original(real, os.path.dirname(root))
        try:
            found = fuzz.fuzz_paths("ci", 60, report=lambda text: None, links=links_available())
        finally:
            nl.inside_folder = original
        self.assertTrue(found, "the path fuzzer did not notice that every path was let in")

    @unittest.skipUnless(links_available(), "this machine cannot make symbolic links")
    def test_the_path_fuzzer_sees_a_check_that_ignores_links(self):
        import posixpath
        original = nl.real_path
        nl.real_path = lambda path: posixpath.normpath(os.path.abspath(path))
        try:
            found = fuzz.fuzz_paths("ci", 400, report=lambda text: None, links=True)
        finally:
            nl.real_path = original
        self.assertTrue(found, "the path fuzzer did not notice a check that does not follow links")

    def test_the_program_fuzzer_sees_a_host_exception(self):
        original = nl.range_iterations

        def old(start, end, step, descending, position):
            span = (start - end) if descending else (end - start)
            return 0 if span < 0 else int(span / step + 1e-9) + 1

        nl.range_iterations = old
        try:
            found = fuzz.fuzz_programs("1", 1, report=lambda text: None, start=125)
        finally:
            nl.range_iterations = original
        self.assertTrue(found and any("OverflowError" in text for text in found[0][3]),
                        "the program fuzzer did not report the OverflowError of a huge `for` bound")


if __name__ == "__main__":
    unittest.main()
