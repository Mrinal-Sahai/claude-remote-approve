# Changelog

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
