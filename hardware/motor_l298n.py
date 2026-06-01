from __future__ import annotations

"""
Simple L298N motor controller for Raspberry Pi.

Default wiring follows the user's physical pin numbers:
- IN3 -> physical pin 32
- IN4 -> physical pin 33

This version controls a single motor/channel with 2 input pins.
It is safe to run on a PC too: if RPi.GPIO is missing, it falls back to
simulation mode and only prints actions.
"""

from dataclasses import dataclass

from hardware.wiring import WIRING

try:
    import RPi.GPIO as GPIO
except ImportError:  # Running on PC
    GPIO = None  # type: ignore


@dataclass
class MotorConfig:
    in3: int = WIRING.motor_in3_pin
    in4: int = WIRING.motor_in4_pin
    active_high: bool = True
    use_board_numbering: bool = WIRING.use_board_numbering


class MotorL298N:
    def __init__(self, cfg: MotorConfig | None = None, simulate_if_no_gpio: bool = True) -> None:
        self.cfg = cfg or MotorConfig()
        self.simulate = GPIO is None and simulate_if_no_gpio

        if self.simulate:
            print("[MOTOR] Running in simulation mode (no RPi.GPIO).")
            return

        GPIO.setwarnings(False)
        desired_mode = GPIO.BOARD if self.cfg.use_board_numbering else GPIO.BCM
        current_mode = GPIO.getmode()
        if current_mode is None:
            GPIO.setmode(desired_mode)
        GPIO.setup(self.cfg.in3, GPIO.OUT)
        GPIO.setup(self.cfg.in4, GPIO.OUT)
        self.stop()

    def _write(self, in3: bool, in4: bool) -> None:
        if self.simulate:
            print(f"[MOTOR] IN3={int(in3)} IN4={int(in4)}")
            return

        GPIO.output(self.cfg.in3, GPIO.HIGH if in3 else GPIO.LOW)
        GPIO.output(self.cfg.in4, GPIO.HIGH if in4 else GPIO.LOW)

    def forward(self) -> None:
        self._write(True, False)

    def backward(self) -> None:
        self._write(False, True)

    def stop(self) -> None:
        self._write(False, False)

    def cleanup(self) -> None:
        if self.simulate:
            return
        try:
            if GPIO.getmode() is not None:
                self.stop()
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass


if __name__ == "__main__":
    motor = MotorL298N()
    try:
        motor.forward()
    finally:
        motor.cleanup()
