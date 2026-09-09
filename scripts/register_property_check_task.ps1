param([switch]$Activate)
$ErrorActionPreference = 'Stop'
$workspacePath = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $workspacePath '.venv\Scripts\pythonw.exe'
$runnerPath = Join-Path $workspacePath 'scripts\detect_property_changes.py'
if (!(Test-Path -LiteralPath $pythonPath) -or !(Test-Path -LiteralPath $runnerPath)) {
    throw 'Existing CommandCore runtime or runner is missing.'
}
$taskName = 'CommandCore Property Change Checks'
$taskArguments = '-B "' + $runnerPath + '" --scheduled'
$accountName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
if (!$Activate) {
    [pscustomobject]@{TaskName=$taskName; Cadence='Every 2 hours'; Cost=0; RequiresSignedInUser=$true; RunLevel='Limited'; Activated=$false}
    return
}
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    if ($existingTask.Actions.Count -ne 1 -or $existingTask.Actions[0].Execute -ne $pythonPath -or
        $existingTask.Actions[0].Arguments -ne $taskArguments -or $existingTask.Actions[0].WorkingDirectory -ne $workspacePath -or
        $existingTask.Principal.RunLevel -ne 'Limited' -or $existingTask.Principal.LogonType -ne 'Interactive') {
        throw 'A different task already exists. No task was changed.'
    }
    $existingTask | Select-Object TaskName, State
    return
}
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $taskArguments -WorkingDirectory $workspacePath
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId $accountName -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description 'Read-only Credit Friendly Homes property change checks. Local checkpoint only; no CRM/Google writes or communications.' |
    Select-Object TaskName, State
