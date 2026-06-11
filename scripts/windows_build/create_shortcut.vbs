' ============================================================================
' Tiger Motors Digital Twin - Desktop Shortcut Creator
' ============================================================================
'
' Creates a desktop shortcut to TigerMotorsDT.exe.
'
' Usage:
'   Double-click this file (from the same folder as TigerMotorsDT.exe)
'   OR  cscript create_shortcut.vbs
'
' The shortcut is created on the current user's desktop.
' ============================================================================

Option Explicit

Dim objShell, objFSO, objShortcut
Dim strDesktopPath, strShortcutPath, strTargetPath, strWorkingDir
Dim strScriptDir, strExePath
Dim intResult

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strExePath = objFSO.BuildPath(strScriptDir, "TigerMotorsDT.exe")
strWorkingDir = strScriptDir
strDesktopPath = objShell.SpecialFolders("Desktop")
strShortcutPath = objFSO.BuildPath(strDesktopPath, "Tiger Motors Digital Twin.lnk")

If Not objFSO.FileExists(strExePath) Then
    MsgBox "Error: TigerMotorsDT.exe not found!" & vbCrLf & vbCrLf & _
           "Expected location: " & strExePath & vbCrLf & vbCrLf & _
           "Place this script in the same folder as TigerMotorsDT.exe.", _
           vbCritical, "Tiger Motors Digital Twin - Shortcut Creator"
    WScript.Quit 1
End If

If objFSO.FileExists(strShortcutPath) Then
    intResult = MsgBox("A shortcut already exists on the desktop." & vbCrLf & vbCrLf & _
                       "Replace it?", _
                       vbYesNo + vbQuestion, "Tiger Motors Digital Twin - Shortcut Creator")
    If intResult = vbNo Then
        WScript.Quit 0
    End If
    objFSO.DeleteFile strShortcutPath, True
End If

Set objShortcut = objShell.CreateShortcut(strShortcutPath)
objShortcut.TargetPath = strExePath
objShortcut.WorkingDirectory = strWorkingDir
objShortcut.Description = "Tiger Motors Digital Twin - Production Monitor & Configuration"
objShortcut.WindowStyle = 1
objShortcut.IconLocation = strExePath & ",0"
objShortcut.Save

If objFSO.FileExists(strShortcutPath) Then
    MsgBox "Desktop shortcut created!" & vbCrLf & vbCrLf & _
           "Shortcut location: " & strShortcutPath, _
           vbInformation, "Tiger Motors Digital Twin - Shortcut Creator"
    WScript.Quit 0
Else
    MsgBox "Failed to create the desktop shortcut. Check permissions and retry.", _
           vbCritical, "Tiger Motors Digital Twin - Shortcut Creator"
    WScript.Quit 1
End If

Set objShortcut = Nothing
Set objFSO = Nothing
Set objShell = Nothing
