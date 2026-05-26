# Chạy realtime trên Raspberry Pi + camera

## 1. Chuẩn bị Raspberry Pi

- **Raspberry Pi 4 Model B** (khuyến nghị 2GB RAM trở lên).
- **Camera**: USB webcam **hoặc** Pi Camera (CSI).
- **Raspberry Pi OS** (64-bit khuyến nghị).

## 2. Copy project và model lên Pi

- Copy toàn bộ thư mục `weed_detection_project` từ PC sang Pi (SCP, USB, Git…).
- Đảm bảo có file **`models/best.pt`** (model đã train trên PC).

## 3. Cài đặt môi trường trên Pi

```bash
cd ~/weed_detection_project

# Tạo virtualenv (tùy chọn)
python3 -m venv venv
source venv/bin/activate   # Linux

# Cài thư viện (trên Pi có sẵn RPi.GPIO)
pip install -r requirements.txt
```

**Nếu dùng Pi Camera (CSI):**

```bash
sudo apt update
sudo apt install -y python3-picamera2
```

## 4. Chạy realtime

Có hai cách chạy:

- **`main.py`**: dùng servo GPIO (pin 17/27); hỗ trợ Pi Camera (--picam2).
- **`run_weed_laser.py`**: script đơn giản theo đúng 6 bước (YOLO → tọa độ → góc servo → servo + laser); hỗ trợ **GPIO** hoặc **PCA9685** (--pca9685). Công thức servo đơn giản `(x/width)*180`: dùng thêm `--simple`.

### USB webcam (camera index 0)

```bash
python3 main.py --camera 0 --fps 8 --imgsz 320
```

- `--fps 8`: giới hạn ~8 FPS cho Pi.
- `--imgsz 320`: inference nhanh (320 hoặc 416); bỏ hoặc `--imgsz 640` nếu cần chính xác hơn.

### Pi Camera (CSI) qua picamera2

```bash
python3 main.py --picam2 --fps 8 --imgsz 320
```

### Có màn hình, muốn xem khung hình (debug)

```bash
python3 main.py --camera 0 --show --fps 5 --imgsz 320
```

### Dừng chương trình

- **Không có cửa sổ**: `Ctrl+C`.
- **Có cửa sổ**: nhấn **ESC** hoặc `Ctrl+C`.

## 5. Tham số dòng lệnh

| Tham số     | Mặc định      | Ý nghĩa |
|------------|----------------|---------|
| `--model`  | `models/best.pt` | Đường dẫn model |
| `--camera` | `0`            | Index camera (USB) |
| `--conf`   | `0.5`          | Ngưỡng confidence |
| `--fps`    | `10`           | FPS mục tiêu (~5–10 trên Pi) |
| `--imgsz`  | `320`          | Kích thước inference (320 nhanh, 640 chính xác) |
| `--show`   | tắt            | Bật cửa sổ xem ảnh |
| `--picam2` | tắt            | Dùng Pi Camera (CSI) qua picamera2 |
| `--class-id` | `0`          | Class cần nhắm (0 = Black-grass theo weed.yaml) |

## 6. Kết nối phần cứng (servo + laser)

- **Servo pan**: GPIO 17 (BCM), **Servo tilt**: GPIO 27 (BCM) — chỉnh trong `hardware/servo_control.py` nếu khác.
- **Laser**: GPIO 22 (BCM) — chỉnh trong `hardware/laser_control.py` nếu khác.

Nếu chạy **không gắn Pi** (test trên PC): servo và laser chạy chế độ **simulate** (in log, không điều khiển thật).

## 7. Dùng servo qua PCA9685 (ServoKit)

Nếu bạn nối servo qua board **PCA9685** (I2C):

```bash
pip install adafruit-circuitpython-servokit
python run_weed_laser.py --pca9685 --imgsz 320
```

Sơ đồ nối dây chi tiết: xem **WIRING_RASPBERRY_PI.md**.  
Tối ưu FPS 15–20: xem **OPTIMIZE_PI_FPS.md**.  
**Calibrate camera → servo** để laser bắn trúng cỏ: xem **CALIBRATE_CAMERA_SERVO.md**.

## 8. FPS thực tế trên Pi 4

- `imgsz=320`, YOLOv8n: khoảng **5–10 FPS** tùy Pi 4 2GB/4GB.
- Giảm `--fps` xuống 5 nếu Pi bị quá tải.
