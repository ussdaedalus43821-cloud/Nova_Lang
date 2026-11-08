# 12. The policy dialect: source, syntax and statements

## [pol.overview] What the policy dialect is

The **policy dialect** is the language the game's control scripts are written in
(`.nova` files such as `reactor_rules.nova`). It looks like NovaLang and is not
NovaLang: it has its own words (`func`, `null`, `set`), its own rules for what
counts as true, what `+` does and what an error says, and its own engine
declarations (`rule`, `fault`, ...). The decision to specify it as a language of
its own, and not as switches inside NovaLang, is
[ADR 0004](../decisions/0004-policy-dialect-after-measurement.md); the measured
differences are in [`../design/m10-dialect-inventory.md`](../design/m10-dialect-inventory.md).

The dialect has the profile `policy` (`README.md`). Its sections have ids that
start with `pol.`, and its cases run on the policy engine
(`dialects/policy/`) and on any host that declares the profile, never on
NovaLang's engines. It shares with NovaLang the corpus format, the runner and
the security stance ([ADR 0003](../decisions/0003-security-stance.md)): a program
has no ambient authority, and everything it can do to the world it does through
functions the host chose to give it.

This chapter covers how a source file is read (`pol.source` to `pol.operators`),
the syntax and what each statement does (`pol.grammar` to `pol.import`), and the
two guards on every run (`pol.limits`, `pol.errors`). Values, operators and the
built-in functions are `13-policy-values.md`; the rule engine is
`14-policy-engine.md`. Those two chapters are written in the next slices of M10.

A program is a sequence of statements run from the first to the last in a global
scope. Its observable effects are what `print` writes (one line per call, kept in
order), the calls it makes to host functions, and, if it fails, one error.

```
print("hello", 1 + 2)
let total = 0
let i = 1
while i <= 4 { total = total + i  i = i + 1 }
print("total", total)
```

prints `hello 3` and `total 10`.

**How cases are written.** A policy case has the same fields as any case
(`tests/conformance/README.md`) with these meanings: `output` is the lines
printed; `error` is the failure text exactly as `[pol.errors]` defines it (there
is no label and `error_line` is not used); `exit` is 0 for a program that ran to
the end, 1 for one that failed; `files` are the modules `import` can find, by
the name the program writes; `host_functions` names the host functions the host
binds for the case, each of which records its call in `host_calls` as
`name(arguments as print shows them)` and returns `null`.

## [pol.source] Source text

A source file is a sequence of characters. Outside a string literal and a
comment, a character that no token begins with is an error, found before any
statement runs: `unexpected character 'é'` (names are ASCII, `[pol.names]`), and
likewise for `$`, `@`, `'`, `&`, and a `!` that is not part of `!=`. An empty
source, or one that is only whitespace and comments, is a program that does
nothing.

## [pol.whitespace] Whitespace and statement boundaries

Space, tab, carriage return and line feed separate tokens and mean nothing else.
**A line end does not end a statement**: the grammar (`[pol.grammar]`) alone
decides where one statement stops and the next begins, so `print(1) print(2)` is
two statements and so are the same two calls on two lines. A call may be split
across lines anywhere between tokens.

```
let a = 1  a = a + 1  let b = a * 2  print(a, b)      # 2 4
```

No separator is needed between a complete statement and the next one (and there
is none to write); two expressions with nothing between them inside one call,
`print(1 2)`, are an error (`expected ')', got '2'`). The line number in a
message is the line of the token being read (`[pol.errors]`).

## [pol.comments] Comments

`#` and `//` each start a comment that runs to the end of the line. There is no
block comment. Inside a string literal neither starts a comment. Since `//` is
always a comment here, **the dialect has no `//` operator**: `print(8 / 2 // 2)`
loses `// 2)` to the comment and fails with `expected ')', got 'eof'`.

## [pol.names] Names

A name starts with an ASCII letter or `_` and continues with ASCII letters,
digits and `_`. Names are case-sensitive and any length. A digit cannot start a
name (`let 1a = 3` reads the number `1` where a name is expected, `expected
'ident', got '1'`); a non-ASCII letter is `unexpected character`.

## [pol.keywords] Keywords

These words are reserved. They cannot be the name of a variable, a function or a
parameter:

```
and or not true false null
let set func return if else while break continue import export as
reactor version params effects signals rule fault
when then priority once edge weight duration label persistent
```

Using one where a name is expected is `expected 'ident', got 'if'` (the word is
shown). That includes the declaration words, so `version`, `label` and
`duration` cannot be variables. **A keyword is allowed as a dictionary key and
after a dot** (`{if: 1}`, `d.return`). The other words other languages reserve
(`def`, `for`, `to`, `try`, `in`) are ordinary names here. `true`, `false` and
`null` are literals.

## [pol.numbers] Numbers

A number literal is decimal digits, optionally followed by a point and more
digits, optionally followed by an exponent: `42`, `3.14`, `.5`, `5.`, `007`
(which is 7), `1e3`, `1E3`, `1e+3`, `2e-2`. The exponent is `e` or `E`, an
optional sign and at least one digit; without a digit the `e` is not part of the
number (`2e` is the number `2` and then the name `e`, an error where an operator
was expected). A literal may start with a point if a digit follows (`.5`) and may end with one
(`5.`); `1.2.3` is the number `1.2` followed by the number `.3`.

Every number is a 64-bit floating-point number; there is no integer type, no
separator (`1_000` is `1` then the name `_000`), no hexadecimal (`0x10` is `0`
then the name `x10`), and no sign in the literal (`-5` is the operator `-` and
`5`). A literal beyond the range of a float is infinity (`1e400` is `inf`). How
numbers print is `[pol.num-display]`.

## [pol.strings] Strings

A string literal is written in double quotes. There are no single-quoted
strings (`'` is `unexpected character`). It may contain any character, **a raw
line end included**. A backslash starts an escape: `\n` (line feed), `\t` (tab),
`\r` (carriage return), `\"` and `\\`. **Any other character after a backslash
stands for itself**: `"\q"` is `q`, `"\x41"` is `x41`, `"\0"` is `0`. There is no
interpolation: `"x = {x}"` is those characters.

A string that is not closed before the end of the source is `unterminated string
literal`, reported with the line the source ends on (a backslash as the last
character of the source counts as unterminated).

```
print("a\tb", "q\"q", "back\\slash")
print("line1\nline2")
```

## [pol.operators] Operators and punctuation

The tokens are `== != <= >= + - * / % < > =` and `( ) { } [ ] , . :`, and the
words `and or not`. The longest match wins (`<=` and not `<` then `=`). There is no
`**`, `&&`, `||`, `<>`, `!` on its own, `+=` or other compound assignment:
`2 ** 3` is `unexpected '*' in expression`, `&&` is `unexpected character '&'`,
and `a = 2` inside an expression is `expected ')', got '='` because `=` is
assignment, a statement, never an expression.

## [pol.grammar] Program and statements

```
program   := statement*
statement := 'let' NAME '=' expr
           | 'set' target '=' expr
           | 'func' NAME '(' [NAME {',' NAME}] ')' block
           | 'import' STRING ['as' NAME]
           | 'export' ('let' NAME '=' expr | 'func' NAME '(' ... ')' block)
           | 'if' expr block ['else' ('if' ... | block)]
           | 'while' expr block
           | 'return' [expr]
           | 'break' | 'continue'
           | block
           | expr ['=' expr]
block     := '{' statement* '}'
```

(The engine declarations `reactor`, `params`, `signals`, `effects`, `rule` and
`fault` also begin a statement; they are `14-policy-engine.md`.)

An expression statement is an expression; if `=` follows, the expression is the
target of an assignment (`[pol.assign]`). **A `{` where a statement begins is
always a block**, never a dictionary, so a dictionary expression used as a
statement must be in parentheses: `{a: 1}` is `unexpected ':' in expression`,
`({a: 1})` is fine, and `{}` is an empty block.

A syntax error is reported with `expected 'X', got 'Y'` (a token was needed and
another was found; `Y` is `eof` at the end of the source, a string literal is shown
without quotes and a number as `[pol.num-display]` prints it), `unexpected 'X' in
expression` (a token that cannot start an expression), `expected a name, got 'X'`
(a dictionary key or a name after a dot), or `unterminated block` (the source
ends inside `{ }`). All syntax errors are found before any statement runs, so a
program with one prints nothing, and lexical errors (`[pol.source]`,
`[pol.strings]`) are found before syntax errors:

```
print("never")
let =                       # line 2: expected 'ident', got '='  (nothing is printed)
```

## [pol.precedence] Expressions: precedence and associativity

From loosest to tightest:

| Level | Operators | Associativity |
| --- | --- | --- |
| 1 | `or` | left |
| 2 | `and` | left |
| 3 | `not` | prefix |
| 4 | `<` `>` `<=` `>=` `==` `!=` | left (all six at one level) |
| 5 | `+` `-` | left |
| 6 | `*` `/` `%` | left |
| 7 | prefix `-` `+` | prefix |
| 8 | call `f(...)`, index `a[...]`, member `a.name` | left |

So `2 + 3 * 4` is 14, `2 - 3 - 4` is -5, `not 1 < 2` is `not (1 < 2)`, and
`-l[0]` is `-(l[0])`. **Comparisons chain to the left and are not special**:
`1 < 2 < 3` is `(1 < 2) < 3`, with the value rules of `13-policy-values.md`. Unary
`+` does nothing. A parenthesised expression may be called, indexed or
accessed: `(func(x) { return x + 1 })(41)` is 42. Arguments and operands are
evaluated left to right.

## [pol.literals] List and dictionary literals

`[a, b, c]` is a list and `{key: value, ...}` a dictionary. A trailing comma is
allowed in list and dictionary literals and in call arguments (`[1, 2,]`,
`{a: 1,}`, `f(1, 2,)`); `[,]` and `{,}` are errors. A dictionary key is written as
a bare name (**any word, keywords included**), as a string literal, or as an
expression in brackets: `{a: 1}`, `{"b c": 2}`, `{[k + "1"]: 3}`, `{if: 4}`. A
number or other token as a bare key is `expected a name, got '1'`. A computed key
that is not a string becomes its text (`[1 + 1]` is the key `2`). A key written twice
keeps its first position and takes the later value (`{a: 1, b: 2, a: 3}` is
`{a: 3, b: 2}`); keys keep the order in which they were first added.

## [pol.let] `let`

`let name = expr` evaluates the expression, then creates the binding in the
current scope with that value. A second `let` of the same name in the same scope
replaces the first. The expression is evaluated before the name is bound, so it
sees the outer binding of that name, if any, and `let a = a` with none is
`unknown identifier 'a'`. A function value that has no name yet, because it was
written `func(...) {...}`, takes the name of the variable it is first bound to by
`let`, which is only visible when it is printed (`<func f>`, `[pol.func]`).

## [pol.assign] Assignment

`target = expr` and `set target = expr` are the same statement. The target is a
name, `a[index]` or `a.name`. **The value is evaluated first**, then the object,
then the index (so for `o()[i()] = v()` the order is `v`, `o`, `i`).

- A **name** is rebound in the nearest scope that has it. **If no scope has it,
  the name is created in the global scope**, wherever the assignment is: inside a
  block, a function or a nested function. (This is how a policy sets a variable
  nothing declared.)
- A **list element** takes an index that is a number; a negative index counts
  from the end; one outside the list is `list index 1 out of range (size 1)`.
- A **dictionary entry** is created or replaced; a key that is not a string is
  turned into text (`d[3] = 4` writes the key `3`).
- Anything else as the object is `cannot assign into a string` (or number, ...),
  and anything else as the target is `cannot assign to a 'num'` (the node kind:
  `num`, `call`, `binary`, ...), which is found when the statement runs, not before.

Lists and dictionaries are shared, not copied: after `b = a`, `b[0] = 2` is seen
through `a`.

## [pol.scope] Scopes

A scope holds bindings and has an enclosing scope; the global scope has none.
Each of these makes a new scope: a block, the body of an `if` branch, **every
iteration of a `while` body**, and every function call (holding the
parameters). A name is looked up from the innermost scope outwards. A binding made
by `let` in a block is gone after it. A function remembers the scope it was
written in (a closure) and sees later changes to the bindings there, not a copy:

```
func counter() { let n = 0  return func() { n = n + 1 return n } }
let a = counter()  let b = counter()  a() a()  print(a(), b())      # 3 1
```

A name is looked up when it is used, not when a function is written, so a
function may use a global that is defined after it (`func f() { return later }`
then `let later = 7`). A function's parameters shadow outer names. Each
iteration of a loop has its own scope, so a function made in the body keeps that
iteration's variables.

## [pol.if] `if`

`if cond { ... }` runs the block when the condition is true (what counts as true is
`13-policy-values.md`). `else if` and `else` follow; the conditions are
evaluated in order and only until the first that is true; the others, and their
blocks, are not evaluated. With nothing true and no `else`, nothing runs. `else`
may start on the next line. The blocks need braces (`if true print(1)` is
`expected '{', got 'print'`), and `else` must be followed by `if` or a block.

## [pol.while] `while`, `break` and `continue`

`while cond { ... }` evaluates the condition before every iteration, including
the first, and runs the body while it is true. `break` leaves the nearest
enclosing loop; `continue` goes on to the next evaluation of the condition. In
nested loops they apply to the innermost. They work from inside nested blocks and
`if` statements of the body. There is no `for` and no loop `else`. The body needs
braces.

## [pol.func] Functions

`func name(a, b) { body }` binds `name` in the current scope to a function value
when the statement runs; it is the same as `let name = func(a, b) { body }`, so
the function can call itself and, as with any `let`, **cannot be called before the
statement has run** (`unknown function 'g'`), although a body may call a function
that is defined later because names are looked up at the call. `func(a, b) { ...
}` as an expression is an anonymous function; it may be called at once or passed
as a value. The name is required in a statement and absent in an expression.

A function has exactly the parameters it lists; a call with a different number of
arguments is `f() takes 2 argument(s), got 1` (the function's name, or
`anonymous`). A parameter listed twice takes the later argument. Parameters
are local; lists and dictionaries are passed shared (`[pol.assign]`).

`return expr` ends the call with that value. `return` followed directly by `}` or
the end of the source returns `null`; **anything else after `return` is its
expression, wherever it is on the page**, so `return` then `print(2)` on the next
line returns `print(2)`'s result. A function that ends without `return` returns
`null`. A function prints as `<func name>`, or `<func anonymous>`.

## [pol.calls] Calling

A call `f(args)` where `f` is a bare name looks the name up in this order:

1. if the name is bound to a **function**, call it;
2. otherwise `held` is the timer of `14-policy-engine.md`;
3. otherwise, if it is a **built-in function** (`13-policy-values.md`), call it;
4. otherwise, if the host registered a **host function** of that name, call it;
5. otherwise, if the name is bound to anything else, `cannot call a number` (or
   its kind); with no binding, `unknown function 'f'`.

A binding that is not a function is therefore **skipped, not an error**, in steps
1 to 4: a variable `scram` and a host function `scram()` coexist, and `let len = 5`
does not stop `len([1, 2])` working. A function bound by the program shadows a
built-in or host function of the same name, and a built-in wins over a host
function. Built-in functions are not values: `let g = len` is `unknown identifier
'len'`.

When the callee is anything else (a call result, an index, a parenthesised
expression), it is evaluated and must be a function, else `cannot call a list`.
All the arguments are evaluated, left to right, before the call; if one fails,
the function is not called. A host function receives the argument values and its
result is its return value (`null` if it has none); how many arguments a host
function accepts is its own business.

## [pol.toplevel] `return`, `break` and `continue` outside their place

At the top of a program (or of a module), or in a block not inside a function or
loop, `return`, `break` and `continue` are not errors: they **end the program
quietly**, so statements after them do not run. Inside a function, a `break` or
`continue` that is not in a loop of that function ends the call, returning `null`.

## [pol.import] `import` and `export`

`import "path" as name` runs the module named `path` once and binds `name` to a
dictionary of its exports. `import "path"` with no `as` instead binds **each
export by its own name** in the current scope, later ones replacing earlier ones
(and replacing a variable of that name). The path is a string given to the host,
which finds the source or does not (`cannot read module 'nope.nova'`). The
binding is made in the scope where the statement runs, so an import in a block or
function is local to it.

A module is a program with its **own global scope**: it sees the built-in and
host functions and nothing of the importer. It runs the first time any importer
asks, and the same exports are given to every later `import` of it, without
running it again (its `print`s happen once); those exports are one shared
dictionary, so `m.NAME = "z"` is seen by all. A module that imports a module
that is being loaded, itself included, is `circular import of 'x.nova'`.

`export let ...` and `export func ...` declare as usual and mark the name. After
the module has run, the exports are the marked names **with their final values**,
in the order of the statements, **leaving out any whose declaration did not run**
(it was after a top-level `return`, say). A name that is not marked is private
(`dict has no key 'secret'` through an alias, `unknown identifier 'secret'` after
a bare import). `export` must be followed by `let` or `func`. In the main
program `export` declares as usual and the marks are not used. A module with no exports
gives `{}`.

Errors while loading: a **syntax error in a module** is reported at the importing
line as `line 2: bad.nova: line 1: expected 'ident', got '='` (the importing line,
the module's name, then the module's own message). A **runtime error in a module**
stops the program and is reported as the module's own error, with the line inside
the module and without its name (`line 2: unknown function 'nope'` for line 2 of
`err.nova`); output the module printed before it stays.

## [pol.limits] Limits

Two guards bound a run so a policy cannot hang or overflow its host.

- **Call depth.** At most 128 user-function calls may be active at once; the 129th
  fails with `call depth limit (128) exceeded -- infinite recursion?`. Built-in and
  host functions do not count.
- **Steps.** A run may take at most 500,000 steps; the next fails with `step budget
  exhausted (500000) -- runaway loop?`. A step is counted for every statement
  executed, for every pass of a `while` (before its condition is evaluated, in
  addition to the condition's own steps), and for every expression evaluated
  except the literals (numbers, strings, `true`, `false`, `null`): a name, an
  operator, a call, an index or member access, a list, a dictionary or a function
  expression is one step each, and its operands add theirs. The program
  `let i = 0 while i < N { i = i + 1 } print(i)` takes exactly `6N + 8` steps, so
  `N = 83332` completes and `83333` does not.

The counters start from zero for each run of the program and for each call a host
makes into it. A failure by either guard is an ordinary error (`[pol.errors]`).

## [pol.errors] Errors

An error stops the program at once. What it had printed stays, nothing after it
runs, and the run's exit status is 1; the host is told the error as a single line
of text. **The first error wins**: nothing after it replaces it.

The text of an error is `line N: message`, where `N` is the 1-based line of the
construct at fault, and the message is one of those in this chapter and
`13-policy-values.md`. There is no label such as `NovaError`. A lexical or
syntax error has the line of the token being read when it was found (for an
unterminated string, the last line of the source). A runtime error has the line of
the name that is unknown, or of the opening bracket of the call, index or member
access that failed, or of the statement for an assignment; inside a function that
is the line inside the function:

```
func f() {
  print(1)
  nope()            # line 3: unknown function 'nope'
}
f()
```

The errors that can come from a module have the forms in `[pol.import]`. A few
errors have no line (a host's own failure); they are the bare message.
