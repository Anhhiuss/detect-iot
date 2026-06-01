from __future__ import annotations

"""
Minimal hardware self-test for Raspberry Pi.

Tests:
- Servo PCA9685 move to a few angles
- Laser on/off pulse
- L298N motor forward/stop

Run on Pi:
  python scripts/selftest_pi_hardware.py

On a PC, modules will fall back to simulation mode if GPIO/I2C deps are missing.
"""

import time

from hardware.laser_control import LaserController
from hardware.motor_l298n import MotorL298N
from hardware.servo_pca9685 import ServoControllerPCA9685, ServoKitConfig
from hardware.wiring import WIRING


def main() -> None:
    print("[TEST] Wiring mapping:")
    print(f"[TEST]   Servo pan  -> PCA9685 channel {WIRING.servo_pan_channel}")
    print(f"[TEST]   Servo tilt -> PCA9685 channel {WIRING.servo_tilt_channel}")
    print(f"[TEST]   Laser      -> BOARD pin {WIRING.laser_pin}")
    print(f"[TEST]   Motor IN3  -> BOARD pin {WIRING.motor_in3_pin}")
    print(f"[TEST]   Motor IN4  -> BOARD pin {WIRING.motor_in4_pin}")
    print("[TEST] Model class mapping expected: 0=crop, 1=weed")

    servo = ServoControllerPCA9685(ServoKitConfig())
    laser = LaserController()
    motor = MotorL298N()

    try:
        print("[TEST] Servo sweep...")
        for angle in (60, 90, 120, 90):
            servo.set_angle(pan=angle, tilt=angle)
            time.sleep(0.5)

        print("[TEST] Laser pulse...")
        laser.pulse(duration_sec=0.5)
        time.sleep(0.5)

        print("[TEST] Motor forward/stop...")
        motor.forward()
        time.sleep(1.0)
        motor.stop()

        print("[TEST] Done.")
    finally:
        motor.cleanup()
        servo.cleanup()
        laser.cleanup()


if __name__ == "__main__":
    main()
