#!/usr/bin/env python3
"""PostToolUse hook: mark tg-approve state files as answered when tool runs.

When Claude Code processes the permission Quick Pick (user answered locally),
it runs the tool and fires PostToolUse.  We scan state/ for pending files
matching this tool call and mark them "answered" so watcher.py knows the
prompt is gone and won't inject a stray keystroke.

Two guards keep this from marking the WRONG prompt when several calls are in
flight at once (Claude batches parallel Bash calls):
  - skip CLI blocking prompts (they carry a `deadline`): they're owned entirely
    by the blocking hook in approve.py and must never be force-answered here,
    or a sibling tool running would cancel a prompt still waiting for a phone
    tap, and the tap would be refused as "expired".
  - match the tool_input too, not just the tool_name, so one Bash call doesn't
    mark a different pending Bash call answered.
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
                    and "deadline" not in st  # CLI prompt — owned by the blocking hook
                    and st.get("tool_name") == tool_name
                    and st.get("tool_input") == tool_input
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
