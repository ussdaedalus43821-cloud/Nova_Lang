"""
nova_ast.py - the shared front end of the NovaLang toolchain.

nova-fmt and nova-lint both need more from the source than the interpreter
does: the formatter has to put every comment back and keep literals spelled
the way they were written, and both tools need to know where statements
start and end. None of that is the interpreter's business, so instead of
changing novalang.py this module subclasses its Lexer and Parser:

    TriviaLexer   produces exactly the same token stream as Lexer (so the
                  parser cannot behave differently), and additionally
                  records every comment, each token's end offset, and the
                  raw source text of number / string / f-string literals.

    SpanParser    builds exactly the same AST as Parser, and additionally
                  stamps statements and expressions with `_start` / `_end`
                  source offsets, plus a few private layout hints. Every
                  extra attribute starts with '_', which is what lets
                  `shape()` compare two trees while ignoring them.

    Visitor       a dispatch-table walker: the table from node class to
                  handler is built once per Visitor subclass, so a visit is
                  one dict lookup instead of the interpreter's per-node
                  getattr("visit_" + name). A node class with no handler is
                  a loud error, never a silent skip.

Measured on novalang.nova (2,206 lines, 8,030 nodes): lexing ~32 ms,
parsing ~17 ms, a full generic walk ~10 ms. That is nowhere near a
bottleneck, so the "unchecked core" split (validate once at the public
entry point, then run an inner loop that skips per-node checks) is
deliberately NOT applied here. If profiling ever shows the walk dominating,
that is the documented next step: keep `Visitor.visit` as the checked entry
and give hot handlers direct references to each other's table entries.
"""

import bisect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import novalang as nl  # noqa: E402
from novalang import NovaError  # noqa: E402,F401  (re-exported for the tools)


# ---------------------------------------------------------------------------
# Lexing with trivia
# ---------------------------------------------------------------------------

class Comment:
    """One `# ...` comment. `trailing` means code precedes it on its line."""

    __slots__ = ("start", "end", "text", "trailing")

    def __init__(self, start, end, text, trailing):
        self.start = start
        self.end = end
        self.text = text
        self.trailing = trailing

    def __repr__(self):
        return "Comment({}, {!r}, trailing={})".format(self.start, self.text, self.trailing)


class TriviaLexer(nl.Lexer):
    """Lexer that also keeps comments, token ends and raw literal text."""

    def read_number(self):
        start = self.index
        token = super().read_number()
        token.raw = self.source[start:self.index]
        return token

    def read_string(self):
        start = self.index
        token = super().read_string()
        token.raw = self.source[start:self.index]
        return token

    def read_fstring(self):
        start = self.index
        token = super().read_fstring()
        token.raw = self.source[start:self.index]
        return token

    def tokenize(self):
        tokens = super().tokenize()
        self.comments = []
        previous = None
        previous_end = 0
        for token in tokens:
            token.end = token_end(token)
            # Between two tokens there is only spaces, tabs, '\r' and at
            # most one comment: a comment runs up to a '\n', and a '\n' is
            # a token of its own.
            gap = self.source[previous_end:token.position]
            hash_at = gap.find("#")
            if hash_at != -1:
                start = previous_end + hash_at
                text = gap[hash_at:].rstrip()
                trailing = previous is not None and previous.value != "\n"
                self.comments.append(Comment(start, start + len(text), text, trailing))
            previous = token
            previous_end = token.end
        return tokens


def token_end(token):
    raw = getattr(token, "raw", None)
    if raw is not None:
        return token.position + len(raw)
    if token.type == nl.TT_EOF:
        return token.position
    return token.position + len(str(token.value))


# ---------------------------------------------------------------------------
# Parsing with spans
# ---------------------------------------------------------------------------

class SpanParser(nl.Parser):
    """Parser that stamps nodes with source spans and layout hints."""

    def last_end(self):
        return self.tokens[self.index - 1].end if self.index > 0 else 0

    def statement(self):
        start = self.current.position
        node = super().statement()
        node._start = start
        node._end = self.last_end()
        return node

    def expression(self):
        start = self.current.position
        node = super().expression()
        # A parenthesised expression comes back through here twice; the
        # outer call finishes last, so the widest span (parens included) wins.
        node._start = start
        node._end = self.last_end()
        return node

    def block(self):
        node = super().block()
        node._end = self.last_end()
        return node

    def primary(self):
        token = self.current
        first = self.index
        node = super().primary()
        if token.type in (nl.TT_NUMBER, nl.TT_STRING):
            node._raw = token.raw
        elif token.type == nl.TT_FSTRING:
            node._quote = token.raw[1]
        elif token.type in (nl.TT_LBRACKET, nl.TT_LBRACE):
            node._start = token.position
            node._end = self.last_end()
            # The author broke the line straight after the opening bracket:
            # keep it exploded, one item per line (black's "magic comma").
            node._multiline = self.tokens[first + 1].type == nl.TT_NEWLINE
        return node

    def dict_literal(self, brace):
        # Remember how each key was spelled: a quoted key stays quoted.
        self._key_tokens = getattr(self, "_key_tokens", [])
        self._key_tokens.append([])
        try:
            node = super().dict_literal(brace)
        finally:
            keys = self._key_tokens.pop()
        for entry, token in zip(node.entries, keys):
            entry._raw_key = token.raw if token.type == nl.TT_STRING else token.value
        return node

    def name_token(self, what, allow_string=False):
        token = super().name_token(what, allow_string)
        if allow_string and getattr(self, "_key_tokens", None):
            self._key_tokens[-1].append(token)
        return token

    def delete_statement(self):
        node = super().delete_statement()
        if isinstance(node, nl.DeleteNode):
            # `delete d.key` and `delete d["key"]` give the same node;
            # remember which one was written.
            node._via_member = self.tokens[self.index - 1].type != nl.TT_RBRACKET
        return node

    def interpolation(self, token):
        """Same as Parser.interpolation, but the holes keep spans and raws."""
        parts = []
        for part in token.value:
            if part[0] == "text":
                parts.append(nl.StringNode(part[1]))
                continue
            _, source, offset = part
            inner_tokens = TriviaLexer(source).tokenize()
            for inner_token in inner_tokens:
                inner_token.position += offset
                inner_token.end += offset
            inner = SpanParser(inner_tokens)
            parts.append(inner.expression())
            if inner.current.type != nl.TT_EOF:
                raise NovaError(
                    "unexpected {} inside this f-string".format(nl.describe(inner.current)),
                    inner.current.position,
                )
        return nl.InterpolationNode(parts, token.position)


class Parsed:
    """Everything the tools need about one source file."""

    def __init__(self, source, tree, tokens, comments):
        self.source = source
        self.tree = tree
        self.tokens = tokens
        self.comments = comments
        self.lines = LineIndex(source)
        self.starts = [token.position for token in tokens]

    def name_after(self, position, name):
        """(start, end) of the first `name` token at or after `position`.
        A binding records where its statement starts - the `let`, the
        `def`, the `for` - and this finds the name itself from there.
        None if there is no such token (a package binding such as
        math_utils is never written out)."""
        index = bisect.bisect_left(self.starts, position or 0)
        for token in self.tokens[index:]:
            if token.type == nl.TT_IDENT and token.value == name:
                return token.position, token.end
        return None


def parse(source):
    """Lex and parse `source`; raises NovaError exactly as novalang.py would."""
    lexer = TriviaLexer(source)
    tokens = lexer.tokenize()
    tree = SpanParser(tokens).parse()
    return Parsed(source, tree, tokens, lexer.comments)


class LineIndex:
    """Offset -> 1-based (line, column), by bisecting the newline offsets."""

    def __init__(self, source):
        # Lines break where the Lexer breaks them: "\n", "\r\n", lone "\r".
        self.starts = [start for start, _ in nl.line_spans(source)]

    def line(self, offset):
        return bisect.bisect_right(self.starts, offset)

    def column(self, offset):
        return offset - self.starts[self.line(offset) - 1] + 1


# ---------------------------------------------------------------------------
# Comparing trees
# ---------------------------------------------------------------------------

def shape(value):
    """A hashable, comparable picture of an AST, ignoring positions and the
    private '_' layout hints. Two sources with equal shapes run identically.
    Leaf values carry their Python type, so 1, 1.0 and true stay distinct."""
    if isinstance(value, nl.Node):
        fields = tuple(
            (key, shape(field))
            for key, field in sorted(vars(value).items())
            if key != "position" and not key.startswith("_")
        )
        return (type(value).__name__, fields)
    if isinstance(value, (list, tuple)):
        return tuple(shape(item) for item in value)
    return (type(value).__name__, value)


# ---------------------------------------------------------------------------
# Dispatch-table visitor
# ---------------------------------------------------------------------------

NODE_CLASSES = {
    name: cls
    for name, cls in vars(nl).items()
    if isinstance(cls, type) and issubclass(cls, nl.Node) and cls is not nl.Node
}


class Visitor:
    """Subclasses define `<prefix><NodeName>` methods (prefix defaults to
    'visit_'); the class-to-method table is built once, at class creation."""

    prefix = "visit_"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        table = {}
        for attr in dir(cls):
            if attr.startswith(cls.prefix):
                node_name = attr[len(cls.prefix):]
                if node_name not in NODE_CLASSES:
                    raise TypeError("{}.{} names no AST node".format(cls.__name__, attr))
                table[NODE_CLASSES[node_name]] = getattr(cls, attr)
        cls._table = table

    def visit(self, node, *args):
        try:
            handler = self._table[type(node)]
        except KeyError:
            raise TypeError(
                "{} has no handler for {}".format(type(self).__name__, type(node).__name__)
            ) from None
        return handler(self, node, *args)
