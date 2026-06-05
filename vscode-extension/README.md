# Claude Remote Approve (Telegram) — VS Code extension

Approve **Claude Code** permission prompts from your phone over Telegram, with a
one-click setup. This extension is a GUI installer + manager around the
[claude-remote-approve](https://github.com/Mrinal-Sahai/claude-remote-approve)
Python hooks — it bundles them, wires them into Claude Code, and gives you a
status-bar control. The hooks themselves keep working in the plain terminal too.

## Setup (≈ 1 minute)

1. Install the extension.
2. Run **“Telegram Approve: Setup / Connect bot”** from the Command Palette (or
   click the status-bar item, or accept the first-run prompt).
3. Paste your bot token from [@BotFather](https://t.me/BotFather) (`/newbot`).
4. When asked, open your bot in Telegram and send it any message.
5. Reload the window when prompted. Done.

From then on, any Claude Code permission prompt also appears in Telegram with
**✅ Allow / ⛔ Deny / ♾️ Always** buttons.

## Status-bar control

Click the **Telegram** item in the status bar for:

- **Enable / Disable** remote approvals (flips `enabled` in config).
- **Manage 'Always' allowlist** — review and remove saved auto-approve rules.
- **Reconnect / change bot** — re-run setup with a different bot.
- **Open log** — view `~/.claude/hooks/tg-approve/tg-approve.log`.

## How the token is stored

Your bot token is written to `~/.claude/hooks/tg-approve/config.json`
(`chmod 600`) — the Python hooks run as separate processes (even from the
terminal when VS Code is closed), so they must read it from disk. The token is
**also** mirrored into VS Code **SecretStorage** so the Setup UI can pre-fill /
rotate it without asking again. It never leaves your machine except in calls to
Telegram's API.

## Requirements

- **Claude Code** installed.
- **Python 3.8+** on your `PATH`.
- **macOS** for phone-tap → editor keystroke injection (notifications work
  everywhere; auto-injection is macOS-only for now). Grant VS Code
  **Accessibility** permission in *System Settings → Privacy & Security*.

## What it changes on your machine

- Copies hook scripts to `~/.claude/hooks/tg-approve/`.
- Adds `PreToolUse` + `PostToolUse` entries to `~/.claude/settings.json`
  (existing hooks are preserved).
- Writes `config.json` (chmod 600) and, on "Always" taps, `allowlist.json`.

See the [main repo](https://github.com/Mrinal-Sahai/claude-remote-approve) for
architecture (`IMPLEMENTATION.md`) and security details.

## License

[MIT](https://github.com/Mrinal-Sahai/claude-remote-approve/blob/main/LICENSE)
