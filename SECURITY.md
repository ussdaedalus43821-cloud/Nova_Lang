# Security policy

## Reporting a vulnerability

**Please do not open a public issue, pull request or discussion for a security
problem.** Report it privately instead:

1. Go to the repository's **Security** tab and choose **Report a vulnerability**
   (GitHub private vulnerability reporting). Only the maintainers can read the
   report.
2. Describe what you found, with the smallest NovaLang program or embedding code
   that shows it, the engine you ran it on (the bytecode VM, the tree-walker,
   the self-hosted interpreter with `--bootstrap`, or the GDScript port), the
   NovaLang version or commit, and your Python version and operating system.

You will get an acknowledgement within 7 days. We will then confirm whether we
can reproduce it, tell you what we plan to do and roughly when, and credit you
in the changelog when the fix ships, unless you prefer not to be named. Please
give us a reasonable chance to fix the problem before you disclose it publicly.

## What counts as a vulnerability

NovaLang does not claim to be a sandbox. Its position is written down in
[ADR 0003](docs/decisions/0003-security-stance.md) and
[the sandbox specification](docs/spec/16-sandbox.md): capability gating and
resource limits, not isolation, and nothing is described as a security boundary
until it has been independently reviewed. Untrusted code should still run in a
separate process or container.

So the reports that matter most are the ones that break a promise NovaLang does
make:

- a program reaching a capability that was denied (files, environment,
  processes, the network, the `python.*` bridge) without being granted it, on
  any engine;
- a way round the curated `python.*` bridge, such as reaching a name starting
  with `_` or a module that was not exposed;
- a resource limit (step budget, call depth, repetition or size limits) that
  fails to stop a program, or an input that crashes the interpreter host
  instead of raising a NovaLang error;
- two engines disagreeing in a way that turns a denial into a grant;
- a package, lockfile or integrity-check bypass in `nova-pkg`.

A script that does something harmful when you run it directly with full
permissions is working as designed. If you are unsure, report it anyway.

## Supported versions

Fixes go into the latest release (currently 2.2.x) and the `develop` branch.
Older releases are not patched.
