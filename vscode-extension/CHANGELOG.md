# Changelog

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
