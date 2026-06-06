#!/usr/bin/env python3
"""PreToolUse hook: route permission prompts to Telegram.

Two strategies, chosen by how Claude Code is running:

  VS Code extension (CLAUDE_CODE_ENTRYPOINT=claude-vscode) -- "both-live":
    spawn a detached watcher (Telegram + keystroke injection), then return
    "ask" so the native Quick Pick appears immediately. Whoever answers first
    wins -- you in the editor, or your phone (the watcher injects the keystroke).

  CLI (terminal) -- "blocking":
    there is no Quick Pick to inject into, so we send the Telegram message and
    block right here until the phone taps, then return the decision directly.
    No native y/N prompt is shown unless the phone times out.

Common flow: read the tool call; if disabled or allow-listed, decide instantly.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_common as tg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHER = os.path.join(HERE, "watcher.py")
DISPATCHER = os.path.join(HERE, "dispatcher.py")
VERBS = {"allow": "Allowed", "deny": "Denied", "always": "Always-allowed"}
# CLI mode blocks the terminal while waiting for a phone tap, so keep the wait
# short and fall back to the native prompt quickly. Max 20s.
CLI_MAX_BLOCK_S = 20

# Per-session kill switch: set this env var in a shell to make the hook get out
# of the way instantly (normal local prompts), without editing config or files.
DISABLE_ENV = "TG_APPROVE_OFF"


def emit(decision, reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


def _spawn_detached(argv):
    devnull = open(os.devnull, "wb")
    subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL, stdout=devnull, stderr=devnull,
        start_new_session=True, close_fds=True,
    )


def _cleanup(decision_id):
    try:
        os.remove(tg.state_path(decision_id))
    except OSError:
        pass


def handle_cli(cfg, decision_id, summary, allow_rule):
    """CLI mode: block until the phone answers and return the decision directly.

    No keystroke injection and no native prompt -- Claude simply waits on this
    hook. If the phone doesn't answer within the window we emit "ask" so the
    normal terminal prompt takes over.
    """
    block_s = min(cfg.get("watcher_timeout_seconds", 600), CLI_MAX_BLOCK_S)
    deadline = time.time() + block_s

    # Tag the prompt with an explicit answerable window so the dispatcher keeps
    # routing taps (and stays alive) for the whole block, not just 90s.
    st = tg.read_state(decision_id)
    st["deadline"] = deadline
    tg.write_state(decision_id, st)

    # Make sure the singleton dispatcher is polling Telegram for our callback.
    try:
        _spawn_detached([sys.executable, DISPATCHER])
    except Exception as e:  # noqa: BLE001
        tg.log(f"cli: failed to spawn dispatcher: {e}")

    # Send the per-prompt approval message (rate-gated, same gate as the watcher).
    mode = tg.reserve_send_slot()
    if mode != "send":
        if mode == "digest":
            tg.send_digest(cfg)
        # No per-prompt button was sent -> let the terminal prompt handle it.
        _cleanup(decision_id)
        emit("ask", "tg-approve: rate-limited; answer in the terminal")
        return

    try:
        message_id = tg.send_approval_message(cfg, decision_id, summary)
    except Exception as e:  # noqa: BLE001
        tg.log(f"cli send_approval_message failed: {e}")
        _cleanup(decision_id)
        emit("ask", "tg-approve: send failed; answer in the terminal")
        return

    tg.log(f"cli blocking for {decision_id}: {summary}")
    while time.time() < deadline:
        action = tg.read_state(decision_id).get("phone_decision")
        if action:
            if action == "always":
                tg.add_allow_rule(allow_rule)
            tg.edit_message(cfg, message_id,
                            f"✅ *{VERBS.get(action, action)} from phone*\n\n`{summary}`")
            _cleanup(decision_id)
            emit("deny" if action == "deny" else "allow", f"tg-approve: {action} from phone")
            tg.log(f"cli done for {decision_id} ({action})")
            return
        time.sleep(0.4)

    # Phone didn't answer in time -> fall back to the native terminal prompt.
    tg.edit_message(cfg, message_id, f"⌛ *Expired* — answer in the terminal\n\n`{summary}`")
    _cleanup(decision_id)
    emit("ask", "tg-approve: phone timeout; answer in the terminal")
    tg.log(f"cli timeout for {decision_id}")


def main():
    # Instant per-session disable: `export TG_APPROVE_OFF=1` in the shell that
    # runs `claude` -> the hook steps aside and you get normal local prompts.
    if os.environ.get(DISABLE_ENV):
        sys.exit(0)

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
    allow_rule = tg.allow_rule_for(tool_name, tool_input)
    decision_id = f"{int(time.time() * 1000):x}{os.getpid():x}"
    tg.write_state(decision_id, {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "summary": summary,
        "allow_rule": allow_rule,
        "status": "pending",
        "created": time.time(),
    })

    # CLI mode: no Quick Pick exists to inject into, so block here and return
    # the decision directly. VS Code extension mode keeps the proven both-live
    # path below, completely unchanged.
    if not tg.is_vscode_extension():
        handle_cli(cfg, decision_id, summary, allow_rule)
        return

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
