' Silent launcher for ReaStream Bridge — drop in shell:startup for auto-start
' Runs minimized with no console window flicker

Dim fso, scriptDir
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

CreateObject("WScript.Shell").Run "pythonw """ & scriptDir & "\reastream_bridge.py"" -d auto -b 2.0 --send-block 512", 0, False
