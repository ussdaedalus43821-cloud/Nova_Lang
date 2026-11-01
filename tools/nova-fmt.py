#!/usr/bin/env python3
"""
nova-fmt - the NovaLang formatter (standardized work).

    python3 tools/nova-fmt.py file.nova            print the formatted file
    python3 tools/nova-fmt.py --write a.nova ...   reformat files in place
    python3 tools/nova-fmt.py --check a.nova ...   exit 1 if any would change

The house style: 4-space indentation, '{' on the header line, `} else {`
cuddled, one statement per line (';' becomes a newline), single spaces
around binary operators, ', ' between items, at most one blank line in a
row. Lists and dictionaries stay on one line when they fit in 100 columns,
unless the author broke the line straight after the opening bracket or a
comment sits inside them; then they go one item per line. Number and
string literals are reproduced exactly as written, and every comment is
kept.

Built-in quality (jidoka): before any output is produced, the result is
re-parsed and checked three ways. Its AST must equal the original's
(positions aside), its comments must be the original's, in order, and
formatting it again must change nothing. If any check fails the formatter
stops with an error and writes nothing.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nova_ast  # noqa: E402
from nova_ast import NovaError, Visitor, nl  # noqa: E402

INDENT = "    "
WIDTH = 100

# Binding strength, loosest first - one level per rule of the grammar.
P_OR, P_AND, P_NOT, P_COMPARE, P_ADD, P_MUL, P_UNARY, P_POSTFIX, P_ATOM = range(1, 10)

BINARY_PRECEDENCE = {"+": P_ADD, "-": P_ADD, "*": P_MUL, "/": P_MUL, "%": P_MUL, "//": P_MUL}

ESCAPE_BACK = {"\\": "\\\\", "\n": "\\n", "\t": "\\t", "\r": "\\r", "\0": "\\0"}

ASSIGNMENTS = (nl.AssignNode, nl.IndexAssignNode, nl.MemberAssignNode)


class FormatError(Exception):
    """The formatter refused to produce output (it would have broken code)."""


def quote(text, mark='"', fstring=False):
    out = []
    for char in text:
        if char in ESCAPE_BACK:
            out.append(ESCAPE_BACK[char])
        elif char == mark:
            out.append("\\" + char)
        elif fstring and char in "{}":
            out.append(char * 2)
        else:
            out.append(char)
    return mark + "".join(out) + mark


def bare_name(key):
    """Can this dictionary key be written without quotes?"""
    return bool(key) and (key[0].isalpha() or key[0] == "_") and all(
        char.isalnum() or char == "_" for char in key
    )


def after(col, text):
    """The column just past `text` when it is written starting at `col`."""
    if "\n" in text:
        return len(text.rsplit("\n", 1)[1])
    return col + len(text)


class Formatter(Visitor):
    """Expressions: ex_<Node>(node, depth, col) -> (text, precedence).
    Statements are written line by line into self.out."""

    prefix = "ex_"

    def __init__(self, parsed):
        self.source = parsed.source
        self.lines = parsed.lines
        self.comments = parsed.comments
        self.next_comment = 0
        self.out = []
        self.trailing = {}              # index into self.out -> comment text
        self.last_source = 0            # source offset of the last thing written
        self.flat = 0                   # >0 inside an f-string hole: no line breaks

    # -- driver -------------------------------------------------------------

    def format(self, tree):
        self.statements(tree.statements, 0, len(self.source))
        self.align_trailing()
        while self.out and self.out[-1] == "":
            self.out.pop()
        return "".join(line.rstrip() + "\n" for line in self.out)

    # -- comments -----------------------------------------------------------

    def pending(self, before):
        """Is there an unwritten comment that starts before `before`?"""
        return (
            self.next_comment < len(self.comments)
            and self.comments[self.next_comment].start < before
        )

    def take(self):
        comment = self.comments[self.next_comment]
        self.next_comment += 1
        return comment

    def trailing_for(self, end, limit):
        """Take the comment that trails the code ending at `end`, if any."""
        if not self.pending(limit):
            return None
        comment = self.comments[self.next_comment]
        if comment.trailing and self.lines.line(comment.start) == self.lines.line(max(end - 1, 0)):
            return self.take()
        return None

    def blank_before(self, offset):
        return self.source.count("\n", self.last_source, offset) >= 2

    # -- statements ---------------------------------------------------------

    def line(self, depth, text):
        self.out.append(INDENT * depth + text)

    def statements(self, statements, depth, end):
        """Write a run of statements plus the comments around them."""
        first = True
        for index, statement in enumerate(statements):
            first = self.own_line_comments(statement._start, depth, first)
            if not first and self.blank_before(statement._start):
                self.out.append("")
            self.statement(statement, depth)
            self.last_source = statement._end
            # `a; b  # note` - the note belongs to the last statement, b.
            limit = statements[index + 1]._start if index + 1 < len(statements) else end
            self.attach_trailing(statement._end, limit)
            first = False
        self.own_line_comments(end, depth, first)

    def own_line_comments(self, before, depth, first):
        while self.pending(before):
            comment = self.take()
            if not first and self.blank_before(comment.start):
                self.out.append("")
            self.line(depth, comment.text)
            self.last_source = comment.end
            first = False
        return first

    def attach_trailing(self, end, limit):
        comment = self.trailing_for(end, limit)
        if comment is not None:
            self.trailing[len(self.out) - 1] = comment.text
            self.last_source = comment.end

    def align_trailing(self):
        align(self.out, self.trailing)

    def statement(self, node, depth, prefix=""):
        handler = STATEMENTS.get(type(node))
        if handler is not None:
            handler(self, node, depth, prefix)
        else:
            col = len(INDENT) * depth + len(prefix)
            self.line(depth, prefix + self.expr(node, depth, col))

    def clauses(self, parts, depth):
        """Write `head { ... } head { ... }` for a compound statement.
        `parts` is a list of (header text, BlockNode)."""
        current = INDENT * depth
        for index, (header, block) in enumerate(parts):
            last = index == len(parts) - 1
            current += header + " {"
            single = len(parts) == 1    # never `{} else {` or `{ x } else {`
            inline = self.inline_body(block, depth) if single else None
            if single and not block.statements and not self.pending(block._end):
                current += "}"          # `def f() {}`
            elif inline is not None and len(current) + len(inline) + 3 <= WIDTH:
                current += " " + inline + " }"
                self.last_source = block._end
            else:
                self.out.append(current)
                self.last_source = block.position + 1
                self.attach_trailing(block.position + 1, block._end)
                self.statements(block.statements, depth + 1, block._end)
                current = INDENT * depth + "}"
            if last:
                self.out.append(current)
            else:
                current += " "

    def inline_body(self, block, depth):
        """The text of a one-statement block the author wrote on one line,
        if it can stay that way: `for x in xs { print(x) }`."""
        if (
            len(block.statements) != 1
            or type(block.statements[0]) in COMPOUND
            or self.pending(block._end)
            or self.lines.line(block.position) != self.lines.line(block._end - 1)
        ):
            return None
        saved = self.out
        self.out = []
        try:
            self.statement(block.statements[0], depth + 1)
            lines = self.out
        finally:
            self.out = saved
        if len(lines) != 1 or "\n" in lines[0]:
            return None
        return lines[0].strip()

    def header(self, depth, prefix, keyword, node, lead=0):
        """`prefix keyword <node>`; `lead` counts characters written before
        the header on the same line (the '} ' of an `} else if`)."""
        col = len(INDENT) * depth + lead + len(prefix) + len(keyword)
        return prefix + keyword + self.expr(node, depth, col)

    def st_If(self, node, depth, prefix):
        parts = []
        keyword = "if "
        lead = 0
        while True:
            parts.append(
                (self.header(depth, prefix, keyword, node.condition, lead), node.then_block)
            )
            prefix = ""
            else_block = node.else_block
            if isinstance(else_block, nl.IfNode):
                node = else_block
                keyword = "else if "
                lead = len("} ")
                continue
            if else_block is not None:
                parts.append(("else", else_block))
            break
        self.clauses(parts, depth)

    def st_While(self, node, depth, prefix):
        parts = [(self.header(depth, prefix, "while ", node.condition), node.body)]
        if node.else_block is not None:
            parts.append(("else", node.else_block))
        self.clauses(parts, depth)

    def st_For(self, node, depth, prefix):
        text = "{}for {} = ".format(prefix, node.name)
        col = len(INDENT) * depth
        text += self.expr(node.start, depth, after(col, text))
        text += " downto " if node.descending else " to "
        text += self.expr(node.end, depth, after(col, text))
        if node.step is not None:
            text += " step "
            text += self.expr(node.step, depth, after(col, text))
        parts = [(text, node.body)]
        if node.else_block is not None:
            parts.append(("else", node.else_block))
        self.clauses(parts, depth)

    def st_ForIn(self, node, depth, prefix):
        names = node.name if node.second_name is None else node.name + ", " + node.second_name
        parts = [(self.header(depth, prefix, "for {} in ".format(names), node.iterable), node.body)]
        if node.else_block is not None:
            parts.append(("else", node.else_block))
        self.clauses(parts, depth)

    def st_FunctionDef(self, node, depth, prefix):
        header = "{}def {}({})".format(prefix, node.name, ", ".join(node.params))
        self.clauses([(header, node.body)], depth)

    def st_Try(self, node, depth, prefix):
        parts = [(prefix + "try", node.body)]
        if node.catch_block is not None:
            name = "" if node.catch_name is None else " " + node.catch_name
            parts.append(("catch" + name, node.catch_block))
        if node.finally_block is not None:
            parts.append(("finally", node.finally_block))
        self.clauses(parts, depth)

    def st_Export(self, node, depth, prefix):
        self.statement(node.inner, depth, prefix + "export ")

    def st_Let(self, node, depth, prefix):
        text = "{}let {} = ".format(prefix, node.name)
        self.line(depth, text + self.value(node.value, depth, len(INDENT) * depth + len(text)))

    def st_Assignment(self, node, depth, prefix):
        col = len(INDENT) * depth + len(prefix)
        self.line(depth, prefix + self.assignment(node, depth, col))

    def st_Return(self, node, depth, prefix):
        if node.value is None:
            self.line(depth, prefix + "return")
        else:
            self.line(depth, self.header(depth, prefix, "return ", node.value))

    def st_Throw(self, node, depth, prefix):
        # Written call-style, as in the docs and every program in the repo.
        self.line(depth, self.header(depth, prefix, "throw(", node.value) + ")")

    def st_Break(self, node, depth, prefix):
        self.line(depth, prefix + "break")

    def st_Continue(self, node, depth, prefix):
        self.line(depth, prefix + "continue")

    def st_Import(self, node, depth, prefix):
        text = prefix + "import " + quote(node.path)
        if node.alias is not None:
            text += " as " + node.alias
        elif node.names is not None:
            text += " with " + ", ".join(node.names)
        self.line(depth, text)

    def st_Delete(self, node, depth, prefix):
        col = len(INDENT) * depth + len(prefix) + len("delete ")
        target = self.operand(node.target, P_POSTFIX, depth, col)
        if getattr(node, "_via_member", False) and isinstance(node.key, nl.StringNode):
            text = target + "." + node.key.value
        else:
            text = target + "[" + self.expr(node.key, depth, after(col, target) + 1) + "]"
        self.line(depth, prefix + "delete " + text)

    def st_DeleteFile(self, node, depth, prefix):
        self.line(depth, self.header(depth, prefix, "delete(", node.path) + ")")

    # -- assignments --------------------------------------------------------

    def assignment(self, node, depth, col):
        if isinstance(node, nl.AssignNode):
            left = node.name
        elif isinstance(node, nl.IndexAssignNode):
            target = self.operand(node.target, P_POSTFIX, depth, col)
            left = target + "[" + self.expr(node.index, depth, after(col, target) + 1) + "]"
        else:
            left = self.operand(node.target, P_POSTFIX, depth, col) + "." + node.name
        left += " = "
        return left + self.value(node.value, depth, after(col, left))

    def value(self, node, depth, col):
        """The right side of '=': an expression, or another assignment."""
        if isinstance(node, ASSIGNMENTS):
            return self.assignment(node, depth, col)
        return self.expr(node, depth, col)

    # -- expressions --------------------------------------------------------

    def expr(self, node, depth, col):
        return self.visit(node, depth, col)[0]

    def operand(self, node, minimum, depth, col, wrap_logical=None):
        """Render `node`, parenthesised if it binds looser than `minimum`
        (or, for readability, if it is an and/or mixed into the other)."""
        text, precedence = self.visit(node, depth, col + 1)
        needs = precedence < minimum or (
            wrap_logical is not None
            and isinstance(node, nl.LogicalOpNode)
            and node.op == wrap_logical
        )
        if needs:
            return "(" + text + ")"
        # Rendered at col + 1 to leave room for a '(': re-render at col if
        # the text is position-sensitive (it contains a line break).
        if "\n" in text:
            return self.visit(node, depth, col)[0]
        return text

    def ex_NumberNode(self, node, depth, col):
        raw = getattr(node, "_raw", None)
        if raw is None:
            raw = repr(node.value)
        return raw, P_ATOM

    def ex_StringNode(self, node, depth, col):
        raw = getattr(node, "_raw", None)
        return (raw if raw is not None else quote(node.value)), P_ATOM

    def ex_BooleanNode(self, node, depth, col):
        return ("true" if node.value else "false"), P_ATOM

    def ex_VarNode(self, node, depth, col):
        return node.name, P_ATOM

    def ex_UnaryOpNode(self, node, depth, col):
        # `-(-1)`, never `--1`.
        minimum = P_ATOM if isinstance(node.operand, nl.UnaryOpNode) else P_UNARY
        return node.op + self.operand(node.operand, minimum, depth, col + 1), P_UNARY

    def ex_NotNode(self, node, depth, col):
        # `not a in b` is legal but reads ambiguously: keep `not (a in b)`.
        minimum = P_ATOM if isinstance(node.operand, nl.CompareNode) else P_NOT
        return "not " + self.operand(node.operand, minimum, depth, col + 4), P_NOT

    def ex_BinOpNode(self, node, depth, col):
        level = BINARY_PRECEDENCE[node.op]
        left_min = level
        if (
            level == P_MUL
            and isinstance(node.left, nl.BinOpNode)
            and node.left.op != node.op
            and BINARY_PRECEDENCE[node.left.op] == P_MUL
        ):
            # `(a // b) % 2` stays: mixed * / // % are easy to misread.
            left_min = P_MUL + 1
        return self.infix(node, level, left_min, level + 1, depth, col)

    def ex_CompareNode(self, node, depth, col):
        # Comparisons do not chain, so both sides must bind tighter.
        return self.infix(node, P_COMPARE, P_ADD, P_ADD, depth, col)

    def ex_LogicalOpNode(self, node, depth, col):
        level = P_OR if node.op == "or" else P_AND
        other = "and" if node.op == "or" else "or"
        left = self.operand(node.left, level, depth, col, wrap_logical=other)
        middle = " " + node.op + " "
        right = self.operand(node.right, level + 1, depth, after(col, left + middle), other)
        return left + middle + right, level

    def infix(self, node, level, left_min, right_min, depth, col):
        left = self.operand(node.left, left_min, depth, col)
        middle = " " + node.op + " "
        right = self.operand(node.right, right_min, depth, after(col, left + middle))
        return left + middle + right, level

    def postfix_target(self, node, depth, col):
        if isinstance(node, nl.NumberNode):
            # `1.x` would lex as the number `1.` followed by `x`.
            return "(" + self.expr(node, depth, col + 1) + ")"
        return self.operand(node, P_POSTFIX, depth, col)

    def ex_CallNode(self, node, depth, col):
        text = self.postfix_target(node.callee, depth, col) + "("
        for index, arg in enumerate(node.args):
            if index:
                text += ", "
            text += self.expr(arg, depth, after(col, text))
        return text + ")", P_POSTFIX

    def ex_IndexNode(self, node, depth, col):
        target = self.postfix_target(node.target, depth, col)
        index = self.expr(node.index, depth, after(col, target) + 1)
        return target + "[" + index + "]", P_POSTFIX

    def ex_SliceNode(self, node, depth, col):
        text = self.postfix_target(node.target, depth, col) + "["
        if node.start is not None:
            text += self.expr(node.start, depth, after(col, text))
        text += ":"
        if node.end is not None:
            text += self.expr(node.end, depth, after(col, text))
        return text + "]", P_POSTFIX

    def ex_MemberNode(self, node, depth, col):
        return self.postfix_target(node.target, depth, col) + "." + node.name, P_POSTFIX

    def ex_InterpolationNode(self, node, depth, col):
        mark = getattr(node, "_quote", '"')
        pieces = []
        self.flat += 1
        try:
            for part in node.parts:
                if isinstance(part, nl.StringNode) and not hasattr(part, "_start"):
                    pieces.append(quote(part.value, mark, fstring=True)[1:-1])
                    continue
                hole = self.expr(part, depth, 0)
                if hole.startswith("{"):
                    hole = " " + hole + " "     # `{{` would read as a literal brace
                pieces.append("{" + hole + "}")
        finally:
            self.flat -= 1
        return "f" + mark + "".join(pieces) + mark, P_ATOM

    def ex_ListNode(self, node, depth, col):
        return self.collection(node, node.items, "[", "]", self.list_item, depth, col), P_ATOM

    def ex_DictNode(self, node, depth, col):
        return self.collection(node, node.entries, "{", "}", self.dict_entry, depth, col), P_ATOM

    def list_item(self, item, depth, col):
        return self.expr(item, depth, col)

    def dict_entry(self, entry, depth, col):
        key = getattr(entry, "_raw_key", None)
        if key is None:
            key = entry.key if bare_name(entry.key) else quote(entry.key)
        key += ": "
        return key + self.expr(entry.value, depth, after(col, key))

    def collection(self, node, items, opening, closing, render, depth, col):
        end = getattr(node, "_end", None)
        has_comments = end is not None and self.pending(end)
        if not items and not has_comments:
            return opening + closing
        if not has_comments:
            text = opening
            for index, item in enumerate(items):
                if index:
                    text += ", "
                text += render(item, depth, after(col, text))
            text += closing
            if self.flat or (
                not getattr(node, "_multiline", False)
                and "\n" not in text
                and col + len(text) <= WIDTH
            ):
                return text
        return self.exploded(node, items, opening, closing, render, depth)

    def exploded(self, node, items, opening, closing, render, depth):
        inner = INDENT * (depth + 1)
        lines = [opening]
        end = node._end
        self.last_source = node._start + 1
        grouped = getattr(node, "_multiline", False)
        line_open = False               # can the last line take another item?
        trailing = {}
        comment = self.trailing_for(node._start + 1, item_start(items[0]) if items else end)
        if comment is not None:
            lines[0] += "  " + comment.text  # `let xs = [  # note`
            self.last_source = comment.end
        first = True
        for index, item in enumerate(items):
            start = item_start(item)
            while self.pending(start):
                comment = self.take()
                if not first and self.blank_before(comment.start):
                    lines.append("")
                lines.append(inner + comment.text)
                self.last_source = comment.end
                line_open = False
                first = False
            # An author-exploded collection keeps its hand-made grouping:
            # an item that shared a source line with the one before it
            # (and no comment came between) shares an output line too.
            joined = (
                grouped
                and line_open
                and self.lines.line(start) == self.lines.line(max(self.last_source - 1, 0))
            )
            if not joined and not first and self.blank_before(start):
                lines.append("")
            if joined:
                trailing.pop(len(lines) - 1, None)
                text = lines.pop() + " "
                text += render(item, depth + 1, len(text))
            else:
                text = inner + render(item, depth + 1, len(inner))
            if index < len(items) - 1:
                text += ","
            item_end = item_finish(item)
            self.last_source = item_end
            # A comment after a later item on the same line is that item's.
            limit = item_start(items[index + 1]) if index + 1 < len(items) else end
            comment = self.trailing_for(item_end, limit)
            if comment is not None:
                trailing[len(lines)] = comment.text
                self.last_source = comment.end
            lines.append(text)
            line_open = comment is None     # nothing may follow a comment
            first = False
        while self.pending(end):
            comment = self.take()
            lines.append(inner + comment.text)
            self.last_source = comment.end
        lines.append(INDENT * depth + closing)
        self.last_source = end
        align(lines, trailing)
        return "\n".join(lines)


def align(lines, trailing):
    """Attach trailing comments (`trailing` maps a line index to its text).
    A run of consecutive single-line entries that all carry one shares a
    single comment column, two spaces past the longest."""
    index = 0
    while index < len(lines):
        if index not in trailing:
            index += 1
            continue
        if "\n" in lines[index]:               # ends an exploded literal
            lines[index] += "  " + trailing[index]
            index += 1
            continue
        run = [index]
        while run[-1] + 1 in trailing and "\n" not in lines[run[-1] + 1]:
            run.append(run[-1] + 1)
        column = max(len(lines[i]) for i in run) + 2
        for i in run:
            lines[i] = lines[i].ljust(column) + trailing[i]
        index = run[-1] + 1


def item_start(item):
    if isinstance(item, nl.DictEntryNode):
        return item.position
    return item._start


def item_finish(item):
    if isinstance(item, nl.DictEntryNode):
        return item.value._end
    return item._end


COMPOUND = (
    nl.IfNode, nl.WhileNode, nl.ForNode, nl.ForInNode, nl.FunctionDefNode, nl.TryNode,
    nl.ExportNode,
)

STATEMENTS = {
    nl.IfNode: Formatter.st_If,
    nl.WhileNode: Formatter.st_While,
    nl.ForNode: Formatter.st_For,
    nl.ForInNode: Formatter.st_ForIn,
    nl.FunctionDefNode: Formatter.st_FunctionDef,
    nl.TryNode: Formatter.st_Try,
    nl.ExportNode: Formatter.st_Export,
    nl.LetNode: Formatter.st_Let,
    nl.AssignNode: Formatter.st_Assignment,
    nl.IndexAssignNode: Formatter.st_Assignment,
    nl.MemberAssignNode: Formatter.st_Assignment,
    nl.ReturnNode: Formatter.st_Return,
    nl.ThrowNode: Formatter.st_Throw,
    nl.BreakNode: Formatter.st_Break,
    nl.ContinueNode: Formatter.st_Continue,
    nl.ImportNode: Formatter.st_Import,
    nl.DeleteNode: Formatter.st_Delete,
    nl.DeleteFileNode: Formatter.st_DeleteFile,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render(parsed):
    return Formatter(parsed).format(parsed.tree)


def format_source(source, verify=True):
    """Return the formatted text of `source`.

    Raises NovaError if `source` does not parse, and FormatError if the
    result fails any of the built-in checks (nothing should be written)."""
    original = nova_ast.parse(source)
    result = render(original)
    if not verify:
        return result

    try:
        again = nova_ast.parse(result)
    except NovaError as error:
        raise FormatError("the formatted output no longer parses: " + error.message)
    if nova_ast.shape(again.tree) != nova_ast.shape(original.tree):
        raise FormatError("the formatted output would change what the program means")
    if [c.text for c in again.comments] != [c.text for c in original.comments]:
        raise FormatError("the formatted output would lose or reorder a comment")
    if render(again) != result:
        raise FormatError("the formatter is not idempotent on this file")
    return result


USAGE = "usage: {} [--write | --check] file.nova [more.nova ...]"


def main(argv):
    args = argv[1:]
    mode = "print"
    if args and args[0] in ("--write", "-w"):
        mode, args = "write", args[1:]
    elif args and args[0] == "--check":
        mode, args = "check", args[1:]
    if not args or any(arg.startswith("-") for arg in args):
        print(USAGE.format(argv[0]), file=sys.stderr)
        return 2

    status = 0
    for path in args:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except OSError as problem:
            print("nova-fmt: cannot read {}: {}".format(path, problem), file=sys.stderr)
            status = 2
            continue
        try:
            result = format_source(source)
        except NovaError as error:
            print(path, file=sys.stderr)
            print(error.render(source), file=sys.stderr)
            status = 2
            continue
        except FormatError as problem:
            print("nova-fmt: {}: refusing to format - {}".format(path, problem), file=sys.stderr)
            status = 2
            continue

        if mode == "print":
            sys.stdout.write(result)
        elif mode == "check":
            if result != source:
                print("would reformat {}".format(path))
                status = max(status, 1)
        elif result != source:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(result)
            print("reformatted {}".format(path))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
