# M10 dialect inventory: what the game dialect really differs in

Status: measurement, written at the start of M10 (2026-11-08). It feeds
[ADR 0004](../decisions/0004-policy-dialect-after-measurement.md), which asks the
owner whether [ADR 0002](../decisions/0002-game-dialect-and-profiles.md) still
holds. Nothing here changes the language.

ADR 0002 listed the differences it had measured at the time (11 rows in two
tables) and called that list "the dialect's entire surface". M10's first task was
to turn that list into named switches. Before naming anything, this document
counts what the dialect actually does, from the game's own sources
(`reference/nova_lexer.py`, `nova_parser.py`, `nova_evaluator.py`, `nova_vm.py`,
`reactor_host.py` and `docs/NOVALANG.md` in Reactor-Game) and from running its 51
recorded oracle programs on NovaLang.

## The experiment

`tools/dialect_probe.py` takes each oracle program, parses it with the game's own
parser, writes the AST back out as NovaLang source (`func` becomes `def`, one
statement per line, strings quoted), and runs the result on `novalang.py`. That is
the most generous translation possible: it changes **only syntax**. Whatever
still differs afterwards is semantics, which is what a profile switch would have
to supply.

| Result of the 51 programs | Count |
| --- | --- |
| Identical output after the syntactic translation | **12** |
| NovaLang has no way to write the program at all | 12 |
| The program runs but prints something different, or one side fails | 15 |
| Both fail, with a different message | 9 |
| NovaLang never stops (`while true { }`; no step budget) | 1 |
| The oracle case is itself a lexer or parser error (nothing to translate) | 2 |

So **12 of 51 (24%)** agree after the best possible syntax translation. The 12 are
plain arithmetic, `let`/`if`/`while`, and named functions.

## The surface, by layer

Counted as independent behaviours, each of which would need its own switch and its
own tests. "Core" is NovaLang v2.1.0.

Every "core" cell below was checked by running it on `novalang.py` 2.1.0.

### Lexical (5)

| # | Game dialect | Core |
| --- | --- | --- |
| L1 | `//` starts a comment (as does `#`) | `//` is the **division operator**: `print(1 // 2)` prints `0`. The same characters mean two different things. |
| L2 | Reserved words: `func set null import export as reactor version params effects signals rule fault when then priority once edge weight duration label persistent` (plus the common ones) | Reserved: `def for to downto step in delete try catch finally throw with`. Each side's keywords are the other side's legal names. |
| L3 | Number literals take an exponent: `1e3`, `2E-2` | `1e3` is a syntax error |
| L4 | A string may contain a raw newline; an unknown escape keeps the character (`"\q"` is `q`) | Both are errors |
| L5 | Every number is a 64-bit float; there is no integer type | Integer and float are distinct types |

### Syntax (11, plus the rule-engine grammar)

| # | Game dialect | Core |
| --- | --- | --- |
| S1 | `func name(...) { }`, and `func (...) { }` as an **anonymous function expression** | `def` only; no anonymous functions |
| S2 | Newlines mean nothing: `let a = 1 a = a + 1 print(a)` on one line is three statements | A line end ends a statement |
| S3 | `{` in statement position is always a block (a dict statement needs parentheses) | `{ let x = 2 }` is read as a dict literal and fails |
| S4 | `set target = value` as well as bare `target = value` | Bare assignment only |
| S5 | A dict key may be a computed `[expr]`; bare keys may be keywords | Bare or string keys only |
| S6 | A trailing comma is allowed in calls, lists and dicts | `[1, 2,]` is a syntax error (calls too) |
| S7 | `a < b < c` is `(a < b) < c` | Refused: "chained comparisons ... are not supported yet" |
| S8 | `return` with no value only before `}` or end of file | By line end |
| S9 | `import "p"` with no alias merges every export into the importer's scope | Alias form only |
| S10 | `export` names are collected; the **final** value of each is exported when the module has run | The value when the `export` statement runs (`[mod.export]`) |
| S11 | No `for`, `try`/`catch`/`finally`, `throw`, `delete`, f-strings, slicing, loop `else` | All present |

### Values and operators (15)

| # | Game dialect | Core |
| --- | --- | --- |
| V1 | `null` is a value; a function that does not `return` gives `null`; it prints `null` and `type(null)` is `"null"` | `nothing`, printed `nothing`, no literal |
| V2 | Truthiness in `if`, `while`, `and`, `or`, `not`: `0 "" [] {} null` are false, all else true | The condition must be a boolean |
| V3 | `+` with a string on either side concatenates the display text (`"n=" + 42`); `list + list` joins | String + number is an error |
| V4 | `/` and `%` by zero give `0`; `%` is C `fmod` (`-7 % 3` is `-1`) | Division by zero is an error; `%` is floored (`-7 % 3` is `2`) |
| V5 | `<` `>` `<=` `>=` accept numbers only; strings cannot be ordered | Strings can be compared |
| V6 | A boolean counts as 0 or 1 in arithmetic | `true + 1` is an error |
| V7 | Number display: integer-valued and under 1e15 prints without a point, otherwise `%.6f` with trailing zeros trimmed (`1/3` prints `0.333333`) | Shortest round-trip digits (`0.3333333333333333`) |
| V8 | A function prints `<func name>`; names from `let f = func ...` are inferred | `<function f(a, b)>` |
| V9 | `type()` answers `number string bool list dict func null` | `number string boolean list dict function` |
| V10 | A dict key is always text: `d[1]` reads the key `"1"`, and assigning creates it | A non-string key is an error |
| V11 | Assigning to a name that exists nowhere creates a **global**, even inside a function | It creates a local |
| V12 | A name in call position: user function, else builtin, else host function; a **non-function binding is skipped** | A non-function is a call error |
| V13 | Builtins are not values: `let g = len` is an unknown identifier | Builtins are first-class |
| V14 | Builtin arity is a minimum; extra arguments are ignored | Exact |
| V15 | A variable and a host function of the same name coexist (`scram`) | One namespace |

### Builtins (38 defined by the dialect)

NovaLang has **19** of the 38 names and lacks **14**: `clamp exp ramp lerp pick
rand held bool int has get remove_at slice contains`. Of the 19 it has, these
differ when called the same way: `round` (half away from zero; core is
half-even: `round(2.5)` is `2` there, `3` in the dialect), `sqrt(-1)` (`0`;
core: error), `pow` overflow (infinity; core: a 4,000-digit integer), `upper`,
`lower`, `join`, `split` and `num` (coerce anything to text or give `0` for
unreadable text; core refuses: `upper(5)`, `num("bad")`), `split(s, "")`
(characters; core: error), `min` / `max` (numbers only; core also takes a list),
`type` (see V9), `print` (writes to a buffer the host drains rather than to
standard output). That is **about 25 of 38** needing a new or overriding
definition, each a spec section's worth of cases.

### Limits and errors (4)

| # | Game dialect | Core |
| --- | --- | --- |
| E1 | Call depth 128 | 1,200 |
| E2 | Step budget 500,000 per run (every statement and expression node costs one); `while true { }` fails the run | None; `while true { }` never stops (confirmed by the probe: 1 of the 51 cases times out) |
| E3 | Every error is `line N: message`; the first error stops the run; no `try` | Label, message and source excerpt; `try`/`catch` |
| E4 | Different wording in all 14 error cases of the oracle (`unknown identifier 'nope'`, `cannot call a number`, `f() takes 2 argument(s), got 1`, `dict has no key 'missing'`, ...) | Core wording (`undefined name 'nope'`, ...) |

### The rule engine (an extension, not a switch)

`reactor`, `params`, `signals`, `effects`, `rule` (`priority once edge`), `fault`
(`weight duration label`), the `held(cond, seconds)` per-call-site timer, the
per-tick order (reset effects, load inputs, fault scheduler, overrides, signals,
rules by priority), the random draws the fault scheduler makes, `persistent`,
the host-function contract (`log alarm scram reset_trip meltdown victory
inject_fault clear_fault`), `describe()`, and `reset(seed)`. ADR 0002 said "the
rule-engine declarations as an extension"; that is a chapter of its own, about
the size of `04-errors.md`.

## The count

| Layer | Items |
| --- | --- |
| Lexical | 5 |
| Syntax | 11 (+ the rule-engine grammar) |
| Values and operators | 15 |
| Builtins | about 25 new or overriding |
| Limits and errors | 4 |
| **Total independent behaviours** | **about 60**, plus the rule engine |

ADR 0002's tables held 11 rows. The measured surface is about five times that.
The probe found no case among the 12 that agree where the agreement is more
than plain arithmetic, `let`/`if`/`while` and named functions.

## What this does to ADR 0002's two triggers

1. **"The switch list grows beyond what can be tested exhaustively."** It has. The
   switches are not independent (S2 changes how every other construct is
   parsed; V7 changes every printed number; L1 gives the same two characters two
   meanings), so testing each in isolation proves
   little, and testing combinations is impossible at about 60 switches. The only
   testable unit is the whole bundle.
2. **"A switch would change the meaning of existing official programs."** Not if a
   profile is chosen explicitly and `core` stays the default: no official program
   changes. But three of the switches (S2, V2, V7) would sit inside the lexer,
   the parser and the number formatter that every official program also goes
   through, in three engines (tree, VM, self-hosted). That is a risk to the 1,925
   checks, not a change of meaning.

Both facts point the same way. The recommendation and the options are in ADR 0004.

## Reproducing the numbers

```bash
python3 tools/dialect_probe.py /path/to/Reactor-Game
```

prints the table above and, per program, its result and the first difference.
