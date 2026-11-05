$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try {
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Requires Windows x64.' }
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Install official Python 3.12 x64 with Python Launcher first: https://www.python.org/downloads/windows/'
    }
    & py -3.12 -c "import struct; assert struct.calcsize('P') == 8; import tkinter"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 with tkinter is required.' }
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        & py -3.12 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
    }
    & .\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check network and retry.' }
    & .\.venv\Scripts\python.exe -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    $privateDir = Join-Path $PSScriptRoot 'data'
    New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
    $userSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    & icacls $privateDir /inheritance:r /grant:r "*$($userSid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot restrict data directory permissions.' }
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'WeChatGroupAI.lnk'))
    $link.TargetPath = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
    $link.Arguments = '"' + (Join-Path $PSScriptRoot 'launch.py') + '"'
    $link.WorkingDirectory = $PSScriptRoot
    $link.Description = 'WeChat group AI assistant'
    $link.Save()
    Write-Host 'Installed. Log in to official WeChat manually, then open WeChatGroupAI on the desktop.'
    Write-Host 'Re-enter API key on this server. Use one group first; add up to two more after verifying replies.'
} catch {
    Write-Host ('Installation stopped: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
