# claude-remote-approve

**Approve Claude Code's permission prompts from your phone, over Telegram.**

When Claude Code wants to run a shell command, edit a file, or fetch a URL, it
normally asks you for permission *in the editor*. This tool mirrors that prompt
to a Telegram chat with **✅ Allow / ⛔ Deny / ♾️ Always** buttons. Tap one on
your phone and Claude continues — even when you're away from the keyboard.

The editor prompt stays live too: whoever answers first wins. Nothing is
auto-approved. If you ignore the phone, you just answer in the editor as usual.

```
┌─────────────┐   tool call    ┌──────────────┐   sendMessage   ┌──────────┐
│ Claude Code │ ─────────────▶ │ approve hook │ ───────────────▶│ Telegram │
└─────────────┘                └──────────────┘                 └────┬─────┘
       ▲                              │ also shows                   │ tap
       │ keystroke (allow/deny)       ▼ the normal editor prompt     │ Allow
       └──────────────────────  watcher ◀── dispatcher ◀────────────┘
```

---

## Why

- **Step away from your desk.** Long agentic runs pause on permission prompts.
  Approve them from the couch, the kitchen, or the bus.
- **Stay in control.** Every gated action still needs an explicit tap. "Always"
  rules are opt-in and per-command.
- **Zero cloud dependency beyond Telegram.** No server to run, no account to
  create besides a free Telegram bot. Pure Python stdlib + Telegram Bot API.

---

## Requirements

- **Claude Code** (the CLI / VS Code extension).
- **Python 3.8+** (uses stdlib only).
- A **Telegram bot token** (free, from [@BotFather](https://t.me/BotFather)).
- For the **VS Code panel** keystroke path: macOS needs Accessibility
  permission, Linux needs `xdotool`, Windows uses built-in PowerShell. The
  **CLI** path needs none of this — it works everywhere out of the box
  (see *Platform support*).

---

## Install

### Option A — VS Code extension (one-click setup)

Install **“Claude Remote Approve (Telegram)”** from the Marketplace, then run
**Telegram Approve: Setup** from the Command Palette. It bundles these scripts,
walks you through connecting your bot, and wires everything up. See
[`vscode-extension/`](vscode-extension/).

### Option B — Shell installer (terminal / non-VS-Code)

```bash
git clone https://github.com/Mrinal-Sahai/claude-remote-approve.git
cd claude-remote-approve
./install.sh
```

The installer will:
1. Copy the hook scripts into `~/.claude/hooks/tg-approve/`.
2. Register the `PreToolUse` + `PostToolUse` hooks in `~/.claude/settings.json`
   (without touching any hooks you already have).
3. Walk you through connecting your bot: paste the token, message the bot once,
   and it auto-detects your chat ID and sends a confirmation.

Then **restart Claude Code** so it reloads `settings.json`.

### Getting a bot token (30 seconds)

1. Open [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/newbot`, pick a name and username.
3. Copy the token it gives you (looks like `1234567890:AAH...`).
4. Open your new bot, send it any message (e.g. `hi`) — this is how the
   installer learns *your* chat ID.

---

## Usage

Just use Claude Code normally. Whenever a tool needs permission you'll get a
Telegram message:

> 🔔 **Claude needs permission**
> `Bash: rm -rf build/`
> Approve on your phone, or answer in the editor.
> [ ✅ Allow ] [ ⛔ Deny ] [ ♾️ Always ]

- **✅ Allow** — runs this one call.
- **⛔ Deny** — rejects this one call.
- **♾️ Always** — runs it *and* remembers the rule so the same kind of call is
  auto-approved next time (no phone, no editor prompt).

### The "Always" allowlist

"Always" rules are stored in `~/.claude/hooks/tg-approve/allowlist.json`:

```json
["Bash:git", "Bash:npm", "Write:*"]
```

- `Bash:<cmd>` matches by the **first word** of the command (`Bash:git` covers
  `git status`, `git push`, …).
- `Tool:*` matches every call of that tool (`Write:*`, `WebFetch:*`).

Delete entries any time to start prompting for them again.

### Turning it off

**Instantly, for one shell session (CLI):** export an environment variable in
the terminal that runs `claude` — the hook steps aside at once and you get
normal local prompts:

```bash
export TG_APPROVE_OFF=1     # off for this session
unset TG_APPROVE_OFF        # back on
```

**Persistently (all sessions):** set `"enabled": false` in
`~/.claude/hooks/tg-approve/config.json` (or remove the hooks from
`settings.json`, or use the **Disable** action in the VS Code status bar). With
it off, Claude Code prompts only in the editor as it did before.

---

## How it works (short version)

`approve.py` picks one of two strategies based on `CLAUDE_CODE_ENTRYPOINT`:

- **VS Code extension** (`claude-vscode`) → the "both-live" path below: return
  `ask` instantly so the native prompt appears, and race it from the phone via a
  detached watcher that injects a keystroke.
- **CLI** (anything else) → **block** in the hook for up to 20 s, send the
  Telegram message, and return the phone's decision directly. No native prompt,
  no keystroke injection — so it's identical on every OS.

The VS Code "both-live" path uses three small processes, coordinated through
state files on disk:

| Piece | Role |
|-------|------|
| `approve.py` | `PreToolUse` hook. Writes a *pending* state file, spawns the watcher, and returns `ask` so the editor prompt appears immediately. (In CLI mode it blocks and decides directly instead.) |
| `dispatcher.py` | **One** per machine. The *only* process that polls Telegram. Routes each tap into the matching prompt's state file. Idle-exits when there's nothing pending. Used by both modes. |
| `watcher.py` | One per prompt (VS Code mode). Sends the Telegram message, then watches its own state file. On a phone tap it injects the keystroke; if you answered in the editor it just stops. |
| `post_tool.py` | `PostToolUse` hook. Marks a prompt "answered" when the tool actually runs, so the watcher knows the editor won. |

A single dispatcher (instead of every watcher polling) is what makes it safe
under bursts — see [IMPLEMENTATION.md](IMPLEMENTATION.md) for the full design,
including the 409-storm and tap-routing problems it solves.

---

## Security

- **Only your chat can approve.** Every callback is checked against your
  configured `chat_id`; taps from anyone else (e.g. a forwarded message) are
  rejected with "Not authorized".
- **Your token stays local.** It lives only in `config.json` (chmod `600`) on
  your machine. It is **git-ignored** and never leaves your computer except in
  calls to Telegram's API.
- **Fail-safe, not fail-open.** If the phone path errors, the prompt falls back
  to the editor. Nothing is auto-approved on failure.
- **Anyone who controls your bot can approve your prompts.** Treat the token
  like a password. If it leaks, revoke it in @BotFather (`/revoke`) and re-run
  `./install.sh`.

---

## Telegram limits & running at scale

- **One machine per bot token.** Telegram's `getUpdates` cursor is global to a
  token; two machines polling the same bot will steal each other's updates. Use
  a separate bot per machine. (The offset file is namespaced per host so the
  conflict is at least obvious in the logs.)
- **~20 messages/min to one chat.** During an agentic burst the tool caps
  itself at 18 sends/min and, past that, sends a single "N approvals pending —
  answer in the editor" digest instead of one message per prompt.
- **Button taps expire.** Telegram only lets a bot answer a tap for ~10 minutes.
  A watcher stops waiting after `watcher_timeout_seconds` (default 600) and
  marks the message expired; late taps get a clean "this prompt expired" reply.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No Telegram message appears | Restart Claude Code (reloads `settings.json`). Check `~/.claude/hooks/tg-approve/tg-approve.log`. |
| "no messages found" during setup | Send your bot a message *before* running setup, then retry. |
| Phone tap doesn't move the editor (macOS) | Grant **Accessibility** permission to VS Code / your terminal in *System Settings → Privacy & Security → Accessibility*. |
| `HTTP 409 Conflict` in the log | Another poller is using the same bot token — run one machine per bot, or kill stray `dispatcher.py`/old `watcher.py` processes. |

Logs live at `~/.claude/hooks/tg-approve/tg-approve.log`.

---

## Platform support

Two run modes, detected automatically via `CLAUDE_CODE_ENTRYPOINT`:

- **VS Code extension panel** — your tap injects a keystroke into the native
  Quick Pick. Per-OS backend (below).
- **Terminal CLI** (any terminal, including VS Code's integrated one and
  JetBrains) — the hook **blocks up to 20 s** waiting for your tap, then returns
  the decision directly. No keystroke injection, so **no per-OS dependency** —
  works the same everywhere.

| Platform | Phone notification | CLI mode (blocking) | VS Code panel (injection) |
|----------|:-:|:-:|:-:|
| macOS | ✅ | ✅ | ✅ AppleScript (needs Accessibility) |
| Linux | ✅ | ✅ | ✅ `xdotool` (X11) |
| Windows | ✅ | ✅ | ✅ PowerShell `SendKeys` (built in) |

The CLI path is fully hands-free on every OS today. For the VS Code panel,
Linux needs `xdotool` installed (`apt install xdotool`) and macOS needs
Accessibility permission.

---

## Uninstall

```bash
rm -rf ~/.claude/hooks/tg-approve
# then remove the tg-approve entries from ~/.claude/settings.json
```

---

## License

[MIT](LICENSE) © 2026 Mrinal Sahai
