#!/usr/bin/env bash
#
# Installer for claude-remote-approve.
#
# Copies the hook scripts into ~/.claude/hooks/tg-approve/, registers the
# Pre/PostToolUse hooks in ~/.claude/settings.json (without clobbering existing
# hooks), and walks you through connecting your Telegram bot.
#
# Re-runnable: it skips steps that are already done.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# locate things
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/hooks/tg-approve"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
HOOK_DIR="$CLAUDE_DIR/hooks/tg-approve"
SETTINGS="$CLAUDE_DIR/settings.json"

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
  echo "ERROR: python3 not found on PATH. Install Python 3.8+ and retry." >&2
  exit 1
fi

echo "==> Using python3 at: $PY"
echo "==> Claude config dir: $CLAUDE_DIR"

# ---------------------------------------------------------------------------
# 1. copy hook scripts
# ---------------------------------------------------------------------------
mkdir -p "$HOOK_DIR"
cp "$SRC_DIR"/approve.py "$SRC_DIR"/dispatcher.py "$SRC_DIR"/watcher.py \
   "$SRC_DIR"/post_tool.py "$SRC_DIR"/tg_common.py "$SRC_DIR"/tg_setup.py "$HOOK_DIR/"
chmod +x "$HOOK_DIR"/*.py
echo "==> Installed hook scripts to $HOOK_DIR"

# ---------------------------------------------------------------------------
# 2. register hooks in settings.json (idempotent, preserves existing hooks)
# ---------------------------------------------------------------------------
PY="$PY" HOOK_DIR="$HOOK_DIR" SETTINGS="$SETTINGS" "$PY" - <<'PYEOF'
import json, os

py = os.environ["PY"]
hook_dir = os.environ["HOOK_DIR"]
path = os.environ["SETTINGS"]
matcher = "Bash|Write|Edit|MultiEdit|NotebookEdit|WebFetch"

try:
    with open(path) as f:
        settings = json.load(f)
except (OSError, ValueError):
    settings = {}

hooks = settings.setdefault("hooks", {})

def ensure(event, script):
    cmd = f"{py} {os.path.join(hook_dir, script)}"
    entries = hooks.setdefault(event, [])
    # already registered? (match on the script filename anywhere in the command)
    for entry in entries:
        for h in entry.get("hooks", []):
            if script in h.get("command", ""):
                return False
    entries.append({"matcher": matcher,
                    "hooks": [{"type": "command", "command": cmd}]})
    return True

added = []
if ensure("PreToolUse", "approve.py"):
    added.append("PreToolUse->approve.py")
if ensure("PostToolUse", "post_tool.py"):
    added.append("PostToolUse->post_tool.py")

os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(settings, f, indent=2)

print("==> settings.json: " + (", ".join(added) if added else "already registered"))
PYEOF

# ---------------------------------------------------------------------------
# 3. connect Telegram (skip if already configured)
# ---------------------------------------------------------------------------
CONFIG="$HOOK_DIR/config.json"
if [ -f "$CONFIG" ] && grep -q '"chat_id": "[0-9]' "$CONFIG" 2>/dev/null; then
  echo "==> Telegram already configured ($CONFIG). Skipping setup."
  echo "    (Delete that file and re-run to reconfigure.)"
  exit 0
fi

cat <<'MSG'

================  CONNECT YOUR TELEGRAM BOT  ================
 1. In Telegram, open @BotFather  ->  /newbot  ->  copy the token.
 2. Paste the token below.
 3. Open your new bot and send it ANY message (e.g. "hi").
============================================================
MSG

printf "Paste your bot token: "
read -r TG_TOKEN
if [ -z "$TG_TOKEN" ]; then
  echo "No token entered. Re-run ./install.sh when ready." >&2
  exit 1
fi
printf "%s" "$TG_TOKEN" > "$HOOK_DIR/token.txt"

printf "\nNow send your bot any message in Telegram, then press Enter here... "
read -r _

"$PY" "$HOOK_DIR/tg_setup.py"

echo
echo "==> Done. Restart Claude Code so it reloads settings.json."
echo "    Trigger any tool (e.g. a shell command) and approve it from your phone."
