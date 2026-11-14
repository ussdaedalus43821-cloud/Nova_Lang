"""std:csv (M14 slice P1, L2, docs/spec/09-library.md [lib.std-csv]): RFC 4180 reading and writing, the errors that name the
line, the limits, a seeded fuzzer against Python's csv module, and the three engines."""

import csv
import io
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import novalang  # noqa: E402

ENGINES = (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"]))
CSV = novalang.NATIVE_FUNCTIONS["csv"]


class _Interpreter:
    counting = False

    def step(self, position=None):
        pass

    def charge(self, units, position=None):
        pass


def call(name, *args):
    return CSV[name].implementation(list(args), None, _Interpreter())


def parse(text):
    return call("parse", text)


def fails(test, name, args, fragment):
    with test.assertRaises(novalang.NovaError) as caught:
        call(name, *args)
    test.assertIn(fragment, caught.exception.message)
    return caught.exception.message


def python_rows(text, delimiter=","):
    """What Python's csv module reads, strictly, with blank lines dropped and a leading BOM removed (the rules of [lib.std-csv])."""
    if text.startswith("﻿"):
        text = text[1:]
    return [row for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True) if row != []]


def nova(flags, program, folder):
    path = os.path.join(folder, "main.nova")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(program)
    return subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True,
                          timeout=600, stdin=subprocess.DEVNULL, cwd=folder, env=dict(os.environ, NOVALANG_CACHE="off"))


class Reading(unittest.TestCase):
    def test_plain_records(self):
        self.assertEqual(parse("a,b,c\n1,2,3\n"), [["a", "b", "c"], ["1", "2", "3"]])
        self.assertEqual(parse("a,b,c\n1,2,3"), [["a", "b", "c"], ["1", "2", "3"]])        # no final line end
        self.assertEqual(parse(""), [])
        self.assertEqual(parse("x"), [["x"]])

    def test_every_line_end_ends_a_record(self):
        for end in ("\r\n", "\n", "\r"):
            self.assertEqual(parse("a,b" + end + "c,d" + end), [["a", "b"], ["c", "d"]], repr(end))
        self.assertEqual(parse("a\r\nb\nc\rd"), [["a"], ["b"], ["c"], ["d"]])

    def test_a_leading_byte_order_mark_is_not_part_of_the_first_field(self):
        self.assertEqual(parse("﻿name,amount\r\nx,1\r\n"), [["name", "amount"], ["x", "1"]])
        self.assertEqual(parse("a,﻿b"), [["a", "﻿b"]])                              # only at the very start

    def test_quoted_fields(self):
        self.assertEqual(parse('"a,b",c'), [["a,b", "c"]])
        self.assertEqual(parse('"say ""hi""",x'), [['say "hi"', "x"]])
        self.assertEqual(parse('""'), [[""]])
        self.assertEqual(parse('"",""'), [["", ""]])
        self.assertEqual(parse('""""'), [['"']])

    def test_line_ends_inside_quotes_are_kept_as_they_are(self):
        self.assertEqual(parse('"line 1\r\nline 2",x\r\ny,z\r\n'), [["line 1\r\nline 2", "x"], ["y", "z"]])
        self.assertEqual(parse('"a\nb\rc"'), [["a\nb\rc"]])

    def test_empty_fields_and_a_trailing_delimiter(self):
        self.assertEqual(parse(",,"), [["", "", ""]])
        self.assertEqual(parse("a,\n,b"), [["a", ""], ["", "b"]])

    def test_a_blank_line_is_not_a_record(self):
        self.assertEqual(parse("a\n\nb\r\n\r\n"), [["a"], ["b"]])
        self.assertEqual(parse("\n\n"), [])

    def test_spaces_are_part_of_the_field(self):
        self.assertEqual(parse(" a , b "), [[" a ", " b "]])
        self.assertEqual(parse("a\0b,\0"), [["a\0b", "\0"]])

    def test_another_delimiter(self):
        self.assertEqual(call("parse_with", "a;b\n1;2", {"delimiter": ";"}), [["a", "b"], ["1", "2"]])
        self.assertEqual(call("parse_with", "a\tb,c", {"delimiter": "\t"}), [["a", "b,c"]])
        self.assertEqual(call("parse_with", '"a;b";c', {"delimiter": ";"}), [["a;b", "c"]])

    def test_lines_are_read_as_one_text(self):
        self.assertEqual(call("parse_lines", ["a,b", '"multi', 'line",c', "", "d,e"]), [["a", "b"], ["multi\nline", "c"], ["d", "e"]])
        self.assertEqual(call("parse_lines", []), [])
        self.assertEqual(call("parse_lines", ["﻿a,b"]), [["a", "b"]])


class Errors(unittest.TestCase):
    def test_an_unclosed_quote_names_the_line_it_starts_on(self):
        message = fails(self, "parse", ["a\nb,\"never\nclosed\n"], "never closed")
        self.assertEqual(message, "csv.parse() found a quoted field that is never closed; it starts on line 2")

    def test_text_after_a_closing_quote(self):
        message = fails(self, "parse", ['ok\n"a"b,c'], "after the closing quote")
        self.assertEqual(message, "csv.parse() found text after the closing quote of a field on line 2; a quoted field must end at the delimiter or the end of the line")

    def test_a_quote_inside_an_unquoted_field(self):
        message = fails(self, "parse", ['a,b\r\nc,d"e\r\n'], "a quote inside")
        self.assertEqual(message, "csv.parse() found a quote inside a field that does not start with one on line 2; quote the whole field and write the quote twice")

    def test_lines_count_inside_quoted_fields(self):
        fails(self, "parse", ['"x\r\ny\nz",1\r\nbad"\n'], "on line 4")
        fails(self, "parse_lines", [['"x', 'y"', 'q"']], "on line 3")

    def test_the_field_limit(self):
        self.assertEqual(call("parse_with", "a,b,c", {"max_fields": 3}), [["a", "b", "c"]])
        message = fails(self, "parse_with", ["a\nb,c,d,e", {"max_fields": 3}], "max_fields")
        self.assertEqual(message, "csv.parse_with() found more than 3 fields in the record on line 2 (the max_fields limit)")
        fails(self, "parse", ["," * 10000], "more than 10000 fields")
        self.assertEqual(len(parse("," * 9999)[0]), 10000)

    def test_bad_arguments(self):
        for value in (5, [], None, True, {}):
            fails(self, "parse", [value], "csv.parse() needs a string for the text, but got")
        fails(self, "parse_lines", ["a"], "csv.parse_lines() needs a list of strings")
        fails(self, "parse_lines", [["a", 5]], "csv.parse_lines() needs a list of strings, and item 2 is a number")
        fails(self, "parse_with", ["a", []], "csv.parse_with() needs a dictionary for the options, but got a list")
        fails(self, "parse_with", ["a", {"sep": ";"}], "csv.parse_with() does not know the option 'sep' (the options are delimiter and max_fields)")
        for bad in ("", ";;", '"', "\n", "\r", 5):
            fails(self, "parse_with", ["a", {"delimiter": bad}], "needs the delimiter to be one character that is not a quote or a line end")
        for bad in (0, -1, 1.5, "3", True):
            fails(self, "parse_with", ["a", {"max_fields": bad}], "needs max_fields to be a whole number of at least 1")


class Records(unittest.TestCase):
    def test_rows_become_dictionaries_by_the_header(self):
        self.assertEqual(call("records", [["name", "amount"], ["a", "1"], ["b", "2"]]),
                         [{"name": "a", "amount": "1"}, {"name": "b", "amount": "2"}])
        self.assertEqual(call("records", [["only"]]), [])
        self.assertEqual(call("records", []), [])

    def test_a_row_of_the_wrong_length_and_a_repeated_name(self):
        message = fails(self, "records", [[["a", "b"], ["1", "2"], ["3"]]], "row 3")
        self.assertEqual(message, "csv.records() found 1 field(s) in row 3, but the header has 2")
        message = fails(self, "records", [[["a", "a"]]], "twice")
        self.assertEqual(message, "csv.records() found the column name 'a' twice in the header")
        fails(self, "records", ["x"], "csv.records() needs a list of rows")
        fails(self, "records", [[["a"], "b"]], "csv.records() needs a list of rows, and row 2 is a string")
        fails(self, "records", [[["a", 1]]], "csv.records() needs the fields to be strings, and row 1 field 2 is a number")


class Writing(unittest.TestCase):
    def test_minimal_quoting(self):
        self.assertEqual(call("format_row", ["a", "b c", "d,e", 'f"g', "h\ni", "j\rk", ""]), 'a,b c,"d,e","f""g","h\ni","j\rk",')
        self.assertEqual(call("format_row", [""]), '""')                  # so that it is not a blank line, which is no record
        self.assertEqual(call("format_row", [1, 2.5, -3]), "1,2.5,-3")

    def test_format_ends_every_record_with_crlf(self):
        self.assertEqual(call("format", [["a", "b"], ["1", "2"]]), "a,b\r\n1,2\r\n")
        self.assertEqual(call("format", []), "")

    def test_bad_rows(self):
        fails(self, "format_row", [[]], "csv.format_row() needs at least one field")
        fails(self, "format_row", [["a", True]], "csv.format_row() needs strings or numbers, and field 2 is a boolean")
        fails(self, "format_row", ["a"], "csv.format_row() needs a list of fields, but got a string")
        fails(self, "format", [[["a"], []]], "csv.format() needs at least one field in row 2")
        fails(self, "format", [[["a"], [None]]], "csv.format() needs strings or numbers, and row 2 field 1 is")

    def test_what_is_written_reads_back(self):
        rows = [["a", 'q"', "x,y", "l\r\nm", ""], [""], ["﻿z"]]
        self.assertEqual(parse(call("format", rows)), rows)


ALPHABET = ["a", "b", "Z", "1", " ", ",", ";", '"', "\r", "\n", "\r\n", "é", "日", "﻿", "\t"]          # no NUL: some Pythons' csv refuse it; [lib.std-csv] reads it as a character (Reading)


class Fuzz(unittest.TestCase):
    """A seeded fuzzer against Python's csv module: what csv.writer writes, std:csv reads back; and on random text, whatever std:csv
    accepts, Python reads the same way, and whatever it refuses, Python refuses too unless the text has a quote in an unquoted field
    (which Python accepts as an ordinary character and [lib.std-csv] does not)."""

    def test_python_written_csv_reads_back(self):
        rng = random.Random(4180)
        for trial in range(3000):
            rows = []
            for _ in range(rng.randrange(0, 6)):
                row = ["".join(rng.choice(ALPHABET) for _ in range(rng.randrange(0, 6))) for _ in range(rng.randrange(1, 5))]
                rows.append(row)
            out = io.StringIO()
            quoting = rng.choice((csv.QUOTE_MINIMAL, csv.QUOTE_ALL))
            csv.writer(out, lineterminator="\r\n", quoting=quoting).writerows(rows)    # with "\n" alone Python leaves a bare CR unquoted
            text = out.getvalue()
            want = rows
            if rows and rows[0] and rows[0][0].startswith("﻿"):
                continue                     # a BOM at the very start of the text is removed, by the rule
            self.assertEqual(parse(text), want, (trial, text))
            self.assertEqual(parse(call("format", rows)) if rows else [], rows, (trial, rows))

    def test_random_text_agrees_with_python(self):
        rng = random.Random(6234)
        accepted = refused = 0
        for trial in range(20000):
            text = "".join(rng.choice(ALPHABET + ['"', '"', ","]) for _ in range(rng.randrange(0, 14)))
            delimiter = rng.choice((",", ";"))
            try:
                got = call("parse_with", text, {"delimiter": delimiter})
            except novalang.NovaError:
                refused += 1
                try:
                    python_rows(text, delimiter)
                except csv.Error:
                    continue
                self.assertTrue(self._has_bare_quote(text, delimiter), (trial, text))
                continue
            accepted += 1
            self.assertEqual(got, python_rows(text, delimiter), (trial, text))
        self.assertGreater(accepted, 3000)
        self.assertGreater(refused, 3000)

    @staticmethod
    def _has_bare_quote(text, delimiter):
        """Does a field that does not start with a quote contain one (Python's csv accepts it as data)?"""
        if text.startswith("﻿"):
            text = text[1:]
        i, n, field_start = 0, len(text), True
        quoted = False
        while i < n:
            c = text[i]
            if quoted:
                if c == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        i += 2
                        continue
                    quoted = False
                    field_start = False
                i += 1
                continue
            if c == '"':
                if field_start:
                    quoted = True
                    field_start = False
                else:
                    return True
            elif c in (delimiter, "\r", "\n"):
                field_start = True
            else:
                field_start = False
            i += 1
        return False


class Engines(unittest.TestCase):
    def test_three_engines_read_and_write_the_same(self):
        program = ('import "std:csv" as csv\n'
                   'let rows = csv.parse("\ufeffname,note\\r\\n\\"Smith, J\\",\\"said \\"\\"hi\\"\\"\\"\\r\\nLee,\\"two\\nlines\\"\\r\\n")\n'
                   'print(len(rows), rows[1][0], rows[1][1], len(rows[2][1]))\n'
                   'let recs = csv.records(rows)\n'
                   'print(recs[0]["name"], recs[1]["note"] == "two\\nlines")\n'
                   'print(csv.format_row(["a", "b,c", 3]))\n'
                   'print(csv.parse(csv.format(rows)) == rows)\n'
                   'try { csv.parse("a\\n\\"b") } catch e { print(e) }\n')
        with tempfile.TemporaryDirectory() as folder:
            for name, flags in ENGINES:
                done = nova(flags, program, folder)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                self.assertEqual(done.stdout.splitlines(), ['3 Smith, J said "hi" 9', "Smith, J true", 'a,"b,c",3', "true",
                                                            "csv.parse() found a quoted field that is never closed; it starts on line 2"], name)

    def test_a_file_by_lines_on_three_engines(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "in.csv"), "wb") as handle:
                handle.write(b'\xef\xbb\xbfdate,amount,memo\r\n2026-11-01,12.50,"rent, Nov"\r\n2026-11-02,3.00,"multi\r\nline"\r\n')
            program = ('import "std:files" as files\nimport "std:csv" as csv\n'
                       'let recs = csv.records(csv.parse_lines(files.lines("in.csv")))\n'
                       'print(len(recs), recs[0]["memo"], recs[1]["amount"])\n')
            for name, flags in ENGINES:
                done = nova(flags, program, folder)
                self.assertEqual(done.returncode, 0, (name, done.stderr))
                self.assertEqual(done.stdout.splitlines(), ["2 rent, Nov 3.00"], name)


if __name__ == "__main__":
    unittest.main()
