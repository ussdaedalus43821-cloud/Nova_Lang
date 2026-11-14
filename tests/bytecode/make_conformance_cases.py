#!/usr/bin/env python3
"""Write tests/conformance/cases/bytecode.json: the conformance cases of docs/spec/17-bytecode.md.

    python3 tests/bytecode/make_conformance_cases.py

The cases are data, and a host in another language runs them as they are: a `source` case asks the host to write an artifact from the
program, read it back and run it (the result must be the program's own); an `artifact` case gives the bytes of a file, in hexadecimal, and the host
reads it: a refused file is the result `name: message`, status 1, no output. This script builds the files with the helpers of test_artifact.py,
runs each case on the VM to record what it does, and **checks the record against what the case is meant to show** (the `want` of each entry),
so a recorded value cannot silently be the wrong one. Run it again after a change of the compiler version, the format version or the opcode table:
the artifacts carry them. Every section of the chapter is cited by at least one case; the station fails if one is not."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tests" / "conformance"))
from common import ROOT, fields, mutate, nl, resign  # noqa: E402
import engines  # noqa: E402
import record  # noqa: E402
import test_artifact as t  # noqa: E402

OUT = ROOT / "tests" / "conformance" / "cases" / "bytecode.json"
CASES = []
BASE_SOURCE = 'print("ok")\n'
BASE = nl.compile_artifact(BASE_SOURCE)
F = fields(BASE)
INF = bytes((4,)) + b"\x00\x00\x00\x00\x00\x00\xf0\x7f"


def hexed(data):
    return data.hex()


def source_case(name, spec, source, **extra):
    CASES.append(dict(name=name, spec=spec, profile="bytecode", source=source, want="ok", **extra))


def refused(name, spec, data, error, **extra):
    CASES.append(dict(name=name, spec=spec, profile="bytecode", source="", artifact=hexed(data), want=error, **extra))


def accepted(name, spec, data, **extra):
    CASES.append(dict(name=name, spec=spec, profile="bytecode", source="", artifact=hexed(data), want="ok", **extra))


def body_of(data):
    return data[F["body"][0]:F["body"][1]]


# ---------------------------------------------------------------------------------------------- programs through an artifact
source_case("bytecode-a-program-runs-through-an-artifact", ["bc.overview", "bc.ops", "bc.code"], t.RICH)
source_case("bytecode-an-error-has-the-programs-line", ["bc.overview", "bc.code"], "let a = 1\nprint(a / 0)\n")
source_case("bytecode-constants-of-every-type", ["bc.constants"],
            'let f = len\nprint(1, -2, 3.5, "héllo ✓", true, false, f("abc"), 123456789012345678901234567890 * 2, 0.1 + 0.2)\n')
source_case("bytecode-an-integer-of-3999-digits-is-a-constant", ["bc.constants", "bc.limits"], "print(len(str(1" + "0" * 3998 + ")))\n")
source_case("bytecode-a-float-literal-that-overflows-is-infinity", ["bc.constants"], "print(1" + "0" * 400 + ".0)\n")
source_case("bytecode-closures-and-nested-functions", ["bc.code"],
            "def outer(a) {\n    let b = a * 2\n    def middle(c) {\n        def inner(d) { return a + b + c + d }\n        return inner\n    }\n"
            "    return middle\n}\nprint(outer(1)(10)(100))\n")
source_case("bytecode-loops-and-try-keep-their-state", ["bc.ops", "bc.verify"],
            'let total = 0\nfor i = 1 to 4 {\n    try {\n        for k, v in {"a": 1, "b": 2} { total = total + v * i }\n'
            '        if i == 3 { throw("three") }\n    } catch e {\n        total = total + 100\n    }\n}\nprint(total)\n')
source_case("bytecode-the-same-source-gives-the-same-bytes", ["bc.determinism"], t.RICH, deterministic=True)
source_case("bytecode-the-profile-still-gates-a-name", ["bc.profile", "bc.overview"], 'print(read("data.txt"))\n',
            files={"data.txt": "hello"}, sandbox={"profile": "restricted"})
source_case("bytecode-a-granted-name-works-through-an-artifact", ["bc.profile"], 'print(read("data.txt"))\n',
            files={"data.txt": "hello"}, sandbox={"profile": "restricted", "read": ["."]})
source_case("bytecode-a-step-limit-trips-in-loaded-code", ["bc.profile"], "let n = 0\nwhile true { n = n + 1 }\n",
            sandbox={"profile": "restricted", "limits": {"steps": 1000}})
source_case("bytecode-the-type-gate-runs-on-the-source", ["bc.profile"],
            next((ROOT / "tests" / "typecheck" / "fail").glob("*.nova")).read_text(encoding="utf-8"))
source_case("bytecode-modules-are-written-and-read-too", ["bc.profile", "bc.overview"],
            'import "util.nova" as util\nprint(util.double(21))\n', files={"util.nova": "export def double(n) { return n * 2 }\n"})

# ---------------------------------------------------------------------------------------------- the header
accepted("bytecode-a-valid-artifact-is-read-and-run", ["bc.header", "bc.reject"], BASE)
refused("bytecode-bad-magic", ["bc.header", "bc.reject"], bytes((BASE[0] ^ 1,)) + BASE[1:], "bad-magic")
refused("bytecode-not-an-artifact-at-all", ["bc.header", "bc.reject"],
        b"print(1) is a program, not an artifact, but long enough to have a trailer", "bad-magic")
refused("bytecode-a-damaged-byte-fails-the-checksum", ["bc.header", "bc.reject"], BASE[:len(BASE) // 2] + bytes((BASE[len(BASE) // 2] ^ 0x10,)) + BASE[len(BASE) // 2 + 1:], "checksum-mismatch")
refused("bytecode-a-file-cut-short-fails-the-checksum", ["bc.header", "bc.reject"], BASE[:-5], "checksum-mismatch")
refused("bytecode-too-short-to-have-a-header", ["bc.header", "bc.encoding", "bc.reject"], BASE[:5], "truncated")
refused("bytecode-an-unknown-format-version", ["bc.header", "bc.reject"], mutate(BASE, F["format"][0], 7), "unknown-format-version")
refused("bytecode-a-different-instruction-set", ["bc.header", "bc.ops", "bc.reject"], mutate(BASE, F["opcode_hash"][0], BASE[F["opcode_hash"][0]] ^ 0xFF), "opcode-set-mismatch")
refused("bytecode-reserved-flags", ["bc.header", "bc.reject"], mutate(BASE, F["flags"][0], 8), "bad-flags")
refused("bytecode-a-source-that-does-not-match-its-hash", ["bc.header", "bc.reject"], mutate(BASE, F["source"][0] + 4, ord("x")), "source-mismatch")
refused("bytecode-bytes-after-the-end-of-the-body", ["bc.header", "bc.reject"], resign(BASE[:-32] + b"\x00"), "trailing-bytes")
refused("bytecode-a-body-length-that-is-too-long", ["bc.header", "bc.encoding", "bc.reject"],
        resign(BASE[:F["body_length"][0]] + t.u32(len(body_of(BASE)) + 9) + body_of(BASE)), "truncated")
refused("bytecode-a-body-length-that-is-too-short", ["bc.header", "bc.reject"],
        resign(BASE[:F["body_length"][0]] + t.u32(len(body_of(BASE)) - 1) + body_of(BASE)), "trailing-bytes")
refused("bytecode-a-compiler-version-over-64-bytes", ["bc.header", "bc.limits", "bc.reject"],
        resign(BASE[:F["compiler"][0]] + t.u32(65) + b"v" * 65 + BASE[F["compiler"][1]:-32]), "limit-exceeded")

# ---------------------------------------------------------------------------------------------- encoding and constants
body = bytearray(BASE[:-32])
body[F["body"][0] + 4] = 0xFF
refused("bytecode-text-that-is-not-utf8", ["bc.encoding", "bc.reject"], resign(bytes(body)), "bad-text")
refused("bytecode-a-flag-that-is-neither-0-nor-1", ["bc.encoding", "bc.constants", "bc.reject"],
        t.with_body(t.code_bytes(pool=[bytes((3, 2)) + t.u32(0)], instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])), "bad-constant")
refused("bytecode-a-name-longer-than-the-file", ["bc.encoding", "bc.reject"], t.with_body(t.name_bytes("<module>")[:4] + t.u32(900) + b"ab"), "truncated")
for label, pool in (("an-unknown-tag", bytes((99,))), ("a-nan", bytes((4,)) + b"\x00\x00\x00\x00\x00\x00\xf8\x7f"),
                    ("an-integer-with-a-leading-zero-byte", bytes((3, 0)) + t.u32(2) + bytes((1, 0))), ("a-negative-zero", bytes((3, 1)) + t.u32(0))):
    refused("bytecode-constant-" + label, ["bc.constants", "bc.reject"],
            t.with_body(t.code_bytes(pool=[pool], instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])), "bad-constant")
accepted("bytecode-positive-infinity-is-a-constant", ["bc.constants"],
         t.with_body(t.code_bytes(pool=[INF], instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])))
refused("bytecode-an-integer-magnitude-over-the-limit", ["bc.constants", "bc.limits", "bc.reject"],
        t.with_body(t.code_bytes(pool=[bytes((3, 0)) + t.u32(nl.ARTIFACT_LIMITS["integer"] + 1)], instructions=t.DONE)), "limit-exceeded")
accepted("bytecode-a-built-in-is-a-name", ["bc.constants"],
         t.with_body(t.code_bytes(pool=[bytes((6,)) + t.name_bytes("len"), bytes((5,)) + t.name_bytes("abc")], nslots=0, instructions=[
             t.op("LOAD_CONST", t.u32(0)), t.op("LOAD_CONST", t.u32(1)), t.op("CALL", t.u32(1)), t.op("RETURN")])))
for label, text in (("a-gated-built-in", "now"), ("a-gated-built-in-read", "read"), ("a-name-that-is-no-built-in", "no_such_function")):
    refused("bytecode-constant-" + label, ["bc.constants", "bc.verify", "bc.reject"],
            t.with_body(t.code_bytes(pool=[bytes((6,)) + t.name_bytes(text)], instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])), "unknown-builtin")

# ---------------------------------------------------------------------------------------------- the code object
child = t.code_bytes(name="inner", closure=[(1, 4)], free=["a"], instructions=t.DONE, pool=t.NOTHING_POOL)
refused("bytecode-a-closure-that-names-a-slot-the-parent-does-not-have", ["bc.code", "bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=1, pool=[bytes((7,)) + child], instructions=[t.op("MAKE_FUNCTION", t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-slot-names-that-do-not-match-the-slot-count", ["bc.code", "bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=2, slot_names=["a"], pool=t.NOTHING_POOL, instructions=t.DONE)), "failed-verify")
refused("bytecode-parameters-and-their-names-differ-in-number", ["bc.code", "bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=1, params=[0], param_names=[], pool=t.NOTHING_POOL, instructions=t.DONE)), "failed-verify")
refused("bytecode-a-cell-parameter-that-is-not-a-parameter", ["bc.code", "bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=2, params=[0], param_names=["a"], cells=[1], pool=t.NOTHING_POOL, instructions=t.DONE)), "failed-verify")
refused("bytecode-a-module-with-a-closure", ["bc.code", "bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(closure=[(1, 0)], free=["a"], pool=t.NOTHING_POOL, instructions=t.DONE)), "failed-verify")

# ---------------------------------------------------------------------------------------------- the instruction set
refused("bytecode-an-opcode-outside-the-table", ["bc.ops", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[bytes((len(nl.ARTIFACT_TABLE),))])), "bad-opcode")
refused("bytecode-opcode-255", ["bc.ops", "bc.reject"], t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[bytes((255,))])), "bad-opcode")
refused("bytecode-an-enumerated-byte-out-of-range", ["bc.ops", "bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("CHECK_BOOL", bytes((2, 0))), t.op("RETURN")])), "failed-verify")
refused("bytecode-a-loop-state-count-of-three", ["bc.ops", "bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=1, pool=t.NOTHING_POOL, instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("ITER_PREP", t.u32(0), bytes((3,))), t.op("RETURN")])), "failed-verify")

# ---------------------------------------------------------------------------------------------- verification, V1 to V14
nest = t.code_bytes(name="f", pool=t.NOTHING_POOL, instructions=t.DONE)
for _ in range(nl.ARTIFACT_LIMITS["depth"] + 5):
    nest = t.code_bytes(name="f", pool=[bytes((7,)) + nest], instructions=[t.op("MAKE_FUNCTION", t.u32(0)), t.op("RETURN")])
refused("bytecode-verify-v1-functions-nested-too-deep", ["bc.verify", "bc.limits", "bc.reject"], t.with_body(nest), "failed-verify")
refused("bytecode-verify-v2-a-pool-index-that-is-not-there", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v2-make-function-of-a-constant-that-is-not-code", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[t.op("MAKE_FUNCTION", t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v3-a-slot-that-is-not-there", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=1, instructions=[t.op("LOAD_FAST", t.u32(5)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v3-a-slot-that-is-a-variable-and-a-cell", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=1, pool=t.NOTHING_POOL, instructions=[
            t.op("LOAD_FAST", t.u32(0)), t.op("POP"), t.op("LOAD_CELL", t.u32(0)), t.op("POP"), t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v4-a-jump-out-of-the-code", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[t.op("JUMP", t.u32(9)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v4-an-empty-exception-range", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=t.DONE, exceptions=[(1, 1, 0, 0)])), "failed-verify")
refused("bytecode-verify-v4-a-handler-out-of-the-code", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=t.DONE, exceptions=[(0, 1, 7, 0)])), "failed-verify")
refused("bytecode-verify-v5-an-empty-chain", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(instructions=[t.op("LOAD_CHAIN", t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v5-a-free-variable-the-function-does-not-have", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(instructions=[t.op("LOAD_CHAIN", t.u32(1), bytes((2,)) + t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v6-the-stack-underflows", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(instructions=[t.op("POP"), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v6-return-with-two-values", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v6-execution-falls-off-the-end", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[t.op("LOAD_CONST", t.u32(0))])), "failed-verify")
refused("bytecode-verify-v7-a-count-over-the-limit", ["bc.verify", "bc.limits", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[t.op("BUILD_LIST", t.u32(nl.ARTIFACT_LIMITS["operands"] + 1)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v8-a-loop-step-with-no-loop-state", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(nslots=1, pool=t.NOTHING_POOL, instructions=[
            t.op("ITER_NEXT", t.u32(0), t.u32(2)), t.op("JUMP", t.u32(0)), t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")])), "failed-verify")
refused("bytecode-verify-v14-a-position-past-the-source", ["bc.verify", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=t.DONE, positions=[0, 99]), source="x = 1\n"), "failed-verify")
accepted("bytecode-a-position-inside-the-source-is-fine", ["bc.verify", "bc.code"],
         t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=t.DONE, positions=[0, 5]), source="x = 1\n"))

# ---------------------------------------------------------------------------------------------- limits
refused("bytecode-limit-too-many-slots", ["bc.limits", "bc.reject"], t.with_body(t.name_bytes("<module>") + t.u32(nl.ARTIFACT_LIMITS["slots"] + 1)), "limit-exceeded")
refused("bytecode-limit-an-instruction-count-of-four-billion", ["bc.limits", "bc.encoding", "bc.reject"],
        t.with_body(t.code_bytes(pool=t.NOTHING_POOL)[:-8] + t.u32(0xFFFFFFFF)), "limit-exceeded")
refused("bytecode-limit-a-pool-count-of-four-billion", ["bc.limits", "bc.encoding", "bc.reject"],
        t.with_body(t.code_bytes()[:-12] + t.u32(0xFFFFFFFF)), "limit-exceeded")
refused("bytecode-limit-a-list-count-larger-than-the-file", ["bc.limits", "bc.encoding", "bc.reject"],
        t.with_body(t.name_bytes("<module>") + t.u32(0) + t.u32(100000)), "truncated")

# ---------------------------------------------------------------------------------------------- what verification does not prove
accepted("bytecode-an-accepted-file-can-still-be-wrong-at-run-time", ["bc.verify", "bc.reject"],
         t.with_body(t.code_bytes(nslots=1, instructions=[t.op("LOAD_CELL", t.u32(0)), t.op("RETURN")])), error_like="InternalError: .*")
other = nl.compile_artifact("print(2)\n")
other_body = other[fields(other)["body"][0]:fields(other)["body"][1]]
forged = resign(BASE[:F["body_length"][0]] + t.u32(len(other_body)) + other_body)       # the code of `print(2)` under the source and header of `print("ok")`
accepted("bytecode-code-that-is-not-the-compilation-of-its-source-is-accepted", ["bc.provenance", "bc.overview"], forged)


# ---------------------------------------------------------------------------------------------- the cache ([bc.cache])
POSIX = ["linux", "darwin"]
CACHE_SOURCE = 'def f(n) { return n * 2 }\nlet total = 0\nfor i = 1 to 5 { total = total + f(i) }\nprint("total", total)\n'


def cache_case(name, spec, source, cache, after, **extra):
    CASES.append(dict(name=name, spec=["bc.cache"] + spec, profile="bytecode", source=source, want="ok", cache=cache, cache_after=after,
                      platforms=POSIX, **extra))


def with_code_of(source, other):
    """The artifact of `source` with the code of `other`: a well-formed file whose code is not the compilation of its source."""
    a, b = nl.compile_artifact(source), nl.compile_artifact(other)
    return resign(a[:fields(a)["body_length"][0]] + t.u32(len(b[fields(b)["body"][0]:fields(b)["body"][1]])) + b[fields(b)["body"][0]:fields(b)["body"][1]])


SPACED = 'print("ok")\nlet padding = "so that every position of the other program is inside this source"\n'
cache_case("bytecode-cache-cold-then-warm", ["bc.overview"], CACHE_SOURCE, {"dir": "default", "runs": 2}, ["program:valid"])
cache_case("bytecode-cache-a-directory-the-embedder-names", [], CACHE_SOURCE, {"dir": "explicit"}, ["program:valid"])
cache_case("bytecode-cache-a-hit-changes-no-error-and-no-line", ["bc.overview", "bc.code"], "let a = 1\nprint(a / 0)\n", {"dir": "default", "runs": 2}, ["program:valid"])
cache_case("bytecode-cache-off-for-restricted-by-default", ["bc.profile"], CACHE_SOURCE, {"dir": "default"}, ["program:absent"], sandbox={"profile": "restricted"})
cache_case("bytecode-cache-on-for-restricted-when-a-directory-is-named", ["bc.profile"], CACHE_SOURCE, {"dir": "explicit"}, ["program:valid"],
           sandbox={"profile": "restricted"})
cache_case("bytecode-cache-switched-off-by-the-environment", [], CACHE_SOURCE, {"dir": "default"}, ["program:absent"], env={"NOVALANG_CACHE": "off"})
cache_case("bytecode-cache-a-damaged-entry-is-replaced", ["bc.reject"], CACHE_SOURCE, {"dir": "explicit", "entry": (b"not an artifact at all" * 9).hex()}, ["program:valid"])
cache_case("bytecode-cache-an-empty-entry-is-replaced", ["bc.reject"], CACHE_SOURCE, {"dir": "explicit", "entry": ""}, ["program:valid"])
cache_case("bytecode-cache-an-entry-made-for-another-source-is-replaced", ["bc.reject", "bc.header"], CACHE_SOURCE,
           {"dir": "explicit", "entry": nl.compile_artifact('print("somebody else")\n').hex()}, ["program:valid"])
good = nl.compile_artifact(CACHE_SOURCE)
cache_case("bytecode-cache-an-entry-of-another-format-version-is-replaced", ["bc.reject", "bc.header"], CACHE_SOURCE,
           {"dir": "explicit", "entry": mutate(good, fields(good)["format"][0], 7).hex()}, ["program:valid"])
cache_case("bytecode-cache-an-entry-for-another-instruction-set-is-replaced", ["bc.reject", "bc.header"], CACHE_SOURCE,
           {"dir": "explicit", "entry": mutate(good, fields(good)["opcode_hash"][0], good[fields(good)["opcode_hash"][0]] ^ 255).hex()}, ["program:valid"])
cache_case("bytecode-cache-a-hit-is-what-runs", ["bc.provenance"], SPACED, {"dir": "explicit", "entry": with_code_of(SPACED, "print(2)\n").hex()},
           ["program:unchanged"])
failing = next((ROOT / "tests" / "typecheck" / "fail").glob("*.nova")).read_text(encoding="utf-8")
cache_case("bytecode-cache-a-hit-still-runs-the-type-gate", ["bc.profile"], failing, {"dir": "explicit", "entry": nl.compile_artifact(failing).hex()},
           ["program:unchanged"])
cache_case("bytecode-cache-a-hit-is-still-gated-by-the-profile", ["bc.profile"], 'print(read("data.txt"))\n',
           {"dir": "explicit", "entry": nl.compile_artifact('print(read("data.txt"))\n').hex()}, ["program:unchanged"], sandbox={"profile": "restricted"})
cache_case("bytecode-cache-a-directory-others-can-write-is-not-used", [], CACHE_SOURCE, {"dir": "explicit", "mode": "0770"}, ["program:absent"])
cache_case("bytecode-cache-a-symbolic-link-is-not-followed", [], SPACED, {"dir": "explicit", "link": with_code_of(SPACED, "print(2)\n").hex()}, ["program:valid"])
cache_case("bytecode-cache-each-module-has-its-own-entry", ["bc.profile"], 'import "util.nova" as util\nprint(util.double(21))\n',
           {"dir": "default", "runs": 2}, ["module util.nova:valid", "program:valid"], files={"util.nova": "export def double(n) { return n * 2 }\n"})


def record_cases():
    problems = []
    cases = []
    for case in CASES:
        want = case.pop("want")
        extra_like = case.get("error_like")
        result = engines.run_case(case, "vm")
        case.update(output=result["output"], error=result["error"], error_line=result["error_line"], exit=result["exit"], host_calls=[])
        if extra_like:
            case["error"] = result["error"]
            if not __import__("re").fullmatch(extra_like, result["error"]):
                problems.append("{}: error {!r} does not match {!r}".format(case["name"], result["error"], extra_like))
        if "cache_after" in case and result.get("cache_after") != case["cache_after"]:
            problems.append("{}: the cache held {!r} afterwards, wanted {!r}".format(case["name"], result.get("cache_after"), case["cache_after"]))
        label = result["error"].partition(": ")[0]
        if want == "ok":
            if label in __import__("conformance").BYTECODE_ERRORS and "artifact" in case:
                problems.append("{}: wanted the file to be accepted, got {}".format(case["name"], result["error"]))
        elif label != want or not result["error"].startswith(want + ": bytecode artifact: ") or result["exit"] != 1:
            problems.append("{}: wanted {}, got {!r} (exit {})".format(case["name"], want, result["error"], result["exit"]))
        cases.append(case)
    return cases, problems


def main():
    cases, problems = record_cases()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    record.dump(OUT, "bytecode", cases)
    cited = sorted({s for c in cases for s in c["spec"]})
    print("wrote {} cases to {}; sections cited: {}".format(len(cases), OUT, ", ".join(cited)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
