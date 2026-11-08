# 0003: What NovaLang claims about security

Status: **Accepted** on 2026-11-08. Needed by the start of M11.

## Context

Several planned products (agents, connectivity, security services) would run
code written by someone other than the embedder. Today:

- `python.*` is a curated bridge with an import allowlist and explicit
  `expose()` registration. The README is clear that it is not unrestricted
  access, and the language runs inside the host Python process.
- File I/O, environment and process access are available to any script run
  directly.
- Resource limits (step budget, call depth) exist in the GDScript port; the
  Python engines have a call-depth limit only.
- Nothing has been independently reviewed.

## Options

1. **Claim a sandbox.** Rely on in-process capability checks and describe the
   result as a security boundary. Cheap to ship, and wrong if any escape
   exists. CPython gives no strong in-process isolation.
2. **Claim capability gating and resource limits, not isolation.** Deny by
   default, grant explicitly, bound resources, and say plainly that untrusted
   code should additionally run in a separate process or container. Provide an
   optional subprocess runner. Describe nothing as a security boundary until an
   independent review has happened.
3. **Make no security claim.** Document that scripts are trusted code.

## Recommendation

Option 2. It builds what can actually be tested (denial and grant per
capability, limits that trip on both engines), keeps the existing curated-bridge
rule in `CONTRIBUTING.md`, and refuses to over-claim. Option 3 closes off the
agent and connectivity products; Option 1 puts users at risk.

## Consequences

- M11 starts from a written threat model and ends with an escape-attempt
  station and an external review before any "boundary" wording is used.
- Existing behavior remains available as an explicit trusted profile so current
  embedders are not broken.
- Package manifests (M13) declare the capabilities they require.

## Decision

Accepted as recommended, by the project owner, on 2026-11-08: Option 2.
NovaLang claims **capability gating and resource limits, not isolation**.
Deny by default, grant explicitly, bound resources, test every denial and every
limit, and say plainly that code you did not write should also run in a
separate process or container. An optional subprocess runner is provided.
Nothing is described as a security boundary until an independent review of the
model has taken place.

Binding consequences for M11, in addition to those above:

- The threat model is written first, and states what is *not* defended.
- Each capability (file read and write by path, network, clock, environment,
  process, the Python bridge) has a test that proves it is denied and a test
  that proves a grant works, on every engine.
- Each resource limit (steps, call depth, collection and string size, output
  size, wall-clock time) has a test that it trips with the specified error on
  every engine.
- The existing, unrestricted behavior stays available as an explicit "trusted"
  profile.

Already done in line with this decision (NovaLang 2.1.0): the Python bridge is
off unless asked for (`--allow-python`, `Nova(allow_python=True)`), every access
to a Python object passes one gate that hides private names and modules that
were not granted, scripts cannot write to modules, classes or functions, and a
test walks every path the gate allows to look for a way out
([`../design/python-bridge-hardening.md`](../design/python-bridge-hardening.md)).
The call-depth limit exists on every engine; a step budget and a wall-clock
limit do not yet exist outside the game port.
