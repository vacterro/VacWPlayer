' WildRiftAssistant - zero-console launcher (double-click this file)
' Runs WildRiftAssistant.bat with a hidden console window.
' If the app does not start, run WildRiftAssistant.bat manually to see errors.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.Run """" & dir & "\WildRiftAssistant.bat""", 0, False
