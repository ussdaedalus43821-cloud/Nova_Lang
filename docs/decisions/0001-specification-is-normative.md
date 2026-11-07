# 0001: The specification is normative

Status: **Proposed**. Needed by the start of M9.

## Context

Today the Python implementation (`novalang.py`) is the only definition of
NovaLang. There are three Python engines (VM, tree-walker, self-hosted) that
are required to agree, and a GDScript port that is checked against a recorded
Python oracle. When a host disagrees with the reference there is no written
statement saying which one is wrong.

## Options

1. **The reference implementation is the definition.** Cheapest; bugs in the
   reference become the language. Other hosts can never be "right", only
   "matching".
2. **A written specification plus a conformance corpus is the definition.** The
   reference implementation is the first conforming host. A disagreement is
   triaged as a spec bug or an implementation bug.

## Recommendation

Option 2. A multi-host ecosystem needs a contract that is not tied to one
implementation, and the project already works this way informally (golden
files, a differential station, an oracle). Writing it down makes the process
explicit.

To keep this honest the corpus, not the prose, decides conformance: a spec
section with no corpus case is a gap to fix, and prose that contradicts the
corpus is a spec bug.

## Consequences

- M9 produces `docs/spec/` and `tests/conformance/`, and a divergence log.
- Changing language behavior means changing the spec and corpus in the same
  pull request.
- Language versioning (what is a major, minor or patch change) gets a written
  rule.

## Decision

_Not yet decided._
