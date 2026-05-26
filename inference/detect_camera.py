import argparse
from pathlib import Path
from time import time

import cv2
from ultralytics import YOLO

from utils.coordinate_convert import CameraConfig, yolo_bbox_to_servo_angles
from hardware.servo_control import ServoController
from hardware.laser_control import LaserController


def load_model(model_path: str | Path = "models/best.pt") -> YOLO:
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path}")
    return YOLO(str(path))


def run_camera_detection(
    model_path: str | Path = "models/best.pt",
    camera_index: int = 0,
    conf: float = 0.2,
    show: bool = True,
    target_class_id: int = 0,
    target_fps: float = 10.0,
) -> None:
    model = load_model(model_path)
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {camera_index}")

    cfg = CameraConfig()
    servo = ServoController()
    laser = LaserController()

    delay = 1.0 / max(target_fps, 1.0)
    last_time = 0.0

    try:
        while True:
            now = time()
            if now - last_time < delay:
                # simple FPS limiting
                continue
            last_time = now

            ret, frame = cap.read()
            if not ret:
                print("[WARN] Failed to read frame.")
                break

            h, w = frame.shape[:2]
            results = model.predict(source=frame, conf=conf, verbose=False)
            laser.off()

            best_det = None
            best_conf = 0.0

            if results:
                r = results[0]
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

                # draw bbox and center
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

            if show:
                cv2.imshow("Weed Detection", frame)
                if cv2.waitKey(1) & 0xFF == 27:  # ESC
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        servo.cleanup()
        laser.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run YOLO weed detection on camera with servo + laser.")
    parser.add_argument("--model", type=str, default="models/best.pt", help="Path to trained model")
    parser.add_argument("--camera", type=int, default=0, help="Camera index")
    parser.add_argument("--conf", type=float, default=0.2, help="Confidence threshold (lower = more sensitive)")
    parser.add_argument("--class-id", type=int, default=0, dest="target_class_id", help="Target class id (weed-only model: 0)")
    parser.add_argument("--no-show", action="store_true", help="Do not show OpenCV window")
    parser.add_argument("--fps", type=float, default=10.0, help="Target FPS (approx.)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_camera_detection(
        model_path=args.model,
        camera_index=args.camera,
        conf=args.conf,
        target_class_id=args.target_class_id,
        show=not args.no_show,
        target_fps=args.fps,
    )

