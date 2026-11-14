# M14: product pilots: NovaLedger (prosumers and small businesses) and NovaAudit (a log analyzer)

| | |
| --- | --- |
| Status | **Draft for the project owner, revised 2026-11-14. Nothing here is decided and nothing is built.** Written after M13 closed (v2.3.0) |
| Scope | The charters of two products that are built to use what M11 (the security model) and M13 (the libraries) made possible: **NovaLedger**, a financial tool for prosumers and small businesses, and **NovaAudit**, an enterprise log analyzer built on `std:regex`; what NovaLang must still provide for them; how their cores are built; the slices that get each to a first pilot. **Not** the other M14 products, **not** a go-to-market plan |
| Reads with | [`ROADMAP.md`](../ROADMAP.md) M14 (the charter rule), [`m13-libraries-and-registry-plan.md`](m13-libraries-and-registry-plan.md), [`m11-threat-model.md`](m11-threat-model.md). See the private Nova_Vision repository for the Master Plan. |
| Names | **NovaLedger** is the financial product (renamed from an earlier working name), **NovaAudit** the log analyzer. The module of the finance design that used the same name is now called NovaBalances |

## 1. What changed from the first draft

The first draft of this plan was a charter for a read-only **consumer budgeting app**. The owner has changed two things, and this version follows both:

1. **The name:** the financial product is called **NovaLedger**.
2. **The audience:** the mass-market consumer budgeting app is dropped. The judgment that the market is saturated and expensive to acquire users in is the **owner's**; this plan does not measure it and does not need to. In its place:
   - **NovaLedger for prosumers and small businesses**, and
   - **NovaAudit**, an enterprise log analyzer built with `std:regex`.

   The reasoning the owner gave is the organising idea of this version: **build tools that leverage the security model (M11) and the text-parsing power (M13), instead of competing with consumer apps on features.**

What carried over unchanged: the decimal core (money is never a float), the forecast with its three scenarios and its honesty rules, the worked example (it was run), the rule that a product's packages declare their capabilities, and the stop-the-line rules. What was dropped: the consumer launch gates and figures, the bank-connection beta, and the personal-finance framing. What is new: a second product, a shared foundation, performance and release facts that matter much more to a business buyer than to a consumer, and a validation slice that comes before any building.

## 2. What M14 is for

The roadmap says M14 "defines when each product may start, not what it contains": a product enters with a one-page charter (owner, the NovaLang capabilities it needs, the hosts it targets, its first measurable outcome). This plan is that charter for two products, plus the work **on the language and libraries** that they need, because that is the part this repository owns. Each product lives in its **own repository**, as Nova_Stats, Nova_Sort, Nova_Log and Nova_Data do.

**The thesis, stated so that it can be tested.** A business that is asked to run a tool on its books or its logs wants to know what the tool can touch. NovaLang can now say so in a way that a reviewer can check: a program's packages **declare** the capabilities they use, the install and the import **refuse** one that uses more, and the program runs under the `restricted` profile with the grants on the command line and nothing else. A product built that way can print the grants it ran with, the version of NovaLang, a hash of its inputs and the version of its rules, and anyone can re-run it and get the same bytes (the deterministic mode exists). That is what is demonstrable today. What it is **not**, by the project's own wording rule (`[sbx.claims]`): isolation, or a security boundary, and the independent review of the sandbox is still pending (section 7). The products must not say more than that.

## 3. Rules this plan inherits

1. **One language, three engines.** Anything a product relies on runs the same on the VM, the tree-walker and the self-hosted engine and has conformance cases. A product does not get a private dialect.
2. **Money is never a float** (NovaLedger). `std:decimal` end to end, an explicit rounding mode at every division, and a test that fails if a float can reach the money path.
3. **The wording rule of `[sbx.claims]`.** Capability gating and limits, not isolation. No "secure", "safe" or "certified" without the evidence for it.
4. **A library is done when the program that asked for it can delete its own helper** (the M13 rule), with its oracle comparison unchanged.
5. **Stop the line.** The suite and the whole CI matrix, Python 3.7 on Windows included, are green on every slice before the next starts.
6. **Analysis, not action.** Both first releases read and report. Neither moves money, changes a system, or deletes a file. That is inherited from the first draft's read-only stance; it is the owner's to change.
7. **Market and customer claims are the owner's and are hypotheses.** Nothing here asserts who will buy, at what price, or that either product beats an existing one.

## 4. Facts (checked on 2026-11-14)

### 4.1 What the two products can use today

| Need | What provides it | State |
| --- | --- | --- |
| Exact money, a rounding mode for every division | `std:decimal`, `std:math`, `std:format` | **Built (2.3.0)**, on the native tier; checked against Python's `decimal`; Nova_Data's report is byte-identical to its hand-written version |
| Pulling fields out of log lines and statements: captures, named groups, `sub`, `pieces` | `std:regex`, linear time whatever the pattern | **Built**; the capability `regex` is kept, so an analyzer must be **granted** it, which is visible on its command line |
| Reading a file of any size without holding it | `std:files` (`lines`, `each_line`) in 64 KiB pieces, under the read grant | **Built**; a file over the 1,000,000-character string limit reads under `restricted` |
| JSON lines | `json.loads` | Built |
| Declared, checked capabilities per package; a signed registry | `nova-pkg` | **Built**; no public registry exists (D8), so a product's packages install from its own repository by path or git |
| Reproducible output | the deterministic mode (a fixed clock and seed) | Built (M11) |
| Reading a bank or a billing export | **A CSV reader** | **Missing.** G-047, deferred in M13 (`std:csv`, seeded by Nova_Data's parser) |
| Dates: what is due in 30 days, a month end, an invoice's age, an interval between two log lines | **Nothing.** G-046 deferred (`std:date`); the built-ins work in seconds since the epoch | **Missing, and the largest gap for both products.** NovaAudit also needs a timestamp **with a numeric offset** (`[10/Oct/2026:13:55:36 +0000]`), so the library must carry an offset; named time zones (G-014) stay out |
| Ordering by a key, grouping, "top N" | `sorted` takes no key and cannot order a list of lists (`sorted([[2,"b"],[1,"z"]])` is a `TypeError`) | **Missing** (G-038) |
| A missing value that is not an error | `d.key` of an absent key is an error, there is no `get(d, k, default)` and no `nothing` literal | **Missing** (G-009); a language decision |
| A hash of an input, as evidence of what was analyzed | **Nothing** in the language | **Missing.** The first draft made this optional; for NovaAudit it is central |
| A step-counted time limit | the limit is wall-clock and differs by engine (G-042, deferred by D5) | **Missing**; matters more for a product that promises a repeatable run |
| Scheduling, a UI, notifications, an installer | None. NovaLang is a language with a CLI, a Python embedding API and a GDScript port | Host work, section 8 |
| A network | no `net` capability and no HTTP (decision D6 moved them here) | Not needed by either first pilot; section 9, P5 |

### 4.2 Measured numbers that shape the plan

- **NovaLedger's ceiling is NovaData's.** Under `restricted` with the default 5 s limit, Nova_Data does **10,000 rows in 3.1 s and 15,000 in 4.4 s**; 20,000 and up are refused with `LimitError`. About 3,600 records a second on the VM and about 50 on the self-hosted engine. The embedder **can raise** the time limit (`--limit time=900000` was run and accepted today); the default is not a wall. A small business's year of bank rows is thousands to tens of thousands.
- **NovaAudit's throughput is the hard fact.** A combined-log pattern with six captures, run with `std:regex` and `files.each_line` on the VM, measured today on Nova_Log's own files: **2,155 lines in 0.44 s, 10,000 in 1.98 s, 50,000 in 8.41 s and 51,462 in 9.02 s: about 4,900 to 5,900 lines a second, or 0.5 to 1.2 MB a second** (one run each, on the machine that built this plan, with the cache off; read them as an order of magnitude). At that rate a 50 MB log takes about 1 to 2 minutes and a gigabyte about 15 to 35 minutes, on one core. That is a real result for an "enterprise" tool: the matcher is a Pike machine written in Python, correct and linear in time, and **not fast**. Section 7 treats this as the central risk of NovaAudit, and the first pilot is sized by it.
- Under `restricted`, importing `std:regex` **without** `--allow-regex` is refused (`ImportError: std:regex needs the 'regex' capability`), so what an analyzer was allowed to do is on its command line.

## 5. The two charters (the one page the roadmap asks for, for each)

Items marked **owner** are decisions only the owner can make; recommendations are in section 11.

### 5.1 NovaLedger (prosumers and small businesses)

| | |
| --- | --- |
| Audience hypothesis | **Owner to confirm, and to test in P0.** Prosumers (freelancers, sole traders, people who run their own books) and small businesses (a shop, an agency, a clinic, a household business) who keep money records in bank exports and spreadsheets, and the bookkeepers or accountants who serve several of them. The plan does not know which of these is the customer; P0 is where that is learned |
| What it does in the first pilot (hypothesis) | From a bank or billing export and a list of expected payments and invoices: **reconcile** the export against what was expected, **age** receivables and payables, a **cash-flow forecast** over the next 30 and 90 days in three scenarios (expected, conservative, stress), recurring-payment and price-change detection, and a **run receipt** (section 6). Every figure is labelled verified, predicted or estimated with its source and date |
| What it never does | Move money; connect to an account in the first pilot; give tax, legal or investment advice; claim to be accounting software or to satisfy an accounting or tax rule; send data off the machine |
| Why this audience, in terms of the platform | The product's selling point is not a feature list but a property: **per-client isolation by grant** (a bookkeeper runs it for client A with `--allow-read` on A's folder and nothing else), **exact money**, **reproducible reports** (the same inputs give the same bytes), and **what it can touch is on its command line**. Whether a buyer values that is a hypothesis for P0 |
| NovaLang capabilities it needs | `files.read` and, if it writes a report, `files.write`, each **confined to one client folder**; `process`; `clock` for "today" (and the deterministic mode for tests). Its core packages need **none**; the static check can say so (section 6) |
| Hosts | **Owner.** First pilot recommended: **a command-line host** (it is the only host that exists), run under `restricted` |
| First measurable outcome (engineering) | From a seeded year of rows (at least 3,000) and an expected-payments file, print the reconciliation, the ageing and the three forecasts **under the restricted profile**, and **every figure equals an independent Python `Decimal` oracle to the cent** on at least 20 generated datasets, including month ends, leap years, refunds and partial payments |
| First measurable outcome (product) | **Owner, from P0.** This plan does not adopt the figures of the earlier consumer-app plan: they were written for a mass-market app |

### 5.2 NovaAudit (an enterprise log analyzer built on `std:regex`)

| | |
| --- | --- |
| Audience hypothesis | **Owner to confirm, and to test in P0.** A security, operations or compliance team that must analyze logs containing sensitive data and wants an analyzer it can read in an afternoon and run with a short, visible list of permissions. "Enterprise" is the owner's word; section 7 lists what an enterprise would ask that does not exist yet |
| What it does in the first pilot (hypothesis) | Reads web-server access logs (combined format, Nova_Log's format) and authentication or system logs, and JSON lines, **by rule files** (a rule is a pattern with named captures, a window and a threshold, written as data, not code): error-rate spikes per window, bursts of failed logins per source, rare or newly seen paths and user agents, request-size outliers, a top-N by status, path and source. It prints a report with **evidence** (line numbers and the matched text), a summary, and an **exit status by severity** so that a pipeline can gate on it |
| What it never does | Write to the log folder; make a network connection; modify or delete a log; claim a detection is complete (a rule finds what it is written to find, and the report says which rules ran) |
| Why this product, in terms of the platform | It needs only the one thing M13 built best and M11 can gate best: **parsing text under a read-only grant**. A run needs `--allow-read LOGS` and `--allow-regex`, and **no write grant at all** if the report goes to standard output. Nova_Log is the precedent: it counts HTTP statuses with hand-written splits, and M13's "done when" for `std:regex` was its status extraction, which one pattern reproduces on all 113,617 non-blank lines of its four datasets |
| NovaLang capabilities it needs | `files.read`, `regex`, `process` (arguments, exit status), `clock` only to print when the run happened. **No `files.write`, no `env`, no `stdin`, no `random`, no `python`, no `net`** |
| Hosts | **Owner.** First pilot recommended: a command-line host, run by an operator or a pipeline |
| First measurable outcome (engineering) | Over a seeded corpus of generated logs (at least 1 million lines in all, in three formats, with planted incidents), the report equals an **independent Python oracle** (an implementation with `re` and `collections`) on every finding, line number and count; the run receipt records the grants and the SHA-256 of each input; and the ceiling table says how many lines per second and per megabyte the analyzer does, on stated hardware (the million-line comparison is a separate, slower check, not part of the default suite) |
| First measurable outcome (product) | **Owner, from P0** |

## 6. How the cores are built (what they share)

### 6.1 Packages and what each may touch

Each product's logic is a set of NovaLang packages in its own repository, **installed by path into a thin root program**. The static check applies to installed packages, not to the root program, which is why the split matters. (A scoped name with a path dependency was tried on 2026-11-14: it installs and imports, and a use of `read` in a package that declares `"capabilities": []` is refused at install.) The pure packages declare **nothing**, so the install proves that parsing, detection, arithmetic and the forecast cannot touch a file:

| Package (proposed) | Does | Declares |
| --- | --- | --- |
| `…/money`, `…/ledger`, `…/recon`, `…/ageing`, `…/forecast` (NovaLedger) | Amounts over `std:decimal`; the normalized transaction list; matching a payment to an expectation; receivable and payable ageing; the three forecasts | none |
| `…/parse`, `…/rules`, `…/detect`, `…/report` (NovaAudit) | Log-line parsing with `std:regex`; rule files as data; the detectors (windowed counts, bursts, rarity); the report text | `regex` for the parsers only; the rest none |
| `…/dates` (both) | Civil dates and timestamps with an offset over `std:date` | none |
| `…/receipt` (both) | The run receipt (below) as text | none |
| `…/import`, `…/store` | Reading the export or the logs; writing a report if one is asked for | `files.read`; `files.write` only where asked |
| the program | Arguments, "today", wiring | `process`, `clock` |

### 6.2 The run receipt (the one idea both products share)

At the end of a run the program prints, and optionally writes, a **receipt**: what it did, in plain text with a fixed order: the version of NovaLang, the product and rules versions, **the grants of the run exactly as given on the command line** (a program cannot ask what it was granted, G-029, so the host passes them in as an argument and a test checks the printed list equals the real flags), a **SHA-256 of every input**, counts of lines read and skipped, which rules ran, and the exit status. With the deterministic mode the whole report is reproducible, so a reviewer can re-run it and compare bytes. This is the project's wording rule applied: the receipt states what was configured and what was read, and **never** that the result is secure, complete or correct beyond the tests. The hash needs a language feature that does not exist yet (L5).

### 6.3 NovaLedger's data and forecast

- **Amount:** a decimal string with a sign (a charge positive, a credit negative, as in Nova_Data), never a number; the store holds `dec.to_string(...)` and parses on load. **Currency** is carried beside the amount, with its minor-unit places (2 for most, 0 for some, 3 for a few); a result is never added across currencies, and a conversion is an explicit step with a stated rate and date, or it is not done. **Date:** a civil date, no time zone (a bill is due on a date, not at an instant). **Labelled figure:** `{value, kind: verified | predicted | estimated, as_of, source}`.
- **The forecast**, three scenarios always, the conservative one for any decision that protects cash. Proposed definitions, for the owner (D-P9):

  ```
  capacity     = available balance - obligations due in the window - minimum cash reserve
  expected     = obligations at their expected amounts, receipts that are due and have a record of paying on time
  conservative = expected, with receipts counted at their observed delay (or not counted), variable costs raised by a stated margin
  stress       = conservative, plus one shock in the first week (the largest payable again, or a stated amount)
  ```

- **A worked example that has been run** (kept as [`m14-examples/forecast-example.nova`](m14-examples/forecast-example.nova); the same output on the VM, the tree-walker and the self-hosted engine). It is the arithmetic of the original personal-finance example, and it is the same shape as a small business's weekly cash: a balance, dated obligations, a reserve, a margin, a shock.

  ```
  expected       $205.00
  conservative   $129.00
  after $80      $125.00
  0.10 + 0.20    0.30 float equals 0.3: false
  ```

  (Balance 1,200 less 500, 120 and 45, an essentials reserve of 180 and a protected reserve of 150 is 205. The conservative figure raises the 180 by 20% and adds a 40 overage: 1,200 − 705 − 216 − 150. The last line is rule 2: a float says `0.1 + 0.2` is not `0.3`.) It is a starting test, not product code.
- **Honesty rules:** every figure carries its label; a forecast that cannot be computed (a missing balance, an unparseable invoice) says what is missing and prints no number; an estimate is never shown with more precision than its inputs; and the report never says that a payment is "safe", only the figures and how they were obtained. It is not accounting, and the report says so.

### 6.4 NovaAudit's rules and detectors

A **rule** is data: an id, a format, a pattern with named captures, and a predicate over the captures (a status class, a path prefix), plus, for a detector, a window and a threshold. The engine is a small interpreter over rules, so a team changes what it looks for without changing code, and a rule file's hash goes into the receipt. Patterns are the author's, never built from log text without `re.escape`; the matcher is linear in time whatever the pattern, so **a rule cannot hang an analyzer** (the point of M13's matcher), and the work is charged to the run's limits. A detector keeps counts per key per window in bounded memory (the list and dictionary limits apply), and **says so when it drops** a key for lack of room instead of silently undercounting.

## 7. NovaAudit: what an enterprise would ask, and what exists

The owner's word is "enterprise". The first pilot is not enterprise-ready, and the plan says what stands between it and that word, in order of how much each matters:

| An enterprise buyer asks for | State today | Plan |
| --- | --- | --- |
| **Speed at their volume** | About 4,900 to 5,900 lines a second on one core (section 4.2); a gigabyte takes roughly a quarter to half an hour | The first pilot is sized to **tens of megabytes per run**, states its ceiling table, and runs one file per process (the host parallelizes across files). **A faster matcher is a decision the owner takes with the measurement in hand** (D-P7): options are a literal and prefix filter in front of the matcher, a native-tier fast path for common patterns, or a compiled DFA. None of them is started |
| **A signed, reproducible release** with a bill of materials and provenance | `v2.2.0` is an unsigned lightweight tag and 2.3.0 will be the same (the roadmap says so) | A **gate before any customer pilot** (P4): a signed tag, a checksummed archive, a build that can be reproduced, a bill of materials. Not started |
| **An independent security review** | The M11 review of the sandbox is **pending**; the matcher and the registry client are marked not reviewed | The review is a gate before NovaAudit is shown to a customer (D-P10). The products say only what the wording rule allows until it has an outcome |
| **Output that fits their pipeline** | Plain text and an exit status are easy; JSON lines and a SARIF or CSV export are not built | A JSON report and a CSV report in the first pilot; other formats on demand |
| **A platform they already run** | Python 3.7 or later, on Linux, macOS and Windows (CI covers all three, Python 3.7 on Windows included) | Stated as a requirement; no installer in the first pilot |
| **Support, a roadmap, compliance paperwork** | None | Not an engineering item; the owner's |

## 8. What NovaLang must provide first (a 2.4.0 library slice, and a patch list)

These are the gaps of section 4.1 that block a first pilot, handled as M13 handled its own: a library, a spec section, conformance cases on three engines, an oracle or differential test, and a program that deletes its own helper.

| # | Item | Why | Done when |
| --- | --- | --- | --- |
| L1 | **`std:date`** (G-046): civil dates (`parse` ISO, `format`, `add_days`, `add_months` with the month-end rule written down, `diff_days`, `weekday`, `last_day_of_month`, `is_leap`, comparison) **and a timestamp with a numeric UTC offset** (parse the common log forms, convert to UTC, `diff_seconds`), no time-zone database; a native tier if the pure version is too slow | Every due date, ageing bucket and window in NovaLedger; every window and burst in NovaAudit | Nova_Data's `is_date` is deleted and its report is byte-identical; a differential test against Python's `datetime` over every date from 1900 to 2100 and a sample of offsets |
| L2 | **`std:csv`** (G-047): RFC 4180 reading (quoted fields, embedded newlines and quotes, BOM, CRLF, CR), by lines and by file, a row-length limit, an error that names the line | NovaLedger's import; NovaAudit's CSV logs | Nova_Data's `parse_fields` and its quote-gluing loop are deleted and its 83 tests pass unchanged; a seeded fuzzer against Python's `csv` |
| L3 | **Ordering by a key** (G-038): `sorted(list, key)` as an additive second argument, or `std:collections.sort_by`; stable | Top-N, ageing, per-key totals | Nova_Data's packed-integer sort is deleted; ties are stable on all three engines |
| L4 | **A missing value** (G-009): owner decides between a `get(d, key, default)` built-in (a new reserved global name, a **major** change by `STABLE.md`), a `std:` function over dictionaries (a minor change), and a `nothing` literal | Optional captures and fields (a log line that lacks a field) are the normal case in NovaAudit | The decision recorded (D-P6); the products use it |
| L5 | **`std:hash`**: SHA-256 of a string or of a file read in pieces, on the native tier, with the RFC 6234 vectors | The run receipt's hash of every input; the evidence a reviewer re-checks. **Recommended, not optional, for NovaAudit** | A vector test; a receipt whose recorded hash equals `sha256sum` of the file |
| L6 | **The 2.3.x patch list** from the M13 close: the step-counted time limit (D5), the nesting counter (G-051), the embedding fixes (G-015, G-017), `nova-pkg add` and `audit`, the deprecation warning | The step-counted limit, so a run gives the same answer on every engine; the embedding fixes, so a host that is not the CLI can run a product | As the M13 plan lists each |
| L7 | **`std:terminal`** (G-023): size and tty detection | Readable reports on a terminal | Optional |

Not in the list on purpose: encryption (D-P8: the host's), a scheduler and notifications (host work), a UI toolkit, `net` and `std:http` (P5), named time zones (G-014: a later minor, with a time-zone database decision), and a faster matcher (D-P7).

## 9. Slices

Relative sizes as in the other plans (S, M, L, XL). P0 to P4 are what a first pilot of either product needs; the rest are gates, not commitments.

| Slice | What | Depends on | Size |
| --- | --- | --- | --- |
| **P0** | **Validation and decisions** (owner-led). Talk to the people in each audience (section 5) before building: what they keep, what they would want a tool to do, whether "you can see exactly what it can touch" matters to them, what scale they have. This plan **cannot** do this and does not pretend to. In parallel, the engineering spike that costs nothing to run: the throughput measurement of section 4.2 on the owner's real log shapes. Create the two repositories with CI that includes Windows and Python 3.7 | the owner | S, but long on the calendar |
| **P1** | **The 2.4.0 libraries** (L1 to L5, L4 as decided) and the **2.3.x patch** (L6), each with its spec section, conformance cases, oracle test and the proof-of-concept deletion of section 8 | P0 decisions | L |
| **P2** | **NovaAudit core and oracle**: `parse`, `rules`, `detect`, `report`, `receipt`; a **seeded generator of logs with planted incidents** and an independent Python oracle (Nova_Data's pattern); property tests (a rule's count never exceeds the lines read; a window never counts a line twice); the ceiling table; the receipt test | P1 (L1, L5, L4) | L |
| **P3** | **NovaLedger core and oracle**: `money`, `ledger`, `recon`, `ageing`, `forecast`, `receipt`; a seeded generator of statements and invoices; every figure against Python `Decimal`; property tests (adding an obligation never raises capacity; conservative never exceeds expected; stress never exceeds conservative); the ceiling table | P1 (L1 to L3) | L |
| **P4** | **Pilot readiness of the language side:** each product's packages declared and checked; the lock pinned; a **signed, checksummed, reproducible release** of the CLI host with a bill of materials; the threat models of section 10 written with their "not defended" lists; the independent reviewer asked to read the data-handling code | P2 or P3 | M |
| P5 | *Gate: not before the owner's validation has an answer and the independent review has an outcome.* **Connections and scale:** a `net` capability and `std:http` (the M13 plan's slice 7: HTTPS only, no proxy, limits, no off-host redirects, an SSRF corpus), a provider layer for NovaLedger's bank or billing feeds, a faster matcher if D-P7 says so, JSON and SARIF integrations for NovaAudit | the gate | XL |
| P6+ | Any action (payments, remediation): **not planned here**. It needs the vault, identity and audit subsystems the roadmap names (NovaSecurity) and the owner's gates | P5 and more | n/a |

Order. **D-P2 recommends NovaAudit first.** It has the closest precedent (Nova_Log), the heaviest use of what M13 built, no money and so no accounting or regulatory exposure, and it needs the smaller part of the date work. NovaLedger second, once `std:date` and `std:csv` have been proved on NovaAudit's logs and on Nova_Data.

## 10. Threat models for the first pilots (not reviewed)

Both follow the form of the M11 and M13 models: assets, actors, then **what is not defended, first**.

**Not defended, for both:** malware on the machine; a user who grants more than the receipt says; anyone who can read the data folder (the language has no encryption: D-P8); the Python interpreter and the operating system; a correct analysis of wrong or incomplete input; and, for NovaAudit, **an attacker who controls what is written to the logs and so what the analyzer sees** (it detects what its rules say; it does not authenticate the log's origin).

| # | Threat | Product | Defence in this plan | Proved by |
| --- | --- | --- | --- | --- |
| A1 | A crafted log or CSV (a gigabyte line, NUL bytes, invalid UTF-8, a million fields) | both | `std:files` reads in pieces under the string limit; `std:csv` has limits and names the line; the restricted profile's limits end a run | fuzz against Python's `csv`; a hostile-file corpus; the ceiling table |
| A2 | A hostile or pathological pattern (a rule file from a less trusted team) | NovaAudit | the matcher is linear in time whatever the pattern and charged to the run; pattern size and nesting are limited | the M13 time tests; a corpus of rule files |
| A3 | A dependency that reads or writes more than it says | both | declared capabilities checked at install and at import; the core declares none; the run's grants are on its command line and in the receipt | a test that every core package declares `[]` and that adding a `read` makes the install fail |
| A4 | A wrong cent | NovaLedger | no float in the money path | a scan of the syntax tree for float literals and `num()` on money; the oracle |
| A5 | A report that misleads (a stale source shown as current, a missing input, a dropped key) | both | labels and `as_of` on every figure; "cannot compute" instead of a guess; a detector that says when it drops keys | property tests; golden reports the owner reads |
| A6 | A receipt that lies | both | written by the program from what it did; the grants it prints are the real flags; the input hashes are `std:hash` of the files read | a test against an independent trace |
| A7 | Data leaves the machine | both | no `net`, no `process` spawning, no `python`; NovaAudit has no write grant at all | the sandbox matrix cells for those capabilities (covered on three engines) |
| A8 | One client's data reaches another's (a bookkeeper serving several) | NovaLedger | one run per client folder, the grant is that folder; no shared state between runs | a test that a run granted A's folder cannot read B's (the path checks of `[sbx.paths]`) |
| A9 | A forged or tampered release of the product | both | the signed, reproducible release of P4 | the release checks of P4 |

## 11. Decisions needed from the owner

| # | Decision | Recommendation | Why |
| --- | --- | --- | --- |
| D-P1 | **Product owners and repositories** | One repository per product (`NovaLedger`, `NovaAudit`), each with its own tests and CI on Windows 3.7 and 3.12 and Linux from the first commit | The roadmap requires a named owner; M13 showed that the rows nobody watches are where failures appear |
| D-P2 | **Which first** | **NovaAudit**, then NovaLedger | Section 9: the closest precedent, the heaviest use of M13, no regulatory exposure, the smaller date need. The owner may well have a customer conversation that changes this |
| D-P3 | **The audiences** (section 5) | Treat both as hypotheses, and run P0 before P2 and P3 | The plan does not know the customer. Building a product for an audience that was assumed is the mistake the consumer draft was in danger of making |
| D-P4 | **The name collision between the product and a module of the finance design** | **Decided by the owner, 2026-11-14:** the module is renamed NovaBalances; the product stays NovaLedger | Two things with one name is the confusion the rename was meant to remove |
| D-P5 | **Order of work: libraries first or product first** | **Libraries first (P1)**, then the products | M13's own lesson: Nova_Data's hand-written helpers were the cost of building the product before the library |
| D-P6 | **Missing values** (L4) | A `std:` function over dictionaries (additive, a minor change), not a new reserved global | A new global built-in is a **major** change by `STABLE.md` |
| D-P7 | **How much speed NovaAudit promises, and whether to build a faster matcher** | State the measured ceiling (tens of megabytes a run, one file per process) in the first pilot, and **decide on a faster matcher after P0 says what volume customers have** | A faster matcher is a large security-sensitive piece of code (the current one is unreviewed); building it on a guess about volume would be the wrong order |
| D-P8 | **Encryption at rest** | Not in the language; the host or the operating system encrypts a data folder, and the receipt says whether it is | NovaLang has no cryptography, and writing it is a larger commitment than anything in M13 |
| D-P9 | **NovaLedger's three forecasts** (section 6.3) | Accept the definitions as a first version, with each margin a named parameter in a file the user can read | "Conservative" and "stress" are a judgment; the engine must show them, not decide them |
| D-P10 | **Gates before a customer sees either product** | The independent review of the sandbox, the matcher and the registry client has an outcome, and the release is signed and reproducible (P4) | An enterprise buyer will ask both; a product that holds financial records or reads sensitive logs should not outrun its reviewer |
| D-P11 | **Do the products publish packages?** | Not to a registry (none exists, D8); install from the repositories by path or git, with the lock | Operating a registry is a business and security commitment that belongs to a later decision |

## 12. Exit criteria for the NovaLang side of the first pilots (testable)

1. `std:date` (with offsets), `std:csv`, ordering by a key and `std:hash` exist, each with a spec section, conformance cases on all three engines, an oracle or differential test, and a proof-of-concept program whose hand-written version is deleted with its tests unchanged (section 8).
2. Each product's core packages declare no capability except NovaAudit's parsers' `regex`, the install and import checks pass, and a test shows that adding a `read` to a core package makes the install fail.
3. NovaAudit: over a seeded corpus of at least 1 million generated lines in three formats with planted incidents, every finding, line number and count equals the independent oracle, on the VM; the pure core agrees on the tree-walker and the self-hosted engine on a smaller sample; and the ceiling table is published.
4. NovaLedger: for 20 or more generated datasets, every figure of the reconciliation, the ageing and the three forecasts equals the `Decimal` oracle to the cent on the VM, and the pure core agrees on the other engines on a smaller sample; no float literal and no `num()` on a money value anywhere in the core.
5. The receipt's printed grants equal the flags of the run, and its input hashes equal `sha256sum`, in tests.
6. A run granted one folder cannot read another (A8), and NovaAudit runs with no write grant.
7. The whole suite and the whole CI matrix are green on every slice, in each product repository and in this one.

## 13. Risks, and what this plan does not decide

| Risk | Mitigation |
| --- | --- |
| **The audience was wrong again** (the first draft's was dropped; these two are hypotheses) | P0 comes first and its answer can change the plan; nothing in P2 or P3 starts on an assumption |
| **NovaAudit is too slow for the volume enterprises have** | The measurement is in section 4.2; the first pilot is sized to it; D-P7 is a decision with the measurement in hand, not a surprise at a customer |
| **A claim the evidence does not support** (security, completeness, accuracy) | The wording rule; the "not defended" lists; the receipt that states configuration, not results; the independent review as a gate |
| **A financial product is read as accounting or advice** | The charter says it is neither; every report says so; a decision about what to call it is the owner's (and a lawyer's), not this plan's |
| **The date library is bigger than it looks** | Civil dates and numeric offsets only, a differential test against Python's `datetime` over two centuries; named time zones are a later decision |
| **A product pulls the language towards its needs and breaks the stable surface** | Every addition goes through `std:` and a minor release; L4 is the one place a major change is possible, and it is the owner's call |
| **Scope: the owner's wider ecosystem plans cover much more than this** | This plan is two read-only products with a CLI host; P5 is gated and P6 is not planned |

**What this plan does not decide.** Market, pricing, positioning against existing products, legal and regulatory review, partnerships, hiring and budget are the owner's and are not verified here. Whether either product helps its users is a question for the pilot's users: the tests of this repository can show that the arithmetic is exact, the parsing is linear, the labels are honest and the permissions are what the receipt says, and nothing more.

