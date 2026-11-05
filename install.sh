#!/bin/zsh
# Forthmark installer (macOS + Claude Code). Run it from anywhere inside the kit:
#   ./install.sh                 hooks, status line, /forthmark commands, menu bar app
#   ./install.sh --no-app        skip the menu bar app (use the browser panel: forthmark.py open)
#   ./install.sh --no-statusline keep Claude Code's status line as it is
#   ./install.sh --uninstall     undo all of the above (status data in ~/.forthmark is kept)
# Nothing is written into your projects. ~/.claude/settings.json is backed up before it is changed.
set -euo pipefail

KIT=${0:A:h}
CLI=$KIT/tools/forthmark.py
app=1 setup_args=() uninstall=0
for arg in "$@"; do
  case $arg in
    --no-app) app=0 ;;
    --no-statusline) setup_args+=(--no-statusline) ;;
    --uninstall) uninstall=1 ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)"; exit 2 ;;
  esac
done

say()  { print -P "%B==>%b $*"; }
warn() { print -P "%F{yellow}!%f $*"; }
fail() { print -P "%F{red}✗%f $*"; exit 1; }

[[ $(uname) == Darwin ]] || fail "这个脚本只用于 macOS；Windows 请用 install.ps1"

# The agent runs `python3 …/forthmark.py`, so python3 on PATH is the one that has to work.
command -v python3 >/dev/null || fail "找不到 python3。安装 Xcode 命令行工具（xcode-select --install）或 Homebrew 的 python 后再运行"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || fail "需要 Python 3.9 以上，当前：$(python3 --version 2>&1)"

if (( uninstall )); then
  say "移除 hook、状态栏、/forthmark 命令"
  python3 "$CLI" teardown
  python3 "$CLI" stop >/dev/null 2>&1 || true
  installed=~/Applications/Forthmark.app
  # Only an app built from this kit: another copy of the kit may own the installed one.
  if [[ -d $installed && $(/usr/libexec/PlistBuddy -c 'Print :ForthmarkKit' "$installed/Contents/Info.plist" 2>/dev/null) == "$KIT" ]]; then
    say "移除菜单栏应用"
    pkill -x Forthmark 2>/dev/null || true
    rm -rf "$installed"
  fi
  say "已卸载。状态数据保留在 ~/.forthmark，不需要了可以直接删除"
  exit 0
fi

command -v claude >/dev/null || warn "没找到 claude 命令：hook 会装好，装上 Claude Code 后即可生效"

say "安装 Claude Code 全局 hook、状态栏和 /forthmark 命令（会先备份 ~/.claude/settings.json）"
python3 "$CLI" setup "${setup_args[@]}"

if (( app )); then
  if command -v swiftc >/dev/null; then
    say "编译并安装菜单栏应用"
    zsh "$KIT/tools/build_app.sh" --install
  else
    warn "没有 swiftc，跳过菜单栏应用（xcode-select --install 后重新运行本脚本即可）；面板可用：python3 \"$CLI\" open"
  fi
fi

print
say "完成。在任一项目里打开 Claude Code，输入 /forthmark-add 接入"
print "  移动了工具目录后，重新运行一次 ./install.sh"
