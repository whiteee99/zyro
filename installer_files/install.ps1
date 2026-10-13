# ZYRO installer script for the portable zip (run on the new PC).
# Right-click this file -> "Run with PowerShell".
# Creates: desktop icon + Ctrl+Alt+Z hotkey (auto-starts with Windows).
$ErrorActionPreference = "Stop"

$dir = $PSScriptRoot
$exe = Join-Path $dir "ZYRO.exe"
if (-not (Test-Path $exe)) { throw "ZYRO.exe not found next to this script." }

$shell = New-Object -ComObject WScript.Shell

# 1) Desktop shortcut -> the exe in this folder
$lnk = $shell.CreateShortcut([Environment]::GetFolderPath("Desktop") + "\ZYRO.lnk")
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = $dir
$lnk.IconLocation = "$dir\zyro.ico,0"
$lnk.Description = "ZYRO - your personal AI"
$lnk.Save()
Write-Host "created: desktop ZYRO icon"

# 2) Ctrl+Alt+Z hotkey helper at startup (invisible background)
$hk = $shell.CreateShortcut([Environment]::GetFolderPath("Startup") + "\ZYRO hotkey.lnk")
$hk.TargetPath = $exe
$hk.Arguments = "--hotkey"
$hk.WorkingDirectory = $dir
$hk.IconLocation = "$dir\zyro.ico,0"
$hk.Description = "ZYRO Ctrl+Alt+Z hotkey"
$hk.Save()
Write-Host "created: startup hotkey helper (Ctrl+Alt+Z)"

# 3) Start it right now too
Start-Process $exe -ArgumentList "--hotkey" -WindowStyle Hidden
Write-Host ""
Write-Host "Done! Double-click the ZYRO icon, or press Ctrl+Alt+Z."
Write-Host "Reminder: install Ollama first if you have not (see README.txt)."
