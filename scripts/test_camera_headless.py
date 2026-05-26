#!/usr/bin/env python3
"""
Test camera không cần màn hình (headless) — dùng trên Raspberry Pi không gắn monitor.

- Không gọi cv2.imshow (không cần X11 / desktop).
- In kích thước frame, FPS đọc, lưu 1 ảnh để kiểm tra (scp về PC xem).

Chạy trên Pi:
  cd ~/weed_detection_project
  python3 scripts/test_camera_headless.py
  python3 scripts/test_camera_headless.py --picam2
  python3 scripts/test_camera_headless.py --camera 0 --frames 60 --save /tmp/cam_test.jpg
  python3 scripts/test_camera_headless.py --model models/best.pt
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Cho phép import từ thư mục gốc project
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import cv2


def _list_dev_video() -> list[str]:
    dev = Path("/dev")
    if not dev.exists():
        return []
    return sorted(str(p) for p in dev.glob("video*") if p.is_char_device())


def open_usb_camera(index: int, width: int, height: int) -> cv2.VideoCapture:
    """Trên Linux/Pi: ưu tiên V4L2 (ổn định hơn với USB webcam)."""
    if os.name == "posix":
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            return cap
    cap = cv2.VideoCapture(index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def scan_usb_cameras(max_index: int = 5, width: int = 640, height: int = 480) -> tuple[cv2.VideoCapture | None, int]:
    """Thử index 0..max_index, trả về (cap, index) nếu đọc được 1 frame."""
    for idx in range(max_index + 1):
        cap = open_usb_camera(idx, width, height)
        if not cap.isOpened():
            continue
        ret, frame = cap.read()
        if ret and frame is not None:
            return cap, idx
        cap.release()
    return None, -1


def open_cap(args: argparse.Namespace):
    if args.picam2:
        from utils.camera_pi import open_camera
        return open_camera(
            camera_index=args.camera,
            use_picam2=True,
            width=args.width,
            height=args.height,
            framerate=args.fps,
        )
    return open_usb_camera(args.camera, args.width, args.height)


def main() -> int:
    p = argparse.ArgumentParser(description="Test camera headless (no GUI)")
    p.add_argument("--camera", type=int, default=0, help="Index camera USB")
    p.add_argument("--picam2", action="store_true", help="Dùng Pi Camera (CSI) qua picamera2")
    p.add_argument("--width", type=int, default=640)
    p.add_argument("--height", type=int, default=480)
    p.add_argument("--fps", type=float, default=15.0, help="Chỉ áp dụng với --picam2")
    p.add_argument("--frames", type=int, default=30, help="Số frame đọc để đo FPS")
    p.add_argument("--save", type=str, default="", help="Lưu ảnh (mặc định: cam_headless_last.jpg trong cwd)")
    p.add_argument("--model", type=str, default="", help="Nếu có: chạy YOLO 1 lần trên frame cuối, in số box")
    p.add_argument("--no-auto-scan", action="store_true", help="Không tự quét index khi mở camera thất bại")
    args = p.parse_args()

    save_path = args.save or str(Path.cwd() / "cam_headless_last.jpg")

    print("[INFO] Opening camera (headless, no imshow)...")
    cap = open_cap(args)
    used_index = args.camera

    if not cap.isOpened() and not args.picam2 and not args.no_auto_scan:
        vdev = _list_dev_video()
        print(f"[INFO] /dev/video*: {vdev if vdev else '(không có — USB webcam có thể chưa cắm / driver chưa load)'}")
        print("[INFO] Tự quét index 0..5 (V4L2)...")
        cap, used_index = scan_usb_cameras(5, args.width, args.height)
        if cap is not None and used_index >= 0:
            print(f"[OK] Mở được camera tại index {used_index} (dùng lại: --camera {used_index})")

    if cap is None or not cap.isOpened():
        print("[ERROR] Không mở được camera.")
        print("  - USB webcam: cắm USB, thử:  sudo usermod -aG video $USER  (logout/login)")
        print("  - Thử tay:      python3 scripts/test_camera_headless.py --camera 1")
        print("  - Pi Camera (dây ribbon CSI):  sudo apt install -y python3-picamera2")
        print("                  python3 scripts/test_camera_headless.py --picam2")
        print("  - Bật camera:   sudo raspi-config → Interface Options → Camera (hoặc Legacy)")
        return 1

    t0 = time.perf_counter()
    last_frame = None
    ok_count = 0
    for i in range(args.frames):
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"[WARN] Frame {i}: read failed")
            continue
        ok_count += 1
        last_frame = frame

    cap.release()
    elapsed = time.perf_counter() - t0

    if last_frame is None:
        print("[ERROR] No valid frame.")
        return 1

    h, w = last_frame.shape[:2]
    print(f"[OK] Frames OK: {ok_count}/{args.frames}, size {w}x{h}, time {elapsed:.2f}s")
    if ok_count and elapsed > 0:
        print(f"[OK] Read FPS (approx): {ok_count / elapsed:.1f}")

    cv2.imwrite(save_path, last_frame)
    print(f"[OK] Saved last frame -> {save_path}")
    print("      (scp file này về PC để xem: scp pi4b@IP:path . )")

    if args.model:
        mp = Path(args.model)
        if not mp.exists():
            print(f"[WARN] Model not found: {mp}, skip YOLO.")
        else:
            from ultralytics import YOLO
            model = YOLO(str(mp))
            results = model.predict(last_frame, imgsz=320, verbose=False)
            n = 0
            if results and results[0].boxes is not None:
                n = len(results[0].boxes)
            print(f"[OK] YOLO detections on last frame: {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
