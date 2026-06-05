// Unit tests for installer.ts — no VS Code needed. Runs with `node --test`.
// installer reads process.env.CLAUDE_CONFIG_DIR each call, so we point it at a
// throwaway temp dir and exercise the real settings-merge / config / allowlist
// logic against the filesystem.
const { test, beforeEach, afterEach } = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const inst = require("../../out/installer.js");

const PY = "/usr/bin/python3"; // any path; we only assert it lands in the command
let tmp;

beforeEach(() => {
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "tg-test-"));
  process.env.CLAUDE_CONFIG_DIR = tmp;
});

afterEach(() => {
  fs.rmSync(tmp, { recursive: true, force: true });
  delete process.env.CLAUDE_CONFIG_DIR;
});

function readSettings() {
  return JSON.parse(fs.readFileSync(path.join(tmp, "settings.json"), "utf8"));
}

test("patchSettings creates Pre+PostToolUse when settings.json is absent", () => {
  const added = inst.patchSettings(PY);
  assert.equal(added.length, 2);
  const s = readSettings();
  assert.ok(s.hooks.PreToolUse[0].hooks[0].command.includes("approve.py"));
  assert.ok(s.hooks.PostToolUse[0].hooks[0].command.includes("post_tool.py"));
  assert.ok(s.hooks.PreToolUse[0].hooks[0].command.startsWith(PY));
});

test("patchSettings preserves the user's existing hooks", () => {
  fs.writeFileSync(
    path.join(tmp, "settings.json"),
    JSON.stringify({
      model: "opus",
      hooks: { PreToolUse: [{ matcher: "Read", hooks: [{ type: "command", command: "echo mine" }] }] },
    })
  );
  inst.patchSettings(PY);
  const s = readSettings();
  assert.equal(s.model, "opus", "unrelated top-level keys kept");
  const cmds = s.hooks.PreToolUse.map((e) => e.hooks[0].command);
  assert.ok(cmds.some((c) => c.includes("echo mine")), "existing hook kept");
  assert.ok(cmds.some((c) => c.includes("approve.py")), "ours appended");
  assert.equal(s.hooks.PreToolUse.length, 2);
});

test("patchSettings is idempotent (no duplicates on re-run)", () => {
  inst.patchSettings(PY);
  const added2 = inst.patchSettings(PY);
  assert.equal(added2.length, 0, "second run adds nothing");
  const s = readSettings();
  assert.equal(s.hooks.PreToolUse.length, 1);
  assert.equal(s.hooks.PostToolUse.length, 1);
});

test("unpatchSettings removes only ours, keeps the rest, prunes empties", () => {
  fs.writeFileSync(
    path.join(tmp, "settings.json"),
    JSON.stringify({
      hooks: { PreToolUse: [{ matcher: "Read", hooks: [{ type: "command", command: "echo mine" }] }] },
    })
  );
  inst.patchSettings(PY);
  const removed = inst.unpatchSettings();
  assert.equal(removed, 2, "removed our Pre + Post entries");
  const s = readSettings();
  assert.equal(s.hooks.PreToolUse.length, 1, "user hook survives");
  assert.ok(s.hooks.PreToolUse[0].hooks[0].command.includes("echo mine"));
  assert.equal(s.hooks.PostToolUse, undefined, "empty PostToolUse pruned");
});

test("writeConfig writes chmod 600 and readConfig round-trips", () => {
  inst.writeConfig({
    bot_token: "t",
    chat_id: "123",
    enabled: true,
    watcher_timeout_seconds: 600,
    poll_interval_seconds: 2,
    vscode_process_name: "Electron",
  });
  const mode = fs.statSync(inst.configPath()).mode & 0o777;
  assert.equal(mode, 0o600, "config.json must be 600");
  const cfg = inst.readConfig();
  assert.equal(cfg.chat_id, "123");
  assert.equal(cfg.bot_token, "t");
});

test("setEnabled flips enabled in place", () => {
  inst.writeConfig({
    bot_token: "t", chat_id: "1", enabled: true,
    watcher_timeout_seconds: 600, poll_interval_seconds: 2, vscode_process_name: "Electron",
  });
  inst.setEnabled(false);
  assert.equal(inst.readConfig().enabled, false);
});

test("allowlist write/read round-trips", () => {
  inst.writeAllowlist(["Bash:git", "Write:*"]);
  assert.deepEqual(inst.readAllowlist(), ["Bash:git", "Write:*"]);
});

test("isConfigured reflects token+chat presence", () => {
  assert.equal(inst.isConfigured(), false);
  inst.writeConfig({
    bot_token: "t", chat_id: "1", enabled: true,
    watcher_timeout_seconds: 600, poll_interval_seconds: 2, vscode_process_name: "Electron",
  });
  assert.equal(inst.isConfigured(), true);
});

test("readConfig returns null when absent", () => {
  assert.equal(inst.readConfig(), null);
});
