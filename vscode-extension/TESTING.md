# Extension e2e testing guide

I (the author tooling) can build, type-check, and package the extension into a
`.vsix`, but I **cannot drive the VS Code GUI** — launching the Extension
Development Host, clicking the status bar, typing into input boxes, reading
notification toasts. Those steps are inherently manual. This guide is the
checklist to run them yourself, plus the product-level cases to watch.

The underlying *engine* (Python hooks: phone tap → editor) has its own guide in
[../docs/TESTING.md](../docs/TESTING.md) — run that first so you know the engine
works; this guide focuses on the **extension wrapper** (setup, settings patching,
status bar, secret storage).

---

## 0. Two ways to run it

### A. Extension Development Host (fastest dev loop)
```bash
cd vscode-extension
npm install
npm run compile
code .          # open the extension folder in VS Code
# press F5  → "Run Extension" → a new [Extension Development Host] window opens
```
The new window has your extension loaded from source. Reload it with
`Cmd+R` after each `npm run compile`.

### B. Real install from a packaged .vsix (closest to what users get)
```bash
cd vscode-extension
npm run compile
npx @vscode/vsce package --allow-missing-repository
code --install-extension claude-remote-approve-0.1.0.vsix
# fully quit and reopen VS Code
```
Use **B** for the final pass — it exercises the real packaged scripts/ bundle,
not your working tree.

> ⚠️ Test with a **throwaway bot** (a second @BotFather bot), not your daily
> one — setup sends a real message and reads `getUpdates`, which consumes
> pending updates on that bot.

---

## 1. Setup flow

| # | Step | Expected |
|---|------|----------|
| 1.1 | Fresh install, first activation | One-time toast: "Approve Claude Code prompts from your phone?" with **Set up now / Later**. |
| 1.2 | Run **Telegram Approve: Setup**, paste a **valid** token | Progress: "Validating…" → "Connected to @yourbot. Detecting your chat…". |
| 1.3 | Before messaging the bot | Modal: "Open your bot … send it any message". |
| 1.4 | Message the bot, click **I've sent it** | Proceeds; writes config; installs hooks; shows "Connected to @yourbot. Reload window". |
| 1.5 | Click **Reload Window** | Window reloads; hooks now active. |
| 1.6 | Paste an **invalid** token (e.g. `123:bad`) | Error toast "Invalid token: …"; nothing written. |
| 1.7 | Valid token but **never message** the bot, click "I've sent it" 5× | After retries: "Couldn't detect your chat…"; no config written. |

**Verify on disk after 1.5:**
```bash
ls -l ~/.claude/hooks/tg-approve/config.json     # mode -rw------- (600)
cat ~/.claude/hooks/tg-approve/config.json        # bot_token + chat_id present
python3 -c "import json;print(json.load(open('$HOME/.claude/settings.json'))['hooks'].keys())"
```
Expect `PreToolUse` and `PostToolUse` present, each pointing at
`approve.py` / `post_tool.py`, AND any hooks you already had still present.

---

## 2. settings.json merge safety (critical — don't clobber user config)

| # | Setup | Expected |
|---|-------|----------|
| 2.1 | Pre-seed `~/.claude/settings.json` with an unrelated hook + other keys | After setup, your hook + keys are **still there**; ours are appended. |
| 2.2 | Run setup **twice** | Second run does **not** duplicate the Pre/PostToolUse entries (idempotent). |
| 2.3 | `settings.json` is malformed JSON | Setup overwrites with a valid file containing only our hooks (document this — back up first). |
| 2.4 | No `~/.claude/settings.json` at all | Created fresh with just our hooks. |

```bash
# 2.2 check: each script referenced exactly once
grep -c approve.py    ~/.claude/settings.json    # → 1
grep -c post_tool.py  ~/.claude/settings.json    # → 1
```

---

## 3. Status bar + commands

| # | State | Expected status-bar text | Click menu |
|---|-------|--------------------------|------------|
| 3.1 | Not configured | `$(rocket) Telegram: setup` | launches setup |
| 3.2 | Configured + enabled | `$(broadcast) Telegram: on` | Disable / Allowlist / Reconnect / Open log |
| 3.3 | Configured + disabled | `$(circle-slash) Telegram: off` | Enable / … |
| 3.4 | Toggle off then on | text + `config.json` `enabled` flips; takes effect on the next prompt | |
| 3.5 | **Open log** with no log yet | "No log yet…" info | |
| 3.6 | **Open log** after a prompt | opens `tg-approve.log` in editor | |
| 3.7 | **Uninstall hooks → Remove hooks only** | our entries gone from `settings.json`; existing hooks kept; `config.json` retained | |
| 3.8 | **Uninstall hooks → Remove everything** | `~/.claude/hooks/tg-approve` deleted; SecretStorage token cleared; status bar reverts to "setup" | |

---

## 4. Allowlist manager

| # | Step | Expected |
|---|------|----------|
| 4.1 | With empty allowlist, run **Manage allowlist** | "No 'Always' rules saved yet." |
| 4.2 | Trigger a tool, tap **♾️ Always** on phone | `allowlist.json` gains a rule (e.g. `Bash:git`). |
| 4.3 | Run **Manage allowlist**, check a rule, confirm | "Removed 1 rule(s)…"; rule gone from `allowlist.json`. |
| 4.4 | Re-trigger that tool | Prompts again (no longer bypassed). |

---

## 5. SecretStorage

| # | Step | Expected |
|---|------|----------|
| 5.1 | After setup, run **Reconnect** | Token input box is **pre-filled** (masked) from SecretStorage. |
| 5.2 | Inspect | Token is in the OS keychain (VS Code SecretStorage) **and** in `config.json` (600). Both by design — see README. |

---

## 6. Full chain (extension + engine together)

This is the real money path. After setup + reload:

1. In Claude Code, trigger a gated tool (e.g. a shell command).
2. Phone gets the message → tap **✅ Allow** → command runs.
3. Confirm via `~/.claude/hooks/tg-approve/tg-approve.log`:
   `dispatcher: routed allow` → `inject_decision(allow) ok` → `watcher done (phone)`.

(Then repeat Deny / Always / editor-wins exactly as in
[../docs/TESTING.md](../docs/TESTING.md) §2.)

---

## 7. Edge cases to keep in mind (product-level)

- **Python missing / not on PATH.** Setup must fail with a clear "python3 not
  found" message, not a silent crash. Test by temporarily renaming python3.
- **`~/.claude` doesn't exist** (user never ran Claude Code). Installer should
  `mkdir -p` it. Verify config + settings get created.
- **Telegram unreachable** (offline, or token revoked mid-use). `getMe` should
  error cleanly during setup; at runtime a failed send must not block the editor
  prompt (engine falls back).
- **Secrets never logged.** Grep the log and the Output panel — the bot token
  must never appear. (`grep -i "$(your token prefix)" ~/.claude/hooks/tg-approve/tg-approve.log` → empty.)
- **Reload requirement.** Claude Code only re-reads `settings.json` on
  reload/restart. The extension prompts for it; verify hooks don't fire until
  then.
- **Multiple VS Code windows.** Each window activates the extension, but the
  Python dispatcher is a per-machine singleton (flock) — confirm only one
  `dispatcher: started` regardless of window count.
- **macOS Accessibility.** Without it, `inject_decision` returns ok but the
  keystroke doesn't land. The extension can't grant it — document the manual
  step. (System Settings → Privacy & Security → Accessibility → enable VS Code.)
- **Non-macOS.** Notifications + buttons work; injection doesn't. The phone tap
  is recorded but you still answer in the editor. Setup should still complete.
- **Uninstall.** Removing the extension does **not** remove the hooks (they live
  in `~/.claude`). Document the manual cleanup (delete `hooks/tg-approve` and the
  `settings.json` entries). Consider an "Uninstall hooks" command in a future
  version.
- **Bot token rotation.** After `/revoke` in BotFather, Reconnect with the new
  token must overwrite both SecretStorage and `config.json`.

---

## 8. Automated tests (wired up — run these)

Two suites ship with the extension:

### Unit (`npm run test:unit`) — no VS Code, fast
Drives the real `installer.ts` against a temp `CLAUDE_CONFIG_DIR` using Node's
built-in test runner. Covers the riskiest logic:
- `patchSettings` creates Pre/PostToolUse, **preserves existing hooks**, is
  **idempotent** (no duplicates on re-run).
- `unpatchSettings` removes only ours, keeps the rest, prunes empties.
- `writeConfig` is **chmod 600**; `readConfig` round-trips; `setEnabled` flips.
- allowlist read/write; `isConfigured` logic.

```bash
npm run test:unit     # → 9 passing
```

### Integration (`npm run test:integration`) — real VS Code
Uses [`@vscode/test-electron`](https://github.com/microsoft/vscode-test) to
download and launch VS Code, load the extension, and assert it activates and
registers all commands. Needs a display (use `xvfb-run` on headless Linux CI).

```bash
npm run test:integration   # downloads VS Code, → 2 passing
```

Config: [`.vscode-test.mjs`](.vscode-test.mjs). Tests:
[`src/test/suite/`](src/test/suite/). The manual checklist (§1–§7) still owns the
UI-flow paths that can't be asserted programmatically (input boxes, toasts,
keystroke injection).

---

## 9. Release sign-off checklist

- [ ] §1 setup happy path + both failure paths
- [ ] §2 settings merge: existing hooks preserved, idempotent, no duplicates
- [ ] §3 status bar reflects all three states + toggle works
- [ ] §4 allowlist add (phone) + remove (UI)
- [ ] §6 full chain: allow / deny / always / editor-wins
- [ ] §7 python-missing + telegram-down handled gracefully
- [ ] token absent from logs/output
- [ ] `config.json` is mode 600
- [ ] tested from a packaged `.vsix` (method B), not just F5
