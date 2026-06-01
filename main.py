from __future__ import annotations

"""
Pi-only realtime weed detection:

Camera -> YOLO -> error_x/error_y -> servo + laser + motor.
"""

import argparse
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

try:
    import RPi.GPIO as GPIO
except ImportError:  # Running on PC
    GPIO = None  # type: ignore

from hardware.laser_control import LaserController
from hardware.motor_l298n import MotorL298N
from hardware.servo_pca9685 import ServoControllerPCA9685, ServoKitConfig
from hardware.wiring import WIRING


def load_model(model_path: str | Path = "models/best.pt") -> YOLO:
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path.resolve()}")
    return YOLO(str(path))


def run_system(
    model_path: str | Path = "models/best.pt",
    camera_index: int = 0,
    conf: float = 0.2,
    target_class_id: int = 1,
    target_fps: float = 10.0,
    show_window: bool = False,
    imgsz: int = 320,
    use_picam2: bool = False,
    pan_gain: float = 0.02,
    tilt_gain: float = 0.02,
    laser_deadband_x: float = 80.0,
    laser_deadband_y: float = 80.0,
    stable_frames_required: int = 3,
    motor_deadband_x: float = 140.0,
    motor_deadband_y: float = 140.0,
) -> None:
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

    if GPIO is not None and GPIO.getmode() is None:
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BOARD)

    servo = ServoControllerPCA9685(ServoKitConfig())
    laser = LaserController()
    motor = MotorL298N()

    pan_angle = 90.0
    tilt_angle = 90.0
    servo.set_angle(pan=pan_angle, tilt=tilt_angle)
    motor.forward()

    delay_sec = 1.0 / max(target_fps, 1.0)
    delay_ms = int(1000 * delay_sec)
    stable_hits = 0
    last_motor_state = "forward"
    last_detection_time = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Failed to read frame from camera.")
                break

            h, w = frame.shape[:2]
            center_x = w / 2.0
            center_y = h / 2.0

            results_list = model.predict(source=frame, conf=conf, verbose=False, imgsz=imgsz)

            detections = []
            if results_list:
                boxes = results_list[0].boxes
                if boxes is not None and len(boxes) > 0:
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        score = float(box.conf[0].item())
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        detections.append((cls_id, score, x1, y1, x2, y2))

            weed_det = None
            best_weed_conf = 0.0
            crop_count = 0

            for cls_id, score, x1, y1, x2, y2 in detections:
                if cls_id == 0:
                    crop_count += 1
                    if show_window:
                        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 180, 0), 2)
                        cv2.putText(
                            frame,
                            f"crop {score:.2f}",
                            (int(x1), max(20, int(y1) - 10)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 180, 0),
                            1,
                            cv2.LINE_AA,
                        )
                elif cls_id == target_class_id and score > best_weed_conf:
                    best_weed_conf = score
                    weed_det = (x1, y1, x2, y2, score)

            if weed_det is not None:
                last_detection_time = time.time()
                x1, y1, x2, y2, weed_conf = weed_det
                weed_x = (x1 + x2) / 2.0
                weed_y = (y1 + y2) / 2.0
                error_x = weed_x - center_x
                error_y = weed_y - center_y

                pan_angle = max(0.0, min(180.0, pan_angle + (error_x * pan_gain)))
                tilt_angle = max(0.0, min(180.0, tilt_angle + (error_y * tilt_gain)))
                servo.set_angle(pan=pan_angle, tilt=tilt_angle)

                aligned = abs(error_x) < laser_deadband_x and abs(error_y) < laser_deadband_y
                stable_hits = stable_hits + 1 if aligned else 0

                if stable_hits >= stable_frames_required:
                    laser.on()
                else:
                    laser.off()

                motor_should_stop = abs(error_x) < motor_deadband_x and abs(error_y) < motor_deadband_y
                desired_motor_state = "stop" if motor_should_stop else "forward"
                if desired_motor_state != last_motor_state:
                    if desired_motor_state == "stop":
                        motor.stop()
                    else:
                        motor.forward()
                    last_motor_state = desired_motor_state

                if show_window:
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                    cv2.circle(frame, (int(weed_x), int(weed_y)), 4, (0, 0, 255), -1)
                    cv2.circle(frame, (int(center_x), int(center_y)), 4, (255, 0, 0), -1)
                    cv2.putText(
                        frame,
                        f"weed {weed_conf:.2f} ex={error_x:.0f} ey={error_y:.0f} stable={stable_hits} crops={crop_count}",
                        (int(x1), max(20, int(y1) - 10)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        1,
                        cv2.LINE_AA,
                    )
            else:
                stable_hits = 0
                laser.off()
                if last_motor_state != "forward":
                    motor.forward()
                    last_motor_state = "forward"

                if time.time() - last_detection_time > 1.0:
                    pan_angle = 90.0 if pan_angle < 1.0 or pan_angle > 179.0 else pan_angle
                    tilt_angle = 90.0 if tilt_angle < 1.0 or tilt_angle > 179.0 else tilt_angle

            if show_window:
                cv2.putText(
                    frame,
                    f"crop_count={crop_count} weed_target={target_class_id}",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow("Weed Detection System", frame)
                key = cv2.waitKey(delay_ms) & 0xFF
                if key == 27:
                    break
            else:
                time.sleep(delay_sec)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        motor.cleanup()
        servo.cleanup()
        laser.cleanup()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pi-only weed detection: Camera -> YOLO -> servo + laser + motor")
    p.add_argument("--model", default="models/best.pt", help="Path to model")
    p.add_argument("--camera", type=int, default=0, help="Camera index (USB) or 0 when using --picam2")
    p.add_argument("--conf", type=float, default=0.2, help="Confidence threshold")
    p.add_argument("--fps", type=float, default=10.0, help="Target FPS")
    p.add_argument("--imgsz", type=int, default=320, help="Inference size")
    p.add_argument("--show", action="store_true", help="Show debug window")
    p.add_argument("--picam2", action="store_true", help="Use Pi Camera (CSI) via picamera2")
    p.add_argument("--class-id", type=int, default=1, dest="target_class_id", help="Target class ID (0=crop, 1=weed)")
    p.add_argument("--pan-gain", type=float, default=0.02, help="Pan update gain")
    p.add_argument("--tilt-gain", type=float, default=0.02, help="Tilt update gain")
    p.add_argument("--laser-deadband-x", type=float, default=80.0, help="Laser deadband in X")
    p.add_argument("--laser-deadband-y", type=float, default=80.0, help="Laser deadband in Y")
    p.add_argument("--stable-frames", type=int, default=3, help="Frames required before laser turns on")
    p.add_argument("--motor-deadband-x", type=float, default=140.0, help="Motor stop deadband in X")
    p.add_argument("--motor-deadband-y", type=float, default=140.0, help="Motor stop deadband in Y")
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
        pan_gain=args.pan_gain,
        tilt_gain=args.tilt_gain,
        laser_deadband_x=args.laser_deadband_x,
        laser_deadband_y=args.laser_deadband_y,
        stable_frames_required=args.stable_frames,
        motor_deadband_x=args.motor_deadband_x,
        motor_deadband_y=args.motor_deadband_y,
    )

