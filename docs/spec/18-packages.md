# 18. Packages

A *package* is a folder with a `nova.json` that a project depends on. `tools/nova-pkg.py` resolves a project's
dependencies, writes `nova.lock` and copies the packages into `.nova_modules/`; `import "name"` (a bare name, no `.nova`
and no `/`) then loads the package's entry file ([mod.import]). This chapter specifies the manifest, the folder layout,
the lockfile, what the tool checks, and the **declared capabilities** of a package, which the interpreter and the tool
check in the same way (decision D9 of the M13 plan, `[sbx.capabilities]`). The registry (names with an owner, the index,
signatures and `publish`) is the business of a later version and is not specified here.

The sections with an id are what a conforming host does and are held by the conformance corpus (the `modules` and
`sandbox` profiles); the sections about the tool have no id: `tools/nova-pkg.py` is a Python program, not part of a
conforming host, and `tests/pkg/` holds it.

## [pkg.manifest] `nova.json`, version 2

```json
{
  "name": "math-utils",
  "version": "1.4.2",
  "description": "Exact arithmetic helpers",
  "license": "MIT",
  "authors": ["Ada Lovelace <ada@example.org>"],
  "repository": "https://example.org/math-utils",
  "nova": "^2.3.0",
  "main": "main.nova",
  "files": ["main.nova", "src/**/*.nova", "README.md", "LICENSE"],
  "capabilities": ["files.read"],
  "dependencies": {"str-tools": "^0.1.0", "local-lib": {"path": "../local-lib"}},
  "policy": {"capabilities": ["files.read", "clock"]},
  "registry": "../registry"
}
```

| Key | Rule |
| --- | --- |
| `name` | required. Lowercase letters, digits, `.`, `_` and `-`, starting with a letter or digit; or `owner/name` of two such parts (the form for anything to be published). The owners `std` and `nova` are reserved. A name with an owner is valid for a **project**; a **dependency** with one is refused until a registry exists |
| `version` | required. `MAJOR.MINOR.PATCH` |
| `description`, `license`, `repository`, `registry` | text |
| `authors` | a list of text |
| `nova` | the NovaLang versions the package works with, in the range forms of "Version ranges" below. `install` refuses a package whose range does not include the running version |
| `main` | the entry file: a relative `.nova` path with `/` and no `..` (default `main.nova`) |
| `files` | the allowlist that publishing will pack: relative paths and `*` / `**` patterns of `.nova`, `.json` and `.md` files, `LICENSE` and `NOTICE`; no `..`, no absolute path, no `\`, no drive letter |
| `capabilities` | the closed list of capability names the package's own code uses: `files.read`, `files.write`, `env`, `clock`, `random`, `stdin`, `process`, `regex`, `python`, `net`. Each at most once. A package that lists none uses none |
| `dependencies` | an object of name to a range, `{"path": ...}` or `{"git": ..., "ref": ...}` |
| `policy` | the **project's** only: `{"capabilities": [...]}`, the most any dependency may declare ("What `install` checks" below). Ignored in a dependency's manifest |
| `x-...` | any key starting with `x-` is allowed and ignored |
| anything else | **an error**: `unknown key "<key>"`. There is no key for scripts, hooks or commands, and the tool runs nothing from a package at any time |

A dependency's `registry` and `policy` are ignored: a package cannot redirect where the next package comes from or
widen what the project allows. The messages say what is wrong and what to do.

## Version ranges (the tool)

`"*"` any version; `"1.2.3"` exactly that; `"~1.2.3"` the same minor version, from that patch on; `"^1.2.3"` the same
major version (for `0.x` the same minor; for `0.0.x` exactly that patch), from that version on. There are no others.

## [pkg.layout] The folders

```
project/
  nova.json              the project's manifest
  nova.lock              what was installed, exactly (written by install, committed)
  .nova_modules/
    .installed.lock      a copy of nova.lock, written last
    .gitignore           ignores everything here
    math-utils/          one folder per package, flat: one version of each name
      nova.json  main.nova  src/...
```

`import "math-utils"` finds the nearest `.nova_modules/math-utils/nova.json` walking up from the importing file's folder
and loads its `main` (so a package's own imports find its dependencies, which are installed beside it). The packages are
used only if `.nova_modules/.installed.lock` is the same text as `nova.lock` and `nova.lock`'s `requires` is the project's
`dependencies`; otherwise `ImportError: the packages in <folder> cannot be used: <why> - run \`python3 tools/nova-pkg.py
install\``. A bare name binds the module under the name with `-` and `.` made `_`.

## `nova.lock`, version 2 (the tool)

A JSON object with sorted keys and no timestamps (the same inputs write the same bytes): `lockfile_version` (2),
`requires` (the project's `dependencies`) and `packages`, an object by name of `version`, `source` (`registry`, `path` or
`git` with the commit), `integrity` (a SHA-256 over the path and bytes of every file), **`capabilities`** (what the
package declared, sorted) and `dependencies`. A version-1 lockfile (no `capabilities`) is read; the next `install` writes
it as version 2. `install --frozen` installs exactly the lock and refuses a change of any recorded value, including a
package that now declares other capabilities than the lock recorded.

## [pkg.capabilities] Declared capabilities

A package lists in `capabilities` the capabilities of the gated names (`[sbx.capabilities]`) that its own code refers to.
The check is **static**. The syntax tree of each `.nova` file is searched for every **variable the program reads or
calls** whose name is a gated name (the names of `CAPABILITY_OF`, and `python` for the `python` capability). A field name
(`x.read`), a dictionary key (`{read: 1}`) and a name a function declares are not references; a gated name inside an
f-string is. `import` is not a capability of a package: what a package may import is the run's `import` grant.

1. **At import.** When a file inside `.nova_modules/<package>/` is about to run, (a) every capability the package declares
   MUST have been granted to the run, once per package and run: otherwise `ImportError: package "<name>" needs the
   '<capability>' capability, which this run did not grant`, **at the import**, before any code of the package runs (the
   trusted profile grants all but `net`, which no run grants in this version); a name that is not on the closed list is
   `ImportError: package "<name>": nova.json declares "<x>", which is not a capability (the capabilities are: ...)`; and (b)
   the file MUST NOT refer to a gated name whose capability the package does not declare: otherwise `ImportError: package
   "<name>": <file> uses <name>, which needs the <capability> capability, and its nova.json does not declare it` (the file is
   relative to the package, with `/`; if several, the first in alphabetical order of the names).
2. **At install** the tool makes check (b) on every `.nova` file of every package before anything is copied, with the same
   parser (`nova-pkg: <package>/<file> uses <name>, which needs <capability>, which its nova.json does not declare`). A
   package that declares a capability none of its files uses is a **warning**, not an error: over-declaring asks users
   for more than the package needs.
3. The check is the same on the three engines, because it needs only the syntax tree.

**What it proves, and what it does not.** It proves that a package **cannot name** a gated function that it did not
declare, because NovaLang has no dynamic code and no reflection. It does **not** stop **capability passing**: a program
that imports a package and hands it `write` as an argument has given it that capability, which is the language's model
and is visible in the program. It is **not isolation**: a package granted `files.write` can write anywhere the run's
grant allows, and the grants of the run (`[sbx.profiles]`) remain the only enforcement at run time. Declared capabilities
are a consent screen, a review aid and a static check. A per-module grant at run time is a candidate for a later version.

## What `install` checks (the tool)

In this order, and nothing is copied until all of it passes:

1. every manifest is valid (`[pkg.manifest]`) and the running NovaLang version is in each package's `nova` range;
2. `[pkg.capabilities]` 2 for every package;
3. **the project's policy.** If the project's manifest has `policy`, no package may declare a capability outside
   `policy.capabilities`: `package <name> <version> needs <capabilities>, which "policy" in nova.json does not allow`.
   Without `policy` there is no limit;
4. **escalation protection.** A package that is already locked MUST NOT move to a version that declares a capability the
   locked version did not, unless the user names it: `install --accept-capabilities files.read,clock`. The error names the
   package, the new capabilities and what to run. A package added to `nova.json` for the first time is the user's own
   decision and is not an escalation;
5. then the packages are copied and `nova.lock` and `.installed.lock` are written.

`nova-pkg.py capabilities [PACKAGE]` prints, for each installed package (or one), what it declares and what its files
use, marks a capability used and not declared (a file edited after install), and the project's policy. `nova-pkg.py init
[NAME]` writes a version-2 manifest with an empty `capabilities` list.
