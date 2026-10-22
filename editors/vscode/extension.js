// The Vela extension: VS Code starts `vela lsp` when a .vl file is opened
// and talks to it for errors, hover, go to definition, references, the
// outline and formatting. The highlighting is syntaxes/vela.tmLanguage.json.
const vscode = require("vscode");
const { LanguageClient } = require("vscode-languageclient/node");

let client;

function activate(context) {
  const command = vscode.workspace.getConfiguration("vela").get("path", "vela");
  const server = { command, args: ["lsp"] };
  client = new LanguageClient(
    "vela",
    "Vela",
    { run: server, debug: server },
    { documentSelector: [{ scheme: "file", language: "vela" }] },
  );
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("vela.path")) {
        vscode.window.showInformationMessage("Reload the window to use the new vela.path.");
      }
    }),
  );
  return client.start();
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
