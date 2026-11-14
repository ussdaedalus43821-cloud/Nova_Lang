# M13 plan: libraries, registry and API stability

Status: **Plan, decisions D1 to D12 accepted by the owner on 2026-11-13 (recorded in section 9). Nothing is implemented.** Written 2026-11-13. It follows
[ROADMAP M13](../ROADMAP.md) (goal, deliverables, exit criteria, and "Requirements from the Proof-of-Concept Apps") and takes the lessons of M11 and M12 as
constraints. It is not independently reviewed. **One change from the draft: D6 is decided as "defer", and the HTTP slice (slice 7, sections 4.7 and the `net`
capability) moves to M14.** M13 is therefore six slices; sections 4.7 and slice 7 stay in this document as the design M14 starts from, not as M13 scope.

## 1. What M13 is for

Make it safe for other people, and other Nova products, to depend on NovaLang: a standard library that closes the debts the four proof-of-concept apps
recorded, a package registry whose packages cannot take more than they declared, and a promise about what will not change. Four pillars:

1. **The standard library:** the libraries the proof-of-concept apps needed and had to hand-write (section 4).
2. **NovaForge, the registry:** a manifest, a registry protocol, publishing and installing, and a threat model for the supply chain (section 5).
3. **API stability and deprecation:** what is stable, what the version numbers mean, how a function leaves (section 6).
4. **The slices:** seven pull requests (section 7).

### Rules this plan inherits (the "stop the line" rules of M11 and M12)

* **The specification comes first and is normative** ([ADR 0001](../decisions/0001-specification-is-normative.md)). A library or a manifest field exists when a section of
  `docs/spec/` says what it does, and a section is not normative until conformance cases cite it and an engine passes them.
* **Three engines.** The bytecode VM, the tree-walker and the self-hosted interpreter (`novalang.nova`) must agree, or the divergence is recorded
  (`docs/spec/DIVERGENCES.md`). Every new built-in is added to `BUILTINS` in `novalang.py` and to the built-in tables of `novalang.nova` (names, arities, capabilities, path and
  limit checks), unless it is written in NovaLang, in which case there is one implementation.
* **Every capability has a denial case and a grant case on every engine; every limit has a trip case** ([`16-sandbox.md`](../spec/16-sandbox.md), the coverage matrix of
  `tests/security/`). A new capability or limit is not done until the matrix is full.
* **Wording.** `restricted` is capability gating and resource limits, not isolation ([`[sbx.claims]`](../spec/16-sandbox.md), ADR 0003; `tests/security/test_wording.py`
  reads every Markdown file). Nothing in M13 changes that, and a package's declared capabilities are a consent and review mechanism and a static check, never a guarantee about
  what the package does with a grant.
* **No imaginary completion.** A slice is done when its done-when is shown by a test, in the proof-of-concept app that asked for it where there is one.
* **CI is the product.** Windows 3.12 is required and Windows 3.7 is a probe that must not regress; the Linux rows run 3.7 to 3.13 ([`docs/CI.md`](../CI.md)).
* **No install-time code execution, ever.** A package is data and `.nova` source. There are no install scripts, hooks or build steps, and the manifest has no field that could name one.

### Non-goals

* A native runtime, a faster VM, or anything of slice 6 of M12 (deferred by the owner), except the one fix of G-051 that a registry makes necessary (section 7, slice 1).
* Changing the meaning of an existing program. M13 is additive until the stable surface is declared, and after that it is additive or it is a major version.
* Operating a public registry (decision D8). M13 builds the protocol and a reference implementation and tests them end to end; running one for the world is a separate decision.
* A language change to operators, literals or syntax (`+=`, a conditional expression, multi-line strings, an exponent literal). They are recorded in appendix A as deferred, with the reason.

## 2. Where things stand (facts, checked in the source and the four repositories)

* **The gaps.** Fifty entries from the four proof-of-concept apps (G-001 to G-050, each app's `docs/GAPS.md`; `docs/GAPS.md` of this repository holds only the two found in
  M12, G-051 and G-052). Appendix A gives each a disposition.
* **No `Nova_Git` exists.** The brief for this plan names an `http` client "for the `Nova_Git` PoC". There is no such repository on this computer, none in the register, and no
  gap anywhere asks for HTTP. It is in the roadmap's M13 deliverables ("standard-library additions that need the outside world (HTTP, richer time zones, structured data validation)")
  as an anticipated need. Decision D6 is about that.
* **How a built-in exists today.** A function is a `BuiltinFunction` in `BUILTINS`; names are **reserved in every profile** (`let find = 1` is refused if `find` is a built-in), so
  **adding a global name is a breaking change** for any program that used it as a variable (G-016); a name belonging to a capability is *undefined* when the capability is not granted
  (`CAPABILITY_OF`: `files.read`, `files.write`, `env`, `clock`, `random`, `stdin`, `process`, `regex`, plus `import` and `python` as grants); the self-hosted engine keeps its own tables
  in `novalang.nova` and calls the host's implementation for most functions.
* **No network capability exists** ("There is **no network capability**: NovaLang has no network built-in", `[sbx.capabilities]`). A program reaches a network only through a Python
  module the embedder granted under `python`.
* **`regex` is Python's `re`.** `regex(pattern, text)` is `re.search(pattern, text, re.ASCII) is not None`; the specification fixes a portable subset and says a pattern can take
  exponential time and the language puts no limit on that. That is why `regex` is a capability, and why `replace_all`, a plain substring replacement that happens to share the
  group, is unavailable to a `restricted` program (G-050).
* **`read` is the only way in.** It builds one string, a `restricted` string stops at 1,000,000 characters, and a `for` loop builds its whole item list first (`ITER_PREP` /
  `iteration_items`), so no lazy source exists (G-036, G-041).
* **A package manager already exists** (`tools/nova-pkg.py`, 588 lines, `docs/spec` has no chapter for it yet): a `nova.json` manifest (`name`, `version`, `registry`, `main`,
  `dependencies`), version ranges (`1.2.3`, `^`, `~`, `*`), three sources (a version from a registry **that is a directory** laid out as `<registry>/<name>/<version>/`, a local `path`,
  a `git` url with a ref), a flat install into `.nova_modules/`, a `nova.lock` with the version, the source (a git commit, not a ref) and **a SHA-256 over every file's path and bytes**,
  `install`, `install --frozen` and `verify`. At run time `import "name"` walks up to `.nova_modules/<name>/nova.json`, and **refuses a project whose `nova.json` or `nova.lock` changed
  since the last install** (it compares texts; **it does not re-hash the package files at import**: a file edited inside `.nova_modules` after the install is found only by `verify`).
  The registry named by a manifest comes from the root project's manifest or `NOVA_REGISTRY`, not from a dependency's.
* **Not there:** a remote registry, `publish`, signatures, revocation, capabilities in the manifest, a deprecation mechanism, a declared stable surface, a published semantic-versioning policy.
* **The bytecode artifact and its cache exist** (M12): a module's compiled code, with the source, can be loaded and verified; `LOAD_BUILTIN` names every gated built-in a module refers to,
  which is what makes section 5.6 precise.

## 3. The design rules of M13

1. **Three tiers of library, in order of preference.**
   * **Tier 1: pure NovaLang modules** shipped with the interpreter (`import "std:decimal" as decimal`). No capability, no new attack surface, one implementation that runs on all three
     engines and under `restricted`, deterministic. The default for anything that can be written in NovaLang at an acceptable speed (`lib/ecs.nova` and `lib/spatial_hash.nova` are the precedent).
   * **Tier 2: native modules** (`std:regex`, `std:files`): functions in Python reached through a module object, needed when NovaLang cannot do the work (the file system, a matcher fast
     enough to be useful). Each member is gated by a capability or by none, and exists in all three engines' tables.
   * **Tier 3: modules that reach outside the machine** (`std:http`): a new capability, with a grant that names what may be reached, and limits.
2. **Namespaces, not global names.** A `std:` module is bound to a name the importer chooses (`import "std:decimal" as d`); nothing in it is reserved. After the stable surface is declared
   (slice 1), **no new global built-in is added** except by a major version. This turns G-016 from a trap into a rule.
3. **A module declares the capabilities it needs; the import fails if the run did not grant them.** One mechanism for `std:` modules and for packages: a descriptor lists the capability
   names; `import` of a module whose capabilities are not all granted is `ImportError: <module> needs the 'files.read' capability, which this run did not grant`, at the import,
   not later as `undefined name 'read'`. (Section 5.6.)
4. **Declared and used must match, and they are compared by machine.** A module's use of a gated name is visible statically (a gated name is `LOAD_BUILTIN` in compiled code, a name in the
   source), so a package that uses a gated built-in it did not declare is refused. There is no dynamic code and no reflection to hide a name behind ([`05-security.md`](../spec/05-security.md)).
5. **Exact, explicit and bounded.** A library that can be inexact asks for the rounding it wants; one that can be slow or large has a limit counted in the run's steps and sizes, so the
   time limit, the deterministic mode and the three engines agree.
6. **Provisional before stable.** A new library is `provisional` for one minor release (it may change in the next minor) and then `stable` (section 6).

## 4. Pillar 1: the standard library

### 4.0 The module mechanism (slice 1)

* **`import "std:NAME" as alias`** resolves to a module shipped with the interpreter: a NovaLang file under `lib/std/` (Tier 1), or a native module object (Tier 2/3). `std:` is a reserved
  prefix: no package can be named `std`.
* **Capabilities.** Each `std:` module has a descriptor (name, version tier, capabilities, the names it exports); the import checks the capabilities against the run's grants. `std:` modules are
  readable under `restricted` **without** the `import` grant (they are part of the interpreter, hashed with it), and **a package's import of another folder still needs `import`**.
* **Engines.** The VM and the tree-walker share the loader; the self-hosted interpreter gets the same resolution rule in `novalang.nova` (small), and the conformance cases of each library
  run on all three.
* **Artifact cache.** Tier 1 modules are cached like any module (keyed on their text).

### 4.1 Triage of the five (and the others the brief and the roadmap name)

| Rank | Library | Evidence | Tier | New capability | Slice |
| ---: | --- | --- | --- | --- | ---: |
| 1 | **`std:decimal`** (with `std:math`, `std:format`) | G-044 (the central finding), G-043, G-045, G-048, G-008; Nova_Data had to parse money by hand | 1 | none | 2 |
| 2 | **`replace_all` leaves the `regex` capability** (and `std:text`) | G-050, G-006, G-037, G-002, G-039; hit by Nova_Data, found by its own tests | 1 / 2 | none (removes a gate) | 1 |
| 3 | **Streaming reads** (`std:files`) | G-036, G-041, G-042; a 1.5 MB log cannot be read under `restricted` at all | 2 | none (`files.read`) | 3 |
| 4 | **`std:regex`** with captures | G-003; every extraction in the four apps is `split` plus slicing | 2 | `regex` (kept at first, see D3) | 4 |
| 5 | **`std:http`** | no gap; the roadmap anticipates it; no `Nova_Git` exists | 3 | `net` (new) | 7, if D6 says yes |

Ranks 1 to 4 are the proof-of-concept requirements of the roadmap, in the order of their dependencies, not of their cost; rank 5 is the only one with no recorded demand and the only one that
adds a whole new kind of reach. The roadmap's second requirement (number formatting, G-008) is **not in the brief's list**; this plan keeps it, inside `std:format` (4.3), because it shares
its rounding with decimals; decision D10 lets the owner drop it.

### 4.2 `std:decimal` (Tier 1, slice 2)

**What it is.** Exact base-10 arithmetic on values written in NovaLang over integers (which are exact at any size, G-001). A decimal is an opaque value made by the module's functions: a
list `[unscaled, scale]` whose layout is not part of the API (the functions validate every argument, so a hand-made list is refused or means what it says). **It has no operators**: NovaLang has
no operator overloading, so `a + b` on decimals stays an error; adding a decimal *type* with operators and a literal is a language change, decision D2.

**API (all in `import "std:decimal" as dec`):**

| Function | Meaning |
| --- | --- |
| `dec.parse(text)` | the decimal written in `text`: optional sign, digits, optional `.` and digits (`-1250.50`, `.5`, `7.`); no exponent, no separators, no spaces; **an error** `ValueError`-style `NovaError` for anything else |
| `dec.try_parse(text)` | the same, or `nothing` |
| `dec.from_int(n)`, `dec.from_float(x, places, mode)` | from a whole number; from a float **with explicit places and mode** (never an implicit conversion) |
| `dec.add(a, b)`, `dec.sub(a, b)`, `dec.mul(a, b)` | exact; the scale of the result is large enough for the exact answer; never rounds |
| `dec.div(a, b, places, mode)` | `a / b` rounded to `places` digits after the point by `mode`; **places and mode are required** (no silent inexact result); division by zero is an error |
| `dec.quantize(a, places, mode)` | `a` rounded to `places` digits |
| `dec.negate(a)`, `dec.absolute(a)`, `dec.sign(a)` | (not `neg`, `abs`: a built-in's name cannot be exported, G-016) |
| `dec.cmp(a, b)` | -1, 0 or 1; `dec.eq`, `dec.lt`, `dec.le` as conveniences; plus `dec.is_decimal(a)` and `dec.scale(a)` |
| `dec.to_string(a)` | the canonical text: no exponent, the scale kept (`1.50` stays `1.50`), `-0.00` never printed |
| `dec.to_int(a, mode)`, `dec.to_float(a)` | rounded to a whole number; the nearest float |
| `dec.total(list)` | exact sum (not `sum`: a built-in's name) |

**Rounding modes** (strings): `"half_even"`, `"half_up"` (ties away from zero), `"half_down"`, `"up"` (away from zero), `"down"` (towards zero), `"floor"`, `"ceiling"`. Names, not numbers, so a
wrong one is an error.

**Bounds.** A decimal has at most 4,000 digits (the integer limit of `[port.integers]`); a scale is between 0 and 1,000 (no negative scale: nothing needed one); going over is an error, never infinity or a rounded value.

**`std:math`** (also Tier 1 where it can be, native where it cannot): `math.trunc(x)` (towards zero, G-045), `math.divmod(a, b)` (the floor pair of `//` and `%`, with the sign rule written down),
`math.round_half(x, places, mode)` for floats (G-043: `round` stays half-even, it is specified), `math.exp(x)` (G-018). They live in a module, not as global names (rule 2).

**Sandbox integration.** None: pure functions of their arguments, available in every profile, deterministic, counted in steps like any NovaLang code.

**Done when** (the roadmap's wording): Nova_Data's `parse_cents`, `money` and `div_round` are replaced by the library and its oracle comparison (every number in the report against Python
`Decimal`) still passes, on the three engines, and the 10,000-row sample still runs under `restricted` with the default limits.

**Risks.** Speed: NovaLang runs about 2.5 million instructions a second, and a hand-parse of money costs about 70 instructions; the library is allowed to cost up to twice that per call (a
benchmark row in `tests/benchmarks/` makes it visible, and a native `std:decimal` tier is the fallback if it does not). Mixed-type bugs: no operator ever accepts a decimal, so `dec + 1` is `TypeError`, not a wrong answer.

### 4.3 `std:format` (Tier 1, slice 2; decision D10)

`fmt.fixed(x, places)` (a float or an integer to a fixed number of places, half-even like `round`, **always** with the places: `5` -> `5.00`), `fmt.grouped(n, sep)` (thousands separators, G-007),
`fmt.pad_zero(n, width)`, `fmt.fixed_dec(a, places, mode)` for decimals, and one documented rule for how `str()` prints a float (**not** changed in M13: that would be a breaking change to existing
output; the rule is documented and `fmt` is the way out). Closes G-007, G-008, and gives G-048's problem (`1e-07` printed, unreadable by `num()`) a documented route (`fmt.fixed`). G-052 (an overflowing
float literal is infinity) is decided here: the lexer keeps accepting it, and the stable surface says so (a lexer change would break programs that compile today).

### 4.4 `replace_all` and `std:text` (slice 1)

* **G-050:** `replace_all` moves out of `CAPABILITY_OF`: it becomes available in every profile. This is a **relaxation**, so it is additive; the matrix cell `regex:deny` for `replace_all` is removed and a
  case "a restricted program with no grants calls it" is added on all three engines. The name was already reserved, so nothing else changes.
* **`std:text`** (Tier 1 unless noted, optional scope D10): `text.find(s, sub, start)` -> index or -1, `text.starts_with`, `text.ends_with` (G-006, G-037), `text.is_number(s)` and `text.parse_number(s, default)`
  (G-002, G-039: `num` keeps throwing), `text.chr(n)` and `text.ord(s)` (native, so **moved to slice 3**; G-004, G-005: the way to write an escape character, with the output-injection note that a terminal program that prints an
  `ESC` can do what the terminal lets it do), `text.splitext(path)` and `text.basename(path)` (G-031).

### 4.5 Streaming reads: `std:files` (Tier 2, slice 3)

**The problem.** `read` makes one string; under `restricted` a string stops at 1,000,000 characters; a `for` builds its whole list. G-036 (a real log cannot be read in the sandbox), G-041
(a 50 MB file is 212 MB of strings), G-042 (the wall-clock time limit makes the slow self-hosted engine process 250 rows where the VM does 25,000).

**API (`import "std:files" as files`; capability `files.read`, so the import needs the grant):**

| Function | Meaning |
| --- | --- |
| `files.lines(path)` | a **line source**: used in `for line in files.lines(path) { ... }`, it yields one line at a time (the line end removed, `\r\n` handled as `split_lines` does) and holds one line in memory |
| `files.size(path)` | the size in bytes (a file the program may read) |
| `files.is_dir(path)`, `files.is_link(path)` | G-030, G-032: what `listdir` and a path check already know, exposed; `is_link` is judged without following the link |
| `files.read_chunk(path, offset, length)` | a text chunk (bounded by the string limit), for programs that want to page |

**The line source** is a new kind of iterable, valid **only** as the iterable of a `for` (it cannot be stored in a list or a dictionary and printed it shows `<lines path>`). It is **restartable and
holds no handle**: each chunk of 64 KiB is read by opening the path, seeking, reading and closing, and **every open goes through the same path check as `read`** (`[sbx.paths]`: the grant is re-checked, links
are not followed out of the grant), so a file replaced between chunks is judged again, and nothing is left open when a loop is left by `break`, by an error or by the end of the program. A line longer
than the string limit is an error (`a line cannot be longer than 1000000 characters`), not truncation. Each pass of the loop is a step, as any loop pass is; each chunk read is charged to the output-size
accounting like `read` (decision D5 for time).

**Engines.** `ITER_PREP` accepts the line source (a `[source, offset, buffer]` state like the range state); the tree-walker's `for` and the self-hosted interpreter's `for` need the same case; the
conformance cases run on all three. The compiled code is unchanged (a call and a `for`), so artifacts and the cache are unaffected.

**Deterministic time (G-042, decision D5).** A wall-clock limit cannot give the same answer on a slow engine. Options: keep it and document, or add a **cost model** (each instruction a step, each library call
a number of steps by input size) and a limit expressed in steps that every engine reaches at the same program point. The roadmap lists it; this plan treats it as the largest and least certain item of the slice
and recommends making it a separate decision.

**Done when:** Nova_Log's 50 MB log runs under `restricted` with the default limits (roadmap), on the VM; and on the tree-walker and self-hosted engines it runs on a smaller file with the same
counts as the oracle.

### 4.6 `std:regex` (Tier 2, slice 4)

**The problem and the design question.** `regex` returns only true or false (G-003). Adding captures to Python's `re` is a few lines and **expands the one attack the sandbox cannot stop**: catastrophic
backtracking in C, which no in-process limit can interrupt (`[sbx.capabilities]`, `regex`), which is why the capability exists and why the subprocess runner exists. A pattern that is safe on one host
(`re`) is also not portable to the self-hosted engine, a future native runtime or a WebAssembly host. So the proposal is **a specified dialect with a matcher that cannot take exponential time**.

**The dialect (decision D3).** RE2-class, written in `[lib.regex]`: literals and escapes; `.` (any code point but a line feed); classes `[a-z]`, `[^0-9]`, `\d \w \s \b \D \W \S \B` **ASCII only** (as D-021
already says); anchors `^ $`; groups: capturing `( )`, non-capturing `(?: )`, named `(?P<name> )`; alternation `|`; greedy and lazy quantifiers `* + ? {m} {m,} {m,n}` and `*? +? ??`; the flag
`(?i)` (ASCII case folding). **Not in the dialect, and refused with a named error:** back-references, look-ahead and look-behind, atomic groups, possessive quantifiers, recursion, conditionals, Unicode
properties. Leftmost-first semantics, as Perl and RE2 (the first alternative that lets the whole pattern match wins), so results agree with Python's `re` on the common subset and can be fuzzed against it.

**The matcher.** A Pike virtual machine (a Thompson NFA run in lock step): time is `O(pattern size x text length)` whatever the pattern, memory is one thread list per position. **It runs in Python, charged to the
run's steps** (a unit of cost per thread per character), so the time limit, the output limit and the deterministic mode apply, and no pattern can run for ever. Nothing in it calls `re`.

**API (`import "std:regex" as re`):**

| Function | Meaning |
| --- | --- |
| `re.test(pattern, text)` | the old `regex(pattern, text)`, with the specified dialect |
| `re.match(pattern, text)` | the first match anywhere, or `nothing`; a match is a dictionary `{"start": i, "end": j, "text": s, "groups": [s or nothing, ...], "named": {"name": s or nothing}}` (character offsets) |
| `re.find_all(pattern, text, limit)` | a list of matches (non-overlapping, left to right; at most `limit`, default 10,000) |
| `re.sub(pattern, replacement, text, count)` | replace the first `count` (default all); `\1`, `\g<name>` and `\\` in the replacement |
| `re.split(pattern, text, limit)` | the pieces between matches |
| `re.escape(text)` | the text with every character the dialect treats specially escaped |

The existing global `regex(pattern, text)` **stays, unchanged in signature**, and gains the specified matcher; it is on the stable surface (section 6).

**Limits (new, all lower-only by the embedder):** pattern length 4,000 characters; at most 1,000 groups; repeat counts at most 1,000 and a pattern that expands past 20,000 instructions is refused; a call's text is bounded by
the string limit; `find_all` and `split` results by the list limit. A **bad pattern** is `TypeError: regex(): bad pattern: <reason>` as today.

**Capability.** Kept as `regex` at first (the rule of `[sbx.capabilities]` stays true: the matcher is new and unproven). **Relaxing it** (making the library available in every profile, as `replace_all` becomes) is
proposed for the minor release after the engine has run the fuzzers of slice 4 for a release without a finding; the reason the capability existed (an uninterruptible run) would be gone, and the relaxation is additive.

**Tests.** A differential fuzzer against Python's `re` on the shared subset (random patterns and texts, compared on match, span and groups); a time test (patterns known to be exponential in `re`, such as `(a+)+$`,
finish in a bounded number of steps); the Nova_Log done-when.

**Done when** (roadmap): the status-code extraction in Nova_Log (two strategies and a hand-written validity check) is one pattern and its 29 tests still pass.

**Risk.** Speed: a Python Pike VM will be slower than `re` by a large factor; the benchmark suite measures it (a row on the 5 MB log) and the owner decides whether a fast path through `re` for patterns proven free of nested
quantifiers is worth its complexity. The risk accepted by this plan is that a slow safe matcher is better than a fast one that can hang.

### 4.7 `std:http` (Tier 3, slice 7; decision D6: deferred to M14, kept here as the design M14 starts from)

Specified here because the brief asks for it; **recommended last and conditional** (D6): no recorded demand, the largest new attack surface of M13, and it shares its hardened fetch core with the registry client of
slice 6, so it costs least after that slice.

**Capability `net`.** Grant: **hosts**, as `--allow-net HOST[:PORT]` (repeatable) and `net: ["host", "host:8443"]` in the embedding API; exact host names (no wildcards, no IP literals unless the embedder names that literal and passes
the private-address override of `[net.private]`). Absent: `std:http` cannot be imported (`ImportError: std:http needs the 'net' capability`). `[sbx.capabilities]`'s sentence "there is no network capability" is replaced, and that chapter
(owner- and architect-reviewed) gets a dated, unreviewed amendment like threat T17 did.

**API (`import "std:http" as http`):**

| Function | Meaning |
| --- | --- |
| `http.get(url, options)` | an HTTPS GET |
| `http.post(url, body, options)` | an HTTPS POST of a text body |
| result | `{"status": 200, "headers": [["name", "value"], ...], "body": "..."}`; header names lower-cased; the body decoded as UTF-8 with replacement; binary bodies are not supported in the first version |
| `options` | `{"headers": [[name, value], ...], "timeout_ms": n}`; nothing else |

**Rules, each a case:** HTTPS only (an `http:` URL is an error); the host must be granted exactly; **certificates are verified** with the platform's trust store and cannot be turned off; the host name is resolved once and
**the connection is pinned to that address** (defence against DNS rebinding); **addresses in loopback, private, link-local, multicast and unspecified ranges are refused** (SSRF, including the cloud metadata address) unless
the grant names that literal address; **no redirect is followed** by default, and with `{"follow": true}` each hop is checked against the grant and the rules again, at most 5; no cookies, no environment proxies (`HTTP_PROXY` is ignored), no
automatic decompression beyond what the response declares and the size limit still bounds; request headers are validated (no CR or LF, no `Host`, `Content-Length` or `Transfer-Encoding`); a response is read up to the size limit and the rest is an error, not
truncation.

**New limits (lower-only):** `net_bytes` (a response, default 10 MiB), `net_time` (one request, default 10,000 ms, never more than the run's remaining time), `net_requests` (default 100 per run). Each request is a step plus its bytes to the
output-size accounting. **Deterministic mode** denies `net` always.

**What the interpreter cannot stop:** a blocking socket call cannot be interrupted by the in-process limits except through its own timeout, so `net_time` is a socket timeout and the subprocess runner (`--isolate`) remains the way to stop a run from
outside. A granted host is trusted with whatever the program sends it: a program with `files.read` and `net` can send any readable file to a granted host, which is exactly what a grant means; the matrix and the review must say so in those words.

## 5. Pillar 2: NovaForge, the package registry

### 5.1 What exists and what is added

Section 2 lists what `nova-pkg` does today. M13 adds, in this order and without breaking a manifest or a lockfile that works today: capabilities in the manifest and their enforcement (slice 5), then the registry protocol,
publishing, signatures and revocation (slice 6).

### 5.2 The manifest, `nova.json` (version 2)

```json
{
  "name": "acme/ledger",
  "version": "1.4.2",
  "description": "Double-entry bookkeeping over std:decimal",
  "license": "MIT",
  "authors": ["Ada Lovelace <ada@example.org>"],
  "repository": "https://example.org/acme/ledger",
  "nova": ">=2.3.0 <3.0.0",
  "main": "main.nova",
  "files": ["main.nova", "src/**/*.nova", "README.md", "LICENSE"],
  "capabilities": ["files.read"],
  "dependencies": {
    "acme/money": "^2.0.0",
    "local-lib": {"path": "../local-lib"}
  },
  "policy": {"capabilities": ["files.read", "clock"]}
}
```

| Field | Rule |
| --- | --- |
| `name` | **`owner/name`** for anything published (D4); lower case letters, digits, `.`, `_`, `-`; an unscoped name stays valid for local, path and git packages. `std` and `nova` are reserved owners |
| `version` | `MAJOR.MINOR.PATCH`, no pre-release suffix in the first version of the protocol (D11) |
| `nova` | the NovaLang versions the package works with (same range syntax as dependencies); `install` refuses a package whose range excludes the running version |
| `main` | the entry file (default `main.nova`) |
| `files` | the allowlist `publish` packs; **anything else is not in the package**; only `.nova`, `.json`, `.md` and `LICENSE`/`NOTICE` files are accepted |
| `capabilities` | the closed list of capability names the package's own code uses: `files.read`, `files.write`, `env`, `clock`, `random`, `stdin`, `process`, `regex`, `python`, `net`; **required, not optional** (the import fails unless all are granted). A package that names none uses none |
| `dependencies` | as today, plus scoped names |
| `policy.capabilities` | *root project only*: the most a dependency may require; `install` refuses a graph that asks for more (5.6) |
| `registry` | *root project only*, as today; a dependency's `registry` is **ignored** (a rule, with a test: a dependency must not be able to redirect where the next dependency comes from) |
| anything else | unknown keys are an error unless they start with `x-`; **there is no field for scripts, hooks or commands** |

Messages follow the style of `nova-pkg` today: what is wrong, what to do.

### 5.3 The lockfile (version 2)

Lockfile version 1 is read, and rewritten as version 2 on the next `install`. Each package entry gains: `capabilities` (as declared), `resolved` (the registry and the archive's address), `integrity` (the SHA-256 of the **archive**, new, next to the existing hash of the
unpacked files), and `signedBy` (key ids). **No timestamps**, so a lockfile is reproducible. `install --frozen` refuses any change, including a change of a package's capabilities.

### 5.4 The registry protocol (a static index; D7)

A registry is a tree of files served by anything that serves files over HTTPS, or a directory (`file://` and a plain path, as today):

```
<root>/registry.json                    signed: the registry's name, its serial, its expiry, the key ids that sign it
<root>/index/<owner>/<name>.json        signed: every version: archive hash, size, nova range, capabilities, yanked flag
<root>/archive/<owner>/<name>/<version>.tar      a deterministic archive (sorted entries, zero times, fixed modes, no links)
<root>/revoked.json                     signed: key ids and archive hashes that must not be used, with a reason
```

* **Deterministic archives** (ustar, entries sorted by path, mtime 0, mode 0644, owner 0): the same files give the same bytes, so a hash means something and anyone can rebuild a package and compare.
* **The metadata is signed, the archives are pinned by hash.** The signature covers the index, which carries each archive's SHA-256; the lockfile carries the same hash. A tampered archive fails the hash; a tampered or replayed index fails the signature, the **serial** (the client
  remembers the highest serial it has seen and refuses a lower one: rollback) or the **expiry** (a registry that stops being updated stops being trusted: freeze).
* **Signatures: Ed25519**, verified in Python's standard library only. The standard library has no Ed25519, so the verifier is about 120 lines of pure Python (RFC 8032), tested against its published vectors and, where `openssl` or `cryptography` exist, cross-checked in CI; slowness is irrelevant (a handful of
  verifications per install). Decision D8 says who holds the keys.
* **Publishing** writes to a directory registry (or a git repository that serves one): `nova-pkg publish` produces the archive, the index entry and the signature and writes them; **an HTTPS registry is written by whoever operates it**, not by a protocol the tool speaks in M13 (no upload API to attack, no token to leak).
* **Immutability.** A published version is never changed or deleted; the only operations are `yank` (still downloadable by an exact lock, not chosen by a range) and `revoke` (refused everywhere).
* **Trust roots.** The keys a client trusts come from a file shipped with `nova-pkg` for the public registry and from the root `nova.json` (`"registryKeys"`) for others; a key changes only by a signed rotation in `registry.json`.

### 5.5 The supply-chain threat model

Assets: the user's machine and data, the programs that import packages, the publisher's identity, the registry's integrity. Actors: a malicious publisher, a publisher whose account was taken, a malicious maintainer of a trusted package, a network attacker, a compromised registry host or mirror, a careless user. **Not defended** (stated first, as the M11 model does): a package that does what its declared capabilities allow, with
a grant the user gave it; a malicious dependency in a project that grants everything; the contents of a package that nobody reads; the Python interpreter and the machine NovaLang runs on.

| # | Threat | Defence in this plan | Proved by | Residual |
| ---: | --- | --- | --- | --- |
| R1 | **Typosquatting** (`acme/ledgr`) | owner-scoped names; a publish-time check refuses a name within edit distance 1 of an existing name of another owner, and a name that differs only in case, `-`/`_`/`.`; `install` shows the owner | cases for the check | a squat the check does not catch; a user who types the wrong owner |
| R2 | **Dependency confusion** (a private name published publicly) | a root project names its registry and **a dependency's `registry` is ignored**; scoped names; a package from a registry is never silently replaced by one with the same name from another source | a test with two registries | a user who lists the wrong registry |
| R3 | **Account takeover, then a malicious new version** | a new version that **adds a capability** is not installed by `install` without `--accept-capabilities`; the lock pins the old one; `audit` lists every capability change since the lock | test: a version adds `files.write` | a malicious version that adds nothing the user's grants do not already allow |
| R4 | **A malicious maintainer / protestware** | the same, plus yanking and revocation; immutable versions (so nothing is silently replaced) | revocation test | the first install of a bad version |
| R5 | **A network attacker alters an archive or an index** | HTTPS with certificate verification; archive SHA-256 in the signed index and in the lock; the index is signed | tamper tests on every file of a registry | a client that turns verification off (there is no switch) |
| R6 | **A compromised registry host or mirror** | signatures by keys the host does not hold; hash pins; the client trusts keys, not hosts | a test with a registry whose files were all altered | a compromised **signing key**: rotation and revocation of keys, and D8 |
| R7 | **Rollback** (serving an old index with a known-bad version) | the serial must not decrease | test | a client with no state (first run) |
| R8 | **Freeze** (serving a stale index for ever) | the signed expiry | test with an expired registry | up to the expiry window |
| R9 | **Mix and match** (an index from one time, archives from another) | the index pins each archive's hash | test | none known |
| R10 | **A malicious archive** (path traversal, links, device files, huge or many files, a decompression bomb) | the extractor takes **regular files and directories only**, rejects any name that is absolute, has `..`, a drive letter, a backslash or a NUL, rejects links, enforces limits (file count 2,000; one file 1 MiB; total 16 MiB; path 255 bytes), extracts to a fresh directory and renames it into place, and never executes anything | a corpus of hostile archives | none known; fuzzed |
| R11 | **Install-time code execution** | there is none: no scripts, no hooks, no build; the manifest cannot name one | a test that every manifest key is on the closed list | none |
| R12 | **Tampering after the install** (`.nova_modules` edited) | today: only `verify` notices. **New:** the first import of each package in a run re-hashes its files against the lock (a few milliseconds a package), and refuses on a difference | test | an edit between the check and the use of one file in one run |
| R13 | **Lockfile tampering** | `--frozen` in CI; `verify`; the lock holds hashes of archives, so a changed lock changes what is fetched, and a change shows in review | existing tests extended | a reviewer who does not read the lock |
| R14 | **A git dependency** (a moving ref, a rewritten history) | the lock pins the **commit**, as today; git sources are marked `unverified` in `audit` and cannot be published as dependencies of a registry package | test | a user who trusts a git url |
| R15 | **A package that uses more than it declared** | the static check of 5.6 refuses it at install and at import | cases per gated name | capability passing (5.6) |
| R16 | **A resolver attack** (pathological ranges, a huge graph) | limits: 500 packages, 50 dependencies per package, depth 50, resolver steps counted; ranges are the four simple forms | test | none known |
| R17 | **Secrets published by mistake** | `files` is an allowlist; `publish --dry-run` lists what would be packed; a scan refuses files named like keys or `.env` | test | a secret in a `.nova` file |
| R18 | **A signing key stolen** | keys are offline for the registry role; a publisher key can be revoked in `revoked.json`; the index records which key signed which version | test | a stolen key used before revocation |
| R19 | **Denial of service on a client** (a registry that answers slowly or with endless data) | timeouts and size limits in the fetch core (the same core as `std:http`, slice 6) | test | a user who waits |
| R20 | **Deleting a package that others use** ("left-pad") | no deletion: versions are immutable | by construction | a registry host that loses files; mirrors and hashes make that visible |

### 5.6 How the sandbox enforces what a package declares

Today the M11 profile is **per engine** (the whole run has one set of grants) and gated names are `LOAD_BUILTIN` in compiled code. M13 adds a check on top; it does **not** add per-module grants at run time (decision D9).

1. **At `install` and `publish`:** the tool computes the **gated names each of the package's files can refer to** (every name in `CAPABILITY_OF`, the `python` bridge, and `import` of a granted module is out of scope) by compiling the files and reading the `LOAD_BUILTIN`
   names, and the capability each belongs to. It compares with `capabilities`. **More used than declared: the package is refused** (`nova-pkg: acme/ledger/src/store.nova uses write(), which needs files.write, which nova.json does not declare`). Fewer used than declared is a warning (over-declaring asks users for more than needed).
2. **At import:** when a module inside `.nova_modules/<package>/` is loaded, the same scan runs on its code (from the compiler, or from the cached artifact, whose code objects carry the names), and an undeclared gated name is `ImportError`. **Then** the capabilities the package declares are
   compared with the run's grants: any not granted is `ImportError: package acme/ledger needs the 'files.read' capability, which this run did not grant`, **at the import**, not later.
3. **At `install`, for the project:** `policy.capabilities` of the root manifest is the most a dependency may require; the graph is refused if any package needs more. The lock records every package's capabilities, so a diff in review shows a new capability.
4. **Across versions:** `install` refuses to move a locked package to a version that declares a capability the locked one did not, unless `--accept-capabilities` names it.
5. **The three engines:** the check runs in the front end (names in the syntax tree), so the tree-walker and the self-hosted interpreter need only the small scan; the VM uses the same scan.

**What it proves, and what it does not** (the wording rule applies): it proves a package **cannot name** a gated function it did not declare, because NovaLang has no dynamic code and no reflection. It does **not** stop **capability passing**: a program that imports a package and hands it
`write` as an argument has given it that capability, which is the language's model and is visible in the program; and it is not isolation: a package granted `files.write` can write anywhere the grant allows, and the engine runs inside a Python process.
Declared capabilities are a consent screen, a review aid and a static check; the M11 grants remain the only enforcement at run time. A per-module runtime grant (a module identity in every frame, checked at `LOAD_BUILTIN`) is the stronger design and a candidate for M14 (D9).

### 5.7 The command line

`tools/nova-pkg.py` today; the plan adds a front door `novalang.py pkg ...` that runs it (D12 asks whether to rename). Exit status 0 on success, 1 on a problem the message explains, 2 on usage.

| Command | What it does |
| --- | --- |
| `nova-pkg init [NAME]` | write a `nova.json` (version 2) in the current directory |
| `nova-pkg add NAME[@RANGE]` | add a dependency to `nova.json`, then install |
| `nova-pkg install [--frozen] [--accept-capabilities LIST]` | resolve, lock and install (as today, plus the checks of 5.6 and the registry of slice 6); `--frozen` installs exactly `nova.lock` |
| `nova-pkg verify` | re-hash everything against the lock (as today) |
| `nova-pkg audit` | list every installed package with its version, source, capabilities, whether it is yanked or revoked (needs the registry), and the capability changes since the last lock |
| `nova-pkg capabilities [PACKAGE]` | the capabilities the project (or a package) needs, declared and **used** (the scan of 5.6) |
| `nova-pkg pack [--out DIR]` | build the deterministic archive of this package; print its hash |
| `nova-pkg publish [--registry PATH-OR-URL] [--key FILE] [--dry-run]` | validate the manifest, run the scan of 5.6, build the archive, **sign** it, and write the index entry and archive into a directory registry; `--dry-run` prints what would be written |
| `nova-pkg yank VERSION [--registry ...] [--key FILE]` | mark a version yanked in the signed index |

There is no `login`, no token and no upload: nothing in M13 stores a credential.

## 6. Pillar 3: API stability and deprecation

### 6.1 What is stable (declared in slice 1, one file: `docs/spec/STABLE.md` plus a machine-readable `tests/api/stable-surface.json`)

| Surface | Contents | Stable means |
| --- | --- | --- |
| **The language** | chapters 01 to 08 of the specification: lexical rules, values, expressions, scoping, errors, statements, modules | no change in the meaning of a conforming program |
| **The core library** | every global built-in of `[lib.*]` and `[host.*]`: name, arity, argument and result types, behaviour, and the **text of every error message** (messages are part of the contract, `[err.model]`) | as above |
| **The `std:` modules** | name, exports, signatures and behaviour of each, once `stable` | as above |
| **Capabilities** | the capability names, what each defines, how a grant is written | a name is never removed or narrowed; one may be added |
| **The embedding API** | the public `Nova` class and its methods, the errors it raises | no removal or incompatible change |
| **The manifest and the lockfile** | the fields and their meaning (`nova.json` 2, `nova.lock` 2); version 1 files keep being read | a new version of the format is read by all later releases |
| **The command line** | the flags and subcommands documented in `--help` and the README, and the exit statuses | |
| **Not stable** | the **bytecode artifact format** (D3 of M12: "accepted or cleanly rejected, never misread" is the only promise), the cache directory's layout, debug output (`NOVALANG_CACHE_DEBUG`), the layout of a decimal, anything under `tools/` that is not documented, any name starting with `_`, and provisional modules | may change in any minor release |

**The test:** `tests/api/test_stable_surface.py` rebuilds the list of names, arities, capabilities, exports and manifest keys from the running interpreter and compares it with the recorded `stable-surface.json`. **A removal or a change fails the test**; an addition fails it
too until the recorded file is updated in the same pull request (so every change to the surface is read by someone), and a *removal* is accepted only when the version number the file records has moved by a major.

### 6.2 Semantic versioning of NovaLang and its library

NovaLang is versioned `MAJOR.MINOR.PATCH`; the standard library ships **with** the interpreter and has **no version of its own** (a module's tier is its only separate label).

| Change | Version |
| --- | --- |
| Removing or changing the behaviour of anything stable; narrowing a capability; changing an error message; a new reserved word or a new reserved global name; making a program that ran fail to parse | **major** |
| A new function in a `std:` module, a new module, a new capability that is off unless granted, a new optional argument, a new manifest field with a default, a new accepted syntax that was an error, relaxing a gate (as `replace_all`) | **minor** |
| A bug fix where the implementation did not follow the specification ([ADR 0001](../decisions/0001-specification-is-normative.md): the specification wins, and a divergence fixed is a patch), a performance change, documentation | **patch** |
| **A security fix** that must break a stable behaviour | **patch or minor, with a changelog entry marked `security` and the break named**; this is the one exception, and it is written down in the policy |

Packages follow the same rules for their own surface (their `version` and their `nova` range); the registry **does not enforce** semantic versioning (it cannot), but `audit` reports a package whose minor release **removed** an export that the previous one had (a compare of
exports, from the static scan).

### 6.3 Deprecation

1. **Announce:** the change is recorded in `docs/spec/DEPRECATIONS.md` (name, what replaces it, the version it is deprecated in, the earliest version it can be removed in) and in the changelog, in the minor release that deprecates it.
2. **Warn:** from that release a call to a deprecated function prints, **once per call site per run**, to standard error, `warning: <name>() is deprecated since 2.5; use <replacement> (removal not before 3.0)` with the program's line. The format is specified; **standard output and the exit status do not change**, so
   existing programs and tests keep passing; `--warnings=error` turns a warning into an error (for CI), `--warnings=off` silences them. The embedding API takes a `warning` callback; in deterministic mode warnings are collected, never printed. A deprecated *capability*, *manifest field* or *flag* warns the same way at install or startup.
3. **Sunset:** a deprecated item stays for **at least two minor releases and at least six months**, whichever is longer, and **is removed only in a major release**. The removal is itself listed in the changelog with the migration.
4. **No silent removal:** the stable-surface test (6.1) is what makes this a rule and not a hope.
5. **Packages:** a package may mark a version `deprecated` in the index with a message; `install` prints it.

### 6.4 Compatibility across versions

A **compatibility suite** (`tests/compat/`): a corpus of small packages and programs with their expected output, run by the current build **and by each of the last two minor releases' tags** in CI (checked out into temporary directories); a package that works on the older release and fails on the newer is a compatibility break and stops the line. The suite grows by one entry per
bug that ever broke a package. Its first cases are the four proof-of-concept apps, run unchanged.

## 7. The slices

Each slice is a branch and a pull request, with the rules of M12: the specification section and its conformance cases first; **a full local suite and the whole CI matrix green** (Windows 3.12 required, Windows 3.7 not worse); the capability matrix full for anything new; the threat model amended where the slice adds
reach (and marked unreviewed until the independent review); no merge without the owner's go-ahead; documents labelled with their review state.

| # | Slice | Contents | Depends | Size |
| ---: | --- | --- | --- | --- |
| 1 | **Foundations** | `std:` import and the capability-declaring module descriptor (4.0); `replace_all` out of the `regex` capability (G-050); `std:text` (G-002, G-006, G-031, G-037, G-039; G-004/5 moved to slice 3); **the explicit nesting counter** in the parser, compiler, tree-walker and artifact loader (G-051: a registry puts untrusted source in front of the parser); the embedding fixes G-015 and G-017; the stable-surface file and test (6.1), the deprecation mechanism and its cases (6.3); `docs/spec/STABLE.md` | M12 | M |
| 2 | **Decimal, math and formatting** | `std:decimal`, `std:math` (`trunc`, `divmod`, `round_half`, `exp`), `std:format` (G-007, G-008), the G-052 decision; benchmark rows | 1 | M |
| 3 | **Streaming and files** | `std:files` (`lines`, `size`, `is_dir`, `is_link`, `read_chunk`), the line source in `ITER_PREP` on all three engines, the path re-check per chunk, the deterministic-time decision (D5) | 1 | L |
| 4 | **Regular expressions** | the dialect in `[lib.regex]`, the Pike VM with step accounting, `std:regex`, the `regex` builtin on the new matcher, the differential fuzzer, the time tests | 1 | L |
| 5 | **Packages, part 1: manifest and capabilities** | manifest 2 and the lockfile 2 (reading 1), the scan and the enforcement of 5.6, escalation protection, the first-import re-hash (R12), `init`, `add`, `audit`, `capabilities`; chapter `18-packages.md` with its cases; threat rows R3, R11, R12, R15 | 1 | M |
| 6 | **Packages, part 2: the registry** | the archive format and the hardened extractor, the static index and its signatures (Ed25519 verifier and vectors), serial and expiry, revocation, `pack`, `publish`, `yank`, install from a directory or HTTPS registry (a hardened fetch core: HTTPS only, size and time limits, no proxy); the end-to-end test of the roadmap's exit criterion; the supply-chain table of 5.5 as tests | 5 | L |
| 7 | **HTTP** (**moved to M14 by D6; not M13 scope**) | the `net` capability and its limits, `std:http` on the fetch core of slice 6, the matrix cells, the SSRF corpus, the amendment of `[sbx.capabilities]` | 6 | M |

### Slice 2: progress (branch `m13/slice-2-decimal`; a draft until the owner has read it)

| Item of the slice | State |
| --- | --- |
| `std:decimal` | **Built** (spec `[lib.std-decimal]`; 22 exports; every mode; pure NovaLang). Proved against Python's `decimal` on random inputs on all three engines (`tests/std/test_decimal.py`, 400 + 60 + 12 cases) and by 16 conformance cases. Deviations from the sketch above: `abs`, `sum` and `neg` cannot be exports (a built-in's name is reserved), so they are `absolute`, `total`, `negate`; scale is 0 to 1000 |
| `std:math` | **Built** (`trunc`, `divmod`, `round_half`, `exp`; spec `[lib.std-math]`; 4 cases) |
| `std:format` | **Built** (`fixed`, `grouped`, `pad_zero`; spec `[lib.std-format]`; 5 cases) |
| The G-052 decision | **Decided: keep, documented** (`[lib.std-format]`) |
| Benchmark row | **Not built yet** |
| Nova_Data replaced by the library (the "done when") | **Not done.** That is a change in the Nova_Data repository; this repository holds the library and the oracle comparison |

### Slice 1: progress (branch `m13/slice-1-foundations`; a draft until the owner has read it)

Nothing below is marked implemented in the roadmap: slice 1 is not done until every item of its row in the table above is.

| Item of the slice | State |
| --- | --- |
| `std:` import, the module list (`lib/std/modules.json`), the capability declaration and its check at the import | **Built on all three engines.** Spec `[mod.std]`; 8 conformance cases; `tests/std/` proves the capability rule on all three engines with a throw-away module (no standard module declares a capability yet, so no conformance case can; the spec says so) |
| `replace_all` out of the `regex` capability (G-050) | **Built on all three engines.** `[sbx.capabilities]` amended (marked unreviewed in the threat model's review log); the denial cases that expected it undefined now expect it to work; the matrix is still 201 of 201 |
| `std:text` | **Built** (`find`, `find_from`, `starts_with`, `ends_with`, `is_number`, `parse_number`, `basename`, `splitext`; spec `[lib.std-text]`; 7 conformance cases). **`chr` and `ord` (G-004, G-005) are not in it:** they need a native function, and the native module tier does not exist until slice 3, so they move to slice 3 |
| The stable-surface file and test | **Built** (`tests/api/`, `docs/spec/STABLE.md`): the surface is read from the source; a removal or change fails unless the major version moved; any other change fails until the record is rewritten |
| The deprecation mechanism (the warning, `--warnings`, the embedding callback) | **Not built.** The policy and an empty `DEPRECATIONS.md` exist; nothing is deprecated, so nothing is owed yet |
| The explicit nesting counter (G-051) | **Not built.** It touches the parser, the compiler, the tree-walker and the artifact loader, and needs PyPy to verify; it should be its own pull request |
| The embedding fixes (G-015, G-017) | **Not built** |

Slices 2, 3 and 4 depend only on slice 1 and could run in parallel by different people; **slice 4 and slice 6 carry the security weight of the milestone** and each ends with a request that the independent reviewer (D-review of M11) read them. The close of the milestone (a version number, the README's numbers, the changelog) follows slice 6 (slice 7 is M14's, by D6).

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| A new matcher is slow or wrong | a differential fuzzer against `re`; measured in the benchmark suite; the old behaviour stays available until the fuzzers have run a release |
| A new library reserves names and breaks programs | rule 2: namespaces; the stable-surface test counts reserved names |
| Streaming needs a new iterable on three engines and gets out of step | one conformance profile of cases, run on all three; the divergence log is the safety net |
| Pure-NovaLang decimal is too slow for NovaFinance | a benchmark row; a native tier behind the same API is the fallback and changes nothing a program sees |
| The static capability check gives a false sense of isolation | the wording rule; section 5.6 says what it does not do; the independent review |
| A registry key is lost or stolen | offline keys, rotation, revocation, and D8 (who holds them) decided before slice 6 |
| Pure-Python Ed25519 has a bug | RFC 8032 vectors, a differential test against `openssl` or `cryptography` where present in CI, and a review of the verifier alone |
| The registry client is itself an HTTP client with every classic flaw | one hardened fetch core, written once, tested by the SSRF and redirect corpus of slice 7's design even if slice 7 is not built |
| Windows and Python 3.7 behave differently (links, file locking, atomic rename, `restricted` unsupported on 3.7 Windows) | cases marked per platform as in the cache's; atomic renames only with `os.replace`; the Windows probe watched per slice |
| The scope is large | the slices can stop after any of them: each is useful alone, and 5 and 6 are the only ones whose value depends on the other |

## 9. Decisions needed from the owner

| # | Decision | Recommendation | Why |
| --- | --- | --- | --- |
| D1 | **Library architecture:** three tiers, `std:` modules, namespaces instead of global names, and **a declared stable surface before any addition** | **Accept** | A global name is reserved in every profile, so each new global function is a breaking change; a module costs one name that the importer chooses; Tier 1 gives one implementation on three engines |
| D2 | **Decimal:** function-style over an opaque value (no operators) now, or a language-level `decimal` type with operators and a literal | **Functions now; revisit the type with the NovaFinance charter** | A type touches the value model, every operator, `type()`, printing, JSON and the lexer on three engines; the library fixes the demonstrated problem (exactness, rounding) without any of that. The cost is `dec.add(a, b)` instead of `a + b`, accepted until a charter says it matters |
| D3 | **Regex:** a specified linear-time dialect and an engine written for NovaLang, or Python's `re` with captures added | **Our engine, behind the `regex` capability at first, relaxed after a release of fuzzing** | `re` can hang a run that nothing in-process can interrupt, and its dialect is not portable; our engine cannot, counts steps, and can be fuzzed against `re`. The cost is speed and a few weeks of work, and the loss of backreferences and look-around |
| D4 | **Package names:** owner-scoped (`acme/ledger`) for published packages, flat names kept for local and git | **Scoped** | the main defence against typosquatting and dependency confusion; unscoped names can never be tied to an owner |
| D5 | **Time limit:** keep the wall-clock limit (G-042), or add a step-based cost model so every engine stops at the same point | **Keep wall-clock in M13; record the cost model as its own milestone item** | the model touches every library call on three engines and is the least certain work in the plan; streaming (G-036) does not need it |
| D6 | **HTTP:** build `std:http` and the `net` capability in M13 (slice 7), or defer to a later milestone | **Defer; build the hardened fetch core in slice 6 and decide slice 7 when a program needs it** | no gap or app asks for it, `Nova_Git` does not exist, it is the only addition that reaches out, and the fetch core exists anyway. If you want it now, the plan above is the design |
| D7 | **Registry shape:** a static signed index (files over HTTPS or a directory), or a service with an API | **Static index** | nothing to operate or attack at publish time, no tokens, mirrors are trivial, and it is what the roadmap says |
| D8 | **Keys and operation:** who holds the registry signing key(s), how many, how they rotate; whether M13 **operates** a public registry or only ships the protocol, the reference implementation and a tested local one | **Ship the protocol and the reference; do not operate a public registry in M13; keys are generated offline, 2 of 3, when a registry is stood up** | operating one is a business and security commitment that belongs to the NovaForge product, not to the language milestone; the protocol must be right first |
| D9 | **Capability enforcement for packages:** a static declaration check (5.6), or per-module capability sets enforced at run time | **The static check now; runtime per-module grants in M14** | a module identity at every `LOAD_BUILTIN` changes the VM and every engine and the artifact; the static check is exact for what a package can name (no dynamic code) and ships with the manifest |
| D10 | **Scope of carried-in items:** include number formatting (G-008, `std:format`; it is in the roadmap's list but not in yours), `std:text` (find, starts/ends with, number parsing, chr/ord), and the embedding fixes (G-015, G-017) in slice 1 and 2; **defer** `+=` and the conditional expression (G-049), the leading-`+` line (G-011), multi-line strings (G-010), line continuation (G-040), dates and time zones (G-014, G-046), CSV (G-047), error values (G-022), the global-assignment rule (G-021), `files.write` granularity (G-027, G-028) | **Include the first group, defer the second** (reasons in appendix A) | the first group is additive, small and unblocks the apps; the second changes the language's syntax or its reviewed sandbox surface and needs its own decisions |
| D11 | **Versioning of the surface:** which release declares the stable surface (**2.3.0**, additively, with the first breaking removal possible only at 3.0.0); no pre-release suffixes in the registry's first protocol | **2.3.0 declares it** | declaring it early makes every later slice prove it is additive; removing nothing needs no major |
| D12 | **Tool name and entry:** keep `tools/nova-pkg.py` and add `novalang.py pkg ...` as a front door, or rename | **Add the front door, keep the file** | existing documentation and tests name the file |

### Decisions recorded (owner, 2026-11-13)

The owner accepted the recommendation of every row above (D1 to D12) as written, and named these explicitly: our own linear-time regex engine (D3), owner-scoped
package names (D4), static capability checks at install and import (D9), declaring the stable surface in 2.3.0 (D11), keeping `nova-pkg.py` with a front door (D12),
and not operating a public registry in M13 (D8). The owner also confirmed that `Nova_Git` was discussed but never built.

**D6 as decided:** defer HTTP to M14, where it gets a proper `net` capability. The recommendation said "build the hardened fetch core in slice 6 and decide slice 7
later"; the owner's wording defers the whole of `std:http` and the `net` capability to M14. This plan reads that as: slice 6 still needs a fetch core for the registry
client (a registry served over HTTPS cannot be installed from without one), and it is **internal to `nova-pkg`**, not exposed to NovaLang programs, and not a capability. If
that reading is wrong, say so before slice 6.

Consequences, applied throughout: M13 has six slices (1 to 6); the `net` capability, `std:http` and the `[sbx.capabilities]` amendment are not touched in M13, so the
reviewed M11 text stays as it is; `net` remains in the manifest's closed capability list **as reserved and rejected** until M14 (a package that declares it is refused,
so nothing can depend on a capability that cannot be granted); the roadmap's "outside world" deliverable is carried to M14 for HTTP.

The five follow-up questions below were not answered; until the owner says otherwise the plan proceeds on the recommendation given with each.

### Questions that follow from the decisions

1. **Deprecation windows (6.3):** two minor releases and six months, whichever is longer. Longer? Shorter?
2. **Package licences:** require an SPDX `license` for publishing? *Recommend yes, a warning in M13.*
3. **The independent reviewer** of M11 (still pending) is asked to read slices 4 and 6 as well. *Recommend yes, and that the review of M11 is not closed before those slices land.*
4. **Over-declared capabilities** (a package declares `net` and never uses it): warning, as proposed, or refusal? *Recommend warning.*
5. **Where do the `std:` modules' tests of "done when" live:** in each proof-of-concept repository (a pull request there replacing the hand-written helper) or only in this repository's vendored copies? *Recommend both: the vendored copies gate the slice, the repositories follow after.*

## 10. Exit criteria (testable)

1. A package can be **published** to a registry, **installed** from it (a directory registry in the test, an HTTPS one in a hermetic local server test), and **verified**, end to end, in a test; and every row of the supply-chain table of 5.5 that says "test" has one.
2. **A breaking change to the declared stable surface fails a test** (6.1), and the compatibility suite (6.4) runs the last two minor releases.
3. Each library of slices 1 to 4 meets its **done-when** in the proof-of-concept program that asked for it, on the VM, with the oracle comparison unchanged.
4. A package that uses a gated built-in it did not declare **cannot be installed or imported** (5.6), on all three engines, in a test per gated name.
5. Every new capability and limit has its denial, grant and trip cases on every engine (the matrix is full), and the threat model records the new reach, marked unreviewed.
6. No document says more about security than `[sbx.claims]` allows (the wording test passes).
7. The full local suite and the whole CI matrix are green on every slice.

## 11. Order and size

Slice 1 first (it decides the mechanism and the promise); then 2, 3 and 4 in any order or in parallel; 5 before 6; slice 7 is not part of M13 (D6). Relative size, as in the roadmap: **L** (about as large as M12). The longest single items are the matcher (4.6), the line source on three engines (4.5) and the registry with
its signatures (slice 6).

---

## Appendix A: the fifty gaps, and what M13 does with each

`PASS` is a finding that needs nothing. "Deferred" always has a reason; nothing is dropped silently. Slice numbers are those of section 7.

| Gap | What | Disposition |
| --- | --- | --- |
| G-001 | Big integers are exact | PASS: the basis of `std:decimal` |
| G-002 | `num()` throws on text | Slice 1: `text.is_number`, `text.parse_number(s, default)` (`num` keeps throwing: stable) |
| G-003 | `regex()` returns only true or false | **Slice 4** |
| G-004, G-005 | No escape character, no `chr`/`ord` | Slice 3: `text.chr`, `text.ord` (moved from slice 1: they need a native function and the native module tier starts in slice 3; a global name would break programs) |
| G-006 | No `find`, `startswith`, `endswith` | Slice 1: `std:text` |
| G-007, G-008 | No thousands separator, no number formatting | Slice 2: `std:format` (D10) |
| G-009 | No null; a missing key is an error | Deferred: needs a decision on missing values in the language (`nothing`), not a library |
| G-010 | No multi-line strings, templates, HTML escape | Deferred: syntax; `std:text.escape_html` is a candidate for a later minor |
| G-011 | A line starting with `+` is a new statement | Deferred: a parser diagnostic; the linter can warn first |
| G-012, G-013 | No disk I/O rates, Wi-Fi, sensors | Out of scope: outside what a scripting language reaches |
| G-014 | Time zones | Deferred: needs a time-zone database (Python 3.7 has no `zoneinfo`); with dates (G-046) |
| G-015 | Embedding cannot give a program its `args()` | Slice 1 |
| G-016 | Natural names are reserved | **Policy** (rule 2): namespaces; the surface test counts reserved names |
| G-017 | `import` needs four undocumented Python files | Slice 1: the interpreter names what it needs; documentation |
| G-018 | No `exp()`, no power operator | Slice 2: `math.exp`; the operator is syntax (deferred) |
| G-019 | Two engines word one error differently | Conformance (D-001); not an M13 item |
| G-020 | The self-hosted interpreter is 31x slower | M12 residue; not an M13 item |
| G-021 | Assigning to a global from a function makes a local | Deferred: a semantic change (major) |
| G-022 | A caught error is a bare string | Deferred: error values are a language change (major) |
| G-023 | No terminal size or tty detection | Deferred: a `std:terminal` candidate for M14 |
| G-024 | No test runner; `assert` stops at the first failure | Deferred: a tool (`nova test`), M14 |
| G-025 | Unspecified Python exceptions | Contained since M12 (`InternalError`); ongoing |
| G-026 | A program cannot handle Ctrl-C | Deferred: embedding/host design |
| G-027, G-028 | `files.write` also grants remove and delete; `rename` replaces | Deferred: splitting a capability is a breaking change to the reviewed M11 surface; a package that declares `files.write` is deemed to include removal; `files.remove` can be added later without breaking declarations |
| G-029 | No way to ask which capabilities were granted | Deferred: a design question (does a program learn its own grants?) |
| G-030 | No `isdir` or `stat` | Slice 3: `files.is_dir`, `files.size` |
| G-031 | No `splitext`/`basename` | Slice 1: `std:text` |
| G-032 | No `lstat`/`islink` | Slice 3: `files.is_link` |
| G-033 | The target folder arrives only through the working directory | Host design: `args()` works under `process` (not an M13 item) |
| G-034 | The CLI reads the flag after `--bootstrap` as the program | A tool fix: slice 1 if trivial |
| G-035 | No way to learn whether the file system ignores case | Deferred: minor |
| G-036 | A `restricted` program cannot read a file over 1,000,000 characters | **Slice 3** |
| G-037 | No `index`/`find`/`startswith` | Slice 1: `std:text` |
| G-038 | `sorted()` cannot order pairs or take a key | Slice 1: an optional second argument (additive); or `std:collections.sort_by` |
| G-039 | `num()` accepts more than digits; no `isdigit` | Slice 1: `text.is_number` |
| G-040 | An expression cannot continue on the next line | Deferred: lexer rule (syntax) |
| G-041 | No lazy line reader | **Slice 3** |
| G-042 | The wall-clock limit is engine-dependent | D5: deferred by recommendation |
| G-043 | `round()` is half-to-even | Slice 2: `math.round_half`, `dec.quantize` (`round` is specified and stable) |
| G-044 | No decimal type | **Slice 2** |
| G-045 | `//` and `%` floor; no `trunc`/`divmod`/`int` | Slice 2: `math.trunc`, `math.divmod` |
| G-046 | No date support | Deferred: `std:date` in a later minor |
| G-047 | No CSV reader | Deferred: `std:csv`, a Tier 1 candidate seeded by Nova_Data's parser, a later minor |
| G-048 | Small floats print as `1e-07` | Slice 2: documented rule and `fmt.fixed`; changing `str()` is a major |
| G-049 | No `+=`, no conditional expression, `and`/`or` give booleans | Deferred: syntax |
| G-050 | `replace_all` needs `regex` | **Slice 1** |
| G-051 | The nesting limit leans on the host's recursion limit | Slice 1: the explicit counter |
| G-052 | An overflowing float literal is infinity | Slice 2: decided with `std:format` (keep, document) |
