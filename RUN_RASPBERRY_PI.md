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

- **`main.py`**: chạy Pi-only, YOLO trên Pi, servo PCA9685, laser GPIO và motor L298N.
- **`run_weed_laser.py`**: script cũ theo workflow khác; nếu bạn chỉ dùng Pi-only thì ưu tiên `main.py`.

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
| `--class-id` | `1`          | Class cần nhắm (0 = crop, 1 = weed) |

## 6. Kết nối phần cứng

### Servo qua PCA9685

Dây đang nối theo cấu hình bạn xác nhận:

- Servo pan → PCA9685 channel 14
- Servo tilt → PCA9685 channel 15
- PCA9685 nối I2C với Pi (SDA, SCL, VCC, GND)

### Laser

- Laser + transistor: VCC, pin 16, GND
- Trong code, laser đang dùng **BOARD pin 16**

### Motor qua L298N

- IN3 → pin 32
- IN4 → pin 33

Trong code, motor đang dùng **BOARD numbering** nên sẽ khớp trực tiếp với dây này.

Nếu chạy **không có Pi thật** thì các module sẽ tự chuyển sang chế độ **simulate** và chỉ in log.

### Cách chạy

```bash
python scripts/selftest_pi_hardware.py
python main.py --picam2 --imgsz 320 --fps 8
```

## 7. Cài thêm cho PCA9685

Nếu dùng PCA9685/ServoKit:

```bash
pip install adafruit-circuitpython-servokit
pip install adafruit-blinka
```

Bật I2C rồi kiểm tra thiết bị:

```bash
sudo raspi-config
sudo i2cdetect -y 1
```

## 8. Chạy self-test phần cứng

Script test nhanh servo, laser và motor:

```bash
python scripts/selftest_pi_hardware.py
```

## 9. FPS thực tế trên Pi 4

- `imgsz=320`, YOLOv8n: khoảng **5–10 FPS** tùy Pi 4 2GB/4GB.
- Giảm `--fps` xuống 5 nếu Pi bị quá tải.
- Model `models/best.pt` hiện có **2 class**: `0=crop`, `1=weed`.
