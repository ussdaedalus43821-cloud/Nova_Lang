"""Keeps the draft of chapter 17 (docs/design/m12-bytecode-spec-draft.md) in step with the compiler.

The opcode table of the draft is generated from novalang.OPCODES and novalang.STACK_EFFECT; this check reads the table back out of the
Markdown and fails if an opcode was added, removed, renumbered or given another stack effect without the draft being regenerated, if the
opcode-set hash printed in the draft is not the hash of the printed table, or if the draft refers to a section id it does not define.
It is the seed of the test slice 4 adds for the real chapter (M12 plan, slice 3)."""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
import novalang as nl  # noqa: E402

DRAFT = os.path.join(ROOT, "docs", "design", "m12-bytecode-spec-draft.md")


def rows(text):
    found = []
    for line in text.splitlines():
        m = re.match(r"^\| (\d+) \| `([A-Z_]+)` \| (`[a-z0-9]+`|-) \| ([^|]+) \| ([^|]+) \|$", line)
        if m:
            found.append((int(m.group(1)), m.group(2), m.group(3).strip("`"), m.group(4).strip()))
    return found


def run(check):
    with open(DRAFT, encoding="utf-8") as handle:
        text = handle.read()
    table = rows(text)
    check([name for _, name, _, _ in table] == nl.OPCODES and [n for n, _, _, _ in table] == list(range(len(nl.OPCODES))),
          "bytecode draft: the opcode table lists every opcode of novalang.OPCODES, in order, numbered from 0",
          "table has {} rows, OPCODES has {}".format(len(table), len(nl.OPCODES)))
    bad = []
    for _, name, _, effect in table:
        fixed = nl.STACK_EFFECT[name]
        if isinstance(fixed, int) and effect.split(" ")[0] not in (("%+d" % fixed) if fixed > 0 else str(fixed), "0"):
            bad.append((name, effect, fixed))
    check(not bad, "bytecode draft: every fixed stack effect in the table is the one in novalang.STACK_EFFECT", str(bad))
    kinds_used = {kind for _, _, kind, _ in table if kind != "-"}
    kinds_defined = set(re.findall(r"^\| `([a-z0-9]+)` \| (?:`u|a |two|`u8|`u32)", text, flags=re.M))
    check(kinds_used <= kinds_defined, "bytecode draft: every argument kind used in the opcode table is defined in the kinds table",
          str(sorted(kinds_used - kinds_defined)))
    canonical = "".join("{} {} {} {} r1\n".format(n, name, kind, effect) for n, name, kind, effect in table)
    stated = re.search(r"the hash is `([0-9a-f]{64})`", text)
    check(bool(stated) and stated.group(1) == hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
          "bytecode draft: the opcode-set hash printed in the draft is the SHA-256 of the printed table",
          "stated {}".format(stated.group(1) if stated else None))
    said = re.search(r"^(\d+) opcodes, numbered", text, flags=re.M)
    check(bool(said) and int(said.group(1)) == len(nl.OPCODES), "bytecode draft: the text says how many opcodes there are, and it is right")
    defined = set(re.findall(r"^## \[(bc\.[a-z]+)\]", text, flags=re.M))
    used = set(re.findall(r"`\[(bc\.[a-z]+)\]`", text))
    check(used <= defined, "bytecode draft: every section id the draft cites is a section it defines", str(sorted(used - defined)))
    questions = set(re.findall(r"`\[bc\.questions\]` (Q\d)", text))
    listed = set(re.findall(r"^\d\. \*\*(Q\d)\.", text, flags=re.M))
    check(questions <= listed, "bytecode draft: every question the draft refers to (Q1..) is listed under [bc.questions]", str(sorted(questions - listed)))


if __name__ == "__main__":
    failures = []

    def check(ok, label, detail=""):
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            failures.append((label, detail))
            print("     " + str(detail)[:400])
    run(check)
    sys.exit(1 if failures else 0)
