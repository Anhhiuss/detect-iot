from __future__ import annotations

import time
from dataclasses import dataclass

try:
    import RPi.GPIO as GPIO
except ImportError:  # Running on PC
    GPIO = None  # type: ignore


@dataclass
class ServoConfig:
    pan_pin: int = 17
    tilt_pin: int = 27
    freq_hz: int = 50
    min_angle: float = 0.0
    max_angle: float = 180.0
    min_duty: float = 2.5   # 0°
    max_duty: float = 12.5  # 180°


class ServoController:
    def __init__(self, cfg: ServoConfig | None = None, simulate_if_no_gpio: bool = True) -> None:
        self.cfg = cfg or ServoConfig()
        self.simulate = GPIO is None and simulate_if_no_gpio

        self._pan_pwm = None
        self._tilt_pwm = None

        if self.simulate:
            print("[SERVO] Running in simulation mode (no RPi.GPIO).")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.cfg.pan_pin, GPIO.OUT)
        GPIO.setup(self.cfg.tilt_pin, GPIO.OUT)

        self._pan_pwm = GPIO.PWM(self.cfg.pan_pin, self.cfg.freq_hz)
        self._tilt_pwm = GPIO.PWM(self.cfg.tilt_pin, self.cfg.freq_hz)

        self._pan_pwm.start(self._angle_to_duty(90))
        self._tilt_pwm.start(self._angle_to_duty(90))

    def _angle_to_duty(self, angle: float) -> float:
        angle = max(self.cfg.min_angle, min(self.cfg.max_angle, angle))
        span_angle = self.cfg.max_angle - self.cfg.min_angle
        span_duty = self.cfg.max_duty - self.cfg.min_duty
        return self.cfg.min_duty + (angle - self.cfg.min_angle) * span_duty / span_angle

    def set_angle(self, pan: float | None = None, tilt: float | None = None) -> None:
        if self.simulate:
            print(f"[SERVO] Sim pan={pan}, tilt={tilt}")
            return

        if pan is not None and self._pan_pwm is not None:
            duty = self._angle_to_duty(pan)
            self._pan_pwm.ChangeDutyCycle(duty)

        if tilt is not None and self._tilt_pwm is not None:
            duty = self._angle_to_duty(tilt)
            self._tilt_pwm.ChangeDutyCycle(duty)

        time.sleep(0.02)  # allow servo to move a bit

    def cleanup(self) -> None:
        if self.simulate:
            return
        if self._pan_pwm is not None:
            self._pan_pwm.stop()
        if self._tilt_pwm is not None:
            self._tilt_pwm.stop()
        GPIO.cleanup()


if __name__ == "__main__":
    sc = ServoController()
    try:
        for angle in range(60, 121, 10):
            sc.set_angle(pan=angle, tilt=angle)
            time.sleep(0.2)
    finally:
        sc.cleanup()

