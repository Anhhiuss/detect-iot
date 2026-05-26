"""
Hiện camera với crosshair tại tâm ảnh để calibrate: đặt vật mục tiêu trùng tâm.
Chạy: python scripts/calibrate_crosshair.py
Thoát: ESC
"""
import cv2

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    raise SystemExit("Cannot open camera 0")
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

print("Đặt vật mục tiêu trùng crosshair đỏ tại tâm. Nhấn ESC để thoát.")

while True:
    ret, frame = cap.read()
    if not ret:
        break
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.line(frame, (cx - 30, cy), (cx + 30, cy), (0, 0, 255), 2)
    cv2.line(frame, (cx, cy - 30), (cx, cy + 30), (0, 0, 255), 2)
    cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
    cv2.putText(frame, "center", (cx - 25, cy - 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
    cv2.imshow("Calibrate - center = servo 90", frame)
    if cv2.waitKey(1) & 0xFF == 27:
        break

cap.release()
cv2.destroyAllWindows()
