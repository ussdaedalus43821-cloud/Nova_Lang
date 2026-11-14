# M12 slice 2: where the VM's time goes

Status: **Measured 2026-11-14; reviewed by no one but the author.** Written for the owner after slice 1. It changes nothing in
the VM. Every number can be regenerated: `python3 tests/benchmarks/profile_vm.py nova_log` (also `nova_data`, `nova_stats`,
`micro/<name>`; `--markdown` prints the tables below; `--cprofile` adds the Python-level view) and
`python3 tests/benchmarks/op_costs.py`. Machine and method are those of [`docs/benchmarks.md`](../benchmarks.md): a MacBook Pro M1, CPython 3.9.6.

## 1. The answer in one paragraph

The 24,500 lines a second of Nova_Log is not integer math (there is none) and not string splitting (the library's own work
in `split` and `len` is about 4% of a line). A line costs **110 instructions at about 400 ns each**, 45 microseconds. Three
things make an instruction that slow, in this order: **the dispatch loop is one long `if`/`elif` chain, and an instruction
pays 13.8 ns for every opcode listed before its own (7.8 failed tests per instruction on average, about 27% of the run)**;
**calls are expensive**, a NovaLang function call and return costing about 3 microseconds and a call to a library function about 800 ns
of interpreter work around a library function that takes 150 ns (calls and returns are 34% of the run); and **half of all
instructions only move a value** (`LOAD_CONST`, `LOAD_FAST`, `STORE_FAST`, `LOAD_GLOBAL`: 51% of the count, 20% of the time).
None of the three needs a new feature or changes what any program prints.

## 2. How this was measured, and how far to trust it

* **A counting build of the dispatch loop, not a sampler.** `profile_vm.py` copies `execute` in memory and adds, where each
  instruction is fetched, a count and a clock read; it never edits `novalang.py`. A sampling profile of Python would report
  `execute` and nothing else, because the whole VM is one function.
* **Counts are exact; times are estimates.** Two clock reads per instruction (about 55 ns each) inflate every time, so the times are
  scaled to the wall time of an uninstrumented run (the scale is 0.8 to 0.95 and printed with each table). Compare shares.
* **An opcode's time includes everything it does.** `CALL` includes the library function it calls. The built-in tables split that
  into `inside` (the library function) and `around` (what `call_value` adds); the wrapper's own clock reads are subtracted.
* **The dispatch-chain cost is an estimate from a measured constant.** One failed `if op == K:` test in a 60-deep chain costs
  12.9 to 13.8 ns here (measured on a copy of the same shape, in the same process); the report multiplies it by the exact count of failed
  tests. It is an overlay on the opcode times, not a separate category: the failed tests are already inside the instructions' times.
* **Every share below is an upper bound on what a fast path could win**: removing a cost completely is the most one can do.
* Nova_Log, Nova_Data and Nova_Stats are the real programs, vendored (see `tests/benchmarks/workloads/poc/VENDORED.md`). Shares
  differ by 1 to 3 points between profiling runs on this machine.

## 3. Nova_Log: 5 MB, 30,331 lines

1.36 s in the profiling run (the suite's baseline says 24,165 lines/s; this run was 22,330: the machine drifts by about 7% between sessions). **3,342,638 instructions, 110 per line,
2.5 million instructions a second.**

| opcode | count | per line | % of count | % of time | ns each | chain tests before it | ns without the chain tests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CALL | 212,768 | 7.0 | 6.4% | 30.5% | 1945 | 5 | 1875 |
| INDEX | 303,419 | 10.0 | 9.1% | 10.9% | 487 | 11 | 335 |
| LOAD_CONST | 729,329 | 24.0 | 21.8% | 7.0% | 130 | 1 | 116 |
| CHECK_BOOL | 182,146 | 6.0 | 5.4% | 6.0% | 446 | 20 | 170 |
| IN | 121,340 | 4.0 | 3.6% | 5.9% | 665 | 19 | 402 |
| LOAD_FAST | 577,478 | 19.0 | 17.3% | 5.6% | 132 | 0 | 132 |
| RETURN | 60,720 | 2.0 | 1.8% | 3.8% | 851 | 7 | 754 |
| LOAD_GLOBAL | 212,573 | 7.0 | 6.4% | 3.8% | 242 | 4 | 186 |
| JUMP_IF_FALSE_KEEP | 91,078 | 3.0 | 2.7% | 3.6% | 532 | 32 | 89 |
| GE | 60,693 | 2.0 | 1.8% | 3.4% | 756 | 41 | 189 |
| STORE_FAST | 182,640 | 6.0 | 5.5% | 3.4% | 251 | 6 | 168 |
| JUMP_IF_NOT_TRUE | 212,538 | 7.0 | 6.4% | 3.2% | 207 | 2 | 179 |

Built-in calls: 16% of the run is spent calling library functions, but most of that is not the library:

| built-in | calls | per line | % of time | ns inside | ns around |
| --- | ---: | ---: | ---: | ---: | ---: |
| len | 91,069 | 3.0 | 6.6% | 145 | 832 |
| split | 60,673 | 2.0 | 6.1% | 630 | 728 |
| split_lines | 1 | 0.0 | 1.7% | 22988136 | 5051 |
| read | 1 | 0.0 | 0.1% | 984619 | 3378 |

For `len`, the library function takes 145 ns and the call takes 977: the interpreter adds 832 ns (five times the work). In a
line, the library functions do about 1.7 us of work (3.8% of the line) and the calls around them add about 4.0 us (8.8%).

The dispatch chain in this run: 26,134,982 failed tests, **7.8 per instruction, 862 per line, about 26.6% of the run (362 ms)**.
`CHECK_BOOL`, `JUMP_IF_FALSE_KEEP`, `GE` and `IN` look slow in the table (450 to 760 ns) and are mostly chain position: the last column
shows `JUMP_IF_FALSE_KEEP` costs 89 ns of its own and 443 ns of failed tests.

## 4. Nova_Data and Nova_Stats

**Nova_Data, 10,000 rows:** 1.81 s, 441 instructions a row, 410 ns each. Dispatch chain 31.4% (10 failed tests per
instruction). `CALL` 22.1% (20 calls a row, 15 of them to library functions).

| opcode | count | per row | % of count | % of time | ns each | chain tests before it | ns without the chain tests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CALL | 200,466 | 20.0 | 4.5% | 22.1% | 1996 | 5 | 1931 |
| CHECK_BOOL | 322,611 | 32.3 | 7.3% | 8.0% | 450 | 20 | 192 |
| INDEX | 221,098 | 22.1 | 5.0% | 6.1% | 502 | 11 | 360 |
| LOAD_GLOBAL | 420,115 | 42.0 | 9.5% | 5.9% | 253 | 4 | 201 |
| LOAD_FAST | 776,814 | 77.7 | 17.6% | 5.7% | 134 | 0 | 134 |
| LOAD_CONST | 729,748 | 73.0 | 16.5% | 5.5% | 136 | 1 | 123 |
| IN | 130,524 | 13.1 | 3.0% | 4.8% | 664 | 19 | 419 |
| JUMP_IF_TRUE_KEEP | 112,203 | 11.2 | 2.5% | 3.4% | 555 | 34 | 116 |

**Nova_Stats, 50 ticks:** 0.69 s, 22,940 instructions a tick, 599 ns each. `CALL` is **40.8%** of the run (2,588 calls
a tick, most of them to library functions, which take 31% of the run), dispatch chain
18.5%. **`IMPORT` is 7.2%**: 21 module loads at 2.4 ms each, lexing, parsing and compiling files that never change:
the one place in these programs where the artifact cache of slice 5 pays for itself.

| opcode | count | per tick | % of count | % of time | ns each | chain tests before it | ns without the chain tests |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CALL | 129,390 | 2587.8 | 11.3% | 40.8% | 2164 | 5 | 2099 |
| IMPORT | 21 | 0.4 | 0.0% | 7.2% | 2364537 | 61 | 2363745 |
| LOAD_CONST | 249,269 | 4985.4 | 21.7% | 5.2% | 144 | 1 | 131 |
| LOAD_FAST | 233,861 | 4677.2 | 20.4% | 4.5% | 133 | 0 | 133 |
| RETURN | 32,913 | 658.3 | 2.9% | 3.8% | 787 | 7 | 696 |
| GET_MEMBER | 34,268 | 685.4 | 3.0% | 3.4% | 689 | 28 | 326 |
| ADD | 39,400 | 788.0 | 3.4% | 3.1% | 537 | 9 | 420 |
| STORE_FAST | 78,107 | 1562.1 | 6.8% | 2.9% | 257 | 6 | 180 |

## 5. What one operation costs (probes, in a function, over the empty loop)

Each row is one statement in a loop pass; the figure is what it adds over the empty pass (1,090 ns: `RANGE_NEXT`, `STORE_FAST`,
`JUMP`, themselves 24 tests deep). It includes loading the operands and storing the result.

| probe (one per loop pass) | ns per pass | extra ns over the empty loop |
| --- | ---: | ---: |
| `the empty loop pass` | 1090 |  |
| `x = 7                       (LOAD_CONST, STORE_FAST)` | 1482 | 392 |
| `x = i                       (LOAD_FAST, STORE_FAST)` | 1432 | 343 |
| `x = i + 1                   (int add)` | 2025 | 936 |
| `x = i * 3 % 7               (int mul, mod)` | 2796 | 1707 |
| `x = i < 5                   (int compare)` | 1970 | 881 |
| `x = i == 5                  (int equality)` | 1906 | 817 |
| `x = s >= "a"                (string compare, not on the fast path)` | 2394 | 1304 |
| `x = s == "a"                (string equality)` | 1984 | 894 |
| `x = l[2]                    (list index, in range)` | 2068 | 978 |
| `x = l[-1]                   (list index from the end)` | 3740 | 2650 |
| `x = s[2]                    (string index)` | 2095 | 1005 |
| `x = s[-1]                   (string index from the end)` | 3782 | 2693 |
| `x = d["k"]                  (dictionary lookup)` | 2046 | 956 |
| `x = "b" in s                (substring test)` | 2291 | 1201 |
| `x = k in d                  (dictionary key test)` | 2366 | 1277 |
| `x = t and u                 (boolean and)` | 3090 | 2001 |
| `x = t or u                  (boolean or)` | 2637 | 1547 |
| `if t { x = 1 }              (branch taken)` | 1863 | 774 |
| `if u { x = 1 }              (branch not taken)` | 1490 | 400 |
| `x = len(l)                  (built-in call)` | 2871 | 1781 |
| `x = split(s, ",")           (built-in call, does work)` | 3076 | 1987 |
| `x = one(i)                  (NovaLang function call)` | 4575 | 3486 |
| `x = zero()                  (NovaLang call, no arguments)` | 3963 | 2873 |
| `x = [i, i]                  (build a list)` | 2175 | 1085 |


What the probes show: an in-range index is ~980 ns and **an index from the end is ~2,650 ns** (Nova_Log counts from the end on every line);
`and` costs ~2,000 ns and `or` ~1,550 ns (they go through `CHECK_BOOL` and a helper); a comparison of strings with `>=` is ~1,300 ns against
~890 for `==`; a **NovaLang function call is ~2,900 to 3,500 ns**, a call to a library function ~1,800 to 2,000.

## 6. The ranked candidates

Each row says what share of a run it could win at most (the share in the profiles above), not what it will win.
Slice 6 takes them in this order, one commit each, with before/after numbers and the M11 invariants as tests. None changes a step count.

| # | Candidate | Upper bound (share of the run) | Evidence | Behaviour risk |
| --- | --- | --- | --- | --- |
| 1 | **Dispatch order.** Replace the 64-way `if`/`elif` chain with one whose hottest opcodes are tested first and whose tail is split (for example by opcode range), so an average instruction makes 2 to 3 tests instead of 8 to 10 | Nova_Log 26.6%, Nova_Data 31.4%, Nova_Stats 18.5%, `arithmetic` 35.0%, `recursion` 14.5%. A realistic target is two thirds of that | The chain position explains most of the slowness of `CHECK_BOOL`, `JUMP_IF_*_KEEP`, `GE`, `NOT`, `RANGE_NEXT`, `SLICE*` (their own cost is 90 to 400 ns) | None: no instruction changes what it does, only where it is found. The order must be driven by the profile, and re-checked, because it silently goes stale |
| 2 | **The call path.** (a) A NovaLang call and return: avoid slicing and deleting the argument list, building a `Frame` and a slots list in separate steps, the `call_stack` push and pop. (b) A library call: skip `call_value`'s generic checks (arity, limits, path grants, result size) on the `trusted`, non-counting path | `CALL` + `RETURN` are Nova_Log 34.3%, Nova_Data 24.2%, Nova_Stats 44.6%, `recursion` 51%. Of that, the interpreter's work around library functions is 8.8%, 7.2% and about 12% | `ns around` is 700 to 950 ns for every library function, however cheap; a user call is ~3 us | (a) none if the step is still counted once per call; (b) must not skip a check `restricted` needs: the fast path is for `trusted` only, or keeps the checks |
| 3 | **Value traffic.** Superinstructions for the common pairs (`LOAD_FAST`+`LOAD_CONST`, `LOAD_FAST`+`LOAD_FAST`, `LOAD_CONST`+`STORE_FAST`, and a load followed by `INDEX` or `GET_MEMBER`) | `LOAD_CONST`, `LOAD_FAST`, `STORE_FAST`, `LOAD_GLOBAL`: Nova_Log 51% of instructions and 19.8% of time, Nova_Data 48% and 20%. About half of it is the most one can remove | Every one of these instructions pays a fetch and tests; fusing two removes one fetch and the tests of the second | A fused pair changes nothing the program can see, but the step budget counts loop passes and calls, not instructions, so it is unaffected; the escape corpus must still run unchanged |

Smaller, for after those, in order of share:

* **Slow paths that leave the fast path**: an index from the end (+1,670 ns over an in-range one), `IN` (Nova_Log 5.9%, Nova_Data 4.8%; its own cost is ~400 ns, via `compare_operation` and `nova_contains`), string `>=`/`<`, `and`/`or` through `CHECK_BOOL`'s helper function. Each is a few lines in the fast path of its opcode.
* **`restricted` costs +40% to +83% on programs that call library functions or build strings** ([`docs/benchmarks.md`](../benchmarks.md)): the step charge, `check_call_arguments`, `operand_work` and the result-size check run at every library call, and a string `+` leaves the fast path when counting. That price is M11's; the aim is to make it cheaper without removing any of the checks.
* **Module loading**: `IMPORT` is 7.2% of Nova_Stats; that is slice 5's cache (D4's caveat applies: it saves compile time, not execution).
* **Start-up**: 57 to 109 ms of Python import before any program runs (the figure moves with the machine's state; [`docs/benchmarks.md`](../benchmarks.md)): standard-library imports that could be lazy. Not in the plan; worth a decision.

`LOAD_BUILTIN` lookups (`lookup_builtin`, 261 ns) are 12,269 per 50 Stats ticks: 0.5% of the run. Not a candidate. `CHECK_BOOL`'s
own cost (170 to 230 ns) is small once its place in the chain is removed.

## 7. Limits of this profile

* It is the bytecode VM under `trusted`, on CPython 3.9.6, on one machine. CPython 3.11 and later make the same loop faster by a different
  amount per opcode, and the test-by-test cost of a chain may differ, so slice 6 measures each change on the whole suite before keeping it.
* Time inside nested `execute` calls (imports, callbacks from `map`) is subtracted from the caller and credited to the callee. A callback's cost appears in `map`'s `inside` time as well as in its own instructions.
* It does not profile the self-hosted interpreter (`--bootstrap`), which runs the language on top of the VM and is not a speed target of M12.
* Allocation counts (the plan asked for them) are not measured here: no allocation hook exists in the VM, and a Python-level tracer would be slower than the program it measures. The call-path numbers above are the proxy.
