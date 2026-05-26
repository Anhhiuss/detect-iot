import cv2
from ultralytics import YOLO
import time
import os
from collections import deque, Counter

# =====================
# MODEL
# =====================
MODEL_PATH = "models/best.pt"

# =====================
# SETTINGS
# =====================
CONF_THRESHOLD = 0.45     # nhạy hơn
TARGET_CLASS = "weed"
AIM_RADIUS = 90
COOLDOWN = 1.0

# nếu crop/weed bị đảo -> True
SWAP_LABELS = True

# smooth detect
HISTORY_SIZE = 5

# =====================
# CHECK MODEL
# =====================
if not os.path.exists(MODEL_PATH):
    print(f"Khong tim thay model: {MODEL_PATH}")
    exit()

print("Loading model...")
model = YOLO(MODEL_PATH)

print("Classes:")
print(model.names)

# =====================
# CAMERA
# =====================
cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("Khong mo duoc webcam")
    exit()

print("Nhan q de thoat")

last_fire = 0
history = deque(maxlen=HISTORY_SIZE)

# =====================
# LOOP
# =====================
while True:

    ret, frame = cap.read()

    if not ret:
        break

    h, w = frame.shape[:2]
    center_x = w // 2
    center_y = h // 2

    # =====================
    # YOLO
    # =====================
    results = model(
        frame,
        conf=CONF_THRESHOLD,
        verbose=False
    )

    annotated = frame.copy()

    # =====================
    # CROSSHAIR
    # =====================
    cv2.line(
        annotated,
        (center_x - 20, center_y),
        (center_x + 20, center_y),
        (0, 255, 255),
        2
    )

    cv2.line(
        annotated,
        (center_x, center_y - 20),
        (center_x, center_y + 20),
        (0, 255, 255),
        2
    )

    cv2.circle(
        annotated,
        (center_x, center_y),
        AIM_RADIUS,
        (0, 255, 255),
        2
    )

    laser_fire = False
    boxes = results[0].boxes

    if len(boxes) > 0:

        for box in boxes:

            x1, y1, x2, y2 = map(
                int,
                box.xyxy[0]
            )

            conf = float(box.conf[0])
            cls = int(box.cls[0])
            class_name = model.names[cls]

            # =====================
            # FIX DAO LABEL
            # =====================
            if SWAP_LABELS:

                if class_name.lower() == "crop":
                    class_name = "weed"

                elif class_name.lower() == "weed":
                    class_name = "crop"

            history.append(class_name)

            # voting 5 frame
            stable_class = Counter(history).most_common(1)[0][0]

            obj_x = (x1 + x2) // 2
            obj_y = (y1 + y2) // 2

            dx = abs(obj_x - center_x)
            dy = abs(obj_y - center_y)

            # =====================
            # COLOR
            # =====================
            if stable_class == "weed":
                color = (0, 0, 255)
            else:
                color = (0, 255, 0)

            label = f"{stable_class} {conf:.2f}"

            cv2.rectangle(
                annotated,
                (x1, y1),
                (x2, y2),
                color,
                2
            )

            cv2.putText(
                annotated,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2
            )

            cv2.circle(
                annotated,
                (obj_x, obj_y),
                5,
                (255, 0, 0),
                -1
            )

            print(
                f"Detect: {stable_class} conf={conf:.2f}"
            )

            # =====================
            # FIRE
            # =====================
            if (
                stable_class.lower() == TARGET_CLASS
                and conf > CONF_THRESHOLD
                and dx < AIM_RADIUS
                and dy < AIM_RADIUS
            ):

                now = time.time()

                if now - last_fire > COOLDOWN:

                    last_fire = now
                    laser_fire = True

                    print(
                        f"[FIRE] {stable_class} conf={conf:.2f}"
                    )

                    cv2.rectangle(
                        annotated,
                        (x1, y1),
                        (x2, y2),
                        (0, 0, 255),
                        4
                    )

    # =====================
    # STATUS
    # =====================
    if laser_fire:

        cv2.putText(
            annotated,
            "LASER: FIRE",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            3
        )

    else:

        cv2.putText(
            annotated,
            "LASER: SAFE",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 0),
            3
        )

    cv2.imshow(
        "Weed Laser Simulator",
        annotated
    )

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()