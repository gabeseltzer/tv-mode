; tvmode hotkeys (AutoHotkey v2)
;
;   Ctrl+Alt+T   -> tv mode
;   Ctrl+Alt+G   -> game mode
;   Ctrl+Alt+M   -> toggle between the two
;
; Adjust TVMODE below to however you installed it:
;   - dev checkout:   'uv run --project "G:\Programing\tv-mode" tvmode'
;   - pipx / global:  'tvmode'
;   - packaged exe:   '"C:\Program Files\tvmode\tvmode.exe"'

#Requires AutoHotkey v2.0
#SingleInstance Force

TVMODE := 'uv run --project "' A_ScriptDir '" tvmode'

RunMode(args) {
    global TVMODE
    ; Run hidden; a failure pops a tooltip with the exit code.
    rc := RunWait(A_ComSpec ' /c ' TVMODE ' ' args, , 'Hide')
    if (rc != 0) {
        TrayTip('tvmode ' args ' failed (exit ' rc ')', 'tvmode', 'Iconx')
    }
}

^!t:: RunMode('apply tv')
^!g:: RunMode('apply game')
^!m:: RunMode('toggle')
