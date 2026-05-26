"""
Camera input cho Raspberry Pi: USB webcam (OpenCV) hoặc CSI camera (picamera2).

- USB: cv2.VideoCapture(0).
- CSI (Pi Camera): dùng picamera2 nếu có (Raspberry Pi OS 64-bit), trả về frame BGR.

Lưu ý venv: `sudo apt install python3-picamera2` chỉ cho Python hệ thống.
Tạo venv với --system-site-packages hoặc `pip install picamera2` trong venv.
"""
from __future__ import annotations

import os
import time
from typing import Any

import cv2

# Thử dùng Pi Camera (CSI) trên Raspberry Pi
_PICAM2 = None
try:
    from picamera2 import Picamera2
    _PICAM2 = Picamera2
except ImportError:
    pass


def open_camera(
    camera_index: int = 0,
    use_picam2: bool | None = None,
    width: int = 640,
    height: int = 480,
    framerate: float = 15.0,
):
    """
    Mở camera: ưu tiên picamera2 nếu use_picam2=True hoặc (None và có Picamera2).

    Returns:
        cap: object có .read() -> (ret, frame), .release(), .isOpened().
        frame là numpy BGR (h, w, 3).
    """
    if use_picam2 is None:
        use_picam2 = _PICAM2 is not None

    if use_picam2 and _PICAM2 is None:
        raise RuntimeError(
            "picamera2 không import được trong Python hiện tại. "
            "Cài: sudo apt install -y python3-picamera2\n"
            "Nếu dùng venv: tạo lại bằng  python3 -m venv --system-site-packages venv\n"
            "hoặc thử: pip install picamera2"
        )

    if use_picam2 and _PICAM2 is not None:
        try:
            infos = _PICAM2.global_camera_info()
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Không đọc được danh sách camera (libcamera): {e}") from e

        if not infos:
            raise RuntimeError(
                "libcamera không thấy Pi Camera (CSI): danh sách camera rỗng.\n"
                "Kiểm tra:\n"
                "  - Cáp ribbon cắm đúng chiều, chắc chân\n"
                "  - sudo raspi-config → Interface Options → Camera → Enable → reboot\n"
                "  - Chạy: rpicam-hello --list   (hoặc libcamera-hello --list)\n"
                "  - Nếu chỉ có USB webcam: bỏ --picam2, cắm USB và chạy không --picam2"
            ) from None

        if camera_index < 0 or camera_index >= len(infos):
            raise RuntimeError(
                f"camera_num={camera_index} không hợp lệ; libcamera có {len(infos)} camera (0..{len(infos)-1})."
            )

        try:
            picam2 = _PICAM2(camera_num=camera_index)
        except IndexError as e:
            raise RuntimeError(
                "Không mở được Pi Camera. Thử reboot sau khi bật camera trong raspi-config; "
                "chạy `rpicam-hello` để test phần cứng."
            ) from e

        config = picam2.create_preview_configuration(
            main={"size": (width, height), "format": "RGB888"},
            controls={"FrameRate": framerate},
        )
        picam2.configure(config)
        picam2.start()
        return _Picam2Capture(picam2)

    if os.name == "posix":
        cap = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {camera_index}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


class _Picam2Capture:
    """Wrapper để picamera2 giống cv2.VideoCapture: .read() -> (ret, frame)."""

    def __init__(self, picam2: Any) -> None:
        self._picam2 = picam2
        self._open = True

    def isOpened(self) -> bool:
        return self._open

    def read(self):
        if not self._open:
            return False, None
        try:
            arr = self._picam2.capture_array()
            if arr is None:
                return False, None
            frame = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            return True, frame
        except Exception:
            return False, None

    def release(self) -> None:
        self._open = False
        try:
            self._picam2.stop()
        except Exception:
            pass


if __name__ == "__main__":
    cap = open_camera(0, use_picam2=False)
    try:
        for _ in range(50):
            ret, frame = cap.read()
            if not ret:
                break
            cv2.imshow("cam", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
