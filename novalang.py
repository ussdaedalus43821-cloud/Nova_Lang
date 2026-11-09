#!/usr/bin/env python3
# NovaLang v2.1.0 - a small language built from a hand-written lexer,
# recursive-descent parser, bytecode compiler and virtual machine.
"""
NovaLang v2.1.0 - a bytecode compiler and VM

Since 2.0.0 a program runs as bytecode:

    source text  ->  Lexer     ->  tokens
    tokens       ->  Parser    ->  AST (Abstract Syntax Tree)
    AST          ->  type gate ->  refused, or allowed to run (M1)
    AST          ->  Compiler  ->  a CodeObject (bytecode)
    CodeObject   ->  VM        ->  a value

The tree-walking Interpreter that ran every program up to 1.1.0 is still
here, unchanged, as the fallback (`--tree-walk`, Nova(engine="tree")) and
as the reference the VM is tested against: tests/vm/test_differential.py
requires byte-identical output, errors and exit status from both.

Stage 1:  numbers, + - * / ( ), variables, the REPL.
Stage 2:  def / return, if / else, comparisons, booleans, strings,
          print, recursion with a real call stack.
Stage 3:  while loops (with an optional else), for ... to / downto / step,
          break and continue, and / or / not with short-circuiting,
          and block scoping.
Stage 4:  lists and indexing, let, % and //, for ... in, and the
          len / append / pop / range built-ins.
Stage 5:  string indexing and slicing, f-strings, the `in` operator, and
          upper / lower / trim / split / join / str / num / type.
Stage 6:  dictionaries - literals, dot and bracket access, delete,
          merging, pair iteration, and the keys / values built-ins.
Stage 7:  files - read / write / append / exists / listdir, delete(path),
          and input() for reading a line from the person at the keyboard.
Stage 8:  try / catch / finally and throw, so a program can recover from
          an error instead of stopping at it.
Stage 9:  modules - import "file.nova" [as name | with a, b], export def /
          export let, relative paths, a module cache, and circular-import
          detection.
Stage 10: self-hosting - novalang.nova is a second Lexer/Parser/Interpreter
          for this same language, written in NovaLang itself. bootstrap.py
          (or `novalang.py --bootstrap file.nova`) loads it and uses it to
          run a target file, instead of running that file with this Python
          engine directly.
Stage 11: a standard library - time, random, math, the OS and filesystem,
          JSON, string utilities, assert/log, and map/filter/reduce - all
          global, no import needed, and identical under --bootstrap.
Stage 12: embedding - a Python-side Nova class (eval/exec/load_file/call/
          compile/expose) for running NovaLang from a Python program, and
          a NovaLang-side `python` namespace (call/get/set/import) for
          reaching back into Python - through an explicit, host-controlled
          bridge, not unrestricted access to the process.
Stage 13: polish and documentation - README.md, a finalized CHANGELOG.md,
          CONTRIBUTING.md, and the v1.0.0 release. No language or
          standard-library behavior changed; Stages 1-12 are the complete,
          stable feature set that release shipped.
Stage 14: an Entity-Component-System library (lib/ecs.nova) and a grid
          spatial hash (lib/spatial_hash.nova), plus a 25,000-50,000-
          particle demo (examples/ecs_particles.nova,
          examples/ecs_demo.py) built on both. The particle simulation
          itself runs as vectorized NumPy in Python, not NovaLang - see
          lib/ecs.nova's header for the measured numbers behind that
          choice. NovaLang owns the ECS and everything at gameplay
          scale: entities, components, queries, emitters, force fields,
          mouse-interaction rules.
2.0.0:    tooling (M0: --format, --check), gradual typing (M1:
          --typecheck and the type gate), packages (M2: tools/nova-pkg.py),
          editor support (M3: the language server and VS Code extension),
          and the bytecode compiler and VM (M4: --dis), now the default
          engine. Every program runs the same on both engines; the few
          deliberate changes from 1.1.0 are listed in CHANGELOG.md.
2.0.1:    fast paths for assignment through an index, a member and
          delete, and a dispatch order that keeps them out of the bottom
          of the ladder (M6). No behavior changed.
2.1.0:    verification (CI on Linux, macOS and Windows, many new regression
          stations), portability and error-boundary fixes, and a closed
          python.* bridge: off unless --allow-python or
          Nova(allow_python=True), private and module-alias names
          unreachable (docs/design/python-bridge-hardening.md).

No eval(). No exec(). Everything is still built by hand.
"""

import bisect
import decimal
import importlib
import json as json_module
import math
import os
import platform
import random
import re
import shutil
import sys
import contextlib
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from types import BuiltinFunctionType, FunctionType, MethodType, ModuleType

__version__ = "2.1.0"

# A NovaLang call burns several Python frames, so give CPython some headroom
# and enforce our own, friendlier limit in the interpreter (MAX_CALL_DEPTH).
# Both are set generously enough to also cover Stage 10's self-hosted
# interpreter (novalang.nova), where each level of *target*-program
# recursion costs several *host* NovaLang calls in turn - a target
# recursion of 20 (fib(20), say) costs on the order of 200 host-level
# calls. 1200 was tested empirically to stay well clear of where CPython's
# own stack becomes a concern at this recursion limit.
sys.setrecursionlimit(20000)

MAX_CALL_DEPTH = 1200

# How many call-stack frames an error report shows before it elides the middle.
MAX_TRACE_FRAMES = 8


# ---------------------------------------------------------------------------
# Errors and the signals that unwind the interpreter
# ---------------------------------------------------------------------------

class NovaLangError(Exception):
    """Raised by the Stage 12 Python embedding API (Nova.eval/exec/
    load_file/call, and a NovaLang function value wrapped for Python) when
    the NovaLang code involved raises or fails - wrapping the underlying
    NovaError so calling code never has to import NovaLang's own error
    type to handle it. str(this) is the rendered NovaLang message; the
    original NovaError is chained as __cause__ for anyone who wants it."""

    def __init__(self, nova_error):
        super().__init__(error_text(nova_error))
        self.nova_error = nova_error


class NovaError(Exception):
    """A NovaLang error that points at the offending character."""

    def __init__(self, message, position=None, label="NovaError"):
        super().__init__(message)
        self.message = message
        self.position = position
        self.label = label      # file trouble reports itself as FileNotFoundError
        self.stack = None       # filled in by the interpreter on a call error

    def render(self, source):
        """Build a friendly report: the offending line, a caret, the stack."""
        lines = []

        if self.position is not None:
            spans = line_spans(source)
            position = max(0, min(self.position, len(source)))
            line_number = 0
            while line_number < len(spans) - 1 and position >= spans[line_number + 1][0]:
                line_number += 1
            start, end = spans[line_number]
            text = source[start:end]
            offset = position - start
            gutter = "  {} | ".format(line_number + 1) if len(spans) > 1 else "  "
            lines.append(gutter + text)
            lines.append(" " * len(gutter) + " " * min(offset, len(text)) + "^")

        lines.append(self.label + ": " + self.message)

        # Deep recursion produces a very long stack; show both ends of it.
        frames = self.stack or []
        if len(frames) > MAX_TRACE_FRAMES:
            head, tail = frames[:MAX_TRACE_FRAMES - 2], frames[-2:]
            hidden = len(frames) - len(head) - len(tail)
            lines.extend("  in " + frame for frame in head)
            lines.append("  ... {} more frames ...".format(hidden))
            lines.extend("  in " + frame for frame in tail)
        else:
            lines.extend("  in " + frame for frame in frames)

        return "\n".join(lines)


LINE_BREAK = re.compile(r"\r\n|\r|\n")


def line_spans(source):
    """(start, end) of every line, the break excluded. A line ends at
    "\n", "\r\n" or a lone "\r", exactly as the Lexer counts them."""
    spans = []
    start = 0
    for match in LINE_BREAK.finditer(source):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(source)))
    return spans


class ReturnSignal(Exception):
    """Not an error - how `return` unwinds back to the calling frame."""

    def __init__(self, value):
        super().__init__("return")
        self.value = value


class BreakSignal(Exception):
    """How `break` unwinds out of the innermost loop."""

    def __init__(self, position):
        super().__init__("break")
        self.position = position


class ContinueSignal(Exception):
    """How `continue` unwinds to the top of the innermost loop."""

    def __init__(self, position):
        super().__init__("continue")
        self.position = position


# ---------------------------------------------------------------------------
# 1. Lexer  (source text -> tokens)
# ---------------------------------------------------------------------------

TT_NUMBER  = "NUMBER"
TT_STRING  = "STRING"
TT_FSTRING = "FSTRING"      # f"a {b} c" - value is a list of parts
TT_IDENT   = "IDENT"
TT_PLUS    = "PLUS"
TT_MINUS   = "MINUS"
TT_STAR    = "STAR"
TT_SLASH   = "SLASH"
TT_LPAREN  = "LPAREN"
TT_RPAREN  = "RPAREN"
TT_LBRACE  = "LBRACE"
TT_RBRACE  = "RBRACE"
TT_COMMA   = "COMMA"
TT_LBRACKET = "LBRACKET"    # [
TT_RBRACKET = "RBRACKET"    # ]
TT_DOT     = "DOT"          # .   field access
TT_COLON   = "COLON"        # :   inside a slice, or between key and value
TT_PERCENT = "PERCENT"      # %   remainder
TT_DSLASH  = "DSLASH"       # //  integer division
TT_EQUALS  = "EQUALS"       # =   assignment
TT_EQ      = "EQ"           # ==  equality
TT_NE      = "NE"           # !=
TT_LT      = "LT"           # <
TT_GT      = "GT"           # >
TT_LE      = "LE"           # <=
TT_GE      = "GE"           # >=
TT_NEWLINE = "NEWLINE"      # statement separator (also ';')
TT_EOF     = "EOF"

# Keywords are lexed as identifiers first, then promoted by this table.
TT_DEF      = "DEF"
TT_RETURN   = "RETURN"
TT_IF       = "IF"
TT_ELSE     = "ELSE"
TT_TRUE     = "TRUE"
TT_FALSE    = "FALSE"
TT_WHILE    = "WHILE"       # Stage 3 from here down
TT_FOR      = "FOR"
TT_TO       = "TO"
TT_DOWNTO   = "DOWNTO"
TT_STEP     = "STEP"
TT_BREAK    = "BREAK"
TT_CONTINUE = "CONTINUE"
TT_AND      = "AND"
TT_OR       = "OR"
TT_NOT      = "NOT"
TT_LET      = "LET"         # Stage 4
TT_IN       = "IN"
TT_DELETE   = "DELETE"      # Stage 6
TT_TRY      = "TRY"         # Stage 8
TT_CATCH    = "CATCH"
TT_FINALLY  = "FINALLY"
TT_THROW    = "THROW"
TT_IMPORT   = "IMPORT"      # Stage 9
TT_EXPORT   = "EXPORT"
TT_AS       = "AS"
TT_WITH     = "WITH"

KEYWORDS = {
    "def": TT_DEF,
    "return": TT_RETURN,
    "if": TT_IF,
    "else": TT_ELSE,
    "true": TT_TRUE,
    "false": TT_FALSE,
    "while": TT_WHILE,
    "for": TT_FOR,
    "to": TT_TO,
    "downto": TT_DOWNTO,
    "step": TT_STEP,
    "break": TT_BREAK,
    "continue": TT_CONTINUE,
    "and": TT_AND,
    "or": TT_OR,
    "not": TT_NOT,
    "let": TT_LET,
    "in": TT_IN,
    "delete": TT_DELETE,
    "try": TT_TRY,
    "catch": TT_CATCH,
    "finally": TT_FINALLY,
    "throw": TT_THROW,
    "import": TT_IMPORT,
    "export": TT_EXPORT,
    "as": TT_AS,
    "with": TT_WITH,
}

# Keywords may still be used as dictionary keys and field names, so the
# parser needs to recognise their token types as names.
KEYWORD_TOKEN_TYPES = frozenset(KEYWORDS.values())

# `in` sits at the same precedence as the comparisons: `x in a == true`
# is a chained comparison and is rejected, exactly like `a < b < c`.
COMPARISON_TOKENS = (TT_EQ, TT_NE, TT_LT, TT_GT, TT_LE, TT_GE, TT_IN)

SINGLE_CHAR_TOKENS = {
    "+": TT_PLUS,
    "-": TT_MINUS,
    "*": TT_STAR,
    "/": TT_SLASH,
    "(": TT_LPAREN,
    ")": TT_RPAREN,
    "{": TT_LBRACE,
    "}": TT_RBRACE,
    "[": TT_LBRACKET,
    "]": TT_RBRACKET,
    ",": TT_COMMA,
    ".": TT_DOT,
    ":": TT_COLON,
    "%": TT_PERCENT,
}

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'", "0": "\0"}


class Token:
    def __init__(self, type_, value, position):
        self.type = type_
        self.value = value
        self.position = position

    def __repr__(self):
        return "Token({}, {!r})".format(self.type, self.value)


def is_digit(char):
    """An ASCII decimal digit. Not str.isdigit() or str.isdecimal(), which accept
    the digits of other scripts: a name or a number written with look-alike
    characters must be an error, not a different program (docs/spec/01-lexical.md)."""
    return "0" <= char <= "9"


def is_name_start(char):
    """An ASCII letter or an underscore: the start of a name."""
    return "a" <= char <= "z" or "A" <= char <= "Z" or char == "_"


def is_name_char(char):
    return is_name_start(char) or is_digit(char)


def is_bare_name(text):
    """Is `text` a name, so that a dictionary key can print without quotes?"""
    return bool(text) and is_name_start(text[0]) and all(is_name_char(char) for char in text)


class Lexer:
    """Turns source text into a flat list of tokens."""

    def __init__(self, source):
        self.source = source
        self.index = 0

    def peek(self, ahead=0):
        spot = self.index + ahead
        if spot < len(self.source):
            return self.source[spot]
        return None

    def advance(self):
        char = self.source[self.index]
        self.index += 1
        return char

    def tokenize(self):
        tokens = []
        while self.index < len(self.source):
            char = self.peek()
            start = self.index

            # Spaces and tabs are noise; newlines separate statements.
            if char in " \t":
                self.advance()
                continue

            # A line ends at "\n", "\r\n" or a lone "\r", as in editors and
            # the Language Server Protocol. For "\r\n" the "\n" is the newline.
            if char == "\r":
                self.advance()
                if self.peek() != "\n":
                    tokens.append(Token(TT_NEWLINE, "\n", start))
                continue

            if char == "\n" or char == ";":
                self.advance()
                tokens.append(Token(TT_NEWLINE, char, start))
                continue

            # Comments run to the end of the line.
            if char == "#":
                while self.peek() is not None and self.peek() not in "\r\n":
                    self.advance()
                continue

            if is_digit(char) or (char == "." and is_digit(self.peek(1) or "")):
                tokens.append(self.read_number())
                continue

            # f"..." is a formatted string. This has to come before the
            # identifier rule, which would otherwise read the 'f' as a name.
            if char == "f" and self.peek(1) in ('"', "'"):
                tokens.append(self.read_fstring())
                continue

            if is_name_start(char):
                tokens.append(self.read_identifier())
                continue

            if char in ('"', "'"):
                tokens.append(self.read_string())
                continue

            # Two-character operators must be tried before the one-char ones.
            two = self.source[self.index:self.index + 2]
            if two == "//":
                self.advance(); self.advance()
                tokens.append(Token(TT_DSLASH, "//", start))
                continue
            if two == "==":
                self.advance(); self.advance()
                tokens.append(Token(TT_EQ, "==", start))
                continue
            if two == "!=":
                self.advance(); self.advance()
                tokens.append(Token(TT_NE, "!=", start))
                continue
            if two == "<=":
                self.advance(); self.advance()
                tokens.append(Token(TT_LE, "<=", start))
                continue
            if two == ">=":
                self.advance(); self.advance()
                tokens.append(Token(TT_GE, ">=", start))
                continue

            if char == "=":
                self.advance()
                tokens.append(Token(TT_EQUALS, "=", start))
                continue
            if char == "<":
                self.advance()
                tokens.append(Token(TT_LT, "<", start))
                continue
            if char == ">":
                self.advance()
                tokens.append(Token(TT_GT, ">", start))
                continue
            if char == "!":
                raise NovaError(
                    "'!' on its own is not an operator - did you mean '!=' or 'not'?", start
                )

            if char in SINGLE_CHAR_TOKENS:
                self.advance()
                tokens.append(Token(SINGLE_CHAR_TOKENS[char], char, start))
                continue

            raise NovaError("unexpected character {!r}".format(char), start)

        tokens.append(Token(TT_EOF, None, self.index))
        return tokens

    def read_number(self):
        """Read an integer or a float such as 42, 3.14 or .5"""
        start = self.index
        digits = ""
        seen_dot = False

        while self.peek() is not None and (is_digit(self.peek()) or self.peek() == "."):
            char = self.advance()
            if char == ".":
                if seen_dot:
                    raise NovaError("a number cannot have two decimal points", self.index - 1)
                seen_dot = True
            digits += char

        if len(digits) - seen_dot > MAX_INTEGER_DIGITS:
            raise NovaError("this number has too many digits", start)
        try:
            value = float(digits) if seen_dot else int(digits)
        except ValueError:
            raise NovaError("this number has too many digits", start) from None
        return Token(TT_NUMBER, value, start)

    def read_identifier(self):
        """Read a name, then promote it if it is a keyword."""
        start = self.index
        name = ""
        while self.peek() is not None and is_name_char(self.peek()):
            name += self.advance()

        if name in KEYWORDS:
            return Token(KEYWORDS[name], name, start)
        return Token(TT_IDENT, name, start)

    def read_fstring(self):
        """Read f"text {expression} more", splitting it into parts.

        Text parts come back as ("text", value). A placeholder comes back as
        ("expr", source, offset) - the source is parsed later, and the offset
        lets error carets point back at the right column of the real line.
        Write {{ and }} for literal braces.
        """
        start = self.index
        self.advance()                                  # the 'f'
        quote = self.advance()
        parts = []
        text = ""

        while True:
            char = self.peek()
            if char is None or char in "\r\n":
                raise NovaError("this f-string is never closed", start)

            if char == quote:
                self.advance()
                break

            if char == "\\":
                self.advance()
                escape = self.peek()
                if escape is None:
                    raise NovaError("this f-string is never closed", start)
                self.advance()
                if escape not in ESCAPES:
                    raise NovaError("unknown escape '\\{}'".format(escape), self.index - 1)
                text += ESCAPES[escape]
                continue

            if char in "{}" and self.peek(1) == char:   # {{ and }} are literals
                self.advance()
                self.advance()
                text += char
                continue

            if char == "}":
                raise NovaError("a '}' inside an f-string must be written '}}'", self.index)

            if char == "{":
                if text:
                    parts.append(("text", text))
                    text = ""
                self.advance()
                parts.append(self.read_placeholder())
                continue

            self.advance()
            text += char

        if text:
            parts.append(("text", text))
        return Token(TT_FSTRING, parts, start)

    def read_placeholder(self):
        """Scan from just after '{' to its matching '}', quotes respected."""
        begin = self.index
        depth = 1
        inside = None                                   # the open quote, if any

        while True:
            char = self.peek()
            if char is None or char in "\r\n":
                raise NovaError("this f-string placeholder needs a closing '}'", begin)

            if inside is not None:
                if char == "\\":
                    self.advance()
                    if self.peek() is None:
                        raise NovaError("this f-string placeholder needs a closing '}'", begin)
                    self.advance()
                    continue
                if char == inside:
                    inside = None
                self.advance()
                continue

            if char in ('"', "'"):
                inside = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    break
            self.advance()

        source = self.source[begin:self.index]
        self.advance()                                  # the closing '}'
        if not source.strip():
            raise NovaError("this f-string placeholder is empty", begin)
        return ("expr", source, begin)

    def read_string(self):
        """Read "text" or 'text', honouring \\n, \\t and \\\" escapes."""
        start = self.index
        quote = self.advance()
        text = ""

        while True:
            char = self.peek()
            if char is None or char in "\r\n":
                raise NovaError("this string is never closed", start)
            self.advance()
            if char == quote:
                break
            if char == "\\":
                escape = self.peek()
                if escape is None:
                    raise NovaError("this string is never closed", start)
                self.advance()
                if escape not in ESCAPES:
                    raise NovaError("unknown escape '\\{}'".format(escape), self.index - 1)
                text += ESCAPES[escape]
                continue
            text += char

        return Token(TT_STRING, text, start)


# ---------------------------------------------------------------------------
# 2. AST nodes
# ---------------------------------------------------------------------------

class Node:
    """Base class; every node knows how to print itself."""

    def __repr__(self):
        fields = ", ".join(
            "{}={!r}".format(key, value)
            for key, value in vars(self).items()
            if key != "position"
        )
        return "{}({})".format(type(self).__name__, fields)


# -- expressions ------------------------------------------------------------

class NumberNode(Node):
    def __init__(self, value):
        self.value = value


class StringNode(Node):
    def __init__(self, value):
        self.value = value


class BooleanNode(Node):
    def __init__(self, value):
        self.value = value             # Python True / False


class VarNode(Node):
    def __init__(self, name, position):
        self.name = name
        self.position = position


class UnaryOpNode(Node):
    def __init__(self, op, operand, position):
        self.op = op                   # '+' or '-'
        self.operand = operand
        self.position = position


class NotNode(Node):
    def __init__(self, operand, position):
        self.operand = operand
        self.position = position


class BinOpNode(Node):
    def __init__(self, left, op, right, position):
        self.left = left
        self.op = op                   # '+', '-', '*', '/'
        self.right = right
        self.position = position


class CompareNode(Node):
    def __init__(self, left, op, right, position):
        self.left = left
        self.op = op                   # '<', '>', '<=', '>=', '==', '!='
        self.right = right
        self.position = position


class LogicalOpNode(Node):
    """`and` / `or`. Kept apart from BinOpNode because it short-circuits."""

    def __init__(self, left, op, right, position):
        self.left = left
        self.op = op                   # 'and' or 'or'
        self.right = right
        self.position = position


class ListNode(Node):
    def __init__(self, items, position):
        self.items = items             # list of expression nodes
        self.position = position


class IndexNode(Node):
    def __init__(self, target, index, position):
        self.target = target           # the expression being indexed
        self.index = index
        self.position = position


class DictEntryNode(Node):
    """One `key: value` pair inside a dictionary literal."""

    def __init__(self, key, value, position):
        self.key = key                 # a plain string, decided at parse time
        self.value = value
        self.position = position


class DictNode(Node):
    def __init__(self, entries, position):
        self.entries = entries         # list of DictEntryNode
        self.position = position


class MemberNode(Node):
    """`person.name` - the same lookup as person["name"], nicer to read."""

    def __init__(self, target, name, position):
        self.target = target
        self.name = name
        self.position = position


class SliceNode(Node):
    """`a[1:4]`, `a[2:]`, `a[:3]`, `a[:]` - either end may be missing."""

    def __init__(self, target, start, end, position):
        self.target = target
        self.start = start
        self.end = end
        self.position = position


class InterpolationNode(Node):
    """An f-string: a run of pieces whose values are joined into one string."""

    def __init__(self, parts, position):
        self.parts = parts             # StringNodes and expression nodes
        self.position = position


class CallNode(Node):
    def __init__(self, callee, args, position):
        self.callee = callee           # usually a VarNode
        self.args = args               # list of expression nodes
        self.position = position


# -- statements -------------------------------------------------------------

class AssignNode(Node):
    def __init__(self, name, value, position):
        self.name = name
        self.value = value
        self.position = position


class IndexAssignNode(Node):
    """`a[i] = value`"""

    def __init__(self, target, index, value, position):
        self.target = target
        self.index = index
        self.value = value
        self.position = position


class MemberAssignNode(Node):
    """`person.name = value`"""

    def __init__(self, target, name, value, position):
        self.target = target
        self.name = name
        self.value = value
        self.position = position


class DeleteNode(Node):
    """`delete person.city` or `delete person["city"]`"""

    def __init__(self, target, key, position):
        self.target = target
        self.key = key                 # an expression giving the key
        self.position = position


class TryNode(Node):
    """try { } catch e { } finally { } - catch and finally are both optional,
    but at least one of them has to be there."""

    def __init__(self, body, catch_name, catch_block, finally_block, position):
        self.body = body
        self.catch_name = catch_name    # the name bound to the message, or None
        self.catch_block = catch_block
        self.finally_block = finally_block
        self.position = position


class ThrowNode(Node):
    def __init__(self, value, position):
        self.value = value
        self.position = position


class DeleteFileNode(Node):
    """`delete("temp.txt")` - the parenthesised form of delete."""

    def __init__(self, path, position):
        self.path = path
        self.position = position


class ImportNode(Node):
    """`import "path.nova"`, optionally `as name` or `with a, b, ...`."""

    def __init__(self, path, alias, names, position):
        self.path = path        # the raw text as written, e.g. "./math.nova"
        self.alias = alias      # a name, or None
        self.names = names      # a list of names for 'with', or None
        self.position = position


class ExportNode(Node):
    """`export def f() { }` or `export let x = 1` - wraps the real statement."""

    def __init__(self, inner, position):
        self.inner = inner      # a FunctionDefNode or a LetNode
        self.position = position


class LetNode(Node):
    """`let x = value` - always binds in the current scope."""

    def __init__(self, name, value, position, type_name=None):
        self.name = name
        self.value = value
        self.position = position
        self.type_name = type_name     # TypeNode for `let x: int = ...`, else None


class TypeNode(Node):
    """A type annotation such as the `int` in `let x: int = 5`. Only the
    type checker (tools/nova-typecheck.py) reads these; the interpreter
    ignores them, so annotated code runs exactly as unannotated code does."""

    def __init__(self, name, position):
        self.name = name
        self.position = position


class BlockNode(Node):
    def __init__(self, statements, position):
        self.statements = statements
        self.position = position


class IfNode(Node):
    def __init__(self, condition, then_block, else_block, position):
        self.condition = condition
        self.then_block = then_block
        self.else_block = else_block   # BlockNode, IfNode (else if), or None
        self.position = position


class WhileNode(Node):
    def __init__(self, condition, body, else_block, position):
        self.condition = condition
        self.body = body
        self.else_block = else_block   # runs only if no `break` happened
        self.position = position


class ForNode(Node):
    def __init__(self, name, start, end, step, descending, body, else_block, position):
        self.name = name               # the loop variable
        self.start = start
        self.end = end
        self.step = step               # expression node, or None for 1
        self.descending = descending   # True for `downto`
        self.body = body
        self.else_block = else_block
        self.position = position


class ForInNode(Node):
    """`for x in <list> { ... }`"""

    def __init__(self, name, second_name, iterable, body, else_block, position):
        self.name = name
        self.second_name = second_name  # `for key, value in ...`, else None
        self.iterable = iterable
        self.body = body
        self.else_block = else_block
        self.position = position


class BreakNode(Node):
    def __init__(self, position):
        self.position = position


class ContinueNode(Node):
    def __init__(self, position):
        self.position = position


class FunctionDefNode(Node):
    def __init__(self, name, params, body, position, param_types=None, return_type=None):
        self.name = name
        self.params = params           # list of parameter names
        self.body = body               # BlockNode
        self.position = position
        # One TypeNode or None per parameter, and the `-> type`, if written.
        self.param_types = param_types if param_types is not None else [None] * len(params)
        self.return_type = return_type


class ReturnNode(Node):
    def __init__(self, value, position):
        self.value = value             # expression node, or None for bare return
        self.position = position


class ProgramNode(Node):
    def __init__(self, statements, annotated=False, imports=False):
        self.statements = statements
        self.annotated = annotated     # True if any type annotation appears
        self.imports = imports         # True if any `import` appears


# Statements that end in '}' and therefore need no separator after them.
BLOCK_STATEMENTS = (IfNode, WhileNode, ForNode, ForInNode, FunctionDefNode, TryNode)


# ---------------------------------------------------------------------------
# 3. Parser  (tokens -> AST), recursive descent
# ---------------------------------------------------------------------------
#
# The grammar, loosest first. Each rule is one method below.
#
#   program     := (statement SEP)* EOF
#   statement   := funcdef | returnstmt | ifstmt | whilestmt | forstmt
#                | 'break' | 'continue' | letstmt | exprstmt
#   letstmt     := 'let' IDENT '=' exprstmt
#   trystmt     := 'try' block ['catch' [IDENT] block] ['finally' block]
#   throwstmt   := 'throw' expression
#   importstmt  := 'import' STRING ['as' IDENT | 'with' IDENT (',' IDENT)*]
#   exportstmt  := 'export' (funcdef | letstmt)
#   exprstmt    := expression ['=' exprstmt]     (the left side must be a
#                  variable or a list element, checked after parsing)
#   funcdef     := 'def' IDENT '(' [IDENT (',' IDENT)*] ')' block
#   returnstmt  := 'return' [expression]
#   ifstmt      := 'if' expression block ['else' (block | ifstmt)]
#   whilestmt   := 'while' expression block ['else' block]
#   forstmt     := 'for' IDENT '=' expression ('to' | 'downto') expression
#                  ['step' expression] block ['else' block]
#                | 'for' IDENT [',' IDENT] 'in' expression block
#                  ['else' block]
#   delstmt     := 'delete' (expression '.' NAME | expression '[' expression ']')
#                | 'delete' '(' expression ')'          (removes a file)
#   block       := '{' (statement SEP)* '}'
#
#   expression  := or_expr
#   or_expr     := and_expr ('or' and_expr)*
#   and_expr    := not_expr ('and' not_expr)*
#   not_expr    := 'not' not_expr | comparison
#   comparison  := additive [('<'|'>'|'<='|'>='|'=='|'!='|'in') additive]
#   additive    := term (('+'|'-') term)*
#   term        := unary (('*'|'/'|'%'|'//') unary)*
#   unary       := ('+'|'-') unary | call
#   call        := primary ('(' [expression (',' expression)*] ')'
#                        | '[' expression ']'
#                        | '[' [expression] ':' [expression] ']'
#                        | '.' NAME)*
#   primary     := NUMBER | STRING | 'true' | 'false' | IDENT
#                | '[' [expression (',' expression)*] ']' | FSTRING
#                | '{' [NAME ':' expression (',' NAME ':' expression)*] '}'
#                | '(' expression ')'
#
# Precedence falls out of the nesting: `or` is looser than `and`, which is
# looser than `not`, which is looser than a comparison, which is looser than
# + and -, and so on down to calls. So
#
#     not done and i < 10 or i == 99
#
# groups as `((not done) and (i < 10)) or (i == 99)` with no parentheses.
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0
        self.annotated = False          # set by the first type annotation
        self.imports = False            # set by the first import

    # -- token helpers ------------------------------------------------------

    @property
    def current(self):
        return self.tokens[self.index]

    def peek(self, ahead=1):
        spot = min(self.index + ahead, len(self.tokens) - 1)
        return self.tokens[spot]

    def advance(self):
        token = self.tokens[self.index]
        if token.type != TT_EOF:
            self.index += 1
        return token

    def expect(self, type_, description):
        if self.current.type != type_:
            raise NovaError(
                "expected {}, found {}".format(description, describe(self.current)),
                self.current.position,
            )
        return self.advance()

    def skip_newlines(self):
        while self.current.type == TT_NEWLINE:
            self.advance()

    def end_statement(self, statement, closers):
        """After a statement we need a newline, a ';', or a closing token.

        A statement that already ends in '}' is self-terminating, so
        `if x { ... } return 5` on one line is fine.
        """
        target = statement.inner if isinstance(statement, ExportNode) else statement
        if isinstance(target, BLOCK_STATEMENTS):
            self.skip_newlines()
            return
        if self.current.type in closers:
            return
        if self.current.type == TT_NEWLINE:
            self.skip_newlines()
            return
        raise NovaError(
            "expected a new line between statements, found {}".format(describe(self.current)),
            self.current.position,
        )

    def optional_else(self):
        """An `else` may sit on the same line as the '}' or on the next one."""
        return self.optional_keyword(TT_ELSE)

    def optional_keyword(self, type_):
        """Accept a keyword that may follow a '}' on either line."""
        rewind = self.index
        self.skip_newlines()
        if self.current.type == type_:
            self.advance()
            return True
        self.index = rewind
        return False

    # -- rules --------------------------------------------------------------

    def parse(self):
        statements = []
        self.skip_newlines()
        while self.current.type != TT_EOF:
            statement = self.statement()
            statements.append(statement)
            self.end_statement(statement, (TT_EOF,))
            self.skip_newlines()
        return ProgramNode(statements, self.annotated, self.imports)

    def block(self):
        # The '{' may sit on the line after the header, so allow a break here.
        self.skip_newlines()
        opening = self.expect(TT_LBRACE, "a '{' to open the block")
        statements = []
        self.skip_newlines()
        while self.current.type not in (TT_RBRACE, TT_EOF):
            statement = self.statement()
            statements.append(statement)
            self.end_statement(statement, (TT_RBRACE, TT_EOF))
            self.skip_newlines()
        if self.current.type != TT_RBRACE:
            raise NovaError("this block is never closed with '}'", opening.position)
        self.advance()
        return BlockNode(statements, opening.position)

    def statement(self):
        token = self.current

        if token.type == TT_DEF:
            return self.function_def()
        if token.type == TT_RETURN:
            return self.return_statement()
        if token.type == TT_IF:
            return self.if_statement()
        if token.type == TT_WHILE:
            return self.while_statement()
        if token.type == TT_FOR:
            return self.for_statement()
        if token.type == TT_BREAK:
            self.advance()
            return BreakNode(token.position)
        if token.type == TT_CONTINUE:
            self.advance()
            return ContinueNode(token.position)
        if token.type == TT_LET:
            return self.let_statement()
        if token.type == TT_DELETE:
            return self.delete_statement()
        if token.type == TT_TRY:
            return self.try_statement()
        if token.type == TT_THROW:
            return self.throw_statement()
        if token.type == TT_IMPORT:
            return self.import_statement()
        if token.type == TT_EXPORT:
            return self.export_statement()
        return self.expression_statement()

    def function_def(self):
        keyword = self.advance()                        # 'def'
        name_token = self.expect(TT_IDENT, "a function name after 'def'")
        guard_name(name_token.value, name_token.position, "a function")

        self.expect(TT_LPAREN, "a '(' after the function name")
        params = []
        param_types = []
        if self.current.type != TT_RPAREN:
            while True:
                param = self.expect(TT_IDENT, "a parameter name")
                guard_name(param.value, param.position, "a parameter")
                if param.value in params:
                    raise NovaError(
                        "parameter {!r} is listed twice".format(param.value), param.position
                    )
                params.append(param.value)
                param_types.append(self.optional_annotation())
                if self.current.type != TT_COMMA:
                    break
                self.advance()
        self.expect(TT_RPAREN, "a ')' to close the parameter list")

        # `-> type`. There is no arrow token: '-' then '>' with nothing in
        # between, which cannot appear here any other way (a '{' must come
        # next), so neither lexer needed to change.
        return_type = None
        if (
            self.current.type == TT_MINUS
            and self.peek().type == TT_GT
            and self.peek().position == self.current.position + 1
        ):
            self.advance()
            self.advance()
            return_type = self.annotation()

        body = self.block()
        return FunctionDefNode(
            name_token.value, params, body, keyword.position, param_types, return_type
        )

    def optional_annotation(self):
        """`: type` after a name, or None if there is no ':'."""
        if self.current.type != TT_COLON:
            return None
        self.advance()
        return self.annotation()

    def annotation(self):
        """A type name. Which names are real types is the type checker's
        call, so that it can say what was probably meant."""
        token = self.expect(TT_IDENT, "a type name, such as int or string")
        self.annotated = True
        return TypeNode(token.value, token.position)

    def return_statement(self):
        keyword = self.advance()                        # 'return'
        # A bare `return` ends at a newline, a ';', a '}' or the end of input.
        if self.current.type in (TT_NEWLINE, TT_RBRACE, TT_EOF):
            return ReturnNode(None, keyword.position)
        return ReturnNode(self.expression(), keyword.position)

    def if_statement(self):
        keyword = self.advance()                        # 'if'
        condition = self.expression()
        then_block = self.block()

        if self.optional_else():
            if self.current.type == TT_IF:
                else_block = self.if_statement()        # else if ... chain
            else:
                else_block = self.block()
            return IfNode(condition, then_block, else_block, keyword.position)

        return IfNode(condition, then_block, None, keyword.position)

    def while_statement(self):
        keyword = self.advance()                        # 'while'
        condition = self.expression()
        body = self.block()
        else_block = self.block() if self.optional_else() else None
        return WhileNode(condition, body, else_block, keyword.position)

    def for_statement(self):
        keyword = self.advance()                        # 'for'
        name_token = self.expect(TT_IDENT, "a loop variable after 'for'")
        guard_name(name_token.value, name_token.position, "a loop variable")

        # `for x in <thing>` and `for key, value in <thing>` - the other
        # shape of the same keyword.
        second_name = None
        if self.current.type == TT_COMMA:
            self.advance()
            second = self.expect(TT_IDENT, "a second loop variable after the comma")
            guard_name(second.value, second.position, "a loop variable")
            if second.value == name_token.value:
                raise NovaError(
                    "both loop variables are called {!r}".format(second.value), second.position
                )
            second_name = second.value

        if self.current.type == TT_IN:
            self.advance()
            iterable = self.expression()
            body = self.block()
            else_block = self.block() if self.optional_else() else None
            return ForInNode(
                name_token.value, second_name, iterable, body, else_block, keyword.position
            )

        if second_name is not None:
            raise NovaError("expected 'in' after the loop variables", self.current.position)

        self.expect(TT_EQUALS, "a '=' or 'in' after the loop variable")

        start = self.expression()
        if self.current.type not in (TT_TO, TT_DOWNTO):
            raise NovaError(
                "expected 'to' or 'downto', found {}".format(describe(self.current)),
                self.current.position,
            )
        descending = self.advance().type == TT_DOWNTO
        end = self.expression()

        step = None
        if self.current.type == TT_STEP:
            self.advance()
            step = self.expression()

        body = self.block()
        else_block = self.block() if self.optional_else() else None
        return ForNode(
            name_token.value, start, end, step, descending, body, else_block, keyword.position
        )

    def let_statement(self):
        keyword = self.advance()                        # 'let'
        name_token = self.expect(TT_IDENT, "a name after 'let'")
        guard_name(name_token.value, name_token.position, "a variable")
        type_name = self.optional_annotation()
        self.expect(TT_EQUALS, "a '=' after the name in a 'let'")
        return LetNode(
            name_token.value, self.expression_statement(), keyword.position, type_name
        )

    def try_statement(self):
        keyword = self.advance()                        # 'try'
        body = self.block()

        catch_name = None
        catch_block = None
        if self.optional_keyword(TT_CATCH):
            if self.current.type == TT_IDENT:
                name = self.advance()
                guard_name(name.value, name.position, "a caught error")
                catch_name = name.value
            catch_block = self.block()

        finally_block = self.block() if self.optional_keyword(TT_FINALLY) else None

        if catch_block is None and finally_block is None:
            raise NovaError(
                "a 'try' needs a 'catch', a 'finally', or both", keyword.position
            )
        return TryNode(body, catch_name, catch_block, finally_block, keyword.position)

    def throw_statement(self):
        keyword = self.advance()                        # 'throw'
        if self.current.type in (TT_NEWLINE, TT_RBRACE, TT_EOF):
            raise NovaError("throw needs a message to throw", keyword.position)
        return ThrowNode(self.expression(), keyword.position)

    def import_statement(self):
        keyword = self.advance()                        # 'import'
        self.imports = True
        path_token = self.expect(TT_STRING, "a quoted module path after 'import'")

        alias = None
        names = None
        if self.current.type == TT_AS:
            self.advance()
            alias_token = self.expect(TT_IDENT, "a name after 'as'")
            guard_name(alias_token.value, alias_token.position, "a module alias")
            alias = alias_token.value
        elif self.current.type == TT_WITH:
            self.advance()
            names = []
            while True:
                name_token = self.expect(TT_IDENT, "a name to import")
                guard_name(name_token.value, name_token.position, "an imported name")
                if name_token.value in names:
                    raise NovaError(
                        "{!r} is imported twice".format(name_token.value), name_token.position
                    )
                names.append(name_token.value)
                if self.current.type != TT_COMMA:
                    break
                self.advance()

        return ImportNode(path_token.value, alias, names, keyword.position)

    def export_statement(self):
        keyword = self.advance()                        # 'export'
        if self.current.type == TT_DEF:
            inner = self.function_def()
        elif self.current.type == TT_LET:
            inner = self.let_statement()
        else:
            raise NovaError(
                "'export' must be followed by 'def' or 'let', found {}".format(
                    describe(self.current)
                ),
                keyword.position,
            )
        return ExportNode(inner, keyword.position)

    def delete_statement(self):
        keyword = self.advance()                        # 'delete'

        # `delete(path)` looks like a call and removes a file; `delete d.key`
        # removes a dictionary entry. The '(' is what tells them apart, so
        # `delete(files[0])` deletes the named file rather than the entry.
        if self.current.type == TT_LPAREN:
            self.advance()
            path = self.expression()
            self.expect(TT_RPAREN, "a ')' after the file name")
            return DeleteFileNode(path, keyword.position)

        target = self.expression()
        if isinstance(target, MemberNode):
            return DeleteNode(target.target, StringNode(target.name), keyword.position)
        if isinstance(target, IndexNode):
            return DeleteNode(target.target, target.index, keyword.position)
        raise NovaError(
            "delete needs a dictionary entry, as in `delete d.key` or `delete d[\"key\"]`, "
            "or a file, as in `delete(\"temp.txt\")`",
            keyword.position,
        )

    def expression_statement(self):
        """An expression - or an assignment, if a '=' follows it.

        Parsing the left side as a full expression first is what makes both
        `x = 1` and `a[i] = 1` work with one rule: whatever comes back simply
        has to be something we can assign into.
        """
        node = self.expression()
        if self.current.type != TT_EQUALS:
            return node

        equals = self.advance()
        value = self.expression_statement()             # right-assoc: a = b = 3

        if isinstance(node, VarNode):
            guard_name(node.name, node.position, "a variable")
            return AssignNode(node.name, value, node.position)
        if isinstance(node, IndexNode):
            return IndexAssignNode(node.target, node.index, value, node.position)
        if isinstance(node, MemberNode):
            return MemberAssignNode(node.target, node.name, value, node.position)
        raise NovaError(
            "the left side of '=' must be a variable, a list item or a field",
            equals.position,
        )

    def expression(self):
        return self.or_expression()

    def or_expression(self):
        node = self.and_expression()
        while self.current.type == TT_OR:
            op_token = self.advance()
            node = LogicalOpNode(node, "or", self.and_expression(), op_token.position)
        return node

    def and_expression(self):
        node = self.not_expression()
        while self.current.type == TT_AND:
            op_token = self.advance()
            node = LogicalOpNode(node, "and", self.not_expression(), op_token.position)
        return node

    def not_expression(self):
        if self.current.type == TT_NOT:
            op_token = self.advance()
            return NotNode(self.not_expression(), op_token.position)
        return self.comparison()

    def comparison(self):
        node = self.additive()
        if self.current.type in COMPARISON_TOKENS:
            op_token = self.advance()
            right = self.additive()
            node = CompareNode(node, op_token.value, right, op_token.position)
            if self.current.type in COMPARISON_TOKENS:
                raise NovaError(
                    "chained comparisons like 'a < b < c' are not supported yet",
                    self.current.position,
                )
        return node

    def additive(self):
        node = self.term()
        while self.current.type in (TT_PLUS, TT_MINUS):
            op_token = self.advance()
            node = BinOpNode(node, op_token.value, self.term(), op_token.position)
        return node

    def term(self):
        node = self.unary()
        while self.current.type in (TT_STAR, TT_SLASH, TT_PERCENT, TT_DSLASH):
            op_token = self.advance()
            node = BinOpNode(node, op_token.value, self.unary(), op_token.position)
        return node

    def unary(self):
        if self.current.type in (TT_PLUS, TT_MINUS):
            op_token = self.advance()
            return UnaryOpNode(op_token.value, self.unary(), op_token.position)
        return self.call()

    def call(self):
        node = self.primary()
        while True:
            if self.current.type == TT_LPAREN:
                paren = self.advance()
                args = []
                if self.current.type != TT_RPAREN:
                    while True:
                        args.append(self.expression())
                        if self.current.type != TT_COMMA:
                            break
                        self.advance()
                self.expect(TT_RPAREN, "a ')' to close the argument list")
                node = CallNode(node, args, paren.position)
            elif self.current.type == TT_LBRACKET:
                bracket = self.advance()
                node = self.index_or_slice(node, bracket)
            elif self.current.type == TT_DOT:
                dot = self.advance()
                name = self.name_token("a field name after '.'")
                node = MemberNode(node, name.value, dot.position)
            else:
                return node

    def name_token(self, what, allow_string=False):
        """A field or key name: an identifier, a keyword, or a quoted string."""
        token = self.current
        if token.type == TT_IDENT or token.type in KEYWORD_TOKEN_TYPES:
            self.advance()
            return token
        if allow_string and token.type == TT_STRING:
            self.advance()
            return token
        raise NovaError(
            "expected {}, found {}".format(what, describe(token)), token.position
        )

    def dict_literal(self, brace):
        """Just past a '{' in expression position."""
        entries = []
        seen = set()
        self.skip_newlines()

        if self.current.type != TT_RBRACE:
            while True:
                key = self.name_token("a key name", allow_string=True)
                if key.value in seen:
                    raise NovaError(
                        "the key {!r} appears twice in this dictionary".format(key.value),
                        key.position,
                    )
                seen.add(key.value)
                self.expect(TT_COLON, "a ':' after the key")
                entries.append(DictEntryNode(key.value, self.expression(), key.position))
                self.skip_newlines()
                if self.current.type != TT_COMMA:
                    break
                self.advance()
                self.skip_newlines()

        self.expect(TT_RBRACE, "a '}' to close the dictionary")
        return DictNode(entries, brace.position)

    def index_or_slice(self, node, bracket):
        """Just past a '[': either `a[i]` or a slice such as `a[1:4]`."""
        start = None
        if self.current.type not in (TT_COLON, TT_RBRACKET):
            start = self.expression()

        if self.current.type == TT_COLON:
            self.advance()
            end = None
            if self.current.type != TT_RBRACKET:
                end = self.expression()
            self.expect(TT_RBRACKET, "a ']' to close the slice")
            return SliceNode(node, start, end, bracket.position)

        if start is None:
            raise NovaError("an index cannot be empty", bracket.position)
        self.expect(TT_RBRACKET, "a ']' to close the index")
        return IndexNode(node, start, bracket.position)

    def interpolation(self, token):
        """Turn the lexer's f-string parts into nodes, parsing each hole."""
        parts = []
        for part in token.value:
            if part[0] == "text":
                parts.append(StringNode(part[1]))
                continue

            _, source, offset = part
            inner_tokens = Lexer(source).tokenize()
            for inner_token in inner_tokens:            # point at the real line
                inner_token.position += offset
            inner = Parser(inner_tokens)
            parts.append(inner.expression())
            if inner.current.type != TT_EOF:
                raise NovaError(
                    "unexpected {} inside this f-string".format(describe(inner.current)),
                    inner.current.position,
                )
        return InterpolationNode(parts, token.position)

    def primary(self):
        token = self.current

        if token.type == TT_NUMBER:
            self.advance()
            return NumberNode(token.value)

        if token.type == TT_STRING:
            self.advance()
            return StringNode(token.value)

        if token.type == TT_FSTRING:
            self.advance()
            return self.interpolation(token)

        if token.type == TT_TRUE:
            self.advance()
            return BooleanNode(True)

        if token.type == TT_FALSE:
            self.advance()
            return BooleanNode(False)

        if token.type == TT_IDENT:
            self.advance()
            return VarNode(token.value, token.position)

        if token.type == TT_LBRACKET:
            self.advance()
            items = []
            self.skip_newlines()                        # lists may span lines
            if self.current.type != TT_RBRACKET:
                while True:
                    items.append(self.expression())
                    self.skip_newlines()
                    if self.current.type != TT_COMMA:
                        break
                    self.advance()
                    self.skip_newlines()
            self.expect(TT_RBRACKET, "a ']' to close the list")
            return ListNode(items, token.position)

        # A '{' here can only be a dictionary: blocks are read by block(),
        # and '{' is never an infix operator, so `if x { ... }` still ends
        # its condition at the brace.
        if token.type == TT_LBRACE:
            self.advance()
            return self.dict_literal(token)

        if token.type == TT_LPAREN:
            self.advance()
            node = self.expression()
            self.expect(TT_RPAREN, "a closing ')'")
            return node

        if token.type in (TT_EOF, TT_NEWLINE):
            raise NovaError("the expression ends too early", token.position)

        raise NovaError("unexpected {}".format(describe(token)), token.position)


def describe(token):
    """Human-readable name for a token, used in parser error messages."""
    if token.type == TT_EOF:
        return "the end of the input"
    if token.type == TT_NEWLINE:
        return "the end of the line"
    if token.type == TT_STRING:
        return "the string {!r}".format(token.value)
    if token.type == TT_FSTRING:
        return "an f-string"
    if token.type == TT_NUMBER and isinstance(token.value, float):
        # A number written with a point always shows one ([err.syntax]).
        finite = token.value - token.value == 0
        return float_text(token.value) if finite else format_float(token.value)
    return "{!r}".format(token.value)


# ---------------------------------------------------------------------------
# Runtime values
# ---------------------------------------------------------------------------

class Nothing:
    """The value of a function that never returned anything."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self):
        return "nothing"


NOTHING = Nothing()


class NovaFunction:
    """A function written in NovaLang. The tree-walker's carry their `body`
    and defining scope (`closure`); the VM's carry compiled `code`, the
    `cells` they close over and their module's `globals`."""

    code = None
    cells = ()
    globals = None

    def __init__(self, name, params, body, closure):
        self.name = name
        self.params = params
        self.body = body
        self.closure = closure          # the scope the def was written in

    def __repr__(self):
        return "<function {}({})>".format(self.name, ", ".join(self.params))


class BuiltinFunction:
    """A function written in Python and exposed to NovaLang, such as print."""

    def __init__(self, name, arity, implementation, needs_interpreter=False, paths=()):
        self.name = name
        # (argument index, "read" | "write") for each argument that is a file path: a
        # `restricted` engine checks it against its grants before the call
        # (docs/spec/16-sandbox.md [sbx.paths]).
        self.paths = paths
        self.arity = arity              # an int, or None for "any number"
        self.implementation = implementation
        # map/filter/reduce call back into a NovaLang function value passed
        # as an argument, which only the interpreter can do; every other
        # built-in is a plain function of (args, position).
        self.needs_interpreter = needs_interpreter

    def __repr__(self):
        return "<built-in function {}>".format(self.name)


# Lists longer than this are refused, so a typo in range() or a list
# repetition cannot eat all the memory in the machine.
MAX_LIST_LENGTH = 1000000

# The language's own bound on an integer ([port.integers]): at most 4000
# decimal digits, whatever Python release is underneath. Python's own limit on
# turning text into an integer (4300 digits, and absent from older releases)
# is therefore never reached, and every host agrees on where programs stop.
MAX_INTEGER_DIGITS = 4000
INTEGER_LIMIT = 10 ** MAX_INTEGER_DIGITS        # an integer is below this in size
# 2 ** INTEGER_BITS is already beyond INTEGER_LIMIT; pow() uses it to refuse a
# power before computing it.
INTEGER_BITS = 13288


def too_many_digits_error(position):
    return NovaError(
        "the result has too many digits - an integer cannot have more than {} digits".format(
            MAX_INTEGER_DIGITS),
        position,
    )


def bounded_integer(value, position):
    """`value` if it is within the language's integer bound, else the error."""
    if type(value) is int and not -INTEGER_LIMIT < value < INTEGER_LIMIT:
        raise too_many_digits_error(position)
    return value


def builtin_print(args, position, interpreter):
    interpreter.write_output(" ".join(format_value(arg) for arg in args), None, position)
    return NOTHING


def builtin_len(args, position):
    value = args[0]
    if isinstance(value, (list, str, dict)):
        return len(value)
    raise NovaError(
        "len() needs a list, a string or a dictionary, but got {}".format(type_name(value)),
        position,
    )


def dict_argument(value, who, position):
    if not isinstance(value, dict):
        raise NovaError(
            "{} needs a dictionary, but got {}".format(who, type_name(value)), position
        )
    return value


def builtin_keys(args, position):
    return list(dict_argument(args[0], "keys()", position))


def builtin_values(args, position):
    return list(dict_argument(args[0], "values()", position).values())


def builtin_append(args, position):
    """append(list, value) grows a list; append(path, text) grows a file."""
    target, value = args

    if isinstance(target, str):
        text = text_argument(value, "the text appended to a file", position)
        with open_file(target, "a", position) as handle:
            handle.write(text)
        return NOTHING

    if not isinstance(target, list):
        raise NovaError(
            "append() needs a list or a file name as its first argument, but got {}".format(
                type_name(target)
            ),
            position,
        )
    if len(target) >= MAX_LIST_LENGTH:
        raise NovaError("a list cannot grow beyond {} items".format(MAX_LIST_LENGTH), position)
    target.append(value)
    return target


def open_file(path, mode, position):
    """Open a file, turning the operating system's complaint into a NovaError."""
    if os.path.isdir(path):
        # Asked first, because Linux and Windows word this refusal differently
        # (a PermissionError on Windows) and the message is part of the language.
        raise NovaError("{} is a directory, not a file".format(path), position,
                        label="FileError")
    try:
        # Written text is never translated: a line feed is one byte on every
        # platform (open() would write the platform's line end on Windows).
        return open(path, mode, encoding="utf-8", newline="" if mode != "r" else None)
    except FileNotFoundError:
        raise NovaError(path, position, label="FileNotFoundError")
    except IsADirectoryError:
        raise NovaError("{} is a directory, not a file".format(path), position,
                        label="FileError")
    except OSError as problem:
        raise NovaError(
            "{}: {}".format(path, problem.strerror or "cannot be opened"), position,
            label="FileError",
        )


def builtin_read(args, position):
    path = text_argument(args[0], "read()", position)
    with open_file(path, "r", position) as handle:
        try:
            return handle.read()
        except (OSError, UnicodeDecodeError) as problem:
            raise NovaError(
                "{}: {}".format(path, problem), position, label="FileError"
            )


def builtin_write(args, position):
    path = text_argument(args[0], "the file name for write()", position)
    text = text_argument(args[1], "the text for write()", position)
    with open_file(path, "w", position) as handle:
        handle.write(text)
    return NOTHING


def builtin_exists(args, position):
    return os.path.exists(text_argument(args[0], "exists()", position))


def builtin_abspath(args, position):
    # Path canonicalization for novalang.nova's own module resolver
    # (Stage 10, self-hosting) - the same job Python's os.path already does
    # for the host's own import machinery, exposed so the self-hosted
    # implementation does not have to reinvent it by hand.
    return os.path.abspath(text_argument(args[0], "abspath()", position))


def builtin_realpath(args, position):
    # abspath() with every symbolic link followed: what a path really names. The
    # self-hosted interpreter checks a program's paths against its grants with it
    # (docs/spec/10-host.md [host.files], docs/spec/16-sandbox.md [sbx.paths]).
    return os.path.realpath(text_argument(args[0], "realpath()", position))


def builtin_dirname(args, position):
    return os.path.dirname(text_argument(args[0], "dirname()", position))


def builtin_listdir(args, position):
    path = text_argument(args[0], "listdir()", position)
    if os.path.isfile(path):
        raise NovaError("{} is a file, not a directory".format(path), position,
                        label="FileError")
    try:
        return sorted(os.listdir(path))             # sorted, so runs match
    except FileNotFoundError:
        raise NovaError(path, position, label="FileNotFoundError")
    except NotADirectoryError:
        raise NovaError("{} is a file, not a directory".format(path), position,
                        label="FileError")
    except OSError as problem:
        raise NovaError(
            "{}: {}".format(path, problem.strerror or "cannot be listed"), position,
            label="FileError",
        )


def builtin_input(args, position, interpreter):
    interpreter.check_time(position)
    if len(args) > 1:
        raise NovaError("input() takes an optional prompt and nothing else", position)
    prompt = text_argument(args[0], "input()", position) if args else ""
    try:
        return input(prompt)
    except EOFError:
        raise NovaError("input() found no more input to read", position)


def builtin_pop(args, position):
    if not 1 <= len(args) <= 2:
        raise NovaError("pop() takes a list and an optional index", position)
    target = args[0]
    if not isinstance(target, list):
        raise NovaError(
            "pop() needs a list as its first argument, but got {}".format(type_name(target)),
            position,
        )
    if not target:
        raise NovaError("pop() cannot take anything from an empty list", position)
    spot = len(target) - 1 if len(args) == 1 else normalize_index(target, args[1], position)
    return target.pop(spot)


def builtin_range(args, position):
    if not 1 <= len(args) <= 3:
        raise NovaError("range() takes 1, 2 or 3 numbers", position)
    numbers = [whole_number(arg, "range()", position) for arg in args]

    if len(numbers) == 1:
        start, end, step = 0, numbers[0], 1
    elif len(numbers) == 2:
        start, end, step = numbers[0], numbers[1], 1
    else:
        start, end, step = numbers

    if step == 0:
        raise NovaError("range() cannot step by zero", position)

    span = (end - start) if step > 0 else (start - end)
    count = 0 if span <= 0 else (span - 1) // abs(step) + 1
    if count > MAX_LIST_LENGTH:
        raise NovaError(
            "range() would build a list of {} items, which is too large".format(count), position
        )
    return [start + index * step for index in range(count)]


def range_count(args, position):
    """How many items range(*args) would make, or None when range() itself is about to refuse its
    arguments (it reports that error in its own words)."""
    try:
        numbers = [whole_number(arg, "range()", position) for arg in args]
    except NovaError:
        return None
    start, end, step = (0, numbers[0], 1) if len(numbers) == 1 else (
        (numbers[0], numbers[1], 1) if len(numbers) == 2 else tuple(numbers))
    if step == 0:
        return None
    span = (end - start) if step > 0 else (start - end)
    return 0 if span <= 0 else (span - 1) // abs(step) + 1


def text_would_exceed(values, limit):
    """Does the display text of `values` certainly have more than `limit` characters? A lower bound
    that stops the moment it passes the limit, so a structure that shares its parts with itself
    (`l = [l, l]` forty times, whose text would have 2**40 items) is refused after `limit` steps and
    never turned into text ([sbx.limits], string.text)."""
    remaining = limit
    stack = [(value, frozenset()) for value in values]
    while stack:
        value, inside = stack.pop()
        if isinstance(value, str):
            remaining -= len(value)
        elif isinstance(value, (list, dict)):
            if id(value) in inside:
                remaining -= 5                      # [...] or {...}
            else:
                items = value if isinstance(value, list) else [x for pair in value.items() for x in pair]
                remaining -= 2 + max(len(value) - 1, 0) * 2
                inside = inside | {id(value)}
                stack.extend((item, inside) for item in items)
        else:
            remaining -= 1                          # a number, a boolean or nothing: one character at least
        if remaining < 0:
            return True
    return False


# The whitespace trim(), split() and num() skip: ASCII only ([lib.text]). What
# Python calls whitespace includes no-break space, the Unicode spaces and the
# information separators, which would make a text mean different things on
# hosts with different tables (D-020).
ASCII_WHITESPACE = " \t\n\r\x0b\x0c"
ASCII_WHITESPACE_RUNS = re.compile("[" + ASCII_WHITESPACE + "]+")
LINE_ENDS = re.compile("\r\n|\r|\n")


def text_argument(value, who, position):
    """Most of the string built-ins take exactly one string."""
    if not isinstance(value, str):
        raise NovaError("{} needs a string, but got {}".format(who, type_name(value)), position)
    return value


def builtin_upper(args, position):
    return text_argument(args[0], "upper()", position).upper()


def builtin_lower(args, position):
    return text_argument(args[0], "lower()", position).lower()


def builtin_trim(args, position):
    return text_argument(args[0], "trim()", position).strip(ASCII_WHITESPACE)


def builtin_split(args, position):
    if not 1 <= len(args) <= 2:
        raise NovaError("split() takes a string and an optional separator", position)
    text = text_argument(args[0], "split()", position)
    if len(args) == 1:
        return [piece for piece in ASCII_WHITESPACE_RUNS.split(text) if piece]
    separator = text_argument(args[1], "the separator of split()", position)
    if separator == "":
        raise NovaError("split() cannot use an empty separator", position)
    return text.split(separator)


def builtin_join(args, position):
    items, separator = args
    if not isinstance(items, list):
        raise NovaError(
            "join() needs a list as its first argument, but got {}".format(type_name(items)),
            position,
        )
    separator = text_argument(separator, "the separator of join()", position)
    return separator.join(format_value(item) for item in items)


def builtin_str(args, position):
    return format_value(args[0])


def builtin_num(args, position):
    value = args[0]
    if is_number(value):
        return value
    if not isinstance(value, str):
        raise NovaError("num() needs a string, but got {}".format(type_name(value)), position)

    text = value.strip(ASCII_WHITESPACE)
    digits = text[1:] if text[:1] in ("+", "-") else text
    readable = (
        digits
        and digits.count(".") <= 1
        and any(is_digit(char) for char in digits)
        and all(is_digit(char) or char == "." for char in digits)
    )
    if not readable:
        raise NovaError('num() cannot read a number from "{}"'.format(value), position)
    if len(digits) - digits.count(".") > MAX_INTEGER_DIGITS:
        raise NovaError("num(): that number has too many digits", position)
    try:
        return float(text) if "." in digits else int(text)
    except ValueError:
        raise NovaError("num(): that number has too many digits", position) from None


def builtin_type(args, position):
    return type_category(args[0])


# ---------------------------------------------------------------------------
# Stage 11: standard library
# ---------------------------------------------------------------------------
#
# Every function here is global, with no import needed. Each type-checks
# its own arguments and raises a NovaError labelled "TypeError" for a bad
# one, so `catch e` sees e.g. "TypeError: sqrt() needs a number, but got
# a string" - consistent with FileNotFoundError/FileError from Stage 7.

SCRIPT_ARGS = []            # set by main()/run_source(): argv after the file


def numeric_argument(value, who, position):
    if not is_number(value):
        raise NovaError(
            "{} needs a number, but got {}".format(who, type_name(value)), position, label="TypeError"
        )
    return value


def finite_argument(value, who, position):
    """A number that Python can turn into a whole number or hand to the clock.
    NaN and infinity are numbers (they come from json.loads, from num() of a
    very long decimal string and from float overflow), but math.floor, time.sleep
    and the like answer them with a raw Python ValueError or OverflowError, which
    try/catch cannot intercept. Refuse them as sqrt(-1) is refused."""
    if isinstance(value, float) and not math.isfinite(value):
        raise NovaError("{} needs a finite number, but got {}".format(who, format_value(value)),
                        position, label="TypeError")
    return value


def list_argument(value, who, position):
    if not isinstance(value, list):
        raise NovaError(
            "{} needs a list, but got {}".format(who, type_name(value)), position, label="TypeError"
        )
    return value


# ---- time -----------------------------------------------------------------

def builtin_time(args, position, interpreter):
    return interpreter.det.time() if interpreter.det else time.time()


def builtin_sleep(args, position, interpreter):
    ms = finite_argument(numeric_argument(args[0], "sleep()", position), "sleep()", position)
    if ms < 0:
        raise NovaError("sleep() cannot pause for a negative time", position, label="TypeError")
    if interpreter.det:
        interpreter.det.elapsed += ms / 1000.0          # virtual time passes; nobody waits
        return NOTHING
    interpreter.check_time(position, extra_ms=ms)       # a sleep that would pass the limit does not start
    time.sleep(ms / 1000.0)
    return NOTHING


def builtin_monotonic(args, position, interpreter):
    # Seconds on a clock that never goes backwards, from an arbitrary start: for measuring how long
    # something took (docs/spec/10-host.md [host.time]).
    return interpreter.det.elapsed if interpreter.det else time.monotonic()


def builtin_now(args, position, interpreter):
    if interpreter.det:
        return deterministic_iso(interpreter.det.time(), position)
    return datetime.now(timezone.utc).isoformat()


def builtin_format_time(args, position, interpreter):
    timestamp, fmt = args
    timestamp = numeric_argument(timestamp, "format_time()", position)
    fmt = text_argument(fmt, "the format for format_time()", position)
    if interpreter.det:
        return deterministic_format(timestamp, fmt, position)
    try:
        return datetime.fromtimestamp(timestamp).strftime(fmt)
    except (ValueError, OSError, OverflowError) as problem:
        raise NovaError("format_time(): {}".format(problem), position, label="TypeError")


# ---- random -----------------------------------------------------------------

def builtin_random(args, position, interpreter):
    if interpreter.det:
        return interpreter.det.next53() / 9007199254740992        # 2**53, exact
    return random.random()


def builtin_randint(args, position, interpreter):
    low = whole_number(args[0], "randint()", position)
    high = whole_number(args[1], "randint()", position)
    if low > high:
        raise NovaError(
            "randint() needs its first argument no greater than its second", position, label="TypeError"
        )
    if interpreter.det:
        return low + interpreter.det.below(high - low + 1)
    return random.randint(low, high)


def builtin_choice(args, position, interpreter):
    target = list_argument(args[0], "choice()", position)
    if not target:
        raise NovaError("choice() cannot pick from an empty list", position)
    if interpreter.det:
        return target[interpreter.det.below(len(target))]
    return random.choice(target)


def builtin_shuffle(args, position, interpreter):
    target = list_argument(args[0], "shuffle()", position)
    if interpreter.det:
        for i in range(len(target) - 1, 0, -1):             # Fisher-Yates from the end
            j = interpreter.det.below(i + 1)
            target[i], target[j] = target[j], target[i]
        return target
    random.shuffle(target)
    return target


# ---- math -----------------------------------------------------------------

def builtin_abs(args, position):
    return abs(numeric_argument(args[0], "abs()", position))


def builtin_round(args, position):
    if not 1 <= len(args) <= 2:
        raise NovaError("round() takes a number and an optional digit count", position)
    value = numeric_argument(args[0], "round()", position)
    if len(args) == 1:
        return round(finite_argument(value, "round()", position))
    # With a digit count Python returns NaN and infinity unchanged and raises
    # nothing, so that path is left as it was.
    return round(value, whole_number(args[1], "round()", position))


def builtin_floor(args, position):
    return math.floor(finite_argument(numeric_argument(args[0], "floor()", position), "floor()", position))


def builtin_ceil(args, position):
    return math.ceil(finite_argument(numeric_argument(args[0], "ceil()", position), "ceil()", position))


def builtin_sqrt(args, position):
    value = numeric_argument(args[0], "sqrt()", position)
    if value < 0:
        raise NovaError("sqrt() needs a number that is not negative", position, label="TypeError")
    return math.sqrt(value)


def builtin_pow(args, position):
    base = numeric_argument(args[0], "pow()", position)
    exponent = numeric_argument(args[1], "pow()", position)
    if (type(base) is int and type(exponent) is int and exponent > 0 and abs(base) > 1
            and (abs(base).bit_length() - 1) * exponent > INTEGER_BITS):
        raise too_many_digits_error(position)       # refused before it is computed
    try:
        result = base ** exponent
    except (ValueError, OverflowError, ZeroDivisionError) as problem:
        raise NovaError("pow(): {}".format(problem), position, label="TypeError")
    if isinstance(result, complex):
        raise NovaError(
            "pow() produced a complex result, which NovaLang cannot represent", position, label="TypeError"
        )
    return result


def _not_infinite(value, who, position):
    """sin, cos and tan return NaN for NaN without complaint; only infinity
    makes Python raise, so only infinity is refused."""
    if isinstance(value, float) and math.isinf(value):
        raise NovaError("{} needs a finite number, but got {}".format(who, format_value(value)),
                        position, label="TypeError")
    return value


def builtin_sin(args, position):
    return math.sin(_not_infinite(numeric_argument(args[0], "sin()", position), "sin()", position))


def builtin_cos(args, position):
    return math.cos(_not_infinite(numeric_argument(args[0], "cos()", position), "cos()", position))


def builtin_tan(args, position):
    return math.tan(_not_infinite(numeric_argument(args[0], "tan()", position), "tan()", position))


def builtin_ln(args, position):
    value = numeric_argument(args[0], "ln()", position)
    if value <= 0:
        raise NovaError("ln() needs a number greater than zero", position, label="TypeError")
    return math.log(value)


def builtin_log10(args, position):
    value = numeric_argument(args[0], "log10()", position)
    if value <= 0:
        raise NovaError("log10() needs a number greater than zero", position, label="TypeError")
    return math.log10(value)


def numbers_from_args(args, who, position):
    """min/max/sum take either several numbers, or one list of numbers."""
    items = args[0] if len(args) == 1 and isinstance(args[0], list) else list(args)
    if not items:
        raise NovaError("{} needs at least one number".format(who), position, label="TypeError")
    for item in items:
        numeric_argument(item, who, position)
    return items


def builtin_min(args, position):
    return min(numbers_from_args(args, "min()", position))


def builtin_max(args, position):
    return max(numbers_from_args(args, "max()", position))


def builtin_sum(args, position):
    total = 0
    for item in numbers_from_args(args, "sum()", position):
        total = total + item
    return total


# ---- system -----------------------------------------------------------------

def builtin_env(args, position, interpreter):
    name = text_argument(args[0], "env()", position)
    if not interpreter.caps.env_visible(name):
        return NOTHING                      # a hidden variable reads as an unset one ([sbx.capabilities])
    value = os.environ.get(name)
    return NOTHING if value is None else value


def builtin_exit(args, position, interpreter):
    if len(args) > 1:
        raise NovaError("exit() takes an optional status code and nothing else", position)
    code = whole_number(args[0], "exit()", position) if args else 0
    if interpreter.caps.restricted:
        raise ProgramExit(code)
    sys.exit(code)


def builtin_args(args, position):
    return list(SCRIPT_ARGS)


def builtin_platform(args, position):
    return platform.system()


# ---- json -----------------------------------------------------------------

def to_jsonable(value, position):
    if value is NOTHING:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        raise NovaError("json.dumps() cannot represent NaN or infinity", position, label="TypeError")
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [to_jsonable(item, position) for item in value]
    if isinstance(value, dict):
        return {key: to_jsonable(item, position) for key, item in value.items()}
    raise NovaError(
        "json.dumps() cannot represent {}".format(type_name(value)), position, label="TypeError"
    )


def from_jsonable(value):
    if value is None:
        return NOTHING
    if isinstance(value, list):
        return [from_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: from_jsonable(item) for key, item in value.items()}
    return value


def builtin_json_dumps(args, position):
    return json_module.dumps(to_jsonable(args[0], position))


def builtin_json_loads(args, position):
    text = text_argument(args[0], "json.loads()", position)
    def read_integer(digits):
        if len(digits.lstrip("-")) > MAX_INTEGER_DIGITS:
            raise NovaError("json.loads(): that number has too many digits", position,
                            label="TypeError")
        return int(digits)

    def read_float(digits):
        value = float(digits)
        if not math.isfinite(value):
            raise NovaError("json.loads(): that number is too large", position, label="TypeError")
        return value

    def refuse_constant(name):
        raise NovaError("json.loads(): {} is not valid JSON".format(name), position,
                        label="TypeError")

    try:
        return from_jsonable(json_module.loads(text, parse_int=read_integer, parse_float=read_float,
                                               parse_constant=refuse_constant))
    except json_module.JSONDecodeError as problem:
        raise NovaError("json.loads(): {}".format(problem), position, label="TypeError")


def builtin_json_pretty(args, position):
    return json_module.dumps(to_jsonable(args[0], position), indent=2)


# ---------------------------------------------------------------------------
# Stage 12: embedding - a NovaLang-side bridge back into Python
# ---------------------------------------------------------------------------
#
# `python.*` is deliberately NOT unrestricted access to the process: a
# NovaLang script - which may be a level script, a mod, config logic
# someone else wrote - can only reach what the embedding Python program
# chose to hand it (Nova.expose/expose_module), plus a short allowlist of
# pure-computation stdlib modules with no file, process or network access.
# Anything else python.import() refuses, by design.

PYTHON_IMPORT_ALLOWLIST = (
    "math", "random", "statistics", "itertools", "functools",
    "string", "re", "datetime", "json", "collections",
)


_MISSING = object()


def python_granted(module, interpreter):
    """Is `module` one a script may be handed? Its exact name must be on
    PYTHON_IMPORT_ALLOWLIST, as python.import() requires, or the embedding
    program must have exposed that module (Nova.expose_module/expose/
    expose_global). Submodules are not granted along with their package: a
    host that wants `os.path` exposes it, as it exposes `os`. Any other module
    is a way round the allowlist: `re.enum.bltns` is the builtins module,
    `json.codecs` reaches builtins and sys, `statistics.sys` is sys."""
    name = getattr(module, "__name__", "")
    if name in (interpreter.python_allowlist() if interpreter is not None else PYTHON_IMPORT_ALLOWLIST):
        return True
    return interpreter is not None and name in interpreter.python_granted


def bridge_lookup(owner, name, interpreter):
    """The one gate every python.* access goes through (docs/design/
    python-bridge-hardening.md, D1). Returns the attribute, or _MISSING
    when a script may not see it: a name that starts with "_", an attribute
    that does not exist, or one whose value is a module that is not
    granted. A hidden name looks exactly like an absent one."""
    if not isinstance(name, str) or name.startswith("_"):
        return _MISSING
    try:
        value = getattr(owner, name)
    except AttributeError:
        return _MISSING
    if isinstance(value, ModuleType) and not python_granted(value, interpreter):
        return _MISSING
    return value


_NOT_WRITABLE = ((ModuleType, "module"), (type, "class"),
                 ((FunctionType, BuiltinFunctionType, MethodType), "function"))


def bridge_write_check(owner, name, interpreter, position=None):
    """Writes are narrower than reads. A script may set attributes only on
    an object instance the host handed it, never on a module, a class or a
    function: those are shared by the whole process, so `python.set(
    "json.dumps", 5)` would replace json.dumps for the host and every other
    script. And what a script cannot see it cannot overwrite: names that
    start with "_" are refused."""
    for kinds, what in _NOT_WRITABLE:
        if isinstance(owner, kinds):
            raise NovaError(
                'cannot modify the {} "{}": python.set and assignment through a proxy only '
                'write to objects the host exposed, not to modules, classes or functions'
                .format(what, getattr(owner, "__name__", "?")),
                position, label="PythonError",
            )
    if isinstance(name, str) and name.startswith("_"):
        raise NovaError('cannot set private attribute "{}"'.format(name), position, label="PythonError")


class PythonObjectProxy(dict):
    """Makes a live Python object look like a NovaLang dictionary.

    NovaLang's dot/bracket access (visit_MemberNode, visit_IndexNode,
    lookup_key) only ever calls `in`, `[]` and iteration on whatever a
    dict-typed value is - all overridden here to reach the wrapped
    object's real attributes instead of a snapshot, and all it took was
    isinstance(x, dict) already being how the interpreter checks "is this
    a dict", true for a subclass too. So `reactor.temp` reads the actual
    live attribute, `reactor.temp = x` writes it, and `reactor.scram`
    resolves to a real, callable method - no changes needed anywhere else
    in the interpreter.
    """

    def __init__(self, target, interpreter=None):
        super().__init__()
        object.__setattr__(self, "_nova_target", target)
        object.__setattr__(self, "_nova_interpreter", interpreter)

    def _visible_keys(self):
        target = self._nova_target
        names = []
        for name in dir(target):
            if name.startswith("_"):
                continue
            try:
                if isinstance(getattr(target, name), ModuleType) and \
                        bridge_lookup(target, name, self._nova_interpreter) is _MISSING:
                    continue
            except Exception:
                pass            # a property that raises: listed, as before; reading it will report
            names.append(name)
        return names

    def __contains__(self, key):
        try:
            return bridge_lookup(self._nova_target, key, self._nova_interpreter) is not _MISSING
        except NovaError:
            raise
        except Exception as problem:
            raise NovaError("{}: {}".format(type(problem).__name__, problem), label="PythonError")

    def __getitem__(self, key):
        try:
            value = bridge_lookup(self._nova_target, key, self._nova_interpreter)
            if value is _MISSING:
                raise KeyError(key)
            return to_nova_value(value, self._nova_interpreter)
        except KeyError:
            raise
        except NovaError:
            raise
        except Exception as problem:
            raise NovaError("{}: {}".format(type(problem).__name__, problem), label="PythonError")

    def __setitem__(self, key, value):
        try:
            bridge_write_check(self._nova_target, key, self._nova_interpreter)
            setattr(self._nova_target, key, to_python_value(value, self._nova_interpreter))
        except NovaError:
            raise
        except Exception as problem:
            raise NovaError("{}: {}".format(type(problem).__name__, problem), label="PythonError")

    def __iter__(self):
        return iter(self._visible_keys())

    def __len__(self):
        return len(self._visible_keys())

    def keys(self):
        return self._visible_keys()

    def items(self):
        return [(name, self[name]) for name in self._visible_keys()]

    def values(self):
        return [self[name] for name in self._visible_keys()]

    def __repr__(self):
        return "<python object {}>".format(type(self._nova_target).__name__)


def to_nova_value(value, interpreter=None):
    """Python -> NovaLang. A callable becomes a callable NovaLang value;
    any other object becomes a live PythonObjectProxy, so nested access
    like `reactor.core.temp` works without special-casing anything."""
    if value is None:
        return NOTHING
    if isinstance(value, (bool, int, float, str)):
        return bounded_integer(value, None) if type(value) is int else value
    if isinstance(value, ModuleType) and not python_granted(value, interpreter):
        # The attribute gate hides these; this catches one that arrives inside
        # a dict or list, or as the result of a call.
        raise NovaError(
            'the module "{}" cannot be handed to a script: it is not on the python.import() '
            'list and the embedding program did not expose it'.format(value.__name__),
            label="PythonError",
        )
    if isinstance(value, dict):
        return {str(key): to_nova_value(item, interpreter) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_nova_value(item, interpreter) for item in value]
    if callable(value):
        return wrap_python_callable(value)
    return PythonObjectProxy(value, interpreter)


def to_python_value(value, interpreter=None):
    """NovaLang -> Python, the inverse of to_nova_value. Converting a
    NovaLang function or built-in needs an interpreter to call it with
    later - supplied by every call site that has one (the python.* and
    Nova.* built-ins all do); omitting it is only safe for data with no
    function values in it."""
    if value is NOTHING:
        return None
    if isinstance(value, PythonObjectProxy):
        return value._nova_target
    if isinstance(value, (NovaFunction, BuiltinFunction)):
        if interpreter is None:
            raise NovaError(
                "this NovaLang function cannot be handed to Python here - no "
                "interpreter is available to call it with",
                label="PythonError",
            )
        return wrap_nova_callable(value, interpreter)
    if isinstance(value, list):
        return [to_python_value(item, interpreter) for item in value]
    if isinstance(value, dict):
        return {key: to_python_value(item, interpreter) for key, item in value.items()}
    return value                                        # bool, int, float, str


def wrap_python_callable(func, name=None):
    """A Python callable, reachable from NovaLang - its own errors become
    a NovaError labelled PythonError, per Stage 12's error-handling rule."""

    def implementation(args, position, interpreter):
        python_args = [to_python_value(arg, interpreter) for arg in args]
        try:
            result = func(*python_args)
        except NovaError:
            raise
        except Exception as problem:
            raise NovaError(
                "{}: {}".format(type(problem).__name__, problem), position, label="PythonError"
            )
        return to_nova_value(result, interpreter)

    return BuiltinFunction(name or getattr(func, "__name__", "python function"), None,
                           implementation, needs_interpreter=True)


def wrap_nova_callable(fn, interpreter):
    """A NovaLang function or built-in, reachable from Python - see
    Nova.call for the counterpart used when Python code calls in by name."""

    def call_from_python(*python_args):
        nova_args = [to_nova_value(arg, interpreter) for arg in python_args]
        try:
            with interpreter.running():
                result = interpreter.call_value(fn, nova_args, 0)
        except NovaError as error:
            raise NovaLangError(error) from None
        except FatalLimit as fatal:
            raise fatal_error(fatal) from None
        return to_python_value(result, interpreter)

    return call_from_python


def resolve_python_path(interpreter, dotted_name, position):
    """Walk a dotted name like "reactor.core.temp" from the registry."""
    parts = dotted_name.split(".")
    root = parts[0]
    if root not in interpreter.python_registry:
        raise NovaError(
            '"{}" is not available to this script - only names the embedding program '
            'exposed with Nova.expose()/expose_module() can be reached from python.*'
            .format(root),
            position, label="PythonError",
        )
    target = interpreter.python_registry[root]
    try:
        for part in parts[1:]:
            value = bridge_lookup(target, part, interpreter)
            if value is _MISSING:
                raise NovaError(
                    '"{}" has no attribute "{}"'.format(dotted_name, part), position, label="PythonError"
                )
            target = value
    except NovaError:
        raise
    except Exception as problem:
        raise NovaError("{}: {}".format(type(problem).__name__, problem), position, label="PythonError")
    return target


def builtin_python_import(args, position, interpreter):
    name = text_argument(args[0], "python.import()", position)
    if name in interpreter.python_registry:
        return NOTHING
    allowed = interpreter.python_allowlist()
    if name not in allowed:
        raise NovaError(
            '"{}" is not on the list of modules python.import() allows on its own ({}) '
            '- the embedding program can add it with Nova.expose_module("{}")'
            .format(name, ", ".join(allowed), name),
            position, label="PythonError",
        )
    try:
        module = importlib.import_module(name)
    except ImportError as problem:
        raise NovaError("python.import(): {}".format(problem), position, label="PythonError")
    interpreter.python_registry[name] = module
    return NOTHING


def builtin_python_call(args, position, interpreter):
    name = text_argument(args[0], "python.call()", position)
    target = resolve_python_path(interpreter, name, position)
    if not callable(target):
        raise NovaError('"{}" is not callable'.format(name), position, label="PythonError")
    call_args = [to_python_value(arg, interpreter) for arg in args[1:]]
    try:
        result = target(*call_args)
    except NovaError:
        raise
    except Exception as problem:
        raise NovaError(
            "{}: {}".format(type(problem).__name__, problem), position, label="PythonError"
        )
    return to_nova_value(result, interpreter)


def builtin_python_get(args, position, interpreter):
    name = text_argument(args[0], "python.get()", position)
    target = resolve_python_path(interpreter, name, position)
    return to_nova_value(target, interpreter)


def builtin_python_set(args, position, interpreter):
    name = text_argument(args[0], "python.set()", position)
    value = args[1]
    parts = name.split(".")
    root = parts[0]
    if len(parts) == 1:
        # No dots: define or overwrite a top-level registry entry, so a
        # script can hand a value back for the embedding program to read
        # afterwards with Nova.registry[name] or python.get(name) itself.
        interpreter.python_registry[root] = to_python_value(value, interpreter)
        return NOTHING
    if root not in interpreter.python_registry:
        raise NovaError(
            '"{}" is not available to this script - see python.import() or ask the '
            'embedding program to expose it first'.format(root),
            position, label="PythonError",
        )
    target = interpreter.python_registry[root]
    try:
        for part in parts[1:-1]:
            step = bridge_lookup(target, part, interpreter)
            if step is _MISSING:
                raise NovaError('"{}" has no attribute "{}"'.format(name, part), position, label="PythonError")
            target = step
        bridge_write_check(target, parts[-1], interpreter, position)
        setattr(target, parts[-1], to_python_value(value, interpreter))
    except NovaError:
        raise
    except AttributeError as problem:
        raise NovaError("python.set(): {}".format(problem), position, label="PythonError")
    except Exception as problem:
        raise NovaError("python.set(): {}: {}".format(type(problem).__name__, problem),
                        position, label="PythonError")
    return NOTHING


PYTHON_NAMESPACE = {
    "import": BuiltinFunction("python.import", 1, builtin_python_import, needs_interpreter=True),
    "call": BuiltinFunction("python.call", None, builtin_python_call, needs_interpreter=True),
    "get": BuiltinFunction("python.get", 1, builtin_python_get, needs_interpreter=True),
    "set": BuiltinFunction("python.set", 2, builtin_python_set, needs_interpreter=True),
}


def _python_disabled(args, position, interpreter):
    raise NovaError(
        "python.* is disabled: run novalang.py with --allow-python, or create the "
        "embedding host with Nova(allow_python=True)",
        position, label="PythonError",
    )


# What `python` is unless it was asked for. A name, so that scripts, the
# self-hosted interpreter (which forwards to it) and the linter still see a
# `python` global; no capability, because every member only refuses. The
# arity is open so that the refusal, not an arity error, is what a script reads.
PYTHON_DISABLED_NAMESPACE = {
    name: BuiltinFunction("python." + name, None, _python_disabled, needs_interpreter=True)
    for name in ("import", "call", "get", "set")
}


# ---- OS / filesystem -----------------------------------------------------------------

def builtin_cwd(args, position):
    return os.getcwd()


def builtin_mkdir(args, position):
    path = text_argument(args[0], "mkdir()", position)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as problem:
        raise NovaError(
            "mkdir(): {}: {}".format(path, problem.strerror or problem), position, label="FileError"
        )
    return NOTHING


def builtin_remove(args, position):
    path = text_argument(args[0], "remove()", position)
    try:
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)
    except FileNotFoundError:
        raise NovaError(path, position, label="FileNotFoundError")
    except OSError as problem:
        raise NovaError(
            "remove(): {}: {}".format(path, problem.strerror or problem), position, label="FileError"
        )
    return NOTHING


def builtin_rename(args, position):
    old = text_argument(args[0], "the old name for rename()", position)
    new = text_argument(args[1], "the new name for rename()", position)
    try:
        os.rename(old, new)
    except OSError as problem:
        raise NovaError("rename(): {}".format(problem.strerror or problem), position, label="FileError")
    return NOTHING


def builtin_copy(args, position):
    src = text_argument(args[0], "the source for copy()", position)
    dst = text_argument(args[1], "the destination for copy()", position)
    try:
        shutil.copy2(src, dst)
    except OSError as problem:
        raise NovaError("copy(): {}".format(problem.strerror or problem), position, label="FileError")
    return NOTHING


# ---- string utilities -----------------------------------------------------------------

def builtin_regex(args, position):
    pattern = text_argument(args[0], "the pattern for regex()", position)
    text = text_argument(args[1], "the text for regex()", position)
    try:
        return re.search(pattern, text, re.ASCII) is not None   # \d \w \s \b are ASCII (D-021)
    except re.error as problem:
        raise NovaError("regex(): bad pattern: {}".format(problem), position, label="TypeError")


def builtin_replace_all(args, position):
    text = text_argument(args[0], "the text for replace_all()", position)
    old = text_argument(args[1], "the target for replace_all()", position)
    new = text_argument(args[2], "the replacement for replace_all()", position)
    return text.replace(old, new)


def builtin_split_lines(args, position):
    lines = LINE_ENDS.split(text_argument(args[0], "split_lines()", position))
    if lines[-1] == "":
        lines.pop()                             # a final line end starts no new line
    return lines


def builtin_byte_length(args, position):
    # The number of bytes of the UTF-8 form of the text ([lib.text]): what a limit in bytes counts.
    return len(text_argument(args[0], "byte_length()", position).encode("utf-8", "replace"))


def builtin_pad(args, position):
    text = text_argument(args[0], "pad()", position)
    return text.ljust(whole_number(args[1], "pad()", position))


def builtin_pad_left(args, position):
    text = text_argument(args[0], "pad_left()", position)
    return text.rjust(whole_number(args[1], "pad_left()", position))


def builtin_reverse(args, position):
    value = args[0]
    if isinstance(value, str):
        return value[::-1]
    if isinstance(value, list):
        return list(reversed(value))
    raise NovaError(
        "reverse() needs a string or a list, but got {}".format(type_name(value)), position, label="TypeError"
    )


def builtin_sorted(args, position):
    if not 1 <= len(args) <= 2:
        raise NovaError("sorted() takes a list and an optional true or false", position)
    items = list(list_argument(args[0], "sorted()", position))
    descending = False
    if len(args) > 1:
        if not isinstance(args[1], bool):
            raise NovaError("sorted()'s second argument must be true or false", position, label="TypeError")
        descending = args[1]
    # Numbers (a boolean counts as 0 or 1) sort among themselves and strings
    # among themselves; any other item, a NaN, or a mixture, cannot be ordered
    # (D-019).
    numbers = [is_number(item) or isinstance(item, bool) for item in items]
    texts = [isinstance(item, str) for item in items]
    if not (all(numbers) or all(texts)) or any(
            isinstance(item, float) and item != item for item in items):
        raise NovaError("sorted() needs items that can be compared with each other", position, label="TypeError")
    items.sort(reverse=descending)
    return items


# ---- debugging -----------------------------------------------------------------

def builtin_assert(args, position):
    if not 1 <= len(args) <= 2:
        raise NovaError("assert() takes a condition and an optional message", position)
    condition = args[0]
    if not isinstance(condition, bool):
        raise NovaError(
            "assert() needs true or false, but got {}".format(type_name(condition)), position, label="TypeError"
        )
    if not condition:
        message = "assertion failed"
        if len(args) > 1:
            message = text_argument(args[1], "the message for assert()", position)
        raise NovaError(message, position, label="AssertionError")
    return NOTHING


def builtin_log(args, position, interpreter):
    text = " ".join(format_value(arg) for arg in args)
    stamp = datetime.now(timezone.utc).isoformat()
    interpreter.write_output("[{}] {}".format(stamp, text), sys.stderr, position)
    return NOTHING


# ---- higher-order functions -----------------------------------------------------------------
#
# The only built-ins that call back into a NovaLang function value passed
# as an argument - which needs the interpreter itself, not just the
# already-evaluated arguments, hence BuiltinFunction's needs_interpreter.

def callable_argument(value, who, position):
    if not isinstance(value, (NovaFunction, BuiltinFunction)):
        raise NovaError(
            "{} needs a function, but got {}".format(who, type_name(value)), position, label="TypeError"
        )
    return value


def builtin_map(args, position, interpreter):
    fn = callable_argument(args[0], "map()", position)
    items = list_argument(args[1], "map()", position)
    return [interpreter.call_value(fn, [item], position) for item in items]


def builtin_filter(args, position, interpreter):
    fn = callable_argument(args[0], "filter()", position)
    items = list_argument(args[1], "filter()", position)
    kept = []
    for item in items:
        keep = interpreter.call_value(fn, [item], position)
        if not isinstance(keep, bool):
            raise NovaError("filter()'s function must return true or false", position, label="TypeError")
        if keep:
            kept.append(item)
    return kept


def builtin_reduce(args, position, interpreter):
    if not 2 <= len(args) <= 3:
        raise NovaError("reduce() takes a function, a list and an optional starting value",
                        position)
    fn = callable_argument(args[0], "reduce()", position)
    items = list_argument(args[1], "reduce()", position)
    if len(args) >= 3:
        accumulator = args[2]
        rest = items
    else:
        if not items:
            raise NovaError(
                "reduce() needs a non-empty list, or an initial value as a third argument",
                position,
            )
        accumulator = items[0]
        rest = items[1:]
    for item in rest:
        accumulator = interpreter.call_value(fn, [accumulator, item], position)
    return accumulator


BUILTINS = {
    "print": BuiltinFunction("print", None, builtin_print, needs_interpreter=True),
    "len": BuiltinFunction("len", 1, builtin_len),
    "append": BuiltinFunction("append", 2, builtin_append),
    "pop": BuiltinFunction("pop", None, builtin_pop),
    "range": BuiltinFunction("range", None, builtin_range),
    "upper": BuiltinFunction("upper", 1, builtin_upper),
    "lower": BuiltinFunction("lower", 1, builtin_lower),
    "trim": BuiltinFunction("trim", 1, builtin_trim),
    "split": BuiltinFunction("split", None, builtin_split),
    "join": BuiltinFunction("join", 2, builtin_join),
    "str": BuiltinFunction("str", 1, builtin_str),
    "num": BuiltinFunction("num", 1, builtin_num),
    "type": BuiltinFunction("type", 1, builtin_type),
    "keys": BuiltinFunction("keys", 1, builtin_keys),
    "values": BuiltinFunction("values", 1, builtin_values),
    "read": BuiltinFunction("read", 1, builtin_read, paths=((0, "read"),)),
    "write": BuiltinFunction("write", 2, builtin_write, paths=((0, "write"),)),
    "exists": BuiltinFunction("exists", 1, builtin_exists, paths=((0, "read"),)),
    "listdir": BuiltinFunction("listdir", 1, builtin_listdir, paths=((0, "read"),)),
    "input": BuiltinFunction("input", None, builtin_input, needs_interpreter=True),
    "abspath": BuiltinFunction("abspath", 1, builtin_abspath),
    "realpath": BuiltinFunction("realpath", 1, builtin_realpath),
    "dirname": BuiltinFunction("dirname", 1, builtin_dirname),

    # Stage 11: standard library
    "time": BuiltinFunction("time", 0, builtin_time, needs_interpreter=True),
    "monotonic": BuiltinFunction("monotonic", 0, builtin_monotonic, needs_interpreter=True),
    "byte_length": BuiltinFunction("byte_length", 1, builtin_byte_length),
    "sleep": BuiltinFunction("sleep", 1, builtin_sleep, needs_interpreter=True),
    "now": BuiltinFunction("now", 0, builtin_now, needs_interpreter=True),
    "format_time": BuiltinFunction("format_time", 2, builtin_format_time, needs_interpreter=True),
    "random": BuiltinFunction("random", 0, builtin_random, needs_interpreter=True),
    "randint": BuiltinFunction("randint", 2, builtin_randint, needs_interpreter=True),
    "choice": BuiltinFunction("choice", 1, builtin_choice, needs_interpreter=True),
    "shuffle": BuiltinFunction("shuffle", 1, builtin_shuffle, needs_interpreter=True),
    "abs": BuiltinFunction("abs", 1, builtin_abs),
    "round": BuiltinFunction("round", None, builtin_round),
    "floor": BuiltinFunction("floor", 1, builtin_floor),
    "ceil": BuiltinFunction("ceil", 1, builtin_ceil),
    "sqrt": BuiltinFunction("sqrt", 1, builtin_sqrt),
    "pow": BuiltinFunction("pow", 2, builtin_pow),
    "sin": BuiltinFunction("sin", 1, builtin_sin),
    "cos": BuiltinFunction("cos", 1, builtin_cos),
    "tan": BuiltinFunction("tan", 1, builtin_tan),
    "ln": BuiltinFunction("ln", 1, builtin_ln),
    "log10": BuiltinFunction("log10", 1, builtin_log10),
    "min": BuiltinFunction("min", None, builtin_min),
    "max": BuiltinFunction("max", None, builtin_max),
    "sum": BuiltinFunction("sum", None, builtin_sum),
    "env": BuiltinFunction("env", 1, builtin_env, needs_interpreter=True),
    "exit": BuiltinFunction("exit", None, builtin_exit, needs_interpreter=True),
    "args": BuiltinFunction("args", 0, builtin_args),
    "platform": BuiltinFunction("platform", 0, builtin_platform),
    "cwd": BuiltinFunction("cwd", 0, builtin_cwd),
    "mkdir": BuiltinFunction("mkdir", 1, builtin_mkdir, paths=((0, "write"),)),
    "remove": BuiltinFunction("remove", 1, builtin_remove, paths=((0, "write"),)),
    "rename": BuiltinFunction("rename", 2, builtin_rename, paths=((0, "write"), (1, "write"))),
    "copy": BuiltinFunction("copy", 2, builtin_copy, paths=((0, "read"), (1, "write"))),
    "regex": BuiltinFunction("regex", 2, builtin_regex),
    "replace_all": BuiltinFunction("replace_all", 3, builtin_replace_all),
    "split_lines": BuiltinFunction("split_lines", 1, builtin_split_lines),
    "pad": BuiltinFunction("pad", 2, builtin_pad),
    "pad_left": BuiltinFunction("pad_left", 2, builtin_pad_left),
    "reverse": BuiltinFunction("reverse", 1, builtin_reverse),
    "sorted": BuiltinFunction("sorted", None, builtin_sorted),
    "assert": BuiltinFunction("assert", None, builtin_assert),
    "log": BuiltinFunction("log", None, builtin_log, needs_interpreter=True),
    "map": BuiltinFunction("map", 2, builtin_map, needs_interpreter=True),
    "filter": BuiltinFunction("filter", 2, builtin_filter, needs_interpreter=True),
    "reduce": BuiltinFunction("reduce", None, builtin_reduce, needs_interpreter=True),
}

# json.dumps/loads/pretty and the json.dumps-style access are ordinary dict
# access (Stage 6) on a predefined global - not new syntax, just a
# dictionary whose values happen to be callable. See Interpreter.__init__.
JSON_NAMESPACE = {
    "dumps": BuiltinFunction("json.dumps", 1, builtin_json_dumps),
    "loads": BuiltinFunction("json.loads", 1, builtin_json_loads),
    "pretty": BuiltinFunction("json.pretty", 1, builtin_json_pretty),
}


def whole_number(value, who, position):
    """Insist on an integer - 5 and 5.0 are fine, 5.5 and "5" are not."""
    if not is_number(value):
        raise NovaError("{} needs a whole number, but got {}".format(who, type_name(value)),
                        position)
    if isinstance(value, float):
        if not value.is_integer():
            raise NovaError("{} needs a whole number, but got {}".format(who, format_value(value)),
                            position)
        return int(value)
    return value


def type_category(value):
    """The coarse kind of a value, as reported by type()."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, (NovaFunction, BuiltinFunction)):
        return "function"
    return "nothing"


def dict_key(value, position):
    """Dictionary keys are strings, and only strings."""
    if not isinstance(value, str):
        raise NovaError(
            "a dictionary key must be a string, but this is {}".format(type_name(value)),
            position,
        )
    return value


def lookup_key(target, key, position):
    """Read one entry, naming the near misses when it is not there."""
    if key in target:
        return target[key]
    known = list(target)
    if not known:
        raise NovaError("this dictionary is empty, so it has no {!r}".format(key), position)
    shown = ", ".join(known[:8]) + (", ..." if len(known) > 8 else "")
    raise NovaError(
        "this dictionary has no key {!r} - it has {}".format(key, shown), position
    )


def normalize_index(target, index, position):
    """Turn a NovaLang index into a Python one, with friendly errors."""
    if not isinstance(target, (list, str)):
        raise NovaError("{} cannot be indexed".format(type_name(target)), position)
    what = "string" if isinstance(target, str) else "list"
    spot = whole_number(index, "a {} index".format(what), position)

    size = len(target)
    if size == 0:
        raise NovaError(
            "this {} is empty, so it has no {} to index".format(
                what, "character" if what == "string" else "item"
            ),
            position,
        )

    original = spot
    if spot < 0:
        spot += size                    # a[-1] is the last item
    if not 0 <= spot < size:
        raise NovaError(
            "index {} is out of range for a {} of {} {} - valid indexes are "
            "{} to {}".format(
                original, what, size,
                "character(s)" if what == "string" else "item(s)",
                -size, size - 1,
            ),
            position,
        )
    return spot


def guard_name(name, position, role):
    """Built-ins are reserved: `print = 3` and `def print()` are both errors."""
    if name in BUILTINS:
        raise NovaError(
            "{!r} is a built-in function and cannot be used as {} name".format(name, role),
            position,
        )


def type_name(value):
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "a dictionary"
    if isinstance(value, (NovaFunction, BuiltinFunction)):
        return "a function"
    return "nothing"


def format_value(value, seen=None):
    """How a value prints: strings bare, booleans lowercase, ints without .0"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is NOTHING:
        return "nothing"
    if isinstance(value, PythonObjectProxy):
        # Shallow on purpose: a live object's attributes lead to other objects,
        # and a module's lead back to modules, so walking them never ends.
        return repr(value)
    if isinstance(value, list):
        # A list can contain itself, so remember what we are already inside.
        seen = seen or set()
        if id(value) in seen:
            return "[...]"
        seen = seen | {id(value)}
        return "[" + ", ".join(format_repr(item, seen) for item in value) + "]"
    if isinstance(value, dict):
        seen = seen or set()
        if id(value) in seen:
            return "{...}"
        seen = seen | {id(value)}
        return "{" + ", ".join(
            "{}: {}".format(format_key(key), format_repr(item, seen))
            for key, item in value.items()
        ) + "}"
    if isinstance(value, float):
        return format_float(value)
    if isinstance(value, (NovaFunction, BuiltinFunction)):
        return repr(value)
    try:
        return str(value)
    except ValueError:
        # Only if the Python underneath was configured to refuse long integers
        # as text (PYTHONINTMAXSTRDIGITS, set below the language's own bound).
        raise NovaError("this Python is set to refuse converting an integer of this size "
                        "to text (PYTHONINTMAXSTRDIGITS)") from None


# Exact decimal contexts for shortest_digits: one per number of digits, rounding
# to nearest (ties to even) and upwards.
_NEAREST = [decimal.Context(prec=places, rounding=decimal.ROUND_HALF_EVEN) for places in range(1, 18)]
_UPWARDS = [decimal.Context(prec=places, rounding=decimal.ROUND_CEILING) for places in range(1, 18)]


def shortest_digits(value):
    """The decimal digits that spell a finite, positive float, and the
    exponent of the first one: (digits, x) means d.ddd * 10 ** x.

    [port.floats]: the fewest digits that read back as exactly this float,
    and of those the one nearest its true value. For 1, 2, 3 ... digits it
    tries the true value rounded to nearest and, failing that, rounded up,
    and stops at the first that reads back. (Rounding down never helps: a
    float's rounding interval is as wide above it as below, except just above a
    power of two, where it is wider above.) Exact decimal arithmetic and a
    correctly rounded read are all it needs, and neither is repr()'s."""
    exact = decimal.Decimal(value)
    for places in range(1, 18):
        for context in (_NEAREST[places - 1], _UPWARDS[places - 1]):
            candidate = context.create_decimal(exact)
            if float(candidate) == value:
                _, digits, exponent = candidate.as_tuple()
                text = "".join(map(str, digits))
                return text.rstrip("0") or "0", len(digits) - 1 + exponent
    raise AssertionError("17 digits always spell a float")


def float_text(value):
    """A finite float's shortest spelling: positional from 0.0001 up to 1e16,
    exponent form (`1e-05`, `1.5e+16`) outside it. Whole numbers are
    displayed by format_float instead; this is their layout rule too."""
    if value == 0:
        return "-0.0" if math.copysign(1.0, value) < 0 else "0.0"
    sign = "-" if value < 0 else ""
    digits, x = shortest_digits(abs(value))
    if -4 <= x < 16:
        if x >= 0:
            whole = digits[:x + 1].ljust(x + 1, "0")
            return "{}{}.{}".format(sign, whole, digits[x + 1:] or "0")
        return "{}0.{}{}".format(sign, "0" * (-x - 1), digits)
    mantissa = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
    return "{}{}e{}{:02d}".format(sign, mantissa, "-" if x < 0 else "+", abs(x))


def format_float(value):
    """How a float prints ([port.floats]): `inf`, `-inf`, `nan`; a whole value
    as its exact decimal expansion (negative zero as `0`); anything else as
    its shortest spelling."""
    if value != value:
        return "nan"
    if value in (float("inf"), float("-inf")):
        return "inf" if value > 0 else "-inf"
    if value.is_integer():
        return str(int(value))
    return float_text(value)


def format_key(key):
    """Print a key bare when it could be typed bare, quoted otherwise."""
    return key if is_bare_name(key) else format_repr(key)


def format_repr(value, seen=None):
    """How the REPL echoes a value: like format_value but strings are quoted."""
    if isinstance(value, str):
        return '"{}"'.format(
            value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        )
    return format_value(value, seen)


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------

class Environment:
    """One scope. Lookups walk outward; assignment walks outward too, but
    only as far as the nearest barrier.

    A function call creates a *barrier* scope, and so does the global scope.
    Blocks (loop bodies, if bodies) create ordinary, transparent scopes.
    Those two rules together give:

        x = 0
        while x < 10 { x = x + 1 }   # updates the global x - no barrier
                                     # between the block and the globals
        while x < 10 { t = x }       # `t` is new, so it lands in the block
                                     # scope and is gone after the loop

        def f() { x = 99 }           # `x` stops at the function barrier,
                                     # so the global x is untouched
    """

    def __init__(self, parent=None, barrier=False):
        self.values = {}
        self.parent = parent
        self.barrier = barrier

    def get(self, name):
        scope = self
        while scope is not None:
            if name in scope.values:
                return scope.values[name]
            scope = scope.parent
        return None

    def has(self, name):
        scope = self
        while scope is not None:
            if name in scope.values:
                return True
            scope = scope.parent
        return False

    def define(self, name, value):
        """Bind in *this* scope, shadowing anything outside it."""
        self.values[name] = value

    def assign(self, name, value):
        """Update an existing binding out to the nearest barrier, else
        create the name here."""
        scope = self
        while scope is not None:
            if name in scope.values:
                scope.values[name] = value
                return
            if scope.barrier:
                break
            scope = scope.parent
        self.values[name] = value


# ---------------------------------------------------------------------------
# 4. Interpreter  (AST -> a value), tree-walking
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Shared operations (M4). What each operation *means* lives here, once, and
# both engines call it: the tree-walking Interpreter and the bytecode VM.
# The VM's only shortcuts are inline fast paths for the commonest cases -
# two operands of the same exact type(), where the function here would do
# exactly the same Python operation - and station 11 holds them to it.
# The engines differ only in how they get the operands - and in what order
# they evaluate them, which each preserves exactly - never in what an
# operation does with them, so they cannot drift apart.
# ---------------------------------------------------------------------------

def binary_operation(op, left, right, position, limits=None):
    # `limits` is the engine's Limits when it counts them (the restricted profile), else None.
    list_limit = limits.list if limits is not None else MAX_LIST_LENGTH
    string_limit = limits.string if limits is not None else MAX_LIST_LENGTH
    # "abc" + "def" is the one non-numeric arithmetic we allow.
    if op == "+" and isinstance(left, str) and isinstance(right, str):
        if limits is not None and len(left) + len(right) > string_limit:
            raise NovaError("a string cannot grow beyond {} characters".format(string_limit), position)
        return left + right

    # "Ha" * 3 repeats a string; the number may be on either side.
    if op == "*" and (isinstance(left, str) or isinstance(right, str)):
        text, count = (left, right) if isinstance(left, str) else (right, left)
        if isinstance(text, str) and is_number(count):
            times = whole_number(count, "string repetition", position)
            if times < 0:
                raise NovaError(
                    "a string cannot be repeated a negative number of times", position
                )
            if len(text) * times > string_limit:
                raise NovaError(
                    "repeating that string {} times would be too long".format(times),
                    position,
                )
            return text * times

    # Two dictionaries merge with '+'; the right-hand side wins.
    if op == "+" and isinstance(left, dict) and isinstance(right, dict):
        merged = dict(left)
        merged.update(right)
        return merged

    # Lists join with '+' and repeat with '*', always into a new list.
    if op == "+" and isinstance(left, list) and isinstance(right, list):
        if limits is not None and len(left) + len(right) > list_limit:
            raise NovaError("a list cannot grow beyond {} items".format(list_limit), position)
        return left + right

    if op == "*" and (isinstance(left, list) or isinstance(right, list)):
        items, count = (left, right) if isinstance(left, list) else (right, left)
        if not isinstance(items, list) or not is_number(count):
            raise NovaError(
                "a list can only be repeated by a whole number, not by {}".format(
                    type_name(right if isinstance(left, list) else left)
                ),
                position,
            )
        times = whole_number(count, "list repetition", position)
        if times < 0:
            raise NovaError("a list cannot be repeated a negative number of times",
                            position)
        if len(items) * times > list_limit:
            raise NovaError(
                "repeating that list {} times would exceed {} items".format(
                    times, list_limit
                ),
                position,
            )
        return items * times

    if not is_number(left) or not is_number(right):
        raise NovaError(
            "cannot use '{}' on {} and {}".format(op, type_name(left), type_name(right)),
            position,
        )

    try:
        return bounded_integer(numeric_operation(op, left, right, position), position)
    except OverflowError:
        # An integer beyond the range of a float, mixed with a float or divided
        # into a quotient too large to be one. (Float arithmetic itself
        # saturates to infinity, as IEEE 754 says.)
        raise NovaError(
            "a number is too large for this operation - an integer beyond the range of "
            "a float cannot be divided or mixed with a float",
            position,
        ) from None


def numeric_operation(op, left, right, position):
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            raise NovaError("division by zero", position)
        result = left / right
        # Keep whole answers whole: 10 / 2 is 5, not 5.0
        if isinstance(left, int) and isinstance(right, int) and result.is_integer():
            return int(result)
        return result
    if op == "//":
        if right == 0:
            raise NovaError("integer division by zero", position)
        return left // right            # rounds towards negative infinity
    if op == "%":
        if right == 0:
            raise NovaError("cannot take the remainder of a division by zero",
                            position)
        return left % right             # the sign follows the right-hand side

    raise NovaError("unknown operator {!r}".format(op), position)


def compare_operation(op, left, right, position):
    if op == "==":
        return nova_equals(left, right)
    if op == "!=":
        return not nova_equals(left, right)
    if op == "in":
        return nova_contains(left, right, position)

    ordered = (is_number(left) and is_number(right)) or (
        isinstance(left, str) and isinstance(right, str)
    )
    if not ordered:
        raise NovaError(
            "cannot compare {} with {} using '{}'".format(
                type_name(left), type_name(right), op
            ),
            position,
        )

    if op == "<":
        return left < right
    if op == ">":
        return left > right
    if op == "<=":
        return left <= right
    if op == ">=":
        return left >= right

    raise NovaError("unknown comparison {!r}".format(op), position)


def unary_operation(op, value, position):
    if not is_number(value):
        raise NovaError(
            "cannot apply unary '{}' to {}".format(op, type_name(value)), position
        )
    return value if op == "+" else -value


def not_operation(value, position):
    if not isinstance(value, bool):
        raise NovaError(
            "'not' needs true or false, but this is {}".format(type_name(value)),
            position,
        )
    return not value


def logical_side(value, side, op, position):
    """`and` / `or` take only true or false, on either side."""
    if not isinstance(value, bool):
        raise NovaError(
            "the {} side of '{}' must be true or false, but it is {}".format(
                side, op, type_name(value)
            ),
            position,
        )
    return value


def condition_check(value, keyword, position):
    """Conditions are strict: only true or false will do."""
    if not isinstance(value, bool):
        raise NovaError(
            "a '{}' condition must be true or false, but this is {}".format(
                keyword, type_name(value)
            ),
            position,
        )
    return value


def index_operation(target, index, position):
    if isinstance(target, dict):
        return lookup_key(target, dict_key(index, position), position)
    return target[normalize_index(target, index, position)]


def member_operation(target, name, position):
    if not isinstance(target, dict):
        raise NovaError(
            "{} has no fields, so '.{}' means nothing here".format(
                type_name(target), name
            ),
            position,
        )
    return lookup_key(target, name, position)


def member_assign_target(target, position):
    """`x.f = v` refuses a non-dictionary before v is evaluated."""
    if not isinstance(target, dict):
        raise NovaError(
            "only a dictionary can have fields set, but this is {}".format(
                type_name(target)
            ),
            position,
        )


def index_assign_target(target, position):
    """`x[i] = v` refuses a string before i is evaluated."""
    if isinstance(target, str):
        raise NovaError(
            "strings cannot be changed in place - build a new one instead",
            position,
        )


def index_assign_key(target, index, position):
    """...and checks a dictionary's key before v is evaluated."""
    if isinstance(target, dict):
        return dict_key(index, position)
    return index


def index_assign(target, index, value, position, limits=None):
    if isinstance(target, dict):
        if limits is not None and limits.dict is not None and index not in target and len(target) >= limits.dict:
            raise NovaError("a dictionary cannot hold more than {} entries".format(limits.dict), position)
        target[index] = value                         # a new key is fine
        return value
    spot = normalize_index(target, index, position)
    target[spot] = value
    return value


def slice_target(target, position):
    if not isinstance(target, (list, str)):
        raise NovaError("{} cannot be sliced".format(type_name(target)), position)


def slice_bound(value, position):
    return whole_number(value, "a slice bound", position)


def delete_target(target, position):
    if not isinstance(target, dict):
        raise NovaError(
            "delete works on dictionary entries, but this is {}{}".format(
                type_name(target),
                " - use pop() to remove a list item" if isinstance(target, list) else "",
            ),
            position,
        )


def delete_key(target, key, position):
    target.pop(dict_key(key, position), None)       # deleting twice is fine
    return NOTHING


def delete_file(path, position):
    if not isinstance(path, str):
        raise NovaError(
            "delete() needs a file name, but got {}".format(type_name(path)), position
        )
    if os.path.isdir(path):
        raise NovaError(
            "{} is a directory - delete() only removes files".format(path),
            position, label="FileError",
        )
    try:
        os.remove(path)
    except FileNotFoundError:
        pass                                    # deleting twice is harmless
    except IsADirectoryError:
        raise NovaError(
            "{} is a directory - delete() only removes files".format(path),
            position, label="FileError",
        )
    except OSError as problem:
        raise NovaError(
            "{}: {}".format(path, problem.strerror or "cannot be deleted"),
            position, label="FileError",
        )
    return NOTHING


def throw_error(value, position):
    """The NovaError `throw(value)` raises."""
    if not isinstance(value, str):
        return NovaError(
            "throw needs a string, but got {} - use str() to convert it".format(
                type_name(value)
            ),
            position,
        )
    # label "Error" so a thrown message reads as its own kind of trouble.
    return NovaError(value, position, label="Error")


def interpolate(values):
    return "".join(format_value(value) for value in values)


def loop_number(value, role, position):
    """One part of a `for` header must be a number."""
    if not is_number(value):
        raise NovaError(
            "{} must be a number, but this is {}".format(role, type_name(value)),
            position,
        )
    if isinstance(value, float) and not math.isfinite(value):
        # range_iterations would otherwise int() a NaN or infinity.
        raise NovaError(
            "{} must be a finite number, but this is {}".format(role, format_value(value)),
            position,
        )
    return value


def range_iterations(start, end, step, descending, position):
    """How many times a `for` range runs, worked out up front the way
    `range` does, so the loop cannot drift on floats and cannot be confused
    by the body reassigning the loop variable."""
    if step <= 0:
        raise NovaError(
            "a 'for' step must be greater than zero (use 'downto' to count down)",
            position,
        )
    span = (start - end) if descending else (end - start)
    return 0 if span < 0 else int(span / step + 1e-9) + 1


def range_value(start, step, index, descending):
    offset = index * step
    return start - offset if descending else start + offset


def iteration_items(iterable, two_names, position):
    """What `for ... in` walks: a snapshot, so changing the value inside the
    loop cannot make it run forever."""
    if isinstance(iterable, dict):
        # One name walks the keys; two walk key and value together.
        return list(iterable.items()) if two_names else list(iterable)
    if isinstance(iterable, (list, str)):
        return list(enumerate(iterable)) if two_names else list(iterable)
    raise NovaError(
        "'for ... in' needs a list, a string or a dictionary, but this is {}".format(
            type_name(iterable)
        ),
        position,
    )


def imported_name(exports, raw_path, name, position):
    if name not in exports:
        raise NovaError(
            'module "{}" has no exported {!r} - it exports {}'.format(
                raw_path, name, ", ".join(exports) or "nothing"
            ),
            position,
        )
    return exports[name]


# Which engine runs programs: "vm" (bytecode, the default) or "tree" (the
# original tree-walker, kept for comparison - `novalang.py --tree-walk`).
ENGINES = ("vm", "tree")
DEFAULT_ENGINE = "vm"
# Whether a plain Interpreter() gets the python.* namespace. Off; the
# command line's --allow-python turns it on for the run. Nova() does not read
# this: an embedding host decides for itself (Nova(allow_python=True)).
ALLOW_PYTHON = False



# ---------------------------------------------------------------------------
# The sandbox profile (docs/spec/16-sandbox.md)
# ---------------------------------------------------------------------------

# Which capability each gated name belongs to ([sbx.capabilities]). A name that is not here
# is a pure function (or the language itself) and is defined in every profile.
CAPABILITY_OF = {}
for _capability, _names in (
    ("files.read", ("read", "exists", "listdir")),
    ("files.write", ("write", "mkdir", "remove", "rename", "copy")),
    ("env", ("env",)),
    ("clock", ("time", "monotonic", "now", "sleep", "format_time")),
    ("random", ("random", "randint", "choice", "shuffle")),
    ("stdin", ("input",)),
    ("process", ("exit", "args", "platform", "cwd", "abspath", "realpath")),
    ("regex", ("regex", "replace_all")),
):
    for _name in _names:
        CAPABILITY_OF[_name] = _capability

# Windows with Python 3.7 resolves no symbolic link in os.path.realpath, so a path check would
# be weaker there without saying so. The restricted profile refuses to start instead.
SANDBOX_UNSUPPORTED = sys.platform == "win32" and sys.version_info < (3, 8)

SANDBOX_PROFILES = ("trusted", "restricted")
SANDBOX_SETTINGS = {
    "profile": str, "read": (list, tuple), "write": (list, tuple), "import_from": (list, tuple),
    "env": (list, tuple), "clock": bool, "random": bool, "stdin": bool, "process": bool,
    "regex": bool, "python": (list, tuple), "limits": dict,
    "deterministic": bool, "seed": int, "clock_start": (int, float),
}
# These three belong to both profiles ([sbx.determinism]); every other setting is a grant or a limit.
DETERMINISM_SETTINGS = ("deterministic", "seed", "clock_start")
SANDBOX_LIMITS = ("steps", "time", "output", "list", "string", "dict", "depth")


class FatalLimit(BaseException):
    """A limit that ends the run and cannot be caught: the step budget, the time limit and the output
    limit ([sbx.limits], kind `fatal`). It is not a NovaError and not even an Exception, so no `try`
    of a program, no `finally` block, no `except Exception` of the host's own conversions can see it.
    The places that end a run (the command line, the embedding API, the test harness) turn it into
    `LimitError: <message>`."""

    label = "LimitError"

    def __init__(self, message, position=None):
        BaseException.__init__(self, message)
        self.message = message
        self.position = position

    def render(self, source=None):
        return "LimitError: {}".format(self.message)

    def __str__(self):
        return "LimitError: {}".format(self.message)


# The reference values of the limits a `restricted` engine can lower but not raise, and the
# defaults of the three it can set freely ([sbx.limits]).
LIMIT_REFERENCE = {"list": 1000000, "string": 1000000, "dict": 1000000, "depth": MAX_CALL_DEPTH}
LIMIT_DEFAULTS = {"steps": 5000000, "time": 5000, "output": 1000000}


class Limits:
    """The numbers one engine enforces. The `trusted` profile has only the fixed limits of
    [port.limits]; `restricted` has all of them, lowered by the embedder if it wishes."""

    def __init__(self, restricted=False, overrides=None):
        overrides = overrides or {}
        self.list = overrides.get("list", LIMIT_REFERENCE["list"])
        self.string = overrides.get("string", LIMIT_REFERENCE["string"])
        self.depth = overrides.get("depth", LIMIT_REFERENCE["depth"])
        self.dict = overrides.get("dict", LIMIT_REFERENCE["dict"]) if restricted else None
        self.steps = overrides.get("steps", LIMIT_DEFAULTS["steps"]) if restricted else None
        self.time = overrides.get("time", LIMIT_DEFAULTS["time"]) if restricted else None
        self.output = overrides.get("output", LIMIT_DEFAULTS["output"]) if restricted else None


TRUSTED_LIMITS = Limits()


class Determinism:
    """The deterministic mode of an engine ([sbx.determinism]): a random generator the specification
    fixes, and a clock the program cannot read from the machine. The same program, seed and start
    time give the same output on every engine."""

    MODULUS = 1 << 64
    MULTIPLIER = 6364136223846793005          # Knuth's MMIX linear congruential generator
    INCREMENT = 1442695040888963407
    FIRST, LAST = -62135596800, 253402300800   # the years 1 to 9999, as seconds from 1970

    def __init__(self, seed, start):
        self.state = seed % self.MODULUS
        self.start = start
        self.elapsed = 0.0                      # virtual seconds slept so far

    def next53(self):
        """The next 53 random bits, as a whole number below 2**53."""
        self.state = (self.MULTIPLIER * self.state + self.INCREMENT) % self.MODULUS
        return self.state >> 11

    def below(self, n):
        """A whole number from 0 up to but not including n (n a positive whole number)."""
        return (self.next53() * n) >> 53

    def time(self):
        return self.start + self.elapsed


def utc_parts(seconds, position, who):
    """(datetime, microseconds) for a time given in seconds, in UTC, or the error of a time out of range."""
    if seconds != seconds or seconds in (float("inf"), float("-inf")) or not Determinism.FIRST <= seconds < Determinism.LAST:
        raise NovaError("{}: that time is out of range".format(who), position, label="TypeError")
    whole = math.floor(seconds)
    micro = round((seconds - whole) * 1000000)
    if micro >= 1000000:
        whole, micro = whole + 1, micro - 1000000
    return datetime(1970, 1, 1) + timedelta(seconds=whole), micro


def deterministic_iso(seconds, position):
    stamp, micro = utc_parts(seconds, position, "now()")
    return stamp.isoformat() + (".{:06d}".format(micro) if micro else "") + "+00:00"


DETERMINISTIC_DIRECTIVES = "YmdHMSjy%"


def deterministic_format(seconds, fmt, position):
    """format_time() in the deterministic mode: UTC, and exactly the directives every host must support."""
    stamp, _ = utc_parts(seconds, position, "format_time()")
    out, i = [], 0
    while i < len(fmt):
        ch = fmt[i]
        if ch != "%":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(fmt):
            raise NovaError("format_time(): a format cannot end with '%'", position, label="TypeError")
        d = fmt[i + 1]
        if d not in DETERMINISTIC_DIRECTIVES:
            raise NovaError("format_time(): '%{}' is not supported in the deterministic mode".format(d),
                            position, label="TypeError")
        out.append({"Y": "{:04d}".format(stamp.year), "m": "{:02d}".format(stamp.month),
                    "d": "{:02d}".format(stamp.day), "H": "{:02d}".format(stamp.hour),
                    "M": "{:02d}".format(stamp.minute), "S": "{:02d}".format(stamp.second),
                    "j": "{:03d}".format(stamp.timetuple().tm_yday), "y": "{:02d}".format(stamp.year % 100),
                    "%": "%"}[d])
        i += 2
    return "".join(out)


def fatal_error(fatal):
    """The error the embedding API raises for a fatal limit: `LimitError: step budget of ...`."""
    return NovaLangError(NovaError(fatal.message, fatal.position, label="LimitError"))


def sandbox_error(message):
    """A mistake in the sandbox configuration, as the embedding API reports it:
    `NovaLangError: unknown sandbox setting 'allow_reed'` ([sbx.profiles])."""
    return NovaLangError(NovaError(message, None, label="NovaLangError"))


def inside_folder(real, root):
    """Is the real path `real` the folder `root` or something below it? A folder whose name merely
    starts with `root`'s (`data2` beside `data`) is not."""
    real, root = os.path.normcase(real), os.path.normcase(root)
    try:
        return os.path.commonpath([real, root]) == root
    except ValueError:                  # another drive: certainly outside
        return False


def real_path(path):
    """The real, absolute path `path` names: symbolic links followed, `..` resolved after them, a
    part that does not exist judged by its closest existing parent ([sbx.paths] 1 and 3). A path
    that cannot be resolved is not a path of ours: None."""
    try:
        return os.path.realpath(path)
    except (ValueError, OSError):
        return None


class Capabilities:
    """What an engine's programs may reach. `Capabilities()` is the `trusted` profile: everything,
    as NovaLang has always behaved. `Capabilities(profile="restricted", read=[...], ...)` denies
    every capability that is not granted ([sbx.profiles])."""

    def __init__(self, profile="trusted", **settings):
        self.settings = dict(settings, profile=profile)
        for name, value in self.settings.items():
            if name not in SANDBOX_SETTINGS:
                raise sandbox_error("unknown sandbox setting {!r}".format(name))
            if not isinstance(value, SANDBOX_SETTINGS[name]) or (
                    isinstance(value, bool) and name in ("seed", "clock_start")) or (
                    SANDBOX_SETTINGS[name] is bool and not isinstance(value, bool)):
                raise sandbox_error("sandbox setting {!r} has a value of the wrong kind".format(name))
        if profile not in SANDBOX_PROFILES:
            raise sandbox_error("sandbox profile must be one of {}, not {!r}".format(SANDBOX_PROFILES, profile))
        self.restricted = profile == "restricted"
        if self.restricted and SANDBOX_UNSUPPORTED:
            raise sandbox_error("the restricted profile needs Python 3.8 or later on Windows: Python 3.7 "
                                "does not follow symbolic links when it resolves a path")
        if not self.restricted and any(name not in DETERMINISM_SETTINGS and name != "profile" for name in self.settings):
            raise sandbox_error("grants and limits belong to the 'restricted' profile, not 'trusted'")
        if ("seed" in settings or "clock_start" in settings) and not settings.get("deterministic"):
            raise sandbox_error("'seed' and 'clock_start' need deterministic=True")
        self.determinism = ((settings.get("seed", 0), float(settings.get("clock_start", 0.0)))
                            if settings.get("deterministic") else None)
        if self.determinism is not None and not -62135596800 <= self.determinism[1] < 253402300800:
            raise sandbox_error("'clock_start' must be a time in the years 1 to 9999")
        limits = settings.get("limits", {})
        for name, value in limits.items():
            if name not in SANDBOX_LIMITS or isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise sandbox_error("unknown sandbox limit {!r}, or a value that is not a positive "
                                    "whole number".format(name))
        for name, value in limits.items():
            if name in LIMIT_REFERENCE and value > LIMIT_REFERENCE[name]:
                raise sandbox_error("limit {!r} can be lowered but not raised above {}".format(
                    name, LIMIT_REFERENCE[name]))
        self.limits = dict(limits)
        self.limit_values = Limits(self.restricted, limits) if self.restricted else TRUSTED_LIMITS
        here = os.getcwd()
        resolve = lambda folder: real_path(os.path.join(here, folder))     # noqa: E731
        self.roots = {
            "read": [resolve(f) for f in settings.get("read", ())],
            "write": [resolve(f) for f in settings.get("write", ())],
            "import": [resolve(f) for f in settings.get("import_from", ())],
        }
        self.env_names = frozenset(settings.get("env", ()))
        self.python = tuple(settings.get("python", ()))
        self.flags = {name: bool(settings.get(name, False)) for name in ("clock", "random", "stdin", "process", "regex")}

    def has(self, capability):
        """Is `capability` granted? Everything is, in the trusted profile."""
        if not self.restricted:
            return True
        if capability == "files.read":
            return bool(self.roots["read"])
        if capability == "files.write":
            return bool(self.roots["write"])
        if capability == "import":
            return bool(self.roots["import"])
        if capability == "env":
            return bool(self.env_names)
        if capability == "python":
            return bool(self.python)
        return self.flags[capability]

    def defines(self, name):
        """Is the built-in `name` defined for this engine's programs?"""
        capability = CAPABILITY_OF.get(name)
        return capability is None or self.has(capability)

    def env_visible(self, name):
        return not self.restricted or name in self.env_names

    def denied(self, capability, position):
        return NovaError("the {!r} capability is not granted".format(capability), position)

    def check_path(self, path, kind, position, label="FileError"):
        """Raise unless `path` lies inside a folder granted for `kind` ([sbx.paths])."""
        if not self.restricted or not isinstance(path, str):
            return                      # a non-string is the function's own error, in its own order
        real = real_path(path)
        if real is not None and any(inside_folder(real, root) for root in self.roots[kind]):
            return
        raise NovaError("{} is outside the folders this program may use".format(path), position, label=label)

    def python_modules(self):
        """The modules `python.import` accepts on the script's own say."""
        return self.python if self.restricted else PYTHON_IMPORT_ALLOWLIST


TRUSTED = Capabilities()

# What the command line chose (--profile restricted --allow-read DIR ...). Like ALLOW_PYTHON it
# is read by the programs the command line runs; Nova() does not read it, an embedding host
# decides for itself (Nova(profile="restricted", ...)).
DEFAULT_CAPABILITIES = TRUSTED


class ProgramExit(Exception):
    """exit() in a `restricted` engine: ends the run, never the embedder's process."""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


class Interpreter:
    def __init__(self, engine=None, allow_python=None, capabilities=None):
        self.engine = engine or DEFAULT_ENGINE
        if self.engine not in ENGINES:
            raise ValueError("engine must be one of {}, not {!r}".format(ENGINES, engine))
        # python.* is off unless asked for (docs/design/python-bridge-hardening.md,
        # D3): --allow-python for the command line, Nova(allow_python=True) for a host.
        self.caps = capabilities if capabilities is not None else DEFAULT_CAPABILITIES
        self.limits = self.caps.limit_values
        self.det = Determinism(*self.caps.determinism) if self.caps.determinism else None
        self.counting = self.caps.restricted           # steps, time and output are counted
        self.entries = 0                                # runs in progress (a host callback is not a new run)
        self.begin_counters()
        self.allow_python = ALLOW_PYTHON if allow_python is None else allow_python
        if self.caps.restricted:
            self.allow_python = self.caps.has("python")      # the grant is the switch ([sbx.capabilities])
        self.globals = self.new_global_scope()
        self.env = self.globals
        self.call_stack = []            # function names, innermost last

        # Stage 12: the NovaLang-side half of the embedding bridge. Empty
        # by default - a plain `python3 novalang.py script.nova` run has
        # nothing exposed except the modules in PYTHON_IMPORT_ALLOWLIST,
        # importable on demand. An embedding Python program populates this
        # via Nova.expose()/Nova.expose_module() before running a script,
        # which is the only way a NovaLang script reaches anything here -
        # there is no path from `python.*` to an unregistered object.
        self.python_registry = {}
        # Names of modules a script may be handed beyond the allowlist: the
        # ones the embedding program exposed on purpose, each by its own name.
        self.python_granted = set()

        # Module machinery (Stage 9). file_stack tracks the directory of
        # whichever file is currently executing, for resolving a relative
        # import; it starts empty, meaning "no current file - use cwd only".
        self.file_stack = []
        self.import_stack = []          # resolved paths currently loading
        self.modules = {}               # resolved path -> its exports dict
        self.type_cache = None          # the type gate's results (a GateCache)
        self.current_exports = {}       # name -> value, for the module now loading

    python_override = None              # the self-hosted engine's grant (bootstrap.py)

    # -- the limits of a run ([sbx.limits]) ---------------------------------

    def begin_counters(self):
        self.steps = 0
        self.output_bytes = 0
        self.deadline = None
        limits = self.limits
        self.start_time = time.monotonic()
        if limits.time is not None:
            self.deadline = self.start_time + limits.time / 1000.0
        self.next_check = self.check_interval(0)

    def check_interval(self, steps):
        """The step count at which step_slow() must look again: the budget, or the next time check."""
        if not self.counting:
            return float("inf")
        interval = steps + 1000 if self.deadline is not None else float("inf")
        if self.limits.steps is not None:
            interval = min(interval, self.limits.steps + 1)
        return interval

    @contextlib.contextmanager
    def running(self):
        """One run of a program, or one call a host makes into it: the counters start from zero
        unless a run is already in progress (a host function called back into the script is part of
        the same run, so it cannot reset the budget)."""
        if self.entries == 0:
            self.begin_counters()
        self.entries += 1
        try:
            yield self
        finally:
            self.entries -= 1

    def step(self, position=None):
        """One pass of a loop or one call. Cheap: the clock is looked at every 1000 steps."""
        self.steps += 1
        if self.steps >= self.next_check:
            self.step_slow(position)

    def step_slow(self, position):
        limits = self.limits
        if limits.steps is not None and self.steps > limits.steps:
            raise FatalLimit("step budget of {} steps exhausted - is there a loop that never ends?".format(
                limits.steps), position)
        self.check_time(position)
        self.next_check = self.check_interval(self.steps)

    def check_time(self, position, extra_ms=0.0):
        """End the run if the time limit has passed, or would pass after `extra_ms` more waiting."""
        if self.deadline is not None and time.monotonic() + extra_ms / 1000.0 > self.deadline:
            raise FatalLimit("time limit of {} ms exceeded".format(self.limits.time), position)

    def write_output(self, text, stream, position=None):
        """Write one line of the program's output, counted in bytes: the write that would pass the limit is
        not made at all ([sbx.limits], output)."""
        if self.counting and self.limits.output is not None:
            size = len(text.encode("utf-8", "replace")) + 1
            if self.output_bytes + size > self.limits.output:
                raise FatalLimit("output limit of {} bytes exceeded".format(self.limits.output), position)
            self.output_bytes += size
        print(text, file=stream)

    def python_allowlist(self):
        if self.python_override is not None:
            return self.python_override
        return self.caps.python_modules()

    def lookup_builtin(self, name, position=None):
        """The built-in `name`, or None when this engine's profile does not define it: a denied name
        is exactly as undefined as one the program never wrote ([sbx.capabilities])."""
        function = BUILTINS.get(name)
        if function is None or not self.caps.defines(name):
            return None
        return function

    def new_global_scope(self):
        """A program's global scope, and a module's: a module is a fresh
        program, so it starts with the same predefined names ([mod.scope])."""
        scope = Environment(barrier=True)
        # Stage 11: predefined globals, not reserved builtin names - an
        # ordinary `let PI = 3` shadows these in its own scope, the same
        # as it would shadow any other predefined variable.
        scope.define("PI", math.pi)
        scope.define("E", math.e)
        scope.define("json", dict(JSON_NAMESPACE))
        scope.define("python", dict(PYTHON_NAMESPACE if self.allow_python
                                    else PYTHON_DISABLED_NAMESPACE))
        return scope

    # -- dispatch -----------------------------------------------------------

    def evaluate(self, node):
        method = getattr(self, "visit_" + type(node).__name__, None)
        if method is None:
            raise NovaError("cannot evaluate {}".format(type(node).__name__))
        return method(node)

    def execute_block(self, block):
        """Run statements in the *current* scope; the last value wins."""
        result = NOTHING
        for statement in block.statements:
            result = self.evaluate(statement)
        return result

    def execute_scoped_block(self, block, parent=None):
        """Run a block in a fresh child scope, so its new names vanish after."""
        saved = self.env
        self.env = Environment(parent=parent or saved)
        try:
            return self.execute_block(block)
        finally:
            self.env = saved

    # -- programs and blocks ------------------------------------------------

    def visit_ProgramNode(self, node):
        result = NOTHING
        for statement in node.statements:
            result = self.evaluate(statement)
        return result

    def visit_BlockNode(self, node):
        return self.execute_scoped_block(node)

    # -- literals and names -------------------------------------------------

    def visit_NumberNode(self, node):
        return node.value

    def visit_StringNode(self, node):
        return node.value

    def visit_BooleanNode(self, node):
        return node.value

    def visit_VarNode(self, node):
        if node.name in BUILTINS:
            function = self.lookup_builtin(node.name)
            if function is None:
                raise NovaError("undefined name {!r}".format(node.name), node.position)
            return function
        if not self.env.has(node.name):
            raise NovaError("undefined name {!r}".format(node.name), node.position)
        return self.env.get(node.name)

    def visit_AssignNode(self, node):
        value = self.evaluate(node.value)
        self.env.assign(node.name, value)
        return value

    def visit_LetNode(self, node):
        # `let` always binds here, shadowing anything outside this scope.
        value = self.evaluate(node.value)
        self.env.define(node.name, value)
        return value

    def visit_ListNode(self, node):
        # A list may hold any mix of values, so nothing to check here.
        return [self.evaluate(item_node) for item_node in node.items]

    def visit_DictNode(self, node):
        entries = {}
        for entry in node.entries:
            entries[entry.key] = self.evaluate(entry.value)
        return entries

    def visit_IndexNode(self, node):
        target = self.evaluate(node.target)
        index = self.evaluate(node.index)
        return index_operation(target, index, node.position)

    def visit_MemberNode(self, node):
        return member_operation(self.evaluate(node.target), node.name, node.position)

    def visit_MemberAssignNode(self, node):
        target = self.evaluate(node.target)
        member_assign_target(target, node.position)
        value = self.evaluate(node.value)
        if self.counting and self.limits.dict is not None and node.name not in target \
                and len(target) >= self.limits.dict:
            raise NovaError("a dictionary cannot hold more than {} entries".format(self.limits.dict),
                            node.position)
        target[node.name] = value                       # a new key is fine
        return value

    def visit_TryNode(self, node):
        # The outer try/finally is Python's, so `finally` runs on the way out
        # no matter what left the block: normal completion, a caught error, an
        # error still on its way up, or a return / break / continue.
        fatal = False
        try:
            try:
                self.execute_scoped_block(node.body)
            except NovaError as error:
                if node.catch_block is None:
                    raise
                self.run_catch(node, error)
        except FatalLimit:
            fatal = True            # not a NovaError: no catch sees it, and no finally block runs ([sbx.limits])
            raise
        finally:
            if node.finally_block is not None and not fatal:
                self.execute_scoped_block(node.finally_block)
        return NOTHING

    def run_catch(self, node, error):
        """Run the catch block, with the message bound if a name was given."""
        saved = self.env
        self.env = Environment(parent=saved)
        try:
            if node.catch_name is not None:
                self.env.define(node.catch_name, error_text(error))
            self.execute_block(node.catch_block)
        finally:
            self.env = saved

    def visit_ThrowNode(self, node):
        raise throw_error(self.evaluate(node.value), node.position)

    def visit_ImportNode(self, node):
        exports = self.import_module(node.path, node.position)
        if node.names is not None:
            for name in node.names:
                self.env.define(name, imported_name(exports, node.path, name, node.position))
        else:
            module_name = node.alias or default_module_name(node.path, node.position)
            self.env.define(module_name, exports)
        return NOTHING

    def import_module(self, raw_path, position):
        """Load (once) the module `raw_path` names; its exports dict."""
        if self.caps.restricted and not self.caps.has("import"):
            raise NovaError("the 'import' capability is not granted", position, label="ImportError")
        resolved = self.resolve_import(raw_path, position)
        return self.load_module(resolved, raw_path, position)

    def visit_ExportNode(self, node):
        value = self.evaluate(node.inner)
        self.current_exports[node.inner.name] = value
        return value

    def resolve_import(self, raw_path, position):
        """A package name goes through resolve_package; a file path is
        searched relative to the importing file, then the current directory."""
        current_dir = self.file_stack[-1] if self.file_stack else None
        if is_package_import(raw_path):
            found = resolve_package(raw_path, current_dir, position)
            self.caps.check_path(found, "import", position, label="ImportError")
            return found
        candidates = []
        if current_dir is not None:
            candidates.append(os.path.normpath(os.path.join(current_dir, raw_path)))
        candidates.append(os.path.normpath(os.path.join(os.getcwd(), raw_path)))
        if self.caps.restricted:
            # Judge every place before looking in any of them, so a path outside the grant is
            # refused whether or not a file is there ([sbx.paths] 4).
            granted = []
            for candidate in candidates:
                real = real_path(candidate)
                if real is not None and any(inside_folder(real, root) for root in self.caps.roots["import"]):
                    granted.append(candidate)
            if not granted:
                raise NovaError("{} is outside the folders this program may use".format(raw_path),
                                position, label="ImportError")
            candidates = granted

        tried = []
        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            tried.append(candidate)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)

        raise NovaError(
            'cannot find module "{}" - looked in:\n{}'.format(
                raw_path, "\n".join("  " + path for path in tried)
            ),
            position, label="ImportError",
        )

    def load_module(self, resolved_path, raw_path, position):
        """Run a file once and cache its exports, keyed by resolved path.

        A second `import` of the same file - by any name, from anywhere -
        reuses this cache, so modules behave like singletons: two importers
        share the same dictionary and see each other's changes to it.
        """
        if resolved_path in self.modules:
            return self.modules[resolved_path]

        if resolved_path in self.import_stack:
            cycle = self.import_stack[self.import_stack.index(resolved_path):] + [resolved_path]
            chain = " -> ".join(module_label(path) for path in cycle)
            raise NovaError(
                "circular import: {}".format(chain), position, label="ImportError"
            )

        try:
            with open(resolved_path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError as problem:
            raise NovaError(
                'cannot read module "{}": {}'.format(
                    raw_path, problem.strerror or "cannot be opened"
                ),
                position, label="ImportError",
            )

        # A module gets its own top-level scope, its own call stack and its
        # own set of exports - it is a fresh program, not a shared block.
        saved = (self.globals, self.env, self.call_stack, self.current_exports)
        self.globals = self.new_global_scope()
        self.env = self.globals
        self.call_stack = []
        self.current_exports = {}
        self.import_stack.append(resolved_path)
        self.file_stack.append(os.path.dirname(resolved_path))

        loaded = False
        try:
            try:
                run(source, self, resolved_path)
            except NovaError as error:
                raise NovaError(
                    'while loading module "{}":\n{}'.format(
                        raw_path, indent_lines(error.render(source))
                    ),
                    position, label="ImportError",
                ) from None
            else:
                exports = self.current_exports
                loaded = True
        finally:
            if not loaded and self.type_cache is not None:
                # The one time this file (and so anything checked against
                # it) is read again is a retry after this failure.
                self.type_cache.clear()
            self.file_stack.pop()
            self.import_stack.pop()
            self.globals, self.env, self.call_stack, self.current_exports = saved

        self.modules[resolved_path] = exports
        return exports

    def visit_DeleteFileNode(self, node):
        return self.delete_file(self.evaluate(node.path), node.position)

    def visit_DeleteNode(self, node):
        target = self.evaluate(node.target)
        delete_target(target, node.position)
        return delete_key(target, self.evaluate(node.key), node.position)

    def visit_SliceNode(self, node):
        target = self.evaluate(node.target)
        slice_target(target, node.position)
        start = None if node.start is None else slice_bound(
            self.evaluate(node.start), node.position)
        end = None if node.end is None else slice_bound(
            self.evaluate(node.end), node.position)
        # Slices clamp instead of failing: "Hello"[1:99] is "ello".
        return target[start:end]

    def visit_InterpolationNode(self, node):
        parts = [self.evaluate(part) for part in node.parts]
        if self.counting and text_would_exceed(parts, self.limits.string):
            raise self.string_too_long(node.position)
        return "".join(format_value(part) for part in parts)

    def visit_IndexAssignNode(self, node):
        target = self.evaluate(node.target)
        if isinstance(target, dict):
            key = index_assign_key(target, self.evaluate(node.index), node.position)
            return index_assign(target, key, self.evaluate(node.value), node.position, self.limits_if_counting())
        index_assign_target(target, node.position)
        index = self.evaluate(node.index)
        value = self.evaluate(node.value)
        return index_assign(target, index, value, node.position, self.limits_if_counting())

    # -- operators ----------------------------------------------------------

    def visit_UnaryOpNode(self, node):
        return unary_operation(node.op, self.evaluate(node.operand), node.position)

    def visit_NotNode(self, node):
        return not_operation(self.evaluate(node.operand), node.position)

    def visit_LogicalOpNode(self, node):
        left = logical_side(self.evaluate(node.left), "left", node.op, node.position)
        # Short-circuit: the right side is never evaluated when the left
        # side already decides the answer.
        if node.op == "and" and not left:
            return False
        if node.op == "or" and left:
            return True
        return logical_side(self.evaluate(node.right), "right", node.op, node.position)

    def visit_BinOpNode(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        return binary_operation(node.op, left, right, node.position, self.limits_if_counting())

    def visit_CompareNode(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        return compare_operation(node.op, left, right, node.position)

    # -- control flow -------------------------------------------------------

    def condition_value(self, node, keyword):
        return condition_check(self.evaluate(node.condition), keyword, node.position)

    def visit_IfNode(self, node):
        if self.condition_value(node, "if"):
            return self.execute_scoped_block(node.then_block)
        if node.else_block is not None:
            return self.evaluate(node.else_block)   # BlockNode or an else-if
        return NOTHING

    def visit_WhileNode(self, node):
        broke = False
        while self.condition_value(node, "while"):
            if self.counting:
                self.step(node.position)
            try:
                self.execute_scoped_block(node.body)
            except ContinueSignal:
                continue
            except BreakSignal:
                broke = True
                break

        # Like Python: the `else` runs only if the loop was never broken out of.
        if node.else_block is not None and not broke:
            self.execute_scoped_block(node.else_block)
        return NOTHING

    def visit_ForNode(self, node):
        where = node.position
        start = self.loop_number(node.start, "the start of a 'for' range", where)
        end = self.loop_number(node.end, "the end of a 'for' range", where)
        step = 1 if node.step is None else self.loop_number(node.step, "a 'for' step", where)
        iterations = range_iterations(start, end, step, node.descending, node.position)

        # The loop variable lives in a scope of its own, so it does not leak.
        loop_env = Environment(parent=self.env)
        saved = self.env
        self.env = loop_env
        broke = False
        try:
            index = 0
            while index < iterations:
                if self.counting:
                    self.step(node.position)
                loop_env.define(node.name, range_value(start, step, index, node.descending))
                try:
                    self.execute_scoped_block(node.body, parent=loop_env)
                except ContinueSignal:
                    pass
                except BreakSignal:
                    broke = True
                    break
                index += 1
        finally:
            self.env = saved

        if node.else_block is not None and not broke:
            self.execute_scoped_block(node.else_block)
        return NOTHING

    def visit_ForInNode(self, node):
        items = iteration_items(self.evaluate(node.iterable), bool(node.second_name),
                                node.position)
        loop_env = Environment(parent=self.env)
        saved = self.env
        self.env = loop_env
        broke = False
        try:
            for item in items:
                if self.counting:
                    self.step(node.position)
                if node.second_name:
                    loop_env.define(node.name, item[0])
                    loop_env.define(node.second_name, item[1])
                else:
                    loop_env.define(node.name, item)
                try:
                    self.execute_scoped_block(node.body, parent=loop_env)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    broke = True
                    break
        finally:
            self.env = saved

        if node.else_block is not None and not broke:
            self.execute_scoped_block(node.else_block)
        return NOTHING

    def loop_number(self, node, role, fallback_position):
        """Evaluate one part of a `for` header, insisting on a number."""
        return loop_number(self.evaluate(node), role,
                           getattr(node, "position", None) or fallback_position)

    def visit_BreakNode(self, node):
        raise BreakSignal(node.position)

    def visit_ContinueNode(self, node):
        raise ContinueSignal(node.position)

    def visit_ReturnNode(self, node):
        value = NOTHING if node.value is None else self.evaluate(node.value)
        raise ReturnSignal(value)

    # -- functions ----------------------------------------------------------

    def visit_FunctionDefNode(self, node):
        function = NovaFunction(node.name, node.params, node.body, self.env)
        self.env.define(node.name, function)
        return function

    def visit_CallNode(self, node):
        callee = self.evaluate(node.callee)
        args = [self.evaluate(arg) for arg in node.args]
        return self.call_value(callee, args, node.position)

    def limits_if_counting(self):
        return self.limits if self.counting else None

    def check_call_arguments(self, callee, args, position):
        """The size checks a built-in's operands allow before it builds anything ([sbx.limits])."""
        limits, name = self.limits, callee.name
        if name == "append" and args and isinstance(args[0], list) and len(args[0]) >= limits.list:
            raise NovaError("a list cannot grow beyond {} items".format(limits.list), position)
        if name == "range" and 1 <= len(args) <= 3 and all(is_number(a) for a in args):
            count = range_count(args, position)
            if count is not None and count > limits.list:
                raise NovaError("range() would build a list of {} items, which is too large".format(count),
                                position)
        if name == "join" and len(args) == 2 and isinstance(args[0], list) and isinstance(args[1], str):
            # at least one character for each item, and the separators between them
            if len(args[0]) + len(args[1]) * max(len(args[0]) - 1, 0) > limits.string:
                raise self.string_too_long(position)
        if name in ("pad", "pad_left") and len(args) == 2 and is_number(args[1]) and args[1] > limits.string:
            raise self.string_too_long(position)
        if name == "replace_all" and len(args) == 3 and all(isinstance(a, str) for a in args) and args[1]:
            grown = len(args[0]) + args[0].count(args[1]) * max(len(args[2]) - len(args[1]), 0)
            if grown > limits.string:
                raise self.string_too_long(position)
        if name in ("str", "print", "log", "join") and args:
            if text_would_exceed(args if name in ("print", "log") else args[:1], limits.string):
                raise self.string_too_long(position)

    def string_too_long(self, position):
        return NovaError("a string cannot grow beyond {} characters".format(self.limits.string), position)

    def check_result_size(self, result, position):
        """What a built-in returned may not be longer than the limits ([sbx.limits])."""
        limits = self.limits
        if isinstance(result, str):
            if len(result) > limits.string:
                raise self.string_too_long(position)
        elif isinstance(result, list):
            if len(result) > limits.list:
                raise NovaError("a list cannot grow beyond {} items".format(limits.list), position)

    def check_file_append(self, path, position):
        """The file form of append() is a write: it needs `files.write` and a folder."""
        if not self.caps.has("files.write"):
            raise self.caps.denied("files.write", position)
        self.caps.check_path(path, "write", position)

    def delete_file(self, path, position):
        """The `delete` statement of a file: a write ([sbx.capabilities])."""
        if self.caps.restricted:
            if not self.caps.has("files.write"):
                raise self.caps.denied("files.write", position)
            self.caps.check_path(path, "write", position)
        return delete_file(path, position)

    def call_value(self, callee, args, position):
        """Call an already-evaluated callee with already-evaluated args -
        shared by ordinary CallNode evaluation and by map/filter/reduce,
        which call back into a NovaLang function value of their own."""
        if isinstance(callee, BuiltinFunction):
            if callee.arity is not None and len(args) != callee.arity:
                raise NovaError(
                    "{}() takes {} argument(s) but got {}".format(
                        callee.name, callee.arity, len(args)
                    ),
                    position,
                )
            try:
                if self.counting:
                    self.step(position)
                    self.check_call_arguments(callee, args, position)
                if self.caps.restricted:
                    for index, kind in callee.paths:
                        if index < len(args):
                            self.caps.check_path(args[index], kind, position)
                    if callee.name == "append" and args and isinstance(args[0], str):
                        self.check_file_append(args[0], position)
                if callee.needs_interpreter:
                    result = callee.implementation(args, position, self)
                else:
                    result = callee.implementation(args, position)
                if self.counting:
                    self.check_result_size(result, position)
                return bounded_integer(result, position)
            except OverflowError:
                # math.sqrt(10 ** 400) and friends: an integer beyond a float.
                raise NovaError("{}(): a number is too large for this function".format(callee.name),
                                position, label="TypeError") from None

        if not isinstance(callee, NovaFunction):
            raise NovaError(
                "{} is not a function, so it cannot be called".format(type_name(callee)),
                position,
            )

        if len(args) != len(callee.params):
            raise NovaError(
                "{}() expects {} argument(s) but got {}".format(
                    callee.name, len(callee.params), len(args)
                ),
                position,
            )

        if self.counting:
            self.step(position)
        if len(self.call_stack) >= self.limits.depth:
            raise NovaError(
                "call depth of {} exceeded - is the recursion missing a base case?".format(
                    self.limits.depth
                ),
                position,
            )

        if callee.code is not None:
            # A compiled function: the VM runs it (and everything it calls),
            # popping this name, attaching the stack trace and turning a
            # stray break/continue into an error exactly as below.
            self.call_stack.append(callee.name)
            return execute(self, function_frame(callee, args))

        # A fresh barrier scope per call: this is what makes recursion work,
        # what keeps locals from leaking, and what stops an assignment inside
        # a function from reaching out and rewriting a global. Its parent is
        # where the function was defined, not where it was called from.
        frame = Environment(parent=callee.closure, barrier=True)
        for name, value in zip(callee.params, args):
            frame.define(name, value)

        saved_env = self.env
        self.call_stack.append(callee.name)
        self.env = frame
        try:
            self.execute_block(callee.body)
            return NOTHING                      # fell off the end without return
        except ReturnSignal as signal:
            return signal.value
        except (BreakSignal, ContinueSignal) as signal:
            # A loop in the *caller* must not be broken by a stray keyword
            # in the callee's body.
            keyword = "break" if isinstance(signal, BreakSignal) else "continue"
            raise NovaError(
                "'{}' is not inside a loop in {}()".format(keyword, callee.name), signal.position
            )
        except NovaError as error:
            if error.stack is None:             # the innermost frame wins
                error.stack = ["{}()".format(name) for name in reversed(self.call_stack)]
            raise
        finally:
            self.env = saved_env
            self.call_stack.pop()


def is_number(value):
    # bool is a subclass of int in Python, so exclude it explicitly.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Packages (M2). `import "math-utils"` names a package installed by
# tools/nova-pkg.py; anything else - every path ending in .nova, or with a
# '/' in it - is a file, resolved exactly as before packages existed.
# ---------------------------------------------------------------------------

PACKAGE_NAME = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
PACKAGE_DIR = ".nova_modules"


def is_package_import(raw_path):
    return bool(PACKAGE_NAME.match(raw_path)) and not raw_path.endswith(".nova")


def resolve_package(name, start_dir, position):
    """The entry file of package `name`, found the way Node finds
    node_modules: walk up from `start_dir` (the importing file's directory,
    or the current directory) to the first `.nova_modules/<name>/nova.json`.
    Walking up is what lets a package's own imports find its dependencies,
    which nova-pkg installs side by side in the project's .nova_modules."""
    directory = os.path.abspath(start_dir or os.getcwd())
    searched = []
    while True:
        package = os.path.join(directory, PACKAGE_DIR, name)
        if os.path.isfile(os.path.join(package, "nova.json")):
            break
        searched.append(os.path.join(directory, PACKAGE_DIR))
        parent = os.path.dirname(directory)
        if parent == directory:
            raise NovaError(
                'cannot find package "{}" - looked in:\n{}\nIs it in nova.json, and has '
                "`python3 tools/nova-pkg.py install` been run?".format(
                    name, "\n".join("  " + path for path in searched[:6])
                    + ("\n  ..." if len(searched) > 6 else "")
                ),
                position, label="ImportError",
            )
        directory = parent

    check_installed(directory, position)
    manifest_path = os.path.join(package, "nova.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json_module.load(handle)
    except (OSError, ValueError) as problem:
        raise NovaError('package "{}" has an unreadable nova.json: {}'.format(name, problem),
                        position, label="ImportError")
    main = manifest.get("main", "main.nova") if isinstance(manifest, dict) else None
    if not isinstance(main, str) or not main.endswith(".nova"):
        raise NovaError('package "{}": "main" in its nova.json must name a .nova file'.format(name),
                        position, label="ImportError")
    entry = os.path.normpath(os.path.join(package, main))
    if not os.path.isfile(entry):
        raise NovaError('package "{}" has no entry file {}'.format(name, main),
                        position, label="ImportError")
    return entry


INSTALL_HINT = "run `python3 tools/nova-pkg.py install`"
_CHECKED_PROJECTS = set()


def check_installed(project_dir, position):
    """Stop the line if a project's installed packages are not exactly the
    ones its nova.json and nova.lock describe - nova.json edited without an
    install, a lockfile changed or deleted, an install that never finished.
    Checked once per project per run."""
    if project_dir in _CHECKED_PROJECTS:
        return
    modules = os.path.join(project_dir, PACKAGE_DIR)

    def refuse(problem):
        raise NovaError("the packages in {} cannot be used: {} - {}".format(
            modules, problem, INSTALL_HINT), position, label="ImportError")

    def text(name):
        try:
            with open(os.path.join(project_dir, name), "r", encoding="utf-8") as handle:
                return handle.read()
        except OSError:
            return None

    lock_text = text("nova.lock")
    if lock_text is None:
        refuse("there is no nova.lock beside them")
    try:
        lock = json_module.loads(lock_text)
        manifest = json_module.loads(text("nova.json") or "null")
    except ValueError:
        refuse("nova.json or nova.lock is not valid JSON")
    if not isinstance(manifest, dict) or not isinstance(lock, dict):
        refuse("there is no nova.json beside them")
    if lock.get("requires") != manifest.get("dependencies", {}):
        refuse("nova.json has changed since nova.lock was written")
    if text(os.path.join(PACKAGE_DIR, ".installed.lock")) != lock_text:
        refuse("they were not installed from the current nova.lock")
    _CHECKED_PROJECTS.add(project_dir)


def module_label(path):
    """How a module is named in messages: a file inside an installed
    package as <package>/<file> (every package's entry is main.nova, so a
    bare file name would not say which), any other file by its name."""
    marker = os.sep + PACKAGE_DIR + os.sep
    if marker in path:
        return path.rsplit(marker, 1)[1].replace(os.sep, "/")
    return os.path.basename(path)


def default_module_name(raw_path, position):
    """The name a bare `import "path.nova"` binds, absent an alias. A
    package binds its name with '-' and '.' made '_': "math-utils" binds
    math_utils."""
    if is_package_import(raw_path):
        stem = raw_path.replace("-", "_").replace(".", "_")
    else:
        stem = os.path.splitext(os.path.basename(raw_path))[0]
    if not is_bare_name(stem):
        raise NovaError(
            '"{}" does not make a valid module name - import it with \'as\' and choose one'
            .format(raw_path),
            position,
        )
    guard_name(stem, position, "a module")
    return stem


def indent_lines(text, prefix="  "):
    return "\n".join(prefix + line for line in text.split("\n"))


def error_text(error):
    """What `catch e` binds: the message, with a label only when it adds
    something. `throw("boom")` gives "boom"; a missing file gives
    "FileNotFoundError: data.txt"."""
    if error.label in ("NovaError", "Error"):
        return error.message
    return "{}: {}".format(error.label, error.message)


def nova_contains(needle, haystack, position):
    """`x in y` - a substring of a string, or an item of a list."""
    if isinstance(haystack, str):
        if not isinstance(needle, str):
            raise NovaError(
                "'in' can only look for a string inside a string, not {}".format(
                    type_name(needle)
                ),
                position,
            )
        return needle in haystack
    if isinstance(haystack, list):
        return any(nova_equals(needle, item) for item in haystack)
    if isinstance(haystack, dict):
        # For a dictionary, `in` asks about its keys.
        return dict_key(needle, position) in haystack
    raise NovaError(
        "'in' needs a list, a string or a dictionary on its right, but got {}".format(
            type_name(haystack)
        ),
        position,
    )


def nova_equals(left, right):
    """Equality never crosses types: true == 1 is false, not an error."""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, str) != isinstance(right, str):
        return False
    if (left is NOTHING) != (right is NOTHING):
        return False
    if left is NOTHING and right is NOTHING:
        return True
    if is_number(left) != is_number(right):
        return False
    if isinstance(left, list) or isinstance(right, list):
        if not (isinstance(left, list) and isinstance(right, list)):
            return False
        if len(left) != len(right):
            return False
        return all(nova_equals(a, b) for a, b in zip(left, right))
    if isinstance(left, dict) or isinstance(right, dict):
        if not (isinstance(left, dict) and isinstance(right, dict)):
            return False
        if set(left) != set(right):
            return False
        return all(nova_equals(left[key], right[key]) for key in left)
    return left == right


# ---------------------------------------------------------------------------
# The pipeline, in one place
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 5. Compiler  (AST -> bytecode)  - M4
# ---------------------------------------------------------------------------
#
# The compiler turns the same AST the tree-walking Interpreter runs into
# flat bytecode for a stack machine. It changes nothing about the language:
# every rule below reproduces something the Interpreter does, and the
# reason is written next to it.
#
# Scopes. The Interpreter keeps a chain of name -> value dictionaries:
# function calls and the global scope are barriers, blocks are not, a name
# first assigned in a block vanishes after it, reads walk the whole chain
# and assignments stop at the nearest barrier. Bytecode keeps the global
# scope as a dictionary (the REPL, imports and the embedding API all reach
# into it by name), and gives every other binding a numbered slot in its
# function's frame. That is possible because, inside one function body,
# whether a name exists at a given point is known at compile time: only a
# scope's own statements create names in it, and they run in order. So:
#
#   - a binding that is definitely there is a plain slot (LOAD_FAST);
#   - a slot that an inner function reads becomes a cell, shared with the
#     closure, so the inner function sees its value at the time it runs;
#   - an inner function's reads of outer names are genuinely dynamic - it
#     may run before or after those names exist - so they compile to a
#     chain of candidate cells, innermost first, ending in the globals
#     (LOAD_CHAIN): the first one that is set wins, exactly as walking the
#     dictionary chain does;
#   - at module level, a block cannot know whether a global already exists
#     (the REPL or the embedding API may have made it), so an assignment
#     there checks at run time (STORE_CHAIN), as the Interpreter does;
#   - entering a block makes fresh cells for its captured names, so a
#     closure made in each loop iteration keeps its own (NEW_CELLS).
#
# Values. Every statement has a value (run() and the REPL return the last
# one; an `if` gives its block's). A statement list leaves exactly the
# last statement's value on the stack. Loop state lives in hidden slots,
# so the stack is empty at every statement boundary and break/continue
# never need to clean it up.
#
# Errors. Each instruction records the source position of the node it came
# from, and checks happen in the Interpreter's order: `d[k] = v` checks k
# before evaluating v when d is a dictionary, and refuses a string before
# evaluating k at all. try/catch/finally use an exception table (no setup
# instruction): a catch entry takes NovaErrors; a finally entry takes any
# unwinding, so it also runs for the signals a stray `break` or a
# top-level `return` raise - which, as in the Interpreter, `catch` cannot
# intercept. `return`, `break` and `continue` that leave a try run its
# finally body first, inlined on that path.

OPCODES = [
    # stack
    "LOAD_CONST", "POP", "DUP",
    # names
    "LOAD_FAST", "STORE_FAST", "LOAD_CELL", "STORE_CELL",
    "LOAD_GLOBAL", "STORE_GLOBAL", "LOAD_CHAIN", "STORE_CHAIN", "NEW_CELLS", "RESET_SLOTS",
    "LOAD_BUILTIN",
    # arithmetic, comparison, logic
    "ADD", "SUB", "MUL", "DIV", "FLOOR_DIV", "MOD", "NEG", "POS", "NOT",
    "EQ", "NE", "LT", "GT", "LE", "GE", "IN",
    "CHECK_BOOL", "JUMP_IF_FALSE_KEEP", "JUMP_IF_TRUE_KEEP",
    # data
    "BUILD_LIST", "BUILD_DICT", "BUILD_STRING", "INDEX",
    "SLICE_TARGET", "SLICE_BOUND", "SLICE", "GET_MEMBER",
    "INDEX_ASSIGN_TARGET", "INDEX_ASSIGN_KEY", "INDEX_ASSIGN",
    "MEMBER_ASSIGN_TARGET", "SET_MEMBER",
    "DELETE_TARGET", "DELETE_KEY", "DELETE_FILE",
    # control
    "JUMP", "JUMP_IF_NOT_TRUE",
    "LOOP_NUMBER", "RANGE_PREP", "RANGE_NEXT", "ITER_PREP", "ITER_NEXT",
    # functions, errors, modules
    "MAKE_FUNCTION", "CALL", "RETURN", "THROW", "RERAISE", "STRAY", "FAIL",
    "IMPORT", "IMPORT_NAME", "EXPORT",
]
OP = {name: number for number, name in enumerate(OPCODES)}
JUMPS = frozenset(OP[name] for name in (
    "JUMP", "JUMP_IF_NOT_TRUE", "JUMP_IF_FALSE_KEEP", "JUMP_IF_TRUE_KEEP",
    "RANGE_NEXT", "ITER_NEXT"))

BINARY_OPS = {"+": "ADD", "-": "SUB", "*": "MUL", "/": "DIV", "//": "FLOOR_DIV", "%": "MOD"}
COMPARE_OPS = {"==": "EQ", "!=": "NE", "<": "LT", ">": "GT", "<=": "LE", ">=": "GE", "in": "IN"}


class Var:
    """One binding that lives in a frame slot: a name in one scope."""

    __slots__ = ("name", "scope", "slot", "captured", "maybe")

    def __init__(self, name, scope, slot):
        self.name = name
        self.scope = scope
        self.slot = slot
        self.captured = False           # read by an inner function: a cell
        self.maybe = False              # tested "is it set?" at run time


class GlobalVar:
    """A name in a module's global dictionary."""

    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name


class CScope:
    """A compile-time scope: the module's globals, a function's frame, or
    a block, loop or catch scope inside one."""

    def __init__(self, kind, parent, frame):
        self.kind = kind                # module | function | block | loop | catch
        self.parent = parent
        self.frame = frame
        self.vars = {}                  # name -> Var (every name ever bound here)
        self.status = {}                # name -> "definite" | "maybe", at this point

    @property
    def is_globals(self):
        return self.kind == "module"


class CFrame:
    """A compile-time frame: the module's top level, or one function."""

    def __init__(self, name, parent, def_scope, node):
        self.name = name
        self.parent = parent            # the enclosing CFrame, or None
        self.def_scope = def_scope      # the scope its `def` ran in
        self.node = node
        self.slot_names = []            # for the disassembler
        self.freevars = []              # Vars of enclosing frames, in closure order
        self.root = None

    def new_slot(self, label):
        self.slot_names.append(label)
        return len(self.slot_names) - 1

    def free_index(self, var):
        if var not in self.freevars:
            self.freevars.append(var)
        return self.freevars.index(var)


class Resolution:
    """What the resolver decided about every name in a program, keyed by the
    AST node that reads or writes it."""

    def __init__(self):
        self.reads = {}                 # id(VarNode) -> [Var | GlobalVar] candidates
        self.stores = {}                # id(node), name -> ("define" | "assign", [...])
        self.scopes = {}                # (kind, id(node)) -> CScope
        self.frames = {}                # id(FunctionDefNode | ProgramNode) -> CFrame


class Resolver:
    """Pass 1: walk each function body in order - the way it runs - and
    decide where every name lives. Function bodies are resolved after the
    frame that defines them, when every enclosing scope holds every name it
    will ever bind (the function may be called at any point after that)."""

    def __init__(self):
        self.result = Resolution()
        self.pending = []

    def resolve(self, program):
        frame = CFrame("<module>", None, None, program)
        root = CScope("module", None, frame)
        frame.root = root
        self.result.frames[id(program)] = frame
        self.result.scopes[("root", id(program))] = root
        self.scope = root
        self.statements(program.statements)
        while self.pending:
            function, def_scope = self.pending.pop(0)
            self.function(function, def_scope)
        return self.result

    # -- binding --------------------------------------------------------------

    def bind(self, scope, name):
        """`name` now definitely exists in `scope` (a define)."""
        if not scope.is_globals and name not in scope.vars:
            label = name if scope.kind in ("function", "module") else "{}@{}".format(
                name, scope.kind)
            scope.vars[name] = Var(name, scope, scope.frame.new_slot(label))
        scope.status[name] = "definite"
        return GlobalVar(name) if scope.is_globals else scope.vars[name]

    def define(self, node_key, name):
        self.result.stores[(node_key, name)] = ("define", [self.bind(self.scope, name)])

    def assign(self, node_key, name):
        """`name = ...`: update the innermost binding out to the nearest
        barrier, else create it here (Environment.assign)."""
        candidates = []
        scope = self.scope
        while True:
            if scope.is_globals:
                if scope.status.get(name) == "definite":
                    candidates.append(GlobalVar(name))
                    self.result.stores[(node_key, name)] = ("assign", candidates)
                    return
                # A global may or may not exist (the REPL or the embedding API
                # can create one), so this is decided when it runs.
                candidates.append(GlobalVar(name))
                break
            status = scope.status.get(name)
            if status == "definite":
                candidates.append(scope.vars[name])
                self.result.stores[(node_key, name)] = ("assign", candidates)
                return
            if status == "maybe":
                candidates.append(scope.vars[name])
            if scope.kind == "function":
                break                           # the barrier
            scope = scope.parent
        here = self.bind(self.scope, name)
        if self.scope.is_globals:
            self.result.stores[(node_key, name)] = ("assign", [here])
            return
        if candidates:
            self.scope.status[name] = "maybe"   # it might have gone to one of those
            here.maybe = True
        self.result.stores[(node_key, name)] = ("assign", candidates + [here])

    def read(self, node):
        if node.name in BUILTINS:
            return
        self.result.reads[id(node)] = self.lookup(node.name)

    def lookup(self, name):
        candidates = []
        scope = self.scope
        frame = scope.frame
        # This frame's own scopes: their contents at this point are known.
        while True:
            if scope.is_globals:
                candidates.append(GlobalVar(name))
                return candidates
            status = scope.status.get(name)
            if status == "definite":
                candidates.append(scope.vars[name])
                return candidates
            if status == "maybe":
                candidates.append(scope.vars[name])
            if scope.kind == "function":
                break
            scope = scope.parent
        # Enclosing frames: this function runs later, so any binding those
        # scopes ever make may be there - or not yet. Each is a candidate.
        while True:
            scope = frame.def_scope
            frame = scope.frame
            while True:
                if scope.is_globals:
                    candidates.append(GlobalVar(name))
                    return candidates
                var = scope.vars.get(name)
                if var is not None:
                    var.captured = True
                    candidates.append(var)
                if scope.kind == "function":
                    break
                scope = scope.parent

    # -- scopes -----------------------------------------------------------------

    def enter(self, kind, key_node, key="block"):
        scope = CScope(kind, self.scope, self.scope.frame)
        self.result.scopes[(key, id(key_node))] = scope
        self.scope = scope
        return scope

    def leave(self, scope):
        self.scope = scope.parent

    def block(self, block, names=(), kind="block", parent=None):
        saved = self.scope
        if parent is not None:
            self.scope = parent
        scope = self.enter(kind, block)
        for name in names:
            self.bind(scope, name)
        self.statements(block.statements)
        self.scope = saved

    def function(self, node, def_scope):
        frame = CFrame(node.name, def_scope.frame, def_scope, node)
        self.result.frames[id(node)] = frame
        root = CScope("function", def_scope, frame)
        frame.root = root
        self.result.scopes[("root", id(node))] = root
        saved = self.scope
        self.scope = root
        for param in node.params:
            self.bind(root, param)
        self.statements(node.body.statements)
        self.scope = saved

    # -- statements -------------------------------------------------------------

    def statements(self, statements):
        for statement in statements:
            self.visit(statement)

    def visit(self, node):
        method = getattr(self, "r_" + type(node).__name__, None)
        if method is None:
            for child in children(node):
                self.visit(child)
            return
        method(node)

    def r_VarNode(self, node):
        self.read(node)

    def r_LetNode(self, node):
        self.visit(node.value)
        self.define(id(node), node.name)

    def r_AssignNode(self, node):
        self.visit(node.value)
        self.assign(id(node), node.name)

    def r_FunctionDefNode(self, node):
        self.define(id(node), node.name)
        self.pending.append((node, self.scope))

    def r_ImportNode(self, node):
        if node.names is not None:
            for name in node.names:
                self.define(id(node), name)
            return
        try:
            name = node.alias or default_module_name(node.path, node.position)
        except NovaError as error:
            # Not a valid name: an error when the import runs - after the
            # module has loaded, as in the Interpreter - not before.
            node._name_error = error
            return
        self.define(id(node), name)

    def r_IfNode(self, node):
        self.visit(node.condition)
        self.block(node.then_block)
        if isinstance(node.else_block, IfNode):
            self.visit(node.else_block)
        elif node.else_block is not None:
            self.block(node.else_block)

    def r_WhileNode(self, node):
        self.visit(node.condition)
        self.block(node.body)
        if node.else_block is not None:
            self.block(node.else_block)

    def loop(self, node, names):
        outer = self.scope
        loop_scope = self.enter("loop", node, key="loop")
        for name in names:
            self.bind(loop_scope, name)
        node._state_slot = outer.frame.new_slot("<loop state>")
        self.block(node.body)
        self.scope = outer
        if node.else_block is not None:
            self.block(node.else_block)

    def r_ForNode(self, node):
        for part in (node.start, node.end, node.step):
            if part is not None:
                self.visit(part)
        self.loop(node, [node.name])

    def r_ForInNode(self, node):
        self.visit(node.iterable)
        self.loop(node, [node.name] if node.second_name is None else
                  [node.name, node.second_name])

    def r_TryNode(self, node):
        frame = self.scope.frame
        self.block(node.body)
        if node.catch_block is not None:
            names = [node.catch_name] if node.catch_name is not None else []
            self.block(node.catch_block, names, kind="catch")
        if node.finally_block is not None:
            node._finally_slot = frame.new_slot("<unwinding>")
            self.block(node.finally_block)


def children(node):
    """A node's child nodes, in evaluation order."""
    for value in vars(node).values():
        if isinstance(value, Node):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Node):
                    yield item


class CodeObject:
    """Compiled bytecode for one module or function."""

    def __init__(self, name, frame):
        self.name = name
        self.ops = []                   # opcode numbers
        self.args = []                  # one argument per instruction (or None)
        self.positions = []             # source position per instruction (or None)
        self.constants = []
        self.exception_table = []       # (start, end, handler, kind), innermost first
        self.slot_names = frame.slot_names
        self.nslots = 0
        self.params = []                # slots of the parameters, in order
        self.param_names = []
        self.cell_params = []           # the subset of those that are cells
        self.freevars = [var.name for var in frame.freevars]
        self.closure = []               # how MAKE_FUNCTION builds it (in the parent)

    def const(self, value):
        for index, existing in enumerate(self.constants):
            if existing is value or (type(existing) is type(value) and not isinstance(
                    value, (CodeObject, list, dict)) and existing == value):
                return index
        self.constants.append(value)
        return len(self.constants) - 1


class TryContext:
    """A try being compiled: where its protected ranges are, and its
    finally body (to inline on break/continue/return)."""

    def __init__(self, node, loops_depth):
        self.node = node
        self.finally_block = node.finally_block
        self.loops_depth = loops_depth  # loops around the try, not inside it
        self.catch_ranges = []          # closed [start, end) of the try body
        self.finally_ranges = []        # closed ranges of try body + catch body
        self.open_catch = None
        self.open_finally = None


class LoopContext:
    def __init__(self, tries_depth):
        self.tries_depth = tries_depth  # len(try stack) when the loop began
        self.breaks = []
        self.continues = []
        self.continue_target = None


class Compiler:
    """Pass 2: emit bytecode, using the resolver's decisions."""

    def __init__(self, resolution):
        self.resolution = resolution

    def compile_program(self, program):
        frame = self.resolution.frames[id(program)]
        code = CodeObject("<module>", frame)
        self.start(code, frame, self.resolution.scopes[("root", id(program))])
        self.statements(program.statements, True)
        self.emit("RETURN", None, None)
        return self.finish()

    def compile_function(self, node):
        frame = self.resolution.frames[id(node)]
        code = CodeObject(node.name, frame)
        root = self.resolution.scopes[("root", id(node))]
        saved = self.save()
        self.start(code, frame, root)
        code.params = [root.vars[name].slot for name in node.params]
        code.param_names = list(node.params)
        code.cell_params = [root.vars[name].slot for name in node.params
                            if root.vars[name].captured]
        self.new_cells(root, skip=set(node.params))
        self.statements(node.body.statements, False)
        self.emit("LOAD_CONST", code.const(NOTHING), None)
        self.emit("RETURN", None, None)
        finished = self.finish()
        self.restore(saved)
        return finished

    def start(self, code, frame, scope):
        self.code = code
        self.frame = frame
        self.scope = scope
        self.tries = []
        self.loops = []

    def save(self):
        return (self.code, self.frame, self.scope, self.tries, self.loops)

    def restore(self, saved):
        self.code, self.frame, self.scope, self.tries, self.loops = saved

    def finish(self):
        self.code.nslots = len(self.frame.slot_names)
        # Read last: compiling inner functions adds to this frame's free list.
        self.code.freevars = [var.name for var in self.frame.freevars]
        return self.code

    # -- emitting ---------------------------------------------------------------

    def emit(self, name, arg, position):
        self.code.ops.append(OP[name])
        self.code.args.append(arg)
        self.code.positions.append(position)
        return len(self.code.ops) - 1

    def here(self):
        return len(self.code.ops)

    def patch(self, at, target=None):
        self.code.args[at] = self.here() if target is None else target

    def jump(self, name, position=None, extra=None):
        """Emit a forward jump; returns its index for patch()."""
        return self.emit(name, extra, position)

    # -- locations ----------------------------------------------------------------

    def location(self, var):
        """('fast'|'cell'|'free'|'global', index or name) for a variable."""
        if isinstance(var, GlobalVar):
            return ("global", var.name)
        if var.scope.frame is self.frame:
            return ("cell" if var.captured else "fast", var.slot)
        return ("free", self.frame_free_index(var))

    def frame_free_index(self, var):
        return self.frame.free_index(var)

    def load(self, candidates, position):
        if len(candidates) == 1:
            kind, where = self.location(candidates[0])
            # A closure's read is always a chain (it ends in the globals),
            # so a single candidate is never "free".
            op = {"fast": "LOAD_FAST", "cell": "LOAD_CELL", "global": "LOAD_GLOBAL"}[kind]
            self.emit(op, where, position)
            return
        chain = tuple(self.location(var) for var in candidates)
        self.emit("LOAD_CHAIN", self.code.const(chain), position)

    def store(self, node, name, position):
        _, candidates = self.resolution.stores[(id(node), name)]
        if len(candidates) == 1:
            kind, where = self.location(candidates[0])
            op = {"fast": "STORE_FAST", "cell": "STORE_CELL", "global": "STORE_GLOBAL"}[kind]
            self.emit(op, where, position)
            return
        chain = tuple(self.location(var) for var in candidates)
        self.emit("STORE_CHAIN", self.code.const(chain), position)

    def new_cells(self, scope, skip=()):
        """On entering a scope: fresh cells for its captured names, and its
        maybe-slots emptied. A scope is new each time it is entered (each
        loop iteration), and a slot whose "is it set?" is tested at run
        time must not still hold the last time's value."""
        ordered = sorted(scope.vars.items(), key=lambda item: item[1].slot)
        cells = tuple(var.slot for name, var in ordered if var.captured and name not in skip)
        if cells:
            self.emit("NEW_CELLS", self.code.const(cells), None)
        resets = tuple(var.slot for name, var in ordered if var.maybe and not var.captured)
        if resets:
            self.emit("RESET_SLOTS", self.code.const(resets), None)

    # -- statement lists and blocks -----------------------------------------------

    def statements(self, statements, want):
        """Compile a statement list; if `want`, leave the last one's value."""
        if not statements:
            if want:
                self.emit("LOAD_CONST", self.code.const(NOTHING), None)
            return
        for index, statement in enumerate(statements):
            last = index == len(statements) - 1
            self.statement(statement, want and last)

    def block(self, block, want):
        scope = self.resolution.scopes[("block", id(block))]
        saved = self.scope
        self.scope = scope
        self.new_cells(scope)
        self.statements(block.statements, want)
        self.scope = saved

    def statement(self, node, want):
        method = getattr(self, "s_" + type(node).__name__, None)
        if method is not None:
            method(node, want)
            return
        self.expression(node)
        if not want:
            self.emit("POP", None, None)

    # -- statements ---------------------------------------------------------------

    def s_LetNode(self, node, want):
        self.value(node.value)
        if want:
            self.emit("DUP", None, None)
        self.store(node, node.name, node.position)

    def s_AssignNode(self, node, want):
        self.value(node.value)
        if want:
            self.emit("DUP", None, None)
        self.store(node, node.name, node.position)

    def s_IndexAssignNode(self, node, want):
        self.index_assign(node)
        if not want:
            self.emit("POP", None, None)

    def s_MemberAssignNode(self, node, want):
        self.member_assign(node)
        if not want:
            self.emit("POP", None, None)

    def value(self, node):
        """The right side of '=' - an expression, or a nested assignment
        (a = b = 3), which leaves its value."""
        if isinstance(node, AssignNode):
            self.value(node.value)
            self.emit("DUP", None, None)
            self.store(node, node.name, node.position)
        elif isinstance(node, IndexAssignNode):
            self.index_assign(node)
        elif isinstance(node, MemberAssignNode):
            self.member_assign(node)
        else:
            self.expression(node)

    def index_assign(self, node):
        self.expression(node.target)
        self.emit("INDEX_ASSIGN_TARGET", None, node.position)   # a string: refused now
        self.expression(node.index)
        self.emit("INDEX_ASSIGN_KEY", None, node.position)      # a dict: key checked now
        self.value(node.value)
        self.emit("INDEX_ASSIGN", None, node.position)

    def member_assign(self, node):
        self.expression(node.target)
        self.emit("MEMBER_ASSIGN_TARGET", None, node.position)
        self.value(node.value)
        self.emit("SET_MEMBER", self.code.const(node.name), node.position)

    def s_FunctionDefNode(self, node, want):
        self.make_function(node)
        if want:
            self.emit("DUP", None, None)
        self.store(node, node.name, node.position)

    def make_function(self, node):
        child = self.compile_function(node)
        frame = self.resolution.frames[id(node)]
        child.closure = [self.location(var) for var in frame.freevars]
        self.emit("MAKE_FUNCTION", self.code.const(child), node.position)

    def s_ExportNode(self, node, want):
        inner = node.inner
        if isinstance(inner, FunctionDefNode):
            self.make_function(inner)
        else:
            self.value(inner.value)
        self.emit("DUP", None, None)
        self.store(inner, inner.name, inner.position)
        self.emit("EXPORT", self.code.const(inner.name), node.position)
        if not want:
            self.emit("POP", None, None)

    def s_ReturnNode(self, node, want):
        if node.value is not None:
            self.expression(node.value)
        else:
            self.emit("LOAD_CONST", self.code.const(NOTHING), node.position)
        if self.frame.parent is None:
            # Top level: the value is worked out, then it is an error - after
            # any enclosing finally has run, which the signal's unwinding does.
            self.emit("POP", None, None)
            self.emit("STRAY", self.code.const("return"), node.position)
            return
        if any(t.finally_block is not None for t in self.tries):
            slot = self.return_slot()
            self.emit("STORE_FAST", slot, None)
            self.inline_finally(0)
            self.emit("LOAD_FAST", slot, None)
        self.emit("RETURN", None, node.position)

    def return_slot(self):
        if not hasattr(self.frame, "return_slot"):
            self.frame.return_slot = self.frame.new_slot("<return value>")
        return self.frame.return_slot

    def s_BreakNode(self, node, want):
        self.loop_exit(node, "break")

    def s_ContinueNode(self, node, want):
        self.loop_exit(node, "continue")

    def loop_exit(self, node, keyword):
        if not self.loops:
            # Not in a loop of this frame: an error when it runs, after the
            # finally blocks it leaves (the caller reports it, as before).
            self.emit("STRAY", self.code.const(keyword), node.position)
            return
        loop = self.loops[-1]
        self.inline_finally(loop.tries_depth)
        at = self.jump("JUMP", node.position)
        (loop.breaks if keyword == "break" else loop.continues).append(at)

    def inline_finally(self, down_to):
        """Run the finally bodies of the tries being left, innermost first.
        While a finally body runs here, its own try's protection is off (an
        error in it must not run it twice), and so is every inner one's."""
        for index in range(len(self.tries) - 1, down_to - 1, -1):
            context = self.tries[index]
            if context.finally_block is None:
                continue
            for inner in self.tries[index:]:
                self.suspend(inner)
            # Compile the copy where the finally block really is: outside
            # this try and every loop inside it, so a `break` in it leaves
            # the loops around the try (or is stray), as when it runs normally.
            saved_tries, saved_loops = self.tries, self.loops
            self.tries = self.tries[:index]
            self.loops = self.loops[:context.loops_depth]
            self.block(context.finally_block, False)
            self.tries, self.loops = saved_tries, saved_loops
            for inner in self.tries[index:]:
                self.resume(inner)

    def suspend(self, context):
        if context.open_catch is not None:
            context.catch_ranges.append((context.open_catch, self.here()))
            context.open_catch = None
            context.catch_suspended = True
        if context.open_finally is not None:
            context.finally_ranges.append((context.open_finally, self.here()))
            context.open_finally = None
            context.finally_suspended = True

    def resume(self, context):
        if getattr(context, "catch_suspended", False):
            context.open_catch = self.here()
            context.catch_suspended = False
        if getattr(context, "finally_suspended", False):
            context.open_finally = self.here()
            context.finally_suspended = False

    def s_ThrowNode(self, node, want):
        self.expression(node.value)
        self.emit("THROW", None, node.position)

    def s_IfNode(self, node, want):
        self.expression(node.condition)
        test = self.jump("JUMP_IF_NOT_TRUE", node.position, extra=None)
        self.code.args[test] = (self.code.const("if"), None)
        self.block(node.then_block, want)
        if node.else_block is None:
            if want:
                skip = self.jump("JUMP")
                self.code.args[test] = (self.code.args[test][0], self.here())
                self.emit("LOAD_CONST", self.code.const(NOTHING), None)
                self.patch(skip)
            else:
                self.code.args[test] = (self.code.args[test][0], self.here())
            return
        skip = self.jump("JUMP")
        self.code.args[test] = (self.code.args[test][0], self.here())
        if isinstance(node.else_block, IfNode):
            self.s_IfNode(node.else_block, want)
        else:
            self.block(node.else_block, want)
        self.patch(skip)

    def s_WhileNode(self, node, want):
        loop = LoopContext(len(self.tries))
        top = self.here()
        loop.continue_target = top
        self.expression(node.condition)
        test = self.jump("JUMP_IF_NOT_TRUE", node.position)
        self.code.args[test] = (self.code.const("while"), None)
        self.loops.append(loop)
        self.block(node.body, False)
        self.loops.pop()
        self.emit("JUMP", top, None)
        self.code.args[test] = (self.code.args[test][0], self.here())
        self.loop_end(node, loop, want)

    def loop_end(self, node, loop, want):
        """The `else` (only when the loop was not broken out of), then the
        loop's value."""
        for at in loop.continues:
            self.patch(at, loop.continue_target)
        if node.else_block is not None:
            self.block(node.else_block, False)
        for at in loop.breaks:
            self.patch(at)
        if want:
            self.emit("LOAD_CONST", self.code.const(NOTHING), None)

    def s_ForNode(self, node, want):
        for part, role in ((node.start, "the start of a 'for' range"),
                           (node.end, "the end of a 'for' range"),
                           (node.step, "a 'for' step")):
            if part is None:
                continue
            self.expression(part)
            self.emit("LOOP_NUMBER", self.code.const(role),
                      getattr(part, "position", None) or node.position)
        self.emit("RANGE_PREP", (node._state_slot, node.descending, node.step is not None),
                  node.position)
        self.loop_body(node, "RANGE_NEXT", [node.name], want)

    def s_ForInNode(self, node, want):
        self.expression(node.iterable)
        names = [node.name] if node.second_name is None else [node.name, node.second_name]
        self.emit("ITER_PREP", (node._state_slot, len(names)), node.position)
        self.loop_body(node, "ITER_NEXT", names, want)

    def loop_body(self, node, next_op, names, want):
        outer = self.scope
        loop_scope = self.resolution.scopes[("loop", id(node))]
        self.scope = loop_scope
        self.new_cells(loop_scope)      # once per loop: one binding across iterations
        loop = LoopContext(len(self.tries))
        top = self.here()
        loop.continue_target = top
        step = self.emit(next_op, (node._state_slot, None), node.position)
        # Store the loop variables (an ITER_NEXT with two names pushes two).
        for name in reversed(names):
            var = loop_scope.vars[name]
            kind, where = self.location(var)
            self.emit("STORE_CELL" if kind == "cell" else "STORE_FAST", where, None)
        self.loops.append(loop)
        self.block(node.body, False)
        self.loops.pop()
        self.emit("JUMP", top, None)
        self.code.args[step] = (node._state_slot, self.here())
        self.scope = outer
        self.loop_end(node, loop, want)

    def s_TryNode(self, node, want):
        context = TryContext(node, len(self.loops))
        self.tries.append(context)
        context.open_catch = self.here() if node.catch_block is not None else None
        context.open_finally = self.here() if node.finally_block is not None else None
        self.block(node.body, False)
        if context.open_catch is not None:
            context.catch_ranges.append((context.open_catch, self.here()))
            context.open_catch = None
        to_finally = self.jump("JUMP")
        catch_handler = None
        if node.catch_block is not None:
            catch_handler = self.here()
            # The handler starts with the error's text on the stack.
            scope = self.resolution.scopes[("block", id(node.catch_block))]
            saved = self.scope
            self.scope = scope
            self.new_cells(scope)
            if node.catch_name is not None:
                kind, where = self.location(scope.vars[node.catch_name])
                self.emit("STORE_CELL" if kind == "cell" else "STORE_FAST", where, node.position)
            else:
                self.emit("POP", None, None)
            self.statements(node.catch_block.statements, False)
            self.scope = saved
        if context.open_finally is not None:
            context.finally_ranges.append((context.open_finally, self.here()))
            context.open_finally = None
        self.tries.pop()
        self.patch(to_finally)
        if node.finally_block is not None:
            self.block(node.finally_block, False)           # the normal way out
            done = self.jump("JUMP")
            unwinding = self.here()                          # an error or a signal
            self.emit("STORE_FAST", node._finally_slot, None)
            self.block(node.finally_block, False)
            self.emit("RERAISE", node._finally_slot, None)
            self.patch(done)
        for start, end in context.catch_ranges:
            if end > start:
                self.code.exception_table.append((start, end, catch_handler, "catch"))
        if node.finally_block is not None:
            for start, end in context.finally_ranges:
                if end > start:
                    self.code.exception_table.append((start, end, unwinding, "finally"))
        if want:
            self.emit("LOAD_CONST", self.code.const(NOTHING), None)

    def s_ImportNode(self, node, want):
        self.emit("IMPORT", self.code.const(node.path), node.position)
        if node.names is not None:
            for name in node.names:
                self.emit("DUP", None, None)
                self.emit("IMPORT_NAME", self.code.const((name, node.path)), node.position)
                self.store(node, name, node.position)
            self.emit("POP", None, None)
        elif getattr(node, "_name_error", None) is not None:
            error = node._name_error
            self.emit("FAIL", self.code.const((error.message, error.label)), node.position)
            return
        else:
            self.store(node, node.alias or default_module_name(node.path, node.position),
                       node.position)
        if want:
            self.emit("LOAD_CONST", self.code.const(NOTHING), None)

    def s_DeleteNode(self, node, want):
        self.expression(node.target)
        self.emit("DELETE_TARGET", None, node.position)
        self.expression(node.key)
        self.emit("DELETE_KEY", None, node.position)
        if not want:
            self.emit("POP", None, None)

    def s_DeleteFileNode(self, node, want):
        self.expression(node.path)
        self.emit("DELETE_FILE", None, node.position)
        if not want:
            self.emit("POP", None, None)

    # -- expressions --------------------------------------------------------------

    def expression(self, node):
        getattr(self, "e_" + type(node).__name__)(node)

    def e_NumberNode(self, node):
        self.emit("LOAD_CONST", self.code.const(node.value), None)

    e_StringNode = e_NumberNode
    e_BooleanNode = e_NumberNode

    def e_VarNode(self, node):
        if node.name in BUILTINS:
            if node.name in CAPABILITY_OF:
                # A gated name is looked up in the engine that runs the code, so the same compiled
                # script is right for a trusted and for a restricted engine ([sbx.capabilities]).
                self.emit("LOAD_BUILTIN", node.name, node.position)
            else:
                self.emit("LOAD_CONST", self.code.const(BUILTINS[node.name]), node.position)
            return
        self.load(self.resolution.reads[id(node)], node.position)

    def e_UnaryOpNode(self, node):
        self.expression(node.operand)
        self.emit("NEG" if node.op == "-" else "POS", None, node.position)

    def e_NotNode(self, node):
        self.expression(node.operand)
        self.emit("NOT", None, node.position)

    def e_BinOpNode(self, node):
        self.expression(node.left)
        self.expression(node.right)
        self.emit(BINARY_OPS[node.op], None, node.position)

    def e_CompareNode(self, node):
        self.expression(node.left)
        self.expression(node.right)
        self.emit(COMPARE_OPS[node.op], None, node.position)

    def e_LogicalOpNode(self, node):
        self.expression(node.left)
        self.emit("CHECK_BOOL", self.code.const(("left", node.op)), node.position)
        jump = self.jump("JUMP_IF_FALSE_KEEP" if node.op == "and" else "JUMP_IF_TRUE_KEEP")
        self.expression(node.right)
        self.emit("CHECK_BOOL", self.code.const(("right", node.op)), node.position)
        self.patch(jump)

    def e_ListNode(self, node):
        for item in node.items:
            self.expression(item)
        self.emit("BUILD_LIST", len(node.items), node.position)

    def e_DictNode(self, node):
        for entry in node.entries:
            self.expression(entry.value)
        keys = tuple(entry.key for entry in node.entries)
        self.emit("BUILD_DICT", self.code.const(keys), node.position)

    def e_InterpolationNode(self, node):
        for part in node.parts:
            self.expression(part)
        self.emit("BUILD_STRING", len(node.parts), node.position)

    def e_IndexNode(self, node):
        self.expression(node.target)
        self.expression(node.index)
        self.emit("INDEX", None, node.position)

    def e_SliceNode(self, node):
        # The target is checked before the bounds are evaluated, and each
        # bound is made a whole number as soon as it is.
        self.expression(node.target)
        self.emit("SLICE_TARGET", None, node.position)
        for bound in (node.start, node.end):
            if bound is not None:
                self.expression(bound)
                self.emit("SLICE_BOUND", None, node.position)
        self.emit("SLICE", (node.start is not None, node.end is not None), node.position)

    def e_MemberNode(self, node):
        self.expression(node.target)
        self.emit("GET_MEMBER", self.code.const(node.name), node.position)

    def e_CallNode(self, node):
        self.expression(node.callee)
        for arg in node.args:
            self.expression(arg)
        self.emit("CALL", len(node.args), node.position)

    # An assignment can only appear as a statement or on the right of '='.
    def e_AssignNode(self, node):
        self.value(node)

    e_IndexAssignNode = e_AssignNode
    e_MemberAssignNode = e_AssignNode


def compile_ast(program):
    """Compile a parsed program (a ProgramNode) to a module CodeObject."""
    resolution = Resolver().resolve(program)
    return Compiler(resolution).compile_program(program)


def compile_source(source):
    return compile_ast(Parser(Lexer(source).tokenize()).parse())


# -- checking and showing bytecode ----------------------------------------------

# How each instruction changes the stack depth (arg-dependent ones are
# functions of the argument).
STACK_EFFECT = {
    "LOAD_CONST": 1, "POP": -1, "DUP": 1,
    "LOAD_FAST": 1, "STORE_FAST": -1, "LOAD_CELL": 1, "STORE_CELL": -1,
    "LOAD_GLOBAL": 1, "STORE_GLOBAL": -1, "LOAD_CHAIN": 1, "STORE_CHAIN": -1, "NEW_CELLS": 0, "RESET_SLOTS": 0,
    "LOAD_BUILTIN": 1,
    "ADD": -1, "SUB": -1, "MUL": -1, "DIV": -1, "FLOOR_DIV": -1, "MOD": -1,
    "NEG": 0, "POS": 0, "NOT": 0,
    "EQ": -1, "NE": -1, "LT": -1, "GT": -1, "LE": -1, "GE": -1, "IN": -1,
    "CHECK_BOOL": 0, "JUMP_IF_FALSE_KEEP": -1, "JUMP_IF_TRUE_KEEP": -1,
    "BUILD_LIST": lambda n: 1 - n, "BUILD_DICT": None, "BUILD_STRING": lambda n: 1 - n,
    "INDEX": -1, "SLICE_TARGET": 0, "SLICE_BOUND": 0, "SLICE": lambda flags: -sum(flags),
    "GET_MEMBER": 0,
    "INDEX_ASSIGN_TARGET": 0, "INDEX_ASSIGN_KEY": 0, "INDEX_ASSIGN": -2,
    "MEMBER_ASSIGN_TARGET": 0, "SET_MEMBER": -1,
    "DELETE_TARGET": 0, "DELETE_KEY": -1, "DELETE_FILE": 0,
    "JUMP": 0, "JUMP_IF_NOT_TRUE": -1,
    "LOOP_NUMBER": 0, "RANGE_PREP": None, "RANGE_NEXT": None, "ITER_PREP": -1,
    "ITER_NEXT": None,
    "MAKE_FUNCTION": 1, "CALL": lambda n: -n, "RETURN": -1, "THROW": -1, "RERAISE": 0,
    "STRAY": 0, "FAIL": 0, "IMPORT": 1, "IMPORT_NAME": 0, "EXPORT": 0,
}
ENDS_FLOW = frozenset(OP[name] for name in ("JUMP", "RETURN", "THROW", "RERAISE", "STRAY",
                                            "FAIL"))


def jump_target(code, index):
    arg = code.args[index]
    return arg[1] if isinstance(arg, tuple) else arg


def stack_effect(code, index):
    name = OPCODES[code.ops[index]]
    arg = code.args[index]
    effect = STACK_EFFECT[name]
    if name == "BUILD_DICT":
        return 1 - len(code.constants[arg])
    if name == "RANGE_PREP":
        return -(2 + arg[2])            # start, end and maybe step, into the state slot
    if callable(effect):
        return effect(arg)
    return effect


def branch_effect(code, index):
    """(depth change if the jump is taken, if it falls through)."""
    name = OPCODES[code.ops[index]]
    if name in ("JUMP_IF_FALSE_KEEP", "JUMP_IF_TRUE_KEEP"):
        return 0, -1
    if name == "RANGE_NEXT":
        return 0, 1                     # the loop variable, when there is one
    if name == "ITER_NEXT":
        count = code.args[index][0]
        return 0, None                  # resolved from the ITER_PREP that set the slot
    effect = stack_effect(code, index)
    return effect, effect


class BytecodeError(Exception):
    pass


def verify(code):
    """Check one CodeObject (and the functions in it) is well formed: every
    jump lands inside the code, every slot and constant exists, no path
    falls off the end, and the stack depth agrees wherever paths meet and
    never goes negative. A compiler bug is caught here, before any VM runs
    the code."""
    count = len(code.ops)
    iter_names = {}
    for index in range(count):
        name = OPCODES[code.ops[index]]
        arg = code.args[index]
        if name == "ITER_PREP":
            iter_names[arg[0]] = arg[1]
        if code.ops[index] in JUMPS:
            target = jump_target(code, index)
            if not isinstance(target, int) or not 0 <= target < count:
                raise BytecodeError("{}: instruction {} jumps to {}".format(code.name, index, target))
        if name in ("LOAD_FAST", "STORE_FAST", "LOAD_CELL", "STORE_CELL", "RERAISE") and not (
                0 <= arg < code.nslots):
            raise BytecodeError("{}: instruction {} uses slot {}".format(code.name, index, arg))
    depth = {0: 0}
    work = [0]
    for start, end, handler, kind in code.exception_table:
        if not (0 <= start < end <= count and 0 <= handler < count):
            raise BytecodeError("{}: bad exception table entry".format(code.name))
        if handler not in depth:
            depth[handler] = 1          # the error (or its text) is pushed
            work.append(handler)
        elif depth[handler] != 1:
            raise BytecodeError("{}: handler {} entered at two depths".format(code.name, handler))
    while work:
        index = work.pop()
        here = depth[index]
        if index >= count:
            raise BytecodeError("{}: execution falls off the end".format(code.name))
        op = code.ops[index]
        name = OPCODES[op]
        if name == "ITER_NEXT":
            taken, through = 0, iter_names.get(code.args[index][0], 1)
        else:
            taken, through = branch_effect(code, index)
        nexts = []
        if op in JUMPS:
            nexts.append((jump_target(code, index), here + taken))
        if op not in ENDS_FLOW:
            nexts.append((index + 1, here + through))
        if name == "RETURN" and here != 1:
            raise BytecodeError("{}: RETURN at depth {}".format(code.name, here))
        for target, new in nexts:
            if new < 0:
                raise BytecodeError("{}: the stack underflows at {}".format(code.name, index))
            if target in depth:
                if depth[target] != new:
                    raise BytecodeError("{}: depth {} and {} meet at {}".format(
                        code.name, depth[target], new, target))
            else:
                depth[target] = new
                work.append(target)
    for constant in code.constants:
        if isinstance(constant, CodeObject):
            verify(constant)
    return True


def show_constant(value):
    if isinstance(value, CodeObject):
        return "<code {}>".format(value.name)
    if isinstance(value, BuiltinFunction):
        return "<built-in {}>".format(value.name)
    if value is NOTHING:
        return "nothing"
    if isinstance(value, tuple) and all(isinstance(item, tuple) for item in value):
        return " -> ".join("{}:{}".format(kind, where) for kind, where in value)
    return repr(value)


def disassemble(code, source=None):
    """Readable text for a CodeObject and every function inside it."""
    lines = []
    line_of = (lambda pos: None) if source is None else LineLookup(source)
    queue = [code]
    while queue:
        current = queue.pop(0)
        header = "code {}".format(current.name)
        if current.params:
            header += "({})".format(", ".join(current.slot_names[s] for s in current.params))
        lines.append(header)
        if current.slot_names:
            lines.append("  slots: " + ", ".join(
                "{}={}".format(index, name) for index, name in enumerate(current.slot_names)))
        if current.freevars:
            lines.append("  free:  " + ", ".join(
                "{}={}".format(index, name) for index, name in enumerate(current.freevars)))
        if current.closure:
            lines.append("  closure (made from the enclosing frame): " + ", ".join(
                "{}:{}".format(kind, where) for kind, where in current.closure))
        targets = {jump_target(current, i) for i in range(len(current.ops))
                   if current.ops[i] in JUMPS}
        targets |= {entry[2] for entry in current.exception_table}
        last_line = None
        for index, op in enumerate(current.ops):
            name = OPCODES[op]
            arg = current.args[index]
            line = line_of(current.positions[index])
            shown_line = "" if line is None or line == last_line else str(line)
            if line is not None:
                last_line = line
            text = describe_arg(current, name, arg)
            marker = ">>" if index in targets else "  "
            lines.append("  {:>4} {} {:4d} {:<21}{}".format(
                shown_line, marker, index, name, text).rstrip())
        for start, end, handler, kind in current.exception_table:
            lines.append("  exception: {}-{} -> {} ({})".format(start, end - 1, handler, kind))
        lines.append("")
        queue.extend(c for c in current.constants if isinstance(c, CodeObject))
    return "\n".join(lines)


def describe_arg(code, name, arg):
    if arg is None:
        return ""
    if name in ("LOAD_CONST", "LOAD_CHAIN", "STORE_CHAIN", "BUILD_DICT", "GET_MEMBER",
                "SET_MEMBER", "EXPORT", "IMPORT", "IMPORT_NAME", "STRAY", "FAIL", "LOOP_NUMBER",
                "CHECK_BOOL", "NEW_CELLS", "RESET_SLOTS", "MAKE_FUNCTION"):
        value = code.constants[arg]
        if name in ("NEW_CELLS", "RESET_SLOTS"):
            return " ".join("{}({})".format(s, code.slot_names[s]) for s in value)
        if name == "CHECK_BOOL":
            return "{} side of '{}'".format(*value)
        return "{} ({})".format(arg, show_constant(value))
    if name in ("LOAD_FAST", "STORE_FAST", "LOAD_CELL", "STORE_CELL", "RERAISE"):
        return "{} ({})".format(arg, code.slot_names[arg])
    if name in ("LOAD_GLOBAL", "STORE_GLOBAL"):
        return arg
    if name == "JUMP_IF_NOT_TRUE":
        return "to {} ({} condition)".format(arg[1], code.constants[arg[0]])
    if name in ("RANGE_NEXT", "ITER_NEXT"):
        return "{} ({}), done: to {}".format(arg[0], code.slot_names[arg[0]], arg[1])
    if name == "RANGE_PREP":
        return "{} ({}){}{}".format(arg[0], code.slot_names[arg[0]],
                                    " downto" if arg[1] else "", " +step" if arg[2] else "")
    if name == "ITER_PREP":
        return "{} ({}), {} name{}".format(arg[0], code.slot_names[arg[0]], arg[1],
                                           "s" if arg[1] > 1 else "")
    if name in ("JUMP", "JUMP_IF_FALSE_KEEP", "JUMP_IF_TRUE_KEEP"):
        return "to {}".format(arg)
    if name == "SLICE":
        return "[{}:{}]".format("start" if arg[0] else "", "end" if arg[1] else "")
    return str(arg)


class LineLookup:
    def __init__(self, source):
        self.starts = [start for start, _ in line_spans(source)]

    def __call__(self, position):
        if position is None:
            return None
        return bisect.bisect_right(self.starts, position)


# ---------------------------------------------------------------------------
# 6. Virtual machine  (bytecode -> a value)  - M4
# ---------------------------------------------------------------------------
#
# Runs what the Compiler makes. One execute() call runs a frame and every
# NovaLang function it calls - calls push a Frame and stay in the same
# loop, so NovaLang recursion does not use Python's stack. Python recurses
# only where Python calls back into NovaLang (map/filter/reduce, the
# embedding API), through Interpreter.call_value, exactly as before.
#
# What each operation means is the shared functions above; this loop only
# moves values between the stack, slots and cells. Errors follow the
# Interpreter: the exception table finds a handler (a catch takes a
# NovaError and starts with its text; a finally takes anything and starts
# with the exception, which RERAISE raises again); an error leaving a
# function gets its stack trace there if it has none yet; a stray
# break/continue leaving a function becomes, in the caller, the same error
# Interpreter.call_value raised; MAX_CALL_DEPTH is checked on every call.

class Unset:
    """A slot or cell with nothing in it yet."""

    __slots__ = ()

    def __repr__(self):
        return "<unset>"


UNSET = Unset()


class Cell:
    """A binding a closure shares with the frame that made it."""

    __slots__ = ("value",)

    def __init__(self, value=UNSET):
        self.value = value


class Frame:
    __slots__ = ("code", "slots", "stack", "ip", "cells", "globals", "function")

    def __init__(self, code, slots, cells, globals_, function):
        self.code = code
        self.slots = slots
        self.stack = []
        self.ip = 0
        self.cells = cells              # the closure: Cells from enclosing frames
        self.globals = globals_         # the defining module's global dictionary
        self.function = function        # the NovaFunction, or None for a module


class VMError(Exception):
    """The VM broke one of its own invariants - a bug in NovaLang itself,
    never in the program being run, so it is not a NovaError."""


class StraySignal(Exception):
    """A `break` or `continue` outside a loop, or `return` at the top level,
    when it runs. `catch` cannot intercept it; `finally` still runs, as with
    the Interpreter's Break/Continue/ReturnSignal."""

    def __init__(self, kind, position):
        super().__init__(kind)
        self.kind = kind
        self.position = position


def module_frame(code, globals_):
    return Frame(code, [UNSET] * code.nslots, (), globals_, None)


def function_frame(function, args):
    code = function.code
    slots = [UNSET] * code.nslots
    for slot, value in zip(code.params, args):
        slots[slot] = value
    for slot in code.cell_params:
        slots[slot] = Cell(slots[slot])
    return Frame(code, slots, function.cells, function.globals, function)


def stray_error(signal, function_name):
    """What a stray signal leaving a function becomes (Interpreter.call_value)."""
    return NovaError("'{}' is not inside a loop in {}()".format(signal.kind, function_name),
                     signal.position)


def top_level_error(signal):
    """What a stray signal reaching the top level becomes (run())."""
    if signal.kind == "return":
        return NovaError("'return' only makes sense inside a function")
    return NovaError("'{}' is not inside a loop".format(signal.kind), signal.position)


def find_handler(code, index, problem):
    """(handler, what to push) for the error raised by instruction `index`."""
    for start, end, handler, kind in code.exception_table:
        if start <= index < end:
            if kind == "catch":
                if isinstance(problem, NovaError):
                    return handler, error_text(problem)
                continue
            return handler, problem
    return None, None


def vm_function(code, cells, globals_):
    function = NovaFunction(code.name, code.param_names, None, None)
    function.code = code
    function.cells = cells
    function.globals = globals_
    return function


def execute(interpreter, entry):
    """Run `entry` (a Frame) to its RETURN; the value it returns."""
    frames = []                         # the callers of the current frame
    frame = entry
    call_stack = interpreter.call_stack
    counting = interpreter.counting                 # the restricted profile counts steps and sizes
    vm_limits = interpreter.limits if counting else None
    max_depth = interpreter.limits.depth
    dict_limit = interpreter.limits.dict if counting else None

    # Each opcode number as a local variable (looked up by name, so the
    # order of OPCODES never matters here); locals are fastest in the loop.
    LOAD_CONST_ = OP["LOAD_CONST"]; POP_ = OP["POP"]; DUP_ = OP["DUP"]
    LOAD_FAST_ = OP["LOAD_FAST"]; STORE_FAST_ = OP["STORE_FAST"]; LOAD_CELL_ = OP["LOAD_CELL"]
    STORE_CELL_ = OP["STORE_CELL"]; LOAD_GLOBAL_ = OP["LOAD_GLOBAL"]; STORE_GLOBAL_ = OP["STORE_GLOBAL"]
    LOAD_BUILTIN_ = OP["LOAD_BUILTIN"]
    LOAD_CHAIN_ = OP["LOAD_CHAIN"]; STORE_CHAIN_ = OP["STORE_CHAIN"]; NEW_CELLS_ = OP["NEW_CELLS"]
    limit = INTEGER_LIMIT; negative_limit = -INTEGER_LIMIT      # locals: faster than globals
    RESET_SLOTS_ = OP["RESET_SLOTS"]; ADD_ = OP["ADD"]; SUB_ = OP["SUB"]
    MUL_ = OP["MUL"]; DIV_ = OP["DIV"]; FLOOR_DIV_ = OP["FLOOR_DIV"]
    MOD_ = OP["MOD"]; NEG_ = OP["NEG"]; POS_ = OP["POS"]
    NOT_ = OP["NOT"]; EQ_ = OP["EQ"]; NE_ = OP["NE"]
    LT_ = OP["LT"]; GT_ = OP["GT"]; LE_ = OP["LE"]
    GE_ = OP["GE"]; IN_ = OP["IN"]; CHECK_BOOL_ = OP["CHECK_BOOL"]
    JUMP_IF_FALSE_KEEP_ = OP["JUMP_IF_FALSE_KEEP"]; JUMP_IF_TRUE_KEEP_ = OP["JUMP_IF_TRUE_KEEP"]; BUILD_LIST_ = OP["BUILD_LIST"]
    BUILD_DICT_ = OP["BUILD_DICT"]; BUILD_STRING_ = OP["BUILD_STRING"]; INDEX_ = OP["INDEX"]
    SLICE_TARGET_ = OP["SLICE_TARGET"]; SLICE_BOUND_ = OP["SLICE_BOUND"]; SLICE_ = OP["SLICE"]
    GET_MEMBER_ = OP["GET_MEMBER"]; INDEX_ASSIGN_TARGET_ = OP["INDEX_ASSIGN_TARGET"]; INDEX_ASSIGN_KEY_ = OP["INDEX_ASSIGN_KEY"]
    INDEX_ASSIGN_ = OP["INDEX_ASSIGN"]; MEMBER_ASSIGN_TARGET_ = OP["MEMBER_ASSIGN_TARGET"]; SET_MEMBER_ = OP["SET_MEMBER"]
    DELETE_TARGET_ = OP["DELETE_TARGET"]; DELETE_KEY_ = OP["DELETE_KEY"]; DELETE_FILE_ = OP["DELETE_FILE"]
    JUMP_ = OP["JUMP"]; JUMP_IF_NOT_TRUE_ = OP["JUMP_IF_NOT_TRUE"]; LOOP_NUMBER_ = OP["LOOP_NUMBER"]
    RANGE_PREP_ = OP["RANGE_PREP"]; RANGE_NEXT_ = OP["RANGE_NEXT"]; ITER_PREP_ = OP["ITER_PREP"]
    ITER_NEXT_ = OP["ITER_NEXT"]; MAKE_FUNCTION_ = OP["MAKE_FUNCTION"]; CALL_ = OP["CALL"]
    RETURN_ = OP["RETURN"]; THROW_ = OP["THROW"]; RERAISE_ = OP["RERAISE"]
    STRAY_ = OP["STRAY"]; FAIL_ = OP["FAIL"]; IMPORT_ = OP["IMPORT"]
    IMPORT_NAME_ = OP["IMPORT_NAME"]; EXPORT_ = OP["EXPORT"]

    code = frame.code
    ops, args, consts, positions = code.ops, code.args, code.constants, code.positions
    slots, stack, cells, glob = frame.slots, frame.stack, frame.cells, frame.globals
    ip = frame.ip

    while True:
        try:
            while True:
                op = ops[ip]
                arg = args[ip]
                ip += 1

                if op == LOAD_FAST_:
                    stack.append(slots[arg])
                elif op == LOAD_CONST_:
                    stack.append(consts[arg])
                elif op == JUMP_IF_NOT_TRUE_:
                    value = stack.pop()
                    if value is not True:
                        if value is not False:
                            condition_check(value, consts[arg[0]], positions[ip - 1])
                        ip = arg[1]
                elif op == LOAD_BUILTIN_:
                    value = interpreter.lookup_builtin(arg)
                    if value is None:
                        raise NovaError("undefined name {!r}".format(arg), positions[ip - 1])
                    stack.append(value)
                elif op == LOAD_GLOBAL_:
                    value = glob.get(arg, UNSET)
                    if value is UNSET:
                        raise NovaError("undefined name {!r}".format(arg), positions[ip - 1])
                    stack.append(value)
                elif op == CALL_:
                    if arg:
                        call_args = stack[-arg:]
                        del stack[-arg:]
                    else:
                        call_args = []
                    callee = stack.pop()
                    if type(callee) is NovaFunction and callee.code is not None:
                        if len(call_args) != len(callee.params):
                            raise NovaError("{}() expects {} argument(s) but got {}".format(
                                callee.name, len(callee.params), len(call_args)),
                                positions[ip - 1])
                        if len(call_stack) >= max_depth:
                            raise NovaError(
                                "call depth of {} exceeded - is the recursion missing a base "
                                "case?".format(max_depth), positions[ip - 1])
                        if counting:
                            interpreter.step(positions[ip - 1])   # a call is a step
                        frame.ip = ip
                        frames.append(frame)
                        call_stack.append(callee.name)
                        # function_frame(), inline: the hottest path in a call.
                        code = callee.code
                        new_slots = [UNSET] * code.nslots
                        for slot, value in zip(code.params, call_args):
                            new_slots[slot] = value
                        if code.cell_params:
                            for slot in code.cell_params:
                                new_slots[slot] = Cell(new_slots[slot])
                        frame = Frame(code, new_slots, callee.cells, callee.globals, callee)
                        ops, args, consts, positions = (code.ops, code.args, code.constants,
                                                        code.positions)
                        slots, stack, cells, glob = (frame.slots, frame.stack, frame.cells,
                                                     frame.globals)
                        ip = 0
                    else:
                        stack.append(interpreter.call_value(callee, call_args, positions[ip - 1]))
                elif op == STORE_FAST_:
                    slots[arg] = stack.pop()
                elif op == RETURN_:
                    value = stack.pop()
                    if stack:
                        # verify() proves RETURN runs with exactly one value
                        # on the stack; anything left means the VM itself
                        # went wrong. Stop the line rather than carry on.
                        raise VMError("{} returned with {} stray value(s) on its stack".format(
                            code.name, len(stack)))
                    if frame.function is not None:
                        call_stack.pop()
                    if frame is entry:
                        return value
                    frame = frames.pop()
                    code = frame.code
                    ops, args, consts, positions = (code.ops, code.args, code.constants,
                                                    code.positions)
                    slots, stack, cells, glob = (frame.slots, frame.stack, frame.cells,
                                                 frame.globals)
                    ip = frame.ip
                    stack.append(value)
                elif op == EQ_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is str or kind is bool or kind is float):
                        stack[-1] = left == right
                    else:
                        stack[-1] = compare_operation("==", left, right, positions[ip - 1])
                elif op == ADD_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float
                                                or (kind is str and not counting)):
                        result = left + right
                        if kind is int and not negative_limit < result < limit:
                            raise too_many_digits_error(positions[ip - 1])
                        stack[-1] = result
                    else:
                        stack[-1] = binary_operation("+", left, right, positions[ip - 1], vm_limits)
                elif op == SUB_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float):
                        result = left - right
                        if kind is int and not negative_limit < result < limit:
                            raise too_many_digits_error(positions[ip - 1])
                        stack[-1] = result
                    else:
                        stack[-1] = binary_operation("-", left, right, positions[ip - 1])
                elif op == INDEX_:
                    index = stack.pop()
                    target = stack[-1]
                    kind = type(target)
                    # Fast: a present string key, or an in-range non-negative
                    # whole index. Anything else - negative indexes, misses
                    # and every error - goes through index_operation.
                    if kind is dict:
                        if type(index) is str and index in target:
                            stack[-1] = target[index]
                            continue
                    elif kind is list or kind is str:
                        if type(index) is int and 0 <= index < len(target):
                            stack[-1] = target[index]
                            continue
                    stack[-1] = index_operation(target, index, positions[ip - 1])
                elif op == JUMP_:
                    if counting and arg < ip:
                        interpreter.step(positions[ip - 1])       # a pass of a loop is a step
                    ip = arg
                elif op == STORE_GLOBAL_:
                    glob[arg] = stack.pop()
                elif op == LT_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float or kind is str):
                        stack[-1] = left < right
                    else:
                        stack[-1] = compare_operation("<", left, right, positions[ip - 1])
                elif op == LOAD_CHAIN_:
                    for kind, where in consts[arg]:
                        if kind == "fast":
                            value = slots[where]
                        elif kind == "cell":
                            value = slots[where].value
                        elif kind == "free":
                            value = cells[where].value
                        else:
                            value = glob.get(where, UNSET)
                            name = where
                        if value is not UNSET:
                            stack.append(value)
                            break
                    else:
                        raise NovaError("undefined name {!r}".format(name), positions[ip - 1])
                elif op == MOD_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float) and right != 0:
                        stack[-1] = left % right
                    else:
                        stack[-1] = binary_operation("%", left, right, positions[ip - 1])
                elif op == ITER_NEXT_:
                    state = slots[arg[0]]
                    index = state[1]
                    if index >= len(state[0]):
                        ip = arg[1]
                    else:
                        state[1] = index + 1
                        item = state[0][index]
                        if state[2]:
                            stack.append(item[0])
                            stack.append(item[1])
                        else:
                            stack.append(item)
                elif op == POP_:
                    stack.pop()
                elif op == IN_:
                    right = stack.pop()
                    stack[-1] = compare_operation("in", stack[-1], right, positions[ip - 1])
                elif op == CHECK_BOOL_:
                    side, name = consts[arg]
                    logical_side(stack[-1], side, name, positions[ip - 1])
                elif op == MUL_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float):
                        result = left * right
                        if kind is int and not negative_limit < result < limit:
                            raise too_many_digits_error(positions[ip - 1])
                        stack[-1] = result
                    else:
                        stack[-1] = binary_operation("*", left, right, positions[ip - 1], vm_limits)
                elif op == INDEX_ASSIGN_TARGET_:
                    # The fast paths for assignment (M6) skip a helper only
                    # where it would do nothing, or exactly the same store,
                    # and use exact type(): no bool as an int, and no
                    # PythonObjectProxy (a dict subclass) as a dict. Every
                    # other case, and every error, is the helper's, at the
                    # same instruction - so the order of evaluation and of
                    # errors is the compiler's, unchanged.
                    target = stack[-1]
                    if type(target) is not dict and type(target) is not list:
                        index_assign_target(target, positions[ip - 1])
                elif op == INDEX_ASSIGN_KEY_:
                    # A dictionary's key is checked here, before the value.
                    target = stack[-2]
                    if not (type(target) is list
                            or type(target) is dict and type(stack[-1]) is str):
                        stack[-1] = index_assign_key(target, stack[-1], positions[ip - 1])
                elif op == RANGE_NEXT_:
                    state = slots[arg[0]]
                    index = state[3]
                    if index >= state[2]:
                        ip = arg[1]
                    else:
                        state[3] = index + 1
                        stack.append(range_value(state[0], state[1], index, state[4]))
                elif op == INDEX_ASSIGN_:
                    # After the value: a list index is checked now, exactly
                    # when index_assign would check it.
                    value = stack.pop()
                    index = stack.pop()
                    target = stack[-1]
                    if type(target) is dict and type(index) is str and (
                            dict_limit is None or index in target or len(target) < dict_limit):
                        target[index] = value
                        stack[-1] = value
                    elif (type(target) is list and type(index) is int
                          and 0 <= index < len(target)):
                        target[index] = value
                        stack[-1] = value
                    else:   # negative, float, bool, out of range, empty, any error
                        stack[-1] = index_assign(target, index, value, positions[ip - 1], vm_limits)
                elif op == BUILD_DICT_:
                    keys = consts[arg]
                    if keys:
                        values = stack[-len(keys):]
                        del stack[-len(keys):]
                    else:
                        values = []
                    stack.append(dict(zip(keys, values)))
                elif op == ITER_PREP_:
                    slot, names = arg
                    items = iteration_items(stack.pop(), names == 2, positions[ip - 1])
                    slots[slot] = [items, 0, names == 2]
                elif op == GET_MEMBER_:
                    stack[-1] = member_operation(stack[-1], consts[arg], positions[ip - 1])
                elif op == MEMBER_ASSIGN_TARGET_:
                    if type(stack[-1]) is not dict:
                        member_assign_target(stack[-1], positions[ip - 1])
                elif op == NE_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is str or kind is bool or kind is float):
                        stack[-1] = left != right
                    else:
                        stack[-1] = compare_operation("!=", left, right, positions[ip - 1])
                elif op == SET_MEMBER_:
                    value = stack.pop()
                    if dict_limit is not None and consts[arg] not in stack[-1] and len(stack[-1]) >= dict_limit:
                        raise NovaError("a dictionary cannot hold more than {} entries".format(dict_limit),
                                        positions[ip - 1])
                    stack[-1][consts[arg]] = value          # a new key is fine
                    stack[-1] = value
                elif op == JUMP_IF_FALSE_KEEP_:
                    if stack[-1]:
                        stack.pop()
                    else:
                        ip = arg
                elif op == BUILD_LIST_:
                    if arg:
                        items = stack[-arg:]
                        del stack[-arg:]
                    else:
                        items = []
                    stack.append(items)
                elif op == JUMP_IF_TRUE_KEEP_:
                    if stack[-1]:
                        ip = arg
                    else:
                        stack.pop()
                elif op == MAKE_FUNCTION_:
                    child = consts[arg]
                    closure = tuple(slots[where] if kind == "cell" else cells[where]
                                    for kind, where in child.closure)
                    stack.append(vm_function(child, closure, glob))
                elif op == DELETE_TARGET_:
                    if type(stack[-1]) is not dict:
                        delete_target(stack[-1], positions[ip - 1])
                elif op == DELETE_KEY_:
                    key = stack.pop()
                    target = stack[-1]
                    if type(target) is dict and type(key) is str:
                        target.pop(key, None)                   # deleting twice is fine
                        stack[-1] = NOTHING
                    else:
                        stack[-1] = delete_key(target, key, positions[ip - 1])
                elif op == GT_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float or kind is str):
                        stack[-1] = left > right
                    else:
                        stack[-1] = compare_operation(">", left, right, positions[ip - 1])
                elif op == NOT_:
                    stack[-1] = not_operation(stack[-1], positions[ip - 1])
                elif op == LOAD_CELL_:
                    stack.append(slots[arg].value)
                elif op == GE_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float or kind is str):
                        stack[-1] = left >= right
                    else:
                        stack[-1] = compare_operation(">=", left, right, positions[ip - 1])
                elif op == SLICE_BOUND_:
                    stack[-1] = slice_bound(stack[-1], positions[ip - 1])
                elif op == STORE_CELL_:
                    slots[arg].value = stack.pop()
                elif op == NEW_CELLS_:
                    for slot in consts[arg]:
                        slots[slot] = Cell()
                elif op == LOOP_NUMBER_:
                    loop_number(stack[-1], consts[arg], positions[ip - 1])
                elif op == LE_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float or kind is str):
                        stack[-1] = left <= right
                    else:
                        stack[-1] = compare_operation("<=", left, right, positions[ip - 1])
                elif op == SLICE_TARGET_:
                    slice_target(stack[-1], positions[ip - 1])
                elif op == RANGE_PREP_:
                    slot, descending, has_step = arg
                    step = stack.pop() if has_step else 1
                    end = stack.pop()
                    start = stack.pop()
                    iterations = range_iterations(start, end, step, descending, positions[ip - 1])
                    slots[slot] = [start, step, iterations, 0, descending]
                elif op == SLICE_:
                    end = stack.pop() if arg[1] else None
                    start = stack.pop() if arg[0] else None
                    stack[-1] = stack[-1][start:end]
                elif op == NEG_ or op == POS_:
                    stack[-1] = unary_operation("-" if op == NEG_ else "+", stack[-1],
                                                positions[ip - 1])
                elif op == DIV_:
                    right = stack.pop()
                    stack[-1] = binary_operation("/", stack[-1], right, positions[ip - 1])
                elif op == FLOOR_DIV_:
                    right = stack.pop()
                    left = stack[-1]
                    kind = type(left)
                    if type(right) is kind and (kind is int or kind is float) and right != 0:
                        stack[-1] = left // right
                    else:
                        stack[-1] = binary_operation("//", left, right, positions[ip - 1])
                elif op == THROW_:
                    raise throw_error(stack.pop(), positions[ip - 1])
                elif op == DUP_:
                    stack.append(stack[-1])
                elif op == BUILD_STRING_:
                    parts = stack[-arg:] if arg else []
                    if arg:
                        del stack[-arg:]
                    if counting and text_would_exceed(parts, vm_limits.string):
                        raise interpreter.string_too_long(positions[ip - 1])
                    stack.append(interpolate(parts))
                elif op == STORE_CHAIN_:
                    value = stack.pop()
                    chain = consts[arg]
                    last = len(chain) - 1
                    for index, (kind, where) in enumerate(chain):
                        if kind == "fast":
                            if index == last or slots[where] is not UNSET:
                                slots[where] = value
                                break
                        elif kind == "cell":
                            if index == last or slots[where].value is not UNSET:
                                slots[where].value = value
                                break
                        elif kind == "free":
                            if index == last or cells[where].value is not UNSET:
                                cells[where].value = value
                                break
                        elif index == last or where in glob:
                            glob[where] = value
                            break
                elif op == RESET_SLOTS_:
                    for slot in consts[arg]:
                        slots[slot] = UNSET
                elif op == DELETE_FILE_:
                    stack[-1] = interpreter.delete_file(stack[-1], positions[ip - 1])
                elif op == RERAISE_:
                    raise slots[arg]
                elif op == STRAY_:
                    raise StraySignal(consts[arg], positions[ip - 1])
                elif op == FAIL_:
                    message, label = consts[arg]
                    raise NovaError(message, positions[ip - 1], label=label)
                elif op == IMPORT_:
                    stack.append(interpreter.import_module(consts[arg], positions[ip - 1]))
                elif op == IMPORT_NAME_:
                    name, raw_path = consts[arg]
                    stack[-1] = imported_name(stack[-1], raw_path, name, positions[ip - 1])
                elif op == EXPORT_:
                    interpreter.current_exports[consts[arg]] = stack[-1]
                else:
                    raise NovaError("internal error: unknown opcode {}".format(op))
        except VMError:
            raise
        except BaseException as problem:  # noqa: BLE001 - unwound exactly like Python's
            # Unwind: this frame's handler, else leave it and try its caller's.
            while True:
                if isinstance(problem, FatalLimit):
                    handler, payload = None, None       # no catch and no finally sees a fatal limit
                else:
                    handler, payload = find_handler(code, ip - 1, problem)
                if handler is not None:
                    del stack[:]
                    stack.append(payload)
                    ip = handler
                    break
                if frame.function is not None:
                    if isinstance(problem, NovaError) and problem.stack is None:
                        problem.stack = ["{}()".format(name) for name in reversed(call_stack)]
                    call_stack.pop()
                    if isinstance(problem, StraySignal):
                        problem = stray_error(problem, frame.function.name)
                if frame is entry:
                    raise problem
                frame = frames.pop()
                code = frame.code
                ops, args, consts, positions = (code.ops, code.args, code.constants,
                                                code.positions)
                slots, stack, cells, glob = (frame.slots, frame.stack, frame.cells,
                                             frame.globals)
                ip = frame.ip


def type_gate(ast, source, interpreter, path=None):
    """Refuse to run a program that fails its type check (M1, gradual
    typing). A program with no annotations and no imports cannot break a
    type contract, so it costs one flag read here and the checker is never
    loaded - it runs exactly as it always has. Anything else is checked by
    tools/nova-typecheck.py before a single statement executes. `path` is
    the module being loaded (None for a script or an input): the
    interpreter keeps every result, so a module imported by many others is
    checked once, not once per importer."""
    if not (ast.annotated or ast.imports):
        return
    tool = typecheck_tool()
    if interpreter.type_cache is None:
        interpreter.type_cache = tool.GateCache()
    base_dir = interpreter.file_stack[-1] if interpreter.file_stack else None
    refusal = tool.gate_refusal(source, base_dir, interpreter.type_cache, path)
    if refusal is not None:
        message, position = refusal
        raise NovaError(message, position, label="TypeCheckError")


_TYPECHECK = []


def typecheck_tool():
    if not _TYPECHECK:
        _TYPECHECK.append(load_tool("nova-typecheck.py"))
    return _TYPECHECK[0]


def run(source, interpreter, path=None):
    """Lex, parse, type-gate and run `source`; (ast, value). `path` is the
    module's absolute path when this is a module load."""
    try:
        tokens = Lexer(source).tokenize()
        ast = Parser(tokens).parse()
        type_gate(ast, source, interpreter, path)
        return ast, run_program(ast, interpreter)
    except RecursionError:
        # A program nested too deeply to lex, parse or run: a NovaLang error, never Python's
        # ([sbx.limits], nesting).
        raise NovaError("the interpreter ran out of stack - recursion too deep") from None


def run_program(ast, interpreter):
    """Run a parsed program on the interpreter's engine; its value. The counters of the limits start
    from zero here, unless this is a module being loaded by a program that is already running."""
    with interpreter.running():
        return run_program_counted(ast, interpreter)


def run_program_counted(ast, interpreter):
    """A stray `return`, `break` or `continue` at the top level is an error here."""
    if interpreter.engine == "vm":
        code = getattr(ast, "_code", None)
        if code is None:
            code = ast._code = compile_ast(ast)     # compiled once per parse
        try:
            return execute(interpreter, module_frame(code, interpreter.globals.values))
        except StraySignal as signal:
            raise top_level_error(signal) from None
    try:
        return interpreter.evaluate(ast)
    except ReturnSignal:
        raise NovaError("'return' only makes sense inside a function")
    except BreakSignal as signal:
        raise NovaError("'break' is not inside a loop", signal.position)
    except ContinueSignal as signal:
        raise NovaError("'continue' is not inside a loop", signal.position)


# ---------------------------------------------------------------------------
# `tree` - pretty-print an AST
# ---------------------------------------------------------------------------

def is_node_list(value):
    return isinstance(value, list) and all(isinstance(item, Node) for item in value)


def tree_lines(node, label=None, depth=0):
    pad = "  " * depth
    head = "{}: ".format(label) if label else ""

    scalars = []
    children = []
    for key, value in vars(node).items():
        if key == "position":
            continue
        if isinstance(value, Node) or (is_node_list(value) and value):
            children.append((key, value))
        elif value is not None or key not in ("step", "else_block"):
            scalars.append("{}={!r}".format(key, value))

    line = pad + head + type(node).__name__
    if scalars:
        line += " " + " ".join(scalars)
    lines = [line]

    for key, value in children:
        if isinstance(value, Node):
            lines.extend(tree_lines(value, key, depth + 1))
        else:
            lines.append("  " * (depth + 1) + key + ":")
            for item in value:
                lines.extend(tree_lines(item, None, depth + 2))

    return lines


def render_tree(node):
    # A single-statement program reads better without the ProgramNode wrapper.
    if isinstance(node, ProgramNode) and len(node.statements) == 1:
        node = node.statements[0]
    return "\n".join(tree_lines(node))


# ---------------------------------------------------------------------------
# 5. The REPL
# ---------------------------------------------------------------------------

WELCOME = """╔═══════════════════════════════════╗
║       NOVALANG v2.1.0            ║
║   A star-born programming lang   ║
║   Type an expression or 'exit'   ║
╚═══════════════════════════════════╝"""

HELP = "NovaLang v" + __version__ + """ - commands and syntax

  REPL commands
    vars                 list the globals you have defined
    tree <code>          show the AST instead of running it
    help                 show this message
    exit | quit          leave the REPL

  Values
    numbers              1, 42, 3.14      strings  "hi", 'hi'
    booleans             true, false      comments # to end of line
    lists                [1, 2, 3], []    any mix of values
    dictionaries         {name: "Ada", age: 36},  {}  any mix of values
    f-strings            f"Hello, {name}!"   {{ and }} are literal braces
    escapes              \n  \t  \\  \"  \'

  Expressions
    + - * /              arithmetic; "a" + "b" joins, "Ha" * 3 repeats
    % //                 remainder and integer division: 10 % 3, 10 // 3
    < > <= >= == !=      comparisons; strings compare alphabetically
    in                   "ell" in "Hello",  3 in [1, 2, 3],  "age" in d
    and or not           short-circuit logic: `not done and i < 10`
    a[0]  a[-1]          index a list or a string; -1 is the last item
    a[1:4] a[2:] a[:3]   slice a list or a string; out-of-range ends clamp
    d.name  d["name"]    read a dictionary entry, two ways
    [1, 2] + [3]         join lists;  [1, 2] * 3 repeats one
    {x: 1} + {y: 2}      merge dictionaries; the right-hand side wins

  Built-in functions
    print(x, ...)        write a line
    len(a)               how many items or characters
    append(a, v)         add v to the end of a
    pop(a) / pop(a, i)   remove and return the last item, or item i
    range(n)             [0 .. n-1];  range(a, b) and range(a, b, step)
    upper(s) lower(s)    change case;  trim(s) removes outer spaces
    split(s, sep)        cut a string into a list; split(s) uses spaces
    join(a, sep)         glue a list into a string
    str(x) num(s)        convert between numbers and strings
    type(x)              "number", "string", "list", "dict", "boolean", ...
    keys(d) values(d)    a dictionary's keys or values, as a list

  Files and input
    read(path)           the whole file, as one string
    write(path, text)    write text, replacing whatever was there
    append(path, text)   add text to the end of a file
    exists(path)         true if the path is there
    listdir(path)        the names inside a directory, sorted
    delete(path)         remove a file (missing is fine) - note the ()
    input(prompt)        print the prompt, read one typed line

  Standard library (Stage 11 - all global, no import needed)
    time() sleep(ms)     seconds since 1970;  pause for ms milliseconds
    now() format_time(t, fmt)   an ISO-8601 timestamp; custom formatting
    random() randint(a,b) choice(a) shuffle(a)   a float, an int, a pick,
                          and an in-place shuffle
    abs round floor ceil sqrt pow sin cos tan ln log10   the usual math,
                          plus the constants PI and E
    min(...) max(...) sum(...)   several numbers, or one list of them
    env(key)              a variable from the environment, or nothing
    exit(code) args() platform()   stop the program; its own extra
                          command-line words; the OS name
    json.dumps(v) json.loads(s) json.pretty(v)   to and from JSON text
    cwd() mkdir(p) remove(p) rename(a,b) copy(a,b)   the filesystem
    regex(pat, s)         true if pat matches anywhere in s
    replace_all(s,a,b) split_lines(s) pad(s,n) pad_left(s,n) reverse(x)
    sorted(a) sorted(a, true)   ascending, or descending with true
    assert(c) assert(c, msg)   raise an error when c is false
    log(x, ...)           like print, but to stderr with a timestamp
    map(f, a) filter(f, a) reduce(f, a) reduce(f, a, start)
                          the usual three - f may be any function,
                          built-in or your own

  Embedding (Stage 12) - reaching Python from a NovaLang script
    Off unless asked for: `novalang.py --allow-python ...`, or a host that
    creates Nova(allow_python=True). Otherwise every python.* call refuses.
    python.import("math")   allow a module from a short, safe allowlist
                          (math, random, statistics, itertools, functools,
                          string, re, datetime, json, collections) - or
                          one the embedding program chose to expose
    python.call("mod.fn", ...)   call a Python function by dotted name
    python.get("mod.name")   read a Python value by dotted name
    python.set("mod.name", v)   write one back, or define a fresh entry
    reactor.temp  reactor.scram()   an object the *embedding* Python
                          program exposed with Nova.expose_global() reads
                          and calls like this directly - see
                          examples/reactor_script.nova
    This is a deliberate, narrow bridge, not unrestricted access to the
    process: a script only ever reaches what the embedding program chose
    to hand it, plus that short allowlist; names starting with _ and module
    aliases outside the allowlist are never reachable. It is meant for a
    NovaLang script running inside another Python program. See examples/embedding.nova,
    examples/embedding_demo.py, examples/reactor_sim_integration.py and
    examples/daedalus_integration.py.

  Statements
    x = 10               assignment (updates an outer x if one exists)
    let x = 10           declare x in this block, shadowing any outer x
    a[0] = 10            replace a list item
    d.name = "Ada"       set a field; a new key is added
    delete d.name        remove an entry (deleting twice is harmless)
    if c { } else { }    conditionals; `else if` chains
    while c { }          loop while c is true
    for i = 0 to 10 { }  count up 0..10: both ends included; `downto` counts down
    for i = 0 to 100 step 10 { }   0, 10, ... 100 (range(n) stops before n)
    for x in a { }       walk a list, a string, or a dictionary's keys
    for k, v in d { }    walk a dictionary's pairs (or a list's index, item)
    break | continue     leave the loop / jump to the next turn
    try { } catch e { }  run anyway; e holds the message as a string
    try { } finally { }  the finally block always runs
    throw("gone wrong")  raise an error of your own
    import "f.nova"      run a file once; its exports are in f.<name>
    import "f.nova" as g       ...under the name g instead
    import "f.nova" with a, b  ...or bring specific names straight in
    import "math-utils"  a package from nova.json, installed with
                         tools/nova-pkg.py; binds math_utils
    export def f() { }   export let x = 1   mark a name as importable
    while c { } else { } the else runs only if no break happened
    def f(a) { return a } functions; print(...) is built in
    def f(a: int) -> int { }   let x: string = "hi"
                         optional type annotations: checked before the
                         program runs (types: int float string bool list
                         dict any), ignored while it runs

  Scoping
    A name first assigned inside a block belongs to that block and is gone
    when the block ends. Assigning a name that already exists updates it,
    unless it lives outside the current function.

  Multi-line input: an unclosed '{' keeps the prompt open as '  ... '.
  Finish the block with '}' (or press Ctrl-C to throw the draft away).
  Ctrl-C also stops a runaway loop.

  Bytecode: programs are compiled to bytecode and run on a virtual
  machine (M4). `novalang.py --dis file.nova` prints the bytecode without
  running it, and `novalang.py --tree-walk ...` runs anything - a file,
  --bootstrap, the REPL - on the original tree-walking interpreter
  instead, for comparison.

  Toolchain: `novalang.py --check file.nova` lints a program without
  running it (undefined names, unused variables, unreachable code),
  `novalang.py --typecheck file.nova` checks its type annotations (a
  program with annotations is also checked automatically before it runs),
  and `novalang.py --format file.nova` rewrites it in the standard layout.

  Self-hosting: `novalang.py --bootstrap file.nova` runs file.nova through
  novalang.nova - a second Lexer, Parser and Interpreter for this same
  language, written in NovaLang and loaded by this Python engine, rather
  than through this engine's own implementation. It is a command-line
  flag, not something typed here at the prompt."""

# Tokens that clearly cannot end a statement, so the REPL keeps reading.
CONTINUATION_TOKENS = (
    TT_DEF, TT_ELSE, TT_LBRACE, TT_COMMA, TT_LPAREN, TT_LBRACKET, TT_EQUALS,
    TT_PLUS, TT_MINUS, TT_STAR, TT_SLASH, TT_PERCENT, TT_DSLASH,
    TT_LET, TT_IN,
    TT_EQ, TT_NE, TT_LT, TT_GT, TT_LE, TT_GE,
    TT_WHILE, TT_FOR, TT_IF, TT_TO, TT_DOWNTO, TT_STEP,
    TT_AND, TT_OR, TT_NOT,
)

# A statement whose *first* token is one of these always needs a block.
BLOCK_OPENERS = (TT_IF, TT_WHILE, TT_FOR, TT_TRY)


def needs_more_input(source, *, blank_line=False):
    """Decide whether the REPL should keep collecting lines."""
    try:
        tokens = Lexer(source).tokenize()
    except NovaError:
        return False                    # let the real error surface

    meaningful_for_def = [t for t in tokens if t.type not in (TT_NEWLINE, TT_EOF)]
    # `def` (bare, or after `export`) always needs a block; `if`/`while`/
    # `for`/`try` need one only when they open the statement, so that
    # `export let x = 5` - which never gets a '{' - does not wait forever.
    needs_block = any(t.type == TT_DEF for t in meaningful_for_def) or (
        meaningful_for_def and meaningful_for_def[0].type in BLOCK_OPENERS
    )
    braces = brackets = 0
    for token in tokens:
        if token.type == TT_LBRACE:
            braces += 1
        elif token.type == TT_RBRACE:
            braces -= 1
        elif token.type == TT_LBRACKET:
            brackets += 1
        elif token.type == TT_RBRACKET:
            brackets -= 1
    if braces > 0 or brackets > 0:
        return True

    # Preserve blank-line submission for drafts outside an open block or list.
    # "Has a block" is decided from tokens: a brace inside a string, an
    # f-string or a comment is not one.
    if (blank_line and not any(t.type == TT_LBRACE for t in tokens)
            and not source.rstrip().endswith((",", "("))):
        return False

    if needs_block and not any(t.type == TT_LBRACE for t in meaningful_for_def):
        return True

    meaningful = meaningful_for_def
    if not meaningful:
        return False

    return meaningful[-1].type in CONTINUATION_TOKENS


def read_block(first_line):
    """Collect lines until the statement looks complete. None = abandoned."""
    source = first_line
    while needs_more_input(source):
        try:
            more = input("  ... ")
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print("\n(input discarded)")
            return None
        if not more.strip() and not needs_more_input(source, blank_line=True):
            break
        source += "\n" + more
    return source


def repl():
    print(WELCOME)
    interpreter = Interpreter()

    while True:
        try:
            line = input("nova> ")
        except EOFError:                # Ctrl-D
            print()
            print("Goodbye, star-traveller.")
            return 0
        except KeyboardInterrupt:       # Ctrl-C
            print()
            continue

        stripped = line.strip()
        if not stripped:
            continue

        lowered = stripped.lower()
        if lowered in ("exit", "quit"):
            print("Goodbye, star-traveller.")
            return 0
        if lowered == "help":
            print(HELP)
            continue
        if lowered == "vars":
            show_vars(interpreter)
            continue

        show_tree = False
        if lowered == "tree" or lowered.startswith("tree "):
            show_tree = True
            stripped = stripped[4:].strip()
            if not stripped:
                print("usage: tree <code>")
                continue

        source = read_block(stripped)
        if source is None:
            continue

        try:
            if show_tree:
                tokens = Lexer(source).tokenize()
                print(render_tree(Parser(tokens).parse()))
            else:
                _, value = run(source, interpreter)
                if value is not NOTHING:
                    print(format_repr(value))
        except FatalLimit as fatal:
            print(fatal.render(source))
        except NovaError as error:
            print(error.render(source))
        except KeyboardInterrupt:       # Ctrl-C out of a runaway loop
            print("\n(stopped)")
        except RecursionError:
            print("NovaError: the interpreter ran out of stack - recursion too deep")
        except Exception as problem:    # a bug in here, not in your program
            print("InternalError: {}: {}".format(type(problem).__name__, problem))


def show_vars(interpreter):
    names = sorted(interpreter.globals.values)
    if not names:
        print("(no variables defined yet)")
        return
    for name in names:
        print("  {} = {}".format(name, format_repr(interpreter.globals.values[name])))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_source(source, origin, script_args=None):
    """Run a whole program (a file, or code from the command line)."""
    global SCRIPT_ARGS
    SCRIPT_ARGS = list(script_args or [])
    interpreter = Interpreter()
    # A relative import in this file resolves against its own directory first.
    interpreter.file_stack.append(os.path.dirname(os.path.abspath(origin)))
    try:
        run(source, interpreter)
    except ProgramExit as stop:
        return stop.code
    except FatalLimit as fatal:
        print("{}\n{}".format(origin, fatal.render(source)), file=sys.stderr)
        return 1
    except NovaError as error:
        print("{}\n{}".format(origin, error.render(source)), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n(stopped)", file=sys.stderr)
        return 130
    except RecursionError:
        print("NovaError: the interpreter ran out of stack - recursion too deep", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Stage 12: embedding - the Python-side half
# ---------------------------------------------------------------------------

class CompiledScript:
    """A pre-parsed NovaLang program. Lexing and parsing happen once, at
    Nova.compile() time, so running the same script again and again - a
    game loop's per-frame condition, say - skips that work every call."""

    def __init__(self, source, ast):
        self.source = source
        self.ast = ast

    def run(self, engine):
        """Execute against `engine` (a Nova instance), returning the
        result as a Python value. Raises NovaLangError, never a raw
        NovaError - Stage 12's rule that NovaLang trouble surfaces to
        Python code as a Python exception, not something of NovaLang's
        own that caller would have to import novalang to catch."""
        interpreter = engine.interpreter
        try:
            value = run_program(self.ast, interpreter)
        except NovaError as error:
            raise NovaLangError(error) from None
        except FatalLimit as fatal:
            raise fatal_error(fatal) from None
        except RecursionError:
            raise NovaLangError(NovaError("the interpreter ran out of stack - recursion too deep")) from None
        return to_python_value(value, interpreter)


class Nova:
    """The Python side of Stage 12's embedding API: run NovaLang from a
    Python program, and hand it Python objects/functions to reach back
    into with python.* (see expose/expose_module/expose_global).

        engine = Nova()
        engine.expose_global("reactor", reactor)   # reactor.temp, reactor.scram()
        engine.exec('if reactor.temp > 2800 { reactor.scram() }')

    Each Nova wraps its own Interpreter, so independent scripts - two game
    levels, two reactor simulations - run in full isolation just by using
    separate Nova() instances; nothing is shared at the module level.
    Every method here raises NovaLangError, never a raw NovaError, on
    trouble in the NovaLang code it runs.
    """

    def __init__(self, engine=None, allow_python=False, profile="trusted", **settings):
        """`engine` is "vm" (the default) or "tree" (the tree-walker).
        `allow_python` gives scripts the python.* namespace; without it every
        python.import/call/get/set refuses. A host that runs scripts it did
        not write should leave it off and use expose_global instead.

        `profile="restricted"` runs scripts with no capability but the ones granted by the
        other arguments (`read=[folders]`, `write=`, `import_from=`, `env=[names]`, `clock=True`,
        `random=True`, `stdin=True`, `process=True`, `regex=True`, `python=[modules]`,
        `limits={...}`): docs/spec/16-sandbox.md. The default, `trusted`, is how NovaLang has
        always behaved and must not be used for code you did not write."""
        self.interpreter = Interpreter(engine, allow_python=allow_python,
                                       capabilities=TRUSTED if profile == "trusted" and not settings
                                       else Capabilities(profile, **settings))
        self._compiled_cache = {}          # source text -> CompiledScript, see eval()

    @property
    def registry(self):
        """The dict backing python.* - Nova.expose()'d names, and any
        modules python.import() has already pulled in."""
        return self.interpreter.python_registry

    def expose(self, name, value):
        """Make `value` reachable from NovaLang as python.get/call/set
        with a dotted name starting with `name` - e.g. after
        expose("reactor", reactor), python.get("reactor.temp") and
        python.call("reactor.scram") both work. Does not make `name`
        itself a NovaLang global; see expose_global for `reactor.temp`
        written directly, with no python.get wrapper."""
        self.interpreter.python_registry[name] = value
        self._grant(value)

    def _grant(self, value):
        """A module the embedding program hands over on purpose is one a
        script may be given; any other module is not (see python_granted)."""
        if isinstance(value, ModuleType):
            self.interpreter.python_granted.add(value.__name__)

    def expose_module(self, module):
        """Allow python.import(name) to succeed for a module beyond the
        built-in allowlist (PYTHON_IMPORT_ALLOWLIST). Accepts an already-
        imported module object, or a module name to import here first."""
        if isinstance(module, str):
            module = importlib.import_module(module)
        self.interpreter.python_registry[module.__name__] = module
        self._grant(module)
        return module

    def expose_global(self, name, value):
        """Bind `value` directly as a NovaLang global: a script can write
        `reactor.temp` and `reactor.scram()` rather than going through
        python.get/call. An arbitrary object becomes a live proxy (Stage
        12's PythonObjectProxy); a callable becomes a callable NovaLang
        value; a plain number/string/bool/list/dict converts as usual.
        Reserved built-in names are still protected, same as any other
        NovaLang global."""
        try:
            guard_name(name, None, "a global")
            self._grant(value)          # a module handed over on purpose is one the script may hold
            converted = to_nova_value(value, self.interpreter)
        except NovaError as error:
            raise NovaLangError(error) from None
        self.interpreter.globals.define(name, converted)

    def compile(self, code):
        """Lex and parse `code` once, returning a CompiledScript that can
        be run() repeatedly with no further parsing overhead - the
        precompile option for a script called every frame."""
        try:
            tokens = Lexer(code).tokenize()
            ast = Parser(tokens).parse()
            type_gate(ast, code, self.interpreter)
        except NovaError as error:
            raise NovaLangError(error) from None
        return CompiledScript(code, ast)

    def _cached(self, code):
        compiled = self._compiled_cache.get(code)
        if compiled is None:
            compiled = self.compile(code)
            if len(self._compiled_cache) < 512:      # a simple cap, not a real LRU
                self._compiled_cache[code] = compiled
        return compiled

    def eval(self, code):
        """Evaluate `code`, returning its value as a Python value. The
        same source string is only ever lexed/parsed once per engine (see
        _cached above), so calling eval() with an unchanged script every
        frame costs no repeated parsing - enough for a 60fps game loop
        without needing compile() explicitly, though compile() is still
        available when you want to hold the parsed form yourself."""
        return self._cached(code).run(self)

    def exec(self, code):
        """Run `code` for effect; any value it produces is discarded."""
        self.eval(code)

    def load_file(self, path):
        """Read and run a .nova file, returning its last top-level
        expression's value as a Python value. Relative imports inside the
        file resolve against the file's own directory, same as running it
        with `python3 novalang.py path`."""
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        self.interpreter.file_stack.append(os.path.dirname(os.path.abspath(path)))
        return self.compile(source).run(self)

    def call(self, name, *args):
        """Call an already-defined NovaLang function (from a prior eval/
        exec/load_file) by name, with Python arguments, returning its
        result as a Python value."""
        if not self.interpreter.globals.has(name):
            raise NovaLangError(NovaError("undefined name {!r}".format(name)))
        fn = self.interpreter.globals.get(name)
        if not isinstance(fn, (NovaFunction, BuiltinFunction)):
            raise NovaLangError(NovaError("{!r} is not a function".format(name)))
        try:
            nova_args = [to_nova_value(arg, self.interpreter) for arg in args]
            with self.interpreter.running():
                result = self.interpreter.call_value(fn, nova_args, 0)
        except NovaError as error:
            raise NovaLangError(error) from None
        except FatalLimit as fatal:
            raise fatal_error(fatal) from None
        return to_python_value(result, self.interpreter)


def run_bootstrap(args):
    """`--bootstrap program.nova` - run program.nova through novalang.nova,
    NovaLang's own self-hosted Lexer/Parser/Interpreter (Stage 10), instead
    of through this Python engine directly. See bootstrap.py."""
    if not args:
        print("usage: novalang.py --bootstrap <target.nova> [script args...]", file=sys.stderr)
        return 2
    import bootstrap
    return bootstrap.run_bootstrap(args[0], script_args=args[1:], engine=DEFAULT_ENGINE,
                                   allow_python=ALLOW_PYTHON,
                                   sandbox=DEFAULT_CAPABILITIES.settings
                                   if DEFAULT_CAPABILITIES.restricted or DEFAULT_CAPABILITIES.determinism else None)


def dis_main(paths):
    """`--dis file.nova ...` - compile each file and print its bytecode
    (checked by verify() first). Nothing is run."""
    if not paths:
        print("usage: novalang.py --dis file.nova [more.nova ...]", file=sys.stderr)
        return 2
    status = 0
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except (OSError, UnicodeDecodeError) as problem:
            print("cannot read {}: {}".format(path, problem), file=sys.stderr)
            status = 2
            continue
        try:
            code = compile_source(source)
        except NovaError as error:
            print(path, file=sys.stderr)
            print(error.render(source), file=sys.stderr)
            status = 2
            continue
        verify(code)
        if len(paths) > 1:
            print("== " + path)
        print(disassemble(code, source))
    return status


def load_tool(filename):
    """Load tools/<filename> (nova-fmt.py, nova-lint.py). Their names have
    dashes, so they are loaded by path rather than imported by name."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", filename)
    spec = importlib.util.spec_from_file_location(filename[:-3].replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module



# ---------------------------------------------------------------------------
# The subprocess runner (docs/spec/16-sandbox.md [sbx.runner])
# ---------------------------------------------------------------------------
#
# The in-process limits cannot stop a call that never returns to the interpreter (a pattern that
# backtracks for ever inside `regex`). The runner starts the interpreter in a separate process,
# watches the clock and the output from outside, and kills it. On Linux the process also gets an
# address-space limit and a CPU-time limit from the operating system.

RUNNER_GRACE_MS = 2000          # how long past its own time limit a run may take before it is killed
RUNNER_MEMORY_MB = 1024

# What the child runs, as `python -I -X utf8 -c`: set the operating system's limits, then run novalang.py
# exactly as the command line would. A MemoryError that reaches the top is the memory limit.
RUNNER_LAUNCHER = """
import os, runpy, sys
script, memory, cpu = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
try:
    import resource
    if memory:
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    if cpu:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
except (ImportError, ValueError, OSError):
    pass
sys.path.insert(0, os.path.dirname(script))
sys.argv = [script] + sys.argv[4:]
try:
    runpy.run_path(script, run_name="__main__")
except MemoryError:
    sys.stderr.write("LimitError: memory limit of %d MB exceeded\\n" % (memory // (1024 * 1024)))
    sys.exit(1)
"""


class IsolatedResult:
    """What a run in a separate process did: its output, its exit status, and `killed` (None, or
    "time", "output" or "memory") with the `error` line the runner adds when it ended the run."""

    def __init__(self, stdout, stderr, status, killed=None, error=""):
        self.stdout, self.stderr, self.status = stdout, stderr, status
        self.killed, self.error = killed, error

    def __repr__(self):
        return "<IsolatedResult status={} killed={}>".format(self.status, self.killed)


def sandbox_flags(settings):
    """The command-line flags that select `settings` (the dict a Capabilities holds), in the order
    main() reads them."""
    out = ["--profile", settings.get("profile", "trusted")]
    for key, flag in (("read", "--allow-read"), ("write", "--allow-write"), ("import_from", "--allow-import"),
                      ("env", "--allow-env"), ("python", "--allow-python-module")):
        for value in settings.get(key, ()):
            out += [flag, str(value)]
    for key, flag in (("clock", "--allow-clock"), ("random", "--allow-random"), ("stdin", "--allow-stdin"),
                      ("process", "--allow-process"), ("regex", "--allow-regex")):
        if settings.get(key):
            out.append(flag)
    for name, value in settings.get("limits", {}).items():
        out += ["--limit", "{}={}".format(name, value)]
    if settings.get("deterministic"):
        out += ["--deterministic", "--seed", str(settings.get("seed", 0)),
                "--clock-start", repr(float(settings.get("clock_start", 0.0)))]
    return out


def runner_environment(pass_env):
    """The child's environment: empty, but for what Python cannot start without on Windows and the
    variables the embedder named."""
    env = {}
    if sys.platform == "win32":
        for name in ("SYSTEMROOT", "SYSTEMDRIVE", "PATHEXT", "COMSPEC"):
            if name in os.environ:
                env[name] = os.environ[name]
    for name in pass_env:
        if name in os.environ:
            env[name] = os.environ[name]
    return env


def supervise(command, env, stdin_data, wall_ms, output_cap, on_out, on_err):
    """Run `command` and watch it. Returns (status, killed). `stdin_data` is bytes (or None for a closed
    stdin, or the string "inherit"). The child is killed when it outlives `wall_ms` or when its
    output passes `output_cap` bytes: both are checked from outside, so neither depends on the child."""
    if stdin_data == "inherit":
        stdin_mode = None
    elif stdin_data is None:
        stdin_mode = subprocess.DEVNULL
    else:
        stdin_mode = subprocess.PIPE
    process = subprocess.Popen(command, stdin=stdin_mode, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env, cwd=os.getcwd())
    state = {"bytes": 0, "killed": None}
    lock = threading.Lock()

    def pump(stream, sink):
        while True:
            chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
            if not chunk:
                return
            with lock:
                state["bytes"] += len(chunk)
                over = output_cap is not None and state["bytes"] > output_cap
                if over and state["killed"] is None:
                    state["killed"] = "output"
            if over:
                process.kill()
                return
            sink(chunk)

    threads = [threading.Thread(target=pump, args=(process.stdout, on_out), daemon=True),
               threading.Thread(target=pump, args=(process.stderr, on_err), daemon=True)]
    for thread in threads:
        thread.start()
    if stdin_mode == subprocess.PIPE:
        try:
            process.stdin.write(stdin_data)
            process.stdin.close()
        except OSError:
            pass
    try:
        process.wait(timeout=None if wall_ms is None else wall_ms / 1000.0)
    except subprocess.TimeoutExpired:
        with lock:
            if state["killed"] is None:
                state["killed"] = "time"
        process.kill()
        process.wait()
    for thread in threads:
        thread.join(timeout=5)
    for stream in (process.stdout, process.stderr, process.stdin):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    return process.returncode, state["killed"]


def runner_error(killed, status, stderr_text, time_ms, output_cap, memory_mb):
    """The `LimitError:` line for a run the runner ended or the operating system stopped, or ''."""
    if killed == "time":
        return "LimitError: time limit of {} ms exceeded".format(time_ms)
    if killed == "output":
        return "LimitError: output limit of {} bytes exceeded".format(output_cap)
    if status and ("LimitError: memory limit of" in stderr_text or "MemoryError" in stderr_text):
        return "LimitError: memory limit of {} MB exceeded".format(memory_mb)
    if status is not None and status < 0:
        import signal as signal_module
        if hasattr(signal_module, "SIGXCPU") and -status == signal_module.SIGXCPU:
            return "LimitError: time limit of {} ms exceeded".format(time_ms)
        return "LimitError: the run was stopped by signal {}".format(-status)
    return ""


def runner_command(flags, program, memory_mb, wall_ms):
    memory = memory_mb * 1024 * 1024 if memory_mb and sys.platform != "win32" else 0
    cpu = int(math.ceil(wall_ms / 1000.0)) + 1 if wall_ms and sys.platform != "win32" else 0
    return ([sys.executable, "-I", "-X", "utf8", "-c", RUNNER_LAUNCHER, os.path.abspath(__file__), str(memory), str(cpu)]
            + list(flags) + list(program))


def run_isolated(source=None, path=None, *, engine="vm", bootstrap=False, args=(), input_text=None, wall_ms=None,
                 memory_mb=RUNNER_MEMORY_MB, output_cap=None, pass_env=(), profile="restricted", **settings):
    """Run a program in a separate process under the `restricted` profile (or `trusted`) and give back an
    IsolatedResult. `source` is program text (written to a file of its own) or `path` is a file; `settings`
    are those of Nova(): read=[...], clock=True, limits={...}, deterministic=True. The child has an empty
    environment but for `pass_env`, a stdin that is closed unless the `stdin` capability is granted (`stdin=True`;
    then `input_text` is what it reads), the same working directory as the caller (so a relative grant means the same
    folder), and the operating system's limits on memory and CPU time where the system has them. It is killed
    from outside if it outlives `wall_ms` (by default its time limit plus two seconds; none for `trusted`) or
    writes more than `output_cap` bytes (by default twice its output limit)."""
    capabilities = Capabilities(profile, **settings)            # refuses a mistake before anything starts
    limits = capabilities.limit_values
    if wall_ms is None and limits.time is not None:
        wall_ms = limits.time + RUNNER_GRACE_MS
    if output_cap is None and limits.output is not None:
        output_cap = 2 * limits.output + 65536
    temp = None
    try:
        if source is not None:
            temp = tempfile.mkdtemp(prefix="nova-isolated-")
            path = os.path.join(temp, "main.nova")
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(source)
        engine_flags = ["--tree-walk"] if engine == "tree" else []
        program = (["--bootstrap"] if bootstrap else []) + [path] + list(args)
        flags = engine_flags + sandbox_flags(capabilities.settings)
        data = None
        if capabilities.has("stdin") and capabilities.restricted:
            data = (input_text or "").encode("utf-8")
        out, err = [], []
        status, killed = supervise(runner_command(flags, program, memory_mb, wall_ms), runner_environment(pass_env),
                                   data, wall_ms, output_cap, out.append, err.append)
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
    stdout = b"".join(out).decode("utf-8", "replace")
    stderr = b"".join(err).decode("utf-8", "replace")
    error = runner_error(killed, status, stderr, limits.time if limits.time is not None else wall_ms,
                         output_cap, memory_mb)
    if error and killed:
        status = 1
    return IsolatedResult(stdout, stderr, status, killed, error)


def isolate_main(runner, forwarded, rest):
    """`novalang.py --isolate [flags] program.nova`: the same flags, in a separate process."""
    wall_ms, output_cap = runner.get("wall_ms"), runner.get("output_cap")
    limits = DEFAULT_CAPABILITIES.limit_values
    if wall_ms is None and limits.time is not None:
        wall_ms = limits.time + RUNNER_GRACE_MS
    if output_cap is None and limits.output is not None:
        output_cap = 2 * limits.output + 65536
    memory_mb = runner.get("memory_mb", RUNNER_MEMORY_MB)
    inherit = "inherit" if DEFAULT_CAPABILITIES.restricted and DEFAULT_CAPABILITIES.has("stdin") else None
    if not DEFAULT_CAPABILITIES.restricted:
        inherit = "inherit"                                     # the trusted profile has no capabilities to hold back
    err = []

    def to_out(chunk):
        sys.stdout.flush()
        sys.stdout.buffer.write(chunk)
        sys.stdout.buffer.flush()

    def to_err(chunk):
        err.append(chunk)
        sys.stderr.flush()
        sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()

    status, killed = supervise(runner_command(forwarded, rest, memory_mb, wall_ms), runner_environment(runner.get("pass_env", ())),
                               inherit, wall_ms, output_cap, to_out, to_err)
    seen = b"".join(err).decode("utf-8", "replace")
    error = runner_error(killed, status, seen, limits.time if limits.time is not None else wall_ms,
                         output_cap, memory_mb)
    if killed:
        print(error, file=sys.stderr)
        return 1
    if error and "LimitError: memory limit of" not in seen:      # the child says that one itself
        print(error, file=sys.stderr)
    return status if status is not None and status >= 0 else 1


# command line flag -> (sandbox setting, does it take a value)
SANDBOX_FLAGS = {
    "--profile": ("profile", True), "--allow-read": ("read", True), "--allow-write": ("write", True),
    "--allow-import": ("import_from", True), "--allow-env": ("env", True),
    "--allow-python-module": ("python", True), "--limit": ("limits", True),
    "--allow-clock": ("clock", False), "--allow-random": ("random", False),
    "--allow-stdin": ("stdin", False), "--allow-process": ("process", False),
    "--allow-regex": ("regex", False),
    "--deterministic": ("deterministic", False), "--seed": ("seed", True), "--clock-start": ("clock_start", True),
}


RUNNER_FLAGS = {"--isolate": None, "--wall-ms": "wall_ms", "--memory-mb": "memory_mb",
                "--output-cap": "output_cap", "--pass-env": "pass_env"}


def main(argv):
    args = argv[1:]

    if not args:
        return repl()

    # `--tree-walk ...` runs anything below on the original tree-walking
    # interpreter instead of the bytecode VM, for comparing the two.
    # `--allow-python ...` gives the program the python.* namespace, which is
    # off otherwise. Both come before the file or subcommand, in either order.
    global DEFAULT_ENGINE, ALLOW_PYTHON, DEFAULT_CAPABILITIES
    sandbox = {}                            # docs/spec/16-sandbox.md [sbx.profiles]
    runner = {}                             # [sbx.runner]: --isolate and the flags that tune it
    forwarded = []                          # the flags the isolated child is given again
    while args and (args[0] in ("--tree-walk", "--allow-python") or args[0] in SANDBOX_FLAGS
                    or args[0] in RUNNER_FLAGS):
        flag = args[0]
        if flag in RUNNER_FLAGS:
            if flag == "--isolate":
                runner["isolate"] = True
            else:
                if len(args) < 2:
                    print("{} needs a value".format(flag), file=sys.stderr)
                    return 2
                value, args = args[1], args[1:]
                if flag == "--pass-env":
                    runner.setdefault("pass_env", []).append(value)
                else:
                    if not value.isdigit() or int(value) < 1:
                        print("{} needs a positive whole number, not {!r}".format(flag, value), file=sys.stderr)
                        return 2
                    runner[RUNNER_FLAGS[flag]] = int(value)
            args = args[1:]
            continue
        if flag == "--tree-walk":
            DEFAULT_ENGINE = "tree"
        elif flag == "--allow-python":
            ALLOW_PYTHON = True
        elif flag in SANDBOX_FLAGS:
            setting, takes_value = SANDBOX_FLAGS[flag]
            if takes_value:
                if len(args) < 2:
                    print("{} needs a value".format(flag), file=sys.stderr)
                    return 2
                value, args = args[1], args[1:]
                if setting == "limits":
                    name, _, number = value.partition("=")
                    if not number.isdigit():
                        print("--limit needs NAME=VALUE with a whole number, not {!r}".format(value),
                              file=sys.stderr)
                        return 2
                    sandbox.setdefault("limits", {})[name] = int(number)
                elif setting == "profile":
                    sandbox["profile"] = value
                elif setting in ("seed", "clock_start"):
                    try:
                        sandbox[setting] = int(value) if setting == "seed" else float(value)
                    except ValueError:
                        print("{} needs a number, not {!r}".format(flag, value), file=sys.stderr)
                        return 2
                else:
                    sandbox.setdefault(setting, []).append(value)
            else:
                sandbox[setting] = True
        forwarded.append(flag)
        if flag in SANDBOX_FLAGS and SANDBOX_FLAGS[flag][1]:
            forwarded.append(value)
        args = args[1:]
    if sandbox:
        profile = sandbox.pop("profile", "trusted")
        if profile == "restricted" and ALLOW_PYTHON:
            print("--allow-python opens the whole default module list; with --profile restricted "
                  "grant modules one by one with --allow-python-module NAME", file=sys.stderr)
            return 2
        try:
            DEFAULT_CAPABILITIES = Capabilities(profile, **sandbox)
        except NovaLangError as problem:
            print(problem, file=sys.stderr)
            return 2
    if runner.get("isolate"):
        if not args:
            print("--isolate needs a program to run", file=sys.stderr)
            return 2
        return isolate_main(runner, forwarded, args)
    if runner and not runner.get("isolate"):
        print("--wall-ms, --memory-mb, --output-cap and --pass-env belong to --isolate", file=sys.stderr)
        return 2
    if not args:
        return repl()

    if args[0] == "--bootstrap":
        return run_bootstrap(args[1:])

    # `--check file.nova` lints without running; `--format file.nova`
    # rewrites the file in the house style. See tools/nova-lint.py and
    # tools/nova-fmt.py, which can also be run directly.
    if args[0] == "--check":
        return load_tool("nova-lint.py").main(["novalang.py --check"] + args[1:])
    if args[0] == "--typecheck":
        return typecheck_tool().main(["novalang.py --typecheck"] + args[1:])
    if args[0] == "--dis":
        return dis_main(args[1:])
    if args[0] == "--format":
        if len(args) < 2:
            print("usage: novalang.py --format file.nova [more.nova ...]", file=sys.stderr)
            return 2
        return load_tool("nova-fmt.py").main(["novalang.py --format", "--write"] + args[1:])

    # `python3 novalang.py program.nova`  or  `python3 novalang.py "1 + 2"`
    try:
        with open(args[0], "r", encoding="utf-8") as handle:
            return run_source(handle.read(), args[0], script_args=args[1:])
    except UnicodeDecodeError as problem:
        print("FileError: {}: {}".format(args[0], problem), file=sys.stderr)
        return 1
    except (IOError, OSError):
        pass

    source = " ".join(args)
    interpreter = Interpreter()
    try:
        _, value = run(source, interpreter)
    except ProgramExit as stop:
        return stop.code
    except FatalLimit as fatal:
        print(fatal.render(source), file=sys.stderr)
        return 1
    except NovaError as error:
        print(error.render(source), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n(stopped)", file=sys.stderr)
        return 130
    if value is not NOTHING:
        print(format_repr(value))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
