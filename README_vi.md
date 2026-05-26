## Đề tài: Hệ thống nhận diện và tiêu diệt cỏ dại bằng YOLO + Servo + Laser

### 1. Cấu trúc dataset và format YOLO

- **Chia tập dữ liệu**:

  \[
  \text{Dataset} = \text{Train} + \text{Validation} + \text{Test}
  \]

  Ví dụ tỉ lệ:

  \[
  \text{Train} = 70\%,\quad \text{Validation} = 20\%,\quad \text{Test} = 10\%
  \]

- **Format nhãn YOLO cho từng bounding box**:

  \[
  \text{class\_id}\ \ x_{center}\ \ y_{center}\ \ width\ \ height
  \]

  Tất cả đều được **chuẩn hóa** theo kích thước ảnh:

  \[
  x_{center} = \frac{x_{box}}{W},\quad
  y_{center} = \frac{y_{box}}{H},\quad
  width = \frac{w_{box}}{W},\quad
  height = \frac{h_{box}}{H}
  \]

  trong đó \(W, H\) lần lượt là chiều rộng và chiều cao ảnh.

### 2. Công thức loss khi training YOLO

- **Loss tổng**:

  \[
  L = L_{box} + L_{obj} + L_{cls}
  \]

- **Bounding Box Loss** (dựa trên IoU):

  \[
  L_{box} = 1 - IoU,\quad
  IoU = \frac{Area_{intersection}}{Area_{union}}
  \]

- **Objectness Loss** (có / không có vật thể trong cell):

  \[
  L_{obj} = BCE(p,\ p_{gt})
  \]

- **Classification Loss** (phân loại giữa các lớp cây / cỏ):

  \[
  L_{cls} = BCE(c,\ c_{gt})
  \]

- **Cập nhật trọng số (Gradient Descent)**:

  \[
  w_{t+1} = w_t - \eta \nabla L
  \]

  với \(w\) là vector trọng số của model, \(\eta\) là learning rate, \(L\) là loss tổng ở trên.

### 3. Thuật toán training (pipeline)

Quy trình huấn luyện mô hình YOLO trong file `training/train.py`:

```text
Dataset (ảnh + nhãn YOLO)
   ↓
Data Augmentation (do Ultralytics YOLO thực hiện)
   ↓
Forward Propagation (tính dự đoán bbox, objectness, class)
   ↓
Tính Loss = L_box + L_obj + L_cls
   ↓
Backpropagation (tính gradient ∇L)
   ↓
Update Weights: w_{t+1} = w_t - η ∇L
   ↓
Epoch tiếp theo cho đến khi hội tụ
```

### 4. Công thức đánh giá: Precision, Recall, mAP

Sau khi train xong (weights lưu ở `models/best.pt`), hệ thống đánh giá bằng các chỉ số:

- **Precision**:

  \[
  Precision = \frac{TP}{TP + FP}
  \]

- **Recall**:

  \[
  Recall = \frac{TP}{TP + FN}
  \]

- **mAP** (mean Average Precision):

  \[
  mAP = \frac{1}{N}\sum_{i=1}^{N} AP_i
  \]

  trong đó \(AP_i\) là Average Precision của lớp thứ \(i\), và \(N\) là tổng số lớp (ở đây là 12 lớp cây/cỏ).

Các chỉ số này có thể xem trực tiếp trong thư mục `runs/train/weed_yolov8/results*.png` do Ultralytics sinh ra sau khi train.

### 5. Thuật toán chuyển tọa độ YOLO → góc servo

Với bounding box YOLO dạng pixel \((x_1, y_1, x_2, y_2)\) trên ảnh kích thước \(W \times H\):

1. **Tính tâm bbox**:

   \[
   x_c = \frac{x_1 + x_2}{2},\quad
   y_c = \frac{y_1 + y_2}{2}
   \]

2. **Chuẩn hóa vị trí tâm ảnh về \([-0.5, 0.5]\)**:

   \[
   n_x = \frac{x_c}{W} - \frac{1}{2},\quad
   n_y = \frac{y_c}{H} - \frac{1}{2}
   \]

3. **Đổi sang góc lệch tương đối theo FOV của camera** (góc nhìn ngang \(FOV_h\), dọc \(FOV_v\)):

   \[
   \Delta \alpha_x = -n_x \cdot FOV_h,\quad
   \Delta \alpha_y = n_y \cdot FOV_v
   \]

4. **Tính góc servo tuyệt đối** với góc trung tâm \(\theta_{pan}^0, \theta_{tilt}^0\):

   \[
   \theta_{pan} = \theta_{pan}^0 + \Delta \alpha_x,\quad
   \theta_{tilt} = \theta_{tilt}^0 + \Delta \alpha_y
   \]

5. **Giới hạn góc theo cơ khí**:

   \[
   \theta_{pan}^{final} = clamp(\theta_{pan}, \theta_{pan}^{min}, \theta_{pan}^{max}),
   \]
   \[
   \theta_{tilt}^{final} = clamp(\theta_{tilt}, \theta_{tilt}^{min}, \theta_{tilt}^{max})
   \]

Thuật toán trên được cài đặt trong `utils/coordinate_convert.py` (hàm `yolo_bbox_to_servo_angles`), và được sử dụng trong `main.py` cũng như `inference/detect_camera.py` để điều khiển servo xoay chính xác tới vị trí cỏ dại.

### 6. Pipeline AI hoàn chỉnh của hệ thống

```text
Camera
   ↓
Image Acquisition
   ↓
YOLO-based Weed Detector (models/best.pt)
   ↓
Bounding Box Detection + Weed Classification
   ↓
Coordinate Conversion (YOLO bbox → góc pan/tilt)
   ↓
Servo Control (PWM điều khiển pan/tilt)
   ↓
Laser Activation (bật laser khi phát hiện cỏ dại)
```

Khi triển khai trên Raspberry Pi:

- Train trên PC → xuất `models/best.pt`.
- Copy `best.pt` sang thư mục `models/` trên Raspberry Pi.
- Chạy `python main.py` để thực thi toàn bộ pipeline trên: camera → AI → servo → laser.

