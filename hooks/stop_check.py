#!/usr/bin/env python3
"""Claude Code Stop hook (global): in a tracked project, make sure the status file is
valid and not stale, then regenerate the panel.

Blocks the agent from finishing (once per turn) when:
  - the status file fails validation, or
  - files in the project's git working tree changed after the status was last written.
git is only read, never written. Untracked directories: exits silently.

Every check appends one line to <data>/hook-log.jsonl, so `forthmark.py stats` can show
how often the agent kept the status up to date on its own.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
forthmark = None  # imported only for tracked projects


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


def log(pid, result, detail=""):
    entry = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "result": result}
    if detail:
        entry["detail"] = detail
    with open(forthmark.data_dir(pid) / "hook-log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def render():
    try:
        forthmark.render_panel()
    except Exception:
        pass


def usage(pid, hook_input, blocking):
    try:
        forthmark.record_usage(pid, hook_input.get("transcript_path"), hook_input.get("session_id"), blocking)
    except Exception:
        pass  # accounting must never break the hook


def block(pid, result, reason, hook_input):
    usage(pid, hook_input, True)
    log(pid, result, reason)
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    sys.exit(0)


def changed_since(project_path, mtime):
    """Files in the git working tree modified after mtime (read-only git)."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
            cwd=project_path, capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.SubprocessError, FileNotFoundError, NotADirectoryError):
        return []
    newer, entries, i = [], out.split("\0"), 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            i += 1  # -z puts the rename source in the next field
        p = project_path / path
        if p.is_file() and p.stat().st_mtime > mtime:
            newer.append(path)
    return newer


def main():
    global forthmark
    hook_input = json.load(sys.stdin)
    if not tracked(hook_input.get("cwd") or "."):
        return
    import forthmark
    found = forthmark.find_project(hook_input.get("cwd") or ".")
    if not found:
        return
    pid, entry = found
    status_file = forthmark.status_path(pid)

    if hook_input.get("stop_hook_active"):
        usage(pid, hook_input, False)
        log(pid, "retry-pass")
        render()
        return

    errors, _ = forthmark.validate_project(pid)
    if errors:
        block(pid, "invalid", forthmark.L(f"项目状态文件 {status_file} 校验失败，请修正后再结束：\n",
                                          f"The project status file {status_file} failed validation; fix it before finishing:\n")
              + "\n".join(errors[:10]), hook_input)

    newer = changed_since(Path(entry["path"]), status_file.stat().st_mtime)
    if newer:
        shown = ", ".join(newer[:5]) + (forthmark.L(f" 等 {len(newer)} 个文件", f" and more ({len(newer)} files)") if len(newer) > 5 else "")
        block(pid, "stale",
              forthmark.L(f"本轮修改了 {shown}，但项目状态 {status_file} 尚未更新。"
                          "请按 Forthmark 记录规则更新（任务、等待项、bug、决策、next、timeline）。"
                          "如果这些改动不涉及任何需要记录的进展，只需把 updated_at 更新为当前时间。",
                          f"This turn changed {shown}, but the project status {status_file} wasn't updated. "
                          "Update it following the Forthmark recording rules (tasks, waiting items, bugs, decisions, next, timeline). "
                          "If the changes involve no progress worth recording, just set updated_at to the current time."), hook_input)

    usage(pid, hook_input, False)
    log(pid, "ok")
    try:
        forthmark.archive_status(pid)  # keeps the file agents read small; no-op below the threshold
    except Exception:
        pass
    try:
        forthmark.auto_verify(pid)  # 'do' items with a check that now passes resolve themselves
    except Exception:
        pass
    render()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:  # never break the user's session
        pass
