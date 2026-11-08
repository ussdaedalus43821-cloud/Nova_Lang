# 3. Names and scopes

This chapter defines how names are declared, found and changed, for the
statements `let`, assignment, `if`, `while`, `for`, `def` and `return`. A *scope*
is a table of names. There are three kinds:

- the **global scope**, one per program;
- a **function scope**, made by each call of a user function; and
- a **block scope**, made by the body of an `if`, `else`, `while`, `for`,
  `try`, `catch` or `finally`, afresh each time the body runs.

Function and global scopes are *barriers* (see `[scope.assign]`). Block scopes are not.

## [scope.global] The global scope

Top-level statements run in the global scope. A global is visible everywhere in
the program, including inside functions, which read it when they run, not when
they are defined. Reading a name that is not defined anywhere in reach is an
error: `undefined name 'missing'`. A program starts with the built-in functions
and a few predefined names, `PI` and `E` (numbers), `json` (a dictionary of
functions) and, where the host provides the embedding profile, `python`. They are
ordinary globals, not reserved: `let PI = 3` shadows one in its own scope.

A function that needs to change a global cannot assign to it (see
`[scope.assign]`); it can change a list or dictionary the global refers to
(`[scope.references]`):

```
let state = {n: 0}
def bump() { state.n = state.n + 1 }
bump()
bump()
print(state.n)          # 2
```

## [scope.let] Declaring with `let`

`let name = expression` evaluates the expression, then creates `name` in the
**current** scope and gives it the value. The expression does not see the new
name, so `let x = x` is `undefined name 'x'` unless an outer `x` exists.
Declaring a name again in the same scope replaces its value. Declaring a name
that exists in an outer scope hides it for the rest of the current scope, and it
is visible again afterwards.

```
let x = 1
if true { let x = 2
print(x) }              # 2
print(x)                # 1
```

## [scope.assign] Assignment

`name = expression` (without `let`) changes the nearest existing `name`:

1. It looks outward through block scopes, as far as the nearest barrier (the
   enclosing function scope, or the global scope), and changes the first `name`
   it finds.
2. If there is none in reach, it **creates** `name` in the current scope. At the
   top level that is the global scope; inside a block it is the block's scope,
   so the name is gone when the block ends; inside a function it is the
   function's scope.

So a function never changes a name that lives outside it. `x = 2` inside a
function makes a local `x`, and the global `x` is untouched. A block, which is
not a barrier, does change an outer name in the same function.

```
let x = 1
def f() { x = 2
return x }
print(f(), x)           # 2 1

if true { y = 5 }
print(y)                # undefined name 'y'
```

`name = expression` where the right side reads `name` first (`x = x + 1`) is an
error if `name` does not exist: `undefined name 'x'`.

The left side of `=` is a name, `a[i]` or `a.k`; anything else is a syntax error,
`the left side of '=' must be a variable, a list item or a field`. `a[i] = v`
replaces an item (the index follows `[expr.index]`; an out-of-range index is an
error and the list is not extended) and `d.k = v` or `d["k"] = v` sets or adds a
key. A string cannot be assigned into: `strings cannot be changed in place -
build a new one instead`.

## [scope.blocks] Blocks

The body of `if`, `else`, `while`, `for`, `try`, `catch` and `finally` is a block
scope. Names created in it, by `let` or by an assignment that finds no existing
name, are gone when it ends. A loop body gets a new scope for every
iteration, so a `let` inside it starts fresh each time. A function defined in a
block is local to the block.

## [scope.loop-var] Loop variables

`for i = a to b`, `for i = a downto b` and `for x in c` create their variable in
a scope of their own, around the body: it hides an outer name of the same
name during the loop and is gone after it. `to` and `downto` include **both**
ends (`for i = 0 to 3` runs for 0, 1, 2 and 3), `step n` sets the increment
(`n` MUST be greater than zero, `a 'for' step must be greater than zero (use
'downto' to count down)`), and a range that is already past its end runs zero
times. The built-in `range(n)` is different: it stops before `n`.

```
for i = 0 to 3 { }                        # i is 0, 1, 2, 3
for i = 3 downto 1 { }                    # 3, 2, 1
print(range(3))                           # [0, 1, 2]
```

## [scope.function] Functions

`def name(p1, p2) { body }` creates a function value and binds `name`, in the
current scope, as `let` would. Each call creates a function scope in which the
parameters are defined and the body runs. A name that the body creates with
`let` or by assignment lives in that scope and is gone when the call ends.
`return expression` leaves the function from any depth of blocks with that
value; `return` alone, or reaching the end, returns `nothing`.

Reading a name inside a function looks through the function's scope, then its
enclosing scopes (`[scope.closure]`), then the global scope, when the call
runs (`[scope.order]`).

A name `let`-declared in a function after the function has read it keeps
meaning the outer name for the earlier read:

```
let x = 5
def f() { print(x)
let x = 2
print(x) }
f()                                       # 5, then 2
```

## [scope.order] When a name must exist

Names are looked up when a statement runs, not when it is read. At the top
level, a name MUST be defined before the statement that reads it runs:
`print(g())` before `def g()` is `undefined name 'g'`. Inside a function the
lookup happens when the function is called, so a function may use a global
that is defined after the function, and may call a function defined after it,
as long as both exist by the time it is called.

```
def f() { return later }
let later = 3
print(f())                                # 3
```

## [scope.param] Parameters

Parameters are locals of the call, set from the arguments in order. Assigning to
one changes only that local. Passing a list or dictionary passes the same object
(`[scope.references]`); passing a number, string or boolean passes a value.
Giving two parameters the same name is a syntax error: `parameter 'a' is listed
twice`.

## [scope.closure] Functions defined inside functions

A function defined in another function's body can read that function's locals
for as long as it exists, even after the outer call has returned. It cannot
assign to them (assignment makes the inner function's own local, by
`[scope.assign]`); state that must change is kept in a list or dictionary.

```
def counter() {
    let c = {n: 0}
    def inc() { c.n = c.n + 1
    return c.n }
    return inc
}
let a = counter()
let b = counter()
print(a(), a(), a(), b())               # 1 2 3 1
```

Each call of `counter` makes a separate `c`.

## [scope.references] Shared and copied values

Assigning, passing or returning a list, a dictionary or a function gives another
name for the **same** object: `let b = a` then `append(b, 2)` changes what `a`
shows. Numbers, strings and booleans cannot be changed, so a second name for one
is independent. `a + b` for lists and dictionaries, `a * n` and a slice
`a[:]` make new objects.

## [scope.reserved] Built-in names

The names of the built-in functions (`print`, `len`, `append`, `log`, ...) are
reserved. They cannot be declared with `let`, assigned, used as a function name
or used as a parameter name: `'print' is a built-in function and cannot be used
as a variable name` (`a function name`, `a parameter name`).

## [scope.toplevel] `return`, `break` and `continue`

`break` and `continue` MUST be inside a `while` or `for` loop in the same
function: otherwise `'break' is not inside a loop` (`'continue' ...`), and
`'break' is not inside a loop in f()` when it is inside a function `f` but not in
a loop in `f`. `return` MUST be inside a function: at the top level, even inside
a loop, it is `'return' only makes sense inside a function`.

`break` leaves the nearest enclosing loop; `continue` goes on to its next
iteration.
