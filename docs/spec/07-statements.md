# 7. Statements

The statements that decide what runs: `if`, `while`, both `for` forms, `break` and
`continue`, `def`, and `delete`. How names are created and found inside them is
`03-scoping.md`; what a condition may be is `[expr.logic]`; `try`, `catch`,
`finally` and `throw` are `04-errors.md`; `import` and `export` are
`08-modules.md`. This chapter says what each statement does and in what order.

A statement has no value. A block is `{` statements `}`, and a statement ends at
a line end (`[lex.newlines]`).

## [stmt.if] `if`, `else if`, `else`

```
if condition { block }
if condition { block } else { block }
if condition { block } else if condition { block } else { block }
```

The conditions are evaluated from the first, each only if every one before it was
`false`, and the block after the first `true` condition runs; nothing else runs.
With no `true` condition and an `else`, the `else` block runs. A condition MUST be
a boolean (`[expr.logic]`): `a 'if' condition must be true or false, but this is
a number`. Each block is a block scope (`[scope.blocks]`).

`else if` is the only chained form. A nested `if` inside an `else` block is a
different statement and works too. The `else` MAY start the line after the `}`
(`[expr.newlines]`).

```
let a = 1
def probe() { print("probe")
return true }
if a == 1 { print("one") } else if probe() { print("never") }     # one
```

## [stmt.while] `while`

```
while condition { block }
while condition { block } else { block }
```

The condition is evaluated before every iteration, the first included, and the
body runs while it is `true`. It MUST be a boolean each time it is evaluated
(`a 'while' condition must be true or false, but this is a string`). A loop whose
condition is false at the start runs its body zero times. The body is a new block
scope for every iteration (`[scope.blocks]`). For the `else`, see `[stmt.loop-else]`.

## [stmt.for-range] `for` over a range

```
for name = start to end { block }
for name = start to end step n { block }
for name = start downto end { block }
for name = start downto end step n { block }
```

`start`, `end` and `step` are evaluated once, in that order, before the first
iteration, and are not evaluated again; `step` is 1 when omitted. Each MUST be a
finite number (`the start of a 'for' range must be a number, but this is a
string`, and `[port.floats]` for infinity and NaN), and `step` MUST be greater
than zero (`a 'for' step must be greater than zero (use 'downto' to count
down)`).

The loop variable takes the values `start`, `start + step`, `start + 2 * step`,
... up to and **including** `end` when it is reached exactly, and for `downto`
`start`, `start - step`, ... down to `end`. The number of iterations is
decided up front, as the whole number of steps that fit between `start` and `end`
plus one, or none if `start` is already past `end`: the loop does not compare the
variable with `end` as it goes.

When that count is more than a float can hold (the span is an integer too large to be a float, or a float span
over a step so small that the count is infinite) the loop does not start: it is the error of `[err.arithmetic]`,
`a number is too large for this operation - an integer beyond the range of a float cannot be divided or mixed
with a float`, and never a failure of the host.

Each value is `start` plus **k times step**, worked out afresh, not the previous
value plus `step`. With floats this is visible and exact:

```
for x = 0 to 1 step 0.1 { print(x) }
# 0  0.1  0.2  0.30000000000000004  0.4  0.5  0.6000000000000001
# 0.7000000000000001  0.8  0.9  1
```

If `start`, `end` and `step` are all integers the variable is an integer;
otherwise it is a number that prints as `[val.display]` says (`0` and not `0.0`).

The variable lives in its own scope around the body (`[scope.loop-var]`). The body
MAY assign to it, but that changes only the rest of that iteration: the next
iteration takes the next computed value. Functions defined in the body share the
one variable, so they all see its value when they run, not the value of the
iteration that defined them.

## [stmt.for-in] `for` over a value

```
for item in collection { block }
for key, value in collection { block }
```

`collection` MUST be a list, a string or a dictionary (`'for ... in' needs a list,
a string or a dictionary, but this is a number`). One name takes the **items** of
a list, the **characters** (code points) of a string, and the **keys** of a
dictionary, in the order of `[port.order]`. Two names take the **index and
item** of a list, the **index and character** of a string, and the **key and
value** of a dictionary. The two names MUST differ (`both loop variables are
called 'x'`).

The loop works on a snapshot taken before the first iteration. Adding, removing
or replacing items of the list or entries of the dictionary during the loop does
not change which items, keys or values it visits; a value that is itself a list or
dictionary is the same object, so changes inside it are seen. `delete` of a key
the loop has still to visit does not skip it.

```
let d = {a: 1, b: 2, c: 3}
for k in d { print(k)
delete d.b }                                      # a  b  c  (b is still visited)
```

Scoping of the variables is `[scope.loop-var]`. A collection with nothing in it
runs the body zero times.

## [stmt.loop-else] `else` on a loop

A `while` or `for` loop MAY be followed by `else { block }`. The `else` block runs
once, after the loop, if the loop **ended because it ran out**: the `while`
condition became `false`, the range was used up, or the collection was exhausted.
That includes a loop whose body never ran. It does not run if the loop was left by
`break`. `continue` does not matter, and `return` or an error leave the whole loop
and everything after it. The `else` block is a block scope of the scope that
holds the loop; the loop variable is not visible in it.

```
for i = 1 to 5 { if i == 3 { break } } else { print("not printed") }
for x in [] { } else { print("printed") }
```

An `else` is attached to the loop statement directly before it and MAY start the
line after the `}`.

## [stmt.break-continue] `break` and `continue`

`break` leaves the nearest enclosing loop, and `continue` ends the current
iteration and goes on with the next one (for a `while`, back to evaluating the
condition; for a `for`, to the next value). In nested loops they apply to the
innermost; an outer loop is unaffected. Where they may appear is
`[scope.toplevel]`.

They compose with `try`: leaving a loop body by `break` or `continue` from inside
a `try` or `catch` block runs the `finally` block first (`[err.finally]`), and the
`continue` in a `catch` block does what it says.

```
let i = 0
while i < 3 { try { i = i + 1
if i == 2 { continue }
print("i", i) } finally { print("fin", i) } }
# i 1  fin 1  fin 2  i 3  fin 3
```

## [stmt.def] Function definitions

`def name(parameters) { body }` is a statement. When it runs it creates a function
value and binds `name` in the current scope (`[scope.function]`); until the
statement has run there is no such name, so a function cannot be called before the
`def` that follows it in the program (`undefined name 'h'`), although a function
body can call one defined later, because the name is only looked up when the call
runs (`[scope.order]`). A `def` in a block is local to the block, and one in a
function is local to that call. Running a second `def` with the same name in the
same scope replaces the first, as `let` would, and a `def` and a `let` of the same
name replace each other in the order they run.

A function called with the wrong number of arguments is `f() expects 2
argument(s) but got 1` (`[err.call]`). Arguments are passed as values: assigning
to a parameter changes the function's own copy, while a list or dictionary
argument is the same object as the caller's (`[scope.references]`). A function may
call itself by name, to the depth limit of `[port.limits]`. Printing a function
gives `<function f(a, b)>` (`[val.display]`), and `f == f` is true
(`[val.equality]`).

## [stmt.delete] `delete`

```
delete dictionary.key
delete dictionary["key"]
```

removes the entry. The target is evaluated first, then the key. The target MUST be
a dictionary: `delete works on dictionary entries, but this is a string`, and for a
list `delete works on dictionary entries, but this is a list - use pop() to remove
a list item`. The key MUST be a string (`a dictionary key must be a string, but
this is a number`). Deleting a key that is not there is not an error, and
deleting twice is fine. The statement has no value, and the other keys keep their
order (`[port.order]`).

`delete("file")`, with a path in parentheses, deletes a file. That needs a file
system and belongs to the `host` profile; its cases are not part of this chapter.
