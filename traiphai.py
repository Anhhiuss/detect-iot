#!/usr/bin/env python3

import time

from hardware.servo_pca9685 import ServoControllerPCA9685

servo = ServoControllerPCA9685()

try:

    print("\n===== PAN SWEEP =====\n")

    for p in range(30, 151, 10):
        servo.set_angle(pan=p, tilt=90)

        print(
            f"PAN={p:3d}   "
            f"{'<-- RIGHT' if p < 90 else 'CENTER' if p == 90 else 'LEFT -->'}"
        )

        time.sleep(1.5)

    print("\n===== TILT SWEEP =====\n")

    for t in range(75, 106, 5):
        servo.set_angle(pan=90, tilt=t)

        print(
            f"TILT={t:3d}   "
            f"{'DOWN' if t < 90 else 'CENTER' if t == 90 else 'UP'}"
        )

        time.sleep(1.5)

finally:
    servo.cleanup()