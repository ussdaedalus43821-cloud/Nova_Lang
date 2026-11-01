#!/usr/bin/env python3
"""
nova_compiler.py - show what NovaLang compiles a program to.

    python3 tools/nova_compiler.py file.nova [more.nova ...]

Same as `python3 novalang.py --dis`. The compiler itself lives in
novalang.py (compile_ast, Resolver, Compiler, verify, disassemble): every
program goes through it, so it is part of the language, not a tool. This
is only the command-line view of it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import novalang  # noqa: E402

if __name__ == "__main__":
    sys.exit(novalang.dis_main(sys.argv[1:]))
