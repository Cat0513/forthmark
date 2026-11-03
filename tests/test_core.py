"""Runs on macOS and Windows (CI: .github/workflows/test.yml), against a throwaway data dir. Standard library only.

    python -m unittest discover tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "tools"))
TMP = Path(tempfile.mkdtemp(prefix="forthmark test 中文")).resolve()
os.environ.update(FORTHMARK_HOME=str(TMP / "data"), FORTHMARK_CLAUDE_DIR=str(TMP / "claude"), FORTHMARK_LANG="zh")
import fmshared  # noqa: E402
import forthmark  # noqa: E402

CLI = [sys.executable, str(KIT / "tools" / "forthmark.py")]


def cli(*args, cwd=None):
    return subprocess.run(CLI + list(args), cwd=cwd, capture_output=True, encoding="utf-8", timeout=60)


def tearDownModule():
    cli("stop")
    shutil.rmtree(TMP, ignore_errors=True)


def run_hook(script, payload):
    """Run a hook the way Claude Code does: JSON in on stdin as UTF-8 bytes, UTF-8 bytes out."""
    r = subprocess.run([sys.executable, str(KIT / "hooks" / script)], input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       capture_output=True, timeout=60)
    return r.returncode, r.stdout.decode("utf-8"), r.stderr.decode("utf-8")


class Paths(unittest.TestCase):
    def test_inside(self):
        root = TMP / "root"
        (root / "sub dir").mkdir(parents=True, exist_ok=True)
        self.assertTrue(fmshared.inside(root, str(root)))
        self.assertTrue(fmshared.inside(root / "sub dir", str(root)))
        self.assertFalse(fmshared.inside(TMP, str(root)))
        self.assertFalse(fmshared.inside(str(root) + "-other", str(root)))

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_inside_windows_spellings(self):
        root = TMP / "root"
        root.mkdir(exist_ok=True)
        self.assertTrue(fmshared.inside(str(root).upper(), str(root)))
        self.assertTrue(fmshared.inside(str(root).replace("\\", "/"), str(root)))
        git_bash = "/" + root.drive[0].lower() + root.as_posix()[2:]
        self.assertTrue(fmshared.inside(git_bash, str(root)))
        self.assertEqual(fmshared.native_path("/c/x"), "c:/x")
        self.assertFalse(fmshared.inside("Z:\\elsewhere", str(root)))

    def test_replace_file_waits_for_a_locked_target(self):
        real, calls = os.replace, []

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("in use")
            return real(a, b)
        a, b = TMP / "a.tmp", TMP / "b.json"
        a.write_text("x", encoding="utf-8")
        with mock.patch("os.replace", flaky), mock.patch("time.sleep"):
            fmshared.replace_file(a, b)
        self.assertEqual(b.read_text(encoding="utf-8"), "x")
        self.assertEqual(len(calls), 3)

    def test_check_with_a_drive_letter(self):
        f = TMP / "check.txt"
        f.write_text("有内容", encoding="utf-8")
        self.assertEqual(forthmark.run_check(f"contains:{f}:有内容", TMP), (True, ""))
        self.assertFalse(forthmark.run_check(f"contains:{f}:没有", TMP)[0])
        self.assertEqual(forthmark.run_check(f"exists:{f}", TMP), (True, ""))


class Launch(unittest.TestCase):
    def test_powershell_quote(self):
        self.assertEqual(forthmark.powershell_quote("it's"), "'it''s'")

    def test_windows_script(self):
        script = TMP / "launch.ps1"
        forthmark.write_windows_launch(script, TMP / "O'Brien 项目", "claude --continue")
        self.assertTrue(script.read_bytes().startswith(b"\xef\xbb\xbf"))
        text = script.read_text(encoding="utf-8-sig")
        self.assertIn("Remove-Item Env:CLAUDECODE", text)
        self.assertIn("O''Brien 项目'", text)
        self.assertTrue(text.rstrip().endswith("claude --continue"))

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_script_runs_in_powershell(self):
        target = TMP / "O'Brien 项目"
        target.mkdir(exist_ok=True)
        out = TMP / "where.txt"
        script = TMP / "run.ps1"
        forthmark.write_windows_launch(script, target, f"(Get-Location).Path | Set-Content -Encoding UTF8 -LiteralPath {forthmark.powershell_quote(out)}")
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], check=True, timeout=60)
        self.assertEqual(out.read_text(encoding="utf-8-sig").strip(), str(target))


class Setup(unittest.TestCase):
    def setUp(self):
        self.settings = TMP / "claude" / "settings.json"
        self.settings.parent.mkdir(parents=True, exist_ok=True)
        self.user = {"statusLine": {"type": "command", "command": "my-line"},
                     "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "my-stop"}]}]},
                     "permissions": {"allow": ["Bash(ls:*)"]}}
        self.settings.write_text(json.dumps(self.user), encoding="utf-8")

    def tearDown(self):
        cli("teardown")

    def test_setup_then_teardown_restores(self):
        r = cli("setup")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertTrue(forthmark.ours(s["statusLine"]["command"]))
        ours = [h for g in s["hooks"]["Stop"] for h in g["hooks"] if forthmark.ours(h)]
        self.assertEqual(len(ours), 1)
        self.assertTrue(any(h["command"] == "my-stop" for g in s["hooks"]["Stop"] for h in g["hooks"]))
        if os.name == "nt":
            self.assertIn("args", ours[0])  # exec form: no shell involved
            self.assertTrue(any(a.startswith("PowerShell(") for a in s["permissions"]["allow"]))
        self.assertFalse(any(a.startswith("Write(") for a in s["permissions"]["allow"]))  # Claude Code warns: Edit covers it
        self.assertEqual(cli("setup").returncode, 0)  # twice: no duplicates
        s = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(len([h for g in s["hooks"]["Stop"] for h in g["hooks"] if forthmark.ours(h)]), 1)
        self.assertEqual(cli("teardown").returncode, 0)
        self.assertEqual(json.loads(self.settings.read_text(encoding="utf-8")), self.user)

    def test_old_marker_and_user_hooks(self):
        self.assertTrue(forthmark.ours("FORTHMARK_HOOK=1 python3 x.py"))
        self.assertTrue(forthmark.ours({"command": "python.exe", "args": ["x.py", "--forthmark-hook"]}))
        self.assertFalse(forthmark.ours({"command": "statusline.py"}))
        self.assertFalse(forthmark.ours(None))

    def test_installed_hooks_actually_run(self):
        self.assertEqual(cli("setup").returncode, 0)
        s = json.loads(self.settings.read_text(encoding="utf-8"))
        hook = next(h for g in s["hooks"]["SessionStart"] for h in g["hooks"] if forthmark.ours(h))
        command = [hook["command"]] + hook["args"] if "args" in hook else hook["command"]
        r = subprocess.run(command, shell="args" not in hook, input=b"{}", capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)


class Project(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = TMP / "项目 one"
        (cls.path / "子目录").mkdir(parents=True)
        r = cli("add", str(cls.path), "--here")
        assert r.returncode == 0, r.stderr
        cls.pid = forthmark.find_project(cls.path)[0]

    def op(self, *args):
        r = cli("op", *args, cwd=self.path)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_chinese_round_trip(self):
        self.assertIn("写中文任务", self.op("add_task", "title=写中文任务"))
        self.assertIn("写中文任务", cli("show", str(self.path)).stdout)
        self.assertEqual(cli("validate", str(self.path)).returncode, 0)

    def test_session_start_hook(self):
        code, out, err = run_hook("session_start.py", {"cwd": str(self.path / "子目录"), "source": "startup", "session_id": "s1"})
        self.assertEqual((code, err), (0, ""))
        context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("项目状态记录规则", context)
        self.assertIn(forthmark.CLI, context)

    def test_hooks_are_silent_elsewhere(self):
        for script in ("session_start.py", "prompt_submit.py", "stop_check.py"):
            self.assertEqual(run_hook(script, {"cwd": str(TMP), "session_id": "s"}), (0, "", ""), script)

    def test_prompt_hook_relays_panel_changes(self):
        run_hook("prompt_submit.py", {"cwd": str(self.path), "session_id": "s2"})
        time.sleep(1.1)  # the timeline has one-second resolution
        forthmark.apply_op(self.pid, "add_decision", {"text": "面板上的决定"})
        code, out, _ = run_hook("prompt_submit.py", {"cwd": str(self.path), "session_id": "s2"})
        self.assertEqual(code, 0)
        self.assertIn("面板上的决定", json.loads(out)["hookSpecificOutput"]["additionalContext"])

    def test_statusline(self):
        self.op("add_task", "title=状态行任务", "status=doing")
        code, out, err = run_hook("statusline.py", {"cwd": str(self.path), "model": {"display_name": "M"}})
        self.assertEqual((code, err), (0, ""))
        self.assertIn("状态行任务", out)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_stop_hook_blocks_when_status_is_behind(self):
        repo = TMP / "带 git 的项目"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        self.assertEqual(cli("add", str(repo)).returncode, 0)
        time.sleep(1.1)
        (repo / "改动.txt").write_text("x", encoding="utf-8")
        code, out, _ = run_hook("stop_check.py", {"cwd": str(repo), "session_id": "s3"})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_docs_use_forward_slashes(self):
        (self.path / "子目录" / "说明.md").write_text("# 说明", encoding="utf-8")
        self.assertIn("子目录/说明.md", forthmark.list_doc_files(self.path))
        self.assertIn("说明", str(forthmark.read_doc(self.pid, "子目录/说明.md")))

    def test_project_name_rules(self):
        with self.assertRaises(forthmark.OpError):
            forthmark.create_project("a/b")
        if os.name == "nt":
            with self.assertRaises(forthmark.OpError):
                forthmark.create_project('a:b')


class Service(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = cli("open", "--no-browser")
        if r.returncode != 0:
            log = (TMP / "data" / "server.log").read_text(encoding="utf-8", errors="replace")
            raise AssertionError(f"{r.stdout}{r.stderr}\nserver.log:\n{log}")
        cls.url = r.stdout.strip().splitlines()[-1]
        cls.info = json.loads((TMP / "data" / "server.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        r = cli("stop")
        assert "stopped" in r.stdout, r.stdout + r.stderr
        time.sleep(0.5)
        try:
            urllib.request.urlopen(cls.url + "api/ping", timeout=1)
        except OSError:
            return
        raise AssertionError("the service is still running after stop")

    def get(self, path, headers=None):
        return urllib.request.urlopen(urllib.request.Request(self.url + path, headers=headers or {}), timeout=5)

    def test_ping_and_page(self):
        self.assertEqual(json.loads(self.get("api/ping").read())["home"], str(TMP / "data"))
        self.assertIn("Forthmark".encode(), self.get("").read())

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_service_children_open_no_windows(self):
        with mock.patch("subprocess.Popen") as popen:
            forthmark.spawn_service()
        self.assertTrue(popen.call_args.kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)
        code = "import ctypes, subprocess, sys; sys.exit(0 if ctypes.windll.kernel32.GetConsoleWindow() else 3)"
        r = subprocess.run([sys.executable, "-c", code], creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        self.assertEqual(r.returncode, 0)  # the console children would share exists, so they don't make their own

    def test_second_service_exits(self):
        r = subprocess.run(CLI + ["serve"], capture_output=True, encoding="utf-8", timeout=30)
        self.assertIn("already running", r.stdout)
        self.assertEqual(json.loads((TMP / "data" / "server.json").read_text(encoding="utf-8"))["pid"], self.info["pid"])

    def test_rejects_other_hosts_and_missing_token(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("api/state", {"Host": "evil.example"})
        self.assertEqual(e.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get("api/state")
        self.assertEqual(e.exception.code, 403)

    def test_state_with_token(self):
        body = json.loads(self.get("api/state", {"X-Forthmark-Token": self.info["token"]}).read())
        self.assertIn("projects", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
