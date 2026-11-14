# Benchmarks

Baselines that milestones are measured against. Per-app detail and reproduction steps live in each proof-of-concept repo (Nova_Stats, Nova_Sort, Nova_Log, Nova_Data).

## Real-World Baseline (Pre-M12)

These benchmarks establish the performance and security baseline for the M12 (Bytecode Cache & Performance) and M13 (Libraries) milestones. Run on a MacBook Pro M1 (8GB RAM). Unless noted, engine is the Bytecode VM.

### 1. Nova_Stats (System Telemetry)
- **Throughput:** 11 ms per tick on the VM (649 ms on self-hosted).
- **Memory Profile:** 212 MB peak while sampling six system modules.
- **Findings:** Detected a 100% CPU load spike and memory pressure flip to "warning" caused by parallel Python processes. Established that macOS `pmset` uses a heavily smoothed historical average for battery, while NovaLang correctly calculates instantaneous physics.
- **Gaps:** G-026 (Ctrl-C traceback in embedding API).

### 2. Nova_Sort (Sandbox & File I/O)
- **Throughput:** Instantaneous for a 5-item folder. 
- **Security Baseline:** The sandbox successfully enforced `files.read` and `files.write`. However, it revealed two critical flaws: `files.write` implicitly grants `remove`/`delete` (G-027), and `rename` silently overwrites existing files (G-028). 
- **Findings:** Because the sandbox could not prevent deletions or overwrites, the `Nova_Sort` program had to implement its own safety layer (forbidding delete keywords and checking `exists()` before renaming) to safely manage file system operations.

### 3. Nova_Log (Text Parsing at Scale)
- **Throughput:** Consistent ~24,500 lines/sec across all datasets.
- **Memory Profile:** 212 MB peak for a 50 MB file (proves G-036: no streaming read).
- **Datasets & Results:**
  | Dataset | Lines | Time | Unparsed | Notes |
  |---|---|---|---|---|
  | Sample access log (May 2015) | 10,000 | 0.42s | 0 | Combined log format; first 10,000-line sample file, dated 17 May 2015 |
  | Synthetic (Tesla/Starlink) | 50,000 | 2.05s | 0 | 50/50 split of 200s/404s |
  | Nginx (Modern) | 51,462 | 2.09s | 0 | 6.8MB file, universal parsing |
- **Sandbox Limit:** Refused a 1.1MB file with `a string cannot grow beyond 1000000 characters`. Successfully parsed a 488KB chunk (2,154 lines) in the sandbox.

### 4. Nova_Data (Financial Math)
- **Throughput:** 5,916 records/s (1.69s for 10,000 rows).
- **Dataset:** 10,000 synthetic financial transactions (CSV).
- **Precision Baseline:** 
  - Exact sum (integer cents): `$2,231,316.93`
  - Naive float sum (via `str()`): `2231316.930000008`
  - **Drift:** `$0.000000008` after 9,993 additions (Proves the requirement for exact decimal math, G-044).
- **Resilience:** Successfully rejected 6 corrupted rows (leap year 2025-02-29, `N/A` text, `4.999` fraction, missing fields, month 13) without crashing.
- **Sandbox:** Successfully processed a 700KB CSV in `restricted` mode with `--allow-read data`.

### Summary for M12
The core bottleneck across all PoCs is the VM interpreter's overhead when handling string manipulation, floating-point conversions, and massive memory allocations (e.g., reading whole files into memory). The lack of native `regex`, `index`, and streaming reads forces NovaLang to do heavy lifting in the interpreter rather than in optimized C-level standard library functions.
