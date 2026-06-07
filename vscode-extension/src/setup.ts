// Guided onboarding: bot token -> validate -> detect chat id -> write config,
// install hooks, patch settings, send a test message.
import * as vscode from "vscode";
import { execFile } from "node:child_process";
import * as path from "node:path";
import * as tg from "./telegram";
import * as inst from "./installer";

export const SECRET_TOKEN_KEY = "claudeTgApprove.botToken";

async function promptToken(context: vscode.ExtensionContext): Promise<string | undefined> {
  const existing = await context.secrets.get(SECRET_TOKEN_KEY);

  // First, help the user get a token without leaving the flow to go hunt for
  // @BotFather. (Telegram has no API to mint tokens — only @BotFather can — so
  // this is the smoothest it gets: one click to the right chat, then paste.)
  const choice = await vscode.window.showInformationMessage(
    "Step 1 of 3 — Connect a Telegram bot.\n\n" +
      "Need one? Click below to open @BotFather, send /newbot, follow the two prompts " +
      "(name + username), and copy the token it gives you — it looks like 1234567890:AAH...",
    { modal: true },
    "Open @BotFather",
    "I already have a token"
  );
  if (!choice) { return undefined; }
  if (choice === "Open @BotFather") {
    vscode.env.openExternal(vscode.Uri.parse("https://t.me/BotFather"));
  }

  const token = await vscode.window.showInputBox({
    title: "Step 1 of 3 — Paste your bot token",
    prompt: "Paste the token @BotFather gave you (looks like 1234567890:AAH...).",
    placeHolder: "1234567890:AAH...",
    value: existing || "",
    password: true,
    ignoreFocusOut: true,
    validateInput: (v) => (v.trim().includes(":") ? undefined : "That does not look like a bot token (must contain ':')."),
  });
  return token?.trim();
}

/**
 * Spawn detect_chat_id.py which kills any running dispatcher, then long-polls
 * Telegram using the proven Python urllib stack and prints just the chat_id.
 */
function detectViaPython(python: string, scriptPath: string, token: string): Promise<string | null> {
  return new Promise((resolve) => {
    execFile(
      python,
      [scriptPath, token, "60"],
      { timeout: 75000 },
      (_err, stdout) => {
        const chatId = stdout.trim();
        resolve(/^\d+$/.test(chatId) ? chatId : null);
      }
    );
  });
}

/** Manual fallback: user reads their ID from @userinfobot and types it in. */
async function promptManualChatId(): Promise<string | null> {
  const chatId = await vscode.window.showInputBox({
    title: "Step 3 of 3 — Enter your chat ID",
    prompt: "Paste the numeric ID shown by @userinfobot. It looks like: 987654321",
    placeHolder: "987654321",
    ignoreFocusOut: true,
    validateInput: (v) => (/^\d+$/.test(v.trim()) ? undefined : "Must be a plain number — no spaces, letters, or symbols."),
  });
  return chatId?.trim() || null;
}

async function waitForChatId(
  token: string,
  python: string,
  scriptPath: string,
  botUsername: string
): Promise<string | null> {

  // ── Step 1: help the user open their bot ─────────────────────────────────
  const openChoice = await vscode.window.showInformationMessage(
    `Step 2 of 3 — Open @${botUsername} in Telegram on your phone (or this machine) and send it any message, e.g. "hi".`,
    { modal: true },
    "Open on this machine",
    "Already open on my phone"
  );
  if (!openChoice) { return null; }

  if (openChoice === "Open on this machine") {
    vscode.env.openExternal(vscode.Uri.parse(`https://t.me/${botUsername}`));
  }

  // Start Python polling NOW — running in background while user switches apps
  const detectPromise = detectViaPython(python, scriptPath, token);

  // ── Step 2: user confirms they sent the message ───────────────────────────
  const sendChoice = await vscode.window.showInformationMessage(
    `Send @${botUsername} any message now (e.g. "hi"), then click Continue. Auto-detection runs in the background.`,
    { modal: true },
    "Continue",
    "Enter ID manually"
  );

  if (sendChoice === "Enter ID manually") {
    return manualFlow();
  }
  if (!sendChoice) { return null; }

  // Give Python up to 20 s after Continue (covers "sent just before clicking")
  const chatId = await Promise.race([
    detectPromise,
    new Promise<null>((r) => setTimeout(() => r(null), 20000)),
  ]);
  if (chatId) { return chatId; }

  // ── Auto-detection failed: seamless fallback ──────────────────────────────
  const fallback = await vscode.window.showInformationMessage(
    "Could not auto-detect. No problem — get your chat ID in 20 seconds:\n\n1. Open https://t.me/userinfobot in Telegram\n2. Send it any message\n3. It replies with your numeric ID\n4. Paste that number in the next box",
    { modal: true },
    "Open https://t.me/userinfobot",
    "I already have my ID"
  );
  if (!fallback) { return null; }
  if (fallback === "Open https://t.me/userinfobot") {
    vscode.env.openExternal(vscode.Uri.parse("https://t.me/userinfobot"));
  }
  return promptManualChatId();
}

/** Full manual flow shown when user picks "Enter ID manually" upfront. */
async function manualFlow(): Promise<string | null> {
  const go = await vscode.window.showInformationMessage(
    "To find your chat ID: open @userinfobot in Telegram, send it any message, and it will reply with your numeric ID.",
    { modal: true },
    "Open @userinfobot",
    "I already have my ID"
  );
  if (!go) { return null; }
  if (go === "Open @userinfobot") {
    vscode.env.openExternal(vscode.Uri.parse("https://t.me/userinfobot"));
  }
  return promptManualChatId();
}

export async function runSetup(context: vscode.ExtensionContext): Promise<boolean> {
  const token = await promptToken(context);
  if (!token) { return false; }

  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Telegram Approve: Setup", cancellable: false },
    async (progress): Promise<boolean> => {

      // 1. validate token
      progress.report({ message: "Validating token..." });
      let bot: tg.BotInfo;
      try {
        bot = await tg.getMe(token);
      } catch (e: any) {
        vscode.window.showErrorMessage(`Invalid token: ${e.message}`);
        return false;
      }
      await context.secrets.store(SECRET_TOKEN_KEY, token);

      // 2. copy bundled scripts (makes detect_chat_id.py available before we use it)
      let python: string;
      try {
        python = inst.findPython();
        inst.installHooks(context.extensionPath);
      } catch (e: any) {
        vscode.window.showErrorMessage(`Python 3 not found: ${e.message}`);
        return false;
      }

      // 3. detect chat id
      progress.report({ message: `Connected to @${bot.username} — follow the prompts...` });
      const scriptPath = path.join(inst.hookDir(), "detect_chat_id.py");
      const chatId = await waitForChatId(token, python, scriptPath, bot.username);
      if (!chatId) {
        vscode.window.showErrorMessage("Setup cancelled.");
        return false;
      }

      // 4. write config.json (chmod 600)
      progress.report({ message: "Saving config..." });
      const prev = inst.readConfig();
      inst.writeConfig({
        bot_token: token,
        chat_id: chatId,
        enabled: true,
        watcher_timeout_seconds: prev?.watcher_timeout_seconds ?? 600,
        poll_interval_seconds: prev?.poll_interval_seconds ?? 2,
        vscode_process_name: prev?.vscode_process_name ?? "Code",
      });

      // 5. register hooks in settings.json
      progress.report({ message: "Registering hooks..." });
      try {
        inst.patchSettings(python);
      } catch (e: any) {
        vscode.window.showErrorMessage(`Hook registration failed: ${e.message}`);
        return false;
      }

      // 6. test message to the phone
      try {
        await tg.sendMessage(
          token,
          chatId,
          "Claude Remote Approve is connected.\n\nNext time Claude Code asks for permission, you will see it here with Allow / Deny / Always buttons."
        );
      } catch {
        /* non-fatal — config is already saved */
      }

      const reload = await vscode.window.showInformationMessage(
        `All done! Connected to @${bot.username}. Reload the window to activate the hooks.`,
        "Reload Window"
      );
      if (reload === "Reload Window") {
        await vscode.commands.executeCommand("workbench.action.reloadWindow");
      }
      return true;
    }
  );
}
