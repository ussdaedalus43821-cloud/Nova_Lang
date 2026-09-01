#!/usr/bin/env python3
"""
NovaLang v0.1 - Stage 1: The REPL & Math Engine

A tiny language implemented in three classic pieces:

    source text  ->  Lexer   ->  tokens
    tokens       ->  Parser  ->  AST (Abstract Syntax Tree)
    AST          ->  Interpreter -> a number

No eval(). No regex tricks. Everything is built by hand so the pipeline
is visible end to end.
"""

import sys


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class NovaError(Exception):
    """A NovaLang error that points at the offending character."""

    def __init__(self, message, position=None):
        super().__init__(message)
        self.message = message
        self.position = position

    def render(self, source):
        """Build a friendly multi-line error report with a caret."""
        lines = ["  " + source]
        if self.position is not None and 0 <= self.position <= len(source):
            lines.append("  " + " " * self.position + "^")
        lines.append("NovaError: " + self.message)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. Lexer  (source text -> tokens)
# ---------------------------------------------------------------------------

# Token types. Plain strings keep the debug output readable.
TT_NUMBER = "NUMBER"
TT_IDENT  = "IDENT"
TT_PLUS   = "PLUS"
TT_MINUS  = "MINUS"
TT_STAR   = "STAR"
TT_SLASH  = "SLASH"
TT_LPAREN = "LPAREN"
TT_RPAREN = "RPAREN"
TT_EQUALS = "EQUALS"
TT_EOF    = "EOF"

SINGLE_CHAR_TOKENS = {
    "+": TT_PLUS,
    "-": TT_MINUS,
    "*": TT_STAR,
    "/": TT_SLASH,
    "(": TT_LPAREN,
    ")": TT_RPAREN,
    "=": TT_EQUALS,
}


class Token:
    def __init__(self, type_, value, position):
        self.type = type_
        self.value = value
        self.position = position

    def __repr__(self):
        return "Token({}, {!r})".format(self.type, self.value)


class Lexer:
    """Turns a line of source text into a flat list of tokens."""

    def __init__(self, source):
        self.source = source
        self.index = 0

    def peek(self):
        if self.index < len(self.source):
            return self.source[self.index]
        return None

    def advance(self):
        char = self.source[self.index]
        self.index += 1
        return char

    def tokenize(self):
        tokens = []
        while self.index < len(self.source):
            char = self.peek()

            # Whitespace is not significant - skip it.
            if char in " \t\r\n":
                self.advance()
                continue

            if char.isdigit() or char == ".":
                tokens.append(self.read_number())
                continue

            if char.isalpha() or char == "_":
                tokens.append(self.read_identifier())
                continue

            if char in SINGLE_CHAR_TOKENS:
                start = self.index
                self.advance()
                tokens.append(Token(SINGLE_CHAR_TOKENS[char], char, start))
                continue

            raise NovaError("unexpected character {!r}".format(char), self.index)

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

        if digits == ".":
            raise NovaError("'.' is not a number", start)

        value = float(digits) if seen_dot else int(digits)
        return Token(TT_NUMBER, value, start)

    def read_identifier(self):
        """Read a variable name: letters, digits and underscores."""
        start = self.index
        name = ""
        while self.peek() is not None and (self.peek().isalnum() or self.peek() == "_"):
            name += self.advance()
        return Token(TT_IDENT, name, start)


# ---------------------------------------------------------------------------
# 2. AST nodes
# ---------------------------------------------------------------------------

class Node:
    """Base class so every node prints nicely with `tree`."""

    def __repr__(self):
        fields = ", ".join(
            "{}={!r}".format(key, value) for key, value in vars(self).items()
        )
        return "{}({})".format(type(self).__name__, fields)


class NumberNode(Node):
    def __init__(self, value):
        self.value = value


class VarNode(Node):
    def __init__(self, name, position):
        self.name = name
        self.position = position


class AssignNode(Node):
    def __init__(self, name, value):
        self.name = name
        self.value = value


class UnaryOpNode(Node):
    def __init__(self, op, operand, position):
        self.op = op            # '+' or '-'
        self.operand = operand
        self.position = position


class BinOpNode(Node):
    def __init__(self, left, op, right, position):
        self.left = left
        self.op = op            # '+', '-', '*' or '/'
        self.right = right
        self.position = position


# ---------------------------------------------------------------------------
# 3. Parser  (tokens -> AST), recursive descent
# ---------------------------------------------------------------------------
#
# The grammar, lowest precedence first:
#
#   statement  := IDENT '=' statement
#               | expression
#   expression := term   (('+' | '-') term)*
#   term       := unary  (('*' | '/') unary)*
#   unary      := ('+' | '-') unary
#               | primary
#   primary    := NUMBER
#               | IDENT
#               | '(' expression ')'
#
# Each rule becomes one method. Because '+' and '-' are parsed in an outer
# loop and '*' and '/' in an inner one, multiplication binds tighter - that
# is exactly why 5 + 10 * 2 evaluates to 25 and not 30.
# ---------------------------------------------------------------------------

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0

    @property
    def current(self):
        return self.tokens[self.index]

    def advance(self):
        token = self.tokens[self.index]
        if token.type != TT_EOF:
            self.index += 1
        return token

    def expect(self, type_, description):
        if self.current.type != type_:
            raise NovaError("expected {}".format(description), self.current.position)
        return self.advance()

    def parse(self):
        """Parse one complete statement and make sure nothing is left over."""
        node = self.statement()
        if self.current.type != TT_EOF:
            raise NovaError(
                "unexpected {!r} after the end of the expression".format(self.current.value),
                self.current.position,
            )
        return node

    def statement(self):
        # Look ahead one token: IDENT '=' means assignment, anything else
        # is an ordinary expression.
        if self.current.type == TT_IDENT and self.tokens[self.index + 1].type == TT_EQUALS:
            name_token = self.advance()     # the identifier
            self.advance()                  # the '='
            value = self.statement()        # right-associative: a = b = 3
            return AssignNode(name_token.value, value)
        return self.expression()

    def expression(self):
        node = self.term()
        while self.current.type in (TT_PLUS, TT_MINUS):
            op_token = self.advance()
            right = self.term()
            node = BinOpNode(node, op_token.value, right, op_token.position)
        return node

    def term(self):
        node = self.unary()
        while self.current.type in (TT_STAR, TT_SLASH):
            op_token = self.advance()
            right = self.unary()
            node = BinOpNode(node, op_token.value, right, op_token.position)
        return node

    def unary(self):
        if self.current.type in (TT_PLUS, TT_MINUS):
            op_token = self.advance()
            return UnaryOpNode(op_token.value, self.unary(), op_token.position)
        return self.primary()

    def primary(self):
        token = self.current

        if token.type == TT_NUMBER:
            self.advance()
            return NumberNode(token.value)

        if token.type == TT_IDENT:
            self.advance()
            return VarNode(token.value, token.position)

        if token.type == TT_LPAREN:
            self.advance()
            node = self.expression()
            self.expect(TT_RPAREN, "a closing ')'")
            return node

        if token.type == TT_EOF:
            raise NovaError("the expression ends too early", token.position)

        raise NovaError("unexpected {!r}".format(token.value), token.position)


# ---------------------------------------------------------------------------
# 4. Interpreter  (AST -> a number), tree-walking
# ---------------------------------------------------------------------------

class Interpreter:
    """Walks the tree and folds it down to a single Python number."""

    def __init__(self):
        self.variables = {}

    def evaluate(self, node):
        method = getattr(self, "visit_" + type(node).__name__, None)
        if method is None:
            raise NovaError("cannot evaluate {}".format(type(node).__name__))
        return method(node)

    def visit_NumberNode(self, node):
        return node.value

    def visit_VarNode(self, node):
        if node.name not in self.variables:
            raise NovaError("undefined variable {!r}".format(node.name), node.position)
        return self.variables[node.name]

    def visit_AssignNode(self, node):
        value = self.evaluate(node.value)
        self.variables[node.name] = value
        return value

    def visit_UnaryOpNode(self, node):
        value = self.evaluate(node.operand)
        if node.op == "+":
            return value
        return -value

    def visit_BinOpNode(self, node):
        left = self.evaluate(node.left)
        right = self.evaluate(node.right)

        if node.op == "+":
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            if right == 0:
                raise NovaError("division by zero", node.position)
            result = left / right
            # Keep whole answers whole: 10 / 2 is 5, not 5.0
            if isinstance(left, int) and isinstance(right, int) and result.is_integer():
                return int(result)
            return result

        raise NovaError("unknown operator {!r}".format(node.op), node.position)


# ---------------------------------------------------------------------------
# The pipeline, in one place
# ---------------------------------------------------------------------------

def run(source, interpreter):
    tokens = Lexer(source).tokenize()
    ast = Parser(tokens).parse()
    return ast, interpreter.evaluate(ast)


def format_result(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# 5. The REPL
# ---------------------------------------------------------------------------

WELCOME = """╔═══════════════════════════════════╗
║       NOVALANG v0.1              ║
║   A star-born programming lang   ║
║   Type an expression or 'exit'   ║
╚═══════════════════════════════════╝"""

HELP = """NovaLang v0.1 commands
  <expression>   evaluate, e.g.  5 + 10 * 2
  x = 7          assign a variable, then use it:  x * 3
  vars           list the variables you have defined
  tree <expr>    show the AST instead of the answer
  help           show this message
  exit | quit    leave the REPL"""


def repl():
    print(WELCOME)
    interpreter = Interpreter()

    while True:
        try:
            source = input("nova> ")
        except EOFError:          # Ctrl-D
            print()
            print("Goodbye, star-traveller.")
            return 0
        except KeyboardInterrupt:  # Ctrl-C
            print()
            continue

        line = source.strip()

        if not line:
            continue

        lowered = line.lower()
        if lowered in ("exit", "quit"):
            print("Goodbye, star-traveller.")
            return 0
        if lowered == "help":
            print(HELP)
            continue
        if lowered == "vars":
            if not interpreter.variables:
                print("(no variables defined yet)")
            else:
                for name in sorted(interpreter.variables):
                    print("  {} = {}".format(name, format_result(interpreter.variables[name])))
            continue

        # 'tree <expr>' prints the AST - handy for seeing the parser's work.
        show_tree = False
        if lowered == "tree" or lowered.startswith("tree "):
            show_tree = True
            line = line[4:].strip()
            if not line:
                print("usage: tree <expression>")
                continue

        try:
            ast, value = run(line, interpreter)
        except NovaError as error:
            print(error.render(line))
            continue

        if show_tree:
            print(ast)
        else:
            print(format_result(value))


def main(argv):
    # `python3 novalang.py "5 + 10 * 2"` evaluates and exits; no args starts the REPL.
    args = argv[1:]
    if args:
        source = " ".join(args)
        try:
            _, value = run(source, Interpreter())
        except NovaError as error:
            print(error.render(source), file=sys.stderr)
            return 1
        print(format_result(value))
        return 0
    return repl()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
