import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO


def load_model(model_path: str | Path = "models/best.pt") -> YOLO:
    path = Path(model_path)
    if not path.exists():
        raise FileNotFoundError(f"Model not found: {path}")
    return YOLO(str(path))


def detect_on_image(
    image_path: str | Path,
    model_path: str | Path = "models/best.pt",
    conf: float = 0.5,
    save: bool = True,
) -> Path:
    model = load_model(model_path)
    img_path = Path(image_path)
    if not img_path.exists():
        raise FileNotFoundError(f"Image not found: {img_path}")

    results = model.predict(source=str(img_path), conf=conf, save=save, project="runs/detect", name="image")
    # ultralytics returns list of Results
    if not results:
        raise RuntimeError("No results returned from model.")

    out_dir = Path(results[0].save_dir)
    print(f"[INFO] Saved detection result to: {out_dir}")
    # Usually file has same name in that dir
    out_files = list(out_dir.glob(img_path.stem + "*"))
    return out_files[0] if out_files else out_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run YOLO weed detection on a single image.")
    parser.add_argument("--image", type=str, required=True, help="Path to input image")
    parser.add_argument("--model", type=str, default="models/best.pt", help="Path to trained model")
    parser.add_argument("--conf", type=float, default=0.5, help="Confidence threshold")
    parser.add_argument("--nosave", action="store_true", help="Do not save output image")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result_path = detect_on_image(
        image_path=args.image,
        model_path=args.model,
        conf=args.conf,
        save=not args.nosave,
    )
    print(f"[DONE] Result: {result_path}")

