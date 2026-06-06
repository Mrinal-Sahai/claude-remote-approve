#!/usr/bin/env python3
"""Print the chat_id of the first message received by the bot.

Called by the VS Code extension during setup to learn the user's Telegram
chat id without competing with the dispatcher.

Usage: python3 detect_chat_id.py <bot_token> [timeout_seconds]

Exit 0 + chat_id on stdout: success.
Exit 1 + nothing on stdout: timeout or error.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_common as tg  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("Usage: detect_chat_id.py <token> [timeout_s]", file=sys.stderr)
        sys.exit(1)

    token = sys.argv[1]
    total_s = int(sys.argv[2]) if len(sys.argv) > 2 else 60

    # Kill any running dispatcher so we have exclusive Telegram poll access.
    try:
        subprocess.run(["pkill", "-f", "dispatcher.py"],
                       capture_output=True, timeout=3)
        time.sleep(0.6)
    except Exception:  # noqa: BLE001
        pass

    cfg = {"bot_token": token}
    offset = 0
    deadline = time.time() + total_s

    while time.time() < deadline:
        poll_s = min(25, int(deadline - time.time()))
        if poll_s <= 0:
            break
        try:
            resp = tg._api(cfg, "getUpdates",
                           {"offset": offset, "timeout": poll_s},
                           timeout=poll_s + 5)
        except Exception as e:  # noqa: BLE001
            print(f"poll error: {e}", file=sys.stderr)
            time.sleep(1)
            continue

        for upd in resp.get("result", []):
            uid = upd.get("update_id", 0)
            if uid >= offset:
                offset = uid + 1
            msg = upd.get("message") or upd.get("edited_message")
            if msg:
                cid = msg.get("chat", {}).get("id")
                if cid is not None:
                    print(cid)
                    sys.exit(0)

    sys.exit(1)


if __name__ == "__main__":
    main()
