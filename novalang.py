#!/usr/bin/env python3
# NovaLang v0.11.0 - a tiny language built from a hand-written lexer,
# recursive-descent parser, AST and tree-walking interpreter.
"""
NovaLang - Stage 11: Standard Library

The pipeline has not changed since Stage 1, only widened:

    source text  ->  Lexer       ->  tokens
    tokens       ->  Parser      ->  AST (Abstract Syntax Tree)
    AST          ->  Interpreter ->  a value

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

No eval(). No exec(). Everything is still built by hand.
"""

import json as json_module
import math
import os
import platform
import random
import re
import shutil
import sys
import time
from datetime import datetime, timezone

__version__ = "0.11.0"

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
            source_lines = source.split("\n")
            offset = max(0, min(self.position, len(source)))
            line_number = 0
            while line_number < len(source_lines) - 1 and offset > len(source_lines[line_number]):
                offset -= len(source_lines[line_number]) + 1
                line_number += 1
            text = source_lines[line_number]
            gutter = "  {} | ".format(line_number + 1) if len(source_lines) > 1 else "  "
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

            if char == "\r":
                self.advance()
                continue

            if char == "\n" or char == ";":
                self.advance()
                tokens.append(Token(TT_NEWLINE, char, start))
                continue

            # Comments run to the end of the line.
            if char == "#":
                while self.peek() is not None and self.peek() != "\n":
                    self.advance()
                continue

            if char.isdigit() or (char == "." and (self.peek(1) or "").isdigit()):
                tokens.append(self.read_number())
                continue

            # f"..." is a formatted string. This has to come before the
            # identifier rule, which would otherwise read the 'f' as a name.
            if char == "f" and self.peek(1) in ('"', "'"):
                tokens.append(self.read_fstring())
                continue

            if char.isalpha() or char == "_":
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

        while self.peek() is not None and (self.peek().isdigit() or self.peek() == "."):
            char = self.advance()
            if char == ".":
                if seen_dot:
                    raise NovaError("a number cannot have two decimal points", self.index - 1)
                seen_dot = True
            digits += char

        value = float(digits) if seen_dot else int(digits)
        return Token(TT_NUMBER, value, start)

    def read_identifier(self):
        """Read a name, then promote it if it is a keyword."""
        start = self.index
        name = ""
        while self.peek() is not None and (self.peek().isalnum() or self.peek() == "_"):
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
            if char is None or char == "\n":
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
            if char is None or char == "\n":
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
            if char is None or char == "\n":
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

    def __init__(self, name, value, position):
        self.name = name
        self.value = value
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
    def __init__(self, name, params, body, position):
        self.name = name
        self.params = params           # list of parameter names
        self.body = body               # BlockNode
        self.position = position


class ReturnNode(Node):
    def __init__(self, value, position):
        self.value = value             # expression node, or None for bare return
        self.position = position


class ProgramNode(Node):
    def __init__(self, statements):
        self.statements = statements


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
        return ProgramNode(statements)

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
        if self.current.type != TT_RPAREN:
            while True:
                param = self.expect(TT_IDENT, "a parameter name")
                guard_name(param.value, param.position, "a parameter")
                if param.value in params:
                    raise NovaError(
                        "parameter {!r} is listed twice".format(param.value), param.position
                    )
                params.append(param.value)
                if self.current.type != TT_COMMA:
                    break
                self.advance()
        self.expect(TT_RPAREN, "a ')' to close the parameter list")

        body = self.block()
        return FunctionDefNode(name_token.value, params, body, keyword.position)

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
        self.expect(TT_EQUALS, "a '=' after the name in a 'let'")
        return LetNode(name_token.value, self.expression_statement(), keyword.position)

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
    """A function written in NovaLang."""

    def __init__(self, name, params, body, closure):
        self.name = name
        self.params = params
        self.body = body
        self.closure = closure          # the scope the def was written in

    def __repr__(self):
        return "<function {}({})>".format(self.name, ", ".join(self.params))


class BuiltinFunction:
    """A function written in Python and exposed to NovaLang, such as print."""

    def __init__(self, name, arity, implementation, needs_interpreter=False):
        self.name = name
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


def builtin_print(args, position):
    print(" ".join(format_value(arg) for arg in args))
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
    try:
        return open(path, mode, encoding="utf-8")
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


def builtin_dirname(args, position):
    return os.path.dirname(text_argument(args[0], "dirname()", position))


def builtin_listdir(args, position):
    path = text_argument(args[0], "listdir()", position)
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


def builtin_input(args, position):
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
    return text_argument(args[0], "trim()", position).strip()


def builtin_split(args, position):
    if not 1 <= len(args) <= 2:
        raise NovaError("split() takes a string and an optional separator", position)
    text = text_argument(args[0], "split()", position)
    if len(args) == 1:
        return text.split()                     # split on runs of whitespace
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

    text = value.strip()
    digits = text[1:] if text[:1] in ("+", "-") else text
    readable = (
        digits
        and digits.count(".") <= 1
        and any(char.isdigit() for char in digits)
        and all(char.isdigit() or char == "." for char in digits)
    )
    if not readable:
        raise NovaError('num() cannot read a number from "{}"'.format(value), position)
    return float(text) if "." in digits else int(text)


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


def list_argument(value, who, position):
    if not isinstance(value, list):
        raise NovaError(
            "{} needs a list, but got {}".format(who, type_name(value)), position, label="TypeError"
        )
    return value


# ---- time -----------------------------------------------------------------

def builtin_time(args, position):
    return time.time()


def builtin_sleep(args, position):
    ms = numeric_argument(args[0], "sleep()", position)
    if ms < 0:
        raise NovaError("sleep() cannot pause for a negative time", position, label="TypeError")
    time.sleep(ms / 1000.0)
    return NOTHING


def builtin_now(args, position):
    return datetime.now(timezone.utc).isoformat()


def builtin_format_time(args, position):
    timestamp, fmt = args
    timestamp = numeric_argument(timestamp, "format_time()", position)
    fmt = text_argument(fmt, "the format for format_time()", position)
    try:
        return datetime.fromtimestamp(timestamp).strftime(fmt)
    except (ValueError, OSError, OverflowError) as problem:
        raise NovaError("format_time(): {}".format(problem), position, label="TypeError")


# ---- random -----------------------------------------------------------------

def builtin_random(args, position):
    return random.random()


def builtin_randint(args, position):
    low = whole_number(args[0], "randint()", position)
    high = whole_number(args[1], "randint()", position)
    if low > high:
        raise NovaError(
            "randint() needs its first argument no greater than its second", position, label="TypeError"
        )
    return random.randint(low, high)


def builtin_choice(args, position):
    target = list_argument(args[0], "choice()", position)
    if not target:
        raise NovaError("choice() cannot pick from an empty list", position)
    return random.choice(target)


def builtin_shuffle(args, position):
    target = list_argument(args[0], "shuffle()", position)
    random.shuffle(target)
    return target


# ---- math -----------------------------------------------------------------

def builtin_abs(args, position):
    return abs(numeric_argument(args[0], "abs()", position))


def builtin_round(args, position):
    value = numeric_argument(args[0], "round()", position)
    if len(args) == 1:
        return round(value)
    return round(value, whole_number(args[1], "round()", position))


def builtin_floor(args, position):
    return math.floor(numeric_argument(args[0], "floor()", position))


def builtin_ceil(args, position):
    return math.ceil(numeric_argument(args[0], "ceil()", position))


def builtin_sqrt(args, position):
    value = numeric_argument(args[0], "sqrt()", position)
    if value < 0:
        raise NovaError("sqrt() needs a number that is not negative", position, label="TypeError")
    return math.sqrt(value)


def builtin_pow(args, position):
    base = numeric_argument(args[0], "pow()", position)
    exponent = numeric_argument(args[1], "pow()", position)
    try:
        result = base ** exponent
    except (ValueError, OverflowError, ZeroDivisionError) as problem:
        raise NovaError("pow(): {}".format(problem), position, label="TypeError")
    if isinstance(result, complex):
        raise NovaError(
            "pow() produced a complex result, which NovaLang cannot represent", position, label="TypeError"
        )
    return result


def builtin_sin(args, position):
    return math.sin(numeric_argument(args[0], "sin()", position))


def builtin_cos(args, position):
    return math.cos(numeric_argument(args[0], "cos()", position))


def builtin_tan(args, position):
    return math.tan(numeric_argument(args[0], "tan()", position))


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

def builtin_env(args, position):
    value = os.environ.get(text_argument(args[0], "env()", position))
    return NOTHING if value is None else value


def builtin_exit(args, position):
    code = whole_number(args[0], "exit()", position) if args else 0
    sys.exit(code)


def builtin_args(args, position):
    return list(SCRIPT_ARGS)


def builtin_platform(args, position):
    return platform.system()


# ---- json -----------------------------------------------------------------

def to_jsonable(value, position):
    if value is NOTHING:
        return None
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
    try:
        return from_jsonable(json_module.loads(text))
    except json_module.JSONDecodeError as problem:
        raise NovaError("json.loads(): {}".format(problem), position, label="TypeError")


def builtin_json_pretty(args, position):
    return json_module.dumps(to_jsonable(args[0], position), indent=2)


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
        return re.search(pattern, text) is not None
    except re.error as problem:
        raise NovaError("regex(): bad pattern: {}".format(problem), position, label="TypeError")


def builtin_replace_all(args, position):
    text = text_argument(args[0], "the text for replace_all()", position)
    old = text_argument(args[1], "the target for replace_all()", position)
    new = text_argument(args[2], "the replacement for replace_all()", position)
    return text.replace(old, new)


def builtin_split_lines(args, position):
    return text_argument(args[0], "split_lines()", position).splitlines()


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
    items = list(list_argument(args[0], "sorted()", position))
    descending = False
    if len(args) > 1:
        if not isinstance(args[1], bool):
            raise NovaError("sorted()'s second argument must be true or false", position, label="TypeError")
        descending = args[1]
    try:
        items.sort(reverse=descending)
    except TypeError:
        raise NovaError("sorted() needs items that can be compared with each other", position, label="TypeError")
    return items


# ---- debugging -----------------------------------------------------------------

def builtin_assert(args, position):
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


def builtin_log(args, position):
    text = " ".join(format_value(arg) for arg in args)
    stamp = datetime.now(timezone.utc).isoformat()
    print("[{}] {}".format(stamp, text), file=sys.stderr)
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
    "print": BuiltinFunction("print", None, builtin_print),
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
    "read": BuiltinFunction("read", 1, builtin_read),
    "write": BuiltinFunction("write", 2, builtin_write),
    "exists": BuiltinFunction("exists", 1, builtin_exists),
    "listdir": BuiltinFunction("listdir", 1, builtin_listdir),
    "input": BuiltinFunction("input", None, builtin_input),
    "abspath": BuiltinFunction("abspath", 1, builtin_abspath),
    "dirname": BuiltinFunction("dirname", 1, builtin_dirname),

    # Stage 11: standard library
    "time": BuiltinFunction("time", 0, builtin_time),
    "sleep": BuiltinFunction("sleep", 1, builtin_sleep),
    "now": BuiltinFunction("now", 0, builtin_now),
    "format_time": BuiltinFunction("format_time", 2, builtin_format_time),
    "random": BuiltinFunction("random", 0, builtin_random),
    "randint": BuiltinFunction("randint", 2, builtin_randint),
    "choice": BuiltinFunction("choice", 1, builtin_choice),
    "shuffle": BuiltinFunction("shuffle", 1, builtin_shuffle),
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
    "env": BuiltinFunction("env", 1, builtin_env),
    "exit": BuiltinFunction("exit", None, builtin_exit),
    "args": BuiltinFunction("args", 0, builtin_args),
    "platform": BuiltinFunction("platform", 0, builtin_platform),
    "cwd": BuiltinFunction("cwd", 0, builtin_cwd),
    "mkdir": BuiltinFunction("mkdir", 1, builtin_mkdir),
    "remove": BuiltinFunction("remove", 1, builtin_remove),
    "rename": BuiltinFunction("rename", 2, builtin_rename),
    "copy": BuiltinFunction("copy", 2, builtin_copy),
    "regex": BuiltinFunction("regex", 2, builtin_regex),
    "replace_all": BuiltinFunction("replace_all", 3, builtin_replace_all),
    "split_lines": BuiltinFunction("split_lines", 1, builtin_split_lines),
    "pad": BuiltinFunction("pad", 2, builtin_pad),
    "pad_left": BuiltinFunction("pad_left", 2, builtin_pad_left),
    "reverse": BuiltinFunction("reverse", 1, builtin_reverse),
    "sorted": BuiltinFunction("sorted", None, builtin_sorted),
    "assert": BuiltinFunction("assert", None, builtin_assert),
    "log": BuiltinFunction("log", None, builtin_log),
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
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (NovaFunction, BuiltinFunction)):
        return repr(value)
    return str(value)


def format_key(key):
    """Print a key bare when it could be typed bare, quoted otherwise."""
    plain = key and (key[0].isalpha() or key[0] == "_") and all(
        char.isalnum() or char == "_" for char in key
    )
    return key if plain else format_repr(key)


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

class Interpreter:
    def __init__(self):
        self.globals = Environment(barrier=True)
        self.env = self.globals
        self.call_stack = []            # function names, innermost last

        # Stage 11: predefined globals, not reserved builtin names - an
        # ordinary `let PI = 3` shadows these in its own scope, the same
        # as it would shadow any other predefined variable.
        self.globals.define("PI", math.pi)
        self.globals.define("E", math.e)
        self.globals.define("json", dict(JSON_NAMESPACE))

        # Module machinery (Stage 9). file_stack tracks the directory of
        # whichever file is currently executing, for resolving a relative
        # import; it starts empty, meaning "no current file - use cwd only".
        self.file_stack = []
        self.import_stack = []          # resolved paths currently loading
        self.modules = {}               # resolved path -> its exports dict
        self.current_exports = {}       # name -> value, for the module now loading

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
            return BUILTINS[node.name]
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
        if isinstance(target, dict):
            return lookup_key(target, dict_key(index, node.position), node.position)
        return target[normalize_index(target, index, node.position)]

    def visit_MemberNode(self, node):
        target = self.evaluate(node.target)
        if not isinstance(target, dict):
            raise NovaError(
                "{} has no fields, so '.{}' means nothing here".format(
                    type_name(target), node.name
                ),
                node.position,
            )
        return lookup_key(target, node.name, node.position)

    def visit_MemberAssignNode(self, node):
        target = self.evaluate(node.target)
        if not isinstance(target, dict):
            raise NovaError(
                "only a dictionary can have fields set, but this is {}".format(
                    type_name(target)
                ),
                node.position,
            )
        value = self.evaluate(node.value)
        target[node.name] = value                       # a new key is fine
        return value

    def visit_TryNode(self, node):
        # The outer try/finally is Python's, so `finally` runs on the way out
        # no matter what left the block: normal completion, a caught error, an
        # error still on its way up, or a return / break / continue.
        try:
            try:
                self.execute_scoped_block(node.body)
            except NovaError as error:
                if node.catch_block is None:
                    raise
                self.run_catch(node, error)
        finally:
            if node.finally_block is not None:
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
        value = self.evaluate(node.value)
        if not isinstance(value, str):
            raise NovaError(
                "throw needs a string, but got {} - use str() to convert it".format(
                    type_name(value)
                ),
                node.position,
            )
        # label "Error" so a thrown message reads as its own kind of trouble.
        raise NovaError(value, node.position, label="Error")

    def visit_ImportNode(self, node):
        resolved = self.resolve_import(node.path, node.position)
        exports = self.load_module(resolved, node.path, node.position)

        if node.names is not None:
            for name in node.names:
                if name not in exports:
                    raise NovaError(
                        'module "{}" has no exported {!r} - it exports {}'.format(
                            node.path, name, ", ".join(exports) or "nothing"
                        ),
                        node.position,
                    )
                self.env.define(name, exports[name])
        else:
            module_name = node.alias or default_module_name(node.path, node.position)
            self.env.define(module_name, exports)
        return NOTHING

    def visit_ExportNode(self, node):
        value = self.evaluate(node.inner)
        self.current_exports[node.inner.name] = value
        return value

    def resolve_import(self, raw_path, position):
        """Search relative to the importing file, then the current directory."""
        current_dir = self.file_stack[-1] if self.file_stack else None
        candidates = []
        if current_dir is not None:
            candidates.append(os.path.normpath(os.path.join(current_dir, raw_path)))
        candidates.append(os.path.normpath(os.path.join(os.getcwd(), raw_path)))

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
            chain = " -> ".join(os.path.basename(path) for path in cycle)
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
        self.globals = Environment(barrier=True)
        self.env = self.globals
        self.call_stack = []
        self.current_exports = {}
        self.import_stack.append(resolved_path)
        self.file_stack.append(os.path.dirname(resolved_path))

        try:
            try:
                run(source, self)
            except NovaError as error:
                raise NovaError(
                    'while loading module "{}":\n{}'.format(
                        raw_path, indent_lines(error.render(source))
                    ),
                    position, label="ImportError",
                ) from None
            else:
                exports = self.current_exports
        finally:
            self.file_stack.pop()
            self.import_stack.pop()
            self.globals, self.env, self.call_stack, self.current_exports = saved

        self.modules[resolved_path] = exports
        return exports

    def visit_DeleteFileNode(self, node):
        path = self.evaluate(node.path)
        if not isinstance(path, str):
            raise NovaError(
                "delete() needs a file name, but got {}".format(type_name(path)), node.position
            )
        try:
            os.remove(path)
        except FileNotFoundError:
            pass                                    # deleting twice is harmless
        except IsADirectoryError:
            raise NovaError(
                "{} is a directory - delete() only removes files".format(path),
                node.position, label="FileError",
            )
        except OSError as problem:
            raise NovaError(
                "{}: {}".format(path, problem.strerror or "cannot be deleted"),
                node.position, label="FileError",
            )
        return NOTHING

    def visit_DeleteNode(self, node):
        target = self.evaluate(node.target)
        if not isinstance(target, dict):
            raise NovaError(
                "delete works on dictionary entries, but this is {}{}".format(
                    type_name(target),
                    " - use pop() to remove a list item" if isinstance(target, list) else "",
                ),
                node.position,
            )
        key = dict_key(self.evaluate(node.key), node.position)
        target.pop(key, None)                           # deleting twice is fine
        return NOTHING

    def visit_SliceNode(self, node):
        target = self.evaluate(node.target)
        if not isinstance(target, (list, str)):
            raise NovaError("{} cannot be sliced".format(type_name(target)), node.position)

        bound = "a slice bound"
        start = None if node.start is None else whole_number(
            self.evaluate(node.start), bound, node.position)
        end = None if node.end is None else whole_number(
            self.evaluate(node.end), bound, node.position)

        # Slices clamp instead of failing: "Hello"[1:99] is "ello".
        return target[start:end]

    def visit_InterpolationNode(self, node):
        return "".join(format_value(self.evaluate(part)) for part in node.parts)

    def visit_IndexAssignNode(self, node):
        target = self.evaluate(node.target)
        if isinstance(target, dict):
            key = dict_key(self.evaluate(node.index), node.position)
            value = self.evaluate(node.value)
            target[key] = value                         # a new key is fine
            return value
        if isinstance(target, str):
            raise NovaError(
                "strings cannot be changed in place - build a new one instead",
                node.position,
            )
        index = self.evaluate(node.index)
        value = self.evaluate(node.value)
        spot = normalize_index(target, index, node.position)
        target[spot] = value
        return value

    # -- operators ----------------------------------------------------------

    def visit_UnaryOpNode(self, node):
        value = self.evaluate(node.operand)
        if not is_number(value):
            raise NovaError(
                "cannot apply unary '{}' to {}".format(node.op, type_name(value)), node.position
            )
        return value if node.op == "+" else -value

    def visit_NotNode(self, node):
        value = self.evaluate(node.operand)
        if not isinstance(value, bool):
            raise NovaError(
                "'not' needs true or false, but this is {}".format(type_name(value)),
                node.position,
            )
        return not value

    def visit_LogicalOpNode(self, node):
        left = self.evaluate(node.left)
        if not isinstance(left, bool):
            raise NovaError(
                "the left side of '{}' must be true or false, but it is {}".format(
                    node.op, type_name(left)
                ),
                node.position,
            )

        # Short-circuit: the right side is never evaluated when the left
        # side already decides the answer.
        if node.op == "and" and not left:
            return False
        if node.op == "or" and left:
            return True

        right = self.evaluate(node.right)
        if not isinstance(right, bool):
            raise NovaError(
                "the right side of '{}' must be true or false, but it is {}".format(
                    node.op, type_name(right)
                ),
                node.position,
            )
        return right

    def visit_BinOpNode(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        op = node.op

        # "abc" + "def" is the one non-numeric arithmetic we allow.
        if op == "+" and isinstance(left, str) and isinstance(right, str):
            return left + right

        # "Ha" * 3 repeats a string; the number may be on either side.
        if op == "*" and (isinstance(left, str) or isinstance(right, str)):
            text, count = (left, right) if isinstance(left, str) else (right, left)
            if isinstance(text, str) and is_number(count):
                times = whole_number(count, "string repetition", node.position)
                if times < 0:
                    raise NovaError(
                        "a string cannot be repeated a negative number of times", node.position
                    )
                if len(text) * times > MAX_LIST_LENGTH:
                    raise NovaError(
                        "repeating that string {} times would be too long".format(times),
                        node.position,
                    )
                return text * times

        # Two dictionaries merge with '+'; the right-hand side wins.
        if op == "+" and isinstance(left, dict) and isinstance(right, dict):
            merged = dict(left)
            merged.update(right)
            return merged

        # Lists join with '+' and repeat with '*', always into a new list.
        if op == "+" and isinstance(left, list) and isinstance(right, list):
            return left + right

        if op == "*" and (isinstance(left, list) or isinstance(right, list)):
            items, count = (left, right) if isinstance(left, list) else (right, left)
            if not isinstance(items, list) or not is_number(count):
                raise NovaError(
                    "a list can only be repeated by a whole number, not by {}".format(
                        type_name(right if isinstance(left, list) else left)
                    ),
                    node.position,
                )
            times = whole_number(count, "list repetition", node.position)
            if times < 0:
                raise NovaError("a list cannot be repeated a negative number of times",
                                node.position)
            if len(items) * times > MAX_LIST_LENGTH:
                raise NovaError(
                    "repeating that list {} times would exceed {} items".format(
                        times, MAX_LIST_LENGTH
                    ),
                    node.position,
                )
            return items * times

        if not is_number(left) or not is_number(right):
            raise NovaError(
                "cannot use '{}' on {} and {}".format(op, type_name(left), type_name(right)),
                node.position,
            )

        if op == "+":
            return left + right
        if op == "-":
            return left - right
        if op == "*":
            return left * right
        if op == "/":
            if right == 0:
                raise NovaError("division by zero", node.position)
            result = left / right
            # Keep whole answers whole: 10 / 2 is 5, not 5.0
            if isinstance(left, int) and isinstance(right, int) and result.is_integer():
                return int(result)
            return result
        if op == "//":
            if right == 0:
                raise NovaError("integer division by zero", node.position)
            return left // right            # rounds towards negative infinity
        if op == "%":
            if right == 0:
                raise NovaError("cannot take the remainder of a division by zero",
                                node.position)
            return left % right             # the sign follows the right-hand side

        raise NovaError("unknown operator {!r}".format(op), node.position)

    def visit_CompareNode(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        op = node.op

        if op == "==":
            return nova_equals(left, right)
        if op == "!=":
            return not nova_equals(left, right)
        if op == "in":
            return nova_contains(left, right, node.position)

        ordered = (is_number(left) and is_number(right)) or (
            isinstance(left, str) and isinstance(right, str)
        )
        if not ordered:
            raise NovaError(
                "cannot compare {} with {} using '{}'".format(
                    type_name(left), type_name(right), op
                ),
                node.position,
            )

        if op == "<":
            return left < right
        if op == ">":
            return left > right
        if op == "<=":
            return left <= right
        if op == ">=":
            return left >= right

        raise NovaError("unknown comparison {!r}".format(op), node.position)

    # -- control flow -------------------------------------------------------

    def condition_value(self, node, keyword):
        """Conditions are strict: only true or false will do."""
        value = self.evaluate(node.condition)
        if not isinstance(value, bool):
            raise NovaError(
                "a '{}' condition must be true or false, but this is {}".format(
                    keyword, type_name(value)
                ),
                node.position,
            )
        return value

    def visit_IfNode(self, node):
        if self.condition_value(node, "if"):
            return self.execute_scoped_block(node.then_block)
        if node.else_block is not None:
            return self.evaluate(node.else_block)   # BlockNode or an else-if
        return NOTHING

    def visit_WhileNode(self, node):
        broke = False
        while self.condition_value(node, "while"):
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

        if step <= 0:
            raise NovaError(
                "a 'for' step must be greater than zero (use 'downto' to count down)",
                node.position,
            )

        # Work out the iteration count up front, the way `range` does, so the
        # loop cannot drift on floats and cannot be confused by the body
        # reassigning the loop variable.
        span = (start - end) if node.descending else (end - start)
        iterations = 0 if span < 0 else int(span / step + 1e-9) + 1

        # The loop variable lives in a scope of its own, so it does not leak.
        loop_env = Environment(parent=self.env)
        saved = self.env
        self.env = loop_env
        broke = False
        try:
            index = 0
            while index < iterations:
                offset = index * step
                loop_env.define(node.name, start - offset if node.descending else start + offset)
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
        iterable = self.evaluate(node.iterable)

        # Iterate over a snapshot, so changing the value inside the loop
        # cannot make it run forever.
        if isinstance(iterable, dict):
            # One name walks the keys; two walk key and value together.
            items = list(iterable.items()) if node.second_name else list(iterable)
        elif isinstance(iterable, (list, str)):
            items = list(enumerate(iterable)) if node.second_name else list(iterable)
        else:
            raise NovaError(
                "'for ... in' needs a list, a string or a dictionary, but this is {}".format(
                    type_name(iterable)
                ),
                node.position,
            )

        loop_env = Environment(parent=self.env)
        saved = self.env
        self.env = loop_env
        broke = False
        try:
            for item in items:
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
        value = self.evaluate(node)
        if not is_number(value):
            raise NovaError(
                "{} must be a number, but this is {}".format(role, type_name(value)),
                getattr(node, "position", None) or fallback_position,
            )
        return value

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
            if callee.needs_interpreter:
                return callee.implementation(args, position, self)
            return callee.implementation(args, position)

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

        if len(self.call_stack) >= MAX_CALL_DEPTH:
            raise NovaError(
                "call depth of {} exceeded - is the recursion missing a base case?".format(
                    MAX_CALL_DEPTH
                ),
                position,
            )

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


def default_module_name(raw_path, position):
    """The name a bare `import "path.nova"` binds, absent an alias."""
    stem = os.path.splitext(os.path.basename(raw_path))[0]
    valid = stem and (stem[0].isalpha() or stem[0] == "_") and all(
        char.isalnum() or char == "_" for char in stem
    )
    if not valid:
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

def run(source, interpreter):
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    try:
        value = interpreter.evaluate(ast)
    except ReturnSignal:
        raise NovaError("'return' only makes sense inside a function")
    except BreakSignal as signal:
        raise NovaError("'break' is not inside a loop", signal.position)
    except ContinueSignal as signal:
        raise NovaError("'continue' is not inside a loop", signal.position)
    return ast, value


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
║       NOVALANG v0.11.0           ║
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

  Statements
    x = 10               assignment (updates an outer x if one exists)
    let x = 10           declare x in this block, shadowing any outer x
    a[0] = 10            replace a list item
    d.name = "Ada"       set a field; a new key is added
    delete d.name        remove an entry (deleting twice is harmless)
    if c { } else { }    conditionals; `else if` chains
    while c { }          loop while c is true
    for i = 0 to 10 { }  count up; `downto` counts down
    for i = 0 to 100 step 10 { }
    for x in a { }       walk a list, a string, or a dictionary's keys
    for k, v in d { }    walk a dictionary's pairs (or a list's index, item)
    break | continue     leave the loop / jump to the next turn
    try { } catch e { }  run anyway; e holds the message as a string
    try { } finally { }  the finally block always runs
    throw("gone wrong")  raise an error of your own
    import "f.nova"      run a file once; its exports are in f.<name>
    import "f.nova" as g       ...under the name g instead
    import "f.nova" with a, b  ...or bring specific names straight in
    export def f() { }   export let x = 1   mark a name as importable
    while c { } else { } the else runs only if no break happened
    def f(a) { return a } functions; print(...) is built in

  Scoping
    A name first assigned inside a block belongs to that block and is gone
    when the block ends. Assigning a name that already exists updates it,
    unless it lives outside the current function.

  Multi-line input: an unclosed '{' keeps the prompt open as '  ... '.
  Finish the block with '}' (or press Ctrl-C to throw the draft away).
  Ctrl-C also stops a runaway loop.

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


def needs_more_input(source):
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
    if needs_block and not any(t.type == TT_LBRACE for t in meaningful_for_def):
        return True

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
        if not more.strip() and not source.rstrip().endswith(("{", ",", "(")):
            # A blank line ends a draft that is only waiting on a '{'.
            if needs_more_input(source) and "{" not in source:
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


def run_bootstrap(args):
    """`--bootstrap program.nova` - run program.nova through novalang.nova,
    NovaLang's own self-hosted Lexer/Parser/Interpreter (Stage 10), instead
    of through this Python engine directly. See bootstrap.py."""
    if not args:
        print("usage: novalang.py --bootstrap <target.nova> [script args...]", file=sys.stderr)
        return 2
    import bootstrap
    return bootstrap.run_bootstrap(args[0], script_args=args[1:])


def main(argv):
    args = argv[1:]

    if not args:
        return repl()

    if args[0] == "--bootstrap":
        return run_bootstrap(args[1:])

    # `python3 novalang.py program.nova`  or  `python3 novalang.py "1 + 2"`
    try:
        with open(args[0], "r", encoding="utf-8") as handle:
            return run_source(handle.read(), args[0], script_args=args[1:])
    except (IOError, OSError):
        pass

    source = " ".join(args)
    interpreter = Interpreter()
    try:
        _, value = run(source, interpreter)
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
