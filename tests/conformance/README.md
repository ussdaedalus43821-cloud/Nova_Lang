# The conformance corpus

Host-neutral test cases for [the specification](../../docs/spec/README.md): a
program, and what any conforming host must do with it. The format is the one the
game port already uses for its 51 cases (`conformance.json` in `Reactor-Game`),
extended with the spec sections each case tests and a profile.

```
python3 tests/conformance/conformance.py                 run it
python3 tests/run_all.py --station conformance           the same, as a station
python3 tests/conformance/record.py --check              the VM still does what is recorded?
```

## A case

```json
{
 "name": "expr-division-by-zero-error",
 "spec": ["expr.division", "err.arithmetic"],
 "profile": "core",
 "source": "print(1 / 0)",
 "output": [],
 "error": "NovaError: division by zero",
 "error_line": 1,
 "exit": 1,
 "host_calls": []
}
```

| Field | Meaning |
| --- | --- |
| `name` | unique |
| `spec` | the spec sections the case tests (`docs/spec/`, the ids in square brackets) |
| `profile` | the feature set a host needs to run it: `core`, `modules` or `host` (`docs/spec/README.md`) |
| `source` | the program |
| `output` | the lines `print` writes, in order, before the program ends |
| `error` | `Label: message` of the error that ends the program, or `""` |
| `error_line` | the 1-based line of that error, or `null` when it has none; compared only for hosts that report a line |
| `exit` | the process exit status |
| `host_calls` | calls the program makes to the host (none yet; kept for the game cases) |
| `files` | optional; module files the program imports: a map from a relative path (with `/`) to its text. They are written, with the program as `main.nova`, into a folder of their own that the engine runs in, so `import "sub/util.nova"` finds `sub/util.nova`. For the `modules` profile (`docs/spec/08-modules.md`) |
| `error_like` | optional regular expression the error must match instead of equalling `error`, for a message that contains a host-defined limit (the call depth) |
| `deep` | optional; the program recurses until the host's call-depth limit, so it is not run on the tree-walker where that would crash the process (Windows before Python 3.11; a `SKIPPED:` line says so) |
| `divergences` | optional; see below |

`output`, `error` and `exit` are what **the specification says**. They were
first recorded from the reference engine (the bytecode VM, `record.py`) and then
read against the spec text; where the engine did not do what the text says, the
case keeps the spec's value and the engine's behavior goes in `divergences`.

## Rules the station enforces

1. Every case cites at least one spec section, and every cited section exists.
2. Every spec section is cited by at least one case. Writing a section means
   writing the cases that pin it.
3. Every engine produces exactly the recorded `output`, `error` and `exit`
   (and `error_line`, for the two engines that report one).
4. **Divergences**: where an engine is known to disagree with the spec, the case
   carries `"divergences": {"<engine>": {"id": "D-003", "output": ..., "error":
   ..., "exit": ...}}`. The station requires that engine to behave exactly as
   recorded, so a disagreement cannot grow unnoticed; and fails when it starts
   following the spec, so the entry gets closed. An entry whose behavior differs between
   Python releases and so cannot be pinned (D-013) says `Untested:` and needs no case.
   Each id must be in
   [`DIVERGENCES.md`](../../docs/spec/DIVERGENCES.md) as `open`, and every `open`
   entry must be used by a case. A divergence that is a stack overflow carries
   `"unstable": true`, because it ends differently on different Pythons.
5. One systematic difference is not repeated in every case: the self-hosted
   interpreter's error headlines (D-001). Its `Error:` label and its
   `LexError@12:` / `ParseError@12:` prefix are removed before comparing, and
   its line number is not compared. An import failure arrives as
   `Error: ImportError: message` and is read as the `ImportError` label. The
   rule is `normalize()` in `conformance.py`. For an `ImportError` every engine's
   error is cut after its first line, because what follows names places on the
   machine (folders searched, a nested report); a case that needs the rest
   catches the error and tests the text with `in`.

## Engines

| Name | What runs |
| --- | --- |
| `vm` | `novalang.Interpreter("vm")`, in this process |
| `tree` | `novalang.Interpreter("tree")`, in this process |
| `bootstrap` | `novalang.py --bootstrap`, one subprocess per case, four at a time |

## Adding to the corpus

1. Write the section in `docs/spec/` with an id, `## [group.name] Title`.
2. Add cases that cite it, in `cases/<area>.json`. Give the expected values the
   spec states; `record.py --missing` fills absent ones from the VM, and you read
   them against the text.
3. Run the station. For each engine that disagrees, either fix the engine, fix
   the text, or add the entry to the divergence log and the case.

The cases are data, not code, so another implementation (the GDScript port, a
future host) can read the same files.
