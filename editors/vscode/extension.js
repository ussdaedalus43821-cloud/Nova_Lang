// The NovaLang extension: a thin client that starts tools/nova-lsp.py and
// connects it to VS Code. Every language feature lives in the server, so the
// same server can back any LSP-capable editor. Plain JavaScript, so there is
// no build step: `npm install` here, then run the extension.

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

const SERVER = path.join("tools", "nova-lsp.py");

let client;

// Where tools/nova-lsp.py is: the novalang.serverPath setting; else each
// workspace folder or any folder above it; else the NovaLang checkout this
// extension sits in (editors/vscode/ inside it).
function findServer(configured, workspaceFolders, extensionDir) {
  if (configured) {
    return fs.existsSync(configured) ? configured : null;
  }
  for (const folder of workspaceFolders) {
    let directory = folder;
    for (;;) {
      const candidate = path.join(directory, SERVER);
      if (fs.existsSync(candidate)) {
        return candidate;
      }
      const parent = path.dirname(directory);
      if (parent === directory) {
        break;
      }
      directory = parent;
    }
  }
  const bundled = path.join(extensionDir, "..", "..", SERVER);
  return fs.existsSync(bundled) ? path.normalize(bundled) : null;
}

function activate(context) {
  const settings = vscode.workspace.getConfiguration("novalang");
  const folders = (vscode.workspace.workspaceFolders || []).map((f) => f.uri.fsPath);
  const server = findServer(settings.get("serverPath"), folders, context.extensionPath);
  if (!server) {
    vscode.window.showErrorMessage(
      "NovaLang: cannot find tools/nova-lsp.py - open a NovaLang checkout, " +
        "or set novalang.serverPath."
    );
    return;
  }
  const run = {
    command: settings.get("pythonPath") || "python3",
    args: [server],
    transport: TransportKind.stdio,
  };
  client = new LanguageClient(
    "novalang",
    "NovaLang",
    { run, debug: run },
    {
      documentSelector: [
        { scheme: "file", language: "novalang" },
        { scheme: "untitled", language: "novalang" },
      ],
    }
  );
  context.subscriptions.push({ dispose: () => client && client.stop() });
  return client.start();
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate, findServer };
