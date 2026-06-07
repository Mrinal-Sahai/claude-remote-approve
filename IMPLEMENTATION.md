# Implementation notes

This document explains **how** `claude-remote-approve` works and, more
importantly, **why** it's built the way it is. The design went through one major
rewrite to survive concurrent prompts; both the old and new shapes are described
so the trade-offs are clear.

---

## 1. The hook contract we're building on

Claude Code lets you register **hooks** — small programs it runs at defined
moments. We use two:

- **`PreToolUse`** — runs *before* a tool executes. It reads the tool call as
  JSON on stdin and may print a JSON decision on stdout:
  ```json
  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
     "permissionDecision": "ask|allow|deny",
     "permissionDecisionReason": "..."}}
  ```
  `allow` runs the tool, `deny` blocks it, `ask` shows the normal editor prompt.
- **`PostToolUse`** — runs *after* a tool executes. We use it purely as a signal
  that "the tool actually ran, so the user must have approved it in the editor."

Both are registered in `~/.claude/settings.json` with a `matcher` selecting
which tools they fire for (`Bash|PowerShell|Write|Edit|MultiEdit|NotebookEdit|WebFetch`).
`PowerShell` is a distinct tool name on native Windows (separate from `Bash`,
which routes through Git Bash) — listing both ensures shell commands are gated
on every OS.

The key constraint: **a hook is a short-lived process.** It can't sit and wait
for a phone tap — that would block Claude. So the real work happens in a
*detached* background process that outlives the hook.

---

## 2. The "both live" idea

We never replace the editor prompt — we *race* it.

1. `approve.py` (PreToolUse) returns `ask` almost immediately, so the editor
   Quick Pick appears with no perceptible delay.
2. In parallel, a background process sends the Telegram message.
3. Whoever answers first wins:
   - **Editor:** you pick an option → the tool runs → `PostToolUse` fires.
   - **Phone:** you tap a button → we inject the equivalent keystroke into the
     still-open editor prompt.

This means the feature is **purely additive**: if Telegram is down, your token
is wrong, or you just ignore your phone, Claude Code behaves exactly as it did
before. Fail-safe by construction.

---

## 3. Why a keystroke, not an API?

Claude Code's permission Quick Pick is rendered inside VS Code's **Chromium web
layer**. It is *invisible* to the macOS Accessibility API — you cannot find or
click its buttons programmatically, and you cannot reliably detect whether it's
open by inspecting the UI tree. We learned this the hard way (an entire earlier
approach based on `osascript` reading text fields was a dead end).

What *does* work: the Quick Pick responds to plain keystrokes when VS Code is
frontmost.

- **Allow / Always** → `Return` (key code 36) — accepts the highlighted option.
- **Deny** → `Escape` (key code 53) — dismisses the prompt, which Claude treats
  as a denial.

So `inject_decision()` brings VS Code to the front and sends one key event via
`osascript`. That's the whole injection mechanism — deliberately dumb and
robust.

Because we can't *see* the Quick Pick, we can't poll the UI to know if it's
still open. Instead we track the prompt's lifecycle in a **state file** (§5) and
only ever inject while that file says `status == "pending"` and is fresh
(< 90 s). Fail-closed: if we're unsure, we don't inject.

### 3.1 Cross-platform injection

`inject_decision()` dispatches on `sys.platform`, but the keystrokes are the
same everywhere — `Return` to accept, `Escape` to deny:

| OS | Backend | Notes |
|----|---------|-------|
| macOS | `osascript` → System Events | Needs Accessibility permission. Brings VS Code frontmost first. |
| Windows | PowerShell `[System.Windows.Forms.SendKeys]::SendWait` | No dependency; sends to the foreground window. |
| Linux | `xdotool key --clearmodifiers` | X11; requires `xdotool` on PATH. |

The macOS branch is unchanged from the original single-platform implementation;
Windows/Linux are additive and never touch the macOS path.

### 3b. Two run modes: injection vs blocking

Injection only makes sense when there's a **VS Code Quick Pick** to drive. In a
plain terminal there's a y/N prompt instead, which AppleScript/SendKeys/xdotool
can't reliably answer. So `approve.py` chooses a strategy up front:

```
mode = (CLAUDE_CODE_ENTRYPOINT == "claude-vscode") ? "inject" : "block"
```

This is deliberately **fail-safe toward blocking**: only the exact string
`claude-vscode` takes the injection path. Every other entrypoint — the terminal
CLI, the integrated terminal, a JetBrains plugin, future frontends — uses the
blocking path, which needs no UI at all.

**Blocking mode** (`handle_cli`) is simpler than the both-live design:

1. Tag the state file with an explicit `deadline` (now + 20 s).
2. Ensure the dispatcher is running; send the Telegram message.
3. Poll our own state file until `phone_decision` is set, then `emit()` the
   decision **directly** as the hook's stdout — Claude proceeds with no prompt.
4. If the deadline passes, `emit("ask")` so the normal terminal prompt takes
   over. Nothing is auto-approved on timeout.

The block is capped at 20 s and the PreToolUse hook is registered with a 35 s
`timeout` so Claude never kills it mid-wait. Because the hook *is* still alive
the whole time, the dispatcher's stale-prompt guard had to learn about the
`deadline` field: `route_phone_decision()` and `count_pending_states()` honor an
explicit `deadline` when present, and otherwise fall back to the original 90 s
window — so VS Code prompts (no `deadline` key) behave exactly as before.

**Instant disable.** `approve.py` checks `TG_APPROVE_OFF` before anything else
and exits `0` (normal local prompt) if it's set — a zero-cost per-shell kill
switch for CLI use, independent of the persistent `enabled` config flag.

---

## 4. The architecture, and the bug that forced the rewrite

### 4.1 First design: every watcher polls (broken under load)

Originally each pending prompt spawned a watcher, and **each watcher polled
Telegram** (`getUpdates`) for taps. With one prompt at a time this worked. With
concurrent prompts it failed two ways:

1. **HTTP 409 storms.** Telegram allows only **one** in-flight `getUpdates` per
   bot token. N watchers polling at once → constant `409 Conflict`. A file-lock
   band-aid didn't fully fix it, because the non-lock-holders fell back to
   zero-timeout polls that *still* hit Telegram concurrently.

2. **Tap cannibalisation (the serious one).** `getUpdates` is *destructive*:
   reading an update with offset `N+1` acknowledges everything ≤ `N`. So if
   watcher-A polled and received the tap meant for watcher-B, A would advance
   the offset and **discard B's tap** (acking it as "not mine / expired").
   B never saw its own approval. Concurrent phone approval was silently broken.

This only shows up under concurrency — exactly the agentic-burst case the tool
is *for* — which is why it survived single-prompt testing.

### 4.2 Current design: one dispatcher, N poll-less watchers

```
approve.py (PreToolUse, per call)
   ├─ write state/<id>.json  {status: pending, ...}
   ├─ spawn watcher.py <id>   (detached)
   └─ emit "ask"  → editor prompt appears

watcher.py (one per prompt, NO Telegram polling)
   ├─ ensure_dispatcher()         # spawn the singleton if not running
   ├─ send Telegram message (rate-gated)  → store message_id locally
   └─ loop on its OWN state file:
        phone_decision set & pending → inject keystroke, edit msg, done
        status == answered           → editor won, done
        deadline passed              → expire, done
   └─ delete state/<id>.json

dispatcher.py (ONE per machine — flock singleton)
   └─ loop: getUpdates  (the only poller → no 409, no cannibalisation)
        for each tap:
          reject if from-id ≠ chat_id            # security
          route_phone_decision(id, action)       # write into THAT prompt's file
          ack the phone (verb, or "expired")
        exit after 30 s with zero pending prompts

post_tool.py (PostToolUse)
   └─ mark matching pending state file → status: answered  (editor won)
```

Why this fixes both problems:

- **Single poller ⇒ no 409.** Only `dispatcher.py` ever calls `getUpdates`, and
  a `flock` singleton guarantees only one dispatcher runs per machine. A second
  one fails the non-blocking lock acquire and exits.
- **Routing, not consuming ⇒ no cannibalisation.** The dispatcher reads *all*
  updates and writes each tap into the **state file of the prompt it belongs
  to** (`route_phone_decision`). A tap for B can never be eaten by A's watcher,
  because watchers no longer read the Telegram stream at all — they only read
  their own file.

The dispatcher is ephemeral: it starts on demand and idle-exits after 30 s with
nothing pending, so there's no long-lived daemon to manage.

---

## 5. State files: the coordination substrate

Everything is coordinated through one small JSON file per prompt in
`state/<decision_id>.json`. `decision_id` is `"<ms-time><pid>"` in hex — unique
per call.

```json
{
  "tool_name": "Bash",
  "tool_input": {"command": "git push"},
  "summary": "Bash: git push",
  "allow_rule": "Bash:git",
  "status": "pending",          // pending → answered (by post_tool)
  "created": 1733460000.0,
  "phone_decision": "allow",    // written by dispatcher on a tap
  "phone_decided_at": 1733460005.0
}
```

The lifecycle is a tiny state machine:

```
            approve.py writes
                  │
                  ▼
            ┌───────────┐  dispatcher routes tap   ┌──────────────────┐
            │  pending  │ ───────────────────────▶ │ pending +        │
            │           │                          │ phone_decision   │
            └─────┬─────┘                          └────────┬─────────┘
   post_tool      │ (editor answered)                       │ watcher injects
   marks          ▼                                         ▼
            ┌───────────┐                          keystroke → tool runs
            │ answered  │                          watcher deletes file
            └───────────┘
```

The watcher checks `phone_decision` **only while `status == pending`**, so if
the editor already answered (status flipped to `answered` by `post_tool.py`),
the watcher will *not* inject a stray keystroke. That ordering is the guard
against the "double answer" race.

---

## 6. Distribution-scale hardening

These are the things that don't matter for one user on one machine but bite once
the tool is widely used or driven hard:

| Concern | Mitigation | Where |
|---------|-----------|-------|
| Anyone could approve via a forwarded message | Reject callbacks whose `from.id` ≠ configured `chat_id` | `dispatcher._handle_callback` |
| Agentic burst trips Telegram's ~20 msg/min cap | Sliding-window gate: ≤ 18 sends/min, then a single digest, then suppress (editor-only). Coordinated across watchers via `flock` on a shared ledger | `tg_common.reserve_send_slot` |
| Two machines, one bot token, stolen updates | Offset file namespaced per hostname (`tg_offset_<host>.txt`) + documented "one machine per bot" | `dispatcher.py` |
| Tap on an old/expired prompt hangs the phone spinner | Always `answerCallbackQuery`; unknown/stale ids get a clean "expired" reply | `dispatcher._handle_callback` |
| Token on disk in plaintext | `config.json` is `chmod 600` and git-ignored; setup deletes the temporary `token.txt` | `tg_common.save_config`, `tg_setup.py` |

---

## 7. File-by-file

| File | Lines of responsibility |
|------|--------------------------|
| `tg_common.py` | Config/allowlist IO, Telegram API wrappers, the rate-limit ledger, state-file IO + `route_phone_decision`, `inject_decision`, `quickpick_open`. |
| `approve.py` | PreToolUse: allowlist short-circuit, write state; VS Code → spawn watcher + emit `ask`; CLI → `handle_cli` (block up to 20 s, emit decision directly). |
| `dispatcher.py` | The singleton poller: long-poll `getUpdates`, auth-check, route taps, idle-exit. |
| `watcher.py` | Per-prompt: rate-gated send, poll-less wait on own state file, keystroke injection, message edits, cleanup. |
| `post_tool.py` | PostToolUse: flip matching pending prompt to `answered`. |
| `tg_setup.py` | One-time: token → auto-detect chat_id → write `config.json` → test message. |

---

## 8. Known limitations / future work

- **One machine per bot token.** A shared backend (or webhooks with a tiny
  relay) would lift this, at the cost of running a server.
- **Digest is per-machine, not a true cross-prompt batch.** Under extreme
  bursts you get one digest + editor-only prompts rather than N individual
  buttoned messages. That's a deliberate trade to stay under the rate cap.
- **Linux injection requires X11.** `xdotool` doesn't work on Wayland. CLI
  blocking mode (which needs no injection) is the recommended path on Wayland.
- **No end-to-end encryption beyond Telegram's.** Approvals traverse Telegram's
  servers. Don't use this for prompts whose *summary text* is itself sensitive.
