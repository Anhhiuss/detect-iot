from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import cv2
from ultralytics import YOLO


def open_camera(index: int) -> cv2.VideoCapture:
    if os.name == "nt":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if cap.isOpened():
            return cap
        return cv2.VideoCapture(index, cv2.CAP_MSMF)
    return cv2.VideoCapture(index)


def parse_class_ids(classes_csv: str | None) -> set[int] | None:
    if not classes_csv:
        return None
    out: set[int] = set()
    for part in classes_csv.split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"Invalid class id: {part}")
        out.add(int(part))
    return out or None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Local-only realtime webcam test (no upload, no cloud push)."
    )
    ap.add_argument("--model", default="models/best.pt", help="Path to YOLO model")
    ap.add_argument("--camera", type=int, default=0, help="Webcam index")
    ap.add_argument("--conf", type=float, default=0.25, help="Detection confidence threshold")
    ap.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    ap.add_argument("--classes", type=str, default=None, help="CSV class ids filter, e.g. 0")
    ap.add_argument("--show-fps", action="store_true", help="Overlay FPS on preview")
    args = ap.parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path.resolve()}")

    allowed = parse_class_ids(args.classes)
    model = YOLO(str(model_path))
    cap = open_camera(args.camera)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera index {args.camera}")

    print("[INFO] Running LOCAL realtime test only (no upload/no push).")
    print("[INFO] Press ESC to exit.")

    last_ts = time.perf_counter()
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("[WARN] Failed to read frame from webcam.")
                break

            results = model.predict(frame, conf=args.conf, imgsz=args.imgsz, verbose=False)
            names = results[0].names if results else {}

            det_count = 0
            if results and results[0].boxes is not None:
                for box in results[0].boxes:
                    cls_id = int(box.cls[0].item())
                    if allowed is not None and cls_id not in allowed:
                        continue
                    det_count += 1
                    score = float(box.conf[0].item())
                    x1, y1, x2, y2 = box.xyxy[0].tolist()

                    cv2.rectangle(
                        frame,
                        (int(x1), int(y1)),
                        (int(x2), int(y2)),
                        (0, 255, 0),
                        2,
                    )
                    label = f"{names.get(cls_id, cls_id)} {score:.2f}"
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

            now = time.perf_counter()
            fps = 1.0 / max(1e-6, now - last_ts)
            last_ts = now

            hud = [f"DETS: {det_count}", "MODE: LOCAL_ONLY"]
            if args.show_fps:
                hud.append(f"FPS: {fps:.1f}")
            for i, text in enumerate(hud):
                y = 24 + i * 22
                cv2.rectangle(frame, (8, y - 16), (250, y + 4), (0, 0, 0), -1)
                cv2.putText(
                    frame,
                    text,
                    (12, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

            cv2.imshow("local_webcam_realtime", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

