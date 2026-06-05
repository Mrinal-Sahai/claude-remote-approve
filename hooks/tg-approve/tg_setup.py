#!/usr/bin/env python3
"""One-time setup for the Telegram remote-approval hook.

Reads your bot token from (in order):
  1. env var TG_BOT_TOKEN, or
  2. a file you create: ~/.claude/hooks/tg-approve/token.txt

Then it auto-detects your chat id from the most recent message you sent the
bot, writes config.json (chmod 600), deletes token.txt, and sends a test
message to confirm.

Prereqs:
  1. In Telegram, talk to @BotFather -> /newbot -> copy the token.
  2. Put the token in token.txt (or export TG_BOT_TOKEN=...).
  3. Open your new bot in Telegram and send it any message (e.g. "hi").
  4. Run: python3 tg_setup.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_common as tg  # noqa: E402

TOKEN_FILE = os.path.join(tg.BASE_DIR, "token.txt")


def get_token():
    tok = os.environ.get("TG_BOT_TOKEN", "").strip()
    if tok:
        return tok
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def main():
    token = get_token()
    if not token:
        print("ERROR: no token. Put it in token.txt or set TG_BOT_TOKEN.")
        print(f"  token.txt path: {TOKEN_FILE}")
        sys.exit(1)

    cfg = tg.load_config()
    cfg["bot_token"] = token

    # Find chat id from the latest incoming message.
    try:
        res = tg._api(cfg, "getUpdates", {"offset": 0, "timeout": 0}, timeout=15)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: could not reach Telegram API: {e}")
        print("Check the token is correct.")
        sys.exit(1)

    chat_id = None
    for upd in res.get("result", []):
        msg = upd.get("message") or upd.get("edited_message")
        if msg and msg.get("chat", {}).get("id") is not None:
            chat_id = msg["chat"]["id"]
    if chat_id is None:
        print("ERROR: no messages found. Open your bot in Telegram, send it any")
        print("message (e.g. 'hi'), then run this again.")
        sys.exit(1)

    cfg["chat_id"] = str(chat_id)
    tg.save_config(cfg)

    # Remove the plaintext token file now that it's in config (chmod 600).
    try:
        os.remove(TOKEN_FILE)
    except OSError:
        pass

    try:
        tg._api(cfg, "sendMessage", {
            "chat_id": cfg["chat_id"],
            "text": "✅ tg-approve connected. You'll get permission prompts here.",
        })
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: config saved but test message failed: {e}")
        sys.exit(1)

    print("SUCCESS")
    print(f"  chat_id : {chat_id}")
    print(f"  config  : {tg.CONFIG_PATH} (chmod 600)")
    print("  A test message was sent to your Telegram. Setup complete.")


if __name__ == "__main__":
    main()
