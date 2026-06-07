# test_center.py

from hardware.servo_pca9685 import ServoControllerPCA9685
from hardware.laser_control import LaserController
import time

servo = ServoControllerPCA9685()
laser = LaserController()

try:
    servo.set_angle(
        pan=80,
        tilt=105

    )

    laser.on()

    print("PAN=90 TILT=90")
    print("LASER=ON")
    print("Nhấn Ctrl+C để thoát")

    while True:
        time.sleep(1)

except KeyboardInterrupt:
    pass

finally:
    laser.off()
    laser.cleanup()
    servo.cleanup()

    print("LASER=OFF")