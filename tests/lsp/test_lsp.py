#!/usr/bin/env python3
"""
test_lsp.py - drives tools/nova-lsp.py the way an editor does, over real
stdio JSON-RPC, and checks every response.

    python3 tests/lsp/test_lsp.py      (also run by tests/run_all.py, station 9)

VS Code cannot run headless here, so this is the editor: it spawns the
server, frames messages with Content-Length, and asserts on the protocol
itself - capabilities, diagnostics with exact ranges, formatting edits,
definition locations and hover text - plus how the server copes with
mistakes (unknown methods, malformed JSON, a crashing handler, requests
out of order). Expected positions are computed here from the text,
independently of the server's own position code.

It also checks the VS Code extension without VS Code: its manifest, its
grammar (keywords, built-ins and types must equal the language's own -
the drift guard - and sample lines must highlight as expected), and its
client code, run under Node with stand-ins for the vscode modules.
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SERVER = os.path.join(ROOT, "tools", "nova-lsp.py")
EXTENSION = os.path.join(ROOT, "editors", "vscode")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import novalang  # noqa: E402

TIMEOUT = 30


# ---------------------------------------------------------------------------
# A minimal LSP client
# ---------------------------------------------------------------------------

class Client:
    def __init__(self, cwd=ROOT):
        self.process = subprocess.Popen(
            [sys.executable, SERVER], cwd=cwd, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.inbox = queue.Queue()
        self.notifications = []
        self.next_id = 0
        threading.Thread(target=self.pump, daemon=True).start()

    def pump(self):
        stream = self.process.stdout
        while True:
            length = None
            while True:
                header = stream.readline()
                if not header:
                    self.inbox.put(None)
                    return
                header = header.strip()
                if not header:
                    break
                name, _, value = header.partition(b":")
                if name.lower() == b"content-length":
                    length = int(value)
            self.inbox.put(json.loads(stream.read(length).decode("utf-8")))

    def send_raw(self, body):
        self.process.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.process.stdin.flush()

    def send(self, message):
        message["jsonrpc"] = "2.0"
        self.send_raw(json.dumps(message).encode("utf-8"))

    def notify(self, method, params=None):
        self.send({"method": method, "params": params or {}})

    def receive(self):
        message = self.inbox.get(timeout=TIMEOUT)
        if message is not None and "id" not in message:
            self.notifications.append(message)
        return message

    def request(self, method, params=None):
        self.next_id += 1
        wanted = self.next_id
        self.send({"id": wanted, "method": method, "params": params})
        while True:
            message = self.receive()
            if message is None:
                raise RuntimeError("the server closed its output")
            if message.get("id") == wanted:
                return message

    def notification(self, method):
        """The next notification called `method` (earlier ones kept too)."""
        for index, message in enumerate(self.notifications):
            if message["method"] == method:
                return self.notifications.pop(index)
        while True:
            message = self.receive()
            if message is None:
                raise RuntimeError("the server closed its output")
            if message.get("method") == method:
                self.notifications.remove(message)
                return message

    def initialize(self, capabilities=None):
        response = self.request("initialize", {"processId": None, "rootUri": None,
                                               "capabilities": capabilities or {}})
        self.notify("initialized")
        return response

    def open(self, uri, text, version=1):
        self.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri, "languageId": "novalang", "version": version, "text": text}})
        return self.notification("textDocument/publishDiagnostics")["params"]

    def change(self, uri, text, version):
        self.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": version},
                                               "contentChanges": [{"text": text}]})
        return self.notification("textDocument/publishDiagnostics")["params"]

    def close(self):
        try:
            self.request("shutdown")
            self.notify("exit")
            return self.process.wait(timeout=TIMEOUT)
        finally:
            if self.process.poll() is None:
                self.process.kill()


# ---------------------------------------------------------------------------
# Expected positions, computed independently of the server
# ---------------------------------------------------------------------------

BREAK = re.compile(r"\r\n|\r|\n")


def lsp_position(text, offset, utf16=True):
    line = 0
    start = 0
    for match in BREAK.finditer(text):
        if match.start() >= offset:
            break
        line += 1
        start = match.end()
    piece = text[start:offset]
    width = len(piece) + (sum(1 for c in piece if ord(c) > 0xFFFF) if utf16 else 0)
    return {"line": line, "character": width}


def where(text, needle, nth=0, into=0, utf16=True):
    """The LSP position `into` characters into the nth occurrence of needle."""
    index = -1
    for _ in range(nth + 1):
        index = text.index(needle, index + 1)
    return lsp_position(text, index + into, utf16)


def span(text, needle, nth=0, utf16=True):
    index = -1
    for _ in range(nth + 1):
        index = text.index(needle, index + 1)
    return {"start": lsp_position(text, index, utf16),
            "end": lsp_position(text, index + len(needle), utf16)}


def file_uri(path):
    return "file://" + os.path.abspath(path)


# ---------------------------------------------------------------------------
# The tests
# ---------------------------------------------------------------------------

def test_protocol(check):
    client = Client()
    try:
        early = client.request("textDocument/hover", {})
        check(early.get("error", {}).get("code") == -32002,
              "a request before initialize is refused (ServerNotInitialized)", early)
        result = client.initialize()["result"]
        capabilities = result["capabilities"]
        check(result["serverInfo"]["name"] == "nova-lsp", "initialize names the server", result)
        check(capabilities["positionEncoding"] == "utf-16",
              "positions default to UTF-16, as LSP requires", capabilities)
        check(capabilities["textDocumentSync"]["change"] == 1, "documents sync in full", capabilities)
        check(all(capabilities.get(k) for k in ("documentFormattingProvider",
                                                "definitionProvider", "hoverProvider")),
              "formatting, definition and hover are offered", capabilities)

        unknown = client.request("textDocument/completion", {})
        check(unknown.get("error", {}).get("code") == -32601,
              "an unknown request gets MethodNotFound", unknown)
        client.notify("$/setTrace", {"value": "off"})
        client.notify("workspace/didChangeConfiguration", {})
        client.send_raw(b"{ this is not json")
        bad = client.receive()
        check(bad.get("id") is None and bad.get("error", {}).get("code") == -32700,
              "malformed JSON gets ParseError with a null id", bad)
        crash = client.request("textDocument/hover", {"textDocument": {"uri": "file:///nope.nova"}})
        check(crash.get("error", {}).get("code") in (-32600, -32603),
              "a bad request is answered with an error, not a crash", crash)
        broken = client.request("textDocument/hover", None)
        check(broken.get("error", {}).get("code") == -32603,
              "a handler that fails becomes InternalError", broken)
        still = client.request("textDocument/formatting", {"textDocument": {"uri": "file:///x.nova"}})
        check("error" in still and client.process.poll() is None,
              "...and the server keeps serving", still)

        client.request("shutdown")
        after = client.request("textDocument/hover", {})
        check(after.get("error", {}).get("code") == -32600,
              "requests after shutdown are refused", after)
        client.notify("exit")
        check(client.process.wait(timeout=TIMEOUT) == 0, "exit after shutdown ends with 0")
    finally:
        if client.process.poll() is None:
            client.process.kill()

    rude = Client()
    rude.initialize()
    rude.notify("exit")
    check(rude.process.wait(timeout=TIMEOUT) == 1, "exit without shutdown ends with 1")


def test_diagnostics(check):
    client = Client()
    try:
        client.initialize()
        uri = "file:///virtual/demo.nova"
        text = ('let face = "😀😀"; let n: int = 5\n'
                'n = "five"\n'
                'print(face, missing)\n'
                'let unused = 1\n')
        published = client.open(uri, text)
        found = {d["code"]: d for d in published["diagnostics"]}
        check(sorted(found) == ["E001", "T006", "W001"], "the expected findings are published",
              published)
        if "E001" in found:
            d = found["E001"]
            check(d["range"] == span(text, "missing") and d["severity"] == 1
                  and d["source"] == "nova-lint", "E001 underlines exactly the name", d)
        if "T006" in found:
            d = found["T006"]
            check(d["range"] == span(text, '"five"') and d["source"] == "nova-typecheck",
                  "T006 underlines exactly the value", d)
        if "W001" in found:
            d = found["W001"]
            check(d["severity"] == 2 and d.get("tags") == [1] and
                  d["range"] == span(text, "let unused"),
                  "an unused variable is a faded warning", d)
        check(published.get("version") == 1, "diagnostics carry the document version", published)

        emoji = 'let face = "😀😀"; print(face, nowhere)\n'
        published = client.change(uri, emoji, 2)
        ranges = [d["range"] for d in published["diagnostics"] if d.get("code") == "E001"]
        got = ranges[0] if ranges else None
        check(got == span(emoji, "nowhere"),
              "after an emoji, characters count UTF-16 code units", (got, span(emoji, "nowhere")))
        check(got is not None and got["start"]["character"] == 31,
              "(31 here: 29 code points, and each emoji is two units)", got)

        for name, brk in (("\\r\\n", "\r\n"), ("lone \\r", "\r")):
            text = "let a = 1" + brk + "print(b)" + brk
            published = client.change(uri, text, 3)
            ranges = [d["range"] for d in published["diagnostics"] if d.get("code") == "E001"]
            check(ranges == [{"start": {"line": 1, "character": 6},
                              "end": {"line": 1, "character": 7}}],
                  "a {} file puts diagnostics on the editor's line".format(name), published)

        published = client.change(uri, "let fine = 1\nprint(fine)\n", 4)
        check(published["diagnostics"] == [] and published["version"] == 4,
              "fixing the code clears its diagnostics", published)

        published = client.change(uri, "let broken = (1 +\n", 5)
        check(len(published["diagnostics"]) == 1 and published["diagnostics"][0]["source"] ==
              "novalang", "a parse error is one diagnostic", published)

        client.notify("textDocument/didSave", {"textDocument": {"uri": uri}})
        check(client.notification("textDocument/publishDiagnostics")["params"]["uri"] == uri,
              "saving re-publishes diagnostics")
        client.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
        closed = client.notification("textDocument/publishDiagnostics")["params"]
        check(closed["diagnostics"] == [], "closing a document clears its diagnostics", closed)
        client.close()
    finally:
        if client.process.poll() is None:
            client.process.kill()

    wide = Client()
    try:
        result = wide.initialize({"general": {"positionEncodings": ["utf-32", "utf-16"]}})
        check(result["result"]["capabilities"]["positionEncoding"] == "utf-32",
              "a client offering UTF-32 gets it")
        emoji = 'let face = "😀😀"; print(face, nowhere)\n'
        published = wide.open("file:///virtual/wide.nova", emoji)
        got = [d["range"]["start"]["character"] for d in published["diagnostics"]
               if d.get("code") == "E001"]
        check(got == [29], "...and then each emoji counts once (29)", published)
        wide.close()
    finally:
        if wide.process.poll() is None:
            wide.process.kill()


def test_formatting(check):
    client = Client()
    try:
        client.initialize()
        uri = "file:///virtual/messy.nova"
        messy = "let x=1+2\nif x>2 { print(x) }\n"
        client.open(uri, messy)
        edits = client.request("textDocument/formatting", {
            "textDocument": {"uri": uri}, "options": {"tabSize": 2, "insertSpaces": True}})["result"]
        check(edits == [{"range": {"start": {"line": 0, "character": 0},
                                   "end": {"line": 2, "character": 0}},
                         "newText": "let x = 1 + 2\nif x > 2 { print(x) }\n"}],
              "formatting replaces the document with the standard layout", edits)
        client.change(uri, "let x = 1 + 2\n", 2)
        edits = client.request("textDocument/formatting", {"textDocument": {"uri": uri},
                                                           "options": {}})["result"]
        check(edits == [], "an already formatted document needs no edits", edits)
        client.change(uri, "let x = (\n", 3)
        edits = client.request("textDocument/formatting", {"textDocument": {"uri": uri},
                                                           "options": {}})["result"]
        shown = client.notification("window/showMessage")["params"]
        check(edits == [] and "does not parse" in shown["message"],
              "unparseable code is not formatted, and the user is told why", (edits, shown))
        client.close()
    finally:
        if client.process.poll() is None:
            client.process.kill()


def test_navigation(check):
    scratch = tempfile.mkdtemp(prefix="nova-lsp-")
    workspace = os.path.join(scratch, "workspace")
    shutil.copytree(os.path.join(HERE, "workspace"), workspace)
    installed = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "nova-pkg.py"),
                                "install"], cwd=workspace, capture_output=True, text=True)
    check(installed.returncode == 0, "the workspace's package installs", installed.stderr)
    main_path = os.path.join(workspace, "main.nova")
    shapes_path = os.path.join(workspace, "shapes.nova")
    hello_path = os.path.join(workspace, ".nova_modules", "hello", "main.nova")
    text = open(main_path, encoding="utf-8").read()
    shapes = open(shapes_path, encoding="utf-8").read()
    hello = open(hello_path, encoding="utf-8").read()
    client = Client(cwd=workspace)
    try:
        client.initialize()
        uri = file_uri(main_path)
        published = client.open(uri, text)
        check(published["diagnostics"] == [], "the workspace has no diagnostics", published)

        def ask(method, needle, nth=0, into=1):
            return client.request(method, {"textDocument": {"uri": uri},
                                           "position": where(text, needle, nth, into)})["result"]

        def at(path, source, needle, nth=0):
            return {"uri": file_uri(path), "range": span(source, needle, nth)}

        cases = [
            ("a local variable", "size", 2, at(main_path, text, "size", 0)),
            ("a function", "scale(2.5", 0, at(main_path, text, "scale", 0)),
            ("a parameter", "factor * value", 0, at(main_path, text, "factor", 0)),
            ("a loop variable", "print(turn)", 0, None),
            ("a name imported with `with`", "area(size", 0, at(shapes_path, shapes, "area")),
            ("a member of an imported module", "shapes.name", 0, None),
            ("a package's export", "hello.greet", 0, None),
            ("an import's path", '"./shapes.nova" as', 0,
             {"uri": file_uri(shapes_path), "range": {"start": {"line": 0, "character": 0},
                                                      "end": {"line": 0, "character": 0}}}),
            ("the package name in its import", '"hello"', 0,
             {"uri": file_uri(hello_path), "range": {"start": {"line": 0, "character": 0},
                                                     "end": {"line": 0, "character": 0}}}),
        ]
        loop_at = text.index("for turn") + len("for ")
        member_at = at(shapes_path, shapes, "name")
        greet_at = at(hello_path, hello, "greet")
        for label, needle, nth, expected in cases:
            into = 1
            if label == "a loop variable":
                needle, into = "print(turn)", len("print(") + 1
                expected = {"uri": uri, "range": {"start": lsp_position(text, loop_at),
                                                  "end": lsp_position(text, loop_at + 4)}}
            elif label == "a member of an imported module":
                into = len("shapes.") + 1
                expected = member_at
            elif label == "a package's export":
                into = len("hello.") + 1
                expected = greet_at
            got = ask("textDocument/definition", needle, nth, into)
            check(got == expected, "definition of " + label, (got, expected))
        check(ask("textDocument/definition", 'upper("done")') is None,
              "a built-in has no definition to jump to")
        check(ask("textDocument/definition", "# The workspace", 0, 3) is None,
              "nothing to jump to from a comment")

        def hover(needle, nth=0, into=1):
            result = ask("textDocument/hover", needle, nth, into)
            return result["contents"]["value"] if result else None

        hovers = [
            ("a function's signature", "scale(2.5", 0, 1, "def scale(factor: float, value) -> float"),
            ("a typed variable", "size)", 0, 1, "size: int"),
            ("an unannotated variable", "label, upper", 0, 1, "label: any"),
            ("a parameter", "factor * value", 0, 1, "(parameter) factor: float"),
            ("an unannotated parameter", "* value", 0, 3, "(parameter) value: any"),
            ("an imported function", "area(size", 0, 1,
             "def area(width: float, height: float) -> float"),
            ("a module member", "shapes.name", 0, len("shapes.") + 1, "def name(sides: int) -> string"),
            ("a built-in", 'upper("done")', 0, 1, "(built-in) upper(string) -> string"),
            ("a predefined global", "PI)", 0, 1, "(predefined) PI: float"),
            ("a loop variable", "print(turn)", 0, len("print(") + 1, "(loop variable) turn: any"),
        ]
        for label, needle, nth, into, expected in hovers:
            got = hover(needle, nth, into)
            check(got is not None and got.startswith("```novalang\n" + expected + "\n```"),
                  "hover over " + label, got)
        check(hover("print(area", 0, 0) is not None and hover("\n\nlet size", 0, 0) is None,
              "hover is null where there is no name")
        client.close()
    finally:
        if client.process.poll() is None:
            client.process.kill()
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# The VS Code extension
# ---------------------------------------------------------------------------

def alternation(pattern):
    """The words of a \\b(a|b|c)\\b pattern."""
    match = re.search(r"\(([A-Za-z0-9_|]+)\)", pattern)
    return set(match.group(1).split("|")) if match else set()


class Grammar:
    """Just enough of TextMate to tokenize one line: match and begin/end
    rules, includes, earliest match wins and ties go to the earlier rule.
    Python's `re` stands in for Oniguruma, which these patterns allow."""

    def __init__(self, data):
        self.data = data

    def rules(self, patterns):
        for rule in patterns:
            if "include" in rule:
                name = rule["include"]
                target = self.data if name == "$self" else self.data["repository"][name[1:]]
                yield from self.rules(target.get("patterns", [target]) if "patterns" in target
                                      and "match" not in target and "begin" not in target
                                      else [target])
            else:
                yield rule

    def scopes(self, line):
        """[(text, scope)] for one line."""
        found = []
        self.run(line, 0, len(line), list(self.rules(self.data["patterns"])), None, found)
        return found

    def capture(self, match, captures, found):
        for group, capture in captures.items():
            if match.group(int(group)):
                found.append((match.group(int(group)), capture["name"]))

    def run(self, line, position, stop, patterns, end_pattern, found, end_captures=None):
        while position < stop:
            best = None
            if end_pattern is not None:
                end = re.compile(end_pattern).search(line, position)
                if end:
                    best = (end.start(), -1, end, None)
            for order, rule in enumerate(patterns):
                pattern = rule.get("match") or rule.get("begin")
                match = re.compile(pattern).search(line, position)
                if match and (best is None or match.start() < best[0]):
                    best = (match.start(), order, match, rule)
            if best is None:
                return stop
            start, _, match, rule = best
            if rule is None:
                self.capture(match, end_captures or {}, found)
                return match.end()
            if "match" in rule:
                if "name" in rule:
                    found.append((match.group(0), rule["name"]))
                self.capture(match, rule.get("captures", {}), found)
                position = max(match.end(), position + 1)
            else:
                self.capture(match, rule.get("beginCaptures", {}), found)
                inner = list(self.rules(rule.get("patterns", [])))
                after = self.run(line, match.end(), stop, inner, rule["end"], found,
                                 rule.get("endCaptures", {}))
                if "name" in rule:
                    found.append((line[match.start():after], rule["name"]))
                position = max(after, position + 1)
        return stop


GRAMMAR_SAMPLES = [
    ('# a comment with "quotes"', "# a comment with \"quotes\"", "comment.line.number-sign.novalang"),
    ('let s = "not # a comment"', '"not # a comment"', "string.quoted.double.novalang"),
    ("let t = 'single'", "'single'", "string.quoted.single.novalang"),
    ('print(f"{name} is {age}")', "{", "punctuation.section.interpolation.begin.novalang"),
    ('print(f"{name} is {age}")', "name", None),     # a hole is code, not string text
    ('print(f"{x} {{literal}}")', "{{", "constant.character.escape.novalang"),
    ('print("tab\\there")', "\\t", "constant.character.escape.novalang"),
    ("let n = 3.25 + .5", "3.25", "constant.numeric.novalang"),
    ("let n = 3.25 + .5", ".5", "constant.numeric.novalang"),
    ("def add(a: int) -> int {", "add", "entity.name.function.novalang"),
    ("def add(a: int) -> int {", "int", "support.type.novalang"),
    ("for i = 0 to 9 step 2 {", "step", "keyword.control.novalang"),
    ("if a and not b {", "not", "keyword.operator.logical.novalang"),
    ('import "m.nova" with f', "with", "keyword.control.import.novalang"),
    ("let ok = true", "true", "constant.language.boolean.novalang"),
    ("print(len(xs))", "len", "support.function.builtin.novalang"),
    ("let r = PI * 2", "PI", "support.constant.novalang"),
    ("let length = 3", "length", None),          # a name that starts like a built-in
    ("let iffy = 1", "iffy", None),              # ... and like a keyword
]


def test_extension(check):
    manifest = json.load(open(os.path.join(EXTENSION, "package.json")))
    check(os.path.isfile(os.path.join(EXTENSION, manifest["main"])), "package.json's main exists")
    language = manifest["contributes"]["languages"][0]
    check(language["id"] == "novalang" and ".nova" in language["extensions"],
          "the extension claims .nova files")
    check(os.path.isfile(os.path.join(EXTENSION, language["configuration"])),
          "its language configuration exists")
    json.load(open(os.path.join(EXTENSION, language["configuration"])))
    entry = manifest["contributes"]["grammars"][0]
    grammar = json.load(open(os.path.join(EXTENSION, entry["path"])))
    check(grammar["scopeName"] == entry["scopeName"] == "source.novalang",
          "the grammar's scope name matches the manifest")

    # Drift guard: the grammar knows exactly the language's words.
    repository = grammar["repository"]
    keywords = set()
    for rule in repository["keywords"]["patterns"]:
        keywords |= alternation(rule["match"])
    check(keywords == set(novalang.KEYWORDS), "grammar keywords == novalang.KEYWORDS",
          sorted(keywords ^ set(novalang.KEYWORDS)))
    builtins = alternation(repository["builtins"]["match"])
    check(builtins == set(novalang.BUILTINS), "grammar built-ins == novalang.BUILTINS",
          sorted(builtins ^ set(novalang.BUILTINS)))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "nova_typecheck", os.path.join(ROOT, "tools", "nova-typecheck.py"))
    typecheck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(typecheck)
    types = alternation(repository["type-annotation"]["match"].split("\\s*", 1)[1])
    check(types == set(typecheck.ANNOTATIONS), "grammar types == the type checker's",
          sorted(types ^ set(typecheck.ANNOTATIONS)))
    predefined = alternation(repository["predefined"]["match"])
    check(predefined == set(novalang.Interpreter().globals.values),
          "grammar predefined names == the interpreter's", sorted(predefined))

    engine = Grammar(grammar)
    for line, piece, scope in GRAMMAR_SAMPLES:
        scopes = engine.scopes(line)
        given = [s for text, s in scopes if text == piece]
        ok = (not given) if scope is None else scope in given
        check(ok, "highlighting: {!r} in {!r} is {}".format(piece, line, scope or "plain"), scopes)

    node = shutil.which("node")
    if node is None:
        check(False, "node is needed to test editors/vscode/extension.js")
        return
    done = subprocess.run([node, os.path.join(HERE, "extension_test.js"), ROOT],
                          capture_output=True, text=True, timeout=TIMEOUT)
    for row in done.stdout.splitlines():
        status, _, label = row.partition(" ")
        if status in ("ok", "FAIL"):
            check(status == "ok", "extension.js: " + label, done.stderr)
    check(done.returncode == 0 and "ok " in done.stdout, "extension.js runs under node",
          done.stdout + done.stderr)


def run(check):
    for test in (test_protocol, test_diagnostics, test_formatting, test_navigation,
                 test_extension):
        try:
            test(check)
        except Exception as problem:  # noqa: BLE001 - report, then carry on
            check(False, "{} raised {}: {}".format(test.__name__, type(problem).__name__, problem))


def main():
    failures = []

    def check(ok, label, detail=None):
        print("[{}] {}".format("ok" if ok else "FAILED", label))
        if not ok:
            failures.append(label)
            if detail is not None:
                print("        " + repr(detail)[:600])
    run(check)
    print()
    print("All LSP tests passed." if not failures else "{} LSP test(s) failed.".format(len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
