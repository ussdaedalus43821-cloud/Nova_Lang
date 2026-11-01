# NovaLang for VS Code

Syntax highlighting for `.nova` files, plus diagnostics, formatting,
go-to-definition and hover, served by NovaLang's own language server,
`tools/nova-lsp.py`.

## Install (from this checkout)

```bash
cd editors/vscode
npm install                 # fetches vscode-languageclient, the only dependency
```

Then either open `editors/vscode` in VS Code and press **F5** (an Extension
Development Host starts with NovaLang support), or package it:

```bash
npx @vscode/vsce package    # writes novalang-0.3.0.vsix
code --install-extension novalang-0.3.0.vsix
```

There is no build step: `extension.js` is plain JavaScript.

## What it does

| In the editor           | Comes from                                              |
|-------------------------|---------------------------------------------------------|
| Red and yellow squiggles | `nova-lint` and `nova-typecheck`, as you type          |
| Format Document          | `nova-fmt` (the layout is fixed; tab-size options are ignored) |
| Go to Definition (F12)   | locals, parameters, functions, imports, packages      |
| Hover                    | the type of the name under the cursor                 |
| Colours                  | `syntaxes/novalang.tmLanguage.json`                   |

## Settings

- `novalang.pythonPath` - the Python 3 that runs the server (default `python3`).
- `novalang.serverPath` - path to `tools/nova-lsp.py`. When empty, it is looked
  for in each workspace folder and the folders above it, then in the NovaLang
  checkout this extension sits in.

## Other editors

The server speaks plain LSP over stdio, so any LSP client can use it: run
`python3 tools/nova-lsp.py` for files with the `.nova` extension.

## Testing

`tests/lsp/test_lsp.py` (part of `tests/run_all.py`) drives the server over
real JSON-RPC, checks this extension's manifest and grammar - the grammar's
keywords, built-ins and types must equal the language's own - and runs
`extension.js` under Node with stand-ins for the `vscode` modules.
