from __future__ import annotations

"""Central wiring configuration for Raspberry Pi hardware.

Update this file if you change any wire. All hardware modules and tests
should import values from here so pin/channel mapping stays consistent.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WiringConfig:
    # PCA9685 servo channels
    servo_pan_channel: int = 14
    servo_tilt_channel: int = 15

    # Laser on Raspberry Pi physical pin numbering
    laser_pin: int = 16

    # L298N on Raspberry Pi physical pin numbering
    motor_in3_pin: int = 32
    motor_in4_pin: int = 33

    # GPIO numbering mode for L298N/laser
    use_board_numbering: bool = True


WIRING = WiringConfig()
