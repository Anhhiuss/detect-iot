import argparse
from pathlib import Path

from ultralytics import YOLO


def train(
    data_cfg: str = "config/weed.yaml",
    model_name: str = "yolov8n.pt",
    epochs: int = 120,
    imgsz: int = 640,
    batch: int = 12,
    device: str | int | None = None,
    workers: int = 8,
    patience: int = 25,
    freeze: int = 0,
    close_mosaic: int = 15,
    amp: bool = True,
    single_cls: bool = True,
    project: str = "runs/train",
    name: str = "weed_retrain_realtime",
) -> Path:
    """
    Train YOLO model on weed dataset.

    The training process follows the standard YOLO formulation:
    - Total loss: L = L_box + L_obj + L_cls
    - Weights are updated by gradient descent: w_{t+1} = w_t - η ∇L

    Parameters are chosen to be reasonable for both PC and Raspberry Pi
    (if you use Pi only for fine‑tuning with small batch size).
    """
    data_cfg_path = Path(data_cfg)
    if not data_cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {data_cfg_path}")

    models_dir = Path("models")
    models_dir.mkdir(parents=True, exist_ok=True)

    # Load base model (from models/yolov8n.pt if exists, else from ultralytics hub)
    local_model_path = models_dir / model_name
    model = YOLO(str(local_model_path) if local_model_path.exists() else model_name)

    # NOTE:
    # Realtime detector quality depends mostly on true object-level labels.
    # If your labels are full-image boxes (x=0.5 y=0.5 w=1 h=1), model will not learn
    # to localize multiple weeds in one frame reliably.
    results = model.train(
        data=str(data_cfg_path),
        epochs=epochs,
        imgsz=imgsz,
        batch=batch,
        device=device,
        workers=workers,
        patience=patience,
        freeze=freeze,
        close_mosaic=close_mosaic,
        amp=amp,
        optimizer="auto",
        cos_lr=True,
        seed=42,
        deterministic=True,
        cache="ram",
        single_cls=single_cls,
        project=project,
        name=name,
        val=True,
    )

    # Best weights are usually at runs/train/<name>/weights/best.pt
    best_weights = Path(results.save_dir) / "weights" / "best.pt"
    if best_weights.exists():
        target = models_dir / "best.pt"
        target.write_bytes(best_weights.read_bytes())
        print(f"[INFO] Copied best weights to {target}")

        # Export ONNX for faster CPU inference on Raspberry Pi/Windows.
        try:
            export_model = YOLO(str(target))
            export_model.export(format="onnx", imgsz=imgsz, dynamic=True, simplify=True, opset=12)
            print("[INFO] Exported ONNX model for realtime inference.")
        except Exception as exc:
            print(f"[WARN] ONNX export failed: {exc}")

        return target

    print("[WARN] Best weights not found; check runs/train directory.")
    return best_weights


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train YOLO model for weed detection")
    parser.add_argument("--data", type=str, default="config/weed.yaml", help="Path to dataset yaml")
    parser.add_argument("--model", type=str, default="yolov8n.pt", help="Base model name or path")
    parser.add_argument("--epochs", type=int, default=120, help="Training epochs")
    parser.add_argument("--imgsz", type=int, default=640, help="Image size")
    parser.add_argument("--batch", type=int, default=12, help="Batch size")
    parser.add_argument("--device", type=str, default=None, help="Device id, e.g. '0' or 'cpu'")
    parser.add_argument("--workers", type=int, default=8, help="Dataloader workers")
    parser.add_argument("--patience", type=int, default=25, help="Early stopping patience")
    parser.add_argument("--freeze", type=int, default=0, help="Freeze first N layers")
    parser.add_argument("--close-mosaic", type=int, default=15, help="Disable mosaic in last N epochs")
    parser.add_argument("--no-amp", action="store_true", help="Disable mixed precision")
    parser.add_argument(
        "--multi-class",
        action="store_true",
        help="Disable weed-only mode (single_cls) and keep original multi-class behavior",
    )
    parser.add_argument("--project", type=str, default="runs/train", help="Train project dir")
    parser.add_argument("--name", type=str, default="weed_retrain_realtime", help="Run name")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train(
        data_cfg=args.data,
        model_name=args.model,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        patience=args.patience,
        freeze=args.freeze,
        close_mosaic=args.close_mosaic,
        amp=not args.no_amp,
        single_cls=not args.multi_class,
        project=args.project,
        name=args.name,
    )

