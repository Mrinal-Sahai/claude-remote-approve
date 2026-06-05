#!/usr/bin/env python3
"""Per-prompt watcher for one pending permission prompt (poll-less).

Spawned by approve.py with a decision id.  It:
  - sends the approval message to Telegram (Allow / Deny / Always buttons),
    subject to the burst rate-limit gate, and
  - watches its OWN state file for the outcome:
      * phone tap  -> dispatcher.py wrote state["phone_decision"]; we inject the
                      keystroke into the still-open Quick Pick,
      * answered in the editor -> post_tool.py marked status="answered"; we stop,
      * timeout    -> mark the message expired, stop.

It never talks to Telegram's getUpdates — the single dispatcher owns polling and
routes taps here.  This eliminates the 409 storm and tap-cannibalisation that
the old N-pollers design suffered under concurrent prompts.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_common as tg  # noqa: E402

LOCAL_POLL_S = 0.3  # how often we re-read our (local, cheap) state file


def ensure_dispatcher():
    """Spawn the singleton dispatcher if one isn't already running."""
    disp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatcher.py")
    try:
        devnull = open(os.devnull, "wb")
        subprocess.Popen(
            [sys.executable, disp],
            stdin=subprocess.DEVNULL, stdout=devnull, stderr=devnull,
            start_new_session=True, close_fds=True,
        )
    except Exception as e:  # noqa: BLE001
        tg.log(f"failed to spawn dispatcher: {e}")


def _send(cfg, decision_id, summary):
    """Send the approval message subject to the rate gate. Returns message_id or None."""
    mode = tg.reserve_send_slot()
    if mode == "send":
        try:
            return tg.send_approval_message(cfg, decision_id, summary)
        except Exception as e:  # noqa: BLE001
            tg.log(f"send_approval_message failed: {e}")
            return None
    if mode == "digest":
        tg.send_digest(cfg)
        tg.log(f"rate-limited: sent digest, {decision_id} editor-only")
    else:
        tg.log(f"rate-limited: suppressed, {decision_id} editor-only")
    return None


def _on_phone_decision(cfg, action, allow_rule, summary, message_id):
    """A phone tap arrived for us; inject it into the still-open Quick Pick."""
    tg.inject_decision(cfg, action)
    if action == "always":
        tg.add_allow_rule(allow_rule)
    verb = {"allow": "Allowed", "deny": "Denied", "always": "Always-allowed"}.get(action, action)
    tg.edit_message(cfg, message_id, f"✅ *{verb} from phone*\n\n`{summary}`")


def watch(cfg, decision_id, allow_rule, summary, message_id, deadline):
    """Wait for the outcome on our state file. Returns final status string."""
    while time.time() < deadline:
        st = tg.read_state(decision_id)
        action = st.get("phone_decision")
        if action and st.get("status") == "pending":
            _on_phone_decision(cfg, action, allow_rule, summary, message_id)
            return "phone"
        if st.get("status") == "answered":
            tg.edit_message(cfg, message_id, f"ℹ️ *Answered in the editor*\n\n`{summary}`")
            return "editor"
        if not st:  # state file vanished unexpectedly
            return "gone"
        time.sleep(LOCAL_POLL_S)
    return "timeout"


def main():
    if len(sys.argv) < 2:
        return
    decision_id = sys.argv[1]
    cfg = tg.load_config()
    st = tg.read_state(decision_id)
    summary = st.get("summary", "(unknown action)")
    allow_rule = st.get("allow_rule", "")

    ensure_dispatcher()
    message_id = _send(cfg, decision_id, summary)

    deadline = time.time() + cfg["watcher_timeout_seconds"]
    status = watch(cfg, decision_id, allow_rule, summary, message_id, deadline)
    if status == "timeout":
        tg.edit_message(cfg, message_id, f"⌛ *Expired* — answer in the editor\n\n`{summary}`")

    try:
        os.remove(tg.state_path(decision_id))
    except OSError:
        pass
    tg.log(f"watcher done for {decision_id} ({status})")


if __name__ == "__main__":
    main()
