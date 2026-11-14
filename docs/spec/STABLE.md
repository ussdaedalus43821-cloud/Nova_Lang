# What is stable: the public surface and the versioning policy

Status: **policy, in force from the release that declares it (2.3.0, owner decision D11 of the
[M13 plan](../design/m13-libraries-and-registry-plan.md)); this file is not a specification chapter and has no
section ids.** What it promises is enforced by a test, not by good intentions: `tests/api/test_stable_surface.py`
compares the running interpreter with the recorded surface in `tests/api/stable-surface.json` and fails on a
removal or a change that has no new major version behind it.

## What is stable

| Surface | What is covered | Where it is written |
| --- | --- | --- |
| The language | chapters 1 to 8 and 16 of this specification: lexical rules, values, expressions, scoping, errors, statements, modules and the `restricted` profile | `docs/spec/` and the conformance corpus |
| The core library | every global built-in: its name, number of arguments, argument and result types, behaviour, and the text of its error messages | `09-library.md`, `10-host.md`, `tests/api/stable-surface.json` |
| The standard modules | each `std:` module whose tier is `stable`: its name, exports, signatures, behaviour and messages | `lib/std/modules.json`, the chapter that defines it |
| Capabilities | the names in `[sbx.capabilities]` and what each one gates: never removed or narrowed, but one can be added | `16-sandbox.md` |
| The embedding API | the public class `Nova` and the methods and arguments it has | `11-embedding.md` |
| The package manifest and lockfile | the `nova.json` and `nova.lock` fields that exist today (and their meaning); a file written for an older format keeps being read | `tools/nova-pkg.py` |
| The command line | the flags the sandbox accepts (`--profile`, `--allow-*`, `--limit`, `--deterministic`, `--seed`, `--clock-start`) | `tests/api/stable-surface.json` |

**Not stable**, and free to change in any release: the bytecode artifact format and the cache directory's layout
(`17-bytecode.md`: a file is accepted or cleanly refused, which is the only promise), the debug output of the cache,
anything whose name starts with an underscore, anything under `tools/` that no document describes, the contents
of `lib/` (the example libraries), and every `std:` module whose tier is `provisional`.

## The two tiers of a standard module

A module added to `lib/std/modules.json` is **`provisional`** in the release that adds it: its exports may change or
be removed in the next *minor* release, because nobody has used it in a real program yet. After one minor release
without such a change it can be promoted to **`stable`**, which is a change of one word in `modules.json` and an
update of the recorded surface. A provisional module is still listed in the recorded surface, so a change to it is
visible in review, but it does not need a new major version.

## What the version numbers mean

NovaLang is versioned `MAJOR.MINOR.PATCH`. The standard library ships with the interpreter and has no number
of its own.

| Change | Release |
| --- | --- |
| Removing or changing anything stable; narrowing a capability; changing an error message; a new keyword or a new reserved global name (a built-in name is reserved in every profile, so a program using it as a variable breaks); a program that parsed and ran no longer doing so | **major** |
| A new function in a `std:` module; a new module; a new capability that is off unless granted; a new optional argument; a new manifest field that has a default; a new syntax that used to be an error; relaxing a gate (as `replace_all` leaving the `regex` capability in M13) | **minor** |
| Making an implementation follow the specification where it did not (the specification wins, ADR 0001), a faster implementation, documentation | **patch** |
| A fix that has to break stable behaviour to close a hole in the `restricted` profile's capability gating or resource limits | **patch or minor**, with a changelog entry marked `security` that names the break. This is the one exception, and it is written here so that it is not a secret |

**One narrowing is declared here, not hidden.** In the release that adds `std:regex` the pattern language of `regex()` becomes the
dialect of `[lib.regex]`. Before it the specification said that more of the host's dialect "may work but is not portable", and
on the Python engines that meant everything `re` has; a program that used a back-reference, look-ahead, look-behind, an atomic
group, a possessive quantifier, a conditional group, a flag other than a leading `(?i)`, or an octal escape in a pattern now gets
`TypeError: regex(): bad pattern: <reason>`. By the table above that is a **major** change in the usual case; it is made in a
minor release because the specification never promised those constructs, the old behaviour was the host's and not the language's,
and the reason a pattern is refused names the construct and the way to write it. Every pattern in the dialect keeps its
meaning, and `$` still matches before a final line feed. This is the owner-accepted cost of decision D3 of the M13 plan
("the loss of backreferences and look-around"), and the changelog entry for the release must say it.

Two consequences follow. **New library functions go in `std:` modules, never in the global namespace,** because a
new global built-in is a major change; and **a program can rely on a stable name existing for the whole life of a major
version.**

## How a function leaves

1. **Announced:** it is listed in [DEPRECATIONS.md](DEPRECATIONS.md) with what replaces it, the release that
   deprecated it and the earliest release that may remove it, and in the changelog.
2. **Warned:** from that release a call prints one warning per call site and run to standard error. Standard output
   and the exit status do not change, so existing programs and their tests keep passing.
3. **Kept for a sunset:** at least two minor releases **and** at least six months, whichever is longer.
4. **Removed only in a major release,** with the migration in the changelog.

*State of the mechanism in this version: the policy and the list exist; the warning itself (point 2) is not
implemented yet, and nothing is deprecated, so nothing is owed. It is part of the foundations still to land
before 2.3.0 declares the surface (see the M13 plan, slice 1).*

## Changing the recorded surface

`python3 tests/api/test_stable_surface.py --update` rewrites `tests/api/stable-surface.json` from the source. The
rewrite goes in the same change as the code, so the diff of that file is what a reviewer reads. The test fails if the
file is out of date, and **it also fails on a removal or a change to a stable item while the major version is the
one the record was written for**, whatever the record says.
