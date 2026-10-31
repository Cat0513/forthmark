#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook (global): if the user changed things in the panel
since this session last heard (recorded a decision, marked something done, paused a
task...), tell the agent before it answers. Nothing changed: prints nothing, costs no tokens.

Untracked directories: exits silently. Never fails the session.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))


def data_home():
    return Path(os.environ.get("FORTHMARK_HOME") or "~/.forthmark").expanduser()


def tracked(cwd):
    """Cheap check against the registry, so untracked projects never load the toolkit."""
    home = data_home()
    try:
        projects = json.loads((home / "registry.json").read_text(encoding="utf-8"))["projects"].values()
    except (OSError, ValueError, KeyError):
        return False
    cwd = os.path.realpath(cwd)
    return any(cwd == p["path"] or cwd.startswith(p["path"].rstrip("/") + "/") for p in projects)


def session_started(transcript):
    """Fallback for sessions that began before this hook existed: when the transcript was created."""
    try:
        st = os.stat(transcript)
        born = getattr(st, "st_birthtime", st.st_ctime)
        return datetime.fromtimestamp(born).astimezone().isoformat(timespec="seconds")
    except (OSError, TypeError):
        return None


def main():
    hook_input = json.load(sys.stdin)
    if not tracked(hook_input.get("cwd") or "."):
        return
    import forthmark

    found = forthmark.find_project(hook_input.get("cwd") or ".")
    if not found:
        return
    pid, _ = found
    session = hook_input.get("session_id")
    changes = forthmark.panel_changes_since(pid, session, session_started(hook_input.get("transcript_path")))
    forthmark.mark_synced(pid, session)
    # Paused from the panel without a note: the agent knows where things stand, so it writes it.
    no_note = [t for t in forthmark.load_status(pid)["tasks"] if t["status"] == "paused" and not t.get("note")]
    if not changes and not no_note:
        return
    parts = []
    if changes:
        lines = "\n".join(f"- {forthmark.strip_source(e['text'])}" for e in changes)
        parts.append(forthmark.L(
            "Forthmark：自你上次看到状态以来，用户在面板上做了这些更新（已写入状态文件，不需要再记录）：\n"
            f"{lines}\n请据此继续，例如用户给出的答复就是你在等的信息；当前状态以 `forthmark.py show` 为准。",
            "Forthmark: since you last saw the status, the user made these updates in the panel (already in the status file, "
            f"no need to record them):\n{lines}\nContinue accordingly; for example, an answer from the user is the information "
            "you were waiting for. `forthmark.py show` has the current status."))
    if no_note:
        todo = forthmark.L("、", ", ").join(forthmark.L(f"{t['id']}（{t['title']}）", f"{t['id']} ({t['title']})") for t in no_note)
        parts.append(forthmark.L(
            f"Forthmark：{todo} 已暂停但还没有恢复要点。请根据你掌握的上下文补写一句「做到哪、回来从哪继续」："
            f"`{forthmark.CLI} op pause_task id=<id> note=\"…\"`；不清楚的写你知道的部分即可。",
            f"Forthmark: {todo} paused without a resume note. From what you know, add one line on where it stopped and "
            f"where to pick up: `{forthmark.CLI} op pause_task id=<id> note=\"…\"`; write what you know if unsure."))
    context = "\n\n".join(parts)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                             "additionalContext": context}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # a broken status tool must never break the user's session
        pass
