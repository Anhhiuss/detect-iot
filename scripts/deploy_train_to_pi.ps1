# Đồng bộ code + cấu hình training lên Raspberry Pi (PowerShell trên Windows)
# Dùng: .\scripts\deploy_train_to_pi.ps1
# Hoặc: .\scripts\deploy_train_to_pi.ps1 -PiHost 192.168.23.105 -PiUser pi4b

param(
    [string]$PiHost = "192.168.23.105",
    [string]$PiUser = "pi4b",
    [string]$RemoteDir = "~/weed_detection_project"
)

$ErrorActionPreference = "Stop"
# Thư mục gốc project (cùng cấp với thư mục scripts)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $ProjectRoot "training\train.py"))) {
    $ProjectRoot = (Get-Location).Path
}

Write-Host "[INFO] Project root: $ProjectRoot"
Write-Host "[INFO] Target: ${PiUser}@${PiHost}:$RemoteDir"

# Thư mục tạo trên Pi
ssh "${PiUser}@${PiHost}" "mkdir -p $RemoteDir/training $RemoteDir/config $RemoteDir/models $RemoteDir/scripts $RemoteDir/utils"

# Code training + chuẩn bị dataset + dependency
scp (Join-Path $ProjectRoot "training\train.py") "${PiUser}@${PiHost}:${RemoteDir}/training/"
scp (Join-Path $ProjectRoot "config\weed.yaml") "${PiUser}@${PiHost}:${RemoteDir}/config/"
scp (Join-Path $ProjectRoot "prepare_dataset.py") "${PiUser}@${PiHost}:${RemoteDir}/"
scp (Join-Path $ProjectRoot "requirements.txt") "${PiUser}@${PiHost}:${RemoteDir}/"

# Test camera headless + camera Pi (CSI)
$headless = Join-Path $ProjectRoot "scripts\test_camera_headless.py"
if (Test-Path $headless) {
    scp $headless "${PiUser}@${PiHost}:${RemoteDir}/scripts/"
    Write-Host "[OK] Copied scripts/test_camera_headless.py"
}
$campi = Join-Path $ProjectRoot "utils\camera_pi.py"
if (Test-Path $campi) {
    scp $campi "${PiUser}@${PiHost}:${RemoteDir}/utils/"
    Write-Host "[OK] Copied utils/camera_pi.py (for --picam2)"
}

# Model gốc (nếu có) để train từ pretrained
$yolo = Join-Path $ProjectRoot "models\yolov8n.pt"
if (Test-Path $yolo) {
    scp $yolo "${PiUser}@${PiHost}:${RemoteDir}/models/"
    Write-Host "[OK] Copied models/yolov8n.pt"
} else {
    Write-Host "[WARN] models/yolov8n.pt not found locally; Pi will download from Ultralytics on first train."
}

Write-Host ""
Write-Host "[DONE] Code training đã gửi lên Pi."
Write-Host "Tiếp theo trên Pi:"
Write-Host "  1) Gửi dataset: dataset/ hoặc dataset_yolo/ (scp -r ...)"
Write-Host "  2) ssh ${PiUser}@${PiHost}"
Write-Host "  cd $RemoteDir && python3 -m venv venv && source venv/bin/activate"
Write-Host "  pip install -U pip && pip install ultralytics opencv-python-headless numpy"
Write-Host "  python training/train.py --data config/weed.yaml --model yolov8n.pt --epochs 30 --imgsz 416 --batch 4 --device cpu"
