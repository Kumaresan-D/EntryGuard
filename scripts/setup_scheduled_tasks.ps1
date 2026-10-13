<#
.SYNOPSIS
Registers two daily Windows Scheduled Tasks for the NVR video pipeline:
  1. EntryGuard-NVRDownload  - runs scripts.nvr_download at -DownloadTime
  2. EntryGuard-UploadVideos - runs scripts.upload_downloaded_videos -DelayHours later

Run this once scripts/nvr_download.py works end-to-end manually (with
NVR_HEADLESS=false while debugging) - these scheduled runs use the headless
default instead.

    powershell -ExecutionPolicy Bypass -File scripts\setup_scheduled_tasks.ps1
    powershell -ExecutionPolicy Bypass -File scripts\setup_scheduled_tasks.ps1 -DownloadTime "20:00" -DelayHours 4

Re-run any time to change the times - it replaces existing tasks with the
same names rather than duplicating them. Both tasks are registered to run
only while you're logged in (no Windows account password is stored anywhere);
if you need them to run while logged off, open Task Scheduler and change a
task's "Run whether user is logged on or not" setting yourself.
#>
param(
    [string]$DownloadTime = "20:00",
    [double]$DelayHours = 4
)

$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectDir "venv\Scripts\python.exe"

$downloadTimeSpan = [TimeSpan]::Parse($DownloadTime)
$uploadTotalMinutes = ($downloadTimeSpan.TotalMinutes + $DelayHours * 60) % 1440
$uploadTime = "{0:00}:{1:00}" -f [math]::Floor($uploadTotalMinutes / 60), ($uploadTotalMinutes % 60)

function Register-DailyTask {
    param([string]$Name, [string]$ModuleName, [string]$AtTime)

    $action = New-ScheduledTaskAction -Execute $PythonExe -Argument "-m $ModuleName" -WorkingDirectory $ProjectDir
    $trigger = New-ScheduledTaskTrigger -Daily -At $AtTime
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

    Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Write-Host "Registered '$Name' to run daily at $AtTime"
}

Register-DailyTask -Name "EntryGuard-NVRDownload" -ModuleName "scripts.nvr_download" -AtTime $DownloadTime
Register-DailyTask -Name "EntryGuard-UploadVideos" -ModuleName "scripts.upload_downloaded_videos" -AtTime $uploadTime

Write-Host ""
Write-Host "Note: DelayHours is a fixed guess, not a real completion check - if the" -ForegroundColor Yellow
Write-Host "NVR sometimes takes longer than $DelayHours hours to finish saving files," -ForegroundColor Yellow
Write-Host "the upload task will run too early and find nothing (or a partial set)." -ForegroundColor Yellow
Write-Host "Re-run this script with a larger -DelayHours if that happens." -ForegroundColor Yellow
Write-Host ""
Write-Host "View/edit these in Task Scheduler, or remove with:"
Write-Host "  Unregister-ScheduledTask -TaskName 'EntryGuard-NVRDownload' -Confirm:`$false"
Write-Host "  Unregister-ScheduledTask -TaskName 'EntryGuard-UploadVideos' -Confirm:`$false"
