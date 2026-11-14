#!/usr/bin/env python3
"""Regenerate tests/bytecode/fixtures/v1/ (the golden artifacts of the bytecode format).

    python3 tests/bytecode/make_fixtures.py

The fixtures freeze this format generation: golden artifacts that every later build must still read (or refuse cleanly), the output each one
printed when it was made, and a set of damaged files with the name of the error each must give. Regenerate only on purpose: a change of the
compiler version, of the opcode table or of the format changes every file, which is the point of having them. The compiler version is recorded in
manifest.json so the test can say so."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, fields, nl, resign, run_artifact  # noqa: E402
import test_artifact as t  # noqa: E402

OUT = HERE / "fixtures" / "v1"
PROGRAMS = [   # (fixture name, source file or text, run it?)
    ("recursion", "tests/benchmarks/workloads/micro/recursion.nova", True),
    ("arithmetic", "tests/benchmarks/workloads/micro/arithmetic.nova", True),
    ("float_math", "tests/benchmarks/workloads/micro/float_math.nova", True),
    ("string_build", "tests/benchmarks/workloads/micro/string_build.nova", True),
    ("string_scan", "tests/benchmarks/workloads/micro/string_scan.nova", True),
    ("split_join", "tests/benchmarks/workloads/micro/split_join.nova", True),
    ("list_dict", "tests/benchmarks/workloads/micro/list_dict.nova", True),
    ("higher_order", "tests/benchmarks/workloads/micro/higher_order.nova", True),
    ("try_catch", "tests/benchmarks/workloads/micro/try_catch.nova", True),
    ("matrix", "tests/benchmarks/workloads/micro/matrix.nova", True),
    ("closures", "tests/compiler/closures.nova", True),
    ("control", "tests/compiler/control.nova", True),
    ("data", "tests/compiler/data.nova", True),
    ("scopes", "tests/compiler/scopes.nova", True),
    ("try_finally", "tests/compiler/try_finally.nova", True),
    ("modules", "tests/compiler/modules.nova", False),         # imports files: loaded and compared, not run
    ("errors", "examples/errors.nova", False),                 # deletes a file it made: loaded and compared, not run
    ("rich", t.RICH, True),
    ("typed", "let width: number = 4\nlet label: string = \"nova\"\nprint(label, width * 2)\n", True),
]


def text_of(source):
    path = ROOT / source
    return path.read_text(encoding="utf-8") if source.endswith(".nova") and path.exists() else source


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "rejected").mkdir(parents=True)
    accepted = []
    for name, source, run in PROGRAMS:
        text = text_of(source)
        data = nl.compile_artifact(text)
        (OUT / (name + ".novac")).write_bytes(data)
        entry = {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "run": run}
        if run:
            status, out, err = run_artifact(data)
            entry.update(status=status, stdout=out)
        else:
            entry.update(status=None, stdout=None)
        accepted.append(entry)
    base = nl.compile_artifact("print(1 + 2)\nlet x = [1, 2]\nprint(x[0])\n")
    f = fields(base)
    body_at = f["body"][0]
    damaged = {
        "bad_magic": ("bad-magic", bytes((base[0] ^ 1,)) + base[1:]),
        "truncated": ("checksum-mismatch", base[:100]),
        "too_short": ("truncated", base[:5]),
        "checksum": ("checksum-mismatch", base[:-1] + bytes((base[-1] ^ 1,))),
        "format_version": ("unknown-format-version", t.mutate(base, f["format"][0], 7)),
        "instruction_set": ("opcode-set-mismatch", t.mutate(base, f["opcode_hash"][0], base[f["opcode_hash"][0]] ^ 0xFF)),
        "flags": ("bad-flags", t.mutate(base, f["flags"][0], 8)),
        "source": ("source-mismatch", t.mutate(base, f["source"][0] + 4, ord("q"))),
        "trailing": ("trailing-bytes", resign(base[:-32] + b"\x00")),
        "bad_text": ("bad-text", t.mutate(base, body_at + 4, 0xFF)),
        "bad_opcode": ("bad-opcode", t.with_body(t.code_bytes(pool=t.NOTHING_POOL, instructions=[bytes((200,))]))),
        "bad_constant": ("bad-constant", t.with_body(t.code_bytes(pool=[bytes((99,))], instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")]))),
        "unknown_builtin": ("unknown-builtin", t.with_body(t.code_bytes(pool=[bytes((6,)) + t.name_bytes("now")], instructions=[t.op("LOAD_CONST", t.u32(0)), t.op("RETURN")]))),
        "slot_out_of_range": ("failed-verify", t.with_body(t.code_bytes(nslots=1, instructions=[t.op("LOAD_FAST", t.u32(5)), t.op("RETURN")]))),
        "stack_underflow": ("failed-verify", t.with_body(t.code_bytes(instructions=[t.op("POP"), t.op("RETURN")]))),
        "too_large": ("limit-exceeded", t.with_body(t.name_bytes("<module>") + t.u32(nl.ARTIFACT_LIMITS["slots"] + 1))),
    }
    rejected = []
    for name, (error, data) in sorted(damaged.items()):
        (OUT / "rejected" / (name + ".novac")).write_bytes(data)
        rejected.append({"name": name, "error": error})
    manifest = {"format": nl.ARTIFACT_FORMAT, "compiler": nl.__version__, "accepted": accepted, "rejected": rejected,
                "note": "Generated by tests/bytecode/make_fixtures.py; see its docstring before regenerating."}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(e["bytes"] for e in accepted)
    print("wrote {} artifacts ({:,} bytes) and {} damaged files to {}".format(len(accepted), total, len(rejected), OUT))


if __name__ == "__main__":
    main()
