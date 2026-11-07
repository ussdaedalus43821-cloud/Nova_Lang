"""Regression tests for formatter refusal and malformed package and LSP input."""

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class FormatterRefusalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("nova_fmt", ROOT / "tools/nova-fmt.py")
        cls.formatter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.formatter)

    def test_refusal_preserves_file_and_continues_batch(self):
        original = "# keep\nlet count=1\n"
        cases = (
            (("let =\n",), "no longer parses"),
            (("# keep\nlet count = 2\n",), "change what the program means"),
            (("let count = 1\n",), "lose or reorder a comment"),
            (("# keep\nlet count = 1\n", original), "not idempotent"),
        )
        for mode in ("--write", "--check", None):
            for rendered, diagnostic in cases:
                with self.subTest(mode=mode, diagnostic=diagnostic), tempfile.TemporaryDirectory() as folder:
                    refused = Path(folder) / "refused.nova"
                    next_file = Path(folder) / "next.nova"
                    refused.write_bytes(original.encode())
                    next_file.write_bytes(b"let next_value=2\n")
                    outputs = iter(rendered)
                    real_render = self.formatter.render

                    def render(parsed):
                        # Only the first file receives a simulated renderer regression.
                        if any(comment.text == "# keep" for comment in parsed.comments):
                            return next(outputs)
                        return real_render(parsed)

                    args = ["nova-fmt.py"] + ([mode] if mode else []) + [str(refused), str(next_file)]
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with patch.object(self.formatter, "render", render), redirect_stdout(stdout), redirect_stderr(stderr):
                        self.assertEqual(self.formatter.main(args), 2)
                    self.assertEqual(refused.read_bytes(), original.encode())
                    self.assertIn(f"{refused}: refusing to format", stderr.getvalue())
                    self.assertIn(diagnostic, stderr.getvalue())
                    if mode == "--write":
                        self.assertIn(f"reformatted {next_file}", stdout.getvalue())
                        self.assertEqual(next_file.read_bytes(), b"let next_value = 2\n")
                    elif mode == "--check":
                        self.assertIn(f"would reformat {next_file}", stdout.getvalue())
                        self.assertEqual(next_file.read_bytes(), b"let next_value=2\n")
                    else:
                        self.assertEqual(stdout.getvalue(), "let next_value = 2\n")
                        self.assertEqual(next_file.read_bytes(), b"let next_value=2\n")


class PackageInputTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.project = Path(folder.name)
        self.manifest = self.project / "nova.json"
        self.lock = self.project / "nova.lock"
        self.manifest.write_text('{"name":"fixture","version":"1.0.0"}', encoding="utf-8")
        modules = self.project / ".nova_modules"
        modules.mkdir()
        self.marker = modules / ".installed.lock"
        self.marker.write_bytes(b"previous install")
        (modules / "fixture-lib").mkdir()
        (modules / "fixture-lib" / "main.nova").write_bytes(b"export let answer = 42\n")

    def assert_refused(self, command, diagnostic):
        before = {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        done = subprocess.run(
            [sys.executable, str(ROOT / "tools/nova-pkg.py"), *command],
            cwd=self.project, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("nova-pkg: error:", done.stderr)
        self.assertIn(diagnostic, done.stderr)
        self.assertNotIn("Traceback", done.stderr)
        self.assertEqual(before, {p: p.read_bytes() for p in self.project.rglob("*") if p.is_file()})

    def test_malformed_manifests(self):
        for data, diagnostic in (
            (b"{", "not valid JSON"),
            (b"[]", "must be a JSON object"),
            (b'{"name":"Bad","version":"1.0.0"}', "lowercase package name"),
            (b'{"name":"fixture","version":"1.0.0","dependencies":[]}', "dependencies"),
        ):
            with self.subTest(data=data):
                self.manifest.write_bytes(data)
                self.assert_refused(("install",), diagnostic)

    def test_invalid_json_or_encoding_in_lock(self):
        for data, diagnostic in ((b"{", "not valid JSON"), (b"\xff", "cannot read")):
            for command in (("install", "--frozen"), ("verify",)):
                with self.subTest(data=data, command=command):
                    self.lock.write_bytes(data)
                    self.assert_refused(command, diagnostic)

    def test_lock_structure(self):
        entry = {"version": "1.0.0", "source": {"path": "../lib"}, "integrity": "sha256:test"}
        for packages, diagnostic in (
            (None, "packages"),
            ({"fixture-lib": None}, "fixture-lib"),
            ({"fixture-lib": dict(entry, source=None)}, "source"),
            ({"fixture-lib": dict(entry, source={"git": "unused"})}, "source"),
            ({"../fixture-lib": entry}, "package name"),
        ):
            for command in (("install", "--frozen"), ("verify",)):
                with self.subTest(packages=packages, command=command):
                    self.lock.write_text(json.dumps({
                        "lockfile_version": 1, "requires": {}, "packages": packages,
                    }), encoding="utf-8")
                    self.assert_refused(command, diagnostic)


def frame(body):
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


class LspInputTests(unittest.TestCase):
    def session(self, data, status):
        result = subprocess.run([sys.executable, str(ROOT / "tools/nova-lsp.py")],
                                input=data, cwd=ROOT, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, status, result.stderr)
        self.assertEqual(result.stderr, b"")
        responses = []
        output = io.BytesIO(result.stdout)
        while True:
            header = output.readline()
            if not header:
                return responses
            self.assertTrue(header.startswith(b"Content-Length: "))
            length = int(header.partition(b":")[2])
            self.assertEqual(output.readline(), b"\r\n")
            body = output.read(length)
            self.assertEqual(len(body), length)
            responses.append(json.loads(body))

    def test_bad_frames_followed_by_valid_requests(self):
        tail = b"".join(frame(json.dumps(message).encode()) for message in (
            {"jsonrpc": "2.0", "method": "initialize", "id": 1,
             "params": {"initializationOptions": {"padding": "x" * 70000}}},
            {"jsonrpc": "2.0", "method": "shutdown", "id": 2},
            {"jsonrpc": "2.0", "method": "exit"},
        ))
        bad_frames = (
            b"Content-Type: application/json\r\n\r\n",
            b"Content-Length: bogus\r\n\r\n",
            b"Content-Length: -1\r\n\r\n",
            b"Content-Length: 999999999999999999999999999\r\n\r\n",
            frame(b"\xff"),
        )
        for bad in bad_frames:
            with self.subTest(bad=bad):
                error, initialized, shutdown = self.session(bad + tail, 0)
                self.assertIsNone(error["id"])
                self.assertEqual(error["error"]["code"], -32700)
                self.assertEqual(initialized["id"], 1)
                self.assertIn("capabilities", initialized["result"])
                self.assertEqual(shutdown["id"], 2)
                self.assertIsNone(shutdown["result"])

    def test_eof_during_header_or_body(self):
        for data in (b"Content-Length: 10\r\n", b"Content-Length: 10\r\n\r\n{}",
                     b"Content-Length: 1000000000000\r\n\r\n{}"):
            with self.subTest(data=data):
                self.assertEqual(self.session(data, 1), [])
