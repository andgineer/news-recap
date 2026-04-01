$LogDir = Join-Path $env:LOCALAPPDATA "news-recap\logs"
$LogFile = Join-Path $LogDir "news-recap-$(Get-Date -Format 'yyyy-MM-dd').log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Get-ChildItem $LogDir -Filter 'news-recap-*.log' |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$env:PATH = "$env:USERPROFILE\.local\bin;$env:LOCALAPPDATA\Microsoft\WinGet\Links;$env:PATH"

Add-Content -Path $LogFile -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===== news-recap"
Add-Content -Path $LogFile -Value "USER=$env:USERNAME"
try { Add-Content -Path $LogFile -Value "news-recap=$(Get-Command {{NEWS_RECAP_CMD}} -ErrorAction Stop)" } catch { Add-Content -Path $LogFile -Value "{{NEWS_RECAP_CMD}}: not in PATH" }

try {
    & {{NEWS_RECAP_CMD}} --no-color ingest {{RSS_ARGS}} *>> $LogFile
    if ($LASTEXITCODE -ne 0) { throw "ingest failed (exit $LASTEXITCODE)" }
    & {{NEWS_RECAP_CMD}} --no-color create {{AGENT_ARGS}} *>> $LogFile
    if ($LASTEXITCODE -ne 0) { throw "create failed (exit $LASTEXITCODE)" }
    Add-Content -Path $LogFile -Value "===== RESULT: OK"
} catch {
    Add-Content -Path $LogFile -Value "===== RESULT: FAILED ($($_.Exception.Message))"
}
