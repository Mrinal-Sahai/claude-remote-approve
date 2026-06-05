#!/usr/bin/env python3
"""Single per-machine Telegram poller for tg-approve.

Exactly one of these runs at a time (guarded by a flock singleton).  It is the
ONLY process that calls getUpdates, which means:
  - no concurrent-poll HTTP 409 storms, and
  - no tap-cannibalisation: every callback is routed to the state file of the
    prompt it belongs to, instead of being eaten by whichever watcher polled.

For each callback it:
  1. rejects anyone who is not the configured chat (security),
  2. routes "<decision_id>:<action>" into state/<decision_id>.json so that
     prompt's watcher can inject the keystroke,
  3. acks the phone (stops the button spinner); unknown/stale ids get "expired".

It exits on its own once no prompt has been pending for IDLE_EXIT_S, so it never
lingers as a zombie daemon.  approve.py respawns one on the next prompt.
"""
import fcntl
import os
import re
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_common as tg  # noqa: E402

SINGLETON_LOCK = os.path.join(tg.BASE_DIR, "dispatcher.lock")
_HOST = re.sub(r"[^A-Za-z0-9_.-]", "_", socket.gethostname() or "host")
OFFSET_PATH = os.path.join(tg.BASE_DIR, f"tg_offset_{_HOST}.txt")

IDLE_EXIT_S = 30          # exit after this long with zero pending prompts
LONG_POLL_S = 20          # Telegram long-poll window (returns early on a tap)

VERBS = {"allow": "✅ Allowed", "deny": "⛔ Denied", "always": "♾️ Always-allowed"}


def read_offset():
    try:
        with open(OFFSET_PATH) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def write_offset(v):
    try:
        with open(OFFSET_PATH, "w") as f:
            f.write(str(v))
    except OSError:
        pass


def _handle_callback(cfg, cb):
    """Route one callback_query to its prompt's state file."""
    from_id = str(cb.get("from", {}).get("id", ""))
    if from_id != str(cfg["chat_id"]):
        tg.answer_callback(cfg, cb["id"], "Not authorized")
        tg.log(f"dispatcher: rejected unauthorized id={from_id!r}")
        return
    data = cb.get("data", "")
    if ":" not in data:
        tg.answer_callback(cfg, cb["id"], "⌛ Expired")
        return
    decision_id, action = data.split(":", 1)
    if tg.route_phone_decision(decision_id, action):
        tg.answer_callback(cfg, cb["id"], VERBS.get(action, action))
        tg.log(f"dispatcher: routed {action} -> {decision_id}")
    else:
        tg.answer_callback(cfg, cb["id"], "⌛ This prompt expired — answer in the editor")


def poll_loop(cfg):
    idle_since = time.time()
    while True:
        try:
            updates = tg.get_updates(cfg, read_offset(), timeout=LONG_POLL_S)
        except Exception as e:  # noqa: BLE001
            tg.log(f"dispatcher get_updates error: {e}")
            time.sleep(2)
            updates = []
        for upd in updates:
            write_offset(upd["update_id"] + 1)
            cb = upd.get("callback_query")
            if cb:
                _handle_callback(cfg, cb)

        if tg.count_pending_states() > 0:
            idle_since = time.time()
        elif time.time() - idle_since > IDLE_EXIT_S:
            tg.log("dispatcher: idle, exiting")
            return


def main():
    # Singleton: hold the lock for our whole lifetime.  A second dispatcher
    # fails the non-blocking acquire and exits immediately.
    lock_file = open(SINGLETON_LOCK, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return  # another dispatcher already owns the poll

    cfg = tg.load_config()
    if not cfg.get("bot_token") or not cfg.get("chat_id"):
        return
    tg.log(f"dispatcher: started (pid {os.getpid()}, host {_HOST})")
    try:
        poll_loop(cfg)
    finally:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_file.close()
        tg.log("dispatcher: stopped")


if __name__ == "__main__":
    main()
