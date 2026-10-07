# Synex QB Portal - install as a Windows background service (scheduled task) with daily backups.
# Run ONCE in an Administrator PowerShell on the computer that hosts the portal:
#   powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
param(
    [int]$Port = 8000,
    [string]$BackupTime = "01:00"
)
$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Run this script as Administrator." }

$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Python virtual environment not found: $Python" }
if (-not (Test-Path (Join-Path $Backend ".env"))) { throw "backend\.env is missing" }
if (-not (Test-Path (Join-Path $Root "frontend\dist\frontend\browser\index.html"))) { throw "Build the frontend first (ng build)" }

# 1. the portal: starts with Windows, restarts if it stops
$action = New-ScheduledTaskAction -Execute $Python -Argument "run.py $Port" -WorkingDirectory $Backend

$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName "Synex QB Portal" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

# 2. daily database + attachments backup
$bAction = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Root\deploy\windows\backup.ps1`""
$bTrigger = New-ScheduledTaskTrigger -Daily -At $BackupTime
Register-ScheduledTask -TaskName "Synex QB Portal Backup" -Action $bAction -Trigger $bTrigger -Principal $principal -Force | Out-Null

# 3. let other computers on the network open the portal
if (-not (Get-NetFirewallRule -DisplayName "Synex QB Portal" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Synex QB Portal" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Domain,Private | Out-Null
}

Start-ScheduledTask -TaskName "Synex QB Portal"
Start-Sleep -Seconds 8
try { $h = Invoke-RestMethod "http://localhost:$Port/api/health"; Write-Host "Portal is running: $($h.status)" -ForegroundColor Green }
catch { Write-Warning "Portal did not answer yet. Check Task Scheduler > 'Synex QB Portal'." }
Write-Host "Daily backup at $BackupTime -> $Root\backups"
Write-Host "Open http://$(hostname):$Port from other computers on the network."
