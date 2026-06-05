import * as vscode from "vscode";
import * as fs from "node:fs";
import { runSetup } from "./setup";
import { manageAllowlist } from "./allowlist";
import * as inst from "./installer";

let statusBar: vscode.StatusBarItem;

function updateStatusBar(): void {
  const cfg = inst.readConfig();
  if (!cfg?.bot_token || !cfg?.chat_id) {
    statusBar.text = "$(rocket) Telegram: setup";
    statusBar.tooltip = "Click to connect a Telegram bot for remote approvals";
  } else if (cfg.enabled) {
    statusBar.text = "$(broadcast) Telegram: on";
    statusBar.tooltip = "Remote approvals are ON — click for options";
  } else {
    statusBar.text = "$(circle-slash) Telegram: off";
    statusBar.tooltip = "Remote approvals are OFF — click for options";
  }
  statusBar.show();
}

async function statusMenu(context: vscode.ExtensionContext): Promise<void> {
  const cfg = inst.readConfig();
  if (!cfg?.bot_token || !cfg?.chat_id) {
    await runSetup(context);
    updateStatusBar();
    return;
  }
  const toggleLabel = cfg.enabled ? "$(circle-slash) Disable remote approvals" : "$(check) Enable remote approvals";
  const pick = await vscode.window.showQuickPick(
    [
      { label: toggleLabel, id: "toggle" },
      { label: "$(list-unordered) Manage 'Always' allowlist", id: "allowlist" },
      { label: "$(sync) Reconnect / change bot", id: "reconnect" },
      { label: "$(output) Open log", id: "log" },
    ],
    { title: "Telegram Remote Approve" }
  );
  if (!pick) {
    return;
  }
  switch (pick.id) {
    case "toggle":
      inst.setEnabled(!cfg.enabled);
      updateStatusBar();
      break;
    case "allowlist":
      await manageAllowlist();
      break;
    case "reconnect":
      await runSetup(context);
      updateStatusBar();
      break;
    case "log":
      await vscode.commands.executeCommand("claudeTgApprove.openLog");
      break;
  }
}

async function openLog(): Promise<void> {
  const p = inst.logPath();
  if (!fs.existsSync(p)) {
    vscode.window.showInformationMessage("No log yet — it appears after the first permission prompt.");
    return;
  }
  const doc = await vscode.workspace.openTextDocument(p);
  await vscode.window.showTextDocument(doc, { preview: true });
}

export function activate(context: vscode.ExtensionContext): void {
  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBar.command = "claudeTgApprove.statusMenu";

  context.subscriptions.push(
    statusBar,
    vscode.commands.registerCommand("claudeTgApprove.setup", async () => {
      await runSetup(context);
      updateStatusBar();
    }),
    vscode.commands.registerCommand("claudeTgApprove.reconnect", async () => {
      await runSetup(context);
      updateStatusBar();
    }),
    vscode.commands.registerCommand("claudeTgApprove.toggle", () => {
      const cfg = inst.readConfig();
      if (!cfg || !cfg.bot_token) {
        vscode.window.showWarningMessage("Run 'Telegram Approve: Setup' first.");
        return;
      }
      inst.setEnabled(!cfg.enabled);
      updateStatusBar();
      vscode.window.showInformationMessage(`Remote approvals ${cfg.enabled ? "disabled" : "enabled"}.`);
    }),
    vscode.commands.registerCommand("claudeTgApprove.manageAllowlist", manageAllowlist),
    vscode.commands.registerCommand("claudeTgApprove.openLog", openLog),
    vscode.commands.registerCommand("claudeTgApprove.statusMenu", () => statusMenu(context))
  );

  updateStatusBar();

  // First-run nudge: offer setup once if nothing is configured.
  if (!inst.isConfigured() && !context.globalState.get("claudeTgApprove.nudged")) {
    context.globalState.update("claudeTgApprove.nudged", true);
    vscode.window
      .showInformationMessage(
        "Approve Claude Code prompts from your phone? Connect a Telegram bot.",
        "Set up now",
        "Later"
      )
      .then((choice) => {
        if (choice === "Set up now") {
          vscode.commands.executeCommand("claudeTgApprove.setup");
        }
      });
  }
}

export function deactivate(): void {
  /* nothing to clean up — the Python hooks run independently */
}
