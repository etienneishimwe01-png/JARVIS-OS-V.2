$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $projectRoot "scripts\start_jarvis.bat"
$icon = Join-Path $projectRoot "JARVIS.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "JARVIS.lnk"

if (-not (Test-Path $launcher)) {
    throw "JARVIS launcher not found: $launcher"
}

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Launch the JARVIS Windows desktop assistant"
$shortcut.WindowStyle = 1
if (Test-Path $icon) {
    $shortcut.IconLocation = "$icon,0"
}
$shortcut.Save()

Write-Output "Created JARVIS shortcut: $shortcutPath"
