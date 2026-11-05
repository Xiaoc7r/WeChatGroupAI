@echo off
set "WXAI_REPAIR=%~f0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:WXAI_REPAIR); & ([scriptblock]::Create(($s -split '(?m)^# REPAIR_START\r?$',2)[1]))"
pause
exit /b
# REPAIR_START
$ErrorActionPreference = 'Stop'
try {
    $root = 'C:\WeChatGroupAI\WeChatGroupAI-server-package'
    $python = Join-Path $root '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Run on the server where WeChatGroupAI is installed.' }
    Write-Host '[1/4] Checking Windows Python modules (no API calls or chat access)...'
    & $python -c "import win32api, win32gui, win32ui, pythoncom; print('Windows modules OK')"
    if ($LASTEXITCODE -eq 0) {
        Write-Host 'SUCCESS: Modules already work. Close and reopen the assistant.' -ForegroundColor Green
        exit 0
    }
    Write-Host '[2/4] Downloading Microsoft Visual C++ x64 runtime. Timeout: 120 seconds.'
    $runtime = Join-Path ([Environment]::GetFolderPath('Desktop')) 'VC_redist.x64.exe'
    if (-not (Test-Path -LiteralPath $runtime)) {
        $runtime = Join-Path $env:TEMP ('wxai-vcredist-' + [guid]::NewGuid().ToString() + '.exe')
        & curl.exe --fail --location --connect-timeout 10 --max-time 120 --progress-bar --output $runtime 'https://aka.ms/vc14/vc_redist.x64.exe'
        if ($LASTEXITCODE -ne 0) { throw 'Runtime download failed. Send the error shown above.' }
    }
    Write-Host 'Checking Microsoft digital signature...'
    $sig = Get-AuthenticodeSignature -LiteralPath $runtime
    if ($sig.Status -ne 'Valid' -or $sig.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'Microsoft signature verification failed.' }
    Write-Host '[3/4] Installing runtime. Allow the Windows administrator prompt if shown.'
    $proc = Start-Process -FilePath $runtime -ArgumentList '/install /quiet /norestart' -Verb RunAs -PassThru -WindowStyle Hidden
    $elapsed = 0
    while (-not $proc.WaitForExit(10000)) {
        $elapsed += 10
        Write-Host "Runtime setup still running: $elapsed seconds."
        if ($elapsed -ge 180) { throw 'Setup is still running. Do not repeat installation; send this screen.' }
    }
    if ($proc.ExitCode -notin @(0,1638,3010)) { throw "Runtime installer exit code: $($proc.ExitCode)" }
    Write-Host '[4/4] Checking actual win32ui import...'
    & $python -c "import win32api, win32gui, win32ui, pythoncom; print('Windows modules OK')"
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Repairing pywin32 package at the existing pinned version...'
        & $python -m pip install --index-url https://mirrors.aliyun.com/pypi/simple/ --timeout 15 --retries 1 --only-binary=:all: --force-reinstall --no-deps pywin32==312
        if ($LASTEXITCODE -ne 0) { throw 'pywin32 repair failed. Send this screen.' }
        & $python -c "import win32api, win32gui, win32ui, pythoncom; print('Windows modules OK')"
        if ($LASTEXITCODE -ne 0) { throw 'DLL import still fails. Send the full error above; do not reinstall everything.' }
    }
    Write-Host 'SUCCESS: win32ui import verified. Reopen WeChatGroupAI and start again.' -ForegroundColor Green
    Write-Host 'This verifies Windows modules only, not WeChat connectivity or unattended operation.'
} catch {
    Write-Host ('STOPPED: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
