# Ordinary-user entry; preview is the default. Never changes Root or system settings.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Instance,
    [string]$Route,
    [double]$SpeedMps,
    [double]$DurationSeconds,
    [string]$Python = "python",
    [string]$Manager,
    [string]$Adb,
    [string]$Serial,
    [string]$Binding,
    [string]$Calibration,
    [string]$DeviceId,
    [string]$Journal = "local/agent.sqlite",
    [switch]$ExecuteVirtualReplay,
    [switch]$IsolatedNoPersonalData,
    [switch]$RecoverStop,
    [switch]$NoInteractive
)
$ErrorActionPreference = "Stop"
$arguments = @("-m", "swu_happyrun.cli", "mumu", "replay", "--instance", $Instance)
if ($RecoverStop) {
    $arguments += "--recover-stop"
} else {
    if (-not $Route -or $SpeedMps -le 0 -or $DurationSeconds -le 0) {
        throw "Provide Route, positive SpeedMps and positive DurationSeconds."
    }
    $arguments += @("--route", $Route, "--speed-mps",
        $SpeedMps.ToString([Globalization.CultureInfo]::InvariantCulture),
        "--duration-seconds", $DurationSeconds.ToString([Globalization.CultureInfo]::InvariantCulture))
}
if ($ExecuteVirtualReplay) {
    if (-not $IsolatedNoPersonalData) { throw "Explicit isolated-instance confirmation is required." }
    if (-not $Manager -or -not $Adb -or -not $Serial -or -not $Binding -or -not $DeviceId) {
        throw "Execution needs Manager, Adb, Serial, Binding and the registered DeviceId."
    }
    if (-not $RecoverStop -and -not $Calibration) { throw "Execution needs local Calibration." }
    $arguments += @("--execute-virtual-replay", "--isolated-no-personal-data", "--manager", $Manager,
        "--adb", $Adb, "--serial", $Serial, "--binding", $Binding,
        "--device-id", $DeviceId, "--journal", $Journal)
    if ($Calibration) { $arguments += @("--calibration", $Calibration) }
}
if ($NoInteractive) { $arguments += "--no-interactive" }
& $Python @arguments
exit $LASTEXITCODE
