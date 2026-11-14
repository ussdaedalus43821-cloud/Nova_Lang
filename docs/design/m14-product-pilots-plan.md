# M14: product pilots, starting with NovaSteward Observe

| | |
| --- | --- |
| Status | **Draft for the project owner. Nothing here is decided and nothing is built.** Written after M13 closed (v2.3.0, 2026-11-14) |
| Scope | The one-page charter of the first product (NovaSteward, read-only), what NovaLang must still provide for it, how its core is built on `std:decimal`, and the slices that get it to a first pilot. **Not** the other M14 products, **not** the go-to-market plan |
| Reads with | [`ROADMAP.md`](../ROADMAP.md) M14 (the charter rule), [`vision/NOVA_EXPERIENCE.md`](../vision/NOVA_EXPERIENCE.md) section 3 (the product), [`vision/NOVA_FINANCE.md`](../vision/NOVA_FINANCE.md) (the design), [`vision/LAUNCH_ROADMAP.md`](../vision/LAUNCH_ROADMAP.md) (the gates), [`m13-libraries-and-registry-plan.md`](m13-libraries-and-registry-plan.md) |
| Names | **NovaSteward** is the finance app. It is not *Steward*, the studio's existing game, and it is not *NovaFinance*, the larger design of which it is the read-only first release |

## 1. What M14 is for

The roadmap says M14 "defines when each product may start, not what it contains": a product enters with a one-page charter
(owner, the NovaLang capabilities it needs, the hosts it targets, its first measurable outcome) and the prerequisites. M13 is the last
prerequisite for NovaFinance, and the vision documents choose NovaSteward as the first product. This plan is that charter, plus the work
**on the language and libraries** that the charter needs, because that is the part this repository owns. The product itself lives in its own
repository, as Nova_Stats, Nova_Sort, Nova_Log and Nova_Data do.

What this plan is careful about, from the vision documents themselves:

- **It is read-only.** NovaSteward Observe shows, forecasts and warns. It moves no money, makes no payment and gives no investment advice.
  *Coordinate* and *Act* (the vision's second and third releases) are not in this plan at all.
- **The product numbers are hypotheses.** The launch roadmap's retention, conversion, interview and budget figures are planning targets
  written by the product side. Nothing in this plan depends on them, and nothing here claims them.
- **No bank connection is in the first pilot.** The launch roadmap's own order is "observe without accounts" first: manual bills, a CSV import,
  a transparent forecast, local storage. That order is also what the language can support today, because the language has no network
  capability (decision D6 moved it here) and the registry's fetch core is deliberately internal to `nova-pkg`.

## 2. Rules this plan inherits

1. **One language, three engines.** Anything the product relies on runs the same on the VM, the tree-walker and the self-hosted engine, and has
   conformance cases. A product does not get a private dialect.
2. **Money is never a float.** NovaSteward's money path uses `std:decimal` end to end, with an explicit rounding mode at every division; a test
   fails if a float can reach it (section 5.3).
3. **The wording rule of `[sbx.claims]`.** The restricted profile is capability gating and limits, not isolation. NovaSteward's documents say
   what its grants prevent and what they do not, and never "secure" or "safe" without the evidence.
4. **A library is only done when the program that asked for it can delete its own helper.** The M13 rule, kept: the acceptance of each library
   below is a program of the product (or of a proof of concept) with its hand-written version gone and its oracle comparison unchanged.
5. **Stop the line.** The whole suite and the whole CI matrix, including Python 3.7 on Windows, are green on every slice before the next starts.
6. **No unreviewed claim about security.** The independent review of M11 is still pending (the roadmap says so); a product that holds financial
   records may not say more than the roadmap does until it has an outcome.

## 3. Facts (checked on 2026-11-14)

### 3.1 What a NovaSteward core would use, and whether it exists

| Need | What provides it | State |
| --- | --- | --- |
| Exact money, a rounding mode for every division | `std:decimal` (`parse`, `add`, `sub`, `mul`, `div(a, b, places, mode)`, `quantize`, `cmp`, `total`, `to_string`) | **Built (2.3.0)**, on the native tier; verified against Python's `decimal` on all three engines; Nova_Data's report is byte-identical to its hand-written version |
| Amounts as text: thousands separators, fixed places | `std:format` (`fixed`, `grouped`, `pad_zero`) | Built |
| Reading a bank export | **A CSV reader** | **Missing.** G-047, deferred in M13 ("`std:csv`, seeded by Nova_Data's parser"). Nova_Data hand-writes one and says so |
| Reading a large file under the sandbox | `std:files.lines` / `each_line` | Built; the restricted profile reads a file over 1,000,000 characters |
| Pulling a date, an amount or a name out of an email or a statement line | `std:regex` (captures, named groups, `sub`, `pieces`), linear time | Built; capability `regex` (kept until a release of fuzzing) |
| **Dates**: what is due in the next 30 days, a monthly bill on the 31st, the end of a pay period, a weekday | **Nothing.** G-046 ("no date support"), deferred: "`std:date` in a later minor". The built-ins are `now`, `format_time` and `time` (a clock capability), and they work in seconds since the epoch | **Missing, and the largest gap.** A 30-day forecast is date arithmetic |
| Time zones | Nothing (G-014, deferred: Python 3.7 has no `zoneinfo`) | Missing; avoidable in the first pilot by treating every date as a **civil date** with no time zone (section 5.2) |
| Ordering rows by a key, grouping, "the largest per category" | `sorted` takes no key and cannot order a list of lists (checked today: `sorted([[2,"b"],[1,"z"]])` is a `TypeError`); Nova_Data packs two numbers into one to sort (G-038) | **Missing** |
| A missing value that is not an error | `d.missing` is an error, `get(d, key, default)` does not exist, there is no `nothing` literal (`type(nothing)` is `undefined name`); callers use `key in d` (G-009) | **Missing**; a language decision, not only a library |
| Local storage that is encrypted | NovaLang has `read`, `write`, `append`, `mkdir` behind `files.read` / `files.write`, and **no cryptography at all** | **Missing, by design.** See D-S3: encryption belongs to the host, not to the language |
| An append-only record of what the program did (the "Daily Receipt") | `append(path, line)` under `files.write` | Possible today as a plain file; a tamper-evident log needs a hash (below) |
| Scheduling, notifications, a user interface | None. NovaLang is a language with a CLI, an embedding API for Python and a port to GDScript | **Host work**; see section 6 |
| Talking to a bank or an aggregator | No `net` capability, no HTTP (decision D6: M14) | Not needed for the first pilot; **prerequisites in section 7, slice 6** |
| Packaging the product's own modules, with their capabilities checked | `nova-pkg` with declared capabilities, a signed registry on a folder or HTTPS | **Built (2.3.0)**; no public registry exists (D8), so the product's modules are local or git packages |

### 3.2 What Nova_Data teaches about size

Nova_Data is the nearest precedent: a spending report from a CSV, in NovaLang, under the restricted profile with the default limits
(5 s of wall-clock time). Measured today, after moving to `std:decimal` and `std:files` (merged 2026-11-14): **10,000 rows in 3.1 s, 15,000 in 4.4 s,
20,000 and up refused with `LimitError`**, about 3,600 records a second on the VM; on the self-hosted engine about 50 records a second. A household's
year of transactions is a few thousand rows, so a *daily* recompute fits, with the headroom the table shows and no more. Two consequences:

- **Design the core to be incremental.** A ledger that is re-read in full every time is the ceiling that Nova_Data already hits. Store a normalized
  ledger and recompute forecasts from it, not from the CSV.
- **The time limit is wall-clock and engine-dependent** (G-042, deferred by decision D5). A product whose forecast must give the same answer in
  the same budget on every engine needs the step-counted limit; section 6 lists it as a candidate, with the reason.

## 4. The charter (the one page the roadmap asks for)

Items marked **owner** are decisions only the owner can make; the plan's recommendation is in section 9.

| | |
| --- | --- |
| Product | NovaSteward Observe: the read-only first release of the private financial foresight app. "Know what's coming. Stay in control." |
| Owner | **owner** (the roadmap requires one named; not assumed here) |
| What it does in the first pilot | From manual bills and a CSV import: a bill calendar, a transparent 30-day cash-flow forecast (expected, conservative, stress; every figure labelled verified, predicted or estimated, with its source and the date of its data), recurring-payment and price-change detection, and a **Daily Receipt** (a plain-language record of what the program did and with which permissions) |
| What it never does | Move money; connect to an account in the first pilot; give investment or tax advice; hold a bank password; send data off the machine |
| NovaLang capabilities it needs | `files.read` and `files.write`, **confined to one data folder**; `process` (arguments, exit); `clock` for "today" (and a way to fix "today" for tests: the deterministic mode exists). It needs **no** `env`, `stdin`, `random`, `python`, `net`, and `regex` only if email or statement text is parsed. Its pure core needs **none at all**, and the package capability check can say so (section 5.1) |
| Hosts it targets | **Owner.** The launch roadmap says "mobile/desktop prototype" and names no host; NovaLang runs today as a Python program and, for the games, as a GDScript port. First pilot recommended: **a command-line host** like Nova_Data's, because it is the only host that exists and the core is the part worth proving first (D-S2) |
| First measurable outcome (engineering side) | From a seeded ledger CSV (12 months, at least 3,000 rows) plus a bills file, the program prints the three 30-day forecasts and the Daily Receipt, **under the restricted profile with the default limits and on three engines' worth of agreement for the pure core**, and **every figure equals an independent Python `Decimal` oracle to the cent** on at least 20 generated datasets, including month ends, leap years and refunds |
| First measurable outcome (product side) | The launch roadmap's alpha gate (80% of testers complete setup in 10 minutes; 70% name a correctly explained insight). **This plan does not measure it and does not vouch for it** |

## 5. How the core is built

### 5.1 Modules, and what each may touch

NovaSteward's logic is a set of NovaLang packages in its own repository, installed by path into a thin root program (the static check applies to installed packages, not to the root program; a scoped name with a path dependency was tried and installs and imports). The point of splitting them is that **most of them need no capability, and the
static check of slice 5 proves it**: a package that declares `"capabilities": []` and still uses `read` is refused at install and at import.

| Package (proposed names) | Does | Declares |
| --- | --- | --- |
| `novasteward/money` | Amount parsing and printing over `std:decimal`; rounding rules in one place; the rule that no float enters | none |
| `novasteward/dates` | Civil-date arithmetic over `std:date` (section 6) | none |
| `novasteward/ledger` | The normalized transaction list; categories; reconciliation | none |
| `novasteward/bills` | The bill calendar; recurrence rules (weekly, monthly on day N or last day, every N days) | none |
| `novasteward/recurring` | Detecting recurring payments and price changes from the ledger | none |
| `novasteward/forecast` | The three forecasts and their explanations | none |
| `novasteward/receipt` | Building the Daily Receipt lines from events (pure: it returns text) | none |
| `novasteward/store` | Reading and writing the data folder: the ledger, the bills, the receipt | `files.read`, `files.write` |
| `novasteward/import` | CSV and statement-text import into ledger records | `files.read` (and `regex` only if text is parsed) |
| the program (`steward.nova`) | The host-facing entry: arguments, "today", wiring | `process`, `clock` |

The run is then `--profile restricted --allow-read DATA --allow-write DATA --allow-process --allow-clock`, and nothing else. The Daily Receipt prints
that exact list (a program cannot ask what it was granted: G-029, so the **host passes the grant in as an argument and the receipt says it**; a
test checks the printed list equals the real flags).

### 5.2 The data model

Every value of money, date and label is plain text in files, so a record can be read, diffed and exported by a person:

- **Amount:** a decimal string with a sign by the convention of Nova_Data (a charge is positive, a credit negative), never a number. `std:decimal` values are opaque, so the
  store holds `dec.to_string(...)` and parses on load.
- **Date:** an ISO civil date (`2027-01-31`) with **no time zone**. A bill is due on a date, not at an instant. This sidesteps G-014 for the pilot and is stated as a limit.
- **Labelled figure:** `{value, kind: "verified" | "predicted" | "estimated", as_of, source}`. A forecast figure is never printed without its label; a stale source says so
  (the launch roadmap asks for "precise sync-status labels"; in the pilot the only sources are the user's import and the user's own bills).
- **Event:** one line of the Daily Receipt: when, what the program did, which data it read, which data it wrote, which permissions the run had.

### 5.3 The forecast, and a worked example that has been run

The design asks for three forecasts, always: **expected**, **conservative** (income delayed, expenses higher) and **stress** (something important goes wrong), and
that decisions protecting essential funds use the conservative one. This plan proposes these definitions for the owner to accept or change (D-S6); the arithmetic
is the library's, not new:

```
capacity = available balance - obligations due in the window - essentials reserve - protected reserve
expected     = obligations at their expected amounts, essentials at their recent average
conservative = expected, with variable essentials raised by a stated margin, each estimated bill raised by its observed
               worst case, and income that is not yet in the account not counted
stress       = conservative, plus one shock (the largest bill again, or a stated amount) in the first week
```

The worked example of `NOVA_FINANCE.md` section 7, written as a NovaLang program with `std:decimal` and `std:format`, and run on the VM, the tree-walker and the
self-hosted engine with identical output (kept in this repository as [`m14-examples/forecast-example.nova`](m14-examples/forecast-example.nova)):

```
expected       $205.00
conservative   $129.00
after $80      $125.00
0.10 + 0.20    0.30 float equals 0.3: false
```

`$205.00` and `$125.00` are the vision document's own figures (balance 1,200 less rent 500, insurance 120, phone 45, an essentials reserve of 180 and a protected reserve
of 150; then 80 spent). `$129.00` is the same example with essentials 20% higher and an electricity bill 40 over its forecast: 1,200 - 705 - 216 - 150. The last line is the
reason for rule 2: a float says `0.1 + 0.2` is not `0.3`. Nothing in this example is NovaSteward code; it only shows that the library does what the product needs, and it
is a starting test.

**Honesty rules for a forecast** (from the design, made testable): every figure carries its label; a forecast that cannot be computed (missing balance, an unparseable
bill) says what is missing and prints no number; an estimate is never shown with more precision than its inputs; and the forecast never says that spending something is
"safe", only what the figures are and how they were obtained.

## 6. What NovaLang must provide first (a 2.4.0 library slice, and a patch list)

These are the gaps of section 3.1 that block the first pilot, in the way M13 handled them: a library, a spec section, conformance cases, and a program that deletes
its own helper.

| # | Item | Why the product needs it | Done when |
| --- | --- | --- | --- |
| L1 | **`std:date`** (G-046): civil dates (`parse` ISO, `format`, `add_days`, `add_months` with the month-end rule stated, `diff_days`, `weekday`, `last_day_of_month`, comparison, `is_leap`), no time zone, a native tier if the pure version is too slow, specified in `[lib.std-date]` | Every bill, due date and window is date arithmetic; without it the product reimplements the calendar and gets month ends wrong | Nova_Data's hand-written `is_date` and its date validation are replaced by it and the report is byte-identical; a differential test against Python's `datetime.date` over every date from 1900 to 2100 for each operation |
| L2 | **`std:csv`** (G-047): RFC 4180 reading (quoted fields, embedded newlines and quotes, BOM, CRLF, CR), by lines and by file, returns rows, with a row-length limit and an error that names the line | Every statement import | Nova_Data's `parse_fields` and its quote-gluing loop are deleted and its 83 tests pass unchanged; a seeded fuzzer against Python's `csv` module |
| L3 | **Ordering by a key** (G-038): `sorted(list, key)` as an additive second argument, or `std:collections.sort_by`; stable | Per-category totals, "the largest charge", recurring-payment grouping | Nova_Data's packed-integer sort is deleted; ties are stable on all three engines |
| L4 | **A missing value** (G-009): the owner decides between a `get(d, key, default)` built-in (a new reserved global name: a **major** change by `STABLE.md`), a `std:` function over dictionaries, and a `nothing` literal | Reading optional fields of a record without a `key in d` before every access | The decision (D-S5) recorded; the product uses whichever is chosen |
| L5 | **The 2.3.x patch list** from the M13 close: the deprecation warning, the step-counted time limit (D5), the nesting counter (G-051), the embedding fixes (G-015, G-017), `nova-pkg add` and `audit` | The time limit, because a household forecast must answer the same on every engine in the same budget; the embedding fixes, because a host that is not the CLI needs `args()` and a documented set of files | Each as the M13 plan lists it; G-042 closed means the same program gets the same answer (it completes, or it hits the step limit at the same point) on every engine, however long the self-hosted engine takes on the clock |
| L6 | **Hashing for a tamper-evident Daily Receipt**: a `std:hash` (SHA-256 of text) on the native tier, or the receipt stays a plain log and says so | A receipt that can be shown to have changed; optional for the first pilot | A decision (D-S4); if built, an RFC 6234 vector test and a hash-chained receipt whose edit is detected |
| L7 | **`std:terminal`** (G-023): size and tty detection | A readable CLI report | Optional; Nova_Data and Nova_Stats print without it |

Not in the list on purpose: encryption (D-S3), a scheduler and notifications (host work), a UI toolkit, `net`/`std:http` (section 7), and time zones (G-014: a later minor, with a time-zone
database decision).

## 7. Slices

Relative sizes as in the other plans (S, M, L). The first three are what a pilot needs; the rest are gates, not commitments.

| Slice | What | Depends on | Size |
| --- | --- | --- | --- |
| **P0** | **Charter and decisions** (this document, sections 4 and 9): the owner names the product owner, the first host, the storage rule and answers D-S1 to D-S10. The product repository is created (`NovaSteward`) with CI that includes Windows and Python 3.7 | the owner | S |
| **P1** | **The 2.4.0 libraries** (L1 to L3, L4 as decided, L6 if wanted) and the **2.3.x patch** (L5). Each library with its spec section, conformance cases on three engines, an oracle test, and the proof-of-concept deletion of section 6 | P0 | L |
| **P2** | **The core and its oracle**: `money`, `dates`, `ledger`, `bills`, `recurring`, `forecast`, `receipt` as packages with `"capabilities": []`, plus `import` and `store`; a seeded generator of ledgers and bills with an **independent Python oracle** (Nova_Data's pattern: every number against `Decimal`, three engines for the pure core); property tests on the forecast (adding a bill never raises capacity; conservative is never above expected; stress is never above conservative) | P1 | L |
| **P3** | **The command-line host** (`steward.nova`): arguments, "today" (or a fixed one), the data folder, the report, the Daily Receipt with the real grant printed; run under `restricted` with the default limits; the **ceiling table** as in Nova_Data (rows against the 5 s budget); a benchmark row | P2 | M |
| **P4** | **Alpha readiness of the language side**: the product's packages declared and checked; a registry-free install (local or git) with the lock pinned; a reproducible, checksummed release of the CLI host; the threat model of section 8 written, with what is *not* defended; a request that the independent reviewer read the data-handling code | P3 | M |
| P5 | *Gate: not before the alpha and the independent security assessment the launch roadmap itself requires.* **Read-only connections**: a `net` capability and `std:http` (the slice 7 of the M13 plan, designed for the registry's fetch core: HTTPS only, no proxy, limits, no redirects off-host), the SSRF and redirect corpus, OAuth through the institution's own flow (no password ever in a NovaLang program), a provider-capability layer, token storage in a vault (NovaSecurity, which does not exist) | the alpha gate; NovaSecurity's vault and audit subsystems | XL |
| P6+ | Coordinate and Act (the vision's second and third releases): **not planned here**. Action authority also needs NovaSecurity's identity, vault and audit subsystems (NS-1, NS-2, NS-5), and the launch roadmap's own gates | P5 and more | n/a |

Slices P1 to P3 are about the size of M13 slices 2 to 4; P4 is small if P2 respects section 5.1.

## 8. A threat model for the first pilot (not reviewed)

Assets: the user's financial records on their machine; the correctness of the forecast (a wrong figure is harm, not only a bug); the Daily Receipt's honesty. Actors: a
malicious file the user imports; a malicious or compromised dependency; a careless user; another program on the same machine; a person with the user's unlocked laptop.
**Not defended (stated first, as the other models do):** malware on the machine; a user who grants more than the receipt says; anyone who can read the data folder (the language has no
encryption: D-S3); the Python interpreter and the operating system; a forecast that is correct arithmetic over wrong inputs.

| # | Threat | Defence in this plan | Proved by |
| --- | --- | --- | --- |
| S1 | A crafted CSV (huge, deeply quoted, a billion-line field, NUL bytes, invalid UTF-8) | `std:csv` has limits and names the line; `std:files` reads in pieces under the string limit; the restricted profile's limits end a run | fuzz against Python's `csv`; a corpus of hostile files; the ceiling table |
| S2 | A hostile pattern in statement parsing | the linear-time matcher; the pattern is the product's, not the file's | the M13 time tests; the product never builds a pattern from file text without `escape` |
| S3 | A dependency that reads the ledger or writes elsewhere | declared capabilities checked at install and import; the core declares none; the run's grants are one folder | a test that every core package declares `[]` and the install refuses a change; the Daily Receipt prints the grants |
| S4 | Float contamination: a wrong cent | no float in the money path | a test that scans the core's syntax tree for float literals and `num()` on money, and the oracle |
| S5 | A forecast that misleads (a stale source shown as current, a missing bill) | labels, `as_of`, "cannot compute" instead of a number | property tests; golden reports reviewed by the owner |
| S6 | The Daily Receipt that lies, or is edited | it is written by the program from what it did, with the real grant; hash-chained if D-S4 says so | tests that the receipt matches an independent trace; an edit is detected (if built) |
| S7 | Data leaves the machine | the run has no `net`, no `process` spawning, no `python`; the only writes are inside the data folder | the sandbox matrix cells for those capabilities (already covered on three engines) |
| S8 | Data at rest read by another program or a thief | **not defended** by NovaLang; host or operating-system encryption (D-S3) | n/a |

## 9. Decisions needed from the owner

| # | Decision | Recommendation | Why |
| --- | --- | --- | --- |
| D-S1 | **Who owns the product and where does it live?** A named owner, and a repository (`NovaSteward`) with its own tests and CI, like the four proofs of concept | Yes, a new repository, CI on Windows 3.7 and 3.12 and Linux from the first commit | The roadmap requires a named owner; M13 showed that the rows nobody watched (Windows 3.7) are where failures appear |
| D-S2 | **The first host** | A **command-line host** for the pilot, in NovaLang, run under the restricted profile; the UI host is chosen after the core has an oracle | It is the only host that exists, it keeps the product honest about capabilities, and a core proved on a CLI moves to any host that embeds the language; the vision's mobile and desktop hosts do not exist for NovaLang yet |
| D-S3 | **Encryption at rest** | Not in the language. The host (or the operating system) encrypts the data folder, and the Daily Receipt says whether it is | NovaLang has no cryptography, and writing it is a larger security commitment than anything in M13; the launch roadmap asks for "local encrypted storage", which a host provides today (an encrypted volume) |
| D-S4 | **A tamper-evident Daily Receipt** (L6) | A plain, honest log in the pilot; add `std:hash` and a hash chain at P4 if the owner wants the claim | A hash chain proves *an edit happened*, not that the log is complete; promising more than that is a claim the wording rule forbids |
| D-S5 | **Missing values** (L4) | A `std:` function over dictionaries (additive, a minor change), not a new reserved global | A new global built-in is a **major** change by the policy of `STABLE.md`; the library route costs a name the importer chooses |
| D-S6 | **The three forecasts** (section 5.3) | Accept the definitions as a first version, with each margin a named parameter in a file the user can read | The numbers behind "conservative" and "stress" are a product judgment; the engine must make them visible, not decide them |
| D-S7 | **Are the user's rules written in NovaLang or in the policy dialect?** The design says the policy dialect is "the natural candidate" | NovaLang functions in the pilot (the core reads a rules file); revisit the policy dialect when action authority exists | In Observe there is nothing to authorize; the dialect earns its place when a rule allows or blocks an action |
| D-S8 | **Does the product publish packages?** | Not to a registry (none exists, D8); the product's packages are installed from its own repository by path or git, with the lock | An operated registry is a business and security commitment that belongs to a later decision |
| D-S9 | **Order of work: libraries first or product first?** | **Libraries first (P1), then the core (P2)** | M13's own lesson: Nova_Data's hand-written helpers and gaps were the cost of building the product before the library |
| D-S10 | **The independent review** (M11's, still pending) | Make the review of the sandbox, the matcher and the registry client a gate before P5, and ask the reviewer to read the product's data-handling code at P4 | A product that holds financial records should not outrun its reviewer |

## 10. Exit criteria for the NovaLang side of the pilot (testable)

1. `std:date`, `std:csv` and ordered sorting exist, each with a spec section, conformance cases on all three engines, an oracle or differential test, and a proof-of-concept program whose hand-written
   version is deleted with its tests unchanged (section 6).
2. NovaSteward's core packages declare no capability, the install and import checks pass, and a test shows that adding a use of `read` to a core package makes the install fail.
3. For 20 or more generated ledgers (month ends, leap years, refunds, ties), every figure of the three forecasts and the Daily Receipt equals the independent `Decimal` oracle to the cent, on the VM, and the pure
   core agrees on the tree-walker and the self-hosted engine on a smaller sample.
4. The CLI host runs the seeded 12-month ledger under `restricted` with the default limits, and a ceiling table says how many rows fit.
5. A scan of the core finds no float literal and no `num()` on a money value.
6. The Daily Receipt's printed permissions equal the flags of the run, in a test.
7. The whole suite and the whole CI matrix are green on every slice, in the product repository and in this one.

## 11. Risks

| Risk | Mitigation |
| --- | --- |
| The date library is bigger than it looks (month ends, leap years, and the pull towards time zones) | Civil dates only, no time zone, in the first version; a differential test against Python's `datetime.date` for every day of two centuries; time zones stay a later decision |
| The forecast looks authoritative and is wrong | Labels on every figure, "cannot compute" instead of a guess, property tests, golden reports the owner reads, and the wording rule: it states figures and sources, never that something is "safe" |
| Performance: a household's data grows and the 5 s budget does not | A normalized ledger recomputed incrementally; the ceiling table in the repository; the step-counted limit (L5); native-tier functions for the hot paths, as `std:decimal` needed |
| The product pulls the language towards its needs and breaks the stable surface | Every addition goes through `std:` and a minor release; L4 is the one place a major change is possible and is the owner's call |
| Scope: the vision documents describe a whole ecosystem | This plan is **Observe, read-only, no connections, a CLI host**; P5 is gated and P6 is not planned |
| A claim the evidence does not support (security, privacy, accuracy) | The wording rule, the threat model of section 8 with its "not defended" list, and the independent review as a gate (D-S10) |

## 12. What this plan does not decide

The product's persona, interviews, usability gates, pricing, legal and provider review, partnerships, hiring and budget belong to the launch roadmap and to the product side; **none of it is
verified here**. Whether the forecast, as a product, helps people is a question for the pilot's users, not for the tests of this repository: the tests can show the arithmetic is exact and the
labels are honest, and nothing more.
