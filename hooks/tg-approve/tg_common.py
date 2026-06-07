"""Shared helpers for the Telegram remote-approval hook.

Used by approve.py (the PreToolUse hook), watcher.py (the detached background
process that talks to Telegram and injects keystrokes), and tg_setup.py.

Stdlib only — no third-party deps.
"""
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request

# Cross-platform exclusive file lock: fcntl on POSIX, msvcrt on Windows.
# (fcntl is Unix-only; importing it unconditionally crashes the hook on Windows.)
try:
    import fcntl  # POSIX
except ImportError:  # Windows
    fcntl = None
    import msvcrt

# Flags for spawning detached background processes. On Windows, CREATE_NO_WINDOW
# stops a console window flashing on every approval; on POSIX this is 0 (no-op —
# start_new_session does the detaching there). The conditional short-circuits so
# the Windows-only attribute is never accessed on POSIX.
DETACH_CREATIONFLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

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
    # macOS process name VS Code shows up as for UI scripting. Modern builds use
    # "Code"; _macos_editor_process() auto-detects if this doesn't match.
    "vscode_process_name": "Code",
}


# ----------------------------------------------------------------------------
# run mode: VS Code extension vs CLI
# ----------------------------------------------------------------------------
# Claude Code exports CLAUDE_CODE_ENTRYPOINT. The VS Code extension sets it to
# "claude-vscode"; the terminal CLI sets it to "cli" (and the integrated
# terminal counts as CLI too). We treat ONLY the explicit vscode value as
# extension mode, so the proven keystroke-injection path is never taken away
# from a working VS Code setup; everything else uses the blocking CLI strategy.
def is_vscode_extension():
    return os.environ.get("CLAUDE_CODE_ENTRYPOINT", "") == "claude-vscode"


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
    if tool_name in ("Bash", "PowerShell"):
        ti = tool_input or {}
        cmd = (ti.get("command") or ti.get("script") or "").strip()
        first = cmd.split()[0] if cmd else ""
        return f"{tool_name}:{first}"
    return f"{tool_name}:*"


def is_allowlisted(tool_name, tool_input):
    return allow_rule_for(tool_name, tool_input) in load_allowlist()


# ----------------------------------------------------------------------------
# human-readable summary of a tool call (for the phone)
# ----------------------------------------------------------------------------
def summarize(tool_name, tool_input):
    ti = tool_input or {}
    if tool_name in ("Bash", "PowerShell"):
        cmd = ti.get("command") or ti.get("script") or ""
        return f"{tool_name}: {cmd}"[:300]
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


def acquire_lock(fh, blocking=True):
    """Take an exclusive advisory lock on an open file handle, cross-platform.

    Returns True if acquired, False if (non-blocking and) the lock is held
    elsewhere. POSIX uses fcntl.flock; Windows uses msvcrt.locking on one byte.
    """
    if fcntl is not None:  # POSIX
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(fh, flags)
            return True
        except OSError:
            return False
    # Windows
    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), mode, 1)
        return True
    except OSError:
        return False


def release_lock(fh):
    """Release a lock taken by acquire_lock (best effort)."""
    if fcntl is not None:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        except OSError:
            pass
        return
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


def reserve_send_slot():
    """Sliding-window rate gate for outgoing approval messages (lock-protected).

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
        acquire_lock(lock_file)  # best-effort serialization
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
        release_lock(lock_file)
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
                if st.get("status") != "pending":
                    continue
                # CLI prompts stay pending until their explicit deadline; VS Code
                # prompts use the short PROMPT_MAX_AGE_S window (unchanged).
                deadline = st.get("deadline")
                if deadline is not None:
                    if now <= deadline:
                        n += 1
                elif now - st.get("created", 0) < PROMPT_MAX_AGE_S:
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
        acquire_lock(lock_file)
        res = _api(cfg, "getUpdates", {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": json.dumps(["callback_query"]),
        }, timeout=timeout + 10)
        return res.get("result", [])
    finally:
        release_lock(lock_file)
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
    """Inject a keystroke into the focused window to answer the Quick Pick.

    allow/always -> Return/Enter  (selects the highlighted option)
    deny         -> Escape        (dismisses the Quick Pick = deny)

    Per-OS backend: macOS uses AppleScript (the proven path, unchanged),
    Windows uses PowerShell SendKeys, Linux uses xdotool. Returns True if the
    keystroke was sent without error.
    """
    if sys.platform == "darwin":
        return _inject_macos(cfg, decision)
    if sys.platform == "win32":
        return _inject_windows(decision)
    return _inject_linux(decision)


# macOS editor process candidates, in priority order. The System Events process
# name has changed across VS Code versions: older builds showed up as "Electron",
# newer ones as "Code". Forks register under their own names. We auto-detect the
# one that's actually running so a VS Code update (or switching editor) never
# silently breaks the activate step.
_MACOS_EDITOR_CANDIDATES = [
    "Code", "Code - Insiders", "VSCodium", "Cursor", "Windsurf", "Electron",
]


def _macos_editor_process(cfg):
    """Resolve the live System Events process name for the editor window.

    Tries the configured name first (if it exists), then the known editor
    candidates. Falls back to the configured/default name if detection fails —
    so behaviour never regresses below the old hardcoded path.
    """
    configured = cfg.get("vscode_process_name") or "Code"
    ok, out = _osascript(
        'tell application "System Events" to get name of '
        "every process whose background only is false"
    )
    running = [n.strip() for n in out.split(",")] if ok else []
    for cand in [configured, *_MACOS_EDITOR_CANDIDATES]:
        if cand in running:
            if cand != configured:
                log(f"_macos_editor_process: configured {configured!r} not running, using {cand!r}")
            return cand
    return configured  # detection failed — keep original behaviour


def _inject_macos(cfg, decision):
    proc = _macos_editor_process(cfg)
    # Bring VS Code to front so the keystroke lands in the right window.
    activate = f'tell application "System Events" to set frontmost of process "{proc}" to true'
    act_ok, act_out = _osascript(activate)
    if not act_ok:
        log(f"_inject_macos: activate {proc!r} failed: {act_out!r}")
    time.sleep(0.25)
    key = "key code 53" if decision == "deny" else "key code 36"  # Esc / Return
    ok, out = _osascript(f'tell application "System Events" to {key}')
    log(f"inject_decision({decision}) -> proc={proc!r} ok={ok} out={out!r}")
    return ok


def _inject_windows(decision):
    """Windows: bring VS Code to front, then SendKeys. No extra deps."""
    key = "{ESC}" if decision == "deny" else "{ENTER}"
    # Bring VS Code to front first (mirrors the macOS activate step).
    try:
        ps_activate = (
            "$wsh = New-Object -ComObject WScript.Shell; "
            "$wsh.AppActivate('Visual Studio Code')"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_activate],
            capture_output=True, text=True, timeout=5,
        )
        time.sleep(0.25)
    except Exception:  # noqa: BLE001
        pass  # fall through — SendKeys will fire at whatever window is front
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"[System.Windows.Forms.SendKeys]::SendWait('{key}')"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=10,
        )
        ok = out.returncode == 0
        log(f"inject_decision({decision}) [win] -> ok={ok} err={out.stderr.strip()!r}")
        return ok
    except Exception as e:  # noqa: BLE001
        log(f"inject_decision({decision}) [win] failed: {e}")
        return False


def _inject_linux(decision):
    """Linux/X11: focus the VS Code window, then send key with xdotool."""
    key = "Escape" if decision == "deny" else "Return"
    # Bring VS Code to front first (mirrors the macOS activate step).
    try:
        wid_out = subprocess.run(
            ["xdotool", "search", "--class", "Code"],
            capture_output=True, text=True, timeout=5,
        )
        if wid_out.returncode == 0 and wid_out.stdout.strip():
            wid = wid_out.stdout.strip().split()[-1]  # last = topmost window
            subprocess.run(
                ["xdotool", "windowfocus", "--sync", wid],
                capture_output=True, text=True, timeout=5,
            )
    except Exception:  # noqa: BLE001
        pass  # fall through — xdotool key will fire at whatever has focus
    try:
        out = subprocess.run(
            ["xdotool", "key", "--clearmodifiers", key],
            capture_output=True, text=True, timeout=10,
        )
        ok = out.returncode == 0
        log(f"inject_decision({decision}) [linux] -> ok={ok} err={out.stderr.strip()!r}")
        return ok
    except FileNotFoundError:
        log("inject_decision [linux]: xdotool not installed (apt/dnf install xdotool)")
        return False
    except Exception as e:  # noqa: BLE001
        log(f"inject_decision({decision}) [linux] failed: {e}")
        return False


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
    # CLI blocking prompts carry an explicit `deadline`: the hook is still alive
    # and answerable until then. VS Code prompts have no `deadline` field and use
    # the short PROMPT_MAX_AGE_S window tied to the Quick Pick's lifetime.
    deadline = st.get("deadline")
    if deadline is not None:
        if time.time() > deadline:
            return False
    elif time.time() - st.get("created", 0) > PROMPT_MAX_AGE_S:
        return False
    st["phone_decision"] = action
    st["phone_decided_at"] = time.time()
    write_state(decision_id, st)
    return True
