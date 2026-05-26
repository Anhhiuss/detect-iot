"""
Hệ thống hoàn chỉnh: Camera -> YOLO detect weed -> tọa độ -> góc servo -> servo xoay -> laser.

Chạy:
  python run_weed_laser.py                    # GPIO servo + laser
  python run_weed_laser.py --pca9685          # Servo qua PCA9685 (ServoKit)
  python run_weed_laser.py --by-area          # Chọn cỏ lớn nhất (diện tích) thay vì conf cao nhất
  python run_weed_laser.py --confirm 3        # Chỉ bắn laser sau 3 frame liên tiếp có cỏ
  python run_weed_laser.py --pulse 0.3        # Laser bắn từng phát 0.3s
  python run_weed_laser.py --offset-pan 2 --offset-tilt -1   # Calibrate laser trúng tâm
"""
from __future__ import annotations

import argparse
import time
import os
from collections import deque
from pathlib import Path

import cv2
from ultralytics import YOLO

from utils.coordinate_convert import (
    yolo_bbox_to_servo_angles,
    yolo_bbox_to_servo_angles_simple,
    CameraConfig,
)


def _parse_class_set(classes_csv: str | None, fallback: set[int]) -> set[int]:
    if not classes_csv:
        return fallback
    s: set[int] = set()
    for part in classes_csv.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"Invalid class id in --classes: '{part}'")
        s.add(int(part))
    return s if s else fallback


def _select_target(dets: list[dict], w: int, h: int, aim: str) -> dict | None:
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


def _sort_targets(dets: list[dict], w: int, h: int, aim: str) -> list[dict]:
    if not dets:
        return []
    aim = aim.lower()
    if aim == "conf":
        return sorted(dets, key=lambda d: d["conf"], reverse=True)
    if aim == "area":
        return sorted(dets, key=lambda d: d["area"], reverse=True)
    if aim == "center":
        cx0, cy0 = w / 2.0, h / 2.0
        return sorted(dets, key=lambda d: (d["cx"] - cx0) ** 2 + (d["cy"] - cy0) ** 2)
    raise ValueError("aim must be one of: conf, area, center")


def _passes_area_filter(area_norm: float, min_area_norm: float, max_area_norm: float) -> bool:
    return min_area_norm <= area_norm <= max_area_norm


def _passes_roi_filter(cy_norm: float, roi_top: float, roi_bottom: float) -> bool:
    return roi_top <= cy_norm <= roi_bottom


def _in_kill_zone(cx_norm: float, cy_norm: float, zone_x: float, zone_y: float, zone_radius: float) -> bool:
    dx = cx_norm - zone_x
    dy = cy_norm - zone_y
    return (dx * dx + dy * dy) <= (zone_radius * zone_radius)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _target_to_servo_angles(
    target: dict,
    frame_size: tuple[int, int],
    use_simple_formula: bool,
    cfg: CameraConfig | None,
    offset_pan: float,
    offset_tilt: float,
) -> tuple[float, float]:
    x1, y1, x2, y2 = target["x1"], target["y1"], target["x2"], target["y2"]
    if use_simple_formula:
        return yolo_bbox_to_servo_angles_simple(
            (x1, y1, x2, y2),
            frame_size,
            servo_range=180.0,
            offset_pan=offset_pan,
            offset_tilt=offset_tilt,
        )
    if cfg is None:
        raise ValueError("CameraConfig must not be None when using calibrated conversion")
    return yolo_bbox_to_servo_angles((x1, y1, x2, y2), frame_size, cfg)


def _backend_flag(backend: str) -> int:
    backend = backend.lower()
    if backend == "dshow":
        return cv2.CAP_DSHOW
    if backend == "msmf":
        return cv2.CAP_MSMF
    if backend == "v4l2":
        return cv2.CAP_V4L2
    return 0


def open_camera(index: int, backend: str = "auto") -> cv2.VideoCapture:
    """
    TASK: Camera I/O (mở camera theo backend, cross-platform).

    Open camera robustly across Windows/Linux.

    Windows: prefer DSHOW, fallback MSMF.
    Linux: default backend or V4L2 when requested.
    """
    backend = backend.lower()
    if backend != "auto":
        return cv2.VideoCapture(index, _backend_flag(backend))

    if os.name == "nt":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
        return cap

    return cv2.VideoCapture(index)


def _configure_capture_low_latency(cap: cv2.VideoCapture) -> None:
    """Best-effort: giảm queue frame cũ để hạ latency hiển thị."""
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass


def _apply_gui_display_env(display: str, xauthority: str) -> None:
    d = (display or "").strip()
    xa = (xauthority or "").strip()
    if d:
        os.environ["DISPLAY"] = d
        print(f"[INFO] DISPLAY={d}", flush=True)
    if xa:
        os.environ["XAUTHORITY"] = xa
        print(f"[INFO] XAUTHORITY={xa}", flush=True)
    elif d:
        cookie = Path.home() / ".Xauthority"
        if cookie.is_file():
            os.environ.setdefault("XAUTHORITY", str(cookie))
            print(f"[INFO] XAUTHORITY={cookie}", flush=True)


def list_cameras(start: int = 0, end: int = 5, backend: str = "auto") -> None:
    # TASK: Camera probing (dò index camera chạy được).
    print(f"[INFO] Probing cameras {start}..{end} (backend={backend})")
    found = []
    for i in range(start, end + 1):
        cap = open_camera(i, backend=backend)
        ok = cap.isOpened()
        if ok:
            ret, frame = cap.read()
            ok = bool(ret and frame is not None)
        cap.release()
        if ok:
            found.append(i)
            print(f"[OK] Camera index {i}")
        else:
            print(f"[NO] Camera index {i}")
    if not found:
        print("[WARN] No working camera indices found. Check camera permissions/driver, or try another backend.")


def main(
    model_path: str = "models/best.pt",
    camera_index: int = 0,
    conf: float = 0.2,
    target_class_id: int = 0,
    classes_csv: str | None = None,
    aim: str = "center",
    use_pca9685: bool = False,
    use_simple_formula: bool = False,
    show: bool = False,
    imgsz: int = 320,
    frame_skip: int = 1,
    confirm_frames: int = 1,
    multi_target: bool = False,
    max_targets_per_frame: int = 3,
    settle_sec: float = 0.12,
    cooldown_sec: float = 0.25,
    state_debug_log: bool = False,
    vote_window: int = 5,
    min_hits: int = 3,
    max_center_jump_norm: float = 0.18,
    min_area_norm: float = 0.0006,
    max_area_norm: float = 0.6,
    roi_top: float = 0.35,
    roi_bottom: float = 1.0,
    laser_pulse_sec: float = 0.0,
    offset_pan: float = 0.0,
    offset_tilt: float = 0.0,
    use_tracker: bool = False,
    camera_backend: str = "auto",
    use_picam2: bool = False,
    fixed_cam: bool = False,
    kill_zone_x: float = 0.5,
    kill_zone_y: float = 0.5,
    kill_zone_r: float = 0.1,
    turret: bool = False,
    servo_min: float = 20.0,
    servo_max: float = 160.0,
    vs_kp_pan: float = 18.0,
    vs_kp_tilt: float = 18.0,
    vs_max_step: float = 6.0,
    vs_ema_alpha: float = 0.35,
    vs_deadband_px: float = 6.0,
    vs_fire_radius_px: float = 18.0,
    vs_settle_frames: int = 2,
    display: str = "",
    xauthority: str = "",
    drop_frames: int = 0,
    pca_pan_channel: int = 0,
    pca_tilt_channel: int = 1,
    swap_labels: bool = True,
) -> None:
    # TASK: Argument validation + runtime wiring (model/camera/servo/laser/state-machine).
    if not (0.0 <= roi_top < roi_bottom <= 1.0):
        raise ValueError("--roi-top/--roi-bottom must satisfy 0 <= top < bottom <= 1")
    if not (0.0 <= min_area_norm < max_area_norm <= 1.0):
        raise ValueError("--min-area/--max-area must satisfy 0 <= min < max <= 1")
    if max_center_jump_norm <= 0.0:
        raise ValueError("--max-center-jump must be > 0")
    if vote_window <= 0:
        raise ValueError("--vote-window must be > 0")
    if not (1 <= min_hits <= vote_window):
        raise ValueError("--min-hits must satisfy 1 <= min_hits <= vote_window")
    if max_targets_per_frame <= 0:
        raise ValueError("--max-targets must be > 0")
    if settle_sec < 0.0:
        raise ValueError("--settle must be >= 0")
    if cooldown_sec < 0.0:
        raise ValueError("--cooldown must be >= 0")
    if not (0.0 <= kill_zone_x <= 1.0 and 0.0 <= kill_zone_y <= 1.0):
        raise ValueError("--kill-zone-x/--kill-zone-y must be in [0, 1]")
    if not (0.01 <= kill_zone_r <= 0.5):
        raise ValueError("--kill-zone-r must be in [0.01, 0.5]")
    if not (0.0 <= vs_ema_alpha <= 1.0):
        raise ValueError("--vs-ema-alpha must be in [0, 1]")
    if vs_max_step <= 0:
        raise ValueError("--vs-max-step must be > 0")
    if vs_settle_frames < 0:
        raise ValueError("--vs-settle-frames must be >= 0")
    if not (0.0 <= servo_min < servo_max <= 180.0):
        raise ValueError("--servo-min/--servo-max must satisfy 0 <= min < max <= 180")
    if drop_frames < 0:
        raise ValueError("--drop-frames must be >= 0")
    if not (0 <= pca_pan_channel <= 15 and 0 <= pca_tilt_channel <= 15):
        raise ValueError("--pca-pan-channel/--pca-tilt-channel must be in [0, 15]")

    if show:
        _apply_gui_display_env(display, xauthority)

    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path}")
    # TASK: YOLO model load (Ultralytics).
    model = YOLO(str(path))

    # TASK: Camera init (PiCamera2 hoặc OpenCV VideoCapture).
    if use_picam2:
        from utils.camera_pi import open_camera as open_pi_camera
        cap = open_pi_camera(
            camera_index=camera_index,
            use_picam2=True,
            width=640,
            height=480,
            framerate=15.0,
        )
    else:
        cap = open_camera(camera_index, backend=camera_backend)
    if not cap.isOpened():
        raise RuntimeError(
            f"Cannot open camera {camera_index}. "
            f"Try `python run_weed_laser.py --list-cameras` to find a working index, "
            f"or set `--backend dshow` / `--backend msmf` on Windows."
        )
    _configure_capture_low_latency(cap)

    # TASK: Servo init (PCA9685 hoặc GPIO PWM), hoặc bỏ qua nếu fixed_cam.
    servo = None
    if not fixed_cam:
        if use_pca9685:
            from hardware.servo_pca9685 import ServoControllerPCA9685, ServoKitConfig
            servo = ServoControllerPCA9685(
                cfg=ServoKitConfig(
                    pan_channel=pca_pan_channel,
                    tilt_channel=pca_tilt_channel,
                )
            )
        else:
            from hardware.servo_control import ServoController
            servo = ServoController()

    # TASK: Laser init (GPIO) + safety default (OFF mỗi frame).
    from hardware.laser_control import LaserController
    laser = LaserController()

    cfg = None if use_simple_formula else CameraConfig(
        offset_pan=offset_pan,
        offset_tilt=offset_tilt,
    )
    delay = 1.0 / 10.0
    frame_id = 0
    confirm_count = 0
    prev_center: tuple[float, float] | None = None
    hit_window: deque[int] = deque(maxlen=vote_window)
    last_fire_ts = 0.0
    sm_state = "SCAN"
    sm_queue: deque[dict] = deque()
    sm_target: dict | None = None
    sm_settle_until = 0.0
    sm_cooldown_until = 0.0
    sm_scan_started_at = time.monotonic()
    sm_target_started_at = 0.0
    # TASK: Turret control state (camera cố định, servo chase theo sai số pixel).
    # Turret (camera fixed, laser on servo): incremental visual-servo state
    ema_err_x = 0.0
    ema_err_y = 0.0
    settle_count = 0
    current_pan = _clamp(90.0 + offset_pan, servo_min, servo_max)
    current_tilt = _clamp(90.0 + offset_tilt, servo_min, servo_max)
    if turret and servo is not None:
        servo.set_angle(pan=current_pan, tilt=current_tilt)

    try:
        while True:
            if drop_frames > 0:
                for _ in range(drop_frames):
                    if not cap.grab():
                        break
            ret, frame = cap.read()
            if not ret:
                break
            frame_id += 1
            h, w = frame.shape[:2]    

            # Frame skip: chỉ chạy YOLO mỗi frame_skip frame
            if frame_id % frame_skip != 0:
                if show:
                    cv2.imshow("Weed Detection", frame)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break
                else:
                    time.sleep(delay)
                continue

            # TASK: YOLO inference (predict/track).
            if use_tracker:
                results = model.track(
                    frame, conf=conf, verbose=False, imgsz=imgsz,
                    tracker="botsort.yaml", persist=True,
                )
            else:
                results = model.predict(frame, conf=conf, verbose=False, imgsz=imgsz)

            # TASK: Laser safety interlock - reset OFF mỗi frame (laser chỉ bật ở nhánh FIRE).
            laser.off()

            allowed = _parse_class_set(classes_csv, fallback={target_class_id})
            dets: list[dict] = []
            if results and results[0].boxes is not None:
                boxes = results[0].boxes
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    if cls_id not in allowed:
                        continue
                    score = float(box.conf[0].item())
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    area = max(0.0, (x2 - x1)) * max(0.0, (y2 - y1))
                    area_norm = area / float(max(1, w * h))
                    cx = (x1 + x2) / 2.0
                    cy = (y1 + y2) / 2.0
                    cx_norm = cx / float(max(1, w))
                    cy_norm = cy / float(max(1, h))

                    # TASK: Detection filtering (area + ROI) để giảm noise/false positive.
                    if not _passes_area_filter(area_norm, min_area_norm=min_area_norm, max_area_norm=max_area_norm):
                        continue
                    if not _passes_roi_filter(cy_norm, roi_top=roi_top, roi_bottom=roi_bottom):
                        continue

                    dets.append(
                        {
                            "box": box,
                            "cls": cls_id,
                            "conf": score,
                            "x1": x1,
                            "y1": y1,
                            "x2": x2,
                            "y2": y2,
                            "cx": cx,
                            "cy": cy,
                            "cx_norm": cx_norm,
                            "cy_norm": cy_norm,
                            "area": area,
                            "area_norm": area_norm,
                        }
                    )

            if show and dets:
                names = results[0].names if results else {}
                for d in dets:
                    x1, y1, x2, y2 = d["x1"], d["y1"], d["x2"], d["y2"]
                    cls_id = d["cls"]
                    score = d["conf"]
                    label = f"{names.get(cls_id, str(cls_id))} {score:.2f}"
                    cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 2)
                    cv2.putText(
                        frame,
                        label,
                        (int(x1), max(0, int(y1) - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        1,
                        cv2.LINE_AA,
                    )

            # TASK: Fixed camera mode - không điều khiển servo, chỉ FIRE khi target vào kill-zone.
            if fixed_cam:
                now_ts = time.monotonic()
                best = _select_target(dets, w, h, aim=aim)
                zone_target = None
                if best is not None and _in_kill_zone(
                    best["cx_norm"],
                    best["cy_norm"],
                    kill_zone_x,
                    kill_zone_y,
                    kill_zone_r,
                ):
                    zone_target = best
                    hit_window.append(1)
                    confirm_count += 1
                else:
                    hit_window.append(0)
                    confirm_count = 0

                hit_count = sum(hit_window)
                vote_ready = len(hit_window) >= min_hits and hit_count >= min_hits
                can_fire = (
                    zone_target is not None
                    and confirm_count >= confirm_frames
                    and vote_ready
                    and (now_ts - last_fire_ts) >= cooldown_sec
                )
                if can_fire:
                    if laser_pulse_sec > 0:
                        laser.pulse(laser_pulse_sec)
                    else:
                        laser.on()
                        time.sleep(0.05)
                        laser.off()
                    last_fire_ts = time.monotonic()
                    if state_debug_log:
                        print(
                            f"[FIXED] FIRE conf={zone_target['conf']:.2f} "
                            f"confirm={confirm_count} vote={hit_count}/{len(hit_window)}"
                        )

                if show:
                    zx = int(kill_zone_x * w)
                    zy = int(kill_zone_y * h)
                    zr = int(kill_zone_r * min(w, h))
                    cv2.circle(frame, (zx, zy), zr, (255, 255, 0), 2)
                    cv2.putText(
                        frame,
                        f"kill-zone r={kill_zone_r:.2f}",
                        (max(0, zx - 80), max(20, zy - zr - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (255, 255, 0),
                        1,
                        cv2.LINE_AA,
                    )
                    if zone_target is not None:
                        x1, y1, x2, y2 = zone_target["x1"], zone_target["y1"], zone_target["x2"], zone_target["y2"]
                        cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 255), 2)
                        cv2.putText(
                            frame,
                            f"fixed conf={zone_target['conf']:.2f} c={confirm_count} v={hit_count}/{len(hit_window)}",
                            (int(x1), max(0, int(y1) - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (0, 255, 255),
                            1,
                            cv2.LINE_AA,
                        )

                if show:
                    cv2.imshow("Weed Detection", frame)
                    if cv2.waitKey(1) & 0xFF == 27:
                        break
                else:
                    time.sleep(delay)
                continue

            # TASK: Multi-target state machine (SCAN/AIM/SETTLE/FIRE/COOLDOWN) + anti-flicker (vote window).
            if multi_target:
                now_ts = time.monotonic()
                if dets:
                    hit_window.append(1)
                else:
                    hit_window.append(0)

                hit_count = sum(hit_window)
                vote_ready = len(hit_window) >= min_hits and hit_count >= min_hits

                if sm_state == "SCAN":
                    if vote_ready and dets:
                        target_list = _sort_targets(dets, w, h, aim=aim)[:max_targets_per_frame]
                        sm_queue = deque(target_list)
                        sm_target = None
                        if state_debug_log:
                            print(f"[SM] t={now_ts:.3f} SCAN->AIM targets={len(sm_queue)} vote={hit_count}/{len(hit_window)}")
                        sm_state = "AIM"

                if sm_state == "AIM":
                    if sm_target is None:
                        if sm_queue:
                            sm_target = sm_queue.popleft()
                            sm_target_started_at = now_ts
                            if state_debug_log:
                                print(f"[SM] t={now_ts:.3f} AIM pick conf={sm_target['conf']:.2f} remaining={len(sm_queue)}")
                        else:
                            sm_scan_started_at = now_ts
                            if state_debug_log:
                                print(f"[SM] t={now_ts:.3f} AIM->SCAN queue_empty")
                            sm_state = "SCAN"
                    if sm_target is not None:
                        pan, tilt = _target_to_servo_angles(
                            target=sm_target,
                            frame_size=(w, h),
                            use_simple_formula=use_simple_formula,
                            cfg=cfg,
                            offset_pan=offset_pan,
                            offset_tilt=offset_tilt,
                        )
                        if servo is not None:
                            servo.set_angle(pan=pan, tilt=tilt)
                        sm_settle_until = now_ts + settle_sec
                        if state_debug_log:
                            print(f"[SM] t={now_ts:.3f} AIM->SETTLE pan={pan:.1f} tilt={tilt:.1f}")
                        sm_state = "SETTLE"

                if sm_state == "SETTLE":
                    if now_ts >= sm_settle_until:
                        if state_debug_log:
                            print(f"[SM] t={now_ts:.3f} SETTLE->FIRE")
                        sm_state = "FIRE"

                if sm_state == "FIRE":
                    if sm_target is None:
                        sm_scan_started_at = now_ts
                        if state_debug_log:
                            print(f"[SM] t={now_ts:.3f} FIRE->SCAN no_target")
                        sm_state = "SCAN"
                    elif now_ts >= sm_cooldown_until and now_ts - last_fire_ts >= cooldown_sec:
                        if laser_pulse_sec > 0:
                            laser.pulse(laser_pulse_sec)
                        else:
                            laser.on()
                            time.sleep(0.05)
                            laser.off()
                        last_fire_ts = time.monotonic()
                        scan_to_fire_ms = int((last_fire_ts - sm_scan_started_at) * 1000)
                        target_to_fire_ms = int((last_fire_ts - sm_target_started_at) * 1000)
                        if state_debug_log:
                            print(
                                f"[SM] t={last_fire_ts:.3f} FIRE shot conf={sm_target['conf']:.2f} "
                                f"latency_scan_ms={scan_to_fire_ms} latency_target_ms={target_to_fire_ms}"
                            )
                        sm_cooldown_until = last_fire_ts + cooldown_sec
                        if state_debug_log:
                            print(f"[SM] t={last_fire_ts:.3f} FIRE->COOLDOWN until={sm_cooldown_until:.3f}")
                        sm_state = "COOLDOWN"

                if sm_state == "COOLDOWN":
                    if now_ts >= sm_cooldown_until:
                        if sm_queue:
                            sm_target = None
                            if state_debug_log:
                                print(f"[SM] t={now_ts:.3f} COOLDOWN->AIM next_target")
                            sm_state = "AIM"
                        else:
                            sm_target = None
                            sm_scan_started_at = now_ts
                            if state_debug_log:
                                print(f"[SM] t={now_ts:.3f} COOLDOWN->SCAN done_batch")
                            sm_state = "SCAN"

                # TASK: Debug overlay for operator (optional GUI).
                if show and sm_target is not None:
                    x1, y1, x2, y2 = sm_target["x1"], sm_target["y1"], sm_target["x2"], sm_target["y2"]
                    x_center, y_center = sm_target["cx"], sm_target["cy"]
                    best_conf = sm_target["conf"]
                    cv2.circle(frame, (int(x_center), int(y_center)), 5, (0, 0, 255), -1)
                    cv2.putText(
                        frame,
                        f"weed {best_conf:.2f} state={sm_state} q={len(sm_queue)} vote={sum(hit_window)}/{len(hit_window)}",
                        (int(x1), int(y1) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 255, 0),
                        1,
                    )

                confirm_count = 0
                prev_center = None

            else:
                # TASK: Single-target loop (aim + confirm/vote + optional turret visual-servo + FIRE).
                best = _select_target(dets, w, h, aim=aim)
                if best is not None:
                    hit_window.append(1)
                    cur_center = (best["cx_norm"], best["cy_norm"])
                    if prev_center is None:
                        confirm_count = 1
                    else:
                        dx = cur_center[0] - prev_center[0]
                        dy = cur_center[1] - prev_center[1]
                        jump = (dx * dx + dy * dy) ** 0.5
                        if jump <= max_center_jump_norm:
                            confirm_count += 1
                        else:
                            # Target moved too far between frames -> restart confirmation.
                            confirm_count = 1
                    prev_center = cur_center

                    x1, y1, x2, y2 = best["x1"], best["y1"], best["x2"], best["y2"]
                    x_center, y_center = best["cx"], best["cy"]
                    best_conf = best["conf"]

                    stable_to_fire = True
                    if turret and servo is not None:
                        # Camera is fixed; move laser turret incrementally by image error.
                        # TASK: Turret visual-servo (P-control on pixel error + EMA + deadband + settle-to-fire gating).
                        err_x = x_center - (w / 2.0)
                        err_y = y_center - (h / 2.0)
                        alpha = _clamp(vs_ema_alpha, 0.0, 1.0)
                        ema_err_x = (1.0 - alpha) * ema_err_x + alpha * err_x
                        ema_err_y = (1.0 - alpha) * ema_err_y + alpha * err_y
                        dx_px = 0.0 if abs(ema_err_x) <= vs_deadband_px else ema_err_x
                        dy_px = 0.0 if abs(ema_err_y) <= vs_deadband_px else ema_err_y
                        d_pan = _clamp(vs_kp_pan * (dx_px / max(1.0, w)), -vs_max_step, vs_max_step)
                        d_tilt = _clamp(vs_kp_tilt * (dy_px / max(1.0, h)), -vs_max_step, vs_max_step)
                        current_pan = _clamp(current_pan + d_pan, servo_min, servo_max)
                        current_tilt = _clamp(current_tilt + d_tilt, servo_min, servo_max)
                        pan, tilt = current_pan, current_tilt

                        centered = (abs(ema_err_x) <= vs_fire_radius_px) and (abs(ema_err_y) <= vs_fire_radius_px)
                        settle_count = settle_count + 1 if centered else 0
                        stable_to_fire = settle_count >= max(1, vs_settle_frames)
                    else:
                        pan, tilt = _target_to_servo_angles(
                            target=best,
                            frame_size=(w, h),
                            use_simple_formula=use_simple_formula,
                            cfg=cfg,
                            offset_pan=offset_pan,
                            offset_tilt=offset_tilt,
                        )
                        pan = _clamp(pan, servo_min, servo_max)
                        tilt = _clamp(tilt, servo_min, servo_max)

                    if servo is not None:
                        servo.set_angle(pan=pan, tilt=tilt)

                    # Chỉ bắn laser sau khi cỏ xuất hiện liên tiếp confirm_frames frame
                    hit_count = sum(hit_window)
                    vote_ready = len(hit_window) >= min_hits and hit_count >= min_hits
                    if confirm_count >= confirm_frames and vote_ready and stable_to_fire:
                        if laser_pulse_sec > 0:
                            laser.pulse(laser_pulse_sec)
                        else:
                            laser.on()

                    if show:
                        cv2.circle(frame, (int(x_center), int(y_center)), 5, (0, 0, 255), -1)
                        cv2.putText(
                            frame,
                            (
                                f"weed {best_conf:.2f}"
                                + (f" confirm={confirm_count}" if confirm_frames > 1 else "")
                                + f" vote={sum(hit_window)}/{len(hit_window)}"
                            ),
                            (int(x1), int(y1) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1
                        )
                else:
                    hit_window.append(0)
                    confirm_count = 0
                    prev_center = None
                    settle_count = 0

            if show:
                cv2.imshow("Weed Detection", frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
            else:
                time.sleep(delay)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if servo is not None:
            servo.cleanup()
        laser.cleanup()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="YOLO + Servo + Laser - robot diệt cỏ")
    p.add_argument("--model", default="models/best.pt")
    p.add_argument("--camera", type=int, default=0)
    p.add_argument("--conf", type=float, default=0.2, help="Confidence threshold (lower = more sensitive)")
    p.add_argument("--class-id", type=int, default=0, dest="target_class_id")
    p.add_argument("--classes", type=str, default=None, help="Detect nhiều class cùng lúc (CSV), vd: 0,1,2,3")
    p.add_argument("--aim", type=str, default="center", choices=["conf", "area", "center"], help="Servo aim target theo conf/area/center")
    p.add_argument("--pca9685", action="store_true", help="Servo qua PCA9685 (ServoKit)")
    p.add_argument("--simple", action="store_true", help="Công thức servo (x/width)*180, clamp 20–160°")
    p.add_argument("--show", action="store_true", help="Hiện cửa sổ bounding box")
    p.add_argument("--imgsz", type=int, default=320)
    # (deprecated) giữ lại tương thích, map sang --aim area
    p.add_argument("--by-area", action="store_true", help="(deprecated) tương đương --aim area")
    p.add_argument("--frame-skip", type=int, default=1, help="Chỉ chạy YOLO mỗi N frame (2 = FPS xấp xỉ x2)")
    p.add_argument("--confirm", type=int, default=1, help="Chỉ bắn laser sau N frame liên tiếp có cỏ (3 = ổn định)")
    p.add_argument("--multi-target", action="store_true", help="Bật chế độ xử lý tuần tự nhiều cỏ trong cùng frame")
    p.add_argument("--max-targets", type=int, default=3, help="Số target tối đa xử lý mỗi frame khi bật --multi-target")
    p.add_argument("--settle", type=float, default=0.12, help="Thời gian chờ servo ổn định trước khi bắn (giây)")
    p.add_argument("--cooldown", type=float, default=0.25, help="Khoảng nghỉ tối thiểu giữa 2 phát laser (giây)")
    p.add_argument("--state-debug-log", action="store_true", help="In log chuyển state + latency (SCAN->FIRE)")
    p.add_argument("--vote-window", type=int, default=5, help="Kích thước cửa sổ anti-flicker (sliding window)")
    p.add_argument("--min-hits", type=int, default=3, help="Số frame có cỏ tối thiểu trong vote-window để cho phép bắn")
    p.add_argument("--max-center-jump", type=float, default=0.18, help="Ngưỡng nhảy tâm bbox chuẩn hóa/frame để giữ confirm ổn định")
    p.add_argument("--min-area", type=float, default=0.0006, help="Lọc bbox nhỏ nhiễu theo normalized area")
    p.add_argument("--max-area", type=float, default=0.6, help="Lọc bbox quá lớn bất thường theo normalized area")
    p.add_argument("--roi-top", type=float, default=0.35, help="ROI top theo tỷ lệ chiều cao ảnh (0..1)")
    p.add_argument("--roi-bottom", type=float, default=1.0, help="ROI bottom theo tỷ lệ chiều cao ảnh (0..1)")
    p.add_argument("--pulse", type=float, default=0.0, metavar="SEC", help="Laser bắn từng phát SEC giây (vd: 0.3)")
    p.add_argument("--offset-pan", type=float, default=0.0, help="Calibration: bù góc pan (laser trúng tâm)")
    p.add_argument("--offset-tilt", type=float, default=0.0, help="Calibration: bù góc tilt")
    p.add_argument("--track", action="store_true", help="Dùng tracker (botsort) để servo ít rung")
    p.add_argument("--fixed-cam", action="store_true", help="Camera cố định, chỉ bật laser khi target vào kill-zone")
    p.add_argument("--turret", action="store_true", help="Turret mode: camera cố định, servo chase theo sai số tâm ảnh (P-control)")
    p.add_argument("--servo-min", type=float, default=20.0, help="Servo minimum angle clamp")
    p.add_argument("--servo-max", type=float, default=160.0, help="Servo maximum angle clamp")
    p.add_argument("--vs-kp-pan", type=float, default=18.0, help="Turret gain pan")
    p.add_argument("--vs-kp-tilt", type=float, default=18.0, help="Turret gain tilt")
    p.add_argument("--vs-max-step", type=float, default=6.0, help="Turret max degree step per processed frame")
    p.add_argument("--vs-ema-alpha", type=float, default=0.35, help="EMA alpha for image error smoothing")
    p.add_argument("--vs-deadband-px", type=float, default=6.0, help="Deadband in pixels before turret moves")
    p.add_argument("--vs-fire-radius-px", type=float, default=18.0, help="Only FIRE when error within this pixel radius")
    p.add_argument("--vs-settle-frames", type=int, default=2, help="Consecutive centered frames required before FIRE")
    p.add_argument("--kill-zone-x", type=float, default=0.5, help="Tâm kill-zone theo trục X (0..1)")
    p.add_argument("--kill-zone-y", type=float, default=0.5, help="Tâm kill-zone theo trục Y (0..1)")
    p.add_argument("--kill-zone-r", type=float, default=0.1, help="Bán kính kill-zone theo tỷ lệ ảnh (0.01..0.5)")
    p.add_argument("--backend", default="auto", choices=["auto", "dshow", "msmf", "v4l2"], help="Camera backend")
    p.add_argument("--picam2", action="store_true", help="Dùng Pi Camera (CSI) qua picamera2")
    p.add_argument("--display", type=str, default="", help="Khi SSH + --show: ví dụ :0")
    p.add_argument("--xauthority", type=str, default="", help="Cookie X11, ví dụ /home/pi4b/.Xauthority")
    p.add_argument("--drop-frames", type=int, default=1, help="Bỏ N frame cũ trước mỗi lần read để giảm trễ hiển thị")
    p.add_argument("--pca-pan-channel", type=int, default=0, help="PCA9685 channel cho servo pan (0..15)")
    p.add_argument("--pca-tilt-channel", type=int, default=1, help="PCA9685 channel cho servo tilt (0..15)")
    p.add_argument("--list-cameras", action="store_true", help="Probe camera indices (0..5) rồi thoát")
    args = p.parse_args()

    if args.list_cameras:
        list_cameras(0, 5, backend=args.backend)
        raise SystemExit(0)

    main(
        model_path=args.model,
        camera_index=args.camera,
        conf=args.conf,
        target_class_id=args.target_class_id,
        classes_csv=args.classes,
        aim=("area" if args.by_area else args.aim),
        use_pca9685=args.pca9685,
        use_simple_formula=args.simple,
        show=args.show,
        imgsz=args.imgsz,
        frame_skip=args.frame_skip,
        confirm_frames=args.confirm,
        multi_target=args.multi_target,
        max_targets_per_frame=args.max_targets,
        settle_sec=args.settle,
        cooldown_sec=args.cooldown,
        state_debug_log=args.state_debug_log,
        vote_window=args.vote_window,
        min_hits=args.min_hits,
        max_center_jump_norm=args.max_center_jump,
        min_area_norm=args.min_area,
        max_area_norm=args.max_area,
        roi_top=args.roi_top,
        roi_bottom=args.roi_bottom,
        laser_pulse_sec=args.pulse,
        offset_pan=args.offset_pan,
        offset_tilt=args.offset_tilt,
        use_tracker=args.track,
        fixed_cam=args.fixed_cam,
        kill_zone_x=args.kill_zone_x,
        kill_zone_y=args.kill_zone_y,
        kill_zone_r=args.kill_zone_r,
        turret=args.turret,
        servo_min=args.servo_min,
        servo_max=args.servo_max,
        vs_kp_pan=args.vs_kp_pan,
        vs_kp_tilt=args.vs_kp_tilt,
        vs_max_step=args.vs_max_step,
        vs_ema_alpha=args.vs_ema_alpha,
        vs_deadband_px=args.vs_deadband_px,
        vs_fire_radius_px=args.vs_fire_radius_px,
        vs_settle_frames=args.vs_settle_frames,
        camera_backend=args.backend,
        use_picam2=args.picam2,
        display=args.display,
        xauthority=args.xauthority,
        drop_frames=args.drop_frames,
        pca_pan_channel=args.pca_pan_channel,
        pca_tilt_channel=args.pca_tilt_channel,
    )
