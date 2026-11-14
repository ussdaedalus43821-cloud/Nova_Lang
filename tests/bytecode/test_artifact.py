"""The bytecode artifact (.novac): format, rejection, corruption, limits, determinism, the command line, and the round trip.

The contract is docs/spec/17-bytecode.md (sections [bc.*]); the section ids appear in the test names. Run:

    python3 -m unittest discover -s tests/bytecode -v

The round-trip test (the whole conformance corpus, compiled, written, read back and run) takes about a minute; set NOVA_BYTECODE_QUICK=1
to run a tenth of the corpus."""
import hashlib
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common import (HERE, ROOT, MAGIC, artifact_of, fields, load_name, mutate, nl, programs_run_through_artifacts, resign,
                    run_artifact)

import engines  # noqa: E402  (tests/conformance)
import conformance  # noqa: E402

NAMES = {"truncated", "bad-magic", "checksum-mismatch", "unknown-format-version", "opcode-set-mismatch", "bad-flags", "trailing-bytes",
         "bad-text", "bad-constant", "bad-opcode", "bad-argument", "unknown-builtin", "limit-exceeded", "failed-verify", "source-mismatch",
         "internal-error"}

RICH = '''\
# a program that uses most of what the compiler can write
import "nothing_here.nova" as missing_not_loaded
def make_counter(start) {
    let count = start
    def next() {
        count = count + 1
        return count
    }
    return next
}
let counter = make_counter(10)
let total = 0
for i = 1 to 5 { total = total + counter() * i }
let words = split("a,b,c", ",")
let table = {name: "nova", size: len(words), "k": [1, 2.5, -3]}
for key, value in table { total = total + len(str(key)) }
let note = f"total={total} {words[0]}"
print(note, words[1:], table.name, 12345678901234567890 * 3, 1.5, true and not false)
try {
    if total > 0 { throw("boom") }
} catch e {
    print("caught", e)
} finally {
    print("done")
}
while total > 100 { total = total - 50 }
print(total, 10 // 3, 10 % 3, 2 in [1, 2], "b" in "abc", -total, +total)
'''
RICH = RICH.replace('import "nothing_here.nova" as missing_not_loaded\n', "")


def u32(n):
    return n.to_bytes(4, "little")


def name_bytes(text):
    data = text.encode("utf-8")
    return u32(len(data)) + data


def op(name, *parts):
    return bytes((nl.OP[name],)) + b"".join(parts)


def code_bytes(name="<module>", nslots=0, params=(), param_names=(), cells=(), slot_names=None, free=(), closure=(), pool=(),
               instructions=(), positions=None, exceptions=()):
    out = name_bytes(name) + u32(nslots)
    out += u32(len(params)) + b"".join(u32(p) for p in params)
    out += u32(len(param_names)) + b"".join(name_bytes(t) for t in param_names)
    out += u32(len(cells)) + b"".join(u32(c) for c in cells)
    slot_names = ["s%d" % i for i in range(nslots)] if slot_names is None else slot_names
    out += u32(len(slot_names)) + b"".join(name_bytes(t) for t in slot_names)
    out += u32(len(free)) + b"".join(name_bytes(t) for t in free)
    out += u32(len(closure)) + b"".join(bytes((kind,)) + u32(where) for kind, where in closure)
    out += u32(len(pool)) + b"".join(pool)
    out += u32(len(instructions)) + b"".join(instructions)
    positions = [0xFFFFFFFF] * len(instructions) if positions is None else positions
    out += b"".join(u32(p) for p in positions)
    out += u32(len(exceptions)) + b"".join(u32(s) + u32(e) + u32(h) + bytes((k,)) for s, e, h, k in exceptions)
    return out


def with_body(body, source="x = 1\n"):
    """A complete artifact (this build's header, a fresh checksum) around a hand-made code object."""
    base = artifact_of(source)
    f = fields(base)
    return resign(base[:f["body_length"][0]] + u32(len(body)) + body)


def const_int(n):
    return bytes((3, 0)) + u32(1) + bytes((n,))


DONE = [op("LOAD_CONST", u32(0)), op("RETURN")]
NOTHING_POOL = [bytes((0,))]


class Format(unittest.TestCase):
    def test_bc_header_layout(self):
        data = artifact_of("print(1)\n")
        f = fields(data)
        self.assertEqual(data[:8], bytes.fromhex("4e4f5641430d0a1a"))
        self.assertEqual(int.from_bytes(data[f["format"][0]:f["format"][1]], "little"), nl.ARTIFACT_FORMAT)
        self.assertEqual(nl.ARTIFACT_FORMAT, 0, "development builds write format version 0 (Q7)")
        self.assertEqual(data[f["opcode_hash"][0]:f["opcode_hash"][1]], nl.artifact_opcode_hash())
        self.assertEqual(data[f["source"][0] + 4:f["source"][1]], b"print(1)\n")
        self.assertEqual(data[f["source_hash"][0]:f["source_hash"][1]], hashlib.sha256(b"print(1)\n").digest())
        self.assertEqual(data[f["checksum"][0]:], hashlib.sha256(data[:-32]).digest())

    def test_bc_flags_record_annotations_and_imports(self):
        plain = fields(artifact_of("print(1)\n"))
        for source, want in (("print(1)\n", 0), ("let x: number = 1\nprint(x)\n", 1), ('import "m.nova" as m\n', 2)):
            data = artifact_of(source)
            f = fields(data)
            self.assertEqual(int.from_bytes(data[f["flags"][0]:f["flags"][1]], "little"), want, source)
        self.assertIsNotNone(plain)

    def test_bc_determinism_same_source_same_bytes(self):
        self.assertEqual(artifact_of(RICH), artifact_of(RICH))

    def test_bc_determinism_dump_of_load_of_dump(self):
        data = artifact_of(RICH)
        loaded = nl.load_artifact(data)
        self.assertEqual(nl.dump_artifact(loaded.code, loaded.source, loaded.flags), data)

    def test_bc_the_loaded_code_prints_what_the_compiled_code_prints(self):
        status, out, err = run_artifact(artifact_of(RICH))
        self.assertEqual((status, err), (0, ""))
        direct = engines.run_in_process(RICH, "vm")
        self.assertEqual(out.splitlines(), direct["output"])
        self.assertEqual((status, ""), (direct["exit"], direct["error"]))

    def test_bc_ops_the_table_is_the_compilers(self):
        self.assertEqual([name for name, _, _ in nl.ARTIFACT_TABLE], nl.OPCODES)

    def test_bc_ops_every_opcode_can_be_written_and_read(self):
        seen = set()
        sources = [p for pattern in ("examples/*.nova", "tests/bench/*.nova", "tests/benchmarks/workloads/micro/*.nova",
                                     "tests/compiler/*.nova", "tests/benchmarks/workloads/poc/*/*.nova") for p in ROOT.glob(pattern)]
        sources.append(None)
        for path in sources:
            source = RICH if path is None else path.read_text(encoding="utf-8")
            try:
                code = nl.compile_source(source)
            except nl.NovaError:
                continue
            loaded = nl.load_artifact(nl.dump_artifact(code, source))
            stack = [loaded.code]
            while stack:
                current = stack.pop()
                seen.update(current.ops)
                stack.extend(c for c in current.constants if isinstance(c, nl.CodeObject))
        missing = [nl.OPCODES[i] for i in range(len(nl.OPCODES)) if i not in seen]
        self.assertEqual(missing, [], "opcodes the repository's programs never write: {}".format(missing))


class Rejections(unittest.TestCase):
    def expect(self, data, name, mention=None):
        got, message = load_name(data)
        self.assertEqual(got, name, "expected {}, got {} ({})".format(name, got, message if got != "ok" else ""))
        self.assertTrue(message.startswith("bytecode artifact: "), message)
        if mention:
            self.assertIn(mention, message)

    def test_bc_reject_bad_magic(self):
        data = bytearray(artifact_of("x = 1\n"))
        data[0] ^= 1
        self.expect(bytes(data), "bad-magic")
        self.expect(b"hello, this is not an artifact at all, just text that is long enough", "bad-magic")

    def test_bc_reject_truncated_and_checksum(self):
        data = artifact_of("x = 1\n")
        self.expect(data[:5], "truncated")
        self.expect(data[:20], "truncated")
        self.expect(data[:-1], "checksum-mismatch")
        damaged = bytearray(data)
        damaged[len(data) // 2] ^= 0x10
        self.expect(bytes(damaged), "checksum-mismatch")
        self.expect(b"", "truncated")

    def test_bc_reject_format_version_and_instruction_set(self):
        data = artifact_of("x = 1\n")
        f = fields(data)
        self.expect(mutate(data, f["format"][0], 1), "unknown-format-version", "format version 1 is not supported (this is 0)")
        self.expect(mutate(data, f["opcode_hash"][0] + 3, data[f["opcode_hash"][0] + 3] ^ 0xFF), "opcode-set-mismatch")

    def test_bc_reject_flags(self):
        data = artifact_of("x = 1\n")
        self.expect(mutate(data, fields(data)["flags"][0], 4), "bad-flags")

    def test_bc_reject_source_mismatch(self):
        data = artifact_of("x = 1\n")
        f = fields(data)
        self.expect(mutate(data, f["source"][0] + 4, ord("y")), "source-mismatch")
        self.assertEqual(load_name(data, "x = 1\n")[0], "ok")
        self.assertEqual(load_name(data, "x = 2\n")[0], "source-mismatch")

    def test_bc_reject_text_that_is_not_utf8(self):
        data = artifact_of("x = 1\n")
        f = fields(data)
        body = bytearray(data[:-32])
        body[f["body"][0] + 4] = 0xFF               # the first byte of the code object's name
        self.expect(resign(bytes(body)), "bad-text")

    def test_bc_reject_trailing_bytes(self):
        data = artifact_of("x = 1\n")
        f = fields(data)
        body = data[:-32]
        longer = body + b"\x00"
        self.expect(resign(longer), "trailing-bytes")
        shorter_declared = resign(body[:f["body_length"][0]] + u32(f["body"][1] - f["body"][0] - 1) + body[f["body"][0]:])
        self.expect(shorter_declared, "trailing-bytes")

    def test_bc_reject_constants(self):
        for pool, label in (([bytes((99,))], "an unknown tag"), ([bytes((4,)) + b"\x00\x00\x00\x00\x00\x00\xf8\x7f"], "a NaN"),
                            ([bytes((3, 0)) + u32(2) + bytes((1, 0))], "a leading zero byte"),
                            ([bytes((3, 1)) + u32(0)], "a negative zero"), ([bytes((3, 2)) + u32(0)], "a flag that is 2")):
            with self.subTest(label):
                self.expect(with_body(code_bytes(pool=pool, instructions=[op("LOAD_CONST", u32(0)), op("RETURN")])), "bad-constant")

    def test_bc_constants_accept_infinity_and_big_integers(self):
        inf = bytes((4,)) + b"\x00\x00\x00\x00\x00\x00\xf0\x7f"
        status, _, _ = run_artifact(with_body(code_bytes(pool=[inf], instructions=[op("LOAD_CONST", u32(0)), op("RETURN")])))
        self.assertEqual(status, 0)
        big = 10 ** 3999
        source = "print({})\n".format(big)
        data = artifact_of(source)
        self.assertEqual(load_name(data)[0], "ok")

    def test_bc_reject_instructions(self):
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=[bytes((len(nl.ARTIFACT_TABLE),))])), "bad-opcode")
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=[bytes((255,))])), "bad-opcode")

    def test_bc_verify_V2_pool_references(self):
        self.expect(with_body(code_bytes(instructions=[op("LOAD_CONST", u32(0)), op("RETURN")])), "failed-verify", "V2")
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=[op("MAKE_FUNCTION", u32(0)), op("RETURN")])), "failed-verify", "V2")

    def test_bc_verify_V3_slots(self):
        self.expect(with_body(code_bytes(nslots=1, instructions=[op("LOAD_FAST", u32(5)), op("RETURN")])), "failed-verify", "V3")
        self.expect(with_body(code_bytes(nslots=1, pool=NOTHING_POOL, instructions=[
            op("LOAD_FAST", u32(0)), op("POP"), op("LOAD_CELL", u32(0)), op("POP"), op("LOAD_CONST", u32(0)), op("RETURN")])),
            "failed-verify", "V3")      # one slot used as a plain variable and as a cell

    def test_bc_verify_V4_targets_and_handlers(self):
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=[op("JUMP", u32(9)), op("RETURN")])), "failed-verify", "V4")
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=DONE, exceptions=[(1, 1, 0, 0)])), "failed-verify", "V4")
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=DONE, exceptions=[(0, 1, 7, 0)])), "failed-verify", "V4")

    def test_bc_verify_V5_chains(self):
        empty = op("LOAD_CHAIN", u32(0))
        self.expect(with_body(code_bytes(instructions=[empty, op("RETURN")])), "failed-verify", "V5")
        free = op("LOAD_CHAIN", u32(1), bytes((2,)) + u32(0))
        self.expect(with_body(code_bytes(instructions=[free, op("RETURN")])), "failed-verify", "V5")

    def test_bc_verify_V6_stack_depth(self):
        self.expect(with_body(code_bytes(instructions=[op("POP"), op("RETURN")])), "failed-verify", "V6")
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=[op("LOAD_CONST", u32(0)), op("LOAD_CONST", u32(0)), op("RETURN")])),
                    "failed-verify", "V6")
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=[op("LOAD_CONST", u32(0))])), "failed-verify", "V6")

    def test_bc_verify_V8_loop_state(self):
        self.expect(with_body(code_bytes(nslots=1, pool=NOTHING_POOL, instructions=[
            op("ITER_NEXT", u32(0), u32(2)), op("JUMP", u32(0)), op("LOAD_CONST", u32(0)), op("RETURN")])), "failed-verify", "V8")

    def test_bc_verify_V9_V10_closure_and_counts(self):
        child = code_bytes(name="inner", nslots=0, closure=[(1, 4)], free=["a"], instructions=DONE, pool=NOTHING_POOL)
        parent = code_bytes(nslots=1, pool=[bytes((7,)) + child], instructions=[op("MAKE_FUNCTION", u32(0)), op("RETURN")])
        self.expect(with_body(parent), "failed-verify", "V9")
        self.expect(with_body(code_bytes(nslots=2, slot_names=["a"], pool=NOTHING_POOL, instructions=DONE)), "failed-verify", "V10")
        self.expect(with_body(code_bytes(nslots=1, params=[0], param_names=[], pool=NOTHING_POOL, instructions=DONE)), "failed-verify", "V10")

    def test_bc_verify_V11_enumerated_bytes(self):
        bad = op("CHECK_BOOL", bytes((2, 0)))
        self.expect(with_body(code_bytes(pool=NOTHING_POOL, instructions=[op("LOAD_CONST", u32(0)), bad, op("RETURN")])), "failed-verify", "V11")

    def test_bc_verify_V13_gated_and_unknown_builtins(self):
        for text in ("now", "read", "exit", "no_such_function"):
            with self.subTest(text):
                pool = [bytes((6,)) + name_bytes(text)]
                self.expect(with_body(code_bytes(pool=pool, instructions=[op("LOAD_CONST", u32(0)), op("RETURN")])), "unknown-builtin")
        ok = [bytes((6,)) + name_bytes("len")]
        self.assertEqual(load_name(with_body(code_bytes(pool=ok, instructions=[op("LOAD_CONST", u32(0)), op("RETURN")])))[0], "ok")

    def test_bc_verify_V14_positions(self):
        data = with_body(code_bytes(pool=NOTHING_POOL, instructions=DONE, positions=[0, 99]), source="x = 1\n")
        self.expect(data, "failed-verify", "V14")
        self.assertEqual(load_name(with_body(code_bytes(pool=NOTHING_POOL, instructions=DONE, positions=[0, 5]), source="x = 1\n"))[0], "ok")

    def test_bc_limits_are_checked_before_the_memory_is_used(self):
        huge = u32(0xFFFFFFFF)
        for label, body in (("instructions", code_bytes(pool=NOTHING_POOL)[:-8] + huge),
                            ("pool", code_bytes()[:-12] + huge),
                            ("params", name_bytes("<module>") + u32(0) + huge),
                            ("slots", name_bytes("<module>") + huge)):
            with self.subTest(label):
                got, _ = load_name(with_body(body))
                self.assertIn(got, ("limit-exceeded", "truncated"), label)
        self.expect(with_body(name_bytes("<module>") + u32(nl.ARTIFACT_LIMITS["slots"] + 1)), "limit-exceeded")
        too_long = bytes((3, 0)) + u32(nl.ARTIFACT_LIMITS["integer"] + 1)
        self.expect(with_body(code_bytes(pool=[too_long], instructions=DONE)), "limit-exceeded")
        data = artifact_of("x = 1\n")
        f = fields(data)
        longname = resign(data[:f["compiler"][0]] + u32(65) + b"v" * 65 + data[f["compiler"][1]:-32])
        self.expect(longname, "limit-exceeded")

    def test_bc_limits_nesting_is_counted_by_the_loader(self):
        depth = nl.ARTIFACT_LIMITS["depth"] + 5
        inner = code_bytes(name="f", pool=NOTHING_POOL, instructions=DONE)
        for _ in range(depth):
            inner = code_bytes(name="f", pool=[bytes((7,)) + inner], instructions=[op("MAKE_FUNCTION", u32(0)), op("RETURN")])
        self.expect(with_body(inner), "failed-verify", "V1")

    def test_bc_dump_refuses_what_it_cannot_write(self):
        source = "".join("def f%d() {\n" % i for i in range(nl.ARTIFACT_LIMITS["depth"] + 2)) + "".join("}\n" for _ in range(nl.ARTIFACT_LIMITS["depth"] + 2))
        try:
            code = nl.compile_source(source)
        except nl.NovaError:
            self.skipTest("the parser refuses a nesting this deep before the format has to")
        with self.assertRaises(nl.BytecodeDumpError):
            nl.dump_artifact(code, source)

    def test_bc_containment_an_unexpected_exception_is_internal_error(self):
        data = artifact_of("x = 1\n")
        real = nl.verify
        nl.verify = lambda code: 1 / 0
        try:
            self.assertEqual(load_name(data)[0], "internal-error")
        finally:
            nl.verify = real
        self.assertEqual(load_name(data)[0], "ok")


class Corruption(unittest.TestCase):
    """[bc.reject] invariants: every prefix is a named error; every single-byte change, even with the checksum made right again, is
    accepted (and then verified and writable again) or a named error; a seeded fuzzer finds nothing else."""

    SAMPLES = ("x = 1\nprint(x)\n", RICH, "def f(a) { return a * 2 }\nfor i = 1 to 3 { print(f(i)) }\n")

    def check(self, data, label):
        got, value = load_name(data)
        self.assertIn(got, NAMES | {"ok"}, label)
        self.assertNotEqual(got, "internal-error", "{}: an unexpected exception in the reader: {}".format(label, value))
        if got == "ok":
            self.assertTrue(nl.verify(value.code), label)
            nl.dump_artifact(value.code, value.source, value.flags)         # still writable
        return got

    def test_bc_reject_every_prefix_is_a_named_error(self):
        for source in self.SAMPLES:
            data = artifact_of(source)
            for end in range(len(data)):
                got, _ = load_name(data[:end])
                self.assertIn(got, ("truncated", "bad-magic", "checksum-mismatch"), "prefix of {} bytes".format(end))

    def test_bc_reject_every_single_byte_change_with_the_checksum_repaired(self):
        accepted = rejected = 0
        for source in self.SAMPLES:
            data = artifact_of(source)
            for offset in range(len(data) - 32):
                for value in {(data[offset] + 1) & 255, data[offset] ^ 0x80, 0, 255} - {data[offset]}:
                    got = self.check(mutate(data, offset, value), "offset {} value {}".format(offset, value))
                    if got == "ok":
                        accepted += 1
                    else:
                        rejected += 1
        self.assertGreater(rejected, accepted, "most changes should be refused")

    def test_bc_reject_a_seeded_fuzzer_finds_nothing_but_named_errors(self):
        rng = random.Random(20261114)
        for source in self.SAMPLES:
            data = artifact_of(source)
            body = data[:-32]
            for round_ in range(1500):
                mutated = bytearray(body)
                for _ in range(rng.choice((1, 1, 2, 3, 5, 9))):
                    mutated[rng.randrange(len(mutated))] = rng.randrange(256)
                if rng.random() < 0.15:
                    del mutated[rng.randrange(len(mutated)):][:rng.randrange(1, 40)]
                if rng.random() < 0.1:
                    mutated += bytes(rng.randrange(256) for _ in range(rng.randrange(1, 20)))
                self.check(resign(bytes(mutated)), "fuzz {}".format(round_))

    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, "the restricted profile needs Python 3.8 or later on Windows")
    def test_bc_verify_what_loads_runs_without_a_traceback(self):
        """A file that is accepted may do odd things, but never crashes the host: whatever it does ends as the program's own status
        (0 or 1, a limit, a NovaError) or as `InternalError` with status 70, never a Python traceback."""
        caps = nl.Capabilities(profile="restricted", limits={"steps": 4000, "time": 1500, "output": 20000})
        rng = random.Random(1114)
        data = artifact_of(self.SAMPLES[1])
        body = data[:-32]
        counts = {}
        for _ in range(600):
            mutated = bytearray(body)
            for _ in range(rng.choice((1, 2, 3))):
                mutated[rng.randrange(len(mutated))] = rng.randrange(256)
            candidate = resign(bytes(mutated))
            if load_name(candidate)[0] != "ok":
                continue
            status, out, err = run_artifact(candidate, capabilities=caps)
            self.assertNotIn("Traceback", err)
            self.assertIn(status, (0, 1, 70), err[-200:])
            counts[status] = counts.get(status, 0) + 1
        self.assertGreater(sum(counts.values()), 0)


class Containment(unittest.TestCase):
    def test_bc_verify_a_cell_that_was_never_made_is_internal_error_not_a_traceback(self):
        # accepted by the loader (the roles agree) but wrong at run time: LOAD_CELL on a slot that holds no cell.
        data = with_body(code_bytes(nslots=1, instructions=[op("LOAD_CELL", u32(0)), op("RETURN")]))
        self.assertEqual(load_name(data)[0], "ok")
        status, out, err = run_artifact(data)
        self.assertEqual(status, 70)
        self.assertTrue(err.startswith("InternalError"), err)
        self.assertNotIn("Traceback", err)


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)

    def nova(self, *args, cwd=None):
        done = subprocess.run([sys.executable, str(ROOT / "novalang.py"), *args], cwd=cwd or self.path, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120)
        return done.returncode, done.stdout, done.stderr

    def compile(self, source, name="program"):
        (self.path / (name + ".nova")).write_text(source, encoding="utf-8")
        return self.nova("--compile", name + ".nova", "-o", name + ".novac")

    def test_bc_compile_run_and_check(self):
        self.assertEqual(self.compile(RICH), (0, "", ""))
        direct = self.nova("program.nova")
        loaded = self.nova("program.novac")
        self.assertEqual(loaded, direct)
        self.assertEqual(direct[0], 0)
        status, out, err = self.nova("--check-artifact", "program.novac")
        self.assertEqual(status, 0, err)
        self.assertIn("ok: the code is the compilation of the embedded source", out)

    def test_bc_a_standalone_artifact_needs_no_source_file(self):
        self.compile("print(args())\n")
        (self.path / "program.nova").unlink()
        self.assertEqual(self.nova("program.novac", "a", "b")[:2], (0, '["a", "b"]\n'))

    def test_bc_errors_in_a_standalone_artifact_show_the_line_and_the_caret(self):
        self.compile("let a = 1\nprint(a / 0)\n")
        direct = self.nova("program.nova")
        (self.path / "program.nova").unlink()
        loaded = self.nova("program.novac")
        self.assertEqual(loaded[0], 1)
        self.assertIn("division by zero", loaded[2])
        self.assertIn("print(a / 0)", loaded[2])
        self.assertEqual(loaded[2].replace("program.novac", "program.nova"), direct[2])

    def test_bc_check_artifact_catches_code_that_is_not_the_source(self):
        self.compile("print(1)\n", "good")
        self.compile("print(2)\n", "other")
        good = (self.path / "good.novac").read_bytes()
        other = (self.path / "other.novac").read_bytes()
        gf, of = fields(good), fields(other)
        # the code of `print(2)` under the source and header of `print(1)`: well-formed, checksummed, and not its compilation
        forged = resign(good[:gf["body_length"][0]] + other[of["body_length"][0]:of["checksum"][0]])
        (self.path / "forged.novac").write_bytes(forged)
        self.assertEqual(load_name(forged)[0], "ok")
        self.assertEqual(self.nova("forged.novac")[:2], (0, "2\n"))
        status, out, err = self.nova("--check-artifact", "forged.novac")
        self.assertEqual(status, 1)
        self.assertIn("NOT the compilation", err)

    def test_bc_a_damaged_artifact_is_refused_with_its_name_and_status_1(self):
        self.compile("print(1)\n")
        data = bytearray((self.path / "program.novac").read_bytes())
        data[len(data) // 2] ^= 0xFF
        (self.path / "program.novac").write_bytes(bytes(data))
        status, out, err = self.nova("program.novac")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("checksum mismatch", err)
        self.assertNotIn("Traceback", err)

    def test_bc_the_type_gate_runs_on_the_embedded_source(self):
        failing = next((ROOT / "tests" / "typecheck" / "fail").glob("*.nova"))
        source = failing.read_text(encoding="utf-8")
        self.compile(source)
        data = (self.path / "program.novac").read_bytes()
        f = fields(data)
        self.assertEqual(int.from_bytes(data[f["flags"][0]:f["flags"][1]], "little") & 1, 1)
        direct = self.nova("program.nova")
        loaded = self.nova("program.novac")
        self.assertNotEqual(direct[0], 0)
        self.assertEqual(loaded[0], direct[0])
        self.assertEqual(loaded[2].replace("program.novac", "program.nova"), direct[2])

    @unittest.skipIf(nl.SANDBOX_UNSUPPORTED, "the restricted profile needs Python 3.8 or later on Windows")
    def test_bc_the_profile_still_gates_an_artifact(self):
        self.compile('print(read("secret.txt"))\n')
        (self.path / "secret.txt").write_text("s", encoding="utf-8")
        trusted = self.nova("program.novac")
        restricted = self.nova("--profile", "restricted", "program.novac")
        self.assertEqual(trusted[:2], (0, "s\n"))
        self.assertEqual(restricted[0], 1)
        self.assertIn("undefined name 'read'", restricted[2])

    def test_bc_the_tree_walker_does_not_run_artifacts(self):
        self.compile("print(1)\n")
        status, out, err = self.nova("--tree-walk", "program.novac")
        self.assertEqual(status, 2)
        self.assertIn("bytecode VM only", err)

    def test_bc_dis_lists_an_artifact(self):
        self.compile("print(1 + 2)\n")
        direct = self.nova("--dis", "program.nova")
        loaded = self.nova("--dis", "program.novac")
        self.assertEqual(loaded[:2], direct[:2])

    def test_bc_compile_reports_errors_and_usage(self):
        (self.path / "bad.nova").write_text("print(\n", encoding="utf-8")
        status, out, err = self.nova("--compile", "bad.nova", "-o", "bad.novac")
        self.assertEqual(status, 1)
        self.assertFalse((self.path / "bad.novac").exists())
        self.assertEqual(self.nova("--compile", "bad.nova")[0], 2)
        self.assertEqual(self.nova("--check-artifact")[0], 2)


class RoundTrip(unittest.TestCase):
    """Compile, write, read back, run: the same output, error and exit status as running the source, for every program of the
    conformance corpus the VM runs, and for the repository's benchmark programs."""

    def result(self, case):
        try:
            return engines.run_case(case, "vm")
        except Exception as problem:            # noqa: BLE001 - the same failure must happen both ways
            return ("raised", type(problem).__name__)

    def test_bc_the_whole_corpus_gives_identical_results_through_an_artifact(self):
        cases = [c for c in conformance.load_cases() if c.get("profile") != "policy" and "embedding" not in c
                 and not (c.get("sandbox") and "isolate" in c["sandbox"])]
        if os.environ.get("NOVA_BYTECODE_QUICK"):
            cases = cases[::10]
        direct = [self.result(case) for case in cases]
        stats = {}
        with programs_run_through_artifacts(stats):
            loaded = [self.result(case) for case in cases]
        different = [case["name"] for case, a, b in zip(cases, direct, loaded) if a != b]
        self.assertEqual(different, [], "cases that differ through an artifact")
        self.assertGreater(stats.get("through an artifact", 0), len(cases) // 2, stats)
        print("\n  round trip: {} cases, {}".format(len(cases), ", ".join("{} {}".format(v, k) for k, v in sorted(stats.items()))), file=sys.stderr)

    def test_bc_the_benchmark_programs_give_identical_results_through_an_artifact(self):
        paths = sorted((ROOT / "tests" / "benchmarks" / "workloads" / "micro").glob("*.nova")) + sorted((ROOT / "tests" / "bench").glob("*.nova"))
        for path in paths:
            if path.name in ("index_assign.nova", "loops.nova"):
                continue            # long-running; the others exercise the same instructions
            source = path.read_text(encoding="utf-8")
            direct = engines.run_in_process_in(source, "vm", str(path.parent))
            with programs_run_through_artifacts():
                loaded = engines.run_in_process_in(source, "vm", str(path.parent))
            self.assertEqual(loaded, direct, path.name)


class Fixtures(unittest.TestCase):
    """The golden artifacts of tests/bytecode/fixtures/v1/ (made by tests/bytecode/make_fixtures.py): this build must still read every one and
    run it to the recorded output, the bytes must still be what the compiler writes, and every rejected one must be refused with its recorded name."""

    DIR = HERE / "fixtures" / "v1"

    def manifest(self):
        return json.loads((self.DIR / "manifest.json").read_text(encoding="utf-8"))

    def test_bc_fixtures_load_run_and_are_what_the_compiler_writes(self):
        manifest = self.manifest()
        self.assertGreaterEqual(len(manifest["accepted"]), 10)
        for entry in manifest["accepted"]:
            with self.subTest(entry["name"]):
                data = (self.DIR / (entry["name"] + ".novac")).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
                loaded = nl.load_artifact(data)
                self.assertEqual(loaded.compiler, manifest["compiler"], "regenerate the fixtures after a version change: python3 tests/bytecode/make_fixtures.py")
                self.assertEqual(data, nl.compile_artifact(loaded.source), "the compiler no longer writes these bytes")
                if entry["run"]:
                    status, out, err = run_artifact(data, args=entry.get("args", []))
                    self.assertEqual((status, out), (entry["status"], entry["stdout"]))

    def test_bc_fixtures_rejected_ones_have_their_recorded_names(self):
        for entry in self.manifest()["rejected"]:
            with self.subTest(entry["name"]):
                data = (self.DIR / "rejected" / (entry["name"] + ".novac")).read_bytes()
                name, message = load_name(data)
                self.assertEqual(name, entry["error"], message)

    def test_bc_fixtures_cover_every_opcode(self):
        seen = set()
        for entry in self.manifest()["accepted"]:
            stack = [nl.load_artifact((self.DIR / (entry["name"] + ".novac")).read_bytes()).code]
            while stack:
                code = stack.pop()
                seen.update(code.ops)
                stack.extend(c for c in code.constants if isinstance(c, nl.CodeObject))
        missing = [nl.OPCODES[i] for i in range(len(nl.OPCODES)) if i not in seen]
        self.assertEqual(missing, [], "opcodes no fixture contains: {}".format(missing))


if __name__ == "__main__":
    unittest.main()
