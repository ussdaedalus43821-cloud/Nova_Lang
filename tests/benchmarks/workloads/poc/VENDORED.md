# Vendored proof-of-concept programs

Copies, unmodified, of the programs and generators of three proof-of-concept apps, so the benchmark suite is
self-contained and its inputs are reproducible without cloning anything. They are workloads, not tests: nothing here
checks their output (each app's own repository does that against an independent oracle).

| Folder | Source repository | Last commit that changed these files | Files |
| --- | --- | --- | --- |
| `nova_data/` | `Nova_Data` | `3302f35` | `nova_data.nova`, `make_csv.py` (from `tools/`) |
| `nova_log/` | `Nova_Log` | `3de7b16` | `nova_log.nova`, `make_log.py` (from `tools/`) |
| `nova_stats/` | `Nova_Stats` | `4a62a2a` | `src/` (the dashboard), `tests/fixtures/` (recorded command output), `tests/bench.nova` |

The generators are seeded, so the CSV and the log are the same bytes on every run. Nova_Stats needs no generator: its
fixtures are committed. `run.py` and `profile_vm.py` write the generated files to a temporary folder and delete it.

Nova_Sort is not here: its work is file-system calls, which benchmark the disk more than the VM.

To refresh a copy, copy the files again from a newer commit and update this table. The repositories are at
https://github.com/ussdaedalus43821-cloud/.
