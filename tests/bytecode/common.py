"""Helpers for the bytecode artifact tests (docs/spec/17-bytecode.md)."""
import contextlib
import hashlib
import io
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "conformance"))

import novalang as nl  # noqa: E402

MAGIC = nl.ARTIFACT_MAGIC


def artifact_of(source):
    return nl.compile_artifact(source)


def resign(body):
    """An artifact from everything before the checksum: the checksum is recomputed, so a test can change any byte and still
    get past the first check to the one it wants to exercise."""
    return body + hashlib.sha256(body).digest()


def mutate(data, offset, value):
    body = bytearray(data[:-32])
    body[offset] = value
    return resign(bytes(body))


def load_name(data, expect_source=None):
    """('ok', LoadedArtifact) or (error name, message)."""
    try:
        return "ok", nl.load_artifact(data, expect_source)
    except nl.BytecodeLoadError as error:
        return error.name, str(error)


def fields(data):
    """Offsets of the header fields of an artifact made by this build: {name: (start, end)}."""
    out = {}
    at = len(MAGIC)
    out["magic"] = (0, at)
    out["format"] = (at, at + 4)
    at += 4
    out["opcode_hash"] = (at, at + 32)
    at += 32
    length = int.from_bytes(data[at:at + 4], "little")
    out["compiler"] = (at, at + 4 + length)
    at += 4 + length
    out["flags"] = (at, at + 4)
    at += 4
    out["source_hash"] = (at, at + 32)
    at += 32
    length = int.from_bytes(data[at:at + 4], "little")
    out["source"] = (at, at + 4 + length)
    at += 4 + length
    out["body_length"] = (at, at + 4)
    out["body"] = (at + 4, len(data) - 32)
    out["checksum"] = (len(data) - 32, len(data))
    return out


def run_artifact(data, args=(), capabilities=None):
    """Run artifact bytes in this process: (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    saved = nl.DEFAULT_CAPABILITIES
    if capabilities is not None:
        nl.DEFAULT_CAPABILITIES = capabilities
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = nl.run_artifact_bytes(data, "program.novac", list(args))
    finally:
        nl.DEFAULT_CAPABILITIES = saved
    return status, out.getvalue(), err.getvalue()


@contextlib.contextmanager
def programs_run_through_artifacts(stats=None):
    """Inside this block every program the VM runs, and every module it imports, is compiled, written as an artifact, read back and
    verified, and the loaded code is what runs (a program too large to write runs from source, as the cache would). Everything else is
    exactly `novalang.run`. `stats` counts what happened."""
    stats = stats if stats is not None else {}
    original = nl.run

    def run(source, interpreter, path=None):
        if interpreter.engine != "vm":
            return original(source, interpreter, path)
        try:
            tokens = nl.Lexer(source).tokenize()
            program = nl.Parser(tokens).parse()
            nl.type_gate(program, source, interpreter, path)
            try:
                data = nl.dump_artifact(nl.compile_ast(program), source, nl.bytecode_flags(program))
            except nl.BytecodeDumpError:
                stats["not written"] = stats.get("not written", 0) + 1
                data = None
            if data is not None:
                loaded = nl.load_artifact(data, source)
                program._code = loaded.code
                stats["through an artifact"] = stats.get("through an artifact", 0) + 1
            return program, nl.run_program(program, interpreter)
        except RecursionError:
            raise nl.NovaError("the interpreter ran out of stack - recursion too deep") from None

    nl.run = run
    try:
        yield stats
    finally:
        nl.run = original
