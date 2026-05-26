import argparse
import csv
from dataclasses import dataclass
from pathlib import Path

from ultralytics import YOLO


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class EvalStats:
    total: int = 0
    detected: int = 0
    full_frame: int = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate weed detector on real-world positive/negative image sets."
    )
    p.add_argument("--model", default="models/best.pt", help="Path to model file")
    p.add_argument("--pos-dir", required=True, help="Directory containing images with weeds")
    p.add_argument("--neg-dir", required=True, help="Directory containing images without weeds")
    p.add_argument("--conf", type=float, default=0.1, help="Inference confidence threshold")
    p.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    p.add_argument(
        "--full-frame-thresh",
        type=float,
        default=0.9,
        help="Treat detection as full-frame when both w/h normalized >= this threshold",
    )
    p.add_argument(
        "--pass-min-recall",
        type=float,
        default=0.9,
        help="Minimum required recall on positive set",
    )
    p.add_argument(
        "--pass-max-fpr",
        type=float,
        default=0.1,
        help="Maximum allowed false-positive rate on negative set",
    )
    p.add_argument(
        "--pass-max-fullframe-rate",
        type=float,
        default=0.05,
        help="Maximum allowed full-frame box rate across all evaluated images",
    )
    p.add_argument(
        "--report-csv",
        default="runs/eval/realworld_eval.csv",
        help="Path to output CSV report",
    )
    return p.parse_args()


def list_images(directory: Path) -> list[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory.resolve()}")
    return sorted([p for p in directory.rglob("*") if p.suffix.lower() in IMAGE_EXTS])


def infer_image(
    model: YOLO,
    image_path: Path,
    conf: float,
    imgsz: int,
    full_frame_thresh: float,
) -> tuple[bool, bool, int, float]:
    results = model.predict(source=str(image_path), conf=conf, imgsz=imgsz, verbose=False)
    if not results:
        return False, False, 0, 0.0

    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return False, False, 0, 0.0

    det_count = len(boxes)
    max_conf = 0.0
    has_full_frame = False

    for box in boxes:
        score = float(box.conf[0].item())
        max_conf = max(max_conf, score)
        xywhn = box.xywhn[0].tolist()
        w_norm = float(xywhn[2])
        h_norm = float(xywhn[3])
        if w_norm >= full_frame_thresh and h_norm >= full_frame_thresh:
            has_full_frame = True

    return True, has_full_frame, det_count, max_conf


def evaluate_split(
    model: YOLO,
    image_paths: list[Path],
    split_name: str,
    conf: float,
    imgsz: int,
    full_frame_thresh: float,
    writer: csv.writer,
) -> EvalStats:
    stats = EvalStats(total=len(image_paths))
    for image_path in image_paths:
        has_det, has_full_frame, det_count, max_conf = infer_image(
            model=model,
            image_path=image_path,
            conf=conf,
            imgsz=imgsz,
            full_frame_thresh=full_frame_thresh,
        )
        if has_det:
            stats.detected += 1
        if has_full_frame:
            stats.full_frame += 1

        writer.writerow(
            [
                split_name,
                str(image_path),
                int(has_det),
                int(has_full_frame),
                det_count,
                f"{max_conf:.6f}",
            ]
        )
    return stats


def safe_ratio(n: int, d: int) -> float:
    return (n / d) if d > 0 else 0.0


def main() -> None:
    args = parse_args()

    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path.resolve()}")

    pos_dir = Path(args.pos_dir)
    neg_dir = Path(args.neg_dir)
    pos_images = list_images(pos_dir)
    neg_images = list_images(neg_dir)

    if not pos_images:
        raise RuntimeError(f"No images found in positive directory: {pos_dir.resolve()}")
    if not neg_images:
        raise RuntimeError(f"No images found in negative directory: {neg_dir.resolve()}")

    report_path = Path(args.report_csv)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(model_path))

    with report_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["split", "image_path", "has_detection", "has_full_frame", "det_count", "max_conf"])

        pos_stats = evaluate_split(
            model=model,
            image_paths=pos_images,
            split_name="positive",
            conf=args.conf,
            imgsz=args.imgsz,
            full_frame_thresh=args.full_frame_thresh,
            writer=writer,
        )
        neg_stats = evaluate_split(
            model=model,
            image_paths=neg_images,
            split_name="negative",
            conf=args.conf,
            imgsz=args.imgsz,
            full_frame_thresh=args.full_frame_thresh,
            writer=writer,
        )

    recall = safe_ratio(pos_stats.detected, pos_stats.total)
    fpr = safe_ratio(neg_stats.detected, neg_stats.total)
    full_frame_rate = safe_ratio(pos_stats.full_frame + neg_stats.full_frame, pos_stats.total + neg_stats.total)

    pass_recall = recall >= args.pass_min_recall
    pass_fpr = fpr <= args.pass_max_fpr
    pass_full_frame = full_frame_rate <= args.pass_max_fullframe_rate
    overall_pass = pass_recall and pass_fpr and pass_full_frame

    print("=== REAL-WORLD EVAL SUMMARY ===")
    print(f"model={model_path}")
    print(f"positive_images={pos_stats.total}")
    print(f"negative_images={neg_stats.total}")
    print(f"recall_pos={recall:.4f} (threshold >= {args.pass_min_recall:.4f})")
    print(f"fpr_neg={fpr:.4f} (threshold <= {args.pass_max_fpr:.4f})")
    print(
        f"full_frame_rate={full_frame_rate:.4f} "
        f"(threshold <= {args.pass_max_fullframe_rate:.4f})"
    )
    print(f"report_csv={report_path.resolve()}")
    print(f"PASS={overall_pass}")

    if not overall_pass:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
