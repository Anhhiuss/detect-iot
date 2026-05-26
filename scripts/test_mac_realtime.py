#!/usr/bin/env python3
"""
Test realtime YOLO trên macOS (webcam) để verify model nhanh.

Yêu cầu:
  pip install ultralytics opencv-python numpy

Chạy:
  python3 scripts/test_mac_realtime.py --model models/best.pt --camera 0
  python3 scripts/test_mac_realtime.py --model models/best.pt --camera 0 --imgsz 320 --conf 0.5

Thoát: nhấn ESC.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO


def open_mac_camera(index: int) -> cv2.VideoCapture:
    """
    macOS: ưu tiên AVFoundation backend cho webcam ổn định hơn.
    """
    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if cap.isOpened():
        return cap
    return cv2.VideoCapture(index)


def main() -> int:
    p = argparse.ArgumentParser(description="macOS realtime test: Webcam -> YOLO -> bbox overlay")
    p.add_argument("--model", default="models/best.pt", help="Path to YOLO model (.pt/.onnx)")
    p.add_argument("--camera", type=int, default=0, help="Webcam index (0/1/2...)")
    p.add_argument("--imgsz", type=int, default=640, help="Inference size (320/416/640)")
    p.add_argument("--conf", type=float, default=0.5, help="Confidence threshold")
    p.add_argument("--width", type=int, default=640, help="Capture width")
    p.add_argument("--height", type=int, default=480, help="Capture height")
    args = p.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path.resolve()}")

    model = YOLO(str(model_path))

    cap = open_mac_camera(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {args.camera}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            results = model.predict(frame, imgsz=args.imgsz, conf=args.conf, verbose=False)
            annotated = results[0].plot() if results else frame

            cv2.imshow("YOLO macOS realtime test (ESC to quit)", annotated)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

