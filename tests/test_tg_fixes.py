#!/usr/bin/env python3
"""🟡 MOCK suite for claude-remote-approve.

No phone, no real Telegram. Monkeypatches the Telegram + injection surface and
drives the real dispatcher/watcher code. Covers chat_id auth, tap routing to the
correct prompt under concurrency, expiry acks, stale-prompt rejection, the burst
rate gate, and the watcher's inject / editor-wins paths.

Run:  python3 tests/test_tg_fixes.py
"""
import os
import sys
import time

# Import the hook modules straight from this repo (not the installed copy).
HOOK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks", "tg-approve")
sys.path.insert(0, os.path.abspath(HOOK_DIR))
import tg_common as tg      # noqa: E402
import dispatcher           # noqa: E402
import watcher              # noqa: E402

CFG = {"chat_id": "123456", "watcher_timeout_seconds": 2}
acks, injects, edits = [], [], []

tg.answer_callback = lambda cfg, cb_id, text="": acks.append((cb_id, text))
tg.inject_decision = lambda cfg, action: injects.append(action)
tg.edit_message = lambda cfg, mid, text: edits.append((mid, text))


def _mk_state(decision_id, **extra):
    st = {"tool_name": "Bash", "summary": "Bash: echo hi", "allow_rule": "Bash:echo",
          "status": "pending", "created": time.time()}
    st.update(extra)
    tg.write_state(decision_id, st)


def _cleanup(*ids):
    for i in ids:
        try:
            os.remove(tg.state_path(i))
        except OSError:
            pass


def test_dispatcher_rejects_unauthorized():
    acks.clear()
    _mk_state("test_auth")
    dispatcher._handle_callback(CFG, {"id": "cb1", "from": {"id": 999}, "data": "test_auth:allow"})
    assert "phone_decision" not in tg.read_state("test_auth")
    assert acks[-1] == ("cb1", "Not authorized"), acks
    _cleanup("test_auth")
    print("PASS dispatcher_rejects_unauthorized")


def test_dispatcher_routes_to_correct_prompt():
    acks.clear()
    _mk_state("test_A")
    _mk_state("test_B")
    dispatcher._handle_callback(CFG, {"id": "cb2", "from": {"id": 123456}, "data": "test_B:always"})
    assert tg.read_state("test_A").get("phone_decision") is None, "A must be untouched"
    assert tg.read_state("test_B").get("phone_decision") == "always", "B must receive the tap"
    assert acks[-1][0] == "cb2" and "Always" in acks[-1][1], acks
    _cleanup("test_A", "test_B")
    print("PASS dispatcher_routes_to_correct_prompt")


def test_dispatcher_acks_unknown_as_expired():
    acks.clear()
    dispatcher._handle_callback(CFG, {"id": "cb3", "from": {"id": 123456}, "data": "nope:deny"})
    assert "expired" in acks[-1][1].lower(), acks
    print("PASS dispatcher_acks_unknown_as_expired")


def test_route_rejects_stale_prompt():
    _mk_state("test_old", created=time.time() - (tg.PROMPT_MAX_AGE_S + 5))
    assert tg.route_phone_decision("test_old", "allow") is False
    _cleanup("test_old")
    print("PASS route_rejects_stale_prompt")


def test_rate_limit_gate():
    try:
        os.remove(tg.SEND_LEDGER_PATH)
    except OSError:
        pass
    modes = [tg.reserve_send_slot() for _ in range(25)]
    assert modes.count("send") == tg.MAX_SENDS_PER_MIN, modes
    assert modes.count("digest") == 1, modes
    try:
        os.remove(tg.SEND_LEDGER_PATH)
    except OSError:
        pass
    print(f"PASS rate_limit_gate ({modes.count('send')}s/{modes.count('digest')}d/"
          f"{modes.count('suppress')}x)")


def test_watcher_injects_on_phone_decision():
    injects.clear()
    edits.clear()
    _mk_state("test_w", phone_decision="allow")
    status = watcher.watch(CFG, "test_w", "Bash:echo", "Bash: echo hi", 123, time.time() + 2)
    assert status == "phone", status
    assert injects == ["allow"], injects
    assert edits and "from phone" in edits[-1][1], edits
    _cleanup("test_w")
    print("PASS watcher_injects_on_phone_decision")


def test_watcher_stops_on_editor_answer():
    injects.clear()
    _mk_state("test_e", status="answered")
    status = watcher.watch(CFG, "test_e", "Bash:echo", "Bash: echo hi", 123, time.time() + 2)
    assert status == "editor", status
    assert injects == [], "must NOT inject when the editor already answered"
    _cleanup("test_e")
    print("PASS watcher_stops_on_editor_answer")


if __name__ == "__main__":
    test_dispatcher_rejects_unauthorized()
    test_dispatcher_routes_to_correct_prompt()
    test_dispatcher_acks_unknown_as_expired()
    test_route_rejects_stale_prompt()
    test_rate_limit_gate()
    test_watcher_injects_on_phone_decision()
    test_watcher_stops_on_editor_answer()
    print("\nALL MOCK TESTS PASSED")
