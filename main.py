from __future__ import annotations

"""
Main entrypoint for full weed detection system:

Camera -> YOLO -> bounding box -> servo angles -> servo + laser.

Designed to:
- Train on PC (see training/train.py)
- Deploy and run on Raspberry Pi 4 (real-time, camera USB hoặc CSI).
"""

import argparse
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

from utils.coordinate_convert import CameraConfig, yolo_bbox_to_servo_angles
from hardware.servo_control import ServoController
from hardware.laser_control import LaserController


def load_model(model_path: str | Path = "models/best.pt") -> YOLO:
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path.resolve()}")
    return YOLO(str(path))


def run_system(
    model_path: str | Path = "models/best.pt",
    camera_index: int = 0,
    conf: float = 0.2,
    target_class_id: int = 0,
    target_fps: float = 10.0,
    show_window: bool = False,
    imgsz: int = 640,
    use_picam2: bool = False,
) -> None:
    """
    Run full loop. Trên Raspberry Pi: show_window=False, imgsz=320 để chạy nhanh.
    """
    print(f"[INFO] Loading model from {model_path} ...")
    model = load_model(model_path)

    try:
        from utils.camera_pi import open_camera
        print(f"[INFO] Opening camera (picam2={use_picam2}, index={camera_index}) ...")
        cap = open_camera(camera_index=camera_index, use_picam2=use_picam2)
    except Exception:
        print(f"[INFO] Opening camera index {camera_index} (OpenCV) ...")
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {camera_index}")

    cfg = CameraConfig()
    servo = ServoController()
    laser = LaserController()

    delay_sec = 1.0 / max(target_fps, 1.0)
    delay_ms = int(1000 * delay_sec)

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Failed to read frame from camera.")
                break

            h, w = frame.shape[:2]

            # Run inference (imgsz nhỏ hơn = nhanh hơn trên Pi)
            results_list = model.predict(source=frame, conf=conf, verbose=False, imgsz=imgsz)
            laser.off()

            best_det = None
            best_conf = 0.0

            if results_list:
                r = results_list[0]
                boxes = r.boxes
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        score = float(box.conf[0].item())
                        if cls_id != target_class_id:
                            continue
                        if score > best_conf:
                            best_conf = score
                            best_det = box

            if best_det is not None:
                x1, y1, x2, y2 = best_det.xyxy[0].tolist()
                pan, tilt = yolo_bbox_to_servo_angles((x1, y1, x2, y2), (w, h), cfg)
                servo.set_angle(pan=pan, tilt=tilt)
                laser.on()

                if show_window:
                    # Draw box for visualization
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    cv2.circle(frame, (cx, cy), 4, (0, 0, 255), -1)
                    cv2.putText(
                        frame,
                        f"weed {best_conf:.2f}",
                        (int(x1), int(y1) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        1,
                        cv2.LINE_AA,
                    )

            if show_window:
                cv2.imshow("Weed Detection System", frame)
                key = cv2.waitKey(delay_ms) & 0xFF
                if key == 27:  # ESC
                    break
            else:
                time.sleep(delay_sec)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        servo.cleanup()
        laser.cleanup()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weed detection realtime: Camera -> YOLO -> Servo + Laser")
    p.add_argument("--model", default="models/best.pt", help="Path to model")
    p.add_argument("--camera", type=int, default=0, help="Camera index (USB) or 0 khi dùng --picam2")
    p.add_argument("--conf", type=float, default=0.2, help="Confidence threshold (lower = more sensitive)")
    p.add_argument("--fps", type=float, default=10.0, help="Target FPS")
    p.add_argument("--imgsz", type=int, default=640, help="Inference size (640 chuẩn model mới, 320 nhanh hơn)")
    p.add_argument("--show", action="store_true", help="Hiện cửa sổ (PC); trên Pi nên tắt")
    p.add_argument("--picam2", action="store_true", help="Dùng Pi Camera (CSI) qua picamera2")
    p.add_argument("--class-id", type=int, default=0, dest="target_class_id", help="Class ID mục tiêu (model weed-only: 0=weed)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_system(
        model_path=args.model,
        camera_index=args.camera,
        conf=args.conf,
        target_class_id=args.target_class_id,
        target_fps=args.fps,
        show_window=args.show,
        imgsz=args.imgsz,
        use_picam2=args.picam2,
    )

