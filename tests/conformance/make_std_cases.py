"""Writes tests/conformance/cases/std.json (M13 slice 1). Expected outputs are written from the spec text, then checked on every engine."""
import json
import os
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + "/"
cases = []

def case(name, spec, source, output, error="", error_line=None, exit=0, profile="core", sandbox=None, extra=None):
    c = {"name": name, "spec": spec, "profile": profile, "source": source, "output": output,
         "error": error, "error_line": error_line, "exit": exit, "host_calls": []}
    if sandbox is not None:
        c["sandbox"] = sandbox
    if extra:
        c.update(extra)
    cases.append(c)

IMP = 'import "std:text" as text\n'
case("std-import-binds-the-name-after-the-prefix", ["mod.std", "mod.import"],
     'import "std:text"\nprint(type(text), sorted(keys(text)))',
     ['dict ["basename", "ends_with", "find", "find_from", "is_number", "parse_number", "splitext", "starts_with"]'])
case("std-import-as-and-with-forms", ["mod.std", "mod.import"],
     'import "std:text" as t\nprint(t.find("hello", "ll"))\nimport "std:text" with find, ends_with\nprint(find("abc", "c"), ends_with("abc", "bc"))',
     ["2", "2 true"])
case("std-unknown-module-is-an-import-error", ["mod.std"],
     'import "std:nope" as n',
     [], error='ImportError: there is no standard module "std:nope" - the standard modules are: std:decimal, std:format, std:math, std:text',
     error_line=1, exit=1,
     extra={"error_like": '^ImportError: there is no standard module "std:nope" - the standard modules are: std:[a-z_]+(, std:[a-z_]+)*$'})
case("std-name-is-never-a-path", ["mod.std"],
     'try { import "std:../text" as t } catch e { print(e[0:57]) }\ntry { import "std:" as t } catch e { print(e[0:50]) }\ntry { import "std:text/../text" as t } catch e { print(e[0:58]) }',
     ['ImportError: there is no standard module "std:../text" - ', 'ImportError: there is no standard module "std:" - ',
      'ImportError: there is no standard module "std:text/../text'])
case("std-module-is-one-shared-module", ["mod.std", "mod.cache"],
     'import "std:text" as a\nimport "std:text" as b\na.marker = 7\nprint(b.marker)',
     ["7"])
case("std-adds-no-global-name", ["mod.std", "scope.reserved"],
     IMP + 'try { print(find("a", "a")) } catch e { print(e) }\nlet starts_with = 3\nprint(starts_with)',
     ["undefined name 'find'", "3"])
case("std-needs-no-import-grant-in-restricted", ["mod.std", "sbx.profiles"],
     IMP + 'print(text.find("restricted", "ric"), text.basename("a/b.txt"))',
     ["4 b.txt"], profile="sandbox", sandbox={"profile": "restricted"})
case("std-runs-under-the-importers-limits", ["mod.std", "sbx.limits"],
     IMP + 'let i = 0\nwhile i < 100 {\n  text.find("hello", "l")\n  i = i + 1\n}\nprint(i)',
     [], error="LimitError: step budget of 500 steps exhausted - is there a loop that never ends?", exit=1,
     profile="sandbox", sandbox={"profile": "restricted", "limits": {"steps": 500, "time": 120000}},
     extra={"error_like": "^LimitError: step budget of 500 steps exhausted - is there a loop that never ends\\?$"})

case("std-text-find", ["lib.std-text"],
     IMP + 'print(text.find("hello", "ll"), text.find("hello", "he"), text.find("hello", "x"), text.find("hello", ""), text.find("", ""), text.find("aXbX", "X"))\nprint(text.find("héllo", "l"))',
     ["2 0 -1 0 0 1", "2"])
case("std-text-find-from", ["lib.std-text"],
     IMP + 'print(text.find_from("abcabc", "b", 2), text.find_from("abc", "c", -5), text.find_from("abc", "", 99), text.find_from("abc", "a", 1), text.find_from("abc", "a", 0))',
     ["4 2 3 -1 0"])
case("std-text-starts-and-ends-with", ["lib.std-text"],
     IMP + 'print(text.starts_with("hello", "he"), text.starts_with("he", "hello"), text.starts_with("a", ""), text.starts_with("", ""), text.starts_with("hello", "lo"))\nprint(text.ends_with("hello", "llo"), text.ends_with("lo", "hello"), text.ends_with("a", ""), text.ends_with("", ""), text.ends_with("hello", "he"))',
     ["true false true true false", "true false true true false"])
case("std-text-is-number-and-parse-number", ["lib.std-text"],
     IMP + 'print(text.is_number("12"), text.is_number("-3.5"), text.is_number("abc"), text.is_number(""))\nprint(text.parse_number("7", 0), text.parse_number("x", -1), text.parse_number("2.5", 0))\nprint(text.is_number("12") == (num("12") == 12))',
     ["true true false false", "7 -1 2.5", "true"])
case("std-text-basename", ["lib.std-text"],
     IMP + 'print(text.basename("a/b/c.txt"), text.basename("c.txt"), text.basename("a\\\\b.txt"), text.basename("a/b/") == "", text.basename("") == "")',
     ["c.txt c.txt b.txt true true"])
case("std-text-splitext", ["lib.std-text"],
     IMP + 'print(text.splitext("a/b/c.tar.gz"))\nprint(text.splitext(".bashrc"), text.splitext("a.b/c"), text.splitext("..x"), text.splitext("x."))\nprint(text.splitext("noext"), text.splitext("a/b.c/d.e"))',
     ['["a/b/c.tar", ".gz"]', '[".bashrc", ""] ["a.b/c", ""] ["..x", ""] ["x", "."]', '["noext", ""] ["a/b.c/d", ".e"]'])
case("std-text-wrong-argument-types", ["lib.std-text"],
     IMP + 'try { text.find(5, "a") } catch e { print(e) }\ntry { text.find("a", 5) } catch e { print(e) }\ntry { text.starts_with([], "a") } catch e { print(e) }\ntry { text.is_number(5) } catch e { print(e) }\ntry { text.basename(true) } catch e { print(e) }\ntry { text.find_from("a", "a", 1.5) } catch e { print(e) }\ntry { text.find_from("a", "a", "1") } catch e { print(e) }',
     ["the text for text.find() needs a string, but got number",
      "the target for text.find() needs a string, but got number",
      "the text for text.starts_with() needs a string, but got list",
      "the text for text.is_number() needs a string, but got number",
      "the path for text.basename() needs a string, but got boolean",
      "the start for text.find_from() needs a whole number",
      "the start for text.find_from() needs a whole number"])


# ---- std:decimal -------------------------------------------------------------------------------
DEC = 'import "std:decimal" as dec\ndef show(a) { return dec.to_string(a) }\n'
import decimal as _d
case("std-decimal-parse-and-to-string", ["lib.std-decimal"],
     DEC + 'for t in ["1250.50", ".5", "7.", "+12", "-0.00", "007.10", "-3", "0", "123456789012345678901234567890.5"] {\n  print(t, show(dec.parse(t)), dec.scale(dec.parse(t)))\n}',
     ["1250.50 1250.50 2", ".5 0.5 1", "7. 7 0", "+12 12 0", "-0.00 0.00 2", "007.10 7.10 2", "-3 -3 0", "0 0 0",
      "123456789012345678901234567890.5 123456789012345678901234567890.5 1"])
case("std-decimal-parse-refuses-what-is-not-a-plain-decimal", ["lib.std-decimal"],
     DEC + 'for t in ["1e5", "", "1.2.3", " 1", "1 ", "abc", "-", ".", "1,000", "--1"] {\n  try { dec.parse(t) } catch e { print(e) }\n}\ntry { dec.parse(5) } catch e { print(e) }',
     ['decimal.parse() cannot read a decimal from "1e5"', 'decimal.parse() cannot read a decimal from ""', 'decimal.parse() cannot read a decimal from "1.2.3"',
      'decimal.parse() cannot read a decimal from " 1"', 'decimal.parse() cannot read a decimal from "1 "', 'decimal.parse() cannot read a decimal from "abc"',
      'decimal.parse() cannot read a decimal from "-"', 'decimal.parse() cannot read a decimal from "."', 'decimal.parse() cannot read a decimal from "1,000"',
      'decimal.parse() cannot read a decimal from "--1"', "decimal.parse() needs a string, but got number"])
case("std-decimal-try-parse-gives-nothing", ["lib.std-decimal"],
     DEC + 'print(dec.try_parse("abc"), show(dec.try_parse("1.50")))\nprint(dec.try_parse("1e5") == dec.try_parse(""))',
     ["nothing 1.50", "true"])
case("std-decimal-add-sub-mul-are-exact", ["lib.std-decimal"],
     DEC + 'print(show(dec.add(dec.parse("0.1"), dec.parse("0.2"))), 0.1 + 0.2)\nprint(show(dec.mul(dec.parse("19.99"), dec.from_int(3))))\nprint(show(dec.sub(dec.parse("1"), dec.parse("0.005"))))\nprint(show(dec.mul(dec.parse("1.10"), dec.parse("2.5"))), dec.scale(dec.mul(dec.parse("1.10"), dec.parse("2.5"))))\nprint(show(dec.add(dec.parse("1.5"), dec.parse("-1.50"))))',
     ["0.3 0.30000000000000004", "59.97", "0.995", "2.750 3", "0.00"])
big = _d.Decimal("123456789012345678901234567890.123456789")
case("std-decimal-arithmetic-is-exact-beyond-a-float", ["lib.std-decimal"],
     DEC + 'let big = dec.parse("123456789012345678901234567890.123456789")\nprint(show(dec.mul(big, big)))\nprint(show(dec.sub(dec.add(big, dec.parse("1")), big)))',
     [format(_d.Context(prec=500).multiply(big, big), "f"), "1.000000000"])
case("std-decimal-div-needs-places-and-a-mode", ["lib.std-decimal"],
     DEC + 'print(show(dec.div(dec.parse("1"), dec.parse("3"), 5, "down")), show(dec.div(dec.parse("2"), dec.parse("3"), 5, "half_even")))\nprint(show(dec.div(dec.parse("-1"), dec.parse("-8"), 2, "half_even")), show(dec.div(dec.parse("10"), dec.parse("-4"), 0, "half_up")))\nprint(show(dec.div(dec.parse("7"), dec.parse("2"), 1, "floor")), show(dec.div(dec.parse("-7"), dec.parse("2"), 0, "ceiling")))\ntry { dec.div(dec.parse("1"), dec.parse("0.00"), 2, "down") } catch e { print(e) }\ntry { dec.div(dec.parse("1"), dec.parse("3"), 2) } catch e { print(e) }\ntry { dec.div(dec.parse("1"), dec.parse("3"), -1, "down") } catch e { print(e) }\ntry { dec.div(dec.parse("1"), dec.parse("3"), 1.5, "down") } catch e { print(e) }',
     ["0.33333 0.66667", "0.12 -3", "3.5 -3", "decimal.div() cannot divide by zero", "div() expects 4 argument(s) but got 3",
      "decimal.div() needs places to be a whole number from 0 to 1000", "decimal.div() needs places to be a whole number from 0 to 1000"])
rows = []
for mode in ["half_even", "half_up", "half_down", "up", "down", "floor", "ceiling"]:
    m = {"half_even": _d.ROUND_HALF_EVEN, "half_up": _d.ROUND_HALF_UP, "half_down": _d.ROUND_HALF_DOWN, "up": _d.ROUND_UP,
         "down": _d.ROUND_DOWN, "floor": _d.ROUND_FLOOR, "ceiling": _d.ROUND_CEILING}[mode]
    def q(v, p):
        out = format(_d.Decimal(v).quantize(_d.Decimal(1).scaleb(-p), rounding=m, context=_d.Context(prec=100)), "f")
        return out
    rows.append("{} {} {} {} {} {}".format(mode, q("2.5", 0), q("3.5", 0), q("-2.5", 0), q("2.51", 1), q("-2.51", 1)))
case("std-decimal-quantize-by-every-mode", ["lib.std-decimal"],
     DEC + 'for mode in ["half_even", "half_up", "half_down", "up", "down", "floor", "ceiling"] {\n  print(mode, show(dec.quantize(dec.parse("2.5"), 0, mode)), show(dec.quantize(dec.parse("3.5"), 0, mode)), show(dec.quantize(dec.parse("-2.5"), 0, mode)), show(dec.quantize(dec.parse("2.51"), 1, mode)), show(dec.quantize(dec.parse("-2.51"), 1, mode)))\n}',
     rows)
case("std-decimal-quantize-pads-without-rounding", ["lib.std-decimal"],
     DEC + 'print(show(dec.quantize(dec.parse("1.5"), 3, "down")), show(dec.quantize(dec.parse("7"), 2, "up")), show(dec.quantize(dec.parse("0.005"), 2, "half_even")), show(dec.quantize(dec.parse("0.015"), 2, "half_even")))',
     ["1.500 7.00 0.00 0.02"])
case("std-decimal-from-int-and-from-float", ["lib.std-decimal"],
     DEC + 'print(show(dec.from_int(5)), show(dec.from_int(-12)))\nprint(show(dec.from_float(0.1, 2, "half_even")), show(dec.from_float(2.675, 2, "half_even")), show(dec.from_float(0.0000001, 8, "half_up")), show(dec.from_float(5, 2, "down")), show(dec.from_float(-1.005, 2, "half_up")))\ntry { dec.from_int(1.5) } catch e { print(e) }\ntry { dec.from_float("x", 2, "down") } catch e { print(e) }',
     ["5 -12", "0.10 2.68 0.00000010 5.00 -1.01", "decimal.from_int() needs a whole number, but got 1.5", "decimal.from_float() needs a number, but got string"])
case("std-decimal-compare-by-value-not-by-list", ["lib.std-decimal"],
     DEC + 'let a = dec.parse("1.5")\nlet b = dec.parse("1.50")\nprint(a == b, dec.eq(a, b), dec.cmp(a, b), dec.cmp(dec.parse("2"), dec.parse("10")), dec.cmp(dec.parse("-1"), dec.parse("-2")))\nprint(dec.lt(dec.parse("-1"), dec.parse("0")), dec.le(dec.parse("1"), dec.parse("1.0")), dec.lt(a, b), dec.le(b, a))',
     ["false true 0 -1 1", "true true false true"])
case("std-decimal-sign-negate-absolute-total", ["lib.std-decimal"],
     DEC + 'print(dec.sign(dec.parse("-3")), dec.sign(dec.parse("0.00")), dec.sign(dec.parse("0.1")))\nprint(show(dec.negate(dec.parse("0.0"))), show(dec.negate(dec.parse("1.5"))), show(dec.absolute(dec.parse("-3.0"))))\nprint(show(dec.total([dec.parse("1.10"), dec.parse("2.205"), dec.parse("-0.5")])), show(dec.total([])))\ntry { dec.total(5) } catch e { print(e) }',
     ["-1 0 1", "0.0 -1.5 3.0", "2.805 0", "decimal.total() needs a list, but got number"])
case("std-decimal-to-int-and-to-float", ["lib.std-decimal"],
     DEC + 'print(dec.to_int(dec.parse("-7.5"), "half_even"), dec.to_int(dec.parse("7.5"), "half_even"), dec.to_int(dec.parse("7.5"), "down"), dec.to_int(dec.parse("-7.5"), "floor"), dec.to_int(dec.parse("12"), "up"))\nprint(dec.to_float(dec.parse("1.50")), dec.to_float(dec.parse("-0.125")), dec.to_float(dec.parse("100")) == 100)',
     ["-8 8 7 -8 12", "1.5 -0.125 true"])
case("std-decimal-refuses-a-list-that-is-not-a-decimal", ["lib.std-decimal"],
     DEC + 'try { dec.add([1.5, 2], dec.parse("1")) } catch e { print(e) }\ntry { dec.add(5, dec.parse("1")) } catch e { print(e) }\ntry { dec.sub(dec.parse("1"), [1, 2, 3]) } catch e { print(e) }\ntry { dec.mul([1, 1001], dec.parse("1")) } catch e { print(e) }\ntry { dec.cmp(dec.parse("1"), [1, -1]) } catch e { print(e) }\ntry { dec.to_string(true) } catch e { print(e) }\nprint(dec.is_decimal([1999, 2]), dec.is_decimal([1.5, 2]), dec.is_decimal("1.5"), dec.is_decimal([1, 1001]), dec.is_decimal(dec.parse("1")))',
     ["decimal.add() needs a decimal for the first argument, but got [1.5, 2]", "decimal.add() needs a decimal for the first argument, but got 5",
      "decimal.sub() needs a decimal for the second argument, but got [1, 2, 3]", "decimal.mul() needs a decimal for the first argument, but got [1, 1001]",
      "decimal.cmp() needs a decimal for the second argument, but got [1, -1]", "decimal.to_string() needs a decimal for its argument, but got true",
      "true false false false true"])
case("std-decimal-scale-has-a-limit", ["lib.std-decimal"],
     DEC + 'let tiny = dec.parse("0." + 600 * "0" + "1")\nprint(dec.scale(tiny), dec.scale(dec.add(tiny, tiny)))\ntry { dec.mul(tiny, tiny) } catch e { print(e) }\ntry { dec.parse("0." + 1001 * "0") } catch e { print(e) }',
     ["601 601", "decimal.mul() result would have more than 1000 digits after the point",
      'decimal.parse() cannot read a decimal from "0.' + "0" * 1001 + '"'])
case("std-decimal-exports", ["lib.std-decimal", "mod.std"],
     'import "std:decimal" as dec\nprint(join(sorted(keys(dec)), " "))',
     ["absolute add cmp div eq from_float from_int is_decimal le lt mul negate parse quantize scale sign sub to_float to_int to_string total try_parse"])
case("std-decimal-needs-no-grant-in-restricted", ["lib.std-decimal", "sbx.profiles"],
     DEC + 'print(show(dec.div(dec.parse("100"), dec.parse("3"), 2, "half_even")))',
     ["33.33"], profile="sandbox", sandbox={"profile": "restricted"})

# ---- std:math ------------------------------------------------------------------------------------
MATH = 'import "std:math" as math\n'
case("std-math-trunc-and-divmod", ["lib.std-math"],
     MATH + 'print(math.trunc(-2.7), math.trunc(2.7), math.trunc(-3), math.trunc(0.5), math.trunc(-0.5))\nprint(math.divmod(-7, 2), math.divmod(7, -2), math.divmod(7, 2), math.divmod(7.5, 2))\ntry { math.divmod(1, 0) } catch e { print(e) }\ntry { math.trunc("a") } catch e { print(e) }\ntry { math.divmod(1, "b") } catch e { print(e) }',
     ["-2 2 -3 0 0", "[-4, 1] [-4, -1] [3, 1] [3, 1.5]", "integer division by zero",
      "the number for math.trunc() needs a number, but got string", "the divisor for math.divmod() needs a number, but got string"])
case("std-math-round-half-reads-the-text-of-the-number", ["lib.std-math"],
     MATH + 'print(math.round_half(2.675, 2, "half_up"), round(2.675, 2), math.round_half(2.5, 0, "half_even"), math.round_half(-2.5, 0, "half_up"), math.round_half(1234.5678, 2, "down"))\ntry { math.round_half(1.5, 0, "nearest") } catch e { print(e) }\ntry { math.round_half("x", 0, "down") } catch e { print(e) }',
     ["2.68 2.67 2 -3 1234.56", "decimal.from_float() needs a rounding mode: half_even, half_up, half_down, up, down, floor, ceiling",
      "the number for math.round_half() needs a number, but got string"])
case("std-math-exp", ["lib.std-math"],
     MATH + 'print(math.exp(0), math.exp(1) == pow(E, 1), math.exp(2) == pow(E, 2))\ntry { math.exp("x") } catch e { print(e) }',
     ["1 true true", "the exponent for math.exp() needs a number, but got string"])
case("std-math-exports", ["lib.std-math", "mod.std"],
     'import "std:math" as math\nprint(join(sorted(keys(math)), " "))', ["divmod exp round_half trunc"])

# ---- std:format ----------------------------------------------------------------------------------
FMT = 'import "std:format" as fmt\n'
case("std-format-fixed", ["lib.std-format"],
     FMT + 'print(fmt.fixed(1234567.891, 2), fmt.fixed(5, 2), fmt.fixed(0.0000001, 8), fmt.fixed(2.5, 0), fmt.fixed(3.5, 0), fmt.fixed(-0.001, 2), fmt.fixed(-1.005, 2))\nprint(fmt.fixed(0.5, 3), fmt.fixed(100, 0), fmt.fixed(1.25, 1), fmt.fixed(1.35, 1))\ntry { fmt.fixed("1", 2) } catch e { print(e) }\ntry { fmt.fixed(1, -1) } catch e { print(e) }',
     ["1234567.89 5.00 0.00000010 2 4 0.00 -1.00", "0.500 100 1.2 1.4", "the number for format.fixed() needs a number, but got string",
      "decimal.from_float() needs places to be a whole number from 0 to 1000"])
case("std-format-grouped", ["lib.std-format"],
     FMT + 'print(fmt.grouped("1234567.5", ","), fmt.grouped("-1234", "_"), fmt.grouped("123", ","), fmt.grouped("1234567", ""), fmt.grouped("+1000", ","), fmt.grouped(".5", ","))\nprint(fmt.grouped(fmt.fixed(1234567.891, 2), ","), fmt.grouped("1000000", ", "))\ntry { fmt.grouped("abc", ",") } catch e { print(e) }\ntry { fmt.grouped(5, ",") } catch e { print(e) }',
     ["1,234,567.5 -1_234 123 1234567 +1,000 .5", "1,234,567.89 1, 000, 000", 'format.grouped() needs the text of a number such as "1234.5", but got "abc"',
      "format.grouped() needs the text of a number and a separator string"])
case("std-format-pad-zero", ["lib.std-format"],
     FMT + 'print(fmt.pad_zero(7, 3), fmt.pad_zero(-5, 4), fmt.pad_zero(12345, 3), fmt.pad_zero(0, 1), fmt.pad_zero(0, 0))\ntry { fmt.pad_zero(1.5, 3) } catch e { print(e) }\ntry { fmt.pad_zero(1, -1) } catch e { print(e) }',
     ["007 -005 12345 0 0", "the number for format.pad_zero() needs a whole number, but got 1.5", "the width for format.pad_zero() needs a whole number from 0 to 100000"])
case("std-format-exports", ["lib.std-format", "mod.std"],
     'import "std:format" as fmt\nprint(join(sorted(keys(fmt)), " "))', ["fixed grouped pad_zero"])
case("std-format-leaves-str-of-a-float-alone", ["lib.std-format", "lib.std-decimal"],
     FMT + 'print(str(0.0000001), fmt.fixed(0.0000001, 8))\nprint(num(fmt.fixed(0.0000001, 8)) == 0.0000001)',
     ["1e-07 0.00000010", "true"])

json.dump  # (kept for clarity)
doc = {"area": "std", "version": 1, "cases": cases}
open(ROOT + "tests/conformance/cases/std.json", "w", encoding="utf-8").write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
print(len(cases), "cases")
