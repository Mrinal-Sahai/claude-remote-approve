#!/usr/bin/env python3
"""PreToolUse hook: route permission prompts to Telegram (both-live design).

Flow:
  1. Read the tool call from stdin.
  2. If disabled or already allow-listed -> decide instantly (no phone).
  3. Otherwise: spawn a detached watcher (Telegram + keystroke injection),
     then return "ask" so the native VS Code Quick Pick appears immediately.
     Whoever answers first wins -- you in the editor, or your phone (the
     watcher injects the keystroke for you).

Returning "ask" ends this hook; the watcher lives on independently.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_common as tg  # noqa: E402


def emit(decision, reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        sys.exit(0)  # can't parse -> let Claude handle normally

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    cfg = tg.load_config()
    if not cfg.get("enabled") or not cfg.get("bot_token") or not cfg.get("chat_id"):
        sys.exit(0)  # feature off / unconfigured -> normal prompt

    if tg.is_allowlisted(tool_name, tool_input):
        emit("allow", "tg-approve: matched saved 'always' rule")
        return

    summary = tg.summarize(tool_name, tool_input)
    decision_id = f"{int(time.time() * 1000):x}{os.getpid():x}"
    tg.write_state(decision_id, {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "summary": summary,
        "allow_rule": tg.allow_rule_for(tool_name, tool_input),
        "status": "pending",
        "created": time.time(),
    })

    watcher = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watcher.py")
    try:
        devnull = open(os.devnull, "wb")
        subprocess.Popen(
            [sys.executable, watcher, decision_id],
            stdin=subprocess.DEVNULL, stdout=devnull, stderr=devnull,
            start_new_session=True, close_fds=True,
        )
        tg.log(f"spawned watcher for {decision_id}: {summary}")
    except Exception as e:  # noqa: BLE001
        tg.log(f"failed to spawn watcher: {e}")
        sys.exit(0)  # fall back to a normal prompt

    # Hand control to the native Quick Pick; the watcher races it from the phone.
    emit("ask", "tg-approve: sent to phone; answer here or there")


if __name__ == "__main__":
    main()
