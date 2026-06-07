# Changelog

## 0.2.5

- **Fix: quote hook command paths.** The `settings.json` hook command embedded
  the Python and script paths unquoted. On Windows, a space anywhere in the path
  (e.g. a username like `Mrinal Sahai`) truncated the command and the hook
  failed silently. Both paths are now quoted — harmless on macOS/Linux (sh
  parses them identically), correct on Windows.
- `patchSettings` now upgrades an already-registered entry **in place** (command
  + matcher + timeout), so existing installs pick up the quoting and PowerShell
  matcher via the auto-sync, without duplicating entries.

## 0.2.4

- **Auto-sync hooks on update.** After the extension updates, the on-disk hook
  scripts are now refreshed automatically on the next launch — no need to re-run
  Setup. Your bot token and chat id are preserved (they live in config.json and
  are never touched); only the Python scripts and the idempotent settings.json
  entries are refreshed. A one-time toast confirms it.

## 0.2.3

- **Fix: Windows compatibility.** The hooks imported `fcntl` (Unix-only) at the
  top of `tg_common.py` and `dispatcher.py`, which crashed the entire hook on
  Windows before it could run. File locking is now cross-platform — `fcntl` on
  macOS/Linux (unchanged), `msvcrt` on Windows.
- Detached background processes now spawn with `CREATE_NO_WINDOW` on Windows so
  no console window flashes on each approval. On macOS/Linux this is a literal
  `0` (no change — `start_new_session` still does the detaching).
- macOS/Linux behaviour is byte-identical: every Windows-specific branch is
  gated and never executes on POSIX.

## 0.2.2

- **Windows PowerShell coverage.** Native Windows exposes a separate
  `PowerShell` tool (distinct from `Bash`, which routes through Git Bash).
  The hook matcher now includes `PowerShell`, so PowerShell commands are gated
  and sent to your phone like any other command. Re-running setup upgrades the
  matcher on existing installs in place (only the matcher, command untouched).
- `summarize()` and the "Always" allowlist now understand `PowerShell` calls
  (shown as `PowerShell: <command>`, allow-rule `PowerShell:<firstword>`).

## 0.2.1

- Setup wizard now offers a one-click **"Open @BotFather"** button before the
  token prompt, so you don't have to leave the flow to find it. Pick "I already
  have a token" to skip straight to pasting.

## 0.2.0

- **CLI support (hands-free everywhere).** When Claude Code runs in a terminal
  (`CLAUDE_CODE_ENTRYPOINT` ≠ `claude-vscode`), the hook now *blocks* up to 20 s
  waiting for your phone tap and returns the decision directly — no terminal
  prompt, no keystroke injection. Works on macOS, Windows, and Linux identically.
- **Cross-platform keystroke injection** for the VS Code panel path: macOS
  (AppleScript, unchanged), Windows (PowerShell `SendKeys`), Linux (`xdotool`).
- **Instant CLI kill switch:** `export TG_APPROVE_OFF=1` makes the hook step
  aside for that shell session (normal local prompts); `unset` to re-enable.
- PreToolUse hook now registered with a 35 s `timeout` so the CLI block is never
  cut short. VS Code extension behavior is unchanged (the hook returns instantly
  there, and the macOS injection path is byte-identical).

## 0.1.0

- Initial release.
- Guided setup: validate bot token, auto-detect chat id, write config, install
  hooks, patch `settings.json`, send a test message.
- Status-bar control: enable/disable, manage allowlist, reconnect, open log,
  uninstall.
- **Uninstall** command: removes our `settings.json` entries (preserving other
  hooks); optionally wipes scripts, config, and the SecretStorage token.
- Bundles the `claude-remote-approve` Python hooks (single-dispatcher engine).
- Token stored in `config.json` (chmod 600) and mirrored to SecretStorage.
- Test suites: 9 unit (`test:unit`, no VS Code) + 2 integration
  (`test:integration`, real VS Code via @vscode/test-electron).
