"""Writes tests/conformance/cases/packages.json (M13 slice 5): the declared capabilities of an installed package
(docs/spec/18-packages.md [pkg.capabilities]), checked at import on every engine. The project is made by hand (a manifest,
a lockfile, the installed copy of it and the package's files), as `nova-pkg install` would leave it."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) + "/"
cases = []


def case(name, spec, source, output, error="", error_line=None, exit=0, profile="modules", sandbox=None, extra=None):
    c = {"name": name, "spec": spec, "profile": profile, "source": source, "output": output,
         "error": error, "error_line": error_line, "exit": exit, "host_calls": []}
    if sandbox is not None:
        c["sandbox"] = sandbox
    if extra:
        c.update(extra)
    cases.append(c)


def project(package_manifest, main, more=None):
    """The files of a project that depends on `lib`, installed."""
    lock = {"lockfile_version": 2, "requires": {"lib": "*"}, "packages": {"lib": {
        "version": "1.0.0", "source": {"path": "../lib"}, "integrity": "sha256-x",
        "capabilities": package_manifest.get("capabilities", []), "dependencies": {}}}}
    text = json.dumps(lock, indent=2, sort_keys=True) + "\n"
    files = {
        "nova.json": json.dumps({"name": "app", "version": "1.0.0", "dependencies": {"lib": "*"}}),
        "nova.lock": text,
        ".nova_modules/.installed.lock": text,
        ".nova_modules/lib/nova.json": json.dumps(dict({"name": "lib", "version": "1.0.0"}, **package_manifest)),
        ".nova_modules/lib/main.nova": main,
    }
    files.update(more or {})
    return files


LOCK_TWO = json.dumps({"lockfile_version": 2, "requires": {"lib-two.x": "*"}, "packages": {"lib-two.x": {
    "version": "1.0.0", "source": {"path": "../lib"}, "integrity": "sha256-x", "capabilities": [], "dependencies": {}}}},
    indent=2, sort_keys=True) + "\n"
READER = "export def load(path) {\n  return read(path)\n}\n"
IMPORT_ALL = {"profile": "restricted", "import_from": ["."]}
GRANT_READ = {"profile": "restricted", "import_from": ["."], "read": ["."]}

case("pkg-undeclared-gated-name-is-refused-at-import", ["pkg.capabilities", "sbx.capabilities"],
     'import "lib"\nprint(lib.load("nova.json"))',
     [], error='ImportError: package "lib": main.nova uses read, which needs the files.read capability, and its nova.json does not declare it',
     error_line=1, exit=1, extra={"files": project({}, READER)})
case("pkg-declared-gated-name-runs", ["pkg.capabilities"],
     'import "lib"\nprint(len(lib.load("nova.json")) > 0)',
     ["true"], extra={"files": project({"capabilities": ["files.read"]}, READER)})
case("pkg-every-file-of-a-package-is-checked-when-it-is-imported", ["pkg.capabilities"],
     'import ".nova_modules/lib/src/inner.nova" as inner\nprint(inner.go())',
     [], error='ImportError: package "lib": src/inner.nova uses time, which needs the clock capability, and its nova.json does not declare it',
     error_line=1, exit=1,
     extra={"files": project({}, "export let x = 1\n", {".nova_modules/lib/src/inner.nova": "export def go() {\n  return time()\n}\n"})})
case("pkg-a-package-file-imported-by-path-is-checked-like-one-imported-by-name", ["pkg.capabilities"],
     'import ".nova_modules/lib/main.nova" as direct\nprint(direct.twice(4))',
     ["8"], extra={"files": project({}, "export def twice(x) {\n  return x * 2\n}\n")})
case("pkg-a-name-inside-an-f-string-is-a-reference", ["pkg.capabilities"],
     'import "lib"\nprint(lib.go("x"))',
     [], error='ImportError: package "lib": main.nova uses read, which needs the files.read capability, and its nova.json does not declare it',
     error_line=1, exit=1, extra={"files": project({}, 'export def go(path) {\n  return f"{read(path)}"\n}\n')})
case("pkg-field-names-keys-and-parameters-are-not-references", ["pkg.capabilities"],
     'import "lib"\nprint(lib.go({read: 1, time: 2}), lib.named(3, 4))',
     ["3 7"], extra={"files": project({}, 'export def go(table) {\n  return table.read + table["time"]\n}\n'
                                         'export def named(read_count, env_count) {\n  return read_count + env_count\n}\n')})
case("pkg-the-first-undeclared-name-in-alphabetical-order-is-named", ["pkg.capabilities"],
     'import "lib"',
     [], error='ImportError: package "lib": main.nova uses env, which needs the env capability, and its nova.json does not declare it',
     error_line=1, exit=1, extra={"files": project({}, 'export def go() {\n  return [time(), env("HOME")]\n}\n')})
case("pkg-declared-capabilities-must-be-granted-at-the-import", ["pkg.capabilities", "sbx.capabilities"],
     'import "lib"\nprint(lib.load("nova.json"))',
     [], error="ImportError: package \"lib\" needs the 'files.read' capability, which this run did not grant", error_line=1, exit=1,
     profile="sandbox", sandbox=IMPORT_ALL, extra={"files": project({"capabilities": ["files.read"]}, READER)})
case("pkg-declared-and-granted-runs-in-the-restricted-profile", ["pkg.capabilities", "sbx.capabilities"],
     'import "lib"\nprint(len(lib.load("nova.json")) > 0)',
     ["true"], profile="sandbox", sandbox=GRANT_READ, extra={"files": project({"capabilities": ["files.read"]}, READER)})
case("pkg-a-package-that-declares-nothing-needs-no-grant", ["pkg.capabilities", "sbx.profiles"],
     'import "lib"\nprint(lib.twice(21))',
     ["42"], profile="sandbox", sandbox=IMPORT_ALL,
     extra={"files": project({}, "export def twice(x) {\n  return x * 2\n}\n")})
case("pkg-a-capability-that-is-not-on-the-list-is-refused", ["pkg.capabilities"],
     'import "lib"',
     [], error='ImportError: package "lib": nova.json declares "everything", which is not a capability (the capabilities are: '
               'files.read, files.write, env, clock, random, stdin, process, regex, python, net)',
     error_line=1, exit=1, extra={"files": project({"capabilities": ["everything"]}, "export let x = 1\n")})
case("pkg-net-is-not-granted-in-this-version", ["pkg.capabilities"],
     'import "lib"',
     [], error="ImportError: package \"lib\" needs the 'net' capability, which this run did not grant", error_line=1, exit=1,
     extra={"files": project({"capabilities": ["net"]}, "export let x = 1\n")})
case("pkg-the-grant-is-checked-before-any-code-of-the-package-runs", ["pkg.capabilities"],
     'import "lib"',
     [], error="ImportError: package \"lib\" needs the 'files.read' capability, which this run did not grant", error_line=1, exit=1,
     profile="sandbox", sandbox=dict(IMPORT_ALL, clock=True),
     extra={"files": project({"capabilities": ["files.read"]}, 'print("ran")\nexport let x = 1\n')})

case("pkg-a-bare-name-binds-the-name-with-dashes-and-dots-made-underscores", ["pkg.layout"],
     'import "lib-two.x"\nprint(lib_two_x.twice(4))',
     ["8"], extra={"files": {
         "nova.json": json.dumps({"name": "app", "version": "1.0.0", "dependencies": {"lib-two.x": "*"}}),
         "nova.lock": LOCK_TWO, ".nova_modules/.installed.lock": LOCK_TWO,
         ".nova_modules/lib-two.x/nova.json": json.dumps({"name": "lib-two.x", "version": "1.0.0"}),
         ".nova_modules/lib-two.x/main.nova": "export def twice(x) {\n  return x * 2\n}\n"}})
case("pkg-a-package-is-found-walking-up-from-the-importing-file", ["pkg.layout"],
     'import "sub/deep/b.nova" as b\nprint(b.go())',
     ["42"], extra={"files": project({}, "export def twice(x) {\n  return x * 2\n}\n",
                                    {"sub/deep/b.nova": 'import "lib"\nexport def go() {\n  return lib.twice(21)\n}\n'})})
case("pkg-a-package-that-is-not-installed-names-where-it-looked", ["pkg.layout"],
     'try {\n  import "missing"\n} catch e {\n  print(e[0:55])\n}',
     ['ImportError: cannot find package "missing" - looked in:'], extra={"files": project({}, "export let x = 1\n")})
case("pkg-packages-are-not-used-when-the-install-is-stale", ["pkg.layout"],
     'try {\n  import "lib"\n} catch e {\n  print(split(e, "cannot be used: ")[1])\n}',
     ["they were not installed from the current nova.lock - run `python3 tools/nova-pkg.py install`"],
     extra={"files": project({}, "export let x = 1\n", {".nova_modules/.installed.lock": "{}\n"})})
case("pkg-the-entry-file-is-the-main-of-the-manifest", ["pkg.manifest", "pkg.layout"],
     'import "lib"\nprint(lib.where())',
     ["entry"], extra={"files": project({"main": "src/entry.nova"}, "export def where() {\n  return \"wrong\"\n}\n",
                                       {".nova_modules/lib/src/entry.nova": "export def where() {\n  return \"entry\"\n}\n"})})
case("pkg-main-must-name-a-nova-file-and-the-file-must-exist", ["pkg.manifest"],
     'try {\n  import "lib"\n} catch e {\n  print(e)\n}',
     ['ImportError: package "lib": "main" in its nova.json must name a .nova file'],
     extra={"files": project({"main": "main.txt"}, "export let x = 1\n")})
case("pkg-a-missing-entry-file-is-an-import-error", ["pkg.manifest"],
     'try {\n  import "lib"\n} catch e {\n  print(e)\n}',
     ['ImportError: package "lib" has no entry file gone.nova'],
     extra={"files": project({"main": "gone.nova"}, "export let x = 1\n")})

def scoped_project(name, package_manifest, main):
    lock = {"lockfile_version": 2, "requires": {name: "*"}, "packages": {name: {
        "version": "1.0.0", "source": {"registry": "../registry"}, "integrity": "sha256-x", "resolved": "archive/x.tar",
        "archive": "sha256-y", "signedBy": ["0000000000000000"], "capabilities": package_manifest.get("capabilities", []),
        "dependencies": {}}}}
    text = json.dumps(lock, indent=2, sort_keys=True) + "\n"
    return {
        "nova.json": json.dumps({"name": "app", "version": "1.0.0", "dependencies": {name: "*"}}),
        "nova.lock": text, ".nova_modules/.installed.lock": text,
        ".nova_modules/" + name + "/nova.json": json.dumps(dict({"name": name, "version": "1.0.0"}, **package_manifest)),
        ".nova_modules/" + name + "/main.nova": main,
    }


case("pkg-owner-slash-name-is-a-package-and-binds-the-part-after-the-slash", ["pkg.layout"],
     'import "acme/ledger-core"\nprint(ledger_core.twice(4))\nimport "acme/ledger-core" as lc\nprint(lc.twice(5))',
     ["8", "10"], extra={"files": scoped_project("acme/ledger-core", {}, "export def twice(x) {\n  return x * 2\n}\n")})
case("pkg-a-scoped-package-is-held-to-its-declared-capabilities", ["pkg.capabilities", "pkg.layout"],
     'import "acme/ledger"',
     [], error='ImportError: package "acme/ledger": main.nova uses read, which needs the files.read capability, and its nova.json does not declare it',
     error_line=1, exit=1, extra={"files": scoped_project("acme/ledger", {}, READER)})
case("pkg-a-scoped-package-needs-its-capabilities-granted", ["pkg.capabilities", "pkg.layout"],
     'import "acme/ledger"',
     [], error="ImportError: package \"acme/ledger\" needs the 'files.read' capability, which this run did not grant", error_line=1, exit=1,
     profile="sandbox", sandbox=IMPORT_ALL, extra={"files": scoped_project("acme/ledger", {"capabilities": ["files.read"]}, READER)})
case("pkg-the-owner-folder-is-not-a-package", ["pkg.layout"],
     'try {\n  import "acme"\n} catch e {\n  print(e[0:48])\n}',
     ['ImportError: cannot find package "acme" - looked'], extra={"files": scoped_project("acme/ledger", {}, "export let x = 1\n")})
case("pkg-a-name-with-more_than_one_slash-or-a-nova-suffix-is-a-file", ["pkg.layout"],
     'try {\n  import "a/b/c"\n} catch e {\n  print(e[0:44])\n}',
     ['ImportError: cannot find module "a/b/c" - lo'])

doc = {"area": "packages", "version": 1, "cases": cases}
open(ROOT + "tests/conformance/cases/packages.json", "w", encoding="utf-8").write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
print(len(cases), "cases")
