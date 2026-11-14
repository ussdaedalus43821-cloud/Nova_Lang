# 17. The bytecode artifact (`.novac`)

Status: **Owner-decided and implemented on the bytecode VM; not independently reviewed.** This chapter is the specification of
milestone M12's bytecode format ([the plan](../design/m12-runtime-plan.md), slices 3 and 4). It is implemented by `dump_artifact` and
`load_artifact` in `novalang.py`, by the commands `--compile`, `--check-artifact` and running a `.novac`, and is tested by the `bytecode`
conformance profile (below) and by `tests/bytecode/` (golden fixtures, a seeded fuzzer, and the whole conformance corpus run through an
artifact). The compiled-artifact **cache** that uses it is not part of this chapter yet: its rules are in
[`../design/m12-bytecode-notes.md`](../design/m12-bytecode-notes.md) and join this chapter, with the cases that pin them, when slice 5 lands.
The decisions behind the format, and what reading the compiler and the VM found, are in the same notes.

**What this chapter claims, and what it does not.** An artifact is the compiled form of one source text, written down so a later run can skip
lexing, parsing and compiling, and so a program can travel as one self-contained file. It is **a cache of a compilation, not a security
boundary and not an authenticity check** (`[bc.overview]`, `[bc.provenance]`). The chapter specifies what a reader must accept and what it must
refuse; it does not specify an instruction selection, so two hosts compile the same source to different bytes and both conform.

**Profile.** Cases of the `bytecode` profile (`tests/conformance/cases/bytecode.json`) run only on the bytecode VM; the tree-walker and the
self-hosted interpreter have no artifacts. A case gives either a `source` (the host writes an artifact from it, reads it back and runs it, and the
result must be the program's own) or an `artifact` (hexadecimal bytes: the host reads that file; a refusal is the result `name: message`, status 1,
no output). `deterministic` asks the host to check `[bc.determinism]`. A `sandbox` object, as in the `sandbox` profile, sets the engine's grants.

## [bc.overview] What an artifact is, and is not

An artifact is a file holding the compiled form of **one source text**: a module's code object and, nested in it, one code object per function.
It is what `Compiler` makes from a program (`compile_source`), written down so a later run can skip lexing, parsing and compiling.

* It is **self-contained** (decided 2026-11-14): it carries the source text it was compiled from, so it can be run, type-checked and reported on without the
  original file.
* It is **a cache of a compilation, not a program in its own right.** Everything an artifact does is something the source could do: it runs on the
  same VM, under the same profile, limits and grants as the source would.
* It is **not a security boundary and not an authenticity check.** The trailing checksum detects accident, not tampering: anyone who can write
  an artifact can compute its checksum. What keeps a hostile artifact from doing more than a program can is `[bc.verify]` and `[bc.constants]`: the loader
  reads a closed set of types and checks everything the VM would otherwise trust.
* It is **not an API** (decision D3 of [the M12 plan](../design/m12-runtime-plan.md)): any minor release may change the format. The only promise is `[bc.reject]`: an artifact is **accepted or cleanly rejected,
  never misread**.
* It is **independent of the profile.** A gated name compiles to `LOAD_BUILTIN` and is resolved by the engine that runs the code; one artifact is right
  for a `trusted` and a `restricted` engine (M11). `[bc.profile]` keeps it so.
* It does **not** change what any program prints, which error it raises, or what a step budget means: running loaded code is the same VM running the
  same instructions.

Terms: *code object* (ops, arguments, positions, constants, exception table, slots); *pool* (a code object's constants); *name* (a length-prefixed
UTF-8 string, `[bc.encoding]`); *loader* (the code that reads an artifact); *compiler version* (the string `novalang.__version__`).

## [bc.encoding] Primitive encodings

All integers are **fixed-width, little-endian, unsigned**. There are no variable-length integers and no padding or alignment.

| Type | Encoding |
| --- | --- |
| `u8` | one byte |
| `u32` | four bytes |
| *name* | a `u32` length in bytes, then that many bytes of **UTF-8**; the bytes must decode without error and must not contain a surrogate; length at most `[bc.limits]` *string* |
| *list of X* | a `u32` count, then that many X |
| flag | a `u8` that is 0 or 1; any other value is rejected |

A reader never trusts a length: it checks that the bytes remain **before** it allocates or reads. Anything after the last field of the artifact
(before the checksum) is rejected (`trailing-bytes`).

## [bc.header] Header, body and trailer

```
magic            8 bytes   4E 4F 56 41 43 0D 0A 1A   ("NOVAC", CR, LF, SUB: a text-mode copy or a line-ending change is caught)
format version   u32       0 in development builds, 1 in the first release (Q7); a loader reads only its own
opcode-set hash  32 bytes  SHA-256 of the opcode table of [bc.ops]
compiler version name      the compiler's version string, at most 64 bytes
flags            u32       bit 0: the source has type annotations; bit 1: the source has imports; all other bits must be 0
source hash      32 bytes  SHA-256 of the source text, as UTF-8
source           name      the source text exactly as it was compiled (a *name* is a length and UTF-8 bytes: no compression in format 1, Q8)
body length      u32       the number of bytes of the body
body             ...       one code object (the module's), [bc.code]
checksum         32 bytes  SHA-256 of every byte before this field (header and body)
```

* **Why the version string is in the header** (the approved "compiler-version information"): so a rejection can say which compiler made the file, and so the
  key of a cache of artifacts includes it. It is informational for rejection; acceptance is decided by the format version and the opcode-set hash (decision D2 of [the M12 plan](../design/m12-runtime-plan.md)).
* **Flags** exist for one reason, `[bc.profile]`: a program with annotations or imports must still pass the type gate when its code comes from an artifact.
* **The source** is embedded (a decision of the owner). The loader checks that the SHA-256 of the embedded source is the header's source hash; a caller
  that has its own copy of the source (the cache) additionally checks that the two are identical. The embedded source is what a standalone run uses for the type
  gate and for error lines (`[bc.profile]`). **It is not proof that the code was compiled from it** (`[bc.provenance]`).
* **The checksum** is checked first, over the whole file, before anything else is interpreted. It is not a signature.
* The **opcode-set hash** is of this canonical text, one line per opcode in order, `number SP name SP argument-kind SP stack-effect SP r<revision>` and a
  line feed after each line, where the first four fields are the columns of `[bc.ops]` and `r<revision>` is a per-opcode counter that starts at 1 and that
  **a developer must raise whenever the meaning of an opcode changes**, because no hash of names can see a change of meaning. For the table of this draft
  the hash is `47db9dde28b66cbe920e15c3f75a54d69710e4f36172bb86de78829df6785060`; it changes with any edit to the table.

## [bc.constants] Constants

A code object's *pool* holds the values `LOAD_CONST` pushes and the code objects `MAKE_FUNCTION` builds functions from, **and nothing else**. Each
entry is a `u8` tag followed by its payload:

| Tag | Type | Payload |
| ---: | --- | --- |
| 0 | `nothing` | none |
| 1 | `false` | none |
| 2 | `true` | none |
| 3 | integer | a `u8` sign (0 or 1), then a list of `u8` (the magnitude, little-endian, **no leading zero byte**, empty for zero; zero is never negative) |
| 4 | float | eight bytes, an IEEE 754 binary64 in little-endian order; **a NaN is rejected** (the compiler never makes one); positive infinity is accepted (a float literal too large for a binary64 compiles to it, G-052 in [`../GAPS.md`](../GAPS.md)) |
| 5 | text | a *name* |
| 6 | built-in function | a *name*: the name of an ungated built-in; resolved against the loader's own table (`[bc.verify]` V13) |
| 7 | code object | a code object, nested (`[bc.code]`) |

* **There is no list, dictionary or tuple constant**, and no other type. Everything the compiler keeps in its pool as a tuple or list (the keys of a
  `BUILD_DICT`, the slots of `NEW_CELLS`, a `LOAD_CHAIN` chain, the pair of an `IMPORT_NAME`) is an **argument of its instruction** in the file
  (`[bc.ops]`, argument kinds), and the loader rebuilds the in-memory form from it. This is how the approved rule and the compiler's habits fit together.
* **Integers** are limited to 4,000 decimal digits, the limit of the language (`port.integers`); the loader checks the *byte count* of the magnitude
  (`[bc.limits]`) before it makes the integer, so a file cannot make the loader build a huge number.
* **Equal constants are written once** (the compiler already shares them), in order of first use. A float and an integer of equal value are two entries.
* There is **no object reference** of any kind in an artifact: a built-in is a name, a code object is nested bytes, a function is made at run time.

## [bc.code] A code object

```
name              name           "<module>" or the function's name
slot count        u32            nslots: the size of a frame's slot list
parameters        list of u32    the slots of the parameters, in order
parameter names   list of name   one per parameter (the same count)
cell parameters   list of u32    the parameters that are cells; each must be one of the parameters
slot names        list of name   exactly nslots entries (debugging text only)
free names        list of name   the variables of enclosing frames this code reads (debugging text only)
closure           list of entry  how MAKE_FUNCTION builds this function's closure, in the parent: a u8 kind (1 cell, 2 free) and a u32 index;
                                 as many entries as there are free names; empty for a module
pool              list of constant
instruction count u32            n
instructions      n x (u8 opcode, argument)    the argument is encoded by the opcode's kind
positions         n x u32        a source offset per instruction (in characters), or FFFFFFFF for none
exception table   list of entry  each: u32 start, u32 end, u32 handler, u8 kind (0 catch, 1 finally); innermost first
```

* The pool comes **before** the instructions so the loader can check every reference as it reads it.
* **Positions are character offsets into the embedded source**, as in memory, so an error in loaded code points to the same line and column, with the same caret, as an
  error in compiled code. The loader checks every position is below the length of the source in characters, or is `FFFFFFFF`.
* **Slot names and free names are not used by the VM**, only by the disassembler (`--dis`); they are in the file because `--dis` on a cached artifact must
  give the same listing, and they are checked for length and encoding like everything else.
* `closure` is the one place a code object depends on its parent: entry kind 1 reads the parent's slot (which holds a cell), kind 2 the parent's free cell.
  `[bc.verify]` V9 checks the indexes against the parent when the parent's `MAKE_FUNCTION` is read.

## [bc.ops] The instruction set

66 opcodes, numbered as in the table (the number is the byte in the file). The table is generated from `novalang.OPCODES` and `novalang.STACK_EFFECT`;
slice 4 adds a test that regenerates it and fails on any difference. "Stack" is the change in stack depth; the VM's rules are in
[`novalang.py`](../../novalang.py) (`execute`) and the meaning of each operation in chapters 02 to 11.

| # | opcode | argument | stack | what it does |
| ---: | --- | --- | --- | --- |
| 0 | `LOAD_CONST` | `const` | +1 | push constant `arg` of the pool |
| 1 | `POP` | - | -1 | discard the top value |
| 2 | `DUP` | - | +1 | push a second reference to the top value |
| 3 | `LOAD_FAST` | `slot` | +1 | push the value in the slot |
| 4 | `STORE_FAST` | `slot` | -1 | pop into the slot |
| 5 | `LOAD_CELL` | `slot` | +1 | push the value held by the cell in the slot |
| 6 | `STORE_CELL` | `slot` | -1 | pop into the cell in the slot |
| 7 | `LOAD_GLOBAL` | `name` | +1 | push a module global; `undefined name` if it is not set |
| 8 | `STORE_GLOBAL` | `name` | -1 | pop into a module global |
| 9 | `LOAD_CHAIN` | `chain` | +1 | try the listed locations in order and push the first that is set; `undefined name` if none is |
| 10 | `STORE_CHAIN` | `chain` | -1 | pop; store into the first listed location that is already set, else into the last |
| 11 | `NEW_CELLS` | `slots` | 0 | put a fresh empty cell in each listed slot |
| 12 | `RESET_SLOTS` | `slots` | 0 | mark each listed slot as not set |
| 13 | `LOAD_BUILTIN` | `name` | +1 | push the running engine's built-in of that name (gated names resolve per engine); `undefined name` if the engine does not define it |
| 14 | `ADD` | - | -1 | pop the right operand; replace the left with the sum |
| 15 | `SUB` | - | -1 | as ADD, difference |
| 16 | `MUL` | - | -1 | as ADD, product |
| 17 | `DIV` | - | -1 | as ADD, quotient |
| 18 | `FLOOR_DIV` | - | -1 | as ADD, floor quotient |
| 19 | `MOD` | - | -1 | as ADD, remainder |
| 20 | `NEG` | - | 0 | replace the top with its negation |
| 21 | `POS` | - | 0 | replace the top with its unary plus |
| 22 | `NOT` | - | 0 | replace the top with its logical negation |
| 23 | `EQ` | - | -1 | pop the right operand; replace the left with `==` |
| 24 | `NE` | - | -1 | as EQ, `!=` |
| 25 | `LT` | - | -1 | as EQ, `<` |
| 26 | `GT` | - | -1 | as EQ, `>` |
| 27 | `LE` | - | -1 | as EQ, `<=` |
| 28 | `GE` | - | -1 | as EQ, `>=` |
| 29 | `IN` | - | -1 | pop the container; replace the item with whether it is in it |
| 30 | `CHECK_BOOL` | `sideop` | 0 | error unless the top is `true` or `false` (it is an operand of `and` / `or`) |
| 31 | `JUMP_IF_FALSE_KEEP` | `target` | -1 (0 if taken) | if the top is false jump, keeping it; otherwise pop it |
| 32 | `JUMP_IF_TRUE_KEEP` | `target` | -1 (0 if taken) | if the top is true jump, keeping it; otherwise pop it |
| 33 | `BUILD_LIST` | `count` | 1 - n | pop n values; push a list of them |
| 34 | `BUILD_DICT` | `keys` | 1 - n | pop one value per listed key; push a dictionary |
| 35 | `BUILD_STRING` | `count` | 1 - n | pop n parts; push their text (an f-string) |
| 36 | `INDEX` | - | -1 | pop the index; replace the target with the element |
| 37 | `SLICE_TARGET` | - | 0 | error unless the top can be sliced |
| 38 | `SLICE_BOUND` | - | 0 | error unless the top is a whole-number slice bound |
| 39 | `SLICE` | `flags2` | - (flags set) | pop the end and the start if their flags are set; replace the target with the slice |
| 40 | `GET_MEMBER` | `name` | 0 | replace the top with its member of that name |
| 41 | `INDEX_ASSIGN_TARGET` | - | 0 | error unless the target can be assigned through an index |
| 42 | `INDEX_ASSIGN_KEY` | - | 0 | check the key against the target (stack: target, key) |
| 43 | `INDEX_ASSIGN` | - | -2 | pop the value and the index; store; the value replaces the target |
| 44 | `MEMBER_ASSIGN_TARGET` | - | 0 | error unless the target can be assigned through a member |
| 45 | `SET_MEMBER` | `name` | -1 | pop the value; store it in the target's member; the value replaces the target |
| 46 | `DELETE_TARGET` | - | 0 | error unless the target can have an entry deleted |
| 47 | `DELETE_KEY` | - | -1 | pop the key; delete it from the target; `nothing` replaces the target |
| 48 | `DELETE_FILE` | - | 0 | replace the path on top with the result of deleting that file (a host capability) |
| 49 | `JUMP` | `target` | 0 | continue at the instruction `arg` |
| 50 | `JUMP_IF_NOT_TRUE` | `condtarget` | -1 | pop the condition; jump unless it is `true`; error if it is not a boolean (the text names `if` or `while`) |
| 51 | `LOOP_NUMBER` | `role` | 0 | error unless the top is a number, naming the loop role |
| 52 | `RANGE_PREP` | `rangeprep` | -(2 + step flag) | pop start, end and optional step; build the loop state in the slot |
| 53 | `RANGE_NEXT` | `slottarget` | 0 if taken, +1 otherwise | next number of the range, or jump when it is finished |
| 54 | `ITER_PREP` | `iterprep` | -1 | pop the iterable; build the loop state in the slot |
| 55 | `ITER_NEXT` | `slottarget` | 0 if taken, +names otherwise | next item (or key and value), or jump when finished |
| 56 | `MAKE_FUNCTION` | `const` | +1 | push a function made from code constant `arg` and its closure |
| 57 | `CALL` | `count` | -n | pop n arguments and the callee; push the result |
| 58 | `RETURN` | - | -1 | pop the result and leave the frame (verification requires depth exactly 1) |
| 59 | `THROW` | - | -1 | pop a value and raise it as a program error |
| 60 | `RERAISE` | `slot` | 0 | raise again the exception held in the slot (the end of a `finally`) |
| 61 | `STRAY` | `stray` | 0 | raise the signal of a `break`, `continue` or `return` that is not inside a loop or function |
| 62 | `FAIL` | `failtext` | 0 | raise a program error with a message and a label fixed at compile time |
| 63 | `IMPORT` | `name` | +1 | load the module at that path; push its value |
| 64 | `IMPORT_NAME` | `importname` | 0 | replace the module on top with one of its exports |
| 65 | `EXPORT` | `name` | 0 | record the top value as an export of that name; it stays on the stack |

**Argument kinds.** One kind per opcode, fixed by the table:

| kind | encoding | used by |
| --- | --- | --- |
| `slot` | `u32` slot number, below `nslots` | LOAD_FAST, STORE_FAST, LOAD_CELL, STORE_CELL, RERAISE |
| `count` | `u32` count | BUILD_LIST, BUILD_STRING, CALL |
| `target` | `u32` instruction index, below the instruction count | JUMP, JUMP_IF_FALSE_KEEP, JUMP_IF_TRUE_KEEP |
| `const` | `u32` index into the constants pool | LOAD_CONST (any pool type except code), MAKE_FUNCTION (a code object) |
| `name` | a *name*: `u32` length, then UTF-8 | LOAD_GLOBAL, STORE_GLOBAL, LOAD_BUILTIN, GET_MEMBER, SET_MEMBER, EXPORT, IMPORT |
| `chain` | `u32` n (at least 1), then n entries, each a `u8` kind (0 fast, 1 cell, 2 free, 3 global) and a `u32` index (a *name* for kind 3) | LOAD_CHAIN, STORE_CHAIN |
| `slots` | `u32` n (at least 1), then n `u32` slot numbers | NEW_CELLS, RESET_SLOTS |
| `keys` | `u32` n, then n *names* (the dictionary keys, in order) | BUILD_DICT |
| `sideop` | `u8` side (0 left, 1 right), `u8` operator (0 `and`, 1 `or`) | CHECK_BOOL |
| `flags2` | two `u8`, each 0 or 1: a start is present, an end is present | SLICE |
| `condtarget` | `u8` condition (0 `if`, 1 `while`), then a `u32` target | JUMP_IF_NOT_TRUE |
| `role` | `u8` loop role (0 the start of a `for` range, 1 its end, 2 its step) | LOOP_NUMBER |
| `rangeprep` | `u32` slot, `u8` descending (0/1), `u8` has a step (0/1) | RANGE_PREP |
| `slottarget` | `u32` slot, then a `u32` target | RANGE_NEXT, ITER_NEXT |
| `iterprep` | `u32` slot, `u8` names (1 or 2) | ITER_PREP |
| `stray` | `u8` (0 `return`, 1 `break`, 2 `continue`) | STRAY |
| `failtext` | two *names*: the message, then the label | FAIL |
| `importname` | two *names*: the exported name, then the module path | IMPORT_NAME |

An argument is read with exactly its kind's width. An opcode number outside the table, or an argument that does not fit its kind, is rejected
(`bad-opcode`, `bad-argument`).

## [bc.verify] What the loader checks, and what it does not

`verify(code)` exists today (`novalang.py`). It checks jump targets, the slots of five opcodes, the exception table, the stack depth (it must agree
wherever paths meet, never go negative, and be exactly 1 at `RETURN`), that execution never falls off the end, and the nested code objects. **It is not
enough for a file from outside**: the VM trusts several things `verify()` never looks at (finding F4 of [`../design/m12-bytecode-notes.md`](../design/m12-bytecode-notes.md)). The loader MUST check all of the following,
in this order, and reject with `failed-verify` and the check's number (V1 to V14) when one fails:

| # | Check |
| ---: | --- |
| V1 | the nested depth of code objects is at most `[bc.limits]` *depth*, counted by the loader itself (never by the host's recursion limit, G-051 in [`../GAPS.md`](../GAPS.md)) |
| V2 | every pool index (`LOAD_CONST`, `MAKE_FUNCTION`) is below the pool size; `LOAD_CONST` names a non-code entry and `MAKE_FUNCTION` a code entry |
| V3 | every slot number (`LOAD_FAST`, `STORE_FAST`, `LOAD_CELL`, `STORE_CELL`, `RERAISE`, `NEW_CELLS`, `RESET_SLOTS`, `RANGE_PREP`, `RANGE_NEXT`, `ITER_PREP`, `ITER_NEXT`, and each slot in `parameters`, `cell parameters` and `closure` kind 1) is below `nslots` |
| V4 | every jump target and handler is below the instruction count; every exception table entry has start below end |
| V5 | in a `chain`, every `fast` and `cell` index is below `nslots` and every `free` index is below the number of free names; the chain is not empty |
| V6 | the stack depth is consistent on every path and `RETURN` is reached at depth exactly 1 (what `verify()` does now), including the handler entry depth of 1 |
| V7 | `BUILD_LIST`, `BUILD_STRING` and `CALL` counts, and the number of keys of `BUILD_DICT`, never take more values than the depth allows (implied by V6) and are below `[bc.limits]` *operands* |
| V8 | `ITER_NEXT` refers to the slot of the `ITER_PREP` that dominates it, and its depth effect is that `ITER_PREP`'s names count (what `verify()` resolves now); `RANGE_NEXT` likewise refers to a `RANGE_PREP` slot |
| V9 | `closure` entry kind 1 index is below the parent's `nslots` and kind 2 index is below the parent's free-name count, checked at the parent's `MAKE_FUNCTION` |
| V10 | `cell parameters` is a subset of `parameters`; the parameter and parameter-name counts are equal; `slot names` has `nslots` entries; the closure has as many entries as there are free names |
| V11 | every enumerated byte (a side, an operator, a condition, a role, a stray kind, a loop-state count, a chain kind, a closure kind, a flag) is one of its allowed values |
| V12 | the code ends in an instruction that cannot fall off the end (`JUMP`, `RETURN`, `THROW`, `RERAISE`, `STRAY`, `FAIL`), which `verify()` already proves by walking every path |
| V14 | every position is `FFFFFFFF` or below the number of characters of the embedded source |
| V13 | a built-in function constant (tag 6) names a built-in that exists in the loader's table **and is not gated**: not in `CAPABILITY_OF`. Gated names are reached only through `LOAD_BUILTIN`, which the running engine resolves; a tag 6 entry for `read`, `write`, `exit` or any other gated built-in is rejected, because it would hand a program a function its engine's grants may never have allowed |

**What verification does not prove,** said as plainly as `[sbx.claims]` requires: that the code is the compilation of any particular source (the source hash
and the checksum are not a proof); that it terminates; that it uses only values of the right *runtime* types (the VM checks those as it runs, as for compiled
code); or that it is safe to run outside its grants. Capability gating is still `LOAD_BUILTIN` and the run-time checks. Verification makes a hostile file
behave **like some program**, not like *this* program.

**The containment rule (decided by the owner).** The loader raises only the errors of `[bc.reject]`. If it hits anything
else (a Python exception from a malformed value, memory exhaustion, an internal bug), it converts it to `InternalError` (`internal-error`) and rejects the
artifact: it never lets a traceback, a crash or a partially built code object escape. The consequence for a host that caches artifacts is that every rejection means *ignore
the file and compile from source*. The runtime has the matching rule: an exception that is not a `NovaError` leaving the VM while it runs
loaded code is reported as `InternalError`, not as a Python traceback.

**As implemented.** V1, V2, V3, V5, V7 to V11 and V14 are checked while the file is read (`read_code`, `read_argument`); V3 includes a *role* for every slot (plain variable, cell or loop
state), and a slot with two roles is refused; V8 is a forward data-flow over the instructions (`check_loop_state`), a handler starting from what holds at every instruction of the range it
protects; V4, V6 and V12 are `verify()` itself, run last on the rebuilt code; V13 is checked as each built-in constant is read. Not proved, and left to the containment rule: that a cell was
made (`NEW_CELLS`) before `LOAD_CELL` reads it. A test (`test_bc_verify_a_cell_that_was_never_made_is_internal_error_not_a_traceback`) shows such a file runs to `InternalError`, status 70.

## [bc.reject] Rejection

`load(bytes)` returns a verified code object or raises `BytecodeLoadError` with a **name** and a message. These are the only outcomes. Messages start with
`bytecode artifact:` and carry no path or user text beyond the figures shown.

| Name | When | Message |
| --- | --- | --- |
| `truncated` | fewer bytes than a length or the body length says | `bytecode artifact: truncated` |
| `bad-magic` | the first eight bytes are not the magic | `bytecode artifact: not a NovaLang bytecode file` |
| `checksum-mismatch` | the SHA-256 of header and body is not the trailer | `bytecode artifact: checksum mismatch (the file is damaged)` |
| `unknown-format-version` | the format version is not one this loader reads | `bytecode artifact: format version <n> is not supported (this is <m>)` |
| `opcode-set-mismatch` | the opcode-set hash is not this loader's | `bytecode artifact: made for a different instruction set (compiler <version>)` |
| `bad-flags` | a reserved flag bit is set | `bytecode artifact: unknown flags` |
| `trailing-bytes` | bytes remain between the last field and the checksum, or after it | `bytecode artifact: unexpected bytes after the end` |
| `bad-text` | a name is not valid UTF-8, or has a surrogate | `bytecode artifact: text is not valid UTF-8` |
| `bad-constant` | an unknown tag, a NaN, an integer with a leading zero byte or a negative zero, a flag that is not 0 or 1 | `bytecode artifact: bad constant` |
| `bad-opcode` | an opcode number outside the table | `bytecode artifact: unknown instruction <n>` |
| `bad-argument` | reserved: an argument that does not fit its kind; every kind is checked by V3 to V11, so the current table never raises it | `bytecode artifact: bad argument` |
| `unknown-builtin` | V13: tag 6 names no built-in, or a gated one | `bytecode artifact: unknown or gated built-in <name>` |
| `limit-exceeded` | a limit of `[bc.limits]` | `bytecode artifact: too large (<limit>)` |
| `failed-verify` | a check V1 to V12 or V14; an enumerated byte out of range is V11; `verify()`'s own failures (V4 as to jump targets, V6, V12) are reported as V6 | `bytecode artifact: failed verification (V<n>)` |
| `source-mismatch` | the SHA-256 of the embedded source is not the header's, or the caller gave the source it expects and it is not identical to the embedded one | `bytecode artifact: made from a different source` |
| `internal-error` | `[bc.verify]`, the containment rule | `bytecode artifact: internal error while reading` |

The order of checks is the order of the table from the top down to `bad-flags`, then the body in file order, then V1 to V14. A file with two faults reports
the first it meets. **The invariants slice 4 tests:** every prefix of every fixture is `truncated` or another named error; every single-byte change of every
fixture is accepted (and then it is a valid, verified code object) or a named error; a seeded fuzzer finds no input that is accepted and fails `verify()`,
or raises anything else.

## [bc.limits] Limits

| Limit | Value | Because |
| --- | ---: | --- |
| *artifact*: bytes in a file | 67,108,864 (64 MiB) | a loader reads the whole file; far above any real program |
| *string*: bytes in a name, a text constant or the embedded source | 16,777,216 (16 MiB) | the language has no string limit under `trusted`; the `restricted` profile's own 1,000,000-character limit applies when the code runs |
| *integer*: bytes in an integer's magnitude | 1,661 | 4,000 decimal digits is under 13,288 bits |
| *instructions*: per code object | 4,194,304 | the VM keeps `ops` and `args` as lists |
| *pool*: constants per code object | 1,048,576 | |
| *slots*: `nslots` per code object | 1,048,576 | each call allocates a list of this size |
| *operands*: a count, a chain, a list of slots or keys | 1,048,576 | |
| *depth*: nested code objects | 256 | a program that nests functions deeper than this is simply not cached; `dump` refuses it with `limit-exceeded` and the run goes on from source |
| *objects*: code objects per file | 65,536 | |

A limit is checked **before** the memory it protects is used. Exceeding one is `limit-exceeded`, never a crash.

## [bc.determinism] The same source gives the same bytes

For one source text and one compiler version, `dump` produces **identical bytes** on every run and on every host. There is no timestamp, no path, no
hash-order dependence (dictionaries are never iterated for output), no host-dependent width. Pool order is first use, as the compiler already makes it.
Consequences, each a slice 4 test: `dump(load(dump(x))) == dump(x)`; the fixture corpus can be compared byte for byte; two cache writers of one key write the
same bytes, so a lost race loses nothing.

## [bc.profile] Artifacts and the profiles; the type gate; steps

1. **One artifact, any profile.** The loader makes the same code object whatever the profile. A gated built-in is `LOAD_BUILTIN` (resolved by the running
   engine, undefined if the engine does not define it) and never tag 6 (V13).
2. **The type gate runs as it does for source, on the embedded source.** Today `run()` lexes, parses, runs the **type gate** on the parse (`type_gate`) and only then runs
   the program; the gate refuses a program whose annotations do not hold, and it follows the program's imports. A cache hit or a standalone run skips lexing and parsing,
   so without a rule it would skip the gate. **Rule:** the header's flags record whether the source has annotations (bit 0) or imports (bit 1); when either is set, the host
   runs the type gate on the **embedded source** before running the loaded code, exactly as for a compiled run, and a refusal is the same refusal. Imports are found relative
   to the directory of the file being run, as for a source file in that folder. Because the source is embedded, a standalone `.novac` can always do this (the owner's
   answer to Q2); there is no `needs-source` refusal. **What this does and does not give:** the gate checks the embedded *source*, which `[bc.provenance]` says is not a proof about
   the *code*.
3. **Steps and limits are the VM's.** The step counter counts a loop pass and a call, as now; the artifact adds no event and removes none. A limit
   that trips in compiled code trips at the same instruction in loaded code.
4. **Modules.** `IMPORT` is resolved at run time under the grants (not at load time), so an artifact does not embed another artifact. A host that
   caches modules keys each on its own text.

## [bc.provenance] What embedding the source does and does not prove

Embedding the source makes an artifact self-contained: error lines, carets and the type gate work from the file alone. It does **not** make the file trustworthy: a hand-built
artifact can carry a harmless source and different code, and the type gate would pass the source and run the code. This matches `[bc.overview]` (an artifact is not a security
boundary and not an authenticity check) and is why `[bc.verify]` makes hostile code behave like some program under the same grants.

The format is deterministic (`[bc.determinism]`), which gives an exact check at no extra cost: **recompile the embedded source and compare the bytes.** If `dump(compile(source))` equals the
file, the code is the compilation of that source and the gate's verdict on the source is a verdict on the code. This is what `novalang.py --check-artifact FILE` does in the reference host;
it costs a compile, so a run does not do it by default. The cache does something stronger for free: it always has the source it is about to run and compares it with the embedded one.
