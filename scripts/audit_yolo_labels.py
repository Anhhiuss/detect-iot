import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AuditStats:
    total_files: int = 0
    total_boxes: int = 0
    empty_files: int = 0
    invalid_lines: int = 0
    invalid_class_ids: int = 0
    out_of_range_values: int = 0
    near_full_frame_boxes: int = 0
    tiny_boxes: int = 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Audit YOLO labels for weed-only training quality."
    )
    p.add_argument(
        "--labels-dir",
        default="dataset_yolo/labels",
        help="Root labels dir containing train/val/test folders.",
    )
    p.add_argument(
        "--allowed-class",
        type=int,
        default=0,
        help="Allowed class id for weed-only setup.",
    )
    p.add_argument(
        "--full-frame-thresh",
        type=float,
        default=0.95,
        help="Flag boxes with w>=thresh and h>=thresh as near full-frame.",
    )
    p.add_argument(
        "--tiny-area-thresh",
        type=float,
        default=0.0005,
        help="Flag boxes with normalized area < thresh as tiny.",
    )
    return p.parse_args()


def iter_label_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.txt"))


def audit_file(
    file_path: Path,
    allowed_class: int,
    full_frame_thresh: float,
    tiny_area_thresh: float,
    stats: AuditStats,
) -> None:
    lines = file_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        stats.empty_files += 1
        return

    for idx, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 5:
            stats.invalid_lines += 1
            print(f"[INVALID_FORMAT] {file_path}:{idx} -> '{line}'")
            continue

        try:
            cls_id = int(parts[0])
            x, y, w, h = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
        except ValueError:
            stats.invalid_lines += 1
            print(f"[INVALID_PARSE] {file_path}:{idx} -> '{line}'")
            continue

        stats.total_boxes += 1

        if cls_id != allowed_class:
            stats.invalid_class_ids += 1
            print(
                f"[INVALID_CLASS] {file_path}:{idx} -> class={cls_id}, expected={allowed_class}"
            )

        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
            stats.out_of_range_values += 1
            print(
                f"[OUT_OF_RANGE] {file_path}:{idx} -> x={x:.4f} y={y:.4f} w={w:.4f} h={h:.4f}"
            )
            continue

        if w >= full_frame_thresh and h >= full_frame_thresh:
            stats.near_full_frame_boxes += 1
            print(
                f"[NEAR_FULL_FRAME] {file_path}:{idx} -> w={w:.4f} h={h:.4f}"
            )

        area = w * h
        if area < tiny_area_thresh:
            stats.tiny_boxes += 1
            print(f"[TINY_BOX] {file_path}:{idx} -> area={area:.6f}")


def main() -> None:
    args = parse_args()
    labels_root = Path(args.labels_dir)
    if not labels_root.exists():
        raise FileNotFoundError(f"Labels directory not found: {labels_root.resolve()}")

    files = iter_label_files(labels_root)
    stats = AuditStats(total_files=len(files))

    for file_path in files:
        audit_file(
            file_path=file_path,
            allowed_class=args.allowed_class,
            full_frame_thresh=args.full_frame_thresh,
            tiny_area_thresh=args.tiny_area_thresh,
            stats=stats,
        )

    print("\n=== YOLO LABEL AUDIT SUMMARY ===")
    print(f"files={stats.total_files}")
    print(f"boxes={stats.total_boxes}")
    print(f"empty_files={stats.empty_files}")
    print(f"invalid_lines={stats.invalid_lines}")
    print(f"invalid_class_ids={stats.invalid_class_ids}")
    print(f"out_of_range_values={stats.out_of_range_values}")
    print(f"near_full_frame_boxes={stats.near_full_frame_boxes}")
    print(f"tiny_boxes={stats.tiny_boxes}")

    hard_fail = stats.invalid_lines + stats.invalid_class_ids + stats.out_of_range_values
    if hard_fail > 0:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
