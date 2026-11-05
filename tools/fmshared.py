"""What the hooks and forthmark.py share. Kept light: hooks run on every turn, in every project."""
import json
import os
import re
import sys
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def data_home():
    return Path(os.environ.get("FORTHMARK_HOME") or "~/.forthmark").expanduser()


def utf8_stdio():
    """Claude Code talks UTF-8; Windows' default code page would garble or crash on anything else."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def native_path(path):
    """Git Bash spells C:\\x as /c/x; everything here wants the Windows form."""
    path = str(path)
    if IS_WINDOWS and re.match(r"^/[A-Za-z](/|$)", path):
        return f"{path[1]}:{path[2:] or '/'}"
    return path


def inside(path, root):
    """Whether path is root or under it. Case-insensitive, with either slash, on Windows."""
    path = os.path.normcase(os.path.realpath(native_path(path)))
    root = os.path.normcase(os.path.normpath(root))
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives
        return False


def tracked(cwd):
    """Cheap check against the registry, so untracked projects never load the toolkit."""
    try:
        projects = json.loads((data_home() / "registry.json").read_text(encoding="utf-8"))["projects"].values()
    except (OSError, ValueError, KeyError):
        return False
    return any(inside(cwd, p["path"]) for p in projects)


def replace_file(tmp, path):
    """os.replace, waiting out the moment another process has the file open (which blocks it on Windows)."""
    for attempt in range(20):
        try:
            return os.replace(tmp, path)
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05)
