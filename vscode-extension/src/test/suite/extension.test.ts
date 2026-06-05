// Integration tests — run inside a real VS Code via @vscode/test-electron.
// These need a windowing environment (or xvfb on Linux CI); they can't run in a
// pure headless shell. See ../../../TESTING.md §8.
import * as assert from "node:assert";
import * as vscode from "vscode";

const EXT_ID = "MrinalSahai.claude-remote-approve";

describe("claude-remote-approve", () => {
  it("is installed and activates", async () => {
    const ext = vscode.extensions.getExtension(EXT_ID);
    assert.ok(ext, `extension ${EXT_ID} not found`);
    await ext.activate();
    assert.ok(ext.isActive, "extension failed to activate");
  });

  it("registers all contributed commands", async () => {
    const cmds = await vscode.commands.getCommands(true);
    const expected = [
      "claudeTgApprove.setup",
      "claudeTgApprove.toggle",
      "claudeTgApprove.manageAllowlist",
      "claudeTgApprove.openLog",
      "claudeTgApprove.reconnect",
      "claudeTgApprove.uninstall",
      "claudeTgApprove.statusMenu",
    ];
    for (const c of expected) {
      assert.ok(cmds.includes(c), `command not registered: ${c}`);
    }
  });
});
