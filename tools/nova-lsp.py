#!/usr/bin/env python3
"""
nova-lsp - the NovaLang language server (Language Server Protocol, stdio).

    python3 tools/nova-lsp.py

An editor starts this and talks JSON-RPC to it over stdin/stdout. It
serves, for .nova files:

    diagnostics   nova-lint and nova-typecheck findings, and parse errors,
                  published on open, change and save
    formatting    the nova-fmt layout, as one edit
    definition    where the name under the cursor is defined - in this
                  file, in an imported file, or a package
    hover         the type of the name under the cursor

Standard library only. Everything it reports comes from the same code the
command-line tools run - nothing about the language is re-implemented here.

Design notes:
  - One thread, one message at a time. Requests always get exactly one
    response; notifications never get one. An unknown request is answered
    with MethodNotFound; a failure inside a handler becomes an
    InternalError response and the server carries on. stdout carries only
    protocol messages; anything else goes to stderr.
  - Documents are synced whole (TextDocumentSyncKind.Full): a few tens of
    milliseconds to re-analyse even novalang.nova itself, well under what
    a person notices. The open document is analysed from memory; the files
    it imports are read from disk.
  - Positions. NovaLang counts offsets in code points from the start of the
    file; LSP counts (line, character) with `character` in UTF-16 code
    units unless the client offers UTF-32. LineMap converts both ways,
    splitting lines exactly where the lexer does ("\\n", "\\r\\n", lone "\\r").
"""

import bisect
import importlib.util
import json
import os
import sys
import traceback
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import nova_ast  # noqa: E402
from nova_ast import NovaError, nl  # noqa: E402


def load(filename):
    spec = importlib.util.spec_from_file_location(
        filename[:-3].replace("-", "_"), os.path.join(HERE, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lint = load("nova-lint.py")
typecheck = load("nova-typecheck.py")
fmt = load("nova-fmt.py")

VERSION = "0.3.0"

# JSON-RPC and LSP error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603
SERVER_NOT_INITIALIZED = -32002

ERROR, WARNING = 1, 2                   # DiagnosticSeverity
UNNECESSARY = 1                         # DiagnosticTag
FULL_SYNC = 1                           # TextDocumentSyncKind


def log(*parts):
    print("nova-lsp:", *parts, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

class LineMap:
    """Converts between NovaLang offsets (code points from the start) and
    LSP positions (0-based line, and character in the negotiated unit)."""

    def __init__(self, text, encoding="utf-16"):
        self.text = text
        self.encoding = encoding
        spans = nl.line_spans(text)
        self.starts = [start for start, _ in spans]
        self.ends = [end for _, end in spans]

    def units(self, piece):
        if self.encoding == "utf-32":
            return len(piece)
        if self.encoding == "utf-8":
            return len(piece.encode("utf-8"))
        return len(piece) + sum(1 for char in piece if ord(char) > 0xFFFF)

    def position(self, offset):
        offset = max(0, min(offset, len(self.text)))
        line = bisect.bisect_right(self.starts, offset) - 1
        start, end = self.starts[line], self.ends[line]
        return {"line": line, "character": self.units(self.text[start:min(offset, end)])}

    def offset(self, position):
        line = position.get("line", 0)
        if line < 0:
            return 0
        if line >= len(self.starts):
            return len(self.text)
        start, end = self.starts[line], self.ends[line]
        wanted = max(0, position.get("character", 0))
        counted = 0
        for index in range(start, end):
            width = self.units(self.text[index])
            if counted + width > wanted:
                return index        # never inside a character's code units
            counted += width
        return end                  # past the line's end means its end

    def range(self, start, end):
        return {"start": self.position(start), "end": self.position(end)}

    def whole(self):
        return self.range(0, len(self.text))


# ---------------------------------------------------------------------------
# URIs
# ---------------------------------------------------------------------------

def uri_to_path(uri):
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme != "file":
        return None
    return os.path.normpath(urllib.request.url2pathname(urllib.parse.unquote(parsed.path)))


def path_to_uri(path):
    return "file://" + urllib.request.pathname2url(os.path.abspath(path))


# ---------------------------------------------------------------------------
# Analysis: everything known about one version of one document
# ---------------------------------------------------------------------------

class Target:
    """What a name in the source refers to, for definition and hover."""

    def __init__(self, kind, name, binding=None, module=None, kind_type=None):
        self.kind = kind            # binding | builtin | predefined | member | file
        self.name = name
        self.binding = binding
        self.module = module        # typecheck.Module, for member / file / imports
        self.type = kind_type


class IndexingChecker(typecheck.Checker):
    """The type checker, also noting every name it resolves - where the name
    is written, and what it means. Nothing about checking changes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.references = []        # (start, end, Target)
        self.definitions = {}       # id(binding) -> (start, end) of its name
        self.imports = {}           # id(binding) -> (Module, exported name or None)

    def note(self, start, end, target):
        self.references.append((start, end, target))

    def bind(self, name, position, kind, scope=None):
        binding = super().bind(name, position, kind, scope)
        span = self.parsed.name_after(position, name)
        if span is not None and kind != "import":
            self.definitions[id(binding)] = span
            self.note(span[0], span[1], Target("binding", name, binding))
        return binding

    def visit_VarNode(self, node):
        binding = self.scope.lookup(node.name)
        result = super().visit_VarNode(node)
        end = node.position + len(node.name)
        if binding is not None:
            self.note(node.position, end, Target("binding", node.name, binding))
        elif node.name in nl.BUILTINS:
            self.note(node.position, end, Target("builtin", node.name, kind_type=result))
        else:
            self.note(node.position, end, Target("predefined", node.name, kind_type=result))
        return result

    def visit_MemberNode(self, node):
        result = super().visit_MemberNode(node)
        if isinstance(node.target, nl.VarNode):
            binding = self.scope.lookup(node.target.name)
            module = self.imports.get(id(binding), (None, None))[0] if binding else None
            if module is not None:
                start = node.position + 1
                self.note(start, start + len(node.name),
                          Target("member", node.name, module=module, kind_type=result))
        return result

    def visit_ImportNode(self, node):
        bindings = super().visit_ImportNode(node)
        module = self.program.module(node.path, self.base_dir)
        path_token = self.string_after(node.position)
        if module is not None and path_token is not None:
            self.note(path_token.position, path_token.end, Target("file", node.path, module=module))
        for binding in bindings:
            exported = binding.name if node.names is not None else None
            self.imports[id(binding)] = (module, exported)
            span = self.parsed.name_after(node.position, binding.name)
            if span is None or node.names is None and node.alias is None:
                span = (path_token.position, path_token.end) if path_token else None
            if span is not None:
                self.definitions[id(binding)] = span
                if node.names is not None or node.alias is not None:
                    self.note(span[0], span[1], Target("binding", binding.name, binding))
        return bindings

    def string_after(self, position):
        index = bisect.bisect_left(self.parsed.starts, position)
        for token in self.parsed.tokens[index:]:
            if token.type == nl.TT_STRING:
                return token
            if token.type == nl.TT_NEWLINE:
                return None
        return None


class Analysis:
    def __init__(self, uri, text, version):
        self.uri = uri
        self.text = text
        self.version = version
        self.path = uri_to_path(uri)
        self.diagnostics = []
        self.checker = None
        self.program = None
        self.parse_error = None
        try:
            self.parsed = nova_ast.parse(text)
        except NovaError as error:
            self.parsed = None
            self.parse_error = error
            return
        # Parse once: parsing is most of the cost, and both tools accept it.
        self.lint_findings = lint.Linter(self.parsed).run()
        program = typecheck.Program()
        module = program.check(text, self.path, os.path.dirname(self.path) if self.path else None,
                               checker_class=IndexingChecker, parsed=self.parsed)
        self.program = program
        self.module = module
        self.checker = module.checker
        self.type_findings = module.findings

    def target_at(self, offset):
        if self.checker is None:
            return None, None
        best = None
        for start, end, target in self.checker.references:
            if start <= offset <= end and (best is None or end - start < best[1] - best[0]):
                best = (start, end, target)
        if best is None:
            return None, None
        return best[2], (best[0], best[1])


# ---------------------------------------------------------------------------
# Hover text
# ---------------------------------------------------------------------------

def type_name(kind):
    return "any" if kind is None else kind.name


def signature_text(name, kind):
    if kind.params is None:
        return "{}(...) -> {}".format(name, type_name(kind.ret) if kind.ret is not typecheck.SAME
                                      else "number")
    names = kind.names or [None] * len(kind.params)
    parts = []
    for index, (param, param_type) in enumerate(zip(names, kind.params)):
        if param is None:
            parts.append(param_type.name)
        elif param_type is typecheck.ANY and kind.names is not None:
            parts.append(param)
        else:
            parts.append("{}: {}".format(param, param_type.name))
        if index >= kind.required:
            parts[-1] += "?"
    ret = kind.ret
    if ret is typecheck.SAME:
        ret_text = "the type of its argument"
    else:
        ret_text = ret.name
    if kind.names is not None:
        head = "def {}({})".format(name, ", ".join(parts))
        return head if ret is typecheck.ANY else head + " -> " + ret_text
    return "{}({}) -> {}".format(name, ", ".join(parts), ret_text)


def describe_type(name, kind, label=None):
    if isinstance(kind, typecheck.FunctionType):
        return signature_text(name, kind)
    if isinstance(kind, typecheck.ModuleType):
        return "module {}".format(name)
    text = "{}: {}".format(name, type_name(kind))
    return "({}) {}".format(label, text) if label else text


LABELS = {"param": "parameter", "loop": "loop variable", "catch": "caught error"}


def hover_text(analysis, target):
    if target.kind == "binding":
        binding = target.binding
        if binding.kind == "import":
            module, exported = analysis.checker.imports.get(id(binding), (None, None))
            if exported is not None and module is not None:
                return describe_type(binding.name, module.exports.get(exported)) + \
                    "\n\nimported from " + os.path.basename(module.path)
            if module is not None:
                return "module {}\n\n{}".format(binding.name, module.path)
            return "module {} (not found)".format(binding.name)
        return describe_type(binding.name, binding.declared, LABELS.get(binding.kind))
    if target.kind == "builtin":
        return "(built-in) " + describe_type(target.name, target.type)
    if target.kind == "predefined":
        return "(predefined) " + describe_type(target.name, target.type)
    if target.kind == "member":
        return describe_type(target.name, target.type) + \
            "\n\nexported by " + os.path.basename(target.module.path)
    if target.kind == "file":
        return target.module.path
    return None


def markdown(text):
    head, _, rest = text.partition("\n\n")
    value = "```novalang\n" + head + "\n```"
    if rest:
        value += "\n\n" + rest
    return {"kind": "markdown", "value": value}


# ---------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------

class ResponseError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Server:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.initialized = False
        self.shutting_down = False
        self.encoding = "utf-16"
        self.documents = {}             # uri -> Analysis of its latest text
        self.requests = {
            "initialize": self.initialize,
            "shutdown": self.shutdown,
            "textDocument/formatting": self.formatting,
            "textDocument/definition": self.definition,
            "textDocument/hover": self.hover,
        }
        self.notifications = {
            "initialized": lambda params: None,
            "exit": self.exit,
            "textDocument/didOpen": self.did_open,
            "textDocument/didChange": self.did_change,
            "textDocument/didSave": self.did_save,
            "textDocument/didClose": self.did_close,
        }
        self.exit_code = None

    # -- transport ------------------------------------------------------------

    def read_message(self):
        """The next message, None at end of input, or a ResponseError for
        one that cannot be decoded."""
        length = None
        while True:
            header = self.reader.readline()
            if not header:
                return None
            header = header.decode("ascii", "replace").strip()
            if not header:
                break
            name, _, value = header.partition(":")
            if name.strip().lower() == "content-length":
                try:
                    length = int(value.strip())
                except ValueError:
                    length = None
        if length is None:
            return ResponseError(PARSE_ERROR, "a message arrived with no Content-Length")
        if not 0 <= length <= sys.maxsize:
            return ResponseError(PARSE_ERROR, "a message arrived with an invalid Content-Length")
        # Read incrementally so a truncated message cannot force allocation
        # of the entire declared body before any bytes arrive.
        body = bytearray()
        while len(body) < length:
            chunk = self.reader.read(min(length - len(body), 65536))
            if not chunk:
                return None
            body.extend(chunk)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as problem:
            return ResponseError(PARSE_ERROR, "the message is not valid JSON: {}".format(problem))

    def send(self, message):
        message["jsonrpc"] = "2.0"
        body = json.dumps(message, ensure_ascii=False).encode("utf-8")
        self.writer.write(b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n")
        self.writer.write(body)
        self.writer.flush()

    def notify(self, method, params):
        self.send({"method": method, "params": params})

    # -- the loop ---------------------------------------------------------------

    def serve(self):
        while self.exit_code is None:
            message = self.read_message()
            if message is None:
                return 0 if self.shutting_down else 1
            if isinstance(message, ResponseError):
                self.send({"id": None, "error": {"code": message.code, "message": message.message}})
                continue
            self.dispatch(message)
        return self.exit_code

    def dispatch(self, message):
        if not isinstance(message, dict):
            self.send({"id": None, "error": {"code": INVALID_REQUEST,
                                              "message": "a message must be a JSON object"}})
            return
        method = message.get("method")
        params = message.get("params") or {}
        if "id" in message and method is not None:
            self.answer(message["id"], method, params)
        elif method is not None:
            handler = self.notifications.get(method)
            if handler is None:
                return              # unknown notifications, $/ ones included, are ignored
            if not self.initialized and method != "exit":
                return
            try:
                handler(params)
            except Exception:  # noqa: BLE001 - a bug must not take the editor's server down
                log("failed handling", method, "\n" + traceback.format_exc())
        # responses to requests the server sent are not expected; ignore them

    def answer(self, request_id, method, params):
        try:
            if method != "initialize" and not self.initialized:
                raise ResponseError(SERVER_NOT_INITIALIZED, "initialize has not been called")
            if self.shutting_down:
                raise ResponseError(INVALID_REQUEST, "the server is shutting down")
            handler = self.requests.get(method)
            if handler is None:
                raise ResponseError(METHOD_NOT_FOUND, "nova-lsp does not handle " + method)
            self.send({"id": request_id, "result": handler(params)})
        except ResponseError as error:
            self.send({"id": request_id, "error": {"code": error.code, "message": error.message}})
        except Exception as problem:  # noqa: BLE001
            log("failed handling", method, "\n" + traceback.format_exc())
            self.send({"id": request_id, "error": {
                "code": INTERNAL_ERROR, "message": "{}: {}".format(type(problem).__name__, problem)}})

    # -- lifecycle --------------------------------------------------------------

    def initialize(self, params):
        offered = (params.get("capabilities", {}).get("general", {})
                   .get("positionEncodings") or [])
        self.encoding = "utf-32" if "utf-32" in offered else "utf-16"
        self.initialized = True
        return {
            "capabilities": {
                "positionEncoding": self.encoding,
                "textDocumentSync": {"openClose": True, "change": FULL_SYNC,
                                     "save": {"includeText": False}},
                "documentFormattingProvider": True,
                "definitionProvider": True,
                "hoverProvider": True,
            },
            "serverInfo": {"name": "nova-lsp", "version": VERSION},
        }

    def shutdown(self, params):
        self.shutting_down = True
        return None

    def exit(self, params):
        self.exit_code = 0 if self.shutting_down else 1

    # -- documents --------------------------------------------------------------

    def did_open(self, params):
        document = params["textDocument"]
        self.update(document["uri"], document["text"], document.get("version"))

    def did_change(self, params):
        uri = params["textDocument"]["uri"]
        current = self.documents.get(uri)
        text = current.text if current else ""
        for change in params.get("contentChanges", []):
            if "range" in change:       # incremental, though Full was asked for
                lines = LineMap(text, self.encoding)
                start = lines.offset(change["range"]["start"])
                end = lines.offset(change["range"]["end"])
                text = text[:start] + change["text"] + text[end:]
            else:
                text = change["text"]
        self.update(uri, text, params["textDocument"].get("version"))

    def did_save(self, params):
        # Another file on disk may have changed what an open one imports.
        for uri, analysis in list(self.documents.items()):
            self.update(uri, analysis.text, analysis.version)

    def did_close(self, params):
        uri = params["textDocument"]["uri"]
        self.documents.pop(uri, None)
        self.notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})

    def update(self, uri, text, version):
        analysis = Analysis(uri, text, version)
        self.documents[uri] = analysis
        self.notify("textDocument/publishDiagnostics", {
            "uri": uri, "version": version, "diagnostics": self.diagnostics(analysis)})

    def analysis(self, params):
        uri = params["textDocument"]["uri"]
        analysis = self.documents.get(uri)
        if analysis is None:
            raise ResponseError(INVALID_REQUEST, "{} is not open".format(uri))
        return analysis

    # -- features -----------------------------------------------------------------

    def span(self, analysis, start, end):
        """A diagnostic's range: its own end if known, else to the end of
        the token it starts on, else one character."""
        if end is None or end <= start:
            end = start + 1
            if analysis.parsed is not None:
                index = bisect.bisect_right(analysis.parsed.starts, start) - 1
                if index >= 0 and analysis.parsed.tokens[index].position == start:
                    end = max(end, analysis.parsed.tokens[index].end)
        return LineMap(analysis.text, self.encoding).range(start, min(end, len(analysis.text)))

    def diagnostics(self, analysis):
        found = []
        if analysis.parse_error is not None:
            error = analysis.parse_error
            position = error.position if error.position is not None else 0
            found.append({"range": self.span(analysis, position, None), "severity": ERROR,
                          "source": "novalang", "message": error.message})
            return found
        for finding in analysis.lint_findings:
            diagnostic = {
                "range": self.span(analysis, finding.position or 0, finding.end),
                "severity": ERROR if finding.code.startswith("E") else WARNING,
                "code": finding.code, "source": "nova-lint", "message": finding.message,
            }
            if finding.code in ("W001", "W002"):
                diagnostic["tags"] = [UNNECESSARY]
            found.append(diagnostic)
        for finding in analysis.type_findings:
            found.append({
                "range": self.span(analysis, finding.position or 0, finding.end),
                "severity": ERROR, "code": finding.code, "source": "nova-typecheck",
                "message": finding.message,
            })
        return found

    def formatting(self, params):
        analysis = self.analysis(params)
        try:
            result = fmt.format_source(analysis.text)
        except NovaError as error:
            self.notify("window/showMessage", {
                "type": WARNING, "message": "nova-fmt: this file does not parse yet: " + error.message})
            return []
        except fmt.FormatError as problem:
            self.notify("window/showMessage", {
                "type": WARNING, "message": "nova-fmt refused to format: {}".format(problem)})
            return []
        if result == analysis.text:
            return []
        return [{"range": LineMap(analysis.text, self.encoding).whole(), "newText": result}]

    def at_cursor(self, params):
        analysis = self.analysis(params)
        offset = LineMap(analysis.text, self.encoding).offset(params["position"])
        target, span = analysis.target_at(offset)
        return analysis, target, span

    def location(self, path, text, start, end, uri=None):
        return {"uri": uri or path_to_uri(path),
                "range": LineMap(text, self.encoding).range(start, end)}

    def definition(self, params):
        analysis, target, _ = self.at_cursor(params)
        if target is None or target.kind in ("builtin", "predefined"):
            return None
        if target.kind == "file":
            return self.location(target.module.path, target.module.source, 0, 0)
        if target.kind == "member":
            return self.exported(target.module, target.name)
        binding = target.binding
        if binding.kind == "import":
            module, exported = analysis.checker.imports.get(id(binding), (None, None))
            if module is None:
                return None
            if exported is not None:
                return self.exported(module, exported)
            return self.location(module.path, module.source, 0, 0)
        span = analysis.checker.definitions.get(id(binding))
        if span is None:
            return None
        # The document's own URI: it may be an unsaved buffer with no path.
        return self.location(None, analysis.text, span[0], span[1], uri=analysis.uri)

    def exported(self, module, name):
        binding = module.scope.names.get(name)
        if binding is None:
            return self.location(module.path, module.source, 0, 0)
        span = module.parsed.name_after(binding.position, name) or (binding.position,
                                                                    binding.position)
        return self.location(module.path, module.source, span[0], span[1])

    def hover(self, params):
        analysis, target, span = self.at_cursor(params)
        if target is None:
            return None
        text = hover_text(analysis, target)
        if text is None:
            return None
        return {"contents": markdown(text),
                "range": LineMap(analysis.text, self.encoding).range(span[0], span[1])}


def main():
    server = Server(sys.stdin.buffer, sys.stdout.buffer)
    return server.serve()


if __name__ == "__main__":
    sys.exit(main())
