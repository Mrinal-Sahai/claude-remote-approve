// View and remove saved "Always" allowlist rules via a multi-select QuickPick.
import * as vscode from "vscode";
import * as inst from "./installer";

export async function manageAllowlist(): Promise<void> {
  const rules = inst.readAllowlist();
  if (rules.length === 0) {
    vscode.window.showInformationMessage("No 'Always' rules saved yet.");
    return;
  }

  const picks = await vscode.window.showQuickPick(
    rules.map((r) => ({ label: r, picked: false })),
    {
      title: "Saved 'Always' rules — select any to REMOVE",
      canPickMany: true,
      placeHolder: "Checked rules will be deleted (you'll be prompted again for them next time)",
    }
  );

  if (!picks || picks.length === 0) {
    return;
  }

  const toRemove = new Set(picks.map((p) => p.label));
  const remaining = rules.filter((r) => !toRemove.has(r));
  inst.writeAllowlist(remaining);
  vscode.window.showInformationMessage(`Removed ${toRemove.size} rule(s); ${remaining.length} remaining.`);
}
