#!/usr/bin/env python3
"""Claude Code status line: one line at the bottom of the terminal.

In a tracked project:  🎯 t2 用户协议页 · ⏳ 6 等你 · 最久 5 天 · ⏸ 1 · 🐞 1 · 38%
Elsewhere: just the model name. If the user had a status line before setup, its output
comes first and ours is appended.

Shown to the user only, never sent to the model: no tokens. Runs often, so it reads the
two small JSON files directly instead of loading the toolkit.
"""
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from fmshared import data_home, inside, utf8_stdio  # noqa: E402

HOME = data_home()
DIM, AMBER, RED, RESET = "\033[2m", "\033[33m", "\033[31m", "\033[0m"


def is_en():
    """Same rule as forthmark.ui_lang(), without importing it: env, config, then the system language it cached."""
    lang = os.environ.get("FORTHMARK_LANG")
    if lang not in ("zh", "en"):
        try:
            lang = json.loads((HOME / "config.json").read_text(encoding="utf-8")).get("lang")
        except (OSError, ValueError):
            lang = None
    if lang not in ("zh", "en"):
        try:
            lang = (HOME / "lang.cache").read_text(encoding="utf-8").strip()
        except OSError:
            lang = "zh" if os.environ.get("LANG", "").startswith("zh") else "en"
    return lang == "en"


EN = is_en()


def L(zh, en):
    return en if EN else zh


def days(d):
    try:
        return (date.today() - date.fromisoformat(d[:10])).days
    except (TypeError, ValueError):
        return 0


def short(text, n=14):
    """At most n wide characters (CJK) or 2n narrow ones (Latin): the same room on screen in either language."""
    room, out = n * 2, ""
    for ch in text:
        w = 2 if ord(ch) > 0x2E80 else 1
        if room - w < (2 if len(out) < len(text) - 1 else 0):
            return out.rstrip() + "…"
        out, room = out + ch, room - w
    return out


def project_for(cwd):
    try:
        projects = json.loads((HOME / "registry.json").read_text(encoding="utf-8"))["projects"]
    except (OSError, ValueError, KeyError):
        return None
    hits = [(pid, e) for pid, e in projects.items() if inside(cwd, e["path"])]
    return max(hits, key=lambda h: len(h[1]["path"]))[0] if hits else None


def forthmark_line(pid):
    s = json.loads((HOME / "projects" / pid / "status.json").read_text(encoding="utf-8"))
    parts = []
    doing = [t for t in s["tasks"] if t["status"] == "doing"]
    fixing = [b for b in s["bugs"] if b["status"] == "fixing"]
    if doing:
        t = sorted(doing, key=lambda t: not t.get("urgent"))[0]
        parts.append(f"🎯 {'⚡' if t.get('urgent') else ''}{t['id']} {short(t['title'])}" +
                     (f" +{len(doing) - 1}" if len(doing) > 1 else ""))
    elif fixing:
        parts.append(f"🎯 🐞{fixing[0]['id']} {short(fixing[0]['title'])}")
    elif s.get("next"):
        parts.append(f"{DIM}▶ {short(s['next']['title'], 18)}{RESET}")

    waits = [w for w in s["waiting"] if w["status"] == "open"]
    mine = [w for w in waits if w["waiting_on"] == "me"]
    others_late = [w for w in waits if w["waiting_on"] != "me" and days(w["since"]) >= 3]
    if mine:
        oldest = max(days(w["since"]) for w in mine)
        parts.append(f"⏳ {len(mine)} {L('等你', 'on you')}" + (f" {AMBER}{L(f'最久 {oldest} 天', f'oldest {oldest}d')}{RESET}" if oldest >= 3 else ""))
    if others_late:
        parts.append(f"{RED}📣 {len(others_late)} {L('该催了', 'to nudge')}{RESET}")

    paused = [t for t in s["tasks"] if t["status"] == "paused"]
    if paused:
        oldest = max(days(t.get("paused_at")) for t in paused)
        parts.append(f"⏸ {len(paused)}" + (f" {AMBER}{L(f'停 {oldest} 天', f'for {oldest}d')}{RESET}" if oldest >= 3 else ""))
    bugs = [b for b in s["bugs"] if b["status"] in ("open", "fixing")]
    if bugs:
        parts.append(f"🐞 {len(bugs)}")

    live = [t for t in s["tasks"] if t["status"] != "dropped"]
    archived = []
    try:
        archived = json.loads((HOME / "projects" / pid / "archive.json").read_text(encoding="utf-8")).get("tasks", [])
    except (OSError, ValueError):
        pass
    total = len(live) + len([t for t in archived if t["status"] != "dropped"])
    done = sum(t["status"] == "done" for t in live) + sum(t["status"] == "done" for t in archived)
    if total:
        parts.append(f"{DIM}{done * 100 // total}%{RESET}")
    return " · ".join(parts)


def previous_line(raw):
    """Output of the status line the user had before setup, if any."""
    try:
        prev = json.loads((HOME / "setup.json").read_text(encoding="utf-8")).get("prev_statusline")
    except (OSError, ValueError):
        return ""
    if not prev:
        return ""
    try:
        r = subprocess.run(prev, shell=True, input=raw, capture_output=True, encoding="utf-8", errors="replace", timeout=2)
        return r.stdout.splitlines()[0] if r.stdout else ""
    except (subprocess.SubprocessError, OSError):
        return ""


def main():
    utf8_stdio()
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except ValueError:
        data = {}
    cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or os.getcwd()
    ours = ""
    pid = project_for(cwd)
    if pid:
        try:
            ours = forthmark_line(pid)
        except (OSError, ValueError, KeyError):
            ours = ""
    prev = previous_line(raw)
    if not prev and not ours:
        prev = (data.get("model") or {}).get("display_name", "")
    print(" │ ".join(x for x in (prev, ours) if x))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("")
