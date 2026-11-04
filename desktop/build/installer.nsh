; Uninstall: stop the service (its python.exe would stay locked) and, unless this is an update,
; take the hooks out of Claude Code. Status data in ~/.forthmark is kept.
!macro customUnInstall
  nsExec::Exec '"$INSTDIR\resources\python\python.exe" "$INSTDIR\resources\kit\tools\forthmark.py" stop'
  Pop $0
  ${ifNot} ${isUpdated}
    nsExec::Exec '"$INSTDIR\resources\python\python.exe" "$INSTDIR\resources\kit\tools\forthmark.py" teardown'
    Pop $0
  ${endIf}
  Sleep 500
!macroend
