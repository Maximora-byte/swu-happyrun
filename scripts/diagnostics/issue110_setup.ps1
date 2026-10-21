# Fixed setup for issue 110. No original test invocation occurs in this script.
param([Parameter(Mandatory)][ValidateSet('1', '2')][string]$Group)
$ErrorActionPreference = 'Stop'
$evidence = Join-Path $env:GITHUB_WORKSPACE "evidence/group-$Group.json"
[void](New-Item -ItemType Directory -Force -Path (Split-Path $evidence))
$receipt = [ordered]@{
    schema = 1; source = '6a0dac84bf66125c7e2bd506bb0d8c988b1dcc34'
    tree = '09b5064a5e30495f7ced68b84fe453bd5d0413ce'; group = $Group
    batch = 'issue110-native-two-groups-1'; status = 'setup_incomplete'
    original_group_started = $false; subject_verified = $false
    setup_stage = 'entry'; tool_exit = $null; blocker = $null
    setup_parent_exit_verified = $null; setup_descendant_cleanup = 'unverified'
}
function Save-Receipt {
    $receipt | ConvertTo-Json | Set-Content -LiteralPath $evidence -Encoding utf8
}
Save-Receipt
try {
    $receipt.setup_stage = 'python_source_check'
    foreach ($name in @('UV_PYTHON_INSTALL_MIRROR', 'UV_PYTHON_DOWNLOADS_JSON_URL', 'UV_ASTRAL_MIRROR_URL', 'UV_PYTHON_CPYTHON_BUILD', 'UV_CONFIG_FILE', 'UV_WORKING_DIR', 'UV_PROJECT')) {
        if ([Environment]::GetEnvironmentVariable($name)) { throw 'python_source_override' }
    }
    $deadline = [DateTimeOffset]::FromUnixTimeSeconds([long]$env:ISSUE110_SETUP_STARTED).AddSeconds(300)
    # Leave time for a fixed failure receipt before the existing two-minute step ceiling.
    $stepDeadline = [DateTimeOffset]::UtcNow.AddSeconds(110)
    if ($stepDeadline -lt $deadline) { $deadline = $stepDeadline }
    # Allocate this job's own install root; never reuse a preinstalled interpreter.
    $installRoot = [IO.Path]::GetFullPath((Join-Path $env:RUNNER_TEMP "issue110-python-$Group"))
    if (Test-Path -LiteralPath $installRoot) { throw 'python_install_directory_exists' }
    [void](New-Item -ItemType Directory -Path $installRoot)
    $uv = (Get-Command uv -CommandType Application).Source
    function Invoke-UvStage([string]$Stage, [string[]]$Arguments) {
        $receipt.setup_stage = $Stage
        $receipt.tool_exit = $null
        $receipt.setup_parent_exit_verified = $null
        Save-Receipt
        # Reserve two seconds for terminating this setup process and writing its receipt.
        $milliseconds = [int][Math]::Floor(($deadline - [DateTimeOffset]::UtcNow).TotalMilliseconds - 2000)
        if ($milliseconds -le 0) { throw 'setup_deadline' }
        $out = Join-Path $env:RUNNER_TEMP "issue110-$Stage.stdout"
        $err = Join-Path $env:RUNNER_TEMP "issue110-$Stage.stderr"
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $uv
        $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.ArgumentList.Add('--no-config')
        if ($Stage -in @('python_install', 'python_find')) {
            $info.Environment['UV_PYTHON_NO_REGISTRY'] = '1'
            $info.Environment['UV_PYTHON_INSTALL_DIR'] = $installRoot
        }
        foreach ($argument in $Arguments) { $info.ArgumentList.Add($argument) }
        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        $streams = @()
        $started = $false
        try {
            $started = $process.Start()
            if (-not $started) { throw 'setup_api_error' }
            $receipt.setup_parent_exit_verified = $false
            $streams = @([IO.File]::Create($out), [IO.File]::Create($err))
            $copies = [Threading.Tasks.Task[]]@(
                $process.StandardOutput.BaseStream.CopyToAsync($streams[0]),
                $process.StandardError.BaseStream.CopyToAsync($streams[1])
            )
            do {
                $milliseconds = [int][Math]::Floor(($deadline - [DateTimeOffset]::UtcNow).TotalMilliseconds - 2000)
                if ($milliseconds -le 0) { throw 'setup_deadline' }
                if (($streams[0].Length + $streams[1].Length) -gt 4194304) { throw 'setup_output_limit' }
            } until ($process.WaitForExit([Math]::Min(100, $milliseconds)))
            $receipt.tool_exit = $process.ExitCode
            $receipt.setup_parent_exit_verified = $true
            Save-Receipt
            if ($null -eq $receipt.tool_exit -or $receipt.tool_exit -ne 0) { throw 'setup_stage_failed' }
            if (-not [Threading.Tasks.Task]::WaitAll($copies, $milliseconds)) { throw 'setup_deadline' }
            if (($streams[0].Length + $streams[1].Length) -gt 4194304) { throw 'setup_output_limit' }
            return $out
        } finally {
            try {
                if ($started -and -not $process.HasExited) {
                    $process.Kill($true)
                    $receipt.setup_parent_exit_verified = $process.WaitForExit(1000)
                }
            } finally {
                foreach ($stream in $streams) { $stream.Dispose() }
                $process.Dispose()
            }
        }
    }
    [void](Invoke-UvStage 'python_install' @('python', 'install', '3.11.16', '--no-bin'))
    $findOutput = Invoke-UvStage 'python_find' @('python', 'find', '--managed-python', '3.11.16')
    $found = Get-Content -LiteralPath $findOutput -Raw
    if ([string]::IsNullOrWhiteSpace($found)) { throw 'python_path_missing' }
    $python = $found.Trim()
    if ($python -match '[\r\n]' -or -not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'python_path_invalid' }
    $python = [IO.Path]::GetFullPath($python)
    $ownedPrefix = $installRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $python.StartsWith($ownedPrefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'python_path_not_owned' }
    # A lexically nested junction/symlink must not redirect writes outside the owned root.
    $cursor = $python
    while ($true) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'python_path_not_owned' }
        if ($cursor -eq $installRoot) { break }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    $requirements = Join-Path $env:RUNNER_TEMP 'issue110-frozen.txt'
    [void](Invoke-UvStage 'frozen_export' @('export', '--project', 'subject', '--frozen', '--extra', 'server', '--extra', 'agent', '--extra', 'dev', '--no-emit-project', '--format', 'requirements-txt', '--output-file', $requirements))
    [void](Invoke-UvStage 'frozen_sync' @('pip', 'sync', '--python', $python, '--break-system-packages', '--require-hashes', $requirements))
    [void](Invoke-UvStage 'editable_install' @('pip', 'install', '--python', $python, '--break-system-packages', '--no-deps', '--editable', 'subject'))
    if ([DateTimeOffset]::UtcNow -ge $deadline) { throw 'setup_deadline' }
    "ISSUE110_PYTHON=$python" >> $env:GITHUB_ENV
    $receipt.status = 'setup_complete'
    # This setup snapshot cannot assert what a later controller process does.
    $receipt.original_group_started = $null
    Save-Receipt
    exit 0
} catch {
    $receipt.status = 'prerequisites_missing'
    $known = @('setup_deadline', 'setup_stage_failed', 'setup_output_limit', 'python_path_missing', 'python_path_invalid', 'python_source_override', 'python_install_directory_exists', 'python_path_not_owned')
    $receipt.blocker = if ($_.Exception.Message -in $known) { $_.Exception.Message } else { 'setup_api_error' }
    Save-Receipt
    exit 1
}
