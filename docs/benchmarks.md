# Benchmarks

Baselines that milestones are measured against. Each entry names its source so it can be re-run.

## Real-World Baseline (Pre-M12)

Source: [Nova_Log `docs/BENCHMARK.md`](https://github.com/ussdaedalus43821-cloud/Nova_Log/blob/main/docs/BENCHMARK.md), section "Real-World Baseline (Pre-M12)".

Run on a MacBook Pro M1 (8GB RAM) using the default `trusted` profile (to bypass the M11 1MB sandbox limit for large file reads). Engine: VM (no bytecode cache).

| Dataset | Lines | Time | Throughput | Unparsed | Notes |
|---|---|---|---|---|---|
| NASA (1995) | 10,000 | 0.42s | 24,062 /s | 0 | Classic Apache log format |
| Nginx (Modern) | 51,462 | 2.09s | 24,568 /s | 0 | 6.8MB file, tested universal parsing |
| Synthetic (Tesla/Starlink) | 50,000 | 2.05s | 24,440 /s | 0 | 50/50 split of 200s and 404s |

**Observations:**
- The engine scales linearly. Throughput holds steady at ~24,500 lines/sec regardless of file size.
- Zero parsing errors across three completely different log formats.
- The lack of native `regex` or `index` keeps the throughput limited by Python's tree-walking overhead. This is the primary target for M12 (Bytecode) and M13 (Standard Library).
