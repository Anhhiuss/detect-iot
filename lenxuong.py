from hardware.motor_l298n import MotorL298N
import time

motor = MotorL298N()

print("FORWARD")
motor.forward()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("STOP")
    motor.stop()
    motor.cleanup()