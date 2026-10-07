# Remove the Synex QB Portal scheduled tasks and firewall rule (data and backups are kept).
$ErrorActionPreference = "SilentlyContinue"
Stop-ScheduledTask -TaskName "Synex QB Portal"
Unregister-ScheduledTask -TaskName "Synex QB Portal" -Confirm:$false
Unregister-ScheduledTask -TaskName "Synex QB Portal Backup" -Confirm:$false
Remove-NetFirewallRule -DisplayName "Synex QB Portal"
Write-Host "Removed. Database, attachments and backups were not touched."
