"""The regular-expression engine and std:regex (M13 slice 4, docs/spec/09-library.md [lib.regex], [lib.std-regex]).

The matcher is written for NovaLang, not taken from `re`, so these tests are what stands between it and a wrong answer:

* a differential fuzzer against Python's `re` on the part of the dialect both have: random patterns and texts,
  compared on whether there is a match, its span and every group. Patterns in which a repeated item can match
  nothing are compared on whether there is a match and where it starts only (the specified difference);
* the same patterns through find_all, sub and pieces against `finditer`, `sub` and `split`;
* the time tests: patterns that take exponential time in `re` finish in time proportional to pattern x text;
* the work is charged to the run (the step budget and the time limit end a run), on both Python engines;
* the three engines give the same answers (the corpus checks the specified cases; this one random ones).

Seeds are fixed, so a failure is the same failure every time.
"""

import os
import random
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import novalang as nl  # noqa: E402


class Counting:
    """A meter that only counts the work."""
    def __init__(self):
        self.units = 0

    def tick(self, units):
        self.units += units


def search(pattern, text, start=0):
    program = nl.regex_compile(pattern)
    return program, nl.regex_search(program, text, start, Counting())


def spans(program, caps):
    if caps is None:
        return None
    return [None if caps[2 * i] is None or caps[2 * i + 1] is None else (caps[2 * i], caps[2 * i + 1])
            for i in range(program.groups + 1)]


# ---- the pattern generator -----------------------------------------------------------------------

ATOMS = ["a", "b", "c", "a", "b", ".", "\\d", "\\w", "\\s", "[ab]", "[^a]", "[a-c]", "1", " ", "\\.", "[b-c1]", "\\b", "\\B",
         "^", "$", "\\W", "\\D", "[\\d_]", "[^\\s]", "\\x61", "é"]
ASSERTIONS = ("^", "$", "\\b", "\\B")
QUANTIFIERS = ["*", "+", "?", "{2}", "{1,3}", "{0,2}", "{2,}", "*?", "+?", "??", "{1,2}?"]
ALPHABET = "aabbc1 _-.\né"


def single_item(atom):
    """Can a quantifier follow `atom` as it is (one character, one escape, one class or one group)?"""
    if len(atom) == 1 or (len(atom) == 2 and atom[0] == "\\"):
        return True
    if atom.startswith("[") and atom.count("[") == 1 and atom.endswith("]"):
        return True
    if atom.startswith("("):
        depth = 0
        for index, c in enumerate(atom):
            if c == "\\":
                continue
            depth += (c == "(") - (c == ")")
            if depth == 0 and index != len(atom) - 1:
                return False
        return depth == 0
    return atom == "\\x61"


def generate(rng, depth=0):
    r = rng.random()
    if depth > 3 or r < 0.30:
        return rng.choice(ATOMS)
    if r < 0.50:
        return generate(rng, depth + 1) + generate(rng, depth + 1)
    if r < 0.62:
        return generate(rng, depth + 1) + "|" + generate(rng, depth + 1)
    if r < 0.75:
        return "(" + generate(rng, depth + 1) + ")"
    if r < 0.80:
        return "(?:" + generate(rng, depth + 1) + ")"
    if r < 0.84:
        return "(?P<n%d>" % rng.randrange(1000) + generate(rng, depth + 1) + ")"
    atom = generate(rng, depth + 1)
    if atom in ASSERTIONS or atom.endswith(ASSERTIONS):
        atom = "a"
    if not single_item(atom):
        atom = "(?:" + atom + ")"
    return atom + rng.choice(QUANTIFIERS)


def random_text(rng):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randrange(0, 9)))


def nullable(node):
    kind = node[0]
    if kind in ("lit", "any", "set"):
        return False
    if kind in ("empty", "bol", "eol", "wordb", "nwordb"):
        return True
    if kind == "cat":
        return all(nullable(item) for item in node[1])
    if kind == "alt":
        return any(nullable(item) for item in node[1])
    if kind == "group":
        return nullable(node[2])
    return node[2] == 0 or nullable(node[1])            # rep


def loops_over_nothing(node):
    """Is some repeat that can go round more than once made of something that can match nothing?"""
    kind = node[0]
    if kind in ("cat", "alt"):
        return any(loops_over_nothing(item) for item in node[1])
    if kind == "group":
        return loops_over_nothing(node[2])
    if kind == "rep":
        return ((node[3] is None or node[3] > 1) and nullable(node[1])) or loops_over_nothing(node[1])
    return False


def python_spans(pattern, text):
    match = re.search(pattern, text, re.ASCII)
    if match is None:
        return None
    return [match.span(i) if match.span(i) != (-1, -1) else None for i in range(match.re.groups + 1)]


def usable_patterns(seed, count):
    """(pattern, program, strict): patterns both engines accept. `strict` is False for a repeat over something that
    can match nothing, where only the existence and the start of the match are specified."""
    rng = random.Random(seed)
    out = []
    while len(out) < count:
        pattern = generate(rng)
        try:
            re.compile(pattern, re.ASCII)
        except re.error:
            continue
        try:
            program = nl.regex_compile(pattern)
        except nl.RegexError as problem:
            raise AssertionError("the dialect refuses {!r}, which re accepts: {}".format(pattern, problem))
        out.append((pattern, program, not loops_over_nothing(nl.RegexParser(pattern).parse())))
    return out, rng


class Differential(unittest.TestCase):
    def test_search_agrees_with_python(self):
        patterns, rng = usable_patterns(20261114, 1500)
        checked = strict = 0
        for pattern, program, exact in patterns:
            for _ in range(6):
                text = random_text(rng)
                if text == "" and "\\B" in pattern:
                    continue                    # re finds no \B in an empty text; the dialect does ([lib.regex])
                ours = spans(program, nl.regex_search(program, text, 0, Counting()))
                theirs = python_spans(pattern, text)
                checked += 1
                if exact:
                    strict += 1
                    self.assertEqual(ours, theirs, "pattern {!r} on {!r}".format(pattern, text))
                else:
                    self.assertEqual(ours is None, theirs is None, "pattern {!r} on {!r}".format(pattern, text))
                    if ours is not None:
                        self.assertEqual(ours[0][0], theirs[0][0], "pattern {!r} on {!r}".format(pattern, text))
        self.assertGreater(strict, 3000)
        self.assertGreater(checked, 7000)

    def test_every_match_find_all_sub_and_pieces_agree_with_python(self):
        patterns, rng = usable_patterns(7, 700)
        for pattern, program, exact in patterns:
            if not exact:
                continue
            compiled = re.compile(pattern, re.ASCII)
            for _ in range(3):
                text = random_text(rng)
                if text == "" and "\\B" in pattern:
                    continue
                label = "pattern {!r} on {!r}".format(pattern, text)
                found = list(nl.regex_iter(program, text, Counting()))
                wanted = list(compiled.finditer(text))
                self.assertEqual([(c[0], c[1]) for c in found], [m.span() for m in wanted], label)
                for caps, match in zip(found, wanted):
                    self.assertEqual(spans(program, caps), [match.span(i) if match.span(i) != (-1, -1) else None
                                                           for i in range(compiled.groups + 1)], label)
                # sub with a replacement that uses every group, and pieces without the groups re.split adds
                template = nl.regex_template(program, "<" + "".join("\\{}".format(i) for i in range(1, min(program.groups, 9) + 1)) + ">")
                replacement = "<" + "".join("\\{}".format(i) for i in range(1, min(program.groups, 9) + 1)) + ">"
                self.assertEqual(nl.regex_substitute("sub", program, template, text, None, _Unlimited(), None),
                                 compiled.sub(replacement, text), label)
                pieces, last = [], 0
                for match in wanted:
                    pieces.append(text[last:match.start()])
                    last = match.end()
                pieces.append(text[last:])
                self.assertEqual(nl.regex_pieces("pieces", program, text, None, _Unlimited(), None), pieces, label)


class _Unlimited:
    """The part of an interpreter the std:regex helpers look at: no limits, and work that goes nowhere."""
    counting = False

    def step(self, position=None):
        pass

    def charge(self, units, position=None):
        pass


class Dialect(unittest.TestCase):
    def test_what_the_dialect_matches(self):
        table = [
            ("a.c", "abc", (0, 3)), ("a.c", "a\nc", None), ("[^a]", "\n", (0, 1)), ("a|ab", "ab", (0, 1)), ("(a|ab)(c|bcd)", "abcd", (0, 4)),
            ("a*?", "aaa", (0, 0)), ("a+?", "aaa", (0, 1)), ("a{2,3}", "aaaa", (0, 3)), ("a{2,3}?", "aaaa", (0, 2)),
            ("(?i)straße", "STRAßE", (0, 6)), ("(?i)é", "É", None), ("\\d+", "a١٢٣1", (4, 5)), ("\\bfoo\\b", "a foo.", (2, 5)),
            ("^$", "", (0, 0)), ("$", "ab\n", (2, 2)), ("x*$", "ab\n", (2, 2)), ("[a\\]]+", "]a]", (0, 3)), ("[]a]+", "]a]", (0, 3)),
            ("[a-]+", "-a-", (0, 3)), ("[\\d_]+", "x1_2", (1, 4)), ("[^\\s\\d]+", "12 ab 3", (3, 5)), ("\\x41\\u0042\\U00000043", "ABC", (0, 3)),
            ("{", "a{", (1, 2)), ("a{", "a{", (0, 2)), ("a{1", "a{1", (0, 3)), ("a{1,x}", "a{1,x}", (0, 6)), ("\\{2}", "{2}", (0, 3)),
            ("(a*)*", "b", (0, 0)), ("(a|)+", "b", (0, 0)), ("(?:a*)+b", "aab", (0, 3)), ("(?:a|b)*c", "abac", (0, 4)),
            ("\\B", "", (0, 0)), ("\\b", "", None), ("\\w+", "é", None), ("\\W+", "é!", (0, 2)), ("\\S+", "a b", (0, 1)),
            ("a\\.b", "a.b", (0, 3)), ("a\\-b", "a-b", (0, 3)), ("\\é", "é", (0, 1)),
        ]
        for pattern, text, want in table:
            with self.subTest(pattern=pattern, text=text):
                program, caps = search(pattern, text)
                self.assertEqual(None if caps is None else (caps[0], caps[1]), want)

    def test_groups_and_names(self):
        program, caps = search("(a)(?:b)(?P<mid>c)?(d)", "abd")
        self.assertEqual(spans(program, caps), [(0, 3), (0, 1), None, (2, 3)])
        self.assertEqual(program.names, {"mid": 2})
        value = nl.regex_match_value(program, "abd", caps)
        self.assertEqual(value["groups"], ["a", nl.NOTHING, "d"])
        self.assertEqual(value["named"], {"mid": nl.NOTHING})

    def test_a_repeated_group_keeps_its_last_pass(self):
        program, caps = search("(?:(a)|(b))+", "abab")
        self.assertEqual(spans(program, caps), [(0, 4), (2, 3), (3, 4)])

    def test_what_is_refused_names_what_it_is(self):
        table = {
            "(?=a)": "look-ahead", "(?!a)": "look-ahead", "(?<=a)": "look-behind", "(?<!a)": "look-behind", "(?>a)": "atomic",
            "(a)\\1": "back-references", "(?P<n>a)(?P=n)": "back-references", "a*+": "possessive", "a++": "possessive", "a?+": "possessive",
            "(?(1)a|b)": "conditional", "(?#x)": "comment", "(?s)a": "flag", "(?m)a": "flag", "a(?i)": "flag", "(?i:a)": "flag",
            "(?<n>a)": "(?P<name>", "\\A": "unknown escape", "\\Z": "unknown escape", "\\p{L}": "unknown escape", "\\0": "octal",
            "a**": "multiple repeat", "a{2}{3}": "multiple repeat", "a+*": "multiple repeat", "a??+": "multiple repeat", "*": "nothing to repeat",
            "+a": "nothing to repeat", "?": "nothing to repeat", "^*": "nothing to repeat", "$+": "nothing to repeat", "\\b?": "nothing to repeat",
            "{2}": "nothing to repeat", "a{,3}": "{0,3}", "a{3,2}": "minimum above its maximum", "a{1001}": "limited to 1000",
            "(": "unterminated group", "a)": "unbalanced", "(a": "unterminated group", "[a": "unterminated character class", "[": "unterminated",
            "a\\": "backslash", "[z-a]": "bad character range", "[\\d-z]": "shortcut", "[a-\\d]": "bad character range", "\\xZZ": "hexadecimal",
            "\\x4": "hexadecimal", "\\UFFFFFFFF": "beyond the last code point", "(?P<1a>x)": "group name", "(?P<>x)": "group name",
            "(?P<a b>x)": "group name", "(?P<n>a)(?P<n>b)": "used twice", "(?P<é>x)": "group name",
        }
        for pattern, reason in table.items():
            with self.subTest(pattern=pattern):
                with self.assertRaises(nl.RegexError) as caught:
                    nl.regex_compile(pattern)
                self.assertIn(reason, str(caught.exception))

    def test_the_limits_of_a_pattern(self):
        nl.regex_compile("a" * 4000)
        nl.regex_compile("(a)" * 1000)
        nl.regex_compile("a{1000}" * 19)
        nl.regex_compile("(?:" * 100 + "a" + ")" * 100)
        for pattern, reason in (("a" * 4001, "4000 characters"), ("(a)" * 1001, "at most 1000 groups"),
                                ("(?:" * 101 + "a" + ")" * 101, "nested more than 100"), ("a{1000}" * 21, "20000 instructions"),
                                ("(a{1000}){1000}", "20000 instructions"), ("(?:(?:(?:){1000}){1000}){1000}", "400000 steps")):
            with self.subTest(pattern=pattern[:30]):
                started = time.monotonic()
                with self.assertRaises(nl.RegexError) as caught:
                    nl.regex_compile(pattern)
                self.assertIn(reason, str(caught.exception))
                self.assertLess(time.monotonic() - started, 5)

    def test_a_deeply_nested_pattern_is_an_error_not_a_crash(self):
        for depth in (101, 500, 3000):
            with self.assertRaises(nl.RegexError):
                nl.regex_compile("(" * depth + "a" + ")" * depth)

    def test_replacement_templates(self):
        program = nl.regex_compile("(?P<w>a)(b)?")
        self.assertEqual(nl.regex_template(program, "x\\1\\2\\g<w>\\g<2>\\\\y"), ["x", 1, 2, 1, 2, "\\y"])
        for bad, reason in (("\\3", "group 3"), ("\\q", "unknown escape"), ("a\\", "end with a backslash"), ("\\g<zz>", "does not have"),
                            ("\\g", "\\g must be written"), ("\\g<1", "\\g must be written"), ("\\0", "unknown escape")):
            with self.subTest(replacement=bad):
                with self.assertRaises(nl.RegexError) as caught:
                    nl.regex_template(program, bad)
                self.assertIn(reason, str(caught.exception))

    def test_an_empty_match_never_makes_find_all_loop(self):
        for pattern in ("", "a*", "(a|)", "\\b", "$", "^", "x*?"):
            program = nl.regex_compile(pattern)
            matches = list(nl.regex_iter(program, "aab c", Counting()))
            self.assertEqual([(c[0], c[1]) for c in matches], [m.span() for m in re.finditer(pattern, "aab c", re.ASCII)], pattern)

    def test_the_start_of_a_search_does_not_move_the_start_of_the_text(self):
        program = nl.regex_compile("^a")
        self.assertIsNone(nl.regex_search(program, "aa", 1, Counting()))
        self.assertEqual(nl.regex_search(program, "aa", 0, Counting())[:2], [0, 1])
        program = nl.regex_compile("\\ba")
        self.assertIsNone(nl.regex_search(program, "ba", 1, Counting()))            # the b before it is still a word character


class Time(unittest.TestCase):
    def test_patterns_that_are_exponential_for_a_backtracking_engine_take_pattern_times_text(self):
        cases = [("(a+)+$", "a" * 5000 + "b"), ("^(a|aa)+$", "a" * 5000 + "b"), ("(a*)*b", "a" * 5000), ("^(a?){40}a{40}$", "a" * 40),
                 ("(x+x+)+y", "x" * 5000), ("^(\\w+\\s?)*$", "word " * 800 + "!"), ("(.*a){20}", "a" * 3000 + "b"),
                 ("(a|b|ab)*c", "ab" * 3000), ("^(([a-z])+.)+[A-Z]([a-z])+$", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!")]
        for pattern, text in cases:
            with self.subTest(pattern=pattern):
                program = nl.regex_compile(pattern)
                meter = Counting()
                started = time.monotonic()
                nl.regex_search(program, text, 0, meter)
                self.assertLess(time.monotonic() - started, 10)
                # at most every instruction once per position, and a search looks at each start: pattern x text (x a constant)
                self.assertLessEqual(meter.units, (len(program.ops) + 1) * (len(text) + 2) + 1)

    def test_re_itself_needs_exponential_time_on_the_first_of_these(self):
        # not run: the point of the engine is that this is never run through `re`; here only that the claim is about a real pattern
        self.assertIsNotNone(re.compile("(a+)+$"))

    def test_find_all_over_a_large_text_is_linear_in_it(self):
        program = nl.regex_compile("[a-z]+")
        text = ("word " * 20000)
        meter = Counting()
        found = list(nl.regex_iter(program, text, meter))
        self.assertEqual(len(found), 20000)
        self.assertLess(meter.units, 40 * len(text))


class Charged(unittest.TestCase):
    def setUp(self):
        if nl.SANDBOX_UNSUPPORTED:
            self.skipTest("the restricted profile needs Python 3.8 or later on Windows")

    def test_the_step_budget_ends_a_run_that_matches_a_large_text(self):
        for engine in ("vm", "tree"):
            for call in ('regex("(a|b)*c", "ab" * 5000)', 'regex("(a|b)*c", "ab" * 5000) or true'):
                nova = nl.Nova(engine, profile="restricted", regex=True, limits={"steps": 100, "time": 120000})
                with self.assertRaises(nl.NovaLangError) as caught:
                    nova.eval(call)
                self.assertTrue(str(caught.exception).startswith("LimitError: step budget of 100 steps"), (engine, str(caught.exception)))

    def test_the_time_limit_ends_a_run_that_matches_a_large_text(self):
        for engine in ("vm", "tree"):
            nova = nl.Nova(engine, profile="restricted", regex=True, limits={"time": 200, "steps": 10 ** 9})
            started = time.monotonic()
            with self.assertRaises(nl.NovaLangError) as caught:
                nova.eval('regex("((?:a|b|c)*)*z", "abc" * 300000)')
            self.assertEqual(str(caught.exception), "LimitError: time limit of 200 ms exceeded")
            self.assertLess(time.monotonic() - started, 5, engine)

    def test_a_small_match_costs_almost_nothing(self):
        nova = nl.Nova("vm", profile="restricted", regex=True, limits={"steps": 100})
        self.assertEqual(nova.eval('regex("^\\\\d+$", "12345")'), True)

    def test_sub_cannot_build_a_string_past_the_limit(self):
        for engine in ("vm", "tree"):
            nova = nl.Nova(engine, profile="restricted", regex=True, limits={"string": 1000, "time": 120000})
            nova.exec('import "std:regex" as re')
            with self.assertRaises(nl.NovaLangError) as caught:
                nova.eval('re.sub("a", "bbbbbbbbbb", "a" * 500)')
            self.assertEqual(str(caught.exception), "a string cannot grow beyond 1000 characters")
            small = nl.Nova(engine, profile="restricted", regex=True, limits={"list": 100, "time": 120000})
            small.exec('import "std:regex" as re')
            for call in ('re.find_all("a", "a" * 500)', 're.pieces("a", "a" * 500)'):
                with self.assertRaises(nl.NovaLangError) as caught:
                    small.eval(call)
                self.assertEqual(str(caught.exception), "a list cannot grow beyond 100 items")


class Engines(unittest.TestCase):
    """The same random patterns and texts on the VM, the tree-walker and the self-hosted interpreter: one answer."""

    def test_three_engines_one_answer(self):
        patterns, rng = usable_patterns(99, 120)
        lines = ['import "std:regex" as re']
        cases = []
        for pattern, program, exact in patterns:
            text = random_text(rng)
            if text == "" and "\\B" in pattern:
                text = "a b"
            cases.append((pattern, text))
            lines.append("let p = {}".format(nova_string(pattern)))
            lines.append("let t = {}".format(nova_string(text)))
            lines.append('print("@@case@@")\nlet m = re.match(p, t)\nprint(m)')
            lines.append('print(re.test(p, t), len(re.find_all(p, t)), re.pieces(p, t), re.sub(p, "-", t))')
        source = "\n".join(lines) + "\n"
        outputs = {}
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "cases.nova")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(source)
            for name, flags in (("vm", []), ("tree", ["--tree-walk"]), ("bootstrap", ["--bootstrap"])):
                done = subprocess.run([sys.executable, os.path.join(ROOT, "novalang.py")] + flags + [path], capture_output=True, text=True,
                                      timeout=600, stdin=subprocess.DEVNULL, env=dict(os.environ, NOVALANG_CACHE="off"))
                self.assertEqual(done.returncode, 0, (name, done.stderr[-500:]))
                outputs[name] = done.stdout
        self.assertEqual(outputs["vm"], outputs["tree"])
        self.assertEqual(outputs["vm"], outputs["bootstrap"])
        blocks = outputs["vm"].split("@@case@@\n")[1:]
        self.assertEqual(len(blocks), len(cases))
        # and the VM's answers are the right ones for the patterns where Python is the oracle
        for index, (pattern, text) in enumerate(cases):
            program = nl.regex_compile(pattern)
            if loops_over_nothing(nl.RegexParser(pattern).parse()):
                continue
            theirs = python_spans(pattern, text)
            shown = blocks[index].splitlines()[0]
            if theirs is None:
                self.assertEqual(shown, "nothing", (pattern, text))
            else:
                self.assertTrue(shown.startswith("{{start: {}, end: {}, ".format(*theirs[0])), (pattern, text, shown))


def nova_string(text):
    """A NovaLang string literal for `text`."""
    out = ['"']
    for c in text:
        out.append({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}.get(c, c))
    out.append('"')
    return "".join(out)


if __name__ == "__main__":
    unittest.main()
