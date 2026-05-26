"""
Full system runner (one-shot file):

Camera (USB/PiCam3) -> YOLO detect (multi boxes/classes) -> select 1 target -> servo pan/tilt -> laser.

Supports:
- Raspberry Pi Camera v3 (CSI) via picamera2: --picam2
- USB webcam via OpenCV: --camera 0/1
- Servo via GPIO (default) or PCA9685 (ServoKit): --pca9685
- Multi-class detection: --classes 0,1,2,...
- Target selection strategy for servo: --aim center|area|conf
- Stability: --confirm N, --frame-skip N
- Laser pulse: --pulse 0.3
- Calibration offsets: --offset-pan / --offset-tilt

Run (headless, recommended on Pi):
  python3 full_system_run.py --picam2 --imgsz 320 --frame-skip 2 --confirm 3 --pulse 0.3
  python3 full_system_run.py --camera 0 --imgsz 320 --frame-skip 2 --confirm 3 --pulse 0.3

RT (default): capture runs in a background thread (latest-frame slot); laser pulse is non-blocking;
  --watchdog-stale-sec forces laser OFF if no fresh frames. Legacy: --no-rt-capture.

Exit:
  Ctrl+C (headless) or ESC when --show enabled.
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

from hardware.laser_control import LaserController
from utils.coordinate_convert import CameraConfig, yolo_bbox_to_servo_angles, yolo_bbox_to_servo_angles_simple
from utils.rt_tasks import LatestFrameBuffer, StaleFrameWatchdog, capture_loop_worker


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def parse_class_set(classes_csv: str | None, default_one: int | None) -> set[int] | None:
    # No filter -> accept all classes from model.
    if not classes_csv and default_one is None:
        return None
    if not classes_csv and default_one is not None:
        return {default_one}
    out: set[int] = set()
    for p in classes_csv.split(","):
        p = p.strip()
        if not p:
            continue
        if not p.isdigit():
            raise ValueError(f"Invalid class id in --classes: '{p}'")
        out.add(int(p))
    return out or {default_one}


def select_target(dets: list[dict], w: int, h: int, aim: str) -> dict | None:
    if not dets:
        return None
    aim = aim.lower()
    if aim == "conf":
        return max(dets, key=lambda d: d["conf"])
    if aim == "area":
        return max(dets, key=lambda d: d["area"])
    if aim == "center":
        cx0, cy0 = w / 2.0, h / 2.0
        return min(dets, key=lambda d: (d["cx"] - cx0) ** 2 + (d["cy"] - cy0) ** 2)
    raise ValueError("aim must be one of: conf, area, center")


def split_large_weed_boxes(
    frame,
    dets: list[dict],
    area_ratio_min: float,
    min_comp_area_px: float,
) -> list[dict]:
    """Split coarse weed box into sub-boxes via HSV+connected-components."""
    h, w = frame.shape[:2]
    out: list[dict] = []
    for d in dets:
        if d["area"] / max(1.0, float(w * h)) < area_ratio_min:
            out.append(d)
            continue

        x1 = max(0, int(d["x1"]))
        y1 = max(0, int(d["y1"]))
        x2 = min(w, int(d["x2"]))
        y2 = min(h, int(d["y2"]))
        if x2 - x1 < 6 or y2 - y1 < 6:
            out.append(d)
            continue

        roi = frame[y1:y2, x1:x2]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (25, 35, 25), (95, 255, 255))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=1)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)

        split_count = 0
        for i in range(1, n):
            sx, sy, sw, sh, sa = stats[i]
            if sa < min_comp_area_px:
                continue
            gx1, gy1 = x1 + float(sx), y1 + float(sy)
            gx2, gy2 = gx1 + float(sw), gy1 + float(sh)
            area = max(0.0, gx2 - gx1) * max(0.0, gy2 - gy1)
            out.append(
                {
                    "cls": d["cls"],
                    "conf": d["conf"],
                    "x1": gx1,
                    "y1": gy1,
                    "x2": gx2,
                    "y2": gy2,
                    "cx": (gx1 + gx2) / 2.0,
                    "cy": (gy1 + gy2) / 2.0,
                    "area": area,
                }
            )
            split_count += 1
        if split_count == 0:
            out.append(d)
    return out


def open_usb_camera(index: int) -> cv2.VideoCapture:
    if os.name == "posix":
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if cap.isOpened():
            return cap
    return cv2.VideoCapture(index)


def open_any_camera(camera_index: int, picam2: bool) -> object:
    if picam2:
        from utils.camera_pi import open_camera as open_pi_camera

        return open_pi_camera(
            camera_index=camera_index,
            use_picam2=True,
            width=640,
            height=480,
            framerate=15.0,
        )

    return open_usb_camera(camera_index)


def main() -> int:
    ap = argparse.ArgumentParser(description="Full runner: YOLO + servo + laser")
    ap.add_argument("--model", default="models/best.pt")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--picam2", action="store_true", help="Use Pi Camera (CSI) via picamera2")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--debug-dets", action="store_true", help="Print per-frame detection summary")

    ap.add_argument("--class-id", type=int, default=None, dest="default_class_id")
    ap.add_argument("--classes", type=str, default=None, help="CSV class ids to detect (e.g. 0,1,2)")
    ap.add_argument("--aim", default="center", choices=["center", "area", "conf"])

    ap.add_argument("--frame-skip", type=int, default=1)
    ap.add_argument("--confirm", type=int, default=1)
    ap.add_argument("--pulse", type=float, default=0.0, metavar="SEC")
    ap.add_argument("--continuous-laser", action="store_true", help="Keep laser ON while target is tracked (unsafe)")
    ap.add_argument("--pulse-cooldown", type=float, default=0.6, metavar="SEC", help="Min interval between 2 pulses")
    ap.add_argument("--lost-off", type=int, default=3, help="Turn laser OFF only after losing target this many processed frames")
    ap.add_argument("--min-on-ms", type=int, default=120, help="Minimum ON hold time before OFF is allowed")

    ap.add_argument("--simple", action="store_true", help="Simple mapping (x/width)*180 instead of FOV mapping")
    ap.add_argument("--offset-pan", type=float, default=0.0)
    ap.add_argument("--offset-tilt", type=float, default=0.0)
    ap.add_argument(
        "--camera-on-servo",
        action="store_true",
        help="Use incremental visual-servo control for camera+laser mounted on the same pan/tilt head",
    )
    ap.add_argument("--vs-kp-pan", type=float, default=18.0, help="Visual-servo gain for pan axis")
    ap.add_argument("--vs-kp-tilt", type=float, default=18.0, help="Visual-servo gain for tilt axis")
    ap.add_argument("--vs-deadband-px", type=float, default=12.0, help="No motion zone around frame center (pixels)")
    ap.add_argument("--vs-max-step", type=float, default=6.0, help="Max degree update per frame in camera-on-servo mode")
    ap.add_argument("--vs-ema-alpha", type=float, default=0.35, help="EMA for image error smoothing in camera-on-servo mode")
    ap.add_argument("--vs-fire-radius-px", type=float, default=16.0, help="Require target close to center before firing")
    ap.add_argument("--vs-settle-frames", type=int, default=2, help="Require this many centered frames before firing")
    ap.add_argument("--servo-min", type=float, default=20.0, help="Servo minimum angle clamp")
    ap.add_argument("--servo-max", type=float, default=160.0, help="Servo maximum angle clamp")

    ap.add_argument("--pca9685", action="store_true", help="Use PCA9685 ServoKit instead of GPIO PWM")
    ap.add_argument("--pan-ch", type=int, default=0, help="PCA9685 channel for pan servo")
    ap.add_argument("--tilt-ch", type=int, default=1, help="PCA9685 channel for tilt servo")

    ap.add_argument(
        "--no-rt-capture",
        action="store_true",
        help="Legacy: read camera in the main thread (no background capture)",
    )
    ap.add_argument(
        "--watchdog-stale-sec",
        type=float,
        default=3.0,
        metavar="SEC",
        help="If no fresh camera frame for this long, force laser OFF; 0 disables",
    )
    ap.add_argument("--split-weed-boxes", action="store_true", help="Split large weed detections into sub-boxes")
    ap.add_argument("--split-area-ratio", type=float, default=0.12, help="Only split if box area ratio >= this")
    ap.add_argument("--split-min-comp-area", type=float, default=120.0, help="Min area (px) for each split component")
    args = ap.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path.resolve()}")

    model = YOLO(str(model_path))

    if args.pca9685:
        from hardware.servo_pca9685 import ServoControllerPCA9685, ServoKitConfig

        servo_cfg = ServoKitConfig(
            pan_channel=args.pan_ch,
            tilt_channel=args.tilt_ch,
            min_angle=0.0,
            max_angle=180.0,
        )
        servo = ServoControllerPCA9685(cfg=servo_cfg)
    else:
        from hardware.servo_control import ServoController

        servo = ServoController()

    laser = LaserController()

    cap = open_any_camera(args.camera, picam2=args.picam2)
    if not cap.isOpened():
        raise RuntimeError("Cannot open camera (USB/PiCam). Check wiring/index/permissions.")

    allowed = parse_class_set(args.classes, default_one=args.default_class_id)
    cfg = None if args.simple else CameraConfig(offset_pan=args.offset_pan, offset_tilt=args.offset_tilt)

    delay = 1.0 / 10.0
    frame_id = 0
    confirm_count = 0
    laser_status = "OFF"
    laser_is_on = False
    last_seen_target_frame = -10**9
    laser_on_since = 0.0
    last_pulse_ts = 0.0
    current_pan = clamp(90.0 + args.offset_pan, args.servo_min, args.servo_max)
    current_tilt = clamp(90.0 + args.offset_tilt, args.servo_min, args.servo_max)
    servo.set_angle(pan=current_pan, tilt=current_tilt)
    ema_err_x = 0.0
    ema_err_y = 0.0
    settle_count = 0

    stop = threading.Event()
    use_rt_capture = not args.no_rt_capture
    frame_buf: LatestFrameBuffer | None = LatestFrameBuffer() if use_rt_capture else None
    cap_thread: threading.Thread | None = None
    watchdog: StaleFrameWatchdog | None = None
    wd_thread: threading.Thread | None = None

    def _watchdog_stale() -> None:
        try:
            laser.off()
        except Exception:
            pass

    if args.watchdog_stale_sec > 0:
        watchdog = StaleFrameWatchdog(args.watchdog_stale_sec, _watchdog_stale, stop)
        wd_thread = threading.Thread(target=watchdog.run, daemon=True, name="frame-watchdog")
        wd_thread.start()

    if use_rt_capture and frame_buf is not None:
        hb = watchdog.heartbeat if watchdog is not None else None
        cap_thread = threading.Thread(
            target=capture_loop_worker,
            args=(cap, frame_buf, stop, hb),
            daemon=True,
            name="capture",
        )
        cap_thread.start()

    try:
        while True:
            if use_rt_capture and frame_buf is not None:
                snap = frame_buf.get()
                if snap is None:
                    time.sleep(0.001)
                    if args.show:
                        if cv2.waitKey(1) & 0xFF == 27:
                            break
                    else:
                        time.sleep(delay)
                    continue
                frame_id, frame = snap
            else:
                ret, frame = cap.read()
                if not ret or frame is None:
                    break
                frame_id += 1
                if watchdog is not None:
                    watchdog.heartbeat()

            h, w = frame.shape[:2]

            if args.frame_skip > 1 and (frame_id % args.frame_skip != 0):
                if args.show:
                    cv2.imshow("full_system_run", frame)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break
                else:
                    time.sleep(delay)
                continue

            results = model.predict(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)

            dets: list[dict] = []
            det_counts: dict[int, int] = {}
            if results and results[0].boxes is not None:
                for box in results[0].boxes:
                    cls_id = int(box.cls[0].item())
                    if allowed is not None and cls_id not in allowed:
                        continue
                    score = float(box.conf[0].item())
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    area = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    dets.append(
                        {"cls": cls_id, "conf": score, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": cx, "cy": cy, "area": area}
                    )
                    det_counts[cls_id] = det_counts.get(cls_id, 0) + 1

            if args.split_weed_boxes and dets:
                dets = split_large_weed_boxes(
                    frame=frame,
                    dets=dets,
                    area_ratio_min=max(0.0, args.split_area_ratio),
                    min_comp_area_px=max(1.0, args.split_min_comp_area),
                )
                det_counts = {}
                for d in dets:
                    det_counts[d["cls"]] = det_counts.get(d["cls"], 0) + 1

            if args.debug_dets:
                names = results[0].names if results else {}
                cls_summary = ", ".join(f"{names.get(k, k)}:{v}" for k, v in sorted(det_counts.items()))
                print(
                    f"[DEBUG] frame={frame_id} dets={len(dets)} conf={args.conf:.2f} imgsz={args.imgsz}"
                    + (f" classes=[{cls_summary}]" if cls_summary else "")
                )

            # Draw all detections
            if args.show and dets:
                names = results[0].names if results else {}
                for d in dets:
                    x1, y1, x2, y2 = d["x1"], d["y1"], d["x2"], d["y2"]
                    cls_id, score = d["cls"], d["conf"]
                    label = f"{names.get(cls_id, str(cls_id))} {score:.2f}"
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                    cv2.putText(frame, label, (int(x1), max(0, int(y1) - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)

            target = select_target(dets, w, h, aim=args.aim)
            if target is not None:
                confirm_count += 1
                last_seen_target_frame = frame_id
                x1, y1, x2, y2 = target["x1"], target["y1"], target["x2"], target["y2"]
                cx, cy = target["cx"], target["cy"]

                if args.camera_on_servo:
                    err_x = cx - (w / 2.0)
                    err_y = cy - (h / 2.0)
                    alpha = clamp(args.vs_ema_alpha, 0.0, 1.0)
                    ema_err_x = (1.0 - alpha) * ema_err_x + alpha * err_x
                    ema_err_y = (1.0 - alpha) * ema_err_y + alpha * err_y
                    dx_px = 0.0 if abs(ema_err_x) <= args.vs_deadband_px else ema_err_x
                    dy_px = 0.0 if abs(ema_err_y) <= args.vs_deadband_px else ema_err_y

                    # Camera and laser share the gimbal: move by image error incrementally.
                    d_pan = clamp(args.vs_kp_pan * (dx_px / max(1.0, w)), -args.vs_max_step, args.vs_max_step)
                    d_tilt = clamp(args.vs_kp_tilt * (dy_px / max(1.0, h)), -args.vs_max_step, args.vs_max_step)
                    current_pan = clamp(current_pan + d_pan, args.servo_min, args.servo_max)
                    current_tilt = clamp(current_tilt + d_tilt, args.servo_min, args.servo_max)
                    pan, tilt = current_pan, current_tilt

                    # Fire only when target is settled near center for a few consecutive frames.
                    centered = (abs(ema_err_x) <= args.vs_fire_radius_px) and (abs(ema_err_y) <= args.vs_fire_radius_px)
                    settle_count = settle_count + 1 if centered else 0
                elif args.simple:
                    pan, tilt = yolo_bbox_to_servo_angles_simple(
                        (x1, y1, x2, y2),
                        (w, h),
                        offset_pan=args.offset_pan,
                        offset_tilt=args.offset_tilt,
                    )
                    pan = clamp(pan, args.servo_min, args.servo_max)
                    tilt = clamp(tilt, args.servo_min, args.servo_max)
                else:
                    pan, tilt = yolo_bbox_to_servo_angles((x1, y1, x2, y2), (w, h), cfg)
                    pan = clamp(pan, args.servo_min, args.servo_max)
                    tilt = clamp(tilt, args.servo_min, args.servo_max)

                servo.set_angle(pan=pan, tilt=tilt)

                stable_to_fire = (not args.camera_on_servo) or (settle_count >= max(1, args.vs_settle_frames))
                if confirm_count >= args.confirm and stable_to_fire:
                    # Safe default: pulse shot instead of keeping laser latched ON.
                    if (args.pulse > 0) or (not args.continuous_laser):
                        pulse_sec = args.pulse if args.pulse > 0 else 0.15
                        now = time.monotonic()
                        if now - last_pulse_ts >= args.pulse_cooldown:
                            if laser.pulse_async(pulse_sec):
                                last_pulse_ts = now
                                laser_status = f"PULSE {pulse_sec:.2f}s"
                            else:
                                laser_status = "PULSE_BUSY"
                        else:
                            laser_status = f"PULSE_WAIT {max(0.0, args.pulse_cooldown - (now - last_pulse_ts)):.2f}s"
                    else:
                        if not laser_is_on:
                            laser.on()
                            laser_is_on = True
                            laser_on_since = time.monotonic()
                        laser_status = "ON"
                else:
                    if args.camera_on_servo and confirm_count >= args.confirm:
                        laser_status = f"SETTLING {settle_count}/{max(1, args.vs_settle_frames)}"
                    else:
                        laser_status = f"ARMING {confirm_count}/{args.confirm}"

                if args.show:
                    cv2.circle(frame, (int(cx), int(cy)), 5, (0, 0, 255), -1)
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
            else:
                confirm_count = 0
                settle_count = 0
                if laser_is_on:
                    lost_frames = frame_id - last_seen_target_frame
                    on_ms = (time.monotonic() - laser_on_since) * 1000.0
                    if lost_frames >= args.lost_off and on_ms >= args.min_on_ms:
                        laser.off()
                        laser_is_on = False
                        laser_status = "OFF"
                    else:
                        laser_status = f"HOLD_ON lost={lost_frames}/{args.lost_off}"
                else:
                    laser_status = "OFF"

            if args.show:
                info_lines = [
                    f"LASER: {laser_status}",
                    f"DETECTIONS: {len(dets)}",
                    f"TARGET: {'YES' if target is not None else 'NO'}",
                    f"AIM: {args.aim}",
                    f"MODE: {'CAM_ON_SERVO' if args.camera_on_servo else 'CAM_FIXED'}",
                    f"SERVO pan={current_pan:.1f} tilt={current_tilt:.1f}",
                ]
                y0 = 24
                for i, text in enumerate(info_lines):
                    y = y0 + i * 22
                    cv2.rectangle(frame, (8, y - 16), (290, y + 4), (0, 0, 0), -1)
                    cv2.putText(
                        frame,
                        text,
                        (12, y),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 255, 255) if text.startswith("LASER") else (255, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )
                cv2.imshow("full_system_run", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
            else:
                time.sleep(delay)
    finally:
        stop.set()
        if cap_thread is not None:
            cap_thread.join(timeout=2.0)
        try:
            cap.release()
        except Exception:
            pass
        cv2.destroyAllWindows()
        servo.cleanup()
        laser.cleanup()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

