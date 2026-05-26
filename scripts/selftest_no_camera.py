#!/usr/bin/env python3
"""
Self-test không cần camera cho pipeline:
  model load -> inference on synthetic frame -> bbox->servo angles.

Chạy:
  python scripts/selftest_no_camera.py
  python scripts/selftest_no_camera.py --model models/best.pt --imgsz 320
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

# Allow import from project root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.coordinate_convert import CameraConfig, yolo_bbox_to_servo_angles  # noqa: E402


def make_synthetic_frame(width: int = 640, height: int = 480) -> np.ndarray:
    """Tạo frame giả có vài shape để test inference pipeline."""
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (25, 25, 25)
    cv2.rectangle(frame, (120, 100), (280, 300), (0, 220, 0), -1)
    cv2.circle(frame, (430, 240), 70, (220, 220, 0), -1)
    cv2.putText(frame, "NO CAMERA SELFTEST", (110, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return frame


def main() -> int:
    p = argparse.ArgumentParser(description="Self-test pipeline without camera")
    p.add_argument("--model", default="models/best.pt", help="Path to YOLO model")
    p.add_argument("--imgsz", type=int, default=320, help="Inference size")
    p.add_argument("--save", default="selftest_no_camera.jpg", help="Output image path")
    args = p.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"[ERROR] Model not found: {model_path}")
        return 1

    print(f"[INFO] Loading model: {model_path}")
    model = YOLO(str(model_path))

    frame = make_synthetic_frame()
    h, w = frame.shape[:2]
    print(f"[INFO] Synthetic frame: {w}x{h}")

    results = model.predict(frame, imgsz=args.imgsz, conf=0.25, verbose=False)
    n = 0
    if results and results[0].boxes is not None:
        n = len(results[0].boxes)
    print(f"[INFO] Detections on synthetic frame: {n}")

    # Dù có detect hay không, test convert bằng 1 bbox giả tại tâm
    test_bbox = (w * 0.4, h * 0.35, w * 0.6, h * 0.65)
    pan, tilt = yolo_bbox_to_servo_angles(test_bbox, (w, h), CameraConfig())
    print(f"[INFO] Servo angle test from bbox(center): pan={pan:.2f}, tilt={tilt:.2f}")

    # Save an annotated image for confirmation
    out = results[0].plot() if results else frame
    cv2.imwrite(args.save, out)
    print(f"[OK] Saved output image: {args.save}")
    print("[OK] Self-test no-camera finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
