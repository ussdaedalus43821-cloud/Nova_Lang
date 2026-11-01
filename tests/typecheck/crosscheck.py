"""
crosscheck.py - holds nova-typecheck's rules to the real interpreter.

The checker's rules are written by hand, so they can drift from what the
interpreter actually does. This module runs every rule against the real
thing on sample values of each type, and demands two things:

    accepted  => no sample of those types fails at run time, and the result
                 has the type the checker said it would;
    rejected  => at least one sample of those types fails at run time.

So the checker never raises a false alarm on these constructs, and never
waves through something that can blow up because of its types.

check(line) is called by tests/run_all.py.
"""

import itertools
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

import importlib.util  # noqa: E402

import nova_ast  # noqa: E402
import novalang as nl  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "nova_typecheck", os.path.join(ROOT, "tools", "nova-typecheck.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)

SIMPLE = [tc.INT, tc.FLOAT, tc.STRING, tc.BOOL, tc.LIST, tc.DICT]

# Values that exercise each type's edge: a negative and a positive whole
# number, a fractional and a whole-valued float. Containers are sized and
# keyed so that indexing, slicing and field access succeed whenever their
# types are right - a failure must be about types, never about data.
SAMPLES = {
    tc.INT: [1, -1],
    tc.FLOAT: [1.5, 1.0],
    tc.STRING: ["abcd"],
    tc.BOOL: [True, False],
    tc.LIST: [[1, 2, 3]],
    tc.DICT: [{"abcd": 1, "k": 2}],
}

# (template, names) - `a` and `b` are bound to sample values. Every
# construct the checker has a rule for appears here, except throw (which
# always fails at run time, by design) and calls (covered by built-ins).
EXPRESSIONS = [
    ("a + b", "ab"), ("a - b", "ab"), ("a * b", "ab"), ("a / b", "ab"),
    ("a // b", "ab"), ("a % b", "ab"),
    ("a == b", "ab"), ("a != b", "ab"), ("a < b", "ab"), ("a >= b", "ab"),
    ("a in b", "ab"),
    ("-a", "a"), ("+a", "a"), ("not a", "a"), ("a and b", "ab"), ("a or b", "ab"),
    ("a[b]", "ab"), ("a[b:]", "ab"), ("a[:b]", "ab"), ("a.k", "a"),
]
STATEMENTS = [
    ("if a { }", "a"), ("while a { break }", "a"),
    ("a[b] = 1", "ab"), ("a.k = 1", "a"), ("delete a[b]", "ab"),
    ("for i = a to b { break }", "ab"), ("for x in a { break }", "a"),
]


def runtime_type(value):
    if isinstance(value, bool):
        return tc.BOOL
    if nl.is_number(value):
        return tc.INT if float(value).is_integer() else tc.FLOAT
    for python_type, nova_type in ((str, tc.STRING), (list, tc.LIST), (dict, tc.DICT)):
        if isinstance(value, python_type):
            return nova_type
    return tc.NOTHING


def checker_verdict(source, types):
    """(findings, type of the last expression) for `source`, with each name
    in `types` bound to a variable of that declared type."""
    parsed = nova_ast.parse(source)
    checker = tc.Checker(parsed, tc.Program(), None, ROOT, contracts_only=False)
    for name, kind in types.items():
        checker.bind(name, 0, "var").declared = kind
    result = None
    for statement in parsed.tree.statements:
        result = checker.visit(statement)
    return checker.findings, result


def runtime_outcomes(source, values):
    """Run `source` once per combination of sample values; yields
    (values, result value or None, error message or None)."""
    for combo in itertools.product(*values.values()):
        interpreter = nl.Interpreter()
        for name, value in zip(values, combo):
            interpreter.globals.define(name, copy(value))
        try:
            _, result = nl.run(source, interpreter)
            yield combo, result, None
        except nl.NovaError as error:
            yield combo, None, error.message


def copy(value):
    if isinstance(value, list):
        return [copy(item) for item in value]
    if isinstance(value, dict):
        return {key: copy(item) for key, item in value.items()}
    return value


# Run-time errors about a value that is the right type but the wrong
# value - a negative repeat count is still an int. No type system without
# refinement types can rule these out, so they do not count against an
# accepted construct (the samples also avoid zero, for division).
VALUE_ERRORS = ("negative number of times",)


def judge(line, label, accepted, predicted, outcomes):
    outcomes = [
        (combo, result, message) for combo, result, message in outcomes
        if not (accepted and message and any(text in message for text in VALUE_ERRORS))
    ]
    failures = [(combo, message) for combo, _, message in outcomes if message is not None]
    if accepted:
        detail = "\n".join("{} -> {}".format(combo, message) for combo, message in failures)
        line.check(not failures, label + ": accepted, so it must never fail", detail)
        if predicted is not None and not failures:
            wrong = [(combo, result) for combo, result, _ in outcomes
                     if not tc.fits(runtime_type(result), predicted)]
            line.check(not wrong, label + ": result must be " + predicted.name,
                       "\n".join("{} -> {!r}".format(c, r) for c, r in wrong))
    else:
        line.check(bool(failures), label + ": rejected, so some sample must fail",
                   "every sample succeeded")


def check_constructs(line):
    for templates, is_expression in ((EXPRESSIONS, True), (STATEMENTS, False)):
        for template, names in templates:
            for kinds in itertools.product(SIMPLE, repeat=len(names)):
                types = dict(zip(names, kinds))
                findings, result = checker_verdict(template, types)
                label = "{} with {}".format(
                    template, ", ".join("{}: {}".format(n, k.name) for n, k in types.items()))
                values = {name: SAMPLES[kind] for name, kind in types.items()}
                judge(line, label, not findings, result if is_expression else None,
                      runtime_outcomes(template, values))


# A value each built-in's `any` parameter really accepts (an `any`
# parameter is unchecked, not unconditionally valid).
ANY_SAMPLE = {"len": ["abc"], "str": [1], "type": [1], "num": ["5"], "append": [1],
              "choice": [[1]]}
BUILTIN_SAMPLES = {**SAMPLES, tc.INT: [3], tc.FLOAT: [2.5, 4.0], tc.STRING: ["abc"]}


def check_builtins(line):
    interpreter = nl.Interpreter()
    for name, (params, required, ret) in sorted(tc.BUILTIN_SIGNATURES.items()):
        builtin = nl.BUILTINS[name]
        if params is None:
            continue
        valid = [ANY_SAMPLE[name] if kind is tc.ANY else BUILTIN_SAMPLES[kind] for kind in params]

        def call(args):
            try:
                return interpreter.call_value(builtin, list(args), 0), None
            except nl.NovaError as error:
                return None, error.message

        # Every argument count the signature allows works; one fewer or
        # one more than that fails.
        for count in range(required, len(params) + 1):
            for args in itertools.product(*valid[:count]):
                result, problem = call(copy(list(args)))
                line.check(problem is None, "{}{}: accepted, so it must work".format(name, args),
                           problem or "")
                if problem is None:
                    expected = (runtime_type(args[0]) if ret is tc.SAME else ret)
                    line.check(tc.fits(runtime_type(result), expected),
                               "{}{}: must return {}".format(name, args, expected.name),
                               repr(result))
        if required > 0:
            short = [values[0] for values in valid[:required - 1]]
            line.check(call(short)[1] is not None, "{} with {} arguments must fail".format(
                name, required - 1))
        extra = [values[0] for values in valid] + [1]
        line.check(call(extra)[1] is not None, "{} with {} arguments must fail".format(
            name, len(params) + 1))

        # Each typed parameter rejects every type that does not fit it.
        for position, kind in enumerate(params):
            if kind is tc.ANY:
                continue
            for wrong in SIMPLE:
                if tc.fits(wrong, kind):
                    continue
                failed = any(
                    call(copy([sample if i == position else valid[i][0]
                               for i in range(len(params))]))[1] is not None
                    for sample in BUILTIN_SAMPLES[wrong]
                )
                line.check(failed, "{}: argument {} as a {} must fail".format(
                    name, position + 1, wrong.name))


def check(line):
    check_constructs(line)
    check_builtins(line)
