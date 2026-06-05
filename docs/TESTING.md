# Testing guide

How to verify `claude-remote-approve` end to end — both the automated logic
suite (no phone needed) and the live phone round-trip — plus the gotchas that
bite if you don't know them.

There are three layers, mirroring the project's test convention:

| Layer | Symbol | Hits a real phone/Telegram? |
|-------|:--:|:--:|
| Logic suite | 🟡 MOCK | No — Telegram + injection are monkeypatched |
| Live round-trip | 🔴 LIVE | Yes — you tap your real phone |
| Log inspection | 🟢 STATIC | No — reads `tg-approve.log` |

---

## 1. 🟡 MOCK suite (fast, deterministic, run on every change)

The mock suite patches `tg.answer_callback`, `tg.inject_decision`,
`tg.edit_message`, and `tg.send_approval_message`, then drives the real
dispatcher/watcher code. It covers:

| Test | What it proves |
|------|----------------|
| `dispatcher_rejects_unauthorized` | A tap from a non-configured `chat_id` is rejected and never routes a decision. |
| `dispatcher_routes_to_correct_prompt` | With two concurrent prompts, a tap for **B** lands on B and leaves **A** untouched (the cannibalisation fix). |
| `dispatcher_acks_unknown_as_expired` | A tap for an unknown/old id gets a clean "expired" reply (no hung spinner). |
| `route_rejects_stale_prompt` | A prompt older than `PROMPT_MAX_AGE_S` won't accept a routed decision. |
| `rate_limit_gate` | The send gate yields 18 `send` → 1 `digest` → rest `suppress` in a burst. |
| `watcher_injects_on_phone_decision` | A `phone_decision` on a pending prompt triggers exactly one keystroke injection. |
| `watcher_stops_on_editor_answer` | If the editor answered first (`status=answered`), the watcher injects **nothing**. |

Run it:

```bash
python3 tests/test_tg_fixes.py
# → ALL MOCK TESTS PASSED
```

> Note: the suite writes/removes `state/test_*.json` and clears the send ledger.
> Run it when no live prompts are pending so the two don't interfere.

---

## 2. 🔴 LIVE round-trip (do this once after install, and after any change to the inject/route path)

### Pre-flight

1. **Kill stale processes** — old watchers from a previous version keep polling
   and will fight the dispatcher:
   ```bash
   pkill -f "tg-approve/watcher.py"; pkill -f "tg-approve/dispatcher.py"
   ```
2. **Clear stale runtime state:**
   ```bash
   cd ~/.claude/hooks/tg-approve
   rm -f state/*.json *.lock tg_send_ledger.json
   ```
3. Have `tail -f ~/.claude/hooks/tg-approve/tg-approve.log` open in a second
   terminal.

### Test A — Allow

Trigger any gated tool (e.g. ask Claude to run `echo hello`). When the prompt
arrives, **tap ✅ Allow on the phone only — don't touch the editor.**

Expect in the log:
```
spawned watcher for <id>: Bash: echo hello
dispatcher: started (pid …)
dispatcher: routed allow -> <id>
inject_decision(allow) -> ok=True
watcher done for <id> (phone)
```
…and the command runs.

### Test B — Deny

Trigger another command. **Tap ⛔ Deny.** The tool call should be **rejected**
(that's success). Log shows `inject_decision(deny) -> ok=True`, `routed deny`.

### Test C — Always (+ bypass)

Trigger a command. **Tap ♾️ Always.** It runs *and* the rule is appended to
`allowlist.json`. Trigger the **same** command again — it should run with **no
prompt and no watcher spawned** (`approve.py` short-circuits via the allowlist).
Verify:
```bash
grep "spawned watcher" tg-approve.log | tail   # no new line for the 2nd call
cat allowlist.json                              # contains the new rule
```

### Test D — Editor wins

Trigger a command and **answer it in the editor** (ignore the phone). The phone
message should update to **"ℹ️ Answered in the editor"** and the log shows
`watcher done … (editor)` — with **no** `inject_decision` line.

### Test E — Concurrent prompts (the important one)

Hard to stage by hand because tool calls are usually sequential. The reliable
way:

- Run an agentic task that fires several gated tools in quick succession, **or**
- In two terminals, run two `claude` sessions and trigger a prompt in each
  within a few seconds.

Then tap them on the phone **in a different order than they arrived**. Each tap
must land on its own command (check each `routed <action> -> <id>` matches the
right summary). This is the live counterpart to
`dispatcher_routes_to_correct_prompt`. You should see **one** `dispatcher:
started` and **zero** `409 Conflict` lines.

---

## 3. Cases to keep in mind (hard-won)

- **Stale old-version processes are the #1 gotcha.** A watcher from a previous
  build keeps long-polling and causes `409` storms that look like a current
  bug. Always kill `watcher.py`/`dispatcher.py` before a clean test.
- **macOS Accessibility permission is required for injection.** If
  `inject_decision -> ok=True` but the editor prompt doesn't move, grant
  Accessibility to VS Code / your terminal in *System Settings → Privacy &
  Security → Accessibility*, then fully restart the app.
- **`409 Conflict` = more than one poller.** Either a stale process, or two
  machines sharing one bot token. One bot per machine.
- **Working directory matters in tests.** `tg-approve.log` lives in the hook
  dir; use absolute paths when grepping from elsewhere.
- **The allowlist persists across tests.** A "Always" tap during testing leaves
  a real rule in `allowlist.json`. Clean it up afterwards or your later tests
  will silently bypass the phone.
- **Don't run the MOCK suite while live prompts are pending** — both touch the
  `state/` dir and the send ledger.
- **Phone taps are destructive in Telegram's queue.** If a test misbehaves and
  you re-tap, you may be acting on a stale `update_id`; clear state and restart
  the dispatcher for a clean slate.
- **Latency budget.** Phone-tap → injection is typically < 1 s (dispatcher
  long-poll returns on the tap; watcher re-reads its state file every 0.3 s). If
  it's seconds-slow, suspect a `409` storm starving the dispatcher's poll.

---

## 4. What "green" looks like

A healthy full pass:

- 🟡 MOCK: `ALL MOCK TESTS PASSED`.
- 🔴 LIVE A–D: each action reflected in the log with the matching
  `routed`/`inject`/`watcher done (…)` lines and the expected tool outcome.
- 🟢 STATIC: exactly **one** `dispatcher: started` for the session and **zero**
  `409 Conflict` lines.
