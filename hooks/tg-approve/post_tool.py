#!/usr/bin/env python3
"""PostToolUse hook: mark tg-approve state files as answered when tool runs.

When Claude Code processes the permission Quick Pick (user answered locally),
it runs the tool and fires PostToolUse.  We scan state/ for pending files
matching this tool call and mark them "answered" so watcher.py knows the
prompt is gone and won't inject a stray keystroke.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tg_common as tg  # noqa: E402


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    try:
        now = time.time()
        for fname in os.listdir(tg.STATE_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(tg.STATE_DIR, fname)
            try:
                with open(fpath) as f:
                    st = json.load(f)
                if (
                    st.get("status") == "pending"
                    and st.get("tool_name") == tool_name
                    and now - st.get("created", 0) < tg.PROMPT_MAX_AGE_S
                ):
                    st["status"] = "answered"
                    st["answered_at"] = now
                    with open(fpath, "w") as f:
                        json.dump(st, f)
                    tg.log(f"post_tool: marked {fname} answered ({tool_name})")
            except (OSError, ValueError):
                pass
    except OSError:
        pass


if __name__ == "__main__":
    main()
