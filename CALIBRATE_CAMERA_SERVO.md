# Calibrate camera → servo để laser bắn trúng cỏ 100%

Nhiều hệ thống AI bị **lệch**: camera thấy cỏ ở tâm ảnh nhưng laser lại chiếu lệch. Calibration giúp bù sai lệch cơ khí và góc quang học.

---

## 1. Nguyên tắc

- **Camera center** (giữa ảnh) phải tương ứng **servo 90° pan, 90° tilt** (laser nhìn thẳng).
- Nếu lắp camera/laser lệch hoặc servo “90°” không đúng trục, laser sẽ lệch. Ta bù bằng **offset_pan** và **offset_tilt** trong code.

---

## 2. Chuẩn bị

- Raspberry Pi + camera + servo pan-tilt + laser (đã nối dây đúng).
- Một **vật mục tiêu cố định** (ví dụ chấm đen trên giấy trắng hoặc viên sỏi) đặt trước camera.

---

## 3. Bước 1: Đưa mục tiêu vào đúng tâm ảnh

1. Chạy chương trình **chỉ hiển thị camera** (không cần YOLO), vẽ **crosshair tại tâm ảnh** (ví dụ `width//2`, `height//2`).
2. Đặt vật mục tiêu sao cho nó nằm **đúng dưới crosshair** trên màn hình (tức là ở tâm ảnh).
3. Cố định camera và vật, không xoay nữa.

Ví dụ script đơn giản (chỉ camera + crosshair):

```python
import cv2
cap = cv2.VideoCapture(0)
while True:
    ret, frame = cap.read()
    if not ret:
        break
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.line(frame, (cx - 20, cy), (cx + 20, cy), (0, 0, 255), 2)
    cv2.line(frame, (cx, cy - 20), (cx, cy + 20), (0, 0, 255), 2)
    cv2.imshow("Center", frame)
    if cv2.waitKey(1) & 0xFF == 27:
        break
cap.release()
cv2.destroyAllWindows()
```

---

## 4. Bước 2: Đặt servo về 90° (trung lập)

- Trong code servo, set **pan = 90, tilt = 90** (hoặc dùng script test servo).
- Quan sát: **laser có chiếu đúng vào vật mục tiêu** (đang ở tâm ảnh) không?
  - **Có** → không cần offset (offset_pan = 0, offset_tilt = 0).
  - **Không** → laser lệch so với vật; chuyển sang bước 3.

---

## 5. Bước 3: Đo và nhập offset

- **Laser lệch sang phải** so với tâm → cần xoay pan **sang trái** → giảm góc pan → **offset_pan âm** (vd: -2, -3).
- **Laser lệch sang trái** → **offset_pan dương** (vd: +2).
- **Laser lệch lên trên** → **offset_tilt âm**.
- **Laser lệch xuống dưới** → **offset_tilt dương**.

Chỉnh từng bước nhỏ (0.5° hoặc 1°), chạy lại và quan sát:

```bash
python run_weed_laser.py --show --offset-pan -2 --offset-tilt 1
```

Lặp lại cho đến khi **laser trùng vật mục tiêu** khi vật ở tâm ảnh và servo 90°/90°.

---

## 6. Lưu offset vào code (cố định)

Sau khi tìm được giá trị ổn định (vd: offset_pan = -2, offset_tilt = 1):

**Cách 1 – tham số dòng lệnh (khuyến nghị khi demo):**

```bash
python run_weed_laser.py --offset-pan -2 --offset-tilt 1
```

**Cách 2 – sửa mặc định trong code:**

- Nếu dùng **công thức FOV** (`utils/coordinate_convert.py`): trong `CameraConfig` đặt  
  `offset_pan = -2.0`, `offset_tilt = 1.0` (thay số theo giá trị bạn đo).
- Nếu dùng **công thức đơn giản** (`run_weed_laser.py`): truyền `--offset-pan` và `--offset-tilt` vào hàm `yolo_bbox_to_servo_angles_simple`; hoặc thêm biến cấu hình và đọc từ file/config.

---

## 7. Kiểm tra với YOLO

- Bật lại YOLO (detect cỏ thật hoặc vật mục tiêu).
- Đưa cỏ/vật vào **tâm ảnh** (hoặc để YOLO vẽ bbox quanh vật).
- Servo xoay theo tâm bbox; laser bắn.
- Nếu vẫn lệch nhẹ: chỉnh thêm **offset_pan** / **offset_tilt** (có thể khác một chút so với lúc chỉ có crosshair vì bbox là tâm cỏ, không phải tâm toàn ảnh).

---

## 8. Tóm tắt

| Bước | Việc cần làm |
|------|-------------------------------|
| 1 | Vật mục tiêu đặt đúng tâm ảnh (crosshair). |
| 2 | Servo 90°/90°, xem laser có trùng vật không. |
| 3 | Nếu lệch: chỉnh offset_pan, offset_tilt (âm/dương theo hướng lệch). |
| 4 | Chạy với `--offset-pan ... --offset-tilt ...` hoặc sửa mặc định trong code. |
| 5 | Test với YOLO, tinh chỉnh thêm nếu cần. |

Sau khi calibrate đúng, **laser sẽ bắn trúng cỏ** khi YOLO đưa tâm bbox về đúng vị trí và servo dùng cùng offset đó.
