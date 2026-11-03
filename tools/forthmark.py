#!/usr/bin/env python3
"""Forthmark: agent-maintained project status for humans, kept outside your projects.

Usage:
  forthmark.py setup             once: global Claude Code hooks, status line, permissions, /forthmark commands
                               (--no-statusline to leave the status line alone)
  forthmark.py teardown          undo setup (status data is kept)
  forthmark.py add [DIR]         start tracking a project (its git root; --here for DIR itself); nothing is written
  forthmark.py remove [DIR]      stop tracking a project (status data is kept)
  forthmark.py move OLD NEW      the project folder was moved/renamed: keep its status under the new path
  forthmark.py new NAME [--dir=PATH] [--goal="…"]   new folder, tracked, your agent opened in a terminal (you type first)
  forthmark.py session [DIR]     ＋ a new agent session in your terminal (it gets the project's status)
  forthmark.py continue [DIR]    ▶ the agent's most recent session in that folder
  forthmark.py sessions [DIR]    ☰ the agent's own session picker in that folder
  forthmark.py list              tracked projects
  forthmark.py prune [--yes]     data left behind by projects that are no longer tracked
  forthmark.py rules [DIR]       the recording rules for a project's agent
  forthmark.py validate [DIR]    check a project's status file (exit 1 on errors)
  forthmark.py show [DIR]        status summary in the terminal
  forthmark.py stats [DIR]       how often the agent kept the status up to date on its own
  forthmark.py html [--open]     regenerate the static panel for all projects
  forthmark.py archive [DIR]     move old finished items to archive.json (automatic above 12 KB)
  forthmark.py notify [--dry-run] send (or preview) today's nudges; the local service does this every 30 min
  forthmark.py check             load every project/tab of the panel in headless Chrome; fail on JS errors
  forthmark.py open              open the live panel (starts the local service if needed)
  forthmark.py serve             run the local service in the foreground (127.0.0.1 only)
  forthmark.py stop              stop the local service (e.g. after updating the kit)
  forthmark.py op OP [k=v ...]   apply a structured operation to the project in the current dir
  forthmark.py docs [DIR]        the project's docs and scripts (read-only discovery; ★ = progress source)
  forthmark.py doc PATH k=v ...  note what a doc is for: role=plan purpose="…" tags=a,b

All data lives in $FORTHMARK_HOME (default ~/.forthmark). DIR defaults to the current
directory; any directory inside a tracked project resolves to that project.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fmshared import IS_WINDOWS, data_home, native_path, replace_file, utf8_stdio

KIT = Path(__file__).resolve().parent.parent
HOME = data_home()
CLAUDE_DIR = Path(os.environ.get("FORTHMARK_CLAUDE_DIR", "~/.claude")).expanduser()
SCHEMA_PATH = KIT / "schema" / "status.schema.json"
PANEL_TEMPLATE = KIT / "templates" / "panel.html"
RULES_TEMPLATE = KIT / "templates" / "RULES.md"


def bare_path(path):
    """A Windows program path that needs no quotes, for commands that may run in Git Bash or PowerShell:
    PowerShell prints a quoted first word instead of running it. None if spaces can't be avoided."""
    path = str(path)
    if " " in path:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(path, buf, len(buf)):
            path = buf.value
    return None if " " in path else path.replace("\\", "/")


# How agents call us. Quoted, so the kit can live anywhere (spaces included); rules, /forthmark commands
# and the permission rule all use exactly this string.
if IS_WINDOWS:
    CLI = f"{bare_path(sys.executable) or 'python'} {shlex.quote((KIT / 'tools' / 'forthmark.py').as_posix())}"
else:
    CLI = f"python3 {shlex.quote(str(KIT / 'tools' / 'forthmark.py'))}"
REGISTRY = HOME / "registry.json"
PANEL = HOME / "panel.html"
HOOK_MARKER = "FORTHMARK_HOOK=1"
HOOK_ARG = "--forthmark-hook"  # Windows: no shell to set a variable in, so the mark is an ignored argument


def ours(hook):
    """Whether a settings hook entry (or status line command) is one of ours."""
    text = hook if isinstance(hook, str) else " ".join([hook.get("command") or ""] + (hook.get("args") or [])) if hook else ""
    return HOOK_MARKER in text or HOOK_ARG in text


ACTIVITY_DAYS = 21  # the cadence strip: about three weeks is what "am I keeping it moving?" needs


# ---------------------------------------------------------------- registry

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"projects": {}}


def save_registry(reg):
    HOME.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def project_id(path):
    slug = re.sub(r"[^\w.-]+", "-", path.name).strip("-") or "project"
    return f"{slug}-{hashlib.sha1(os.path.normcase(str(path)).encode()).hexdigest()[:6]}"


def find_project(directory):
    """(id, entry) of the tracked project containing directory, or None."""
    directory = Path(native_path(directory)).expanduser().resolve()
    best = None
    for pid, entry in load_registry()["projects"].items():
        root = Path(entry["path"])
        if (directory == root or root in directory.parents) and (
                best is None or len(entry["path"]) > len(best[1]["path"])):
            best = (pid, entry)
    return best


def data_dir(pid):
    return HOME / "projects" / pid


def status_path(pid):
    return data_dir(pid) / "status.json"


def require_project(directory):
    found = find_project(directory)
    if not found:
        sys.exit(f"not tracked: {Path(directory).resolve()}\nrun: forthmark.py add {directory}")
    return found


def starter_status(name):
    now = now_iso()
    return {
        "version": 1, "project": {"name": name}, "updated_at": now, "deadline": None,
        "milestones": [], "next": None, "tasks": [], "waiting": [], "bugs": [], "decisions": [],
        "timeline": [{"at": now, "type": "note", "text": L("开始记录项目状态", "Started tracking this project")}],
    }


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git_root(path):
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path, capture_output=True,
                             encoding="utf-8", errors="replace", timeout=5, check=True).stdout.strip()
        return Path(out).resolve() if out else None
    except (subprocess.SubprocessError, FileNotFoundError, NotADirectoryError):
        return None


def register_project(path):
    """Track a directory (nothing is written into it). Returns (pid, newly_created)."""
    found = find_project(path)
    if found:
        return found[0], False
    pid = project_id(path)
    reg = load_registry()
    reg["projects"][pid] = {"path": str(path), "name": path.name, "added_at": now_iso()}
    save_registry(reg)
    d = data_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    if not status_path(pid).exists():
        write_json(status_path(pid), starter_status(path.name))
    return pid, True


def cmd_add(directory):
    path = Path(directory).expanduser().resolve()
    if not path.is_dir():
        sys.exit(f"not a directory: {path}")
    root = git_root(path)
    if root and root != path and "--here" not in sys.argv:
        print(f"using the repository root {root} (pass --here to track {path} itself)")
        path = root
    pid, created = register_project(path)
    print(f"tracking {path}" if created else f"already tracked: {load_registry()['projects'][pid]['path']}")
    print(f"status   {status_path(pid)}")
    print("nothing was written into the project.\n")
    print(rules_text(pid))
    return 0


def cmd_remove(directory):
    pid, entry = require_project(directory)
    reg = load_registry()
    del reg["projects"][pid]
    save_registry(reg)
    print(f"stopped tracking {entry['path']}\nstatus data kept in {data_dir(pid)}")
    render_panel()
    return 0


def cmd_move(_directory):
    """The project folder was moved or renamed: point its entry at the new place, keeping all its data."""
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit("usage: forthmark.py move OLD_PATH NEW_PATH   (after moving the folder)")
    old = os.path.normpath(os.path.abspath(os.path.expanduser(args[0])))
    new = Path(args[1]).expanduser().resolve()
    if not new.is_dir():
        sys.exit(f"not a directory: {new}")
    reg = load_registry()
    pid = next((k for k, e in reg["projects"].items() if e["path"] in (old, str(Path(old).resolve()))), None)
    if not pid:
        sys.exit(f"no tracked project at {old}\ntracked: " + ", ".join(e["path"] for e in reg["projects"].values()))
    clash = find_project(new)
    if clash and clash[0] != pid and clash[1]["path"] == str(new):
        sys.exit(f"{new} is already tracked as {clash[0]}; remove it first (forthmark.py remove {new})")
    reg["projects"][pid].update(path=str(new), name=new.name)
    save_registry(reg)
    if load_status(pid)["project"].get("name") == Path(old).name:  # still the folder name, not one the user chose
        apply_op(pid, "set_project", {"name": new.name}, source="")
    print(f"{pid}: {old} → {new}\nstatus, history and docs notes kept")
    render_panel()
    return 0


def cmd_prune(_directory):
    """Data dirs of projects that are no longer tracked (e.g. after /forthmark-remove)."""
    tracked_ids = set(load_registry()["projects"])
    orphans = [d for d in sorted((HOME / "projects").glob("*")) if d.is_dir() and d.name not in tracked_ids]
    if not orphans:
        print("no untracked project data")
        return 0
    for d in orphans:
        name = "?"
        try:
            name = json.loads((d / "status.json").read_text(encoding="utf-8"))["project"]["name"]
        except (OSError, ValueError, KeyError):
            pass
        print(f"{d.name:<28} {name}")
    if "--yes" in sys.argv:
        for d in orphans:
            shutil.rmtree(d)
        print(f"deleted {len(orphans)}")
    else:
        print("\nthese are not tracked any more; run with --yes to delete them")
    return 0


def cmd_list(_directory):
    reg = load_registry()["projects"]
    if not reg:
        print("no tracked projects. run: forthmark.py add <dir>")
    for pid, entry in reg.items():
        print(f"{entry['name']:<24} {entry['path']}")
    return 0


# ---------------------------------------------------------------- rules

def rules_text(pid):
    entry = load_registry()["projects"][pid]
    template = RULES_TEMPLATE.with_name("RULES.en.md") if ui_lang() == "en" else RULES_TEMPLATE
    return (template.read_text(encoding="utf-8")
            .replace("{STATUS_PATH}", str(status_path(pid)))
            .replace("{PROJECT}", entry["name"])
            .replace("{CLI}", CLI)
            .replace("{KIT}", str(KIT)))


def cmd_rules(directory):
    pid, _ = require_project(directory)
    print(rules_text(pid))
    return 0


# ---------------------------------------------------------------- validation

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "null": lambda v: v is None,
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def parse_date(s):
    return date.fromisoformat(s)


def parse_datetime(s):
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("missing timezone")
    return dt


FORMATS = {"date": parse_date, "date-time": parse_datetime}


def check_schema(value, schema, path, errors):
    """The JSON Schema subset that schema/status.schema.json uses."""
    types = schema.get("type")
    if types:
        types = [types] if isinstance(types, str) else types
        if not any(TYPE_CHECKS[t](value) for t in types):
            errors.append(f"{path}: expected {'/'.join(types)}, got {type(value).__name__}")
            return
    if value is None:
        return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        fmt = schema.get("format")
        if fmt in FORMATS:
            try:
                FORMATS[fmt](value)
            except ValueError as e:
                errors.append(f"{path}: {value!r} is not a valid {fmt} ({e})")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required field '{key}'")
        for key, sub in value.items():
            if key in props:
                check_schema(sub, props[key], f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unknown field '{key}'")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: {len(value)} items, max {schema['maxItems']}")
        for i, item in enumerate(value):
            check_schema(item, schema.get("items", {}), f"{path}[{i}]", errors)


def blocked_tasks(status):
    """task id -> ids of open waiting items / bugs blocking it."""
    blocked = {}
    for w in status.get("waiting", []):
        if w.get("status") == "open":
            for t in w.get("blocks", []):
                blocked.setdefault(t, []).append(w["id"])
    for b in status.get("bugs", []):
        if b.get("status") in ("open", "fixing"):
            for t in b.get("blocks", []):
                blocked.setdefault(t, []).append(b["id"])
    return blocked


def check_refs(status, project_path, errors, warnings):
    def ids(key):
        seen = set()
        for item in status.get(key, []):
            if item.get("id") in seen:
                errors.append(f"{key}: duplicate id {item['id']}")
            seen.add(item.get("id"))
        return seen

    task_ids, waiting_ids, milestone_ids = ids("tasks"), ids("waiting"), ids("milestones")
    ids("bugs")
    for key in ("waiting", "bugs"):
        for item in status.get(key, []):
            for t in item.get("blocks", []):
                if t not in task_ids:
                    errors.append(f"{key} {item['id']}: blocks unknown task {t}")
    for t in status.get("tasks", []):
        if t.get("milestone") and t["milestone"] not in milestone_ids:
            errors.append(f"task {t['id']}: unknown milestone {t['milestone']}")
    for d in status.get("decisions", []):
        if d.get("from_waiting") and d["from_waiting"] not in waiting_ids:
            errors.append(f"decision '{d['decision'][:30]}': unknown waiting {d['from_waiting']}")

    nxt = status.get("next")
    if nxt and nxt.get("task"):
        if nxt["task"] not in task_ids:
            errors.append(f"next: unknown task {nxt['task']}")
        elif nxt["task"] in blocked_tasks(status):
            warnings.append(f"next points to {nxt['task']}, which is blocked")
    for t in status.get("tasks", []):
        if t.get("status") == "paused" and not t.get("note"):
            warnings.append(f"task {t['id']}: paused without a note on where to pick up")
    for w in status.get("waiting", []):
        if w.get("status") == "open" and w.get("waiting_on") != "me" and not w.get("message_draft"):
            warnings.append(f"waiting {w['id']}: no message_draft for {w.get('waiting_on')}")
        if w.get("status") == "resolved" and not w.get("answer"):
            warnings.append(f"waiting {w['id']}: resolved without an answer")
    for key in ("tasks", "waiting", "bugs", "decisions"):
        for item in status.get(key, []):
            ref = item.get("ref")
            if ref and not (project_path / ref.split("#")[0]).exists():
                warnings.append(f"{key} {item.get('id', '')}: ref '{ref}' does not exist")
    try:
        if (datetime.now(timezone.utc) - parse_datetime(status["updated_at"])).total_seconds() < -300:
            warnings.append("updated_at is in the future")
    except (KeyError, ValueError):
        pass


def validate_status(status, project_path):
    errors, warnings = [], []
    check_schema(status, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")), "$", errors)
    if not errors:
        check_refs(status, project_path, errors, warnings)
    return errors, warnings


def validate_project(pid):
    """(errors, warnings) for a project's status file."""
    path = status_path(pid)
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"missing status file {path}"], []
    except json.JSONDecodeError as e:
        return [f"invalid JSON in {path}: {e}"], []
    return validate_status(merge_archive(status, load_archive(pid)), Path(load_registry()["projects"][pid]["path"]))


def cmd_validate(directory):
    pid, _ = require_project(directory)
    errors, warnings = validate_project(pid)
    for e in errors:
        print(f"ERROR {e}")
    for w in warnings:
        print(f"WARN  {w}")
    if not errors:
        print(f"OK    {status_path(pid)}" + (f" ({len(warnings)} warnings)" if warnings else ""))
    return 1 if errors else 0


def load_status(pid):
    """The live status file: what agents and operations edit."""
    return json.loads(status_path(pid).read_text(encoding="utf-8"))


# Finished history moves to archive.json so the file agents read stays small; every view
# for humans (panel, show, session start) uses the merged full status, so nothing disappears.
ARCHIVE_KEYS = ("tasks", "waiting", "bugs", "decisions", "timeline")
ARCHIVE_THRESHOLD = 12_000  # bytes of status.json before the Stop hook archives
KEEP = {"tasks": 5, "waiting": 5, "bugs": 5, "decisions": 10, "timeline": 12}
ARCHIVE_TIMELINE_MAX = 300


def archive_path(pid):
    return data_dir(pid) / "archive.json"


def load_archive(pid):
    p = archive_path(pid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {k: [] for k in ARCHIVE_KEYS}


def merge_archive(status, archive):
    full = dict(status)
    for k in ARCHIVE_KEYS:
        full[k] = status.get(k, []) + archive.get(k, [])
    full["timeline"] = full["timeline"][:30]  # newest first; views never show more
    return full


def full_status(pid):
    return merge_archive(load_status(pid), load_archive(pid))


def archive_status(pid, force=False):
    """Move old finished items to archive.json. Returns how many moved per kind."""
    if not force and status_path(pid).stat().st_size < ARCHIVE_THRESHOLD:
        return {}
    live, arch = load_status(pid), load_archive(pid)
    pinned = {(live.get("next") or {}).get("task")}
    for x in live["waiting"] + live["bugs"]:
        if x.get("status") in ("open", "fixing"):
            pinned |= set(x.get("blocks", []))
    finished = {
        "tasks": (lambda t: t["status"] in ("done", "dropped") and t["id"] not in pinned, lambda t: t.get("changed_at") or ""),
        "waiting": (lambda w: w["status"] == "resolved", lambda w: w.get("resolved_at") or ""),
        "bugs": (lambda b: b["status"] in ("fixed", "wontfix"), lambda b: b.get("closed_at") or ""),
    }
    moved = {}
    for k, (is_done, when) in finished.items():
        done = sorted([x for x in live[k] if is_done(x)], key=when)  # oldest first
        old = done[:-KEEP[k]] if len(done) > KEEP[k] else []
        if old:
            ids = {x["id"] for x in old}
            live[k] = [x for x in live[k] if x["id"] not in ids]
            arch[k] = old + arch.get(k, [])
            moved[k] = len(old)
    for k in ("decisions", "timeline"):  # both newest first
        if len(live[k]) > KEEP[k]:
            old = live[k][KEEP[k]:]
            live[k] = live[k][:KEEP[k]]
            arch[k] = (old + arch.get(k, []))[:ARCHIVE_TIMELINE_MAX if k == "timeline" else None]
            moved[k] = len(old)
    if moved:
        for path, data in ((archive_path(pid), arch), (status_path(pid), live)):
            tmp = path.with_suffix(".json.tmp")
            write_json(tmp, data)
            replace_file(tmp, path)
    return moved


# ---- what the user did in the panel, for sessions that are already running

def sync_path(pid):
    return data_dir(pid) / "sync.json"


def mark_synced(pid, session_id, when=None):
    p = sync_path(pid)
    sync = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    sync.pop(session_id or "?", None)  # re-insert so the dict order is "most recently seen" last
    sync[session_id or "?"] = when or now_iso()
    if len(sync) > 50:  # forget old sessions
        sync = dict(sorted(sync.items(), key=lambda kv: kv[1])[-50:])
    write_json(p, sync)


def panel_changes_since(pid, session_id, session_started=None):
    """Timeline entries recorded from the panel since this session last heard about them."""
    p = sync_path(pid)
    sync = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    since = sync.get(session_id or "?") or session_started
    if not since:
        return []
    cutoff = parse_datetime(since)
    return [e for e in full_status(pid)["timeline"]
            if from_panel(e["text"]) and parse_datetime(e["at"]) > cutoff][::-1]


def auto_verify(pid):
    """Resolve open 'do' items whose check now passes. Returns what was resolved."""
    project_path = Path(load_registry()["projects"][pid]["path"])
    done = []
    for w in load_status(pid)["waiting"]:
        if w["status"] == "open" and w.get("kind") == "do" and w.get("check") and run_check(w["check"], project_path)[0]:
            done.append(apply_op(pid, "resolve_waiting", {"id": w["id"], "answer": L("已完成", "Done")}, source="auto"))
    return done


def cmd_archive(directory):
    pid, _ = require_project(directory)
    before = status_path(pid).stat().st_size
    moved = archive_status(pid, force=True)
    print(f"archived {moved or 'nothing'}; status.json {before:,} -> {status_path(pid).stat().st_size:,} bytes")
    return 0


# ---------------------------------------------------------------- terminal view

def days_since(d):
    return (date.today() - parse_date(d)).days


def ago(ts):
    secs = (datetime.now(timezone.utc) - parse_datetime(ts)).total_seconds()
    if secs < 60:
        return L("刚刚", "just now")
    if secs < 3600:
        return L(f"{int(secs // 60)} 分钟前", f"{int(secs // 60)} min ago")
    if secs < 86400:
        return L(f"{int(secs // 3600)} 小时前", f"{int(secs // 3600)} h ago")
    return L(f"{int(secs // 86400)} 天前", f"{int(secs // 86400)} d ago")


def waiting_labels():
    return {"me": L("🙋 等你决定", "🙋 Your call"), "me-do": L("🛠 等你去做", "🛠 Your action"),
            "client": L("⏳ 等甲方/需求方", "⏳ Client"), "teammate": L("⏳ 等同事", "⏳ Teammate"),
            "external": L("⏳ 等外部", "⏳ External")}


def waiting_group(w):
    return "me-do" if w["waiting_on"] == "me" and w.get("kind") == "do" else w["waiting_on"]


def show_text(status):
    out = []
    p = out.append
    live = [t for t in status["tasks"] if t["status"] != "dropped"]
    done = sum(t["status"] == "done" for t in live)
    blocked = blocked_tasks(status)

    p(f"■ {status['project']['name']}    {L('更新于', 'updated')} {ago(status['updated_at'])}")
    if status["project"].get("goal"):
        p(f"  {L('目标：', 'Goal: ')}{status['project']['goal']}")
    ms = status.get("milestones", [])
    if ms:
        marks = {"done": "●", "active": "◉", "pending": "○"}
        p(L("  阶段：", "  Phases: ") + " ━ ".join(f"{marks[m['status']]}{m['title']}" for m in ms))
    line = f"  {L('任务：', 'Tasks: ')}{done}/{len(live)}" + (f" ({done * 100 // len(live)}%)" if live else "")
    if status.get("deadline"):
        line += f"    deadline {status['deadline']}" + L(f"（剩 {-days_since(status['deadline'])} 天）", f" ({-days_since(status['deadline'])} days left)")
    p(line)

    nxt = status.get("next")
    p(f"\n▶ {L('下一步：', 'Next: ')}{nxt['title'] if nxt else L('（未设置）', '(not set)')}")
    if nxt and nxt.get("why"):
        p(f"  {nxt['why']}")

    open_w = [w for w in status["waiting"] if w["status"] == "open"]
    if open_w:
        p(L("\n卡在谁", "\nWho's blocking"))
        for kind in ("me", "me-do", "client", "teammate", "external"):
            group = [w for w in open_w if waiting_group(w) == kind]
            if group:
                p(f"  {waiting_labels()[kind]} ({len(group)})")
                for w in group:
                    d = days_since(w["since"])
                    who = f" · {w['who']}" if w.get("who") else ""
                    p(f"    [{w['id']}] {w['question']}  {L(f'已等 {d} 天', f'waiting {d}d')}{' 🔴' if d >= 3 else ''}{who}")
                    if w.get("blocks"):
                        p(f"         └ {L('阻塞：', 'blocks: ')}{', '.join(w['blocks'])}")

    open_b = [b for b in status["bugs"] if b["status"] in ("open", "fixing")]
    if open_b:
        p(L(f"\n🐞 Bug（{len(open_b)} 未修）", f"\n🐞 Bugs ({len(open_b)} open)"))
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for b in sorted(open_b, key=lambda b: order[b["severity"]]):
            p(f"    [{b['id']}] {b['title']}  [{b['severity']}{L(' · 修复中', ' · fixing') if b['status'] == 'fixing' else ''}]")

    cols = {"todo": [], "doing": [], "paused": [], "done": []}
    for t in live:
        cols[t["status"]].append(t)
    if cols["paused"]:
        p(L(f"\n⏸ 暂停中，回头继续（{len(cols['paused'])}）", f"\n⏸ Paused ({len(cols['paused'])})"))
        for t in cols["paused"]:
            since = L(f"  已停 {days_since(t['paused_at'])} 天", f"  paused {days_since(t['paused_at'])}d") if t.get("paused_at") else ""
            p(f"    [{t['id']}] {t['title']}{since}")
            if t.get("note"):
                p(f"         ↳ {t['note']}")
    p(L(f"\n看板  待办 {len(cols['todo'])} │ 进行中 {len(cols['doing'])} │ 暂停 {len(cols['paused'])} │ 完成 {len(cols['done'])}",
      f"\nBoard  to do {len(cols['todo'])} │ doing {len(cols['doing'])} │ paused {len(cols['paused'])} │ done {len(cols['done'])}"))
    for t in cols["doing"] + cols["todo"]:
        mark = "⛔" if t["id"] in blocked else ("⚡" if t.get("urgent") else "…" if t["status"] == "doing" else " ")
        why = f"  ← {', '.join(blocked[t['id']])}" if t["id"] in blocked else ""
        p(f"  {mark} [{t['id']}] {t['title']}{why}")

    tl = status.get("timeline", [])[:5]
    if tl:
        p(L("\n🕒 最近", "\n🕒 Recent"))
        for e in tl:
            p(f"    {ago(e['at']):<8} {e['text']}")
    return "\n".join(out)


def cmd_show(directory):
    pid, _ = require_project(directory)
    print(show_text(full_status(pid)))
    print(f"\n{L('面板：', 'Panel: ')}{PANEL}")
    return 0


def cmd_stats(directory):
    pid, _ = require_project(directory)
    path = data_dir(pid) / "hook-log.jsonl"
    if not path.exists():
        sys.exit("no hook runs recorded yet")
    counts, days = {}, set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        counts[entry["result"]] = counts.get(entry["result"], 0) + 1
        days.add(entry["at"][:10])
    checked = sum(counts.get(k, 0) for k in ("ok", "stale", "invalid"))
    print(L(f"天数 {len(days)} · 会话结束检查 {checked} 次", f"{len(days)} days · {checked} end-of-turn checks"))
    for key, label in (("ok", L("自觉更新", "kept up on its own")), ("stale", L("被拦下补更新", "asked to catch up")),
                       ("invalid", L("格式错误", "invalid format"))):
        n = counts.get(key, 0)
        print(f"  {label}  {n}  ({n * 100 // checked if checked else 0}%)")
    us = usage_summary(pid)
    if us["total"]:
        print(L(f"工具开销 {fmt_tokens(us['overhead'])}+ tokens，占本项目会话 {us['overhead'] * 100 / us['total']:.1f}%"
                f"（会话共 {fmt_tokens(us['total'])}；只算新增 token，不含缓存读取；"
                "+ 为未计入的注入上下文和日常状态更新）",
                f"Tool overhead {fmt_tokens(us['overhead'])}+ tokens, {us['overhead'] * 100 / us['total']:.1f}% of this project's sessions"
                f" (sessions total {fmt_tokens(us['total'])}; new tokens only, no cache reads;"
                " + is injected context and routine status updates, not counted)"))
    return 0


# ---------------------------------------------------------------- token overhead
# The Stop hook reads the session transcript incrementally. Only "new" tokens count
# (input + cache writes + output; cache reads are excluded). Turns the agent had to take
# because the hook blocked it are attributed to this tool exactly; smaller costs (the
# injected rules and status, routine status edits) are not counted, hence "N+".

def usage_path(pid):
    return data_dir(pid) / "usage.json"


def load_usage(pid):
    p = usage_path(pid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"sessions": {}, "days": {}}


def record_usage(pid, transcript, session_id, blocking):
    """Add new calls since the last run; a turn that follows a block is overhead."""
    if not transcript or not os.path.exists(transcript):
        return
    u = load_usage(pid)
    sess = u["sessions"].setdefault(session_id or "?", {"offset": 0, "retry": False, "seen": []})
    seen = set(sess["seen"])
    calls = {}
    with open(transcript, "rb") as f:
        f.seek(sess["offset"] if sess["offset"] <= os.path.getsize(transcript) else 0)
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            m = e.get("message")
            if e.get("type") != "assistant" or not isinstance(m, dict) or not m.get("usage"):
                continue
            mid = m.get("id") or e.get("uuid")
            if mid in seen:
                continue  # one API call is written as several transcript lines
            k = m["usage"]
            calls[mid] = (k.get("input_tokens") or 0) + (k.get("cache_creation_input_tokens") or 0) + (k.get("output_tokens") or 0)
        sess["offset"] = f.tell()
    new = sum(calls.values())
    day = u["days"].setdefault(date.today().isoformat(), {"total": 0, "overhead": 0})
    day["total"] += new
    if sess["retry"]:
        day["overhead"] += new
    sess["retry"] = blocking
    sess["seen"] = (sess["seen"] + list(calls))[-200:]
    tmp = usage_path(pid).with_suffix(".json.tmp")
    write_json(tmp, u)
    replace_file(tmp, usage_path(pid))


def usage_summary(pid):
    days = load_usage(pid)["days"].values()
    return {"total": sum(d["total"] for d in days), "overhead": sum(d["overhead"] for d in days)}


def fmt_tokens(n):
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


# ---------------------------------------------------------------- panel

def git_out(project_path, *args):
    try:
        return subprocess.run(["git", *args], cwd=project_path, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=10, check=True).stdout.split()
    except (subprocess.SubprocessError, FileNotFoundError, NotADirectoryError):
        return []


def local_day(ts):
    return parse_datetime(ts).astimezone().date().isoformat()


def record_history(pid, status):
    """One progress snapshot per day (last write of the day wins)."""
    live = [t for t in status["tasks"] if t["status"] != "dropped"]
    snap = {
        "date": date.today().isoformat(),
        "done": sum(t["status"] == "done" for t in live),
        "total": len(live),
        "waiting": sum(w["status"] == "open" for w in status["waiting"]),
        "bugs": sum(b["status"] in ("open", "fixing") for b in status["bugs"]),
    }
    path = data_dir(pid) / "history.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    rows = [r for r in rows if r["date"] != snap["date"]] + [snap]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return rows


def lifetime_activity(project_path, status, since):
    """Days since the project began and how many of them saw activity (commits or status changes)."""
    if not since:
        return None
    days = set(git_out(project_path, "log", f"--since={since}", "--format=%ad", "--date=short"))
    days |= {local_day(e["at"]) for e in status["timeline"]}
    return {"age": (date.today() - parse_date(since)).days + 1, "active": len(days)}


def project_panel_data(pid, entry):
    status = full_status(pid)
    project_path = Path(entry["path"])
    today = date.today()
    days = [(today - timedelta(days=i)).isoformat() for i in range(ACTIVITY_DAYS - 1, -1, -1)]
    commits, events = {}, {}
    for d in git_out(project_path, "log", f"--since={ACTIVITY_DAYS} days ago", "--format=%ad", "--date=short"):
        commits[d] = commits.get(d, 0) + 1
    for e in status["timeline"]:
        d = local_day(e["at"])
        events[d] = events.get(d, 0) + 1
    activity = [{"date": d, "commits": commits.get(d, 0), "events": events.get(d, 0),
                 "count": commits.get(d, 0) + events.get(d, 0)} for d in days]
    streak = 0
    for a in reversed(activity[:-1] if activity[-1]["count"] == 0 else activity):
        if not a["count"]:
            break
        streak += 1
    last = [parse_datetime(status["updated_at"])]
    last += [parse_datetime(t) for t in git_out(project_path, "log", "-1", "--format=%cI")]
    # When the project began, so days before it aren't drawn as "inactive".
    starts = [local_day(e["at"]) for e in status["timeline"]]
    starts += [entry["added_at"][:10]] if entry.get("added_at") else []
    roots = git_out(project_path, "rev-list", "--max-parents=0", "HEAD")
    if roots:
        starts += git_out(project_path, "log", "-1", "--format=%ad", "--date=short", roots[-1])
    docs, missing = doc_entries(pid, entry, status)
    return {
        "id": pid,
        "path": entry["path"],
        "since": min(starts) if starts else None,
        "lifetime": lifetime_activity(project_path, status, min(starts) if starts else None),
        "docs": docs,
        "docs_missing": missing,
        "status": status,
        "blocked": blocked_tasks(status),
        "activity": activity,
        "streak": streak,
        "active_days": sum(a["count"] > 0 for a in activity),
        "today_done": sum(e["type"] == "done" and local_day(e["at"]) == today.isoformat()
                          for e in status["timeline"]),
        "history": record_history(pid, status),
        "usage": usage_summary(pid),
        "last_activity": max(last).isoformat(),
    }


def render_panel():
    """Static fallback panel (file://). Broken status files are skipped, not fatal."""
    HOME.mkdir(parents=True, exist_ok=True)
    PANEL.write_text(panel_page(panel_payload()), encoding="utf-8")
    return PANEL


CHROME_PATHS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe")]


def cmd_check(_directory):
    """Render the panel and load every project/tab in headless Chrome; fail on JS errors or empty pages."""
    chrome = os.environ.get("FORTHMARK_CHROME") or next((c for c in CHROME_PATHS if os.path.exists(c)), None)
    if not chrome:
        sys.exit("no Chrome/Chromium found (set FORTHMARK_CHROME)")
    path = render_panel()
    projects = list(load_registry()["projects"]) or [""]
    failures = 0
    for pid in projects:
        for tab in ("overview", "board", "feed", "docs"):
            url = f"file://{path}#p={pid}&tab={tab}&f=all"
            try:
                r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--virtual-time-budget=2000",
                                    "--enable-logging=stderr", "--v=0", "--dump-dom", url],
                                   capture_output=True, text=True, timeout=30)
                errors = [l.split('"', 1)[-1].rsplit('", source', 1)[0] for l in r.stderr.splitlines()
                          if "CONSOLE" in l and ("Uncaught" in l or "Error" in l)]
                empty = 'class="card' not in r.stdout and 'class="card ' not in r.stdout
            except subprocess.TimeoutExpired:
                try:  # headless Chrome occasionally hangs; one retry before calling it a failure
                    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--virtual-time-budget=2000",
                                        "--enable-logging=stderr", "--v=0", "--dump-dom", url],
                                       capture_output=True, text=True, timeout=30)
                    errors = [l for l in r.stderr.splitlines() if "CONSOLE" in l and "Uncaught" in l]
                    empty = 'class="card' not in r.stdout
                except subprocess.TimeoutExpired:
                    errors, empty = ["timed out twice"], True
            ok = not errors and not empty
            failures += not ok
            print(f"{'OK ' if ok else 'ERR'} {pid or '(no projects)'} / {tab}" +
                  ("" if ok else f"  {'; '.join(errors) or 'page rendered no cards'}"))
    return 1 if failures else 0


def open_path(target):
    """Open a file or URL with the system's default app."""
    if IS_WINDOWS:
        os.startfile(str(target))
    else:
        subprocess.run(["open", str(target)])


def cmd_html(_directory):
    path = render_panel()
    print(path)
    if "--open" in sys.argv:
        open_path(path)
    return 0


# ---------------------------------------------------------------- documents
# Read-only discovery of a project's docs and scripts, plus an overlay (tags, notes,
# pins, roles) stored on our side in docs.json. Project files are never written.

DOC_EXTS = {".md", ".markdown", ".mdx", ".txt", ".sh", ".bash", ".zsh", ".command", ".ps1", ".bat", ".cmd"}
SCRIPT_EXTS = {".sh", ".bash", ".zsh", ".command", ".ps1", ".bat", ".cmd"}
DOC_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next", "__pycache__", "vendor"}
DOC_LIMIT = 400
PREVIEW_LIMIT = 1_000_000
DOC_ROLES = ("progress", "todo", "plan", "spec", "guide", "notes", "agent", "script", "other")
SOURCE_RE = re.compile(r"^(progress|todo|roadmap|status|changelog|进度|待办)([-_. ]|$)", re.I)
CHECK_RE = re.compile(r"^\s*[-*+]\s+\[([ xX])\]", re.M)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.M)


def docs_meta_path(pid):
    return data_dir(pid) / "docs.json"


def load_docs_meta(pid):
    p = docs_meta_path(pid)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_docs_meta(pid, meta):
    tmp = docs_meta_path(pid).with_suffix(".json.tmp")
    write_json(tmp, meta)
    replace_file(tmp, docs_meta_path(pid))


def list_doc_files(project_path):
    """Relative paths of docs/scripts: git-tracked plus untracked-but-not-ignored, else a pruned walk."""
    try:
        rels = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=project_path,
                              capture_output=True, encoding="utf-8", errors="replace", timeout=10, check=True).stdout.split("\0")
    except (subprocess.SubprocessError, FileNotFoundError, NotADirectoryError):
        rels = None
    if not rels or rels == [""]:
        rels = []
        for root, dirs, names in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in DOC_SKIP_DIRS and not d.startswith(".")]
            rels += [os.path.relpath(os.path.join(root, n), project_path).replace(os.sep, "/") for n in names]
    out = [r for r in rels if r and Path(r).suffix.lower() in DOC_EXTS
           and not any(part in DOC_SKIP_DIRS for part in Path(r).parts[:-1])]
    return sorted(set(out))[:DOC_LIMIT]


def doc_entries(pid, entry, status):
    project_path = Path(entry["path"])
    meta = load_docs_meta(pid)
    refs = {}
    for key in ("tasks", "waiting", "bugs"):
        for item in status.get(key, []):
            if item.get("ref"):
                refs.setdefault(item["ref"].split("#")[0], []).append(item["id"])
    status_time = parse_datetime(status["updated_at"]).timestamp()
    docs = []
    for rel in list_doc_files(project_path):
        full = project_path / rel
        try:
            st = full.stat()
        except OSError:
            continue
        ext = full.suffix.lower()
        m = meta.get(rel, {})
        doc = {"path": rel, "ext": ext, "size": st.st_size, "mtime": st.st_mtime,
               "script": ext in SCRIPT_EXTS, "refs": refs.get(rel, []), **m}
        if ext not in SCRIPT_EXTS and st.st_size <= 512_000:
            text = full.read_text(encoding="utf-8", errors="replace")
            boxes = CHECK_RE.findall(text)
            if boxes:
                doc["checks"] = {"done": sum(b != " " for b in boxes), "total": len(boxes)}
            title = TITLE_RE.search(text)
            if title:
                doc["title"] = title.group(1).strip()[:80]
        role = m.get("role") or ("script" if ext in SCRIPT_EXTS else None)
        if not role and SOURCE_RE.match(full.stem):  # PROGRESS.md, TODO.md, 进度.md … until the agent says otherwise
            role = "todo" if re.match(r"(todo|待办)", full.stem, re.I) else "progress"
        doc["role"] = role
        doc["source"] = role in ("progress", "todo")
        if doc["source"]:
            doc["newer_than_status"] = st.st_mtime > status_time + 1
        docs.append(doc)
    found = {d["path"] for d in docs}
    missing = [{"path": k, "missing": True, **v} for k, v in meta.items() if k not in found]
    return docs, missing


def stale_sources(pid, entry, status):
    docs, _ = doc_entries(pid, entry, status)
    return [d["path"] for d in docs if d.get("newer_than_status")]


def safe_doc_path(pid, rel):
    """Absolute path of a doc inside the tracked project, or OpError. Only whitelisted types."""
    root = Path(load_registry()["projects"][pid]["path"]).resolve()
    full = (root / rel).resolve()
    if root not in full.parents or full.suffix.lower() not in DOC_EXTS or not full.is_file():
        raise OpError("not a readable document in this project")
    return full


def read_doc(pid, rel):
    full = safe_doc_path(pid, rel)
    size = full.stat().st_size
    if size > PREVIEW_LIMIT:
        raise OpError("file too large to preview; open it in your editor")
    return {"path": rel, "ext": full.suffix.lower(), "size": size,
            "text": full.read_text(encoding="utf-8", errors="replace")}


def doc_set_meta(pid, rel, **fields):
    """Update our overlay for one doc. Empty values remove the field."""
    meta = load_docs_meta(pid)
    m = meta.setdefault(rel, {})
    for k, v in fields.items():
        if k == "role" and v and v not in DOC_ROLES:
            raise OpError(f"role must be one of {', '.join(DOC_ROLES)}")
        if k == "tags" and isinstance(v, str):
            v = [t.strip() for t in re.split(r"[,，]", v) if t.strip()]
        if v in (None, "", [], False):
            m.pop(k, None)
        else:
            m[k] = v
    if not m:
        meta.pop(rel, None)
    save_docs_meta(pid, meta)


def cmd_doc(_directory):
    """forthmark.py doc PATH [role=plan] [purpose=...] [tags=a,b] — register what a doc is for."""
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    if not args:
        sys.exit("usage: forthmark.py doc PATH [role=…] [purpose=…] [tags=a,b]   roles: " + ", ".join(DOC_ROLES))
    pid, entry = require_project(".")
    rel = os.path.relpath(Path(args[0]).resolve(), Path(entry["path"]).resolve())
    try:
        safe_doc_path(pid, rel)
        doc_set_meta(pid, rel, **dict(a.split("=", 1) for a in args[1:]))
    except OpError as e:
        sys.exit(f"error: {e}")
    print(f"{rel}: {load_docs_meta(pid).get(rel, {})}")
    return 0


def cmd_docs(directory):
    pid, entry = require_project(directory)
    docs, missing = doc_entries(pid, entry, full_status(pid))
    for d in docs:
        mark = "★" if d.get("source") else " "
        print(f"{mark} {d['path']:<48} {d.get('role') or '-':<9} {d.get('purpose') or d.get('title') or ''}")
    for d in missing:
        print(f"? {d['path']:<48} {L('(找不到文件)', '(file not found)')}")
    return 0


# ---------------------------------------------------------------- config & launching agents
# The reverse channel: start (or continue) a project from the panel by opening the user's own
# agent in their terminal. We only type the command for them; no LLM is called here.

# Variables that belong to one running Claude Code session. If the service was started from inside a
# session they leak into it, and an agent launched from the panel then believes it is a child session
# (transcript saving off, so it can't be resumed) and receives that session's messaging token.
SESSION_ENV = ("CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_EXECPATH",
               "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SESSION_ATTENDED",
               "CLAUDE_CODE_SESSION_ID", "CLAUDE_EFFORT", "CLAUDE_JOB_DIR", "CLAUDE_PID")


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in SESSION_ENV}


CONFIG_PATH = HOME / "config.json"
DEFAULT_CONFIG = {
    "terminal": "auto",               # auto (Ghostty if installed, else Terminal) | ghostty | terminal
                                      # Windows: auto (Windows Terminal if installed, else PowerShell) | windows-terminal | powershell
    # Three ways in, all the agent's own: we only type the command (Codex: "codex",
    # "codex resume --last", "codex resume").
    "agent": "claude",                # ＋ new session; it starts empty: the first message is always the user's
    "resume_last": "claude --continue",  # ▶ the most recent session in that folder (the agent decides which)
    "resume_pick": "claude --resume",    # ☰ the agent's own session picker
    "projects_dir": "~/Documents",    # where new projects go
    "git_init": True,                 # git init new project folders
    "lang": "auto",                   # auto (the system language) | zh | en
}
TERMINALS = ("auto", "windows-terminal", "powershell") if IS_WINDOWS else ("auto", "ghostty", "terminal")


def pick_terminal(choice):
    if choice != "auto":
        return choice
    if IS_WINDOWS:
        return "windows-terminal" if shutil.which("wt") else "powershell"
    apps = (Path("/Applications/Ghostty.app"), Path.home() / "Applications" / "Ghostty.app")
    return "ghostty" if any(a.exists() for a in apps) else "terminal"


def system_lang():
    """'zh' when the system's first preferred language is Chinese, else 'en'. Cached for a day: `defaults` is slow."""
    cache = HOME / "lang.cache"
    try:
        if time.time() - cache.stat().st_mtime < 86400:
            return cache.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    first = ""
    try:
        if IS_WINDOWS:
            import ctypes
            first = "zh" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04 else "en"  # LANG_CHINESE
        else:
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"], capture_output=True, text=True, timeout=3).stdout
            first = out.strip("()\n ").split(",")[0].strip().strip('"')
    except (OSError, subprocess.SubprocessError):
        pass
    first = first or os.environ.get("LANG", "")
    lang = "zh" if first.lower().startswith("zh") else "en"
    try:
        cache.write_text(lang, encoding="utf-8")
    except OSError:
        pass
    return lang


_LANG_MEMO = [None, None]  # (config mtime, lang): L() is called a lot, config.json rarely changes


def ui_lang():
    """The interface language: FORTHMARK_LANG, else config "lang", else the system language."""
    if os.environ.get("FORTHMARK_LANG") in ("zh", "en"):
        return os.environ["FORTHMARK_LANG"]
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        mtime = 0
    if _LANG_MEMO[0] != mtime:
        lang = load_config().get("lang", "auto")
        _LANG_MEMO[:] = [mtime, lang if lang in ("zh", "en") else system_lang()]
    return _LANG_MEMO[1]


def L(zh, en):
    """What the tool itself says, in the interface language. What agents and users wrote stays as written."""
    return en if ui_lang() == "en" else zh


# Timeline entries made outside the agent's own commands carry where they came from; the UserPromptSubmit
# hook passes panel entries on to the session. Both languages are recognised: the language can change.
SOURCE_SUFFIX = {"panel": ("（面板）", " (panel)"), "auto": ("（自动核实）", " (auto-verified)")}


def source_suffix(source):
    zh, en = SOURCE_SUFFIX[source]
    return L(zh, en)


def from_panel(text):
    return text.endswith(SOURCE_SUFFIX["panel"])


def strip_source(text):
    for zh, en in SOURCE_SUFFIX.values():
        for suffix in (zh, en):
            if text.endswith(suffix):
                return text[:-len(suffix)]
    return text


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except ValueError:
            pass
    return cfg


def powershell_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def write_windows_launch(script, path, command):
    lines = [f"Remove-Item Env:{k} -ErrorAction SilentlyContinue" for k in SESSION_ENV]
    lines += [f"Set-Location -LiteralPath {powershell_quote(path)}", command, ""]
    script.write_text("\n".join(lines), encoding="utf-8-sig")  # Windows PowerShell reads a file without a BOM as ANSI


def launch_windows(path, script, terminal):
    powershell = ["powershell", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    if terminal == "windows-terminal":
        subprocess.Popen(["wt", "-d", str(path).replace(";", "\\;")] + powershell, env=clean_env())  # ";" separates wt commands
    else:
        subprocess.Popen(powershell, cwd=path, env=clean_env(), creationflags=subprocess.CREATE_NEW_CONSOLE)


def launch_agent(path, command=None):
    """Open a new terminal window in `path` running the user's agent, with nothing typed for them:
    the first message is always the user's. `command` replaces the agent command (e.g. to resume)."""
    cfg = load_config()
    if cfg["terminal"] not in TERMINALS:
        raise OpError(L(f"不支持的终端 {cfg['terminal']}（可用：{', '.join(TERMINALS)}）", f"unsupported terminal {cfg['terminal']} (available: {', '.join(TERMINALS)})"))
    launch_dir = HOME / "launch"
    launch_dir.mkdir(parents=True, exist_ok=True)
    for old in launch_dir.iterdir():  # leftovers older than a day
        try:
            if time.time() - old.stat().st_mtime > 86400:
                old.unlink(missing_ok=True)
        except OSError:  # Windows: a script still in use can't be deleted
            pass
    stamp = f"{int(time.time() * 1000)}"
    # "{prompt}" is from configs written before the first message became the user's; it expands to nothing.
    agent = cfg["agent"].replace("{prompt}", "").strip()
    if IS_WINDOWS:
        script = launch_dir / f"{stamp}.ps1"
        write_windows_launch(script, path, command or agent)
        try:
            return launch_windows(path, script, pick_terminal(cfg["terminal"]))
        except OSError as e:
            raise OpError(L("打不开终端：", "couldn't open the terminal: ") + str(e))
    # -i as well as -l: many people set PATH (and so reach the agent) only in .zshrc
    lines = ["#!/bin/zsh -il", f"unset {' '.join(SESSION_ENV)}", f"cd {shlex.quote(str(path))} || exit 1", command or agent]
    script = launch_dir / f"{stamp}.command"
    script.write_text("\n".join(lines + ["exec zsh -l", ""]), encoding="utf-8")
    script.chmod(0o700)
    if pick_terminal(cfg["terminal"]) == "ghostty":
        cmd = ["open", "-na", "Ghostty", "--args", "-e", "/bin/zsh", "-il", str(script)]
    else:
        cmd = ["open", "-a", "Terminal", str(script)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=clean_env())
    if r.returncode != 0:
        raise OpError(L("打不开终端：", "couldn't open the terminal: ") + str(r.stderr.strip() or r.returncode))


def create_project(name, directory="", goal="", adopt=False):
    """New folder (optionally git init), tracked from day one, and the user's agent opened in it.
    The goal is shown on the panel (and is part of the status the agent sees at session start);
    nothing is sent to the agent: what to say first is the user's call."""
    name = name.strip()
    if not name or "/" in name or name.startswith("."):
        raise OpError(L("项目名不能为空，不能包含 /，也不能以 . 开头", "the name can't be empty, contain /, or start with ."))
    if IS_WINDOWS and (re.search(r'[<>:"\\|?*]', name) or name.endswith((".", " "))):
        raise OpError(L('项目名不能包含 < > : " \\ | ? *，也不能以空格或 . 结尾', 'the name can\'t contain < > : " \\ | ? * or end with a space or .'))
    cfg = load_config()
    path = Path(os.path.expanduser(directory.strip() or str(Path(os.path.expanduser(cfg["projects_dir"])) / name))).resolve()
    if path.exists() and any(path.iterdir()) and not adopt:
        raise OpError(L("目录已存在且不为空：", "folder exists and isn't empty: ") + str(path))
    path.mkdir(parents=True, exist_ok=True)
    if cfg.get("git_init") and not (path / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=path, capture_output=True, timeout=15)
    pid, _ = register_project(path)
    status = load_status(pid)
    status["project"]["name"] = name
    if goal.strip():
        status["project"]["goal"] = goal.strip().splitlines()[0][:200]
    write_json(status_path(pid), status)
    apply_op(pid, "note", {"text": L("从面板新建项目：", "Created from the panel: ") + str(path)}, source="")
    launch_agent(path)
    return pid


SESSION_MODES = {"new": ("开了一个新会话", "Started a new session"), "last": ("回到了最近的会话", "Resumed the most recent session"),
                 "pick": ("打开了会话列表", "Opened the session picker")}


def open_session(pid, mode):
    """Open the user's agent in the project: a new session, the most recent one, or its own picker.
    Which session is "most recent" and how sessions are listed is the agent's business, not ours;
    a new session gets the project's facts from the SessionStart hook, nothing else."""
    entry = load_registry()["projects"].get(pid)
    if not entry:
        raise OpError(f"unknown project {pid}")
    cfg = load_config()
    path = Path(entry["path"])
    if mode == "new":
        launch_agent(path)
    elif mode == "last":
        launch_agent(path, command=cfg["resume_last"])
    elif mode == "pick":
        launch_agent(path, command=cfg["resume_pick"])
    else:
        raise OpError(f"unknown session mode {mode}")
    zh, en = SESSION_MODES[mode]
    return L(f"已在终端里{zh}", f"{en} in the terminal")


def cmd_new(_directory):
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    if not args:
        sys.exit('usage: forthmark.py new NAME [--dir=PATH] [--goal="…"]')
    opts = dict(a[2:].split("=", 1) for a in sys.argv[2:] if a.startswith("--") and "=" in a)
    try:
        pid = create_project(args[0], opts.get("dir", ""), opts.get("goal", ""))
    except OpError as e:
        sys.exit(f"error: {e}")
    print(f"created and tracking {load_registry()['projects'][pid]['path']}; the agent is starting in your terminal")
    return 0


def _session_cmd(mode):
    def run(directory):
        pid, _ = require_project(directory)
        try:
            print(open_session(pid, mode))
        except OpError as e:
            sys.exit(f"error: {e}")
        return 0
    return run


cmd_session, cmd_continue, cmd_sessions = _session_cmd("new"), _session_cmd("last"), _session_cmd("pick")


# ---------------------------------------------------------------- operations
# Deterministic edits shared by every front end (panel buttons via the local service,
# the CLI, and later MCP). Each one validates the result and writes atomically.

class OpError(Exception):
    pass


_ARCHIVED = {}  # archived items by id prefix, so new ids never reuse an archived one


def _find(items, item_id, kind):
    for item in items:
        if item.get("id") == item_id:
            return item
    raise OpError(f"unknown {kind} {item_id}")


def run_check(check, project_path):
    """Evaluate a read-only 'done' condition. Returns (ok, why-not)."""
    for cond in [c.strip() for c in check.split("&&") if c.strip()]:
        kind, _, rest = cond.partition(":")
        drive = 2 if re.match(r"\s*[A-Za-z]:[\\/]", rest) else 0  # "contains:C:\\x:text"
        path, _, text = rest[drive:].partition(":") if kind == "contains" else (rest[drive:], "", "")
        path = rest[:drive] + path
        full = Path(os.path.expanduser(path.strip()))
        if not full.is_absolute():
            full = project_path / full
        if kind == "exists" and not full.exists():
            return False, L(f"{path} 不存在", f"{path} doesn't exist")
        if kind == "missing" and full.exists():
            return False, L(f"{path} 还在", f"{path} still exists")
        if kind == "contains":
            try:
                if text not in full.read_text(encoding="utf-8", errors="replace"):
                    return False, L(f"{path} 里没有「{text}」", f"{path} doesn't contain \"{text}\"")
            except OSError:
                return False, L(f"{path} 读不到", f"can't read {path}")
        if kind not in ("exists", "missing", "contains"):
            return False, L("看不懂的条件：", "unknown condition: ") + cond
    return True, ""


_PROJECT_PATH = {}  # set by apply_op so checks resolve relative paths inside the project


def op_resolve_waiting(status, id, answer="", by="me", force=False):
    w = _find(status["waiting"], id, "waiting item")
    if w["status"] != "open":
        raise OpError(f"{id} is already resolved")
    if w.get("kind") == "do" and w.get("check") and not force:
        ok, why = run_check(w["check"], _PROJECT_PATH.get("path", Path(".")))
        if not ok:
            raise OpError(L("核实没通过：", "Check failed: ") + why)
    answer = answer.strip() or (L("已完成", "Done") if w.get("kind") == "do" else "")
    if not answer:
        raise OpError("an answer is required")
    today = date.today().isoformat()
    w.update(status="resolved", answer=answer, resolved_at=today)
    if w["waiting_on"] == "me" and w.get("kind") != "do":
        status["decisions"].insert(0, {"date": today, "decision": f"{w['question']} → {answer}", "from_waiting": id})
        return L(f"决定：{w['question']} → {answer}", f"Decided: {w['question']} → {answer}"), "resolved"
    who = L("已完成", "Done") if w.get("kind") == "do" else L("已答复", "Answered")
    return f"{who}{L('：', ': ')}{w['question']}" + ("" if answer in ("已完成", "Done") else f" → {answer}"), "resolved"


def oldest_paused(status):
    paused = [t for t in status["tasks"] if t["status"] == "paused"]
    return min(paused, key=lambda t: t.get("paused_at") or "") if paused else None


def op_set_task(status, id, status_value, note=None):
    if status_value not in ("todo", "doing", "paused", "done", "dropped"):
        raise OpError(f"bad task status {status_value}")
    t = _find(status["tasks"], id, "task")
    was = t["status"]
    t["status"] = status_value
    t["changed_at"] = date.today().isoformat()
    if status_value == "paused":
        t["paused_at"] = t["changed_at"]
        if note:
            t["note"] = note
    else:
        t.pop("paused_at", None)
    if status_value in ("done", "dropped"):
        t.pop("note", None)
        t.pop("urgent", None)
        if (status.get("next") or {}).get("task") == id:
            back = oldest_paused(status)  # finishing an interruption: suggest going back
            status["next"] = ({"task": back["id"], "title": back["title"], "why": L("回到被打断的工作", "back to the interrupted work") +
                               (L("：", ": ") + back["note"] if back.get("note") else "")} if back else None)
    label = {"todo": L("移回待办", "Back to to-do"), "doing": L("继续", "Resumed") if was == "paused" else L("开始", "Started"),
             "paused": L("暂停", "Paused"), "done": L("完成", "Done"), "dropped": L("放弃", "Dropped")}[status_value]
    suffix = L(f"（{note}）", f" ({note})") if status_value == "paused" and note else ""
    return f"{label}{L('：', ': ')}{t['title']}{suffix}", "done" if status_value == "done" else "note"


def op_set_bug(status, id, status_value):
    if status_value not in ("open", "fixing", "fixed", "wontfix"):
        raise OpError(f"bad bug status {status_value}")
    b = _find(status["bugs"], id, "bug")
    b["status"] = status_value
    if status_value in ("fixed", "wontfix"):
        b["closed_at"] = date.today().isoformat()
    else:
        b.pop("closed_at", None)
    label = {"open": L("重新打开", "Reopened"), "fixing": L("开始修复", "Fixing"), "fixed": L("修复", "Fixed"),
             "wontfix": L("不修", "Won't fix")}[status_value]
    return f"{label} bug{L('：', ': ')}{b['title']}", "fixed" if status_value == "fixed" else "bug"


def _next_id(items, prefix):
    items = list(items) + _ARCHIVED.get(prefix, [])
    nums = [int(i["id"][1:]) for i in items if re.fullmatch(prefix + r"\d+", i.get("id", ""))]
    return f"{prefix}{max(nums, default=0) + 1}"


def _list(v):
    return [x.strip() for x in re.split(r"[,，\s]+", v or "") if x.strip()]


def _opt(item, args, *keys):
    for k in keys:
        if args.get(k):
            item[k] = args[k]
    return item


def op_add_task(status, a):
    if not a.get("title"):
        raise OpError("title is required")
    t = _opt({"id": _next_id(status["tasks"], "t"), "title": a["title"], "status": a.get("status", "todo"),
              "changed_at": date.today().isoformat()}, a, "milestone", "ref")
    if t["status"] not in ("todo", "doing"):
        raise OpError("a new task is todo or doing")
    if a.get("urgent") in ("1", "true", "yes", True):
        t["urgent"] = True
    status["tasks"].append(t)
    if t.get("urgent") and t["status"] == "doing":
        status["next"] = {"task": t["id"], "title": t["title"], "why": L("插队处理", "urgent")}
    return L(f"新增任务 {t['id']}：{t['title']}", f"Added {t['id']}: {t['title']}") + (L("（插队）", " (urgent)") if t.get("urgent") else ""), "added"


def op_add_waiting(status, a):
    on = a.get("on") or a.get("waiting_on") or "me"
    if not a.get("question"):
        raise OpError("question is required")
    w = {"id": _next_id(status["waiting"], "w"), "question": a["question"], "waiting_on": on,
         "since": a.get("since") or date.today().isoformat(), "status": "open"}
    if on == "me":
        w["kind"] = a.get("kind", "decide")
    _opt(w, a, "who", "ref", "check")
    for cond in [c.strip() for c in w.get("check", "").split("&&") if c.strip()]:
        if cond.partition(":")[0] not in ("exists", "missing", "contains") or not cond.partition(":")[2]:
            raise OpError(L("check 只支持 exists:路径 / missing:路径 / contains:路径:文字，看不懂：", "check supports exists:PATH / missing:PATH / contains:PATH:TEXT only, not: ") + cond)
    if a.get("draft") or a.get("message_draft"):
        w["message_draft"] = a.get("draft") or a.get("message_draft")
    if a.get("blocks"):
        w["blocks"] = _list(a["blocks"])
    status["waiting"].append(w)
    label = {"me": L("等你去做", "your action") if w.get("kind") == "do" else L("等你决定", "your call"),
             "client": L("等甲方", "client"), "teammate": L("等同事", "teammate"), "external": L("等外部", "external")}.get(on, on)
    return L(f"新增等待 {w['id']}：{w['question']}（{label}）", f"Waiting {w['id']}: {w['question']} ({label})"), "waiting"


def op_add_bug(status, a):
    if not a.get("title"):
        raise OpError("title is required")
    b = _opt({"id": _next_id(status["bugs"], "b"), "title": a["title"], "severity": a.get("severity", "medium"),
              "status": "open"}, a, "ref")
    if a.get("blocks"):
        b["blocks"] = _list(a["blocks"])
    status["bugs"].append(b)
    return L(f"发现 bug {b['id']}：{b['title']}", f"Bug {b['id']}: {b['title']}"), "bug"


def op_add_decision(status, a):
    if not a.get("text"):
        raise OpError("text is required")
    d = _opt({"date": date.today().isoformat(), "decision": a["text"]}, a, "reason", "ref")
    if a.get("from"):
        d["from_waiting"] = a["from"]
    status["decisions"].insert(0, d)
    return L("决策：", "Decision: ") + a["text"], "decision"


def op_set_next(status, a):
    task = a.get("task")
    title = a.get("title") or (_find(status["tasks"], task, "task")["title"] if task else "")
    if not title:
        raise OpError("title or task is required")
    status["next"] = _opt({"title": title}, a, "task", "why")
    return L("下一步：", "Next: ") + title, None  # not worth a timeline entry


def op_set_milestone(status, a):
    ms = status.setdefault("milestones", [])
    if a.get("id"):
        m = _find(ms, a["id"], "milestone")
        _opt(m, a, "title", "status", "due")
    else:
        if not a.get("title"):
            raise OpError("title or id is required")
        m = _opt({"id": _next_id(ms, "m"), "title": a["title"], "status": a.get("status", "pending")}, a, "due")
        ms.append(m)
    if m["status"] == "active":
        for other in ms:
            if other is not m and other["status"] == "active":
                other["status"] = "done"
    return L(f"阶段 {m['id']}：{m['title']}（{m['status']}）", f"Phase {m['id']}: {m['title']} ({m['status']})"), "note" if m["status"] != "done" else "done"


def op_set_project(status, a):
    _opt(status["project"], a, "name", "goal")
    if "deadline" in a:
        status["deadline"] = a["deadline"] or None
    return L("更新项目信息", "Updated project info"), None


def op_note(status, a):
    if not a.get("text"):
        raise OpError("text is required")
    return a["text"], a.get("type", "note")


OPS = {
    "resolve_waiting": lambda s, a: op_resolve_waiting(s, a["id"], a.get("answer", ""),
                                                       force=a.get("force") in ("1", "true", True)),
    "set_task": lambda s, a: op_set_task(s, a["id"], a["status"], a.get("note")),
    "pause_task": lambda s, a: op_set_task(s, a["id"], "paused", a.get("note")),
    "resume_task": lambda s, a: op_set_task(s, a["id"], "doing"),
    "set_bug": lambda s, a: op_set_bug(s, a["id"], a["status"]),
    "add_task": op_add_task,
    "add_waiting": op_add_waiting,
    "add_bug": op_add_bug,
    "add_decision": op_add_decision,
    "set_next": op_set_next,
    "set_milestone": op_set_milestone,
    "set_project": op_set_project,
    "note": op_note,
}


DOC_OPS = {"doc_meta", "doc_viewed", "doc_open", "doc_forget"}


def apply_doc_op(pid, op, args):
    rel = args["path"]
    if op == "doc_viewed":
        safe_doc_path(pid, rel)
        doc_set_meta(pid, rel, last_viewed=now_iso())
        return "viewed"
    if op == "doc_forget":
        meta = load_docs_meta(pid)
        meta.pop(rel, None)
        save_docs_meta(pid, meta)
        return L("已清除这份文档的标记", "Cleared this doc's notes")
    if op == "doc_open":
        open_path(safe_doc_path(pid, rel))
        return L("已用默认程序打开", "Opened in the default app")
    fields = {k: args[k] for k in ("tags", "note", "pinned", "hidden", "role", "purpose") if k in args}
    doc_set_meta(pid, rel, **fields)
    return L("已更新文档标记", "Updated doc notes")


def apply_op(pid, op, args, source="panel"):
    if pid not in load_registry()["projects"]:
        raise OpError(f"unknown project {pid}")
    if op in DOC_OPS:
        return apply_doc_op(pid, op, args)
    if op not in OPS:
        raise OpError(f"unknown operation {op}")
    status = load_status(pid)
    arch = load_archive(pid)
    _PROJECT_PATH["path"] = Path(load_registry()["projects"][pid]["path"])
    _ARCHIVED.clear()
    _ARCHIVED.update({"t": arch.get("tasks", []), "w": arch.get("waiting", []), "b": arch.get("bugs", [])})
    text, kind = OPS[op](status, args)
    now = now_iso()
    status["updated_at"] = now
    if kind:
        entry = text + source_suffix(source) if source else text
        status["timeline"] = ([{"at": now, "type": kind, "text": entry}] + status["timeline"])[:30]
    errors, _ = validate_status(merge_archive(status, arch), Path(load_registry()["projects"][pid]["path"]))
    if errors:
        raise OpError("; ".join(errors[:3]))
    tmp = status_path(pid).with_suffix(".json.tmp")
    write_json(tmp, status)
    replace_file(tmp, status_path(pid))  # atomic: the agent never sees a half-written file
    return text


def cmd_op(directory):
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    if not args:
        sys.exit(f"operations: {', '.join(OPS)}  (arguments as key=value, see .project rules)")
    pid, _ = require_project(".")
    kv = dict(a.split("=", 1) for a in args[1:])
    try:
        print(apply_op(pid, args[0], kv, source=""))
    except OpError as e:
        sys.exit(f"error: {e}")
    # Nudge the agent (printed only, never stored): starting new work while other work is
    # still "doing" usually means it was interrupted and should be paused with a note.
    if (args[0] == "add_task" and kv.get("status") == "doing") or \
            (args[0] in ("set_task", "resume_task") and kv.get("status", "doing") == "doing"):
        status = load_status(pid)
        newest = kv.get("id") or status["tasks"][-1]["id"]
        others = [t for t in status["tasks"] if t["status"] == "doing" and t["id"] != newest]
        if others:
            names = L("、", ", ").join(L(f"{t['id']}（{t['title']}）", f"{t['id']} ({t['title']})") for t in others)
            print(L(f"注意：{names} 仍在进行中。如果是被这件事打断了，用 pause_task id=… note=\"做到哪、回来从哪继续\" 暂停它。",
                    f"Note: {names} still in progress. If this interrupted it, pause it with pause_task id=… note=\"where it stopped, where to resume\"."))
        stuck = blocked_tasks(status).get(newest)
        if stuck:
            print(L(f"注意：{newest} 还被 {'、'.join(stuck)} 卡着，现在开始可能做不下去；确认是在做它，还是在先解决卡住它的事？",
                    f"Note: {newest} is still blocked by {', '.join(stuck)}; starting it may stall. Is this really the work, or unblocking it first?"))
    return 0


# ---------------------------------------------------------------- notifications
# A nudge for things that quietly stall. Checked by the local service every 30 minutes
# (daytime only); each item notifies at most once a day; one notification per project.

NOTIFY_DAYS = 3
NOTIFY_HOURS = range(9, 21)


def notify_items(status):
    """(key, line) for everything worth a nudge in one project."""
    items = []
    for w in status["waiting"]:
        if w["status"] == "open" and w["waiting_on"] != "me" and days_since(w["since"]) >= NOTIFY_DAYS:
            items.append((f"chase:{w['id']}", L(f"该催了：{w['id']} {w['question'][:28]}（已等 {days_since(w['since'])} 天）", f"Time to nudge: {w['id']} {w['question'][:40]} (waiting {days_since(w['since'])}d)")))
    mine = [w for w in status["waiting"] if w["status"] == "open" and w["waiting_on"] == "me"]
    if mine:
        oldest = max(days_since(w["since"]) for w in mine)
        if oldest >= NOTIFY_DAYS:
            items.append(("mine", L(f"{len(mine)} 项在等你，最久 {oldest} 天", f"{len(mine)} waiting on you, oldest {oldest}d")))
    for t in status["tasks"]:
        if t["status"] == "paused" and t.get("paused_at") and days_since(t["paused_at"]) >= NOTIFY_DAYS:
            items.append((f"paused:{t['id']}", L(f"{t['id']} {t['title'][:24]} 已暂停 {days_since(t['paused_at'])} 天", f"{t['id']} {t['title'][:36]} paused {days_since(t['paused_at'])}d")))
        if t["status"] == "doing" and t.get("changed_at") and days_since(t["changed_at"]) >= NOTIFY_DAYS:
            items.append((f"stale:{t['id']}", L(f"{t['id']} {t['title'][:24]} 进行 {days_since(t['changed_at'])} 天没变化", f"{t['id']} {t['title'][:36]} unchanged for {days_since(t['changed_at'])}d")))
    return items


def run_notifications(dry_run=False, force=False, mark=False):
    if not force and datetime.now().hour not in NOTIFY_HOURS:
        return []
    state_path = HOME / "notify.json"
    sent = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    today = date.today().isoformat()
    shown = []
    for pid, entry in load_registry()["projects"].items():
        try:
            status = load_status(pid)
        except (OSError, ValueError):
            continue
        fresh = [(k, line) for k, line in notify_items(status) if sent.get(f"{pid}:{k}") != today]
        if not fresh:
            continue
        title = f"Forthmark · {status['project']['name']}"
        body = L("；", "; ").join(line for _, line in fresh[:3]) + (L(f"；还有 {len(fresh) - 3} 项", f"; {len(fresh) - 3} more") if len(fresh) > 3 else "")
        shown.append((title, body))
        if not dry_run and not IS_WINDOWS:  # Windows: the desktop app posts them, through /api/notify
            script = f'display notification {json.dumps(body, ensure_ascii=False)} with title {json.dumps(title, ensure_ascii=False)}'
            subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
        if (not dry_run and not IS_WINDOWS) or mark:
            for k, _ in fresh:
                sent[f"{pid}:{k}"] = today
    if not dry_run or mark:
        write_json(state_path, {k: v for k, v in sent.items() if v == today})
    return shown


def cmd_notify(_directory):
    shown = run_notifications(dry_run="--dry-run" in sys.argv, force=True)
    for title, body in shown:
        print(f"{title}\n  {body}")
    if not shown:
        print("nothing to notify (or already notified today)")
    return 0


def badge():
    """Menu bar summary across projects: items waiting on you, overdue chases, stalled work."""
    mine = late = stalled = 0
    lines = []
    for pid, entry in load_registry()["projects"].items():
        try:
            s = load_status(pid)
        except (OSError, ValueError):
            continue
        m = [w for w in s["waiting"] if w["status"] == "open" and w["waiting_on"] == "me"]
        l = [w for w in s["waiting"] if w["status"] == "open" and w["waiting_on"] != "me" and days_since(w["since"]) >= NOTIFY_DAYS]
        st = [t for t in s["tasks"] if (t["status"] == "paused" and t.get("paused_at") and days_since(t["paused_at"]) >= NOTIFY_DAYS)
              or (t["status"] == "doing" and t.get("changed_at") and days_since(t["changed_at"]) >= NOTIFY_DAYS)]
        mine, late, stalled = mine + len(m), late + len(l), stalled + len(st)
        bits = [L(f"{len(m)} 等你", f"{len(m)} on you") if m else "", L(f"{len(l)} 该催", f"{len(l)} to nudge") if l else "",
                L(f"{len(st)} 停滞", f"{len(st)} stalled") if st else ""]
        lines.append(f"{s['project']['name']}{L('：', ': ')}" + (L("，", ", ").join(b for b in bits if b) or L("畅通", "all clear")))
    count = mine + late + stalled
    parts = [L(f"{mine} 项等你", f"{mine} on you") if mine else "", L(f"{late} 项该催", f"{late} to nudge") if late else "",
             L(f"{stalled} 项停滞", f"{stalled} stalled") if stalled else ""]
    summary = L("需要你关注：", "Needs you: ") + L("、", ", ").join(p for p in parts if p) if count else L("都很顺", "All smooth")
    # The menu bar shows one monochrome icon plus a plain number; emoji there read as a second icon.
    return {"count": count, "text": str(count) if count else "",
            "tooltip": summary + "\n\n" + ("\n".join(lines) or L("还没有接入项目", "No projects tracked yet"))}


# ---------------------------------------------------------------- local service

SERVER_INFO = HOME / "server.json"
DEFAULT_PORT = 47321


def panel_payload():
    projects = []
    for pid, entry in load_registry()["projects"].items():
        if not validate_project(pid)[0]:
            projects.append(project_panel_data(pid, entry))
    projects.sort(key=lambda p: p["last_activity"], reverse=True)
    cfg = load_config()
    return {"generated_at": now_iso(), "projects": projects, "lang": ui_lang(),
            "config": {"projects_dir": os.path.expanduser(cfg["projects_dir"]), "terminal": cfg["terminal"],
                       "agent": cfg["agent"].split()[0], "git_init": cfg["git_init"],
                       "terminal_name": {"ghostty": "Ghostty", "windows-terminal": "Windows Terminal", "powershell": "PowerShell"}.get(
                           pick_terminal(cfg["terminal"]), L("终端", "Terminal"))}}


def panel_page(data, api=None):
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = PANEL_TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null/*END*/", payload)
    # Inlined (not served) so the static file:// panel can patch the DOM too.
    page = page.replace("/*MORPHDOM*/", (KIT / "vendor" / "morphdom-umd.min.js").read_text(encoding="utf-8"))
    return page.replace("/*API*/null/*END*/", json.dumps(api) if api else "null")


def make_handler(token):
    """Request handler for the local service; built lazily so the hooks never import http.server."""
    import http.server
    import secrets

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def local_host(self):
            # DNS rebinding: a website can point its own domain at 127.0.0.1 and then read this page (and the
            # token) as same-origin. Only answer requests that name us by address.
            port = self.server.server_address[1]
            return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

        def cross_site(self):
            origin = self.headers.get("Origin")
            return origin is not None and origin not in ("null", f"http://{self.headers.get('Host', '')}")

        def authorized(self):
            # A random token embedded in the served page; other websites can't read it, so they can't call us.
            return secrets.compare_digest(self.headers.get("X-Forthmark-Token", ""), token)

        def do_GET(self):
            if not self.local_host():
                return self.send(403, '{"error": "forbidden"}')
            if self.path in ("/", "/index.html") or self.path.startswith("/#"):
                self.send(200, panel_page(panel_payload(), {"token": token}), "text/html; charset=utf-8")
            elif self.path.startswith("/vendor/"):
                name = self.path[len("/vendor/"):]
                ctypes = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
                f = KIT / "vendor" / name
                if "/" in name or f.suffix not in ctypes or not f.is_file():
                    return self.send(404, '{"error": "not found"}')
                self.send(200, f.read_bytes(), ctypes[f.suffix])
            elif self.path.startswith("/api/doc?"):
                if not self.authorized():
                    return self.send(403, '{"error": "forbidden"}')
                from urllib.parse import parse_qs, urlsplit
                q = parse_qs(urlsplit(self.path).query)
                try:
                    self.send(200, json.dumps(read_doc(q["project"][0], q["path"][0]), ensure_ascii=False))
                except (OpError, KeyError) as e:
                    self.send(400, json.dumps({"error": str(e)}, ensure_ascii=False))
            elif self.path == "/api/ping":
                self.send(200, json.dumps({"ok": True, "home": str(HOME)}))
            elif self.path in ("/api/badge", "/api/notify"):
                if not self.authorized():
                    return self.send(403, '{"error": "forbidden"}')
                if self.path == "/api/badge":
                    return self.send(200, json.dumps(badge(), ensure_ascii=False))
                for pid in load_registry()["projects"]:
                    try:
                        auto_verify(pid)
                    except Exception:
                        pass
                shown = run_notifications(dry_run=True, mark=True)
                self.send(200, json.dumps([{"title": t, "body": b} for t, b in shown], ensure_ascii=False))
            elif self.path == "/api/state":
                if not self.authorized():
                    return self.send(403, '{"error": "forbidden"}')
                self.send(200, json.dumps(panel_payload(), ensure_ascii=False))
            else:
                self.send(404, '{"error": "not found"}')

        def do_POST(self):
            if self.path != "/api/op":
                return self.send(404, '{"error": "not found"}')
            if not self.local_host() or self.cross_site() or not self.authorized():
                return self.send(403, '{"error": "forbidden"}')
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                if req.get("op") == "create_project":
                    a = req.get("args", {})
                    pid = create_project(a.get("name", ""), a.get("dir", ""), a.get("goal", ""), a.get("adopt") in ("1", True))
                    render_panel()
                    return self.send(200, json.dumps({"ok": True, "text": L("已创建，agent 已在终端里打开，等你说第一句话", "Created; your agent is open in the terminal, waiting for your first message"), "project": pid}, ensure_ascii=False))
                if req.get("op") == "open_session":
                    text = open_session(req["project"], req.get("args", {}).get("mode", ""))
                    return self.send(200, json.dumps({"ok": True, "text": text}, ensure_ascii=False))
                text = apply_op(req["project"], req["op"], req.get("args", {}))
                render_panel()
                self.send(200, json.dumps({"ok": True, "text": text}, ensure_ascii=False))
            except (OpError, KeyError, ValueError) as e:
                self.send(400, json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            except Exception as e:  # never drop the connection without an answer
                self.send(500, json.dumps({"ok": False, "error": f"internal error: {e}"}, ensure_ascii=False))

    return Handler

def server_url():
    """URL of the running local service, or None."""
    import urllib.request
    if not SERVER_INFO.exists():
        return None
    info = json.loads(SERVER_INFO.read_text(encoding="utf-8"))
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/api/ping", timeout=1) as r:
            # Another data dir's service may hold the port; only accept our own.
            if json.loads(r.read()).get("home") != str(HOME):
                return None
        return f"http://127.0.0.1:{info['port']}/"
    except (OSError, ValueError):
        return None


def spawn_service():
    """Start the local service in the background, independent of this process and its terminal."""
    detach = ({"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if IS_WINDOWS
              else {"start_new_session": True})
    HOME.mkdir(parents=True, exist_ok=True)
    with open(HOME / "server.log", "a", encoding="utf-8") as log:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve"], env=clean_env(),
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, **detach)


def cmd_serve(_directory):
    import http.server
    import secrets
    import socketserver

    class Server(http.server.ThreadingHTTPServer):
        def server_bind(self):  # the stock one reverse-resolves 127.0.0.1, which can take over 30 s
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address[:2]

    for k in SESSION_ENV:  # a long-running service must not carry the session it was started from
        os.environ.pop(k, None)
    HOME.mkdir(parents=True, exist_ok=True)
    running = server_url()
    if running:  # one service per data dir: a second would overwrite server.json and its token
        print(f"already running: {running}", flush=True)
        return 0
    token = secrets.token_urlsafe(24)
    handler = make_handler(token)
    server = None
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 20):
        try:
            server = Server(("127.0.0.1", port), handler)
            break
        except OSError:
            continue
    if not server:
        sys.exit("no free port")
    write_json(SERVER_INFO, {"port": server.server_address[1], "pid": os.getpid(), "token": token})
    os.chmod(SERVER_INFO, 0o600)  # the token lets the menu bar app call the API; only this user can read it

    # Restart in place when the kit's code changes, so a long-running service never serves stale logic.
    import threading
    started = Path(__file__).stat().st_mtime

    def watch():
        while True:
            time.sleep(3)
            try:
                if Path(__file__).stat().st_mtime != started:
                    server.shutdown()
                    return
            except OSError:
                pass
    threading.Thread(target=watch, daemon=True).start()
    print(f"Forthmark panel: http://127.0.0.1:{server.server_address[1]}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    server.server_close()
    print("code changed, restarting", flush=True)
    if IS_WINDOWS:  # os.execv there starts a new process and detaches it from its console anyway
        spawn_service()
        return 0
    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), "serve"])


def cmd_stop(_directory):
    if not SERVER_INFO.exists():
        print("not running")
        return 0
    pid = json.loads(SERVER_INFO.read_text(encoding="utf-8"))["pid"]
    try:
        os.kill(pid, 15)
        print(f"stopped (pid {pid})")
    except OSError:  # Windows reports a gone process differently
        print("not running")
    SERVER_INFO.unlink(missing_ok=True)
    return 0


def cmd_open(_directory):
    url = server_url()
    if not url:
        spawn_service()
        for _ in range(30):
            time.sleep(0.1)
            url = server_url()
            if url:
                break
    if not url:
        sys.exit(f"could not start the local service, see {HOME / 'server.log'}")
    print(url)
    if "--no-browser" not in sys.argv:
        open_path(url)
    return 0


# ---------------------------------------------------------------- setup

SETTINGS = CLAUDE_DIR / "settings.json"
MANIFEST = HOME / "setup.json"
COMMANDS = ("forthmark.md", "forthmark-add.md", "forthmark-remove.md")


def hook_command(script):
    return f'{HOOK_MARKER} {shlex.quote(sys.executable)} {shlex.quote(str(KIT / "hooks" / script))}'


def hook_entry(script):
    """A settings entry for a hook. Windows: exec form, which runs the same with or without Git Bash."""
    if IS_WINDOWS:
        return {"type": "command", "command": sys.executable, "args": [(KIT / "hooks" / script).as_posix(), HOOK_ARG]}
    return {"type": "command", "command": hook_command(script)}


def statusline_command():
    """The status line has no exec form; on Windows this string must work in both Git Bash and PowerShell."""
    if not IS_WINDOWS:
        return hook_command("statusline.py")
    script = (KIT / "hooks" / "statusline.py").as_posix()
    exe = bare_path(sys.executable)
    if exe:
        return f'{exe} "{script}" {HOOK_ARG}'
    return f"""powershell -NoProfile -Command "& '{sys.executable}' '{script}' {HOOK_ARG}\""""


def home_rule_path():
    try:
        return "~/" + HOME.relative_to(Path.home()).as_posix() + "/**"
    except ValueError:
        if IS_WINDOWS:  # permission rules spell C:\\x as //c/x
            return f"//{HOME.drive[0].lower()}/" + HOME.as_posix()[3:] + "/**"
        return "/" + str(HOME) + "/**"


def drop_our_hooks(settings):
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        hooks[event] = [g for g in hooks[event]
                        if not any(ours(h) for h in g.get("hooks", []))]
        if not hooks[event]:
            del hooks[event]
    if "hooks" in settings and not settings["hooks"]:
        del settings["hooks"]


def cmd_setup(_directory):
    HOME.mkdir(parents=True, exist_ok=True)
    HOME.chmod(0o700)  # status can name clients and decisions; launch scripts carry the user's words
    settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    old_manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    if SETTINGS.exists():
        backup = SETTINGS.with_name(f"settings.json.bak-forthmark-{datetime.now():%Y%m%d%H%M%S}")
        shutil.copy2(SETTINGS, backup)
        print(f"backup   {backup}")

    drop_our_hooks(settings)
    hooks = settings.setdefault("hooks", {})
    hooks.setdefault("SessionStart", []).append({
        "matcher": "startup|resume|clear|compact",
        "hooks": [hook_entry("session_start.py")]})
    hooks.setdefault("Stop", []).append({
        "hooks": [hook_entry("stop_check.py")]})
    hooks.setdefault("UserPromptSubmit", []).append({
        "hooks": [hook_entry("prompt_submit.py")]})

    # Status line: ours, appended to whatever the user already had (kept in the manifest).
    prev_sl = old_manifest.get("prev_statusline")
    current = settings.get("statusLine") or {}
    if current.get("command") and not ours(current["command"]):
        prev_sl = current["command"]
    if "--no-statusline" not in sys.argv:
        settings["statusLine"] = {"type": "command", "command": statusline_command()}

    rule_path = home_rule_path()
    wanted_allow = [f"Read({rule_path})", f"Edit({rule_path})", f"Bash({CLI}:*)"] + ([f"PowerShell({CLI} *)"] if IS_WINDOWS else [])
    perms = settings.setdefault("permissions", {})
    # What we added last time goes first: the kit or the data dir may have moved since.
    perms["allow"] = [r for r in perms.get("allow", []) if r not in old_manifest.get("allow", [])]
    perms["additionalDirectories"] = [d for d in perms.get("additionalDirectories", [])
                                      if d not in old_manifest.get("additionalDirectories", [])]
    allow = perms["allow"]
    added_allow = [r for r in wanted_allow if r not in allow]
    allow.extend(added_allow)
    dirs = perms.setdefault("additionalDirectories", [])
    added_dirs = [str(HOME)] if str(HOME) not in dirs else []
    dirs.extend(added_dirs)

    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    write_json(SETTINGS, settings)
    print(f"settings {SETTINGS}: SessionStart + UserPromptSubmit + Stop hooks, status line, access to {HOME}")

    cmd_dir = CLAUDE_DIR / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    for name in set(old_manifest.get("commands", [])) - set(COMMANDS):  # e.g. /standup before the rename
        (cmd_dir / name).unlink(missing_ok=True)
    for name in COMMANDS:
        src = KIT / "commands" / ("en" if ui_lang() == "en" else "") / name  # re-run setup after changing "lang"
        text = src.read_text(encoding="utf-8").replace("{CLI}", CLI)
        (cmd_dir / name).write_text(text, encoding="utf-8")
    print(f"commands /forthmark /forthmark-add /forthmark-remove in {cmd_dir}")

    write_json(MANIFEST, {
        "prev_statusline": prev_sl,
        "allow": sorted(added_allow),
        "additionalDirectories": sorted(added_dirs),
        "commands": list(COMMANDS),
    })
    render_panel()
    print(f"panel    {PANEL}")
    print("\ndone. in any project, open Claude Code and type /forthmark-add")
    return 0


def cmd_teardown(_directory):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    if SETTINGS.exists():
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
        drop_our_hooks(settings)
        if ours((settings.get("statusLine") or {}).get("command")):
            if manifest.get("prev_statusline"):
                settings["statusLine"] = {"type": "command", "command": manifest["prev_statusline"]}
            else:
                del settings["statusLine"]
        perms = settings.get("permissions", {})
        for key in ("allow", "additionalDirectories"):
            if key in perms:
                perms[key] = [r for r in perms[key] if r not in manifest.get(key, [])]
                if not perms[key]:
                    del perms[key]
        if "permissions" in settings and not settings["permissions"]:
            del settings["permissions"]
        write_json(SETTINGS, settings)
        print(f"cleaned  {SETTINGS}")
    for name in manifest.get("commands", COMMANDS):
        p = CLAUDE_DIR / "commands" / name
        if p.exists():
            p.unlink()
    print("removed  /forthmark commands")
    if MANIFEST.exists():
        MANIFEST.unlink()
    print(f"status data kept in {HOME}")
    return 0


# ---------------------------------------------------------------- main

COMMANDS_CLI = {
    "setup": cmd_setup, "teardown": cmd_teardown, "add": cmd_add, "remove": cmd_remove, "move": cmd_move,
    "list": cmd_list, "prune": cmd_prune, "rules": cmd_rules, "validate": cmd_validate, "show": cmd_show,
    "stats": cmd_stats, "html": cmd_html, "open": cmd_open, "serve": cmd_serve, "stop": cmd_stop, "op": cmd_op,
    "doc": cmd_doc, "docs": cmd_docs, "check": cmd_check, "archive": cmd_archive, "notify": cmd_notify,
    "new": cmd_new, "session": cmd_session, "continue": cmd_continue, "sessions": cmd_sessions,
}


def main():
    utf8_stdio()
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS_CLI:
        sys.exit(__doc__)
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    sys.exit(COMMANDS_CLI[sys.argv[1]](args[0] if args else "."))


if __name__ == "__main__":
    main()
