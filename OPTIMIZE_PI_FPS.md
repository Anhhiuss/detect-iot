# Tối ưu model để chạy realtime 15–20 FPS trên Raspberry Pi

## 1. Chọn model nhẹ

- **YOLOv8n** (nano) đã dùng là phù hợp; không cần đổi sang YOLOv8s/m/l trên Pi.
- Giữ file `models/best.pt` (đã train từ yolov8n).

## 2. Giảm kích thước inference (imgsz)

- **imgsz=320**: nhanh nhất, FPS cao, độ chính xác giảm chút.
- **imgsz=416**: cân bằng.
- **imgsz=640**: chính xác hơn, chậm hơn.

Trên Pi 4, khuyến nghị:

```bash
python run_weed_laser.py --imgsz 320
# hoặc
python main.py --imgsz 320 --fps 15
```

## 3. Export sang ONNX (tùy chọn, thường nhanh hơn)

Chạy một lần trên PC hoặc Pi:

```python
from ultralytics import YOLO
model = YOLO("models/best.pt")
model.export(format="onnx", imgsz=320, simplify=True)
# Sinh ra models/best.onnx
```

Chạy inference bằng ONNX (cần `onnxruntime`):

```bash
pip install onnxruntime
```

Trong code, load ONNX thay vì .pt:

```python
model = YOLO("models/best.onnx")
```

Một số máy (đặc biệt có GPU/NPU) chạy ONNX nhanh hơn .pt.

## 4. Giới hạn FPS và tránh xử lý thừa

- Đặt **target FPS** vừa phải (10–15) để Pi không bị quá tải.
- **Tắt hiện cửa sổ** khi chạy thật: không dùng `--show`.
- Trong vòng lặp chỉ gọi `model.predict()` một lần mỗi frame; tránh vẽ ảnh hoặc ghi file không cần thiết.

## 5. Phần cứng và hệ điều hành

- **Raspberry Pi 4** 2GB trở lên; **Pi 5** sẽ nhanh hơn rõ.
- Dùng **Raspberry Pi OS 64-bit** (khuyến nghị).
- Gắn **tản nhiệt** để tránh throttle khi chạy lâu.
- Nếu có **USB webcam**: chọn độ phân giải 640x480 trong code để giảm tải đọc ảnh.

## 6. Frame skip và target confirmation

- **Frame skip**: chỉ chạy YOLO mỗi N frame để tăng FPS (giảm tải CPU).
  ```bash
  python run_weed_laser.py --frame-skip 2
  ```
  → FPS hiệu quả tăng gần 2× (vì bỏ qua 1 frame giữa mỗi lần inference).

- **Target confirmation**: chỉ bắn laser sau khi cỏ xuất hiện **N frame liên tiếp** (servo vẫn xoay mỗi frame).
  ```bash
  python run_weed_laser.py --confirm 3
  ```
  → Servo ít rung, laser không nhấp nháy lung tung.

- **verbose=False** đã dùng trong `model.predict(..., verbose=False)` để tắt log.

## 7. Đo FPS thực tế

Thêm vào vòng lặp (ví dụ trong `run_weed_laser.py`):

```python
import time
fps_start = time.perf_counter()
fps_frames = 0
# Trong loop, mỗi frame:
fps_frames += 1
if fps_frames % 30 == 0:
    elapsed = time.perf_counter() - fps_start
    print(f"FPS (approx): {fps_frames / elapsed:.1f}")
```

Hoặc dùng Ultralytics:

```python
results = model.predict(frame, imgsz=320, verbose=False)
# results[0].speed  # dict với 'inference', 'preprocess', ...
```

## 8. Camera khuyến nghị

- **Raspberry Pi Camera Module 3** (standard) hoặc USB webcam.
- Đặt **resolution 640×480**, **fps 30** nếu có thể (trong `utils/camera_pi.py` có tham số `width`, `height`, `framerate`).

## 9. Tóm tắt tham số khuyến nghị cho ~15–20 FPS (Pi 4)

| Tham số   | Gợi ý   |
|----------|---------|
| Model    | YOLOv8n (best.pt) |
| imgsz    | 320     |
| --fps    | 15 hoặc 20 (giới hạn vòng lặp) |
| --show   | Tắt     |
| Export   | Có thể thử ONNX (imgsz=320) |

Trên **Pi 5** hoặc Pi 4 với ONNX + imgsz=320, mức **15–20 FPS** là khả thi; Pi 4 với .pt thường ở khoảng **8–12 FPS** tùy ảnh.
