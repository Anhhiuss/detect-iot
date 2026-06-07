from __future__ import annotations

from dataclasses import dataclass


# Giới hạn góc servo thực tế (tránh rung ở 0°/180°)
SERVO_ANGLE_MIN = 20.0
SERVO_ANGLE_MAX = 160.0


@dataclass
class CameraConfig:
    # Horizontal / vertical field of view of the camera (degrees)
    fov_h: float = 62.2  # Raspberry Pi Camera v2 approx
    fov_v: float = 48.8
    # Servo neutral angles (camera looking straight at center)
    servo_center_pan: float = 90.0
    servo_center_tilt: float = 90.0
    # Servo angle limits (giới hạn 20–160° tránh rung)
    servo_min_pan: float = SERVO_ANGLE_MIN
    servo_max_pan: float = SERVO_ANGLE_MAX
    servo_min_tilt: float = SERVO_ANGLE_MIN
    servo_max_tilt: float = SERVO_ANGLE_MAX
    # Calibration: offset sau khi đổi pixel → góc (laser bắn trúng tâm)
    offset_pan: float = 0.0
    offset_tilt: float = 0.0


def clamp(value: float, vmin: float, vmax: float) -> float:
    return max(vmin, min(vmax, value))


def yolo_bbox_to_pixel_center(
    xyxy: tuple[float, float, float, float],
) -> tuple[float, float]:
    """
    Convert YOLO xyxy bbox to pixel center (still in pixels, caller must know image size).
    xyxy = (x1, y1, x2, y2)
    """
    x1, y1, x2, y2 = xyxy
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return cx, cy


def pixel_to_servo_angles(
    center: tuple[float, float],
    img_size: tuple[int, int],
    cfg: CameraConfig | None = None,
) -> tuple[float, float]:
    """
    Map pixel center in image to pan/tilt servo angles.

    - center: (cx, cy) in pixel coordinates.
    - img_size: (width, height) of the frame.
    - cfg: camera / servo configuration.
    """
    if cfg is None:
        cfg = CameraConfig()

    cx, cy = center
    w, h = img_size

    # Normalize to [-0.5, 0.5] where 0 is center
    nx = (cx / w) - 0.5
    ny = (cy / h) - 0.5

    # Convert to angles using FOV (negative nx -> pan left, positive -> right)
    angle_x = -nx * cfg.fov_h
    angle_y = ny * cfg.fov_v  # positive ny -> object lower -> tilt down

    pan = clamp(cfg.servo_center_pan + angle_x + cfg.offset_pan, cfg.servo_min_pan, cfg.servo_max_pan)
    tilt = clamp(cfg.servo_center_tilt + angle_y + cfg.offset_tilt, cfg.servo_min_tilt, cfg.servo_max_tilt)
    pan = 180 - pan  
    return pan, tilt


def yolo_bbox_to_servo_angles(
    xyxy: tuple[float, float, float, float],
    img_size: tuple[int, int],
    cfg: CameraConfig | None = None,
) -> tuple[float, float]:
    """
    Helper: take YOLO xyxy box and directly output servo angles.
    """
    center = yolo_bbox_to_pixel_center(xyxy)
    return pixel_to_servo_angles(center, img_size, cfg)


def pixel_to_servo_angles_simple(
    x_center: float,
    y_center: float,
    width: float,
    height: float,
    servo_range: float = 180.0,
    servo_min: float = SERVO_ANGLE_MIN,
    servo_max: float = SERVO_ANGLE_MAX,
    offset_pan: float = 0.0,
    offset_tilt: float = 0.0,
) -> tuple[float, float]:
    """
    Công thức đơn giản: servo = (pixel / kích_thước_ảnh) * 180, rồi clamp 20–160°.
    offset_pan/offset_tilt dùng để calibrate camera → servo (laser bắn trúng).
    """
    servo_x = (x_center / width) * servo_range + offset_pan
    servo_y = (y_center / height) * servo_range + offset_tilt
    servo_x = clamp(servo_x, servo_min, servo_max)
    servo_y = clamp(servo_y, servo_min, servo_max)
    return servo_x, servo_y


def yolo_bbox_to_servo_angles_simple(
    xyxy: tuple[float, float, float, float],
    img_size: tuple[int, int],
    servo_range: float = 180.0,
    servo_min: float = SERVO_ANGLE_MIN,
    servo_max: float = SERVO_ANGLE_MAX,
    offset_pan: float = 0.0,
    offset_tilt: float = 0.0,
) -> tuple[float, float]:
    """Lấy tâm bbox YOLO rồi đổi sang góc servo theo công thức đơn giản (có clamp + offset)."""
    cx, cy = yolo_bbox_to_pixel_center(xyxy)
    w, h = img_size
    return pixel_to_servo_angles_simple(
        cx, cy, w, h, servo_range, servo_min, servo_max, offset_pan, offset_tilt
    )

