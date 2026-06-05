// Filesystem side of the extension: install hook scripts, patch settings.json,
// write config.json (chmod 600), and read/flip runtime state.
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { execFileSync } from "child_process";

const HOOK_FILES = ["approve.py", "dispatcher.py", "watcher.py", "post_tool.py", "tg_common.py", "tg_setup.py"];
const MATCHER = "Bash|Write|Edit|MultiEdit|NotebookEdit|WebFetch";

export function claudeDir(): string {
  return process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
}

export function hookDir(): string {
  return path.join(claudeDir(), "hooks", "tg-approve");
}

export function configPath(): string {
  return path.join(hookDir(), "config.json");
}

export function allowlistPath(): string {
  return path.join(hookDir(), "allowlist.json");
}

export function logPath(): string {
  return path.join(hookDir(), "tg-approve.log");
}

/** Resolve an absolute python3 path for the hook command in settings.json. */
export function findPython(): string {
  for (const cmd of ["python3", "python"]) {
    try {
      const out = execFileSync(cmd, ["-c", "import sys; print(sys.executable)"], {
        encoding: "utf8",
        timeout: 5000,
      }).trim();
      if (out) {
        return out;
      }
    } catch {
      /* try next */
    }
  }
  throw new Error("python3 not found on PATH. Install Python 3.8+ and retry.");
}

/** Copy the bundled hook scripts into ~/.claude/hooks/tg-approve. */
export function installHooks(extensionPath: string): void {
  const src = path.join(extensionPath, "scripts");
  const dst = hookDir();
  fs.mkdirSync(dst, { recursive: true });
  for (const f of HOOK_FILES) {
    fs.copyFileSync(path.join(src, f), path.join(dst, f));
    try {
      fs.chmodSync(path.join(dst, f), 0o755);
    } catch {
      /* best effort */
    }
  }
}

interface HookEntry {
  matcher?: string;
  hooks?: { type: string; command: string }[];
}

/**
 * Register Pre/PostToolUse hooks in settings.json without clobbering existing
 * hooks. Idempotent: skips an event if our script is already referenced.
 * Returns the list of events it added.
 */
export function patchSettings(python: string): string[] {
  const settingsPath = path.join(claudeDir(), "settings.json");
  let settings: any = {};
  try {
    settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
  } catch {
    settings = {};
  }
  settings.hooks = settings.hooks || {};
  const added: string[] = [];

  const ensure = (event: string, script: string) => {
    const cmd = `${python} ${path.join(hookDir(), script)}`;
    const entries: HookEntry[] = (settings.hooks[event] = settings.hooks[event] || []);
    const already = entries.some((e) => (e.hooks || []).some((h) => (h.command || "").includes(script)));
    if (already) {
      return;
    }
    entries.push({ matcher: MATCHER, hooks: [{ type: "command", command: cmd }] });
    added.push(`${event} → ${script}`);
  };

  ensure("PreToolUse", "approve.py");
  ensure("PostToolUse", "post_tool.py");

  fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
  fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2));
  return added;
}

export interface HookConfig {
  bot_token: string;
  chat_id: string;
  enabled: boolean;
  watcher_timeout_seconds: number;
  poll_interval_seconds: number;
  vscode_process_name: string;
}

const DEFAULT_CONFIG: HookConfig = {
  bot_token: "",
  chat_id: "",
  enabled: true,
  watcher_timeout_seconds: 600,
  poll_interval_seconds: 2,
  vscode_process_name: "Electron",
};

export function readConfig(): HookConfig | null {
  try {
    return { ...DEFAULT_CONFIG, ...JSON.parse(fs.readFileSync(configPath(), "utf8")) };
  } catch {
    return null;
  }
}

/** Write config.json with chmod 600 (the Python hooks read this). */
export function writeConfig(cfg: HookConfig): void {
  fs.mkdirSync(hookDir(), { recursive: true });
  fs.writeFileSync(configPath(), JSON.stringify(cfg, null, 2));
  try {
    fs.chmodSync(configPath(), 0o600);
  } catch {
    /* non-POSIX */
  }
}

export function setEnabled(enabled: boolean): void {
  const cfg = readConfig();
  if (cfg) {
    cfg.enabled = enabled;
    writeConfig(cfg);
  }
}

export function readAllowlist(): string[] {
  try {
    const data = JSON.parse(fs.readFileSync(allowlistPath(), "utf8"));
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export function writeAllowlist(rules: string[]): void {
  fs.mkdirSync(hookDir(), { recursive: true });
  fs.writeFileSync(allowlistPath(), JSON.stringify(rules, null, 2));
}

export function isConfigured(): boolean {
  const cfg = readConfig();
  return !!(cfg && cfg.bot_token && cfg.chat_id);
}
