# 5. Security properties of the language

NovaLang is meant to run programs written by someone other than the person
running them, in devices, vehicles and homes where a mistake costs more than a
wrong answer. This chapter states what the *language* guarantees. What a *host*
adds on top (sandboxes, permissions, limits on time and memory, process
isolation) is the subject of milestone M11, [`16-sandbox.md`](16-sandbox.md) and [ADR 0003](../decisions/0003-security-stance.md),
which says plainly that capability gating and limits are claimed and isolation
is not.

The properties here are deliberately small, each is tested by the corpus, and
none depends on a host being well behaved.

## [sec.principles] Zero trust: no authority a program was not given

A program in the `core` profile can compute, build values, define functions
and print. It cannot reach anything outside itself: no files, no environment,
no processes, no network, no clock, no other program's memory, and no way to
ask for one by name. Each such ability is a *capability* that belongs to a
profile (`host`, and the embedding profile), is present only if the host
provides it, and is absent otherwise. Absent means the name is undefined:
`undefined name 'open'`, an ordinary, catchable error (`[err.name]`), and not a
partial or pretend version of the function.

A host MUST NOT add a way to name a capability that is not in a profile the
program was run under. The Python bridge is the model: it is off unless the
host turns it on, and what it hands over passes one gate
([`../design/python-bridge-hardening.md`](../design/python-bridge-hardening.md)).

```
try { open("x") } catch e { print(e) }       # undefined name 'open'
try { system("echo hi") } catch e { print(e) }
```

## [sec.no-dynamic-code] No dynamic code

The language has no way to turn text into code at run time: no `eval`, `exec`,
`compile` or `load`, and no way to import by computed name. Programs are fixed
before they run, so what a program can do can be read from its text. (Modules
are named by a string literal at the top of a file, in the `host` profile.)
A host MUST NOT add one.

```
try { eval("1") } catch e { print(e) }       # undefined name 'eval'
```

## [sec.no-reflection] No reflection

A program cannot inspect or change the machinery it runs on: there is no
`globals`, `locals`, `vars`, `dir`, `getattr` or `setattr`, no access to scopes
as values, and no names for the interpreter's own objects. The only things a
function can touch are its parameters, its own locals, the names visible to it
under `[scope.function]`, and the objects it was handed.

```
try { globals() } catch e { print(e) }       # undefined name 'globals'
try { __builtins__ } catch e { print(e) }    # undefined name '__builtins__'
```

## [sec.scope-isolation] A function cannot reach into its caller

Scoping gives every function a boundary (`[scope.function]`, `[scope.assign]`):

- A called function does not see the locals of the function that called it.
  `inner` cannot read `secret` from `outer`, however it is called.
- Assigning to a name never changes a name outside the function: a callee
  cannot rewrite its caller's variables.
- State therefore moves between functions only through the objects they share,
  which the caller chose to pass. A function given `mine` can change `mine`
  and cannot change `yours`.
- The built-in names cannot be redefined (`[scope.reserved]`), so a program
  cannot replace `len` or `print` for the code that follows it.

```
def reset(acct) { acct.balance = 0 }
let mine = {balance: 100}
let yours = {balance: 100}
reset(mine)
print(mine.balance, yours.balance)           # 0 100
```

This is the language-level form of least privilege: what a function can change
is exactly what it was given.

## [sec.error-boundary] Failures of the host are NovaLang errors

A conforming host MUST NOT let a failure of its own machinery reach a program
as anything but a NovaLang error. A Python `OverflowError`, a C stack overflow, a
`ValueError` from a conversion: none of these may end the program with the
host's report, and none may escape `try`/`catch`. The program sees an error with
a label and a message (`[err.model]`) and can catch it.

The tested cases are the places where a host's number or text handling used to
leak: an integer too large for a float (`[port.integers]`), infinity or NaN given
to a function that needs a whole number (`[port.floats]`), a digit that is not
one of `0`-`9` (`[lex.numbers]`), and numbers with too many digits. A new such
leak is a bug in the host, whatever it is called, and its fix comes with a case.

```
let inf = num("1" + "0" * 400 + ".0")
try { print(floor(inf)) } catch e { print("caught:", e) }
                                             # caught: TypeError: floor() needs a finite number, but got inf
```

## [sec.limits] What is bounded, and what is not yet

The language promises that a few things are bounded, so that a mistake or a
hostile program is stopped with an error rather than exhausting the host:
nesting of calls, the length of a list or string built by repetition, and the
size of a list built by `range` (`[port.limits]`). It does **not** yet promise a
limit on the number of steps a program takes, on the total memory it uses, on
the size of integers it builds, or on the time it runs. A `while true { }` runs
forever. Those limits are a host's to impose (ADR 0003 names them for M11, and [`16-sandbox.md`](16-sandbox.md) `[sbx.limits]` specifies them for the `restricted` profile), and a
host that sets one MUST report it as an error in the way `[err.model]`
describes. Until they exist, running code you did not write needs a process or
container around it as well.
