# 8. Modules

A program can be split into files. A *module* is a NovaLang file that another
program runs with `import` and reads the results of. Modules need a file system
or something that stands in for one, so every case in this chapter is in the
`modules` profile (`README.md`).

Packages (`import "name"` with a bare name and no `.nova`, found in
`.nova_modules` through `nova.json` and `nova.lock`) are specified in
`18-packages.md`.

## [mod.import] `import`

```
import "path/to/util.nova"                    # binds  util
import "path/to/util.nova" as u               # binds  u
import "path/to/util.nova" with double, LIMIT # binds  double  and  LIMIT
```

The path is a string literal (`import p` with a variable is a syntax error:
`expected a quoted module path after 'import'`, which keeps what a program can
load visible in its text, `[sec.no-dynamic-code]`). `import` is a statement: it
runs when control reaches it, loads the module (`[mod.cache]`) and binds in the
**current scope**, as `let` would (`[scope.let]`), so an import inside a block
or function is local to it.

Plain `import` binds the module's **exports** as a dictionary under the file's
name without its folders and extension: `"sub/util.nova"` binds `util`. That name
MUST be a valid name (`[lex.identifiers]`) and not a built-in's: `"my-mod.nova"`
is `"my-mod.nova" does not make a valid module name - import it with 'as' and
choose one`, and `"print.nova"` is `'print' is a built-in function and cannot be
used as a module name`. `as name` chooses the name instead and needs no valid
file name; `name` may not be a built-in's (`[scope.reserved]`).

`with a, b` binds each named export directly and no module name. A name MUST be
exported by the module: `module "util.nova" has no exported 'triple' - it exports
double, LIMIT` (`it exports nothing` when there are none), with the path as it
was written in the `import`. Naming one twice is a syntax error (`'a' is imported
twice`), and so is a built-in's name (`[scope.reserved]`). `as` and `with` do not
combine.

## [mod.export] `export`

```
export def double(x) { return x * 2 }
export let LIMIT = 10
```

`export` is written before a `def` or `let` (`'export' must be followed by 'def'
or 'let'`). The declaration happens as usual and, when the statement runs,
the name and its **value at that moment** are added to the module's exports. A
later assignment to the variable in the module does not change what was
exported, and exporting the same name again replaces the earlier value. A
declaration without `export` is private to the module. The exports are one
dictionary, in the order they were exported, shared by everyone who imports the
module: assigning to a field of `util` changes it for all of them
(`[scope.references]`). A program's own exports, as the program a host starts,
are not used.

## [mod.resolution] Finding the file

A path with a `/` or ending in `.nova` names a file. It is looked for relative
to the folder of the **file containing the `import`**, so a module imports its
neighbours by their own relative path whatever the program's folder is. `.` and
`..` work. No extension is added: `import "util"` is a package name and not the
file `util.nova`. If the file is not there a host MAY look further, in its
working directory for instance; this chapter's cases only rely on the importing
file's folder. When nothing is found the error is
`ImportError: cannot find module "<path>" - looked in:` followed by the places
tried, one to a line, which are the host's.

## [mod.cache] A module runs once

A module's file is run the first time it is imported and its exports are kept,
keyed by the file itself: `"util.nova"`, `"./util.nova"` and `"../sub/util.nova"`
reaching the same file are one module, whoever imports it and under whatever name.
Every later import binds the **same** exports dictionary without running the file
again, so what the module printed is printed once and its state is shared. A
module that fails to load is not kept; importing it again runs it again.

## [mod.scope] A module's own scope

A module runs in a fresh global scope of its own, as a program would, with the
built-ins and the predefined names a program starts with (`PI`, `E`, `json`, and
`python` where the host provides it) and nothing else. It cannot see the importer's variables or
functions, not even ones the importer defined first, and the importer sees only
the exports. A function a module exports keeps working in the module's scope
whatever the importer has: it sees the module's private names. A top-level `return`, `break` or `continue` in a
module is an error as in a program (`[scope.toplevel]`). What the module prints
goes to the same output as the program's.

## [mod.cycles] Circular imports

If a module is imported while it is still loading (a imports b, b imports a) the
second import is `ImportError: circular import: a.nova -> b.nova -> a.nova`
naming the modules by file name, from the one that closes the loop back to
itself. Like every error in a module it reaches the importer wrapped
(`[mod.errors]`).

## [mod.errors] Errors while loading

Any error raised while a module loads (a syntax error in its file, an error its
statements raise, a failed import of its own, a cycle) reaches the program that
imported it as

```
ImportError: while loading module "<path as written in the import>":
  <the module's error, indented>
```

and is an ordinary, catchable error (`[err.try-catch]`) whose text, when caught,
contains the module's own message, so `"division by zero" in e` is true. A module
imported by a module that fails is wrapped once for each level. Everything after
the first line is a report whose layout belongs to the host (a source excerpt,
for example): only the first line and the message inside it are the language's.
A syntax error in the module is found when it is imported, not before the
importing program starts, so a `try` can catch it.

## [mod.std] Standard modules

```
import "std:text"                        # binds  text
import "std:text" as t                   # binds  t
import "std:text" with find, ends_with   # binds  find  and  ends_with
```

A path that starts with `std:` names a **standard module**: a module that ships with
the interpreter and is written once for every engine. A version of NovaLang defines a
fixed set of them (this version: `std:text`, `[lib.std-text]`). Everything else in this
chapter holds for them (`[mod.import]` for the three forms and the name that is bound,
`[mod.export]`, `[mod.cache]`, `[mod.scope]`, `[mod.errors]`), with these differences:

1. **The name is looked up in the set, never in the file system.** A name outside it is
   `ImportError: there is no standard module "std:nope" - the standard modules are:
   std:text`, listing every standard module in alphabetical order, separated by a comma
   and a space. The name is never joined to a path, so `std:../x` is such an error too.
2. **No grant is needed to find one.** A standard module is part of the interpreter, so a
   `restricted` program with no `import` grant may import it, and the folders of
   `[sbx.paths]` do not apply to it. `import "std:text"` and a program with no file system
   at all work alike (the cases are in the `core` profile, not `modules`).
3. **A standard module declares the capabilities it needs** (the names of
   `[sbx.capabilities]`), and importing one when the run did not grant every one of them
   is `ImportError: std:NAME needs the 'CAPABILITY' capability, which this run did not
   grant`, at the `import`, not later as `undefined name 'read'`. A module that declares
   none, as `std:text` does, can be imported in every profile. *No standard module
   declares a capability in this version, so no conformance case exercises this rule yet:
   it is checked by `tests/std/test_modules.py` on the host engines, and it becomes
   normative for a module's engines when the first module that declares one has its cases.*
4. **A standard module adds no global name.** The name it is bound to is the importer's
   (`as`), the default `text` is an ordinary variable that can be shadowed, and a built-in's
   name is still refused as a module name (`[mod.import]`, `[scope.reserved]`).
5. **A standard module runs under the limits of the run that imports it**: its steps, its
   output and its sizes count like the importer's own.
6. **A standard module may call native functions.** Some work cannot be done in NovaLang at
   a usable speed or at all (exact arithmetic on big numbers, the code point of a character, reading
   a file in pieces), so a standard module may be given functions written by the host, which it
   reaches through a name, `native`, that exists in the scope of that one module and in no
   other: a program, a module of its own or a package cannot name it, and it is not a built-in, so it
   reserves nothing. What a native function computes, and the text of its errors, is part of
   the module's specification, the same on every engine; the module's own file only wraps it, so a
   call with the wrong number of arguments is the language's message for a function. A native function
   that reads a file is held to the granted folders exactly as `read` is (`[sbx.paths]`), and
   its result to the limits of the run (`[sbx.limits]`).

The tier of each standard module (`provisional` or `stable`) and what it means is in
[STABLE.md](STABLE.md).
