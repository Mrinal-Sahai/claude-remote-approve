// Guided onboarding: bot token -> validate -> detect chat id -> write config,
// install hooks, patch settings, send a test message.
import * as vscode from "vscode";
import * as tg from "./telegram";
import * as inst from "./installer";

export const SECRET_TOKEN_KEY = "claudeTgApprove.botToken";

async function promptToken(context: vscode.ExtensionContext): Promise<string | undefined> {
  const existing = await context.secrets.get(SECRET_TOKEN_KEY);
  const token = await vscode.window.showInputBox({
    title: "Connect your Telegram bot",
    prompt: "Paste the token from @BotFather (/newbot). It stays on this machine.",
    placeHolder: "1234567890:AAH...",
    value: existing || "",
    password: true,
    ignoreFocusOut: true,
    validateInput: (v) => (v.trim().includes(":") ? undefined : "That doesn't look like a bot token."),
  });
  return token?.trim();
}

async function waitForChatId(token: string): Promise<string | null> {
  // Telegram only knows your chat id after you message the bot once.
  for (let attempt = 0; attempt < 5; attempt++) {
    const chatId = await tg.detectChatId(token);
    if (chatId) {
      return chatId;
    }
    const choice = await vscode.window.showInformationMessage(
      "Open your bot in Telegram and send it any message (e.g. “hi”), then continue.",
      { modal: true },
      "I've sent it"
    );
    if (choice !== "I've sent it") {
      return null;
    }
  }
  return null;
}

export async function runSetup(context: vscode.ExtensionContext): Promise<boolean> {
  const token = await promptToken(context);
  if (!token) {
    return false;
  }

  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Telegram Approve", cancellable: false },
    async (progress): Promise<boolean> => {
      // 1. validate token
      progress.report({ message: "Validating bot token…" });
      let bot: tg.BotInfo;
      try {
        bot = await tg.getMe(token);
      } catch (e: any) {
        vscode.window.showErrorMessage(`Invalid token: ${e.message}`);
        return false;
      }
      await context.secrets.store(SECRET_TOKEN_KEY, token);

      // 2. detect chat id (needs the user to message the bot)
      progress.report({ message: `Connected to @${bot.username}. Detecting your chat…` });
      const chatId = await waitForChatId(token);
      if (!chatId) {
        vscode.window.showErrorMessage(
          "Couldn't detect your chat. Send your bot a message, then run Setup again."
        );
        return false;
      }

      // 3. write config (chmod 600) — the Python hooks read this
      progress.report({ message: "Writing config…" });
      const prev = inst.readConfig();
      inst.writeConfig({
        bot_token: token,
        chat_id: chatId,
        enabled: true,
        watcher_timeout_seconds: prev?.watcher_timeout_seconds ?? 600,
        poll_interval_seconds: prev?.poll_interval_seconds ?? 2,
        vscode_process_name: prev?.vscode_process_name ?? "Electron",
      });

      // 4. install hook scripts + register in settings.json
      progress.report({ message: "Installing hooks…" });
      try {
        const python = inst.findPython();
        inst.installHooks(context.extensionPath);
        inst.patchSettings(python);
      } catch (e: any) {
        vscode.window.showErrorMessage(`Hook install failed: ${e.message}`);
        return false;
      }

      // 5. confirmation message to the phone
      try {
        await tg.sendMessage(token, chatId, "✅ Claude Remote Approve connected. Permission prompts will appear here.");
      } catch {
        /* config is saved regardless; a failed test message isn't fatal */
      }

      const reload = await vscode.window.showInformationMessage(
        `Connected to @${bot.username}. Reload window to activate the hooks.`,
        "Reload Window"
      );
      if (reload === "Reload Window") {
        await vscode.commands.executeCommand("workbench.action.reloadWindow");
      }
      return true;
    }
  );
}
