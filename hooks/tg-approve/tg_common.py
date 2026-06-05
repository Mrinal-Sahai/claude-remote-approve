"""Shared helpers for the Telegram remote-approval hook.

Used by approve.py (the PreToolUse hook), watcher.py (the detached background
process that talks to Telegram and injects keystrokes), and tg_setup.py.

Stdlib only — no third-party deps.
"""
import fcntl
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ALLOWLIST_PATH = os.path.join(BASE_DIR, "allowlist.json")
STATE_DIR = os.path.join(BASE_DIR, "state")
LOG_PATH = os.path.join(BASE_DIR, "tg-approve.log")
# Only one process may hold a long-poll getUpdates at a time (Telegram 409).
TG_POLL_LOCK = os.path.join(BASE_DIR, "tg_poll.lock")
# Serialises access to the outgoing-send rate-limit ledger.
TG_SEND_LOCK = os.path.join(BASE_DIR, "tg_send.lock")
SEND_LEDGER_PATH = os.path.join(BASE_DIR, "tg_send_ledger.json")

# Telegram allows ~20 messages/min to one chat before 429s.  We stay under it
# and, when a burst exceeds the cap, emit a single "N pending" digest instead
# of one message per prompt (see reserve_send_slot).
MAX_SENDS_PER_MIN = 18
RATE_WINDOW_S = 60
DIGEST_COOLDOWN_S = 30

DEFAULT_CONFIG = {
    "bot_token": "",
    "chat_id": "",
    "enabled": True,
    # Watcher gives up waiting for a phone tap after this many seconds, then
    # leaves the editor Quick Pick to be answered locally.
    "watcher_timeout_seconds": 600,
    # How often the watcher polls Telegram + checks if the prompt is still open.
    "poll_interval_seconds": 2,
    # macOS process name VS Code shows up as for UI scripting (Electron app).
    "vscode_process_name": "Electron",
}


# ----------------------------------------------------------------------------
# logging
# ----------------------------------------------------------------------------
def log(msg):
    try:
        with open(LOG_PATH, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass


# ----------------------------------------------------------------------------
# config + allowlist
# ----------------------------------------------------------------------------
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(CONFIG_PATH, 0o600)


def load_allowlist():
    try:
        with open(ALLOWLIST_PATH) as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except (OSError, ValueError):
        pass
    return []


def add_allow_rule(rule):
    rules = load_allowlist()
    if rule not in rules:
        rules.append(rule)
        with open(ALLOWLIST_PATH, "w") as f:
            json.dump(rules, f, indent=2)


def allow_rule_for(tool_name, tool_input):
    """The 'always' rule string we'd persist for this call."""
    if tool_name == "Bash":
        cmd = (tool_input or {}).get("command", "").strip()
        first = cmd.split()[0] if cmd else ""
        return f"Bash:{first}"
    return f"{tool_name}:*"


def is_allowlisted(tool_name, tool_input):
    return allow_rule_for(tool_name, tool_input) in load_allowlist()


# ----------------------------------------------------------------------------
# human-readable summary of a tool call (for the phone)
# ----------------------------------------------------------------------------
def summarize(tool_name, tool_input):
    ti = tool_input or {}
    if tool_name == "Bash":
        cmd = ti.get("command", "")
        return f"Bash: {cmd}"[:300]
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return f"{tool_name}: {ti.get('file_path', ti.get('notebook_path', '?'))}"
    if tool_name == "WebFetch":
        return f"WebFetch: {ti.get('url', '?')}"
    # MCP / other tools: show a compact json
    try:
        blob = json.dumps(ti)[:200]
    except (TypeError, ValueError):
        blob = "<unserializable args>"
    return f"{tool_name}: {blob}"


# ----------------------------------------------------------------------------
# Telegram Bot API (via urllib)
# ----------------------------------------------------------------------------
def _api(cfg, method, params, timeout=35):
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def send_approval_message(cfg, decision_id, summary):
    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ Allow", "callback_data": f"{decision_id}:allow"},
            {"text": "⛔ Deny", "callback_data": f"{decision_id}:deny"},
            {"text": "♾️ Always", "callback_data": f"{decision_id}:always"},
        ]]
    }
    text = f"🔔 *Claude needs permission*\n\n`{summary}`\n\nApprove on your phone, or answer in the editor."
    res = _api(cfg, "sendMessage", {
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(keyboard),
    })
    return res.get("result", {}).get("message_id")


def edit_message(cfg, message_id, text):
    if not message_id:
        return  # nothing was sent (rate-limited / suppressed) -> nothing to edit
    try:
        _api(cfg, "editMessageText", {
            "chat_id": cfg["chat_id"],
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
        })
    except Exception as e:  # noqa: BLE001
        log(f"edit_message failed: {e}")


def answer_callback(cfg, callback_id, text=""):
    try:
        _api(cfg, "answerCallbackQuery", {"callback_query_id": callback_id, "text": text})
    except Exception as e:  # noqa: BLE001
        log(f"answer_callback failed: {e}")


def _load_ledger():
    try:
        with open(SEND_LEDGER_PATH) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {"sends": [], "last_digest": 0}


def reserve_send_slot():
    """Sliding-window rate gate for outgoing approval messages (flock-protected).

    Returns one of:
      "send"     -> caller may send a normal per-prompt approval message,
      "digest"   -> caller should send ONE combined "N pending" digest instead
                    (cap exceeded, but cooldown elapsed),
      "suppress" -> send nothing; rely on the editor (cap exceeded, in cooldown).

    Coordinates every watcher process on this machine so a burst of tool calls
    can't blow past Telegram's ~20-msg/min per-chat limit.
    """
    os.makedirs(BASE_DIR, exist_ok=True)
    lock_file = open(TG_SEND_LOCK, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        now = time.time()
        led = _load_ledger()
        sends = [t for t in led.get("sends", []) if now - t < RATE_WINDOW_S]
        if len(sends) < MAX_SENDS_PER_MIN:
            sends.append(now)
            led["sends"] = sends
            _save_ledger(led)
            return "send"
        # Over the per-minute cap: emit at most one digest per cooldown window.
        if now - led.get("last_digest", 0) > DIGEST_COOLDOWN_S:
            led["last_digest"] = now
            led["sends"] = sends
            _save_ledger(led)
            return "digest"
        led["sends"] = sends
        _save_ledger(led)
        return "suppress"
    finally:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_file.close()


def _save_ledger(led):
    try:
        with open(SEND_LEDGER_PATH, "w") as f:
            json.dump(led, f)
    except OSError:
        pass


def count_pending_states():
    """How many recent pending prompts are awaiting an answer right now."""
    n = 0
    try:
        now = time.time()
        for fname in os.listdir(STATE_DIR):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(STATE_DIR, fname)) as f:
                    st = json.load(f)
                if st.get("status") == "pending" and now - st.get("created", 0) < PROMPT_MAX_AGE_S:
                    n += 1
            except (OSError, ValueError):
                pass
    except OSError:
        pass
    return n


def send_digest(cfg):
    """Send one rate-limit digest message instead of per-prompt notifications."""
    pending = count_pending_states()
    text = (
        f"⚠️ *Claude has {pending} approvals pending*\n\n"
        "Too many requests at once to notify individually — "
        "please answer them in the editor."
    )
    try:
        _api(cfg, "sendMessage", {
            "chat_id": cfg["chat_id"],
            "text": text,
            "parse_mode": "Markdown",
        })
    except Exception as e:  # noqa: BLE001
        log(f"send_digest failed: {e}")


def get_updates(cfg, offset, timeout=20):
    """Long-poll Telegram for callback_query updates.

    Only the single dispatcher process (dispatcher.py) ever calls this, so
    there is no concurrent-poll 409 to defend against.  We still hold a blocking
    flock on TG_POLL_LOCK across the request as a belt-and-braces guard against
    a stray second poller during dispatcher hand-off.
    """
    os.makedirs(BASE_DIR, exist_ok=True)
    lock_file = open(TG_POLL_LOCK, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        res = _api(cfg, "getUpdates", {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["callback_query"]),
        }, timeout=timeout + 10)
        return res.get("result", [])
    finally:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_file.close()


# ----------------------------------------------------------------------------
# macOS UI scripting: drive VS Code permission Quick Pick via keystrokes
# ----------------------------------------------------------------------------
# VS Code's Quick Pick is rendered in Chromium's web layer and is invisible to
# the macOS Accessibility API.  We cannot reliably detect it via osascript.
#
# Detection strategy instead: a prompt is considered "open" if its state file
# exists with status="pending" and was created recently (< PROMPT_MAX_AGE_S).
# A PostToolUse hook marks state files "answered" as soon as the tool actually
# runs (i.e. the Quick Pick was answered locally), so the window is tight.
PROMPT_MAX_AGE_S = 90  # seconds after hook fired before we give up injecting


def _osascript(script):
    """Run AppleScript, return (ok, output)."""
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0, (out.stdout or out.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def quickpick_open(decision_id=None):
    """Return True if the permission prompt for decision_id is still pending.

    Fail-closed: returns False if the state file is absent, answered, or stale.
    The decision_id is passed from the watcher which knows which prompt it owns.
    If decision_id is None (legacy call) we fall back to checking any recent
    pending state file.
    """
    if decision_id:
        st = read_state(decision_id)
        if st.get("status") != "pending":
            log(f"quickpick_open({decision_id}): status={st.get('status')} -> closed")
            return False
        age = time.time() - st.get("created", 0)
        if age > PROMPT_MAX_AGE_S:
            log(f"quickpick_open({decision_id}): age={age:.0f}s > {PROMPT_MAX_AGE_S} -> closed")
            return False
        log(f"quickpick_open({decision_id}): age={age:.0f}s, pending -> open")
        return True

    # Legacy / no decision_id: scan state dir for any recent pending file
    try:
        now = time.time()
        for fname in os.listdir(STATE_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(STATE_DIR, fname)
            try:
                with open(fpath) as f:
                    st = json.load(f)
                if st.get("status") == "pending" and now - st.get("created", 0) < PROMPT_MAX_AGE_S:
                    log(f"quickpick_open(legacy): found pending {fname}")
                    return True
            except (OSError, ValueError):
                pass
    except OSError:
        pass
    log("quickpick_open(legacy): no pending state -> closed")
    return False


def inject_decision(cfg, decision):
    """Inject a keystroke into the VS Code window to answer the Quick Pick.

    allow/always -> Return  (selects the highlighted option)
    deny         -> Escape  (dismisses the Quick Pick = deny)

    Returns True if the keystroke was sent without error.
    """
    proc = cfg.get("vscode_process_name", "Electron")
    # Bring VS Code to front so the keystroke lands in the right window.
    activate = f'tell application "System Events" to set frontmost of process "{proc}" to true'
    _osascript(activate)
    time.sleep(0.25)
    key = "key code 53" if decision == "deny" else "key code 36"  # Esc / Return
    ok, out = _osascript(f'tell application "System Events" to {key}')
    log(f"inject_decision({decision}) -> ok={ok} out={out!r}")
    return ok


# ----------------------------------------------------------------------------
# decision state files (one per pending prompt)
# ----------------------------------------------------------------------------
def state_path(decision_id):
    return os.path.join(STATE_DIR, f"{decision_id}.json")


def write_state(decision_id, data):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(state_path(decision_id), "w") as f:
        json.dump(data, f)


def read_state(decision_id):
    try:
        with open(state_path(decision_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def route_phone_decision(decision_id, action):
    """Dispatcher -> watcher hand-off: record a phone tap into the state file.

    Returns True if a fresh pending prompt for decision_id existed (so the
    caller should ack the tap), False if it was unknown / already answered /
    stale (caller should tell the phone it expired).
    """
    st = read_state(decision_id)
    if st.get("status") != "pending":
        return False
    if time.time() - st.get("created", 0) > PROMPT_MAX_AGE_S:
        return False
    st["phone_decision"] = action
    st["phone_decided_at"] = time.time()
    write_state(decision_id, st)
    return True
