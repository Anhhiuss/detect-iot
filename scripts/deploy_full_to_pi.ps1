# Full sync project -> Raspberry Pi (PowerShell, Windows)
# Usage:
#   .\scripts\deploy_full_to_pi.ps1
#   .\scripts\deploy_full_to_pi.ps1 -PiHost 192.168.23.105 -PiUser pi4b

param(
    [string]$PiHost = "192.168.23.105",
    [string]$PiUser = "pi4b",
    [string]$RemoteDir = "/home/pi4b/weed_detection_project",
    [switch]$IncludeDataset
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $ProjectRoot "run_weed_laser.py"))) {
    $ProjectRoot = (Get-Location).Path
}

Write-Host "[INFO] Local project: $ProjectRoot"
Write-Host "[INFO] Remote target: ${PiUser}@${PiHost}:$RemoteDir"

# Ensure remote directory exists
ssh "${PiUser}@${PiHost}" "mkdir -p $RemoteDir"

# Sync key folders/files (exclude heavy runtime artifacts)
$items = @(
    "config",
    "hardware",
    "inference",
    "scripts",
    "training",
    "utils",
    "main.py",
    "prepare_dataset.py",
    "run_weed_laser.py",
    "requirements.txt",
    "RUN_RASPBERRY_PI.md",
    "WIRING_RASPBERRY_PI.md",
    "OPTIMIZE_PI_FPS.md",
    "CALIBRATE_CAMERA_SERVO.md",
    "README_vi.md"
)

foreach ($item in $items) {
    $src = Join-Path $ProjectRoot $item
    if (Test-Path $src) {
        Write-Host "[COPY] $item"
        scp -r $src "${PiUser}@${PiHost}:${RemoteDir}/"
    } else {
        Write-Host "[SKIP] Missing: $item"
    }
}

# Models (if exists)
$modelBest = Join-Path $ProjectRoot "models\best.pt"
$modelBase = Join-Path $ProjectRoot "models\yolov8n.pt"
ssh "${PiUser}@${PiHost}" "mkdir -p $RemoteDir/models"
if (Test-Path $modelBest) { scp $modelBest "${PiUser}@${PiHost}:${RemoteDir}/models/" }
if (Test-Path $modelBase) { scp $modelBase "${PiUser}@${PiHost}:${RemoteDir}/models/" }

if ($IncludeDataset) {
    $ds = Join-Path $ProjectRoot "dataset_yolo"
    if (Test-Path $ds) {
        Write-Host "[COPY] dataset_yolo (this may take long)"
        scp -r $ds "${PiUser}@${PiHost}:${RemoteDir}/"
    } else {
        Write-Host "[WARN] dataset_yolo not found, skip."
    }
}

Write-Host ""
Write-Host "[DONE] Full project synced to Pi."
Write-Host "Verify on Pi:"
Write-Host "  ssh ${PiUser}@${PiHost} 'ls -la $RemoteDir; ls -la $RemoteDir/scripts'"
