// extension_test.js - runs editors/vscode/extension.js under plain Node,
// with stand-ins for the `vscode` and `vscode-languageclient` modules, and
// checks it launches the language server the right way. Called by
// tests/lsp/test_lsp.py with the repository root as its argument; prints
// one "ok <label>" or "FAIL <label>" line per check.

const Module = require("module");
const path = require("path");
const fs = require("fs");
const os = require("os");

const root = process.argv[2];
const extensionDir = path.join(root, "editors", "vscode");
let failed = 0;

function check(ok, label) {
  console.log((ok ? "ok " : "FAIL ") + label);
  if (!ok) failed += 1;
}

// The stand-ins record what the extension asks of VS Code.
const record = { clients: [], errors: [], settings: {}, folders: [] };
class LanguageClient {
  constructor(id, name, serverOptions, clientOptions) {
    this.args = { id, name, serverOptions, clientOptions };
    this.started = false;
    record.clients.push(this);
  }
  start() { this.started = true; return Promise.resolve(); }
  stop() { this.stopped = true; return Promise.resolve(); }
}
const stubs = {
  vscode: {
    workspace: {
      getConfiguration: () => ({ get: (key) => record.settings[key] }),
      get workspaceFolders() { return record.folders.map((f) => ({ uri: { fsPath: f } })); },
    },
    window: { showErrorMessage: (message) => record.errors.push(message) },
  },
  "vscode-languageclient/node": { LanguageClient, TransportKind: { stdio: 0 } },
};
const realLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request in stubs) return stubs[request];
  return realLoad.call(this, request, parent, isMain);
};

const extension = require(path.join(extensionDir, "extension.js"));
const server = path.join(root, "tools", "nova-lsp.py");

function activate(settings, folders, extensionPath) {
  record.clients = []; record.errors = [];
  record.settings = settings; record.folders = folders;
  const context = { subscriptions: [], extensionPath: extensionPath || extensionDir };
  extension.activate(context);
  return { client: record.clients[0], context };
}

// 1. A workspace that is (inside) a NovaLang checkout finds its own server.
let { client, context } = activate({}, [path.join(root, "examples")], os.tmpdir());
check(client !== undefined, "activating creates a language client");
if (client) {
  const run = client.args.serverOptions.run;
  check(run.command === "python3", "it runs python3 by default");
  check(JSON.stringify(run.args) === JSON.stringify([server]),
        "it finds tools/nova-lsp.py by walking up from the workspace");
  check(run.transport === 0, "it talks over stdio");
  check(client.args.serverOptions.debug === run, "debug runs the same server");
  const selector = client.args.clientOptions.documentSelector;
  check(selector.some((s) => s.language === "novalang" && s.scheme === "file") &&
        selector.some((s) => s.language === "novalang" && s.scheme === "untitled"),
        "it serves saved and unsaved .nova documents");
  check(client.started, "the client is started");
  check(context.subscriptions.length === 1, "stopping is registered for deactivation");
}

// 2. Settings win.
({ client } = activate({ pythonPath: "/opt/py/bin/python3", serverPath: server }, [], os.tmpdir()));
check(client && client.args.serverOptions.run.command === "/opt/py/bin/python3",
      "novalang.pythonPath is used");
check(client && client.args.serverOptions.run.args[0] === server, "novalang.serverPath is used");

// 3. With no workspace, the checkout the extension sits in is used.
({ client } = activate({}, [], extensionDir));
check(client && client.args.serverOptions.run.args[0] === server,
      "with no workspace, the extension's own checkout provides the server");

// 4. Nowhere to be found: say so, start nothing.
const empty = fs.mkdtempSync(path.join(os.tmpdir(), "nova-ext-"));
({ client } = activate({}, [empty], empty));
check(client === undefined && record.errors.length === 1 &&
      record.errors[0].includes("novalang.serverPath"),
      "a missing server is reported, not silently ignored");
({ client } = activate({ serverPath: path.join(empty, "nope.py") }, [], extensionDir));
check(client === undefined && record.errors.length === 1, "a wrong serverPath is reported");
fs.rmSync(empty, { recursive: true });

// 5. Deactivation stops the client.
({ client } = activate({}, [root], os.tmpdir()));
extension.deactivate();
check(client && client.stopped === true, "deactivate stops the client");

process.exit(failed ? 1 : 0);
