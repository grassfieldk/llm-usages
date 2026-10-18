Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
shell.Run """" & root & "\.venv\Scripts\pythonw.exe"" """ & root & "\app.py""", 0, False
