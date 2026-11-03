# Forthmark installer (Windows + Claude Code, preview). Run it from the kit, in a normal (not administrator) window:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1                 hooks, status line, /forthmark commands
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -NoStatusline   keep Claude Code's status line as it is
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall      undo the above (status data in ~\.forthmark is kept)
# Nothing is written into your projects. ~\.claude\settings.json is backed up before it is changed.
param([switch]$NoStatusline, [switch]$Uninstall)

[Console]::OutputEncoding = [Text.Encoding]::UTF8
$zh = (Get-UICulture).Name -like 'zh*'
function L($cn, $en) { if ($zh) { $cn } else { $en } }
function Say($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Warn($text) { Write-Host "!  $text" -ForegroundColor Yellow }
function Fail($text) { Write-Host "x  $text" -ForegroundColor Red; exit 1 }

# The Microsoft Store's "python" placeholder only prints a message and exits with an error, so run each one to check.
function Find-Python {
    foreach ($candidate in @(@('python'), @('py', '-3'))) {
        $exe = $candidate[0]
        $rest = @($candidate | Select-Object -Skip 1)
        try {
            & $exe @rest -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>$null
            if ($LASTEXITCODE -eq 0) { return , $candidate }
        } catch { }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Fail (L '找不到 Python 3.9 以上。从 python.org 安装，并勾选 Add python.exe to PATH，然后重新打开终端' 'Python 3.9+ not found. Install it from python.org with "Add python.exe to PATH" ticked, then reopen the terminal')
}
$exe = $python[0]
$rest = @($python | Select-Object -Skip 1)
$cli = Join-Path $PSScriptRoot 'tools\forthmark.py'

if ($Uninstall) {
    Say (L '移除 hook、状态栏、/forthmark 命令' 'Removing hooks, status line and /forthmark commands')
    & $exe @rest $cli stop *> $null
    & $exe @rest $cli teardown
    if ($LASTEXITCODE -ne 0) { Fail (L '卸载失败，见上面的输出' 'Uninstall failed, see above') }
    Say (L '已卸载。状态数据保留在 ~\.forthmark，不需要了可以直接删除' 'Uninstalled. Status data stays in ~\.forthmark; delete it if you no longer need it')
    exit 0
}

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Warn (L '当前是管理员窗口。Forthmark 不需要管理员权限，建议用普通窗口安装和使用' 'This is an administrator window. Forthmark does not need it; a normal window is recommended')
}
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Warn (L '没找到 claude 命令：hook 会装好，装上 Claude Code 后即可生效' 'claude not found: hooks are installed anyway and take effect once Claude Code is installed')
}

Say (L '安装 Claude Code 全局 hook、状态栏和 /forthmark 命令（会先备份 settings.json）' 'Installing global Claude Code hooks, status line and /forthmark commands (settings.json is backed up first)')
$setup = @('setup')
if ($NoStatusline) { $setup += '--no-statusline' }
& $exe @rest $cli @setup
if ($LASTEXITCODE -ne 0) { Fail (L '安装失败，见上面的输出' 'Install failed, see above') }

Write-Host ''
Say (L '完成。在任一项目里打开 Claude Code，输入 /forthmark-add 接入' 'Done. In any project, open Claude Code and type /forthmark-add')
Write-Host (L "  打开面板：$exe `"$cli`" open" "  Open the panel: $exe `"$cli`" open")
Write-Host (L '  移动了工具目录后，重新运行一次 install.ps1' '  Re-run install.ps1 after moving the kit')
