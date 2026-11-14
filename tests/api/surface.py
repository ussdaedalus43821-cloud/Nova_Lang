"""Builds the public surface of this NovaLang from the running source, for the stable-surface test.

    python3 tests/api/surface.py            print the surface as JSON
    python3 tests/api/test_stable_surface.py --update      rewrite tests/api/stable-surface.json

The surface is what docs/spec/STABLE.md calls stable, read from the code and not from a list kept by
hand: the keywords, every global built-in with its arity and the capability that gates it, the
predefined globals, the capability names, the sandbox limits, the sandbox command-line flags, the
public methods of the embedding class, the package manifest keys the package tool reads, and the
standard modules with their tier and exports. Error message texts are covered by the conformance
corpus, which cites them; this file is about names and shapes.
"""

import inspect
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import novalang  # noqa: E402


def manifest_keys():
    """The `nova.json` keys the package tool and the interpreter read (a `manifest.get("x")` or `manifest["x"]`)."""
    keys = set()
    for name in (os.path.join("tools", "nova-pkg.py"), "novalang.py"):
        with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
            keys.update(re.findall(r'manifest(?:\.get\(|\[)"([a-z][a-z_]*)"', handle.read()))
    return sorted(keys)


def build():
    builtins = {}
    for name, function in sorted(novalang.BUILTINS.items()):
        builtins[name] = {"arity": function.arity, "capability": novalang.CAPABILITY_OF.get(name)}
    nova_methods = {}
    for name in sorted(n for n in dir(novalang.Nova) if not n.startswith("_")):
        member = getattr(novalang.Nova, name)
        if callable(member):
            nova_methods[name] = str(inspect.signature(member))
    with open(os.path.join(novalang.STD_DIR, "modules.json"), encoding="utf-8") as handle:
        std = json.load(handle)["modules"]
    return {
        "version": novalang.__version__,
        "keywords": sorted(novalang.KEYWORDS),
        "builtins": builtins,
        "predefined": ["E", "PI", "json", "python"],
        "json_members": sorted(["dumps", "loads", "pretty"]),
        "capabilities": sorted(set(novalang.CAPABILITY_OF.values()) | {"import", "python"}),
        "limits": sorted(novalang.SANDBOX_LIMITS),
        "sandbox_flags": sorted(novalang.SANDBOX_FLAGS),
        "embedding": {"class": "Nova", "constructor": str(inspect.signature(novalang.Nova.__init__)),
                      "methods": nova_methods},
        "manifest_keys": manifest_keys(),
        "std_modules": {name: {"tier": d["tier"], "capabilities": d["capabilities"], "exports": d["exports"],
                               "native": d.get("native", [])}
                        for name, d in sorted(std.items())},
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=1, ensure_ascii=False, sort_keys=True))
