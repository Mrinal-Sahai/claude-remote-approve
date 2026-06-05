# Changelog

## 0.1.0

- Initial release.
- Guided setup: validate bot token, auto-detect chat id, write config, install
  hooks, patch `settings.json`, send a test message.
- Status-bar control: enable/disable, manage allowlist, reconnect, open log.
- Bundles the `claude-remote-approve` Python hooks (single-dispatcher engine).
- Token stored in `config.json` (chmod 600) and mirrored to SecretStorage.
