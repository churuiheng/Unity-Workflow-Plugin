# Keeps the Unity editor in front for $args[0] minutes (default 5), refocusing every 20 s. $args[1]: project name filter.
$minutes = if ($args.Count -gt 0) { [double]$args[0] } else { 5 }
$project = if ($args.Count -gt 1) { [string]$args[1] } else { "" }
$focus = Join-Path $PSScriptRoot "focus_unity.ps1"
$end = (Get-Date).AddMinutes($minutes)
while ((Get-Date) -lt $end) { & $focus $project | Out-Null; Start-Sleep -Seconds 20 }
"kept Unity focused for $minutes min"
