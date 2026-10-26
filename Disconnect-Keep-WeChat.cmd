@echo off
set "WXAI_DISCONNECT=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:WXAI_DISCONNECT); & ([scriptblock]::Create(($s -split '(?m)^# DISCONNECT_START\r?$',2)[1]))"
pause
exit /b
# DISCONNECT_START
$ErrorActionPreference = 'Stop'
try {
    if ((Get-CimInstance Win32_OperatingSystem).ProductType -eq 1) { throw 'Run on the Windows SERVER, not your own PC.' }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Right-click this file and choose Run as administrator.' }
    $currentSession = [Diagnostics.Process]::GetCurrentProcess().SessionId
    if ($currentSession -le 0) { throw 'Run inside your interactive remote desktop session.' }
    if ($env:SESSIONNAME -notlike 'RDP-*') { throw 'This does not appear to be an RDP session. No changes made.' }
    Write-Host "Transferring YOUR current session $currentSession to console. RDP will disconnect."
    Write-Host 'The desktop may remain unlocked. Anyone with server console access could access it.'
    Write-Host 'No password, firewall, auto-login or lock policy changes are made.'
    & "$env:SystemRoot\System32\tscon.exe" $currentSession /dest:console
    if ($LASTEXITCODE -ne 0) { throw "Session transfer failed: $LASTEXITCODE. Send this screen." }
} catch {
    Write-Host ('STOPPED: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
