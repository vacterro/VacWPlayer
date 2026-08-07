' VacWPlayer - zero-console launcher (double-click this file)
' Runs VacWPlayer.bat with a hidden console window.
' If the app does not start, run VacWPlayer.bat manually to see errors.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.Run """" & dir & "\VacWPlayer.bat""", 0, False
