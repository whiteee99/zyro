# Creates ZYRO's shortcuts (run any time to repair them all):
#   1. Desktop icon          -> opens the System window (no console)
#   2. Start Menu icon       -> same, findable by typing "zyro"
#   3. Startup hotkey helper -> Ctrl+Alt+Z works from boot, invisibly
$ErrorActionPreference = "Stop"

$pythonw = "D:\zyro\venv\Scripts\pythonw.exe"
$script  = "D:\zyro\gui.py"
$hotkey  = "D:\zyro\hotkey.pyw"
$icon    = "D:\zyro\zyro.ico"
$workdir = "D:\zyro"

if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found at $pythonw" }

$shell = New-Object -ComObject WScript.Shell

function New-ZyroShortcut($path, $target, $arguments) {
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $target
    $lnk.Arguments = $arguments
    $lnk.WorkingDirectory = $workdir
    $lnk.IconLocation = "$icon,0"
    $lnk.Description = "ZYRO - the System"
    $lnk.Save()
    Write-Host "created: $path"
}

New-ZyroShortcut ([Environment]::GetFolderPath("Desktop") + "\ZYRO.lnk") `
                  $pythonw ('"' + $script + '"')
New-ZyroShortcut ([Environment]::GetFolderPath("Programs") + "\ZYRO.lnk") `
                  $pythonw ('"' + $script + '"')
New-ZyroShortcut ([Environment]::GetFolderPath("Startup") + "\ZYRO hotkey.lnk") `
                  $pythonw ('"' + $hotkey + '"')

# Also start the hotkey helper right now (in case it is not running).
$running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*hotkey*' }
if (-not $running) {
    Start-Process $pythonw -ArgumentList ('"' + $hotkey + '"') `
        -WindowStyle Hidden
    Write-Host "started: hotkey helper"
}

Write-Host ""
Write-Host "Done."
Write-Host "  Desktop / Start Menu : double-click ZYRO to launch"
Write-Host "  Ctrl+Alt+Z           : summon or launch ZYRO from anywhere"
Write-Host "  (if Ctrl+Alt+Z ever stops working, run this script again)"
