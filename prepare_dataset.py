from __future__ import annotations

"""
Script chuẩn hóa dataset cây/cỏ sang dataset YOLO detection.

Hỗ trợ 2 kiểu dữ liệu đầu vào:

1) Mỗi lớp là một thư mục:

   dataset/
    ├── Black-grass/
    ├── Charlock/
    ├── ...

2) Toàn bộ ảnh nằm chung một thư mục, tên file có tiền tố số:

   dataset/
    ├── 1_001.png
    ├── 1_002.png
    ├── 2_010.png
    └── ...

   Trong đó số đầu (1..12) là id lớp của bộ Plant Seedlings,
   được map sang class_id YOLO = số - 1 (0..11).

Output:

dataset_yolo/
 ├── images/
 │   ├── train/
 │   └── val/
 └── labels/
     ├── train/
     └── val/

Giả định:
- Mỗi ảnh chứa 1 đối tượng chính, ta tạo bbox bao toàn bộ ảnh
  (x_center=0.5, y_center=0.5, width=1.0, height=1.0).
"""

import argparse
import random
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import cv2


# Mapping tên thư mục -> class_id, phải khớp với config/weed.yaml
CLASS_NAME_TO_ID: Dict[str, int] = {
    "Black-grass": 0,
    "Charlock": 1,
    "Cleavers": 2,
    "Common Chickweed": 3,
    "Common wheat": 4,
    "Fat Hen": 5,
    "Loose Silky-bent": 6,
    "Maize": 7,
    "Scentless Mayweed": 8,
    "Shepherd's Purse": 9,
    "Small-flowered Cranesbill": 10,
    "Sugar beet": 11,
}

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

# Mapping từ số tiền tố trong tên file (Plant Seedlings 1..12) -> class_id YOLO 0..11
NUM_PREFIX_TO_CLASS_ID: Dict[int, int] = {i: i - 1 for i in range(1, 13)}


def infer_class_id_from_root_filename(stem: str, accept_tag_class_id: bool = False) -> int | None:
    """
    Infer class id from root-level filename.
    Supported patterns:
    - "<num>_xxx"                (e.g., "6_300") -> map 1..12 -> 0..11
    - "<tag>_<classId>_xxx"      (e.g., "agri_0_9135") -> direct class id
    """
    parts = stem.split("_")
    if not parts:
        return None

    # Pattern 1: "<num>_xxx"
    if parts[0].isdigit():
        num = int(parts[0])
        return NUM_PREFIX_TO_CLASS_ID.get(num)

    # Pattern 2: "<tag>_<classId>_xxx" (optional, must be enabled explicitly)
    if accept_tag_class_id and len(parts) >= 2 and parts[1].isdigit():
        cls_id = int(parts[1])
        if 0 <= cls_id <= 11:
            return cls_id
    return None


def list_images(folder: Path) -> List[Path]:
    files: List[Path] = []
    for ext in IMAGE_EXTS:
        files.extend(folder.rglob(f"*{ext}"))
    return sorted(files)


def split_dataset(
    files: List[Path],
    train_ratio: float = 0.8,
) -> Tuple[List[Path], List[Path]]:
    """Chia files thành train/val (không tạo test)."""
    random.shuffle(files)
    n = len(files)
    n_train = int(n * train_ratio)
    train_files = files[:n_train]
    val_files = files[n_train:]
    return train_files, val_files


def generate_label_for_full_image(class_id: int, image_path: Path) -> str:
    """
    Tạo nhãn YOLO cho bbox bao toàn bộ ảnh.
    YOLO format: class_id x_center y_center width height (đều normalize).
    Ở đây: x_center=y_center=0.5, width=height=1.0
    """
    # Đọc để chắc chắn ảnh hợp lệ (không dùng kích thước trong công thức này)
    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"Cannot read image: {image_path}")
    return f"{class_id} 0.5 0.5 1.0 1.0\n"


def prepare_dataset(
    source_root: Path,
    target_root: Path,
    train_ratio: float = 0.8,
    accept_tag_class_id: bool = False,
    single_class_weed: bool = False,
) -> None:
    if not source_root.exists():
        raise FileNotFoundError(f"Source dataset not found: {source_root}")

    # Tạo thư mục đích
    for split in ["train", "val"]:
        (target_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (target_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    # Single-class mode:
    # - Mọi ảnh đều được gán class_id = 0 (weed)
    if single_class_weed:
        all_images = list_images(source_root)
        if not all_images:
            raise RuntimeError(f"No images found under: {source_root}")

        train_files, val_files = split_dataset(all_images, train_ratio=train_ratio)
        print(
            f"[INFO] single-class weed: total={len(all_images)} "
            f"train={len(train_files)} val={len(val_files)}"
        )

        def copy_and_label_single(split_name: str, fs: List[Path]) -> None:
            img_out_dir = target_root / "images" / split_name
            label_out_dir = target_root / "labels" / split_name
            for img_path in fs:
                src_tag = img_path.parent.name.replace(" ", "_")
                new_name = f"0_{src_tag}_{img_path.stem}{img_path.suffix}"
                dst_img = img_out_dir / new_name
                shutil.copy2(img_path, dst_img)

                label_text = generate_label_for_full_image(0, dst_img)
                dst_label = label_out_dir / f"{dst_img.stem}.txt"
                dst_label.write_text(label_text, encoding="utf-8")

        copy_and_label_single("train", train_files)
        copy_and_label_single("val", val_files)
        print(f"[DONE] Prepared YOLO dataset at: {target_root.resolve()}")
        return

    # Hybrid multi-class mode:
    # - Ảnh trong thư mục lớp: dataset/<ClassName>/*
    # - Ảnh nằm ở root: dataset/<num>_xxx.png (num 1..12)
    class_to_files: Dict[int, List[Path]] = {}

    # Nguồn 1: class folders
    for class_name, class_id in CLASS_NAME_TO_ID.items():
        class_dir = source_root / class_name
        if not class_dir.exists():
            continue
        images = list_images(class_dir)
        if images:
            class_to_files.setdefault(class_id, []).extend(images)

    # Nguồn 2: root-level flat images (không đệ quy)
    root_images = [p for p in source_root.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    for img_path in root_images:
        class_id = infer_class_id_from_root_filename(
            img_path.stem, accept_tag_class_id=accept_tag_class_id
        )
        if class_id is None:
            print(f"[WARN] Skip root image with unknown naming pattern: {img_path.name}")
            continue
        class_to_files.setdefault(class_id, []).append(img_path)

    if not class_to_files:
        raise RuntimeError(
            f"No valid images found in dataset root/folders: {source_root}. "
            "Expected class folders, or root files named '<num>_xxx.png'. "
            "If you intentionally use '<tag>_<classId>_xxx', pass --accept-tag-class-id."
        )

    # Copy + label cho từng class sau khi merge 2 nguồn
    for class_id, files in sorted(class_to_files.items(), key=lambda x: x[0]):
        train_files, val_files = split_dataset(files, train_ratio=train_ratio)
        print(
            f"[INFO] class_id={class_id}: total={len(files)} "
            f"train={len(train_files)} val={len(val_files)}"
        )

        def copy_and_label(split_name: str, fs: List[Path]) -> None:
            img_out_dir = target_root / "images" / split_name
            label_out_dir = target_root / "labels" / split_name
            for img_path in fs:
                # Tên output nhất quán để tránh đụng tên giữa nhiều nguồn
                src_tag = img_path.parent.name.replace(" ", "_")
                new_name = f"{class_id}_{src_tag}_{img_path.stem}{img_path.suffix}"
                dst_img = img_out_dir / new_name
                shutil.copy2(img_path, dst_img)

                label_text = generate_label_for_full_image(class_id, dst_img)
                dst_label = label_out_dir / f"{dst_img.stem}.txt"
                dst_label.write_text(label_text, encoding="utf-8")

        copy_and_label("train", train_files)
        copy_and_label("val", val_files)

    print(f"[DONE] Prepared YOLO dataset at: {target_root.resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Chuẩn hóa dataset cây/cỏ sang YOLO detection dataset (hỗ trợ folder theo lớp hoặc flat)."
    )
    parser.add_argument(
        "--source",
        type=str,
        required=True,
        help="Thư mục gốc raw dataset (chứa các folder như 'Black-grass', 'Charlock', ...).",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="dataset_yolo",
        help="Thư mục output YOLO dataset (mặc định: dataset_yolo).",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Tỷ lệ train (còn lại là val).")
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed cho việc chia train/val/test."
    )
    parser.add_argument(
        "--accept-tag-class-id",
        action="store_true",
        help="Cho phép map ảnh root theo pattern '<tag>_<classId>_xxx' (vd agri_0_123). Mặc định: tắt.",
    )
    parser.add_argument(
        "--single-class-weed",
        action="store_true",
        help="Bỏ phân loại lớp, gán toàn bộ ảnh thành 1 lớp weed (class_id=0).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    random.seed(args.seed)

    src = Path(args.source)
    dst = Path(args.target)
    prepare_dataset(
        source_root=src,
        target_root=dst,
        train_ratio=args.train_ratio,
        accept_tag_class_id=args.accept_tag_class_id,
        single_class_weed=args.single_class_weed,
    )

