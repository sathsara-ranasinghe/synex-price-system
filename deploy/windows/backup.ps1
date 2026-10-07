# Daily PostgreSQL backup for Synex QB Portal. Keeps the last 14 days.
param(
    [string]$BackendDir = (Resolve-Path "$PSScriptRoot\..\..\backend").Path,
    [string]$BackupDir = (Join-Path (Resolve-Path "$PSScriptRoot\..\..").Path "backups"),
    [int]$KeepDays = 14
)
$ErrorActionPreference = "Stop"
$envFile = Join-Path $BackendDir ".env"
$url = (Get-Content $envFile | Where-Object { $_ -match '^DATABASE_URL=' }) -replace '^DATABASE_URL=', ''
if ($url -notmatch '^postgresql\+psycopg://(?<user>[^:]+):(?<pw>[^@]+)@(?<host>[^:/]+)(:(?<port>\d+))?/(?<db>.+)$') {
    throw "DATABASE_URL in $envFile is not a PostgreSQL URL"
}
$pgDump = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\pg_dump.exe" | Sort-Object FullName -Descending | Select-Object -First 1
if (-not $pgDump) { throw "pg_dump.exe not found under C:\Program Files\PostgreSQL" }
New-Item -ItemType Directory -Force $BackupDir | Out-Null
$file = Join-Path $BackupDir ("synex_{0}_{1:yyyyMMdd_HHmm}.dump" -f $Matches.db, (Get-Date))
$env:PGPASSWORD = $Matches.pw
$port = if ($Matches.port) { $Matches.port } else { "5432" }
& $pgDump.FullName -h $Matches.host -p $port -U $Matches.user -Fc -f $file $Matches.db
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed ($LASTEXITCODE)" }
# attachments are files on disk: zip them next to the database dump
$att = Join-Path $BackendDir "data\attachments"
if (Test-Path $att) { Compress-Archive -Path $att -DestinationPath ($file -replace '\.dump$', '_attachments.zip') -Force }
Get-ChildItem $BackupDir -Filter "synex_*" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-$KeepDays) } | Remove-Item -Force
Write-Output "Backup written: $file"
