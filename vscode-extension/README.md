# Claude Remote Approve (Telegram)

Approve **Claude Code** permission prompts from your phone over Telegram — with Allow, Deny, and Always buttons.

**Hands-free in both the VS Code panel and the terminal CLI, on macOS, Windows & Linux.**

![Status bar showing Telegram: on](https://raw.githubusercontent.com/Mrinal-Sahai/claude-remote-approve/main/docs/statusbar.png)

---

## How it works

When Claude Code wants to run a shell command, edit a file, or call a web endpoint, it pauses and sends a Telegram message to your phone. You tap **Allow**, **Deny**, or **Always** (auto-approve this command forever) — and Claude continues.

It works two ways automatically, depending on how you run Claude Code:

- **VS Code extension panel** — your tap injects a keystroke that answers the native prompt (macOS / Windows / Linux backends).
- **Terminal CLI** — the hook simply waits for your tap (up to 20s) and returns the decision directly, so no keystroke injection is needed and there's nothing to set up per-OS.

Either way: one tap on your phone, Claude continues, you never sat back down.

---

## Quick start (about 2 minutes)

### Step 1 — Install and run Setup

1. Install this extension.
2. Open the Command Palette (`Cmd+Shift+P`) and run **"Telegram Approve: Setup / Connect bot"**.
   *(Or click the `$(rocket) Telegram: setup` item in the status bar.)*

### Step 2 — Create your bot (one click from the wizard)

The wizard opens with an **"Open @BotFather"** button — click it (no need to go hunting in Telegram), then:

1. Send `/newbot` and follow the two prompts (a name and a username).
2. Copy the **bot token** BotFather gives you — it looks like `1234567890:AAH...`.
3. Paste it back into the VS Code input box.

*(Already have a token? Pick **"I already have a token"** to skip straight to pasting.)*

### Step 3 — Connect your phone

The setup wizard will ask you to send your bot a message so it can learn your chat ID. You have two options:

**Option A — Auto detect (easier)**
> The wizard opens your bot for you. Send it any message (e.g. "hi"), then click **Continue**. The extension detects your chat ID automatically.

**Option B — Enter manually (always works)**
> Click **"Enter ID manually"**, then open **[@userinfobot](https://t.me/userinfobot)** in Telegram and send it any message. It replies with your numeric ID — paste that into the VS Code input box.

After setup, your phone receives a confirmation message. Reload the VS Code window when prompted, and you are done.

> **Updates are automatic.** You only do setup once. When the extension updates, it refreshes the hook scripts on the next launch by itself — your bot stays connected, no re-setup needed.

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
| **Keystroke backend** | VS Code extension mode injects your tap as a keystroke: macOS uses AppleScript (needs Accessibility), Windows uses PowerShell, Linux uses `xdotool`. CLI mode needs none of this. |

### Platform & Claude Code mode support

There are two ways to run Claude Code: the **VS Code extension** (panel inside VS Code) and the **CLI** (`claude` in a terminal). The extension detects which one you're using (via `CLAUDE_CODE_ENTRYPOINT`) and picks the right strategy automatically — both are fully hands-free.

| Mode | How your tap is applied | Result |
|------|-------------------------|--------|
| **VS Code extension** | Native Quick Pick appears instantly; your tap injects a keystroke that answers it | One tap, hands-free |
| **CLI (any terminal)** | The hook **blocks** and waits for your tap, then returns the decision directly — no terminal prompt is shown | One tap, hands-free |

The CLI "blocking" strategy means Claude simply pauses until you tap — no keystroke injection involved, so it works identically on **macOS, Windows, and Linux** with no extra dependency.

**Commands gated:** `Bash`, `PowerShell` (native Windows), `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, and `WebFetch`. On Windows, Claude Code's `PowerShell` tool is a separate tool from `Bash` — both are covered, so shell commands trigger a notification regardless of which shell Claude uses.

#### Keystroke injection (VS Code extension mode only)

| OS | Backend | Notes |
|----|---------|-------|
| **macOS** | AppleScript (`osascript`) | Needs Accessibility permission |
| **Windows** | PowerShell `SendKeys` | Built in — no extra install. Sends to the focused window. |
| **Linux** | `xdotool` | Install via `apt install xdotool` / `dnf install xdotool` (X11). |

> CLI mode does **not** use injection, so it needs no Accessibility permission and no `xdotool` — it works everywhere out of the box.

#### CLI blocking window

In CLI mode the hook waits up to **20 seconds** for your tap, then falls back to the normal terminal prompt (you can still answer there). Fresh installs register a matching Claude Code hook timeout so the block isn't cut short — if you upgraded from an older version, re-run **"Telegram Approve: Setup"** to apply it.

#### Disable it instantly on the CLI

Set an environment variable in the shell that runs `claude` — the hook steps aside immediately and you get normal local prompts, no file edits or restart needed:

```bash
export TG_APPROVE_OFF=1     # disable for this shell session
claude                      # runs with normal local prompts

unset TG_APPROVE_OFF        # re-enable
```

To disable **permanently** (all sessions, both CLI and the VS Code panel), flip the config flag:

```bash
python3 -c "import json,os;p=os.path.expanduser('~/.claude/hooks/tg-approve/config.json');c=json.load(open(p));c['enabled']=False;json.dump(c,open(p,'w'),indent=2);print('tg-approve disabled')"
```

Set `enabled` back to `true` (or use the status bar **Enable** action in VS Code) to turn it on again.

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
| **macOS Accessibility** (VS Code extension mode only) | Lets the keystroke backend answer the Quick Pick when you tap on your phone. | *System Settings → Privacy & Security → Accessibility → VS Code (Electron) → toggle on* |
| **`xdotool`** (Linux, VS Code extension mode only) | Same keystroke backend on Linux/X11. | `sudo apt install xdotool` or `sudo dnf install xdotool` |

> These are only needed for keystroke injection in **VS Code extension mode**. Windows uses built-in PowerShell (nothing to install). **CLI mode needs none of them** — it waits for your tap and answers directly, on every OS.

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
