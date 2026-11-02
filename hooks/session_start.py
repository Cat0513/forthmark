#!/usr/bin/env python3
"""Claude Code SessionStart hook (global): in a tracked project, give the agent the
recording rules and the current status, so it can resume without being re-briefed.

Untracked directories: exits silently. Never fails the session.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from fmshared import tracked, utf8_stdio  # noqa: E402


def main():
    utf8_stdio()
    hook_input = json.load(sys.stdin)
    if not tracked(hook_input.get("cwd") or "."):
        return
    if hook_input.get("source") == "resume":
        # A resumed session already has the rules and status in its history; don't repeat them.
        # Panel changes made meanwhile reach it through the UserPromptSubmit hook.
        return
    import forthmark

    found = forthmark.find_project(hook_input.get("cwd") or ".")
    if not found:
        return
    pid, entry = found
    context = forthmark.rules_text(pid)
    try:
        status = forthmark.full_status(pid)
        context += forthmark.L("\n\n## 当前状态（会话开始时）\n\n", "\n\n## Current status (at session start)\n\n") + forthmark.show_text(status)
        stale = forthmark.stale_sources(pid, entry, status)
        if stale:
            context += forthmark.L("\n\n**注意**：进度来源 " + "、".join(stale) +
                                   " 在状态上次更新之后有改动，状态可能落后。先对照它们更新状态文件，再开始本次工作。",
                                   "\n\n**Note**: progress sources " + ", ".join(stale) +
                                   " changed after the status was last updated, so it may be behind. Reconcile the status with them before starting.")
    except (OSError, ValueError, KeyError):
        context += forthmark.L("\n\n（状态文件当前无法读取，请检查并修复。）", "\n\n(The status file can't be read right now; please check and fix it.)")
    try:
        forthmark.mark_synced(pid, hook_input.get("session_id"))  # this session has seen everything so far
    except OSError:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": context}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # a broken status tool must never break the user's session
        pass
