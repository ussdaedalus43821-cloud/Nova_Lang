#!/usr/bin/env python3
"""
NovaLang v0.3 - Stage 3: Loops, Logic & Block Scoping

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

No eval(). No exec(). Everything is still built by hand.
"""

import sys

# A NovaLang call burns several Python frames, so give CPython some headroom
# and enforce our own, friendlier limit in the interpreter (MAX_CALL_DEPTH).
sys.setrecursionlimit(10000)

MAX_CALL_DEPTH = 200

# How many call-stack frames an error report shows before it elides the middle.
MAX_TRACE_FRAMES = 8


# ---------------------------------------------------------------------------
# Errors and the signals that unwind the interpreter
# ---------------------------------------------------------------------------

class NovaError(Exception):
    """A NovaLang error that points at the offending character."""

    def __init__(self, message, position=None):
        super().__init__(message)
        self.message = message
        self.position = position
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

        lines.append("NovaError: " + self.message)

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
}

COMPARISON_TOKENS = (TT_EQ, TT_NE, TT_LT, TT_GT, TT_LE, TT_GE)

SINGLE_CHAR_TOKENS = {
    "+": TT_PLUS,
    "-": TT_MINUS,
    "*": TT_STAR,
    "/": TT_SLASH,
    "(": TT_LPAREN,
    ")": TT_RPAREN,
    "{": TT_LBRACE,
    "}": TT_RBRACE,
    ",": TT_COMMA,
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

            if char.isalpha() or char == "_":
                tokens.append(self.read_identifier())
                continue

            if char in ('"', "'"):
                tokens.append(self.read_string())
                continue

            # Two-character operators must be tried before the one-char ones.
            two = self.source[self.index:self.index + 2]
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
BLOCK_STATEMENTS = (IfNode, WhileNode, ForNode, FunctionDefNode)


# ---------------------------------------------------------------------------
# 3. Parser  (tokens -> AST), recursive descent
# ---------------------------------------------------------------------------
#
# The grammar, loosest first. Each rule is one method below.
#
#   program     := (statement SEP)* EOF
#   statement   := funcdef | returnstmt | ifstmt | whilestmt | forstmt
#                | 'break' | 'continue' | assignment | expression
#   funcdef     := 'def' IDENT '(' [IDENT (',' IDENT)*] ')' block
#   returnstmt  := 'return' [expression]
#   ifstmt      := 'if' expression block ['else' (block | ifstmt)]
#   whilestmt   := 'while' expression block ['else' block]
#   forstmt     := 'for' IDENT '=' expression ('to' | 'downto') expression
#                  ['step' expression] block ['else' block]
#   assignment  := IDENT '=' (assignment | expression)
#   block       := '{' (statement SEP)* '}'
#
#   expression  := or_expr
#   or_expr     := and_expr ('or' and_expr)*
#   and_expr    := not_expr ('and' not_expr)*
#   not_expr    := 'not' not_expr | comparison
#   comparison  := additive [('<'|'>'|'<='|'>='|'=='|'!=') additive]
#   additive    := term (('+'|'-') term)*
#   term        := unary (('*'|'/') unary)*
#   unary       := ('+'|'-') unary | call
#   call        := primary ('(' [expression (',' expression)*] ')')*
#   primary     := NUMBER | STRING | 'true' | 'false' | IDENT
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
        if isinstance(statement, BLOCK_STATEMENTS):
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
        rewind = self.index
        self.skip_newlines()
        if self.current.type == TT_ELSE:
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
        if token.type == TT_IDENT and self.peek().type == TT_EQUALS:
            return self.assignment()
        return self.expression()

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
        self.expect(TT_EQUALS, "a '=' after the loop variable")

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

    def assignment(self):
        name_token = self.advance()                     # the identifier
        guard_name(name_token.value, name_token.position, "a variable")
        self.advance()                                  # the '='
        if self.current.type == TT_IDENT and self.peek().type == TT_EQUALS:
            value = self.assignment()                   # a = b = 3
        else:
            value = self.expression()
        return AssignNode(name_token.value, value, name_token.position)

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
        while self.current.type in (TT_STAR, TT_SLASH):
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
        while self.current.type == TT_LPAREN:
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
        return node

    def primary(self):
        token = self.current

        if token.type == TT_NUMBER:
            self.advance()
            return NumberNode(token.value)

        if token.type == TT_STRING:
            self.advance()
            return StringNode(token.value)

        if token.type == TT_TRUE:
            self.advance()
            return BooleanNode(True)

        if token.type == TT_FALSE:
            self.advance()
            return BooleanNode(False)

        if token.type == TT_IDENT:
            self.advance()
            return VarNode(token.value, token.position)

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

    def __init__(self, name, arity, implementation):
        self.name = name
        self.arity = arity              # an int, or None for "any number"
        self.implementation = implementation

    def __repr__(self):
        return "<built-in function {}>".format(self.name)


def builtin_print(args):
    print(" ".join(format_value(arg) for arg in args))
    return NOTHING


BUILTINS = {
    "print": BuiltinFunction("print", None, builtin_print),
}


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
    if isinstance(value, (NovaFunction, BuiltinFunction)):
        return "a function"
    return "nothing"


def format_value(value):
    """How a value prints: strings bare, booleans lowercase, ints without .0"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is NOTHING:
        return "nothing"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (NovaFunction, BuiltinFunction)):
        return repr(value)
    return str(value)


def format_repr(value):
    """How the REPL echoes a value: like format_value but strings are quoted."""
    if isinstance(value, str):
        return '"{}"'.format(
            value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
        )
    return format_value(value)


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

        raise NovaError("unknown operator {!r}".format(op), node.position)

    def visit_CompareNode(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)
        op = node.op

        if op == "==":
            return nova_equals(left, right)
        if op == "!=":
            return not nova_equals(left, right)

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

        if isinstance(callee, BuiltinFunction):
            if callee.arity is not None and len(args) != callee.arity:
                raise NovaError(
                    "{}() takes {} argument(s) but got {}".format(
                        callee.name, callee.arity, len(args)
                    ),
                    node.position,
                )
            return callee.implementation(args)

        if not isinstance(callee, NovaFunction):
            raise NovaError(
                "{} is not a function, so it cannot be called".format(type_name(callee)),
                node.position,
            )

        if len(args) != len(callee.params):
            raise NovaError(
                "{}() expects {} argument(s) but got {}".format(
                    callee.name, len(callee.params), len(args)
                ),
                node.position,
            )

        if len(self.call_stack) >= MAX_CALL_DEPTH:
            raise NovaError(
                "call depth of {} exceeded - is the recursion missing a base case?".format(
                    MAX_CALL_DEPTH
                ),
                node.position,
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
║       NOVALANG v0.3              ║
║   A star-born programming lang   ║
║   Type an expression or 'exit'   ║
╚═══════════════════════════════════╝"""

HELP = """NovaLang v0.3 - commands and syntax

  REPL commands
    vars                 list the globals you have defined
    tree <code>          show the AST instead of running it
    help                 show this message
    exit | quit          leave the REPL

  Values
    numbers              1, 42, 3.14      strings  "hi", 'hi'
    booleans             true, false      comments # to end of line

  Expressions
    + - * /              arithmetic, and "a" + "b" joins strings
    < > <= >= == !=      comparisons, producing true or false
    and or not           short-circuit logic: `not done and i < 10`

  Statements
    x = 10               assignment
    if c { } else { }    conditionals; `else if` chains
    while c { }          loop while c is true
    for i = 0 to 10 { }  count up; `downto` counts down
    for i = 0 to 100 step 10 { }
    break | continue     leave the loop / jump to the next turn
    while c { } else { } the else runs only if no break happened
    def f(a) { return a } functions; print(...) is built in

  Scoping
    A name first assigned inside a block belongs to that block and is gone
    when the block ends. Assigning a name that already exists updates it,
    unless it lives outside the current function.

  Multi-line input: an unclosed '{' keeps the prompt open as '  ... '.
  Finish the block with '}' (or press Ctrl-C to throw the draft away).
  Ctrl-C also stops a runaway loop."""

# Tokens that clearly cannot end a statement, so the REPL keeps reading.
CONTINUATION_TOKENS = (
    TT_DEF, TT_ELSE, TT_LBRACE, TT_COMMA, TT_LPAREN, TT_EQUALS,
    TT_PLUS, TT_MINUS, TT_STAR, TT_SLASH,
    TT_EQ, TT_NE, TT_LT, TT_GT, TT_LE, TT_GE,
    TT_WHILE, TT_FOR, TT_IF, TT_TO, TT_DOWNTO, TT_STEP,
    TT_AND, TT_OR, TT_NOT,
)

# Statements whose header is followed by a '{' block.
BLOCK_OPENERS = (TT_DEF, TT_IF, TT_WHILE, TT_FOR)


def needs_more_input(source):
    """Decide whether the REPL should keep collecting lines."""
    try:
        tokens = Lexer(source).tokenize()
    except NovaError:
        return False                    # let the real error surface

    depth = 0
    for token in tokens:
        if token.type == TT_LBRACE:
            depth += 1
        elif token.type == TT_RBRACE:
            depth -= 1
    if depth > 0:
        return True

    meaningful = [t for t in tokens if t.type not in (TT_NEWLINE, TT_EOF)]
    if not meaningful:
        return False

    # `while x < 10` or `def fib(n)` with the '{' still to come next line.
    if meaningful[0].type in BLOCK_OPENERS and not any(t.type == TT_LBRACE for t in meaningful):
        return True

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

def run_source(source, origin):
    """Run a whole program (a file, or code from the command line)."""
    interpreter = Interpreter()
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


def main(argv):
    args = argv[1:]

    if not args:
        return repl()

    # `python3 novalang.py program.nova`  or  `python3 novalang.py "1 + 2"`
    try:
        with open(args[0], "r", encoding="utf-8") as handle:
            return run_source(handle.read(), args[0])
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
