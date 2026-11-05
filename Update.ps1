param([string]$Target = 'C:\WeChatGroupAI\WeChatGroupAI-server-package')
$ErrorActionPreference = 'Stop'
$source = [IO.Path]::GetFullPath($PSScriptRoot)
$targetRoot = [IO.Path]::GetFullPath($Target).TrimEnd('\')
$files = @('app.py','core.py','features.py','engine.py','launch.py','README.md','使用指南.md','Start.cmd','Disconnect-Keep-WeChat.cmd')
try {
    if ($source.TrimEnd('\') -eq $targetRoot) { throw 'Extract the update ZIP into a SEPARATE folder, then run UPDATE.cmd.' }
    $python = Join-Path $targetRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Existing installation not found. For a new installation, run Install.cmd in the extracted folder.' }
    $running=$null
    try { $running=[Threading.Mutex]::OpenExisting('Local\WeChatGroupAI_single_instance') } catch [Threading.WaitHandleCannotBeOpenedException] {}
    if ($running) { $running.Dispose();throw 'Close the AI assistant first. Keep WeChat logged in.' }
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath (Join-Path $source $file))) { throw "Missing $file. Extract the WHOLE ZIP." }
    }
    & $python -m py_compile (Join-Path $source 'app.py') (Join-Path $source 'engine.py') (Join-Path $source 'core.py') (Join-Path $source 'features.py') (Join-Path $source 'launch.py')
    if ($LASTEXITCODE -ne 0) { throw 'Python check failed. No files changed.' }
    $backup=Join-Path $targetRoot ('backups\before-v4.1-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $existing=@()
    foreach ($file in $files) {
        $old=Join-Path $targetRoot $file
        if (Test-Path -LiteralPath $old) { Copy-Item -LiteralPath $old -Destination (Join-Path $backup $file);$existing+=$file }
    }
    try {
        foreach ($file in $files) { Copy-Item -LiteralPath (Join-Path $source $file) -Destination (Join-Path $targetRoot $file) -Force }
    } catch {
        foreach ($file in $files) {
            $destination=Join-Path $targetRoot $file
            if ($existing -contains $file) { Copy-Item -LiteralPath (Join-Path $backup $file) -Destination $destination -Force }
            elseif (Test-Path -LiteralPath $destination) {
                # Only fixed allowlisted files directly inside the verified target directory.
                if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($destination)) -ne $targetRoot) { throw 'Rollback path check failed.' }
                Remove-Item -LiteralPath $destination -Force
            }
        }
        throw
    }
    Write-Host 'SUCCESS: Updated to v4.1. API key, settings, history and Python preserved.' -ForegroundColor Green
    Write-Host "Backup: $backup"
    Write-Host 'Open your usual shortcut. Existing group settings migrate automatically. Add at most two more groups.'
    Write-Host 'Complete any WeChat login/security verification manually before starting.'
} catch {
    Write-Host ('STOPPED: '+$_.Exception.Message) -ForegroundColor Red
    exit 1
}
