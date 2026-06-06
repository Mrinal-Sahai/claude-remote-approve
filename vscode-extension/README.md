# Claude Remote Approve (Telegram)

Approve **Claude Code** permission prompts from your phone over Telegram — with Allow, Deny, and Always buttons.

![Status bar showing Telegram: on](https://raw.githubusercontent.com/Mrinal-Sahai/claude-remote-approve/main/docs/statusbar.png)

---

## How it works

When Claude Code wants to run a shell command, edit a file, or call a web endpoint, it pauses and sends a Telegram message to your phone. You tap **Allow**, **Deny**, or **Always** (auto-approve this command forever) — and Claude continues.

---

## Quick start (about 2 minutes)

### Step 1 — Create a Telegram bot

1. Open Telegram and search for **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot` and follow the prompts (give it a name and a username).
3. Copy the **bot token** BotFather gives you — it looks like `1234567890:AAH...`.

### Step 2 — Install and run Setup

1. Install this extension.
2. Open the Command Palette (`Cmd+Shift+P`) and run **"Telegram Approve: Setup / Connect bot"**.
   *(Or click the `$(rocket) Telegram: setup` item in the status bar.)*
3. Paste the bot token from Step 1.

### Step 3 — Connect your phone

The setup wizard will ask you to send your bot a message so it can learn your chat ID. You have two options:

**Option A — Auto detect (easier)**
> The wizard opens your bot for you. Send it any message (e.g. "hi"), then click **Continue**. The extension detects your chat ID automatically.

**Option B — Enter manually (always works)**
> Click **"Enter ID manually"**, then open **[@userinfobot](https://t.me/userinfobot)** in Telegram and send it any message. It replies with your numeric ID — paste that into the VS Code input box.

After setup, your phone receives a confirmation message. Reload the VS Code window when prompted, and you are done.

---

## What you will see on your phone

Every time Claude Code needs a permission, your phone gets a message like:

```
🔔 Claude needs permission

`Bash: rm -rf ./dist`

✅ Allow   ⛔ Deny   ♾️ Always
```

Tap a button — the response is instant.

---

## Status bar

The **Telegram** item in the bottom-right status bar shows the current state:

| Icon | Meaning |
|------|---------|
| `$(broadcast) Telegram: on` | Hooks active, approvals being sent to phone |
| `$(rocket) Telegram: setup` | Not yet configured — click to run setup |
| `$(circle-slash) Telegram: off` | Configured but disabled |

Click the status bar item for quick actions:

- **Enable / Disable** — pause phone notifications without uninstalling.
- **Manage 'Always' list** — review and remove saved auto-approve rules.
- **Reconnect / change bot** — re-run setup with a different bot token.
- **Open log** — view the hook activity log.
- **Uninstall hooks** — cleanly remove our `settings.json` entries (optionally wipe scripts and token too).

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| **Claude Code** | Must be installed |
| **Python 3.8+** | Must be on your `PATH` |
| **macOS** (for full experience) | Phone-tap → keystroke auto-inject uses AppleScript (`osascript`). macOS only. See platform table below. |
| **Accessibility permission** (macOS) | Grant VS Code in *System Settings → Privacy & Security → Accessibility* for auto-inject to work. |

### Platform & Claude Code mode support

There are two ways to run Claude Code: the **VS Code extension** (panel inside VS Code) and the **CLI** (`claude` in a terminal). They behave differently with this extension.

| Feature | VS Code extension | CLI — integrated terminal | CLI — external terminal |
|---------|:-----------------:|:-------------------------:|:-----------------------:|
| Phone notification (Allow / Deny / Always) | ✅ | ✅ | ✅ |
| Tap auto-injects answer — no editor interaction needed | ✅ | ⚠️ Unreliable | ❌ |
| Setup wizard, status bar, config | ✅ | ✅ | ✅ |
| Allowlist ("Always") rules | ✅ | ✅ | ✅ |

And by operating system:

| Feature | macOS | Windows | Linux |
|---------|:-----:|:-------:|:-----:|
| Phone notification | ✅ | ✅ | ✅ |
| Tap auto-injects answer | ✅ | ❌ | ❌ |

**VS Code extension mode (recommended):** full experience. Permission prompt appears as a VS Code Quick Pick; tapping Allow/Deny on your phone auto-dismisses it via AppleScript.

**CLI in external terminal:** notification arrives on your phone, you tap — but the terminal prompt (y/N) is not auto-answered. You still need to type in the terminal. Windows/Linux CLI support is a planned improvement.

**CLI in VS Code integrated terminal:** somewhere in between — behaviour depends on which window has focus. Not officially supported.

---

## Finding your chat ID manually

If auto-detection does not work, open **[@userinfobot](https://t.me/userinfobot)** in Telegram and send it any message. It replies immediately with something like:

```
Your user ID: 987654321
First name: Mrinal
...
```

Copy the number next to **"Your user ID"** and paste it into the setup input box.

---

## Permissions & system footprint

This extension is intentionally minimal. Here is every permission it needs and every file it touches — nothing hidden.

### Permissions required

| Permission | Why | How to grant |
|------------|-----|--------------|
| **macOS Accessibility** | Auto-injects keystrokes when you tap Allow/Deny on your phone. Without this, you still get the notification but must manually confirm in the editor. | *System Settings → Privacy & Security → Accessibility → VS Code (Electron) → toggle on* |

> macOS is the only platform where Accessibility is needed. On other platforms, approvals still arrive on your phone — you just confirm in the editor manually.

### Network access

| Destination | What |
|-------------|------|
| `api.telegram.org` (HTTPS, outbound only) | Sends approval requests to your phone; receives your tap response. **No other server is contacted. No analytics. No telemetry.** |

### What is stored and where

| What | Where | Format |
|------|-------|--------|
| Bot token | VS Code Secret Storage (encrypted, never on disk in plaintext) | VS Code built-in secrets API |
| Chat ID + config | `~/.claude/hooks/tg-approve/config.json` | `chmod 600` — readable only by you |
| Hook scripts | `~/.claude/hooks/tg-approve/*.py` | Plain Python, readable, deletable |
| Activity log | `~/.claude/hooks/tg-approve/tg-approve.log` | Plain text, rotated automatically |
| Allow-list rules | `~/.claude/hooks/tg-approve/allowlist.json` | Plain JSON |

### What changes on your machine

| Path | What |
|------|------|
| `~/.claude/hooks/tg-approve/` | Hook scripts + `config.json` (chmod 600) |
| `~/.claude/settings.json` | `PreToolUse` + `PostToolUse` entries added (existing hooks preserved) |

**Uninstall cleanly:** run *"Telegram Approve: Uninstall hooks"* from the Command Palette. It removes our entries from `settings.json` and optionally deletes all scripts, config, and logs.

---

## Troubleshooting

**Setup says "Could not auto-detect"**
Use the manual path: open [@userinfobot](https://t.me/userinfobot), send any message, paste the number.

**Prompts stopped appearing on my phone**
Check the status bar item — it should say `Telegram: on`. If not, click it and choose **Enable**. Also check `~/.claude/hooks/tg-approve/tg-approve.log`.

**"Accessibility permission" warning**
Open *System Settings → Privacy & Security → Accessibility*, find VS Code (or "Electron"), and toggle it on.

**I want to use a different bot**
Run **"Telegram Approve: Reconnect / change bot"** from the Command Palette.

---

## Source & architecture

[github.com/Mrinal-Sahai/claude-remote-approve](https://github.com/Mrinal-Sahai/claude-remote-approve) — see `IMPLEMENTATION.md` for the technical design (single-dispatcher model, rate limiting, per-host offset, graceful expiry).

## License

[MIT](https://github.com/Mrinal-Sahai/claude-remote-approve/blob/main/LICENSE)
