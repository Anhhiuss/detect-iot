from hardware.servo_pca9685 import ServoControllerPCA9685
from hardware.laser_control import LaserController

servo = ServoControllerPCA9685()
laser = LaserController()

pan = 90
tilt = 90

servo.set_angle(pan=pan, tilt=tilt)
laser.on()

print("a/d = pan")
print("w/s = tilt")
print("q = quit")

while True:
    cmd = input("> ").strip().lower()

    if cmd == "a":
        pan -= 10

    elif cmd == "d":
        pan += 10

    elif cmd == "w":
        tilt -= 10  

    elif cmd == "s":
        tilt += 10

    elif cmd == "q":
        break

    pan = max(0, min(180, pan))
    tilt = max(0, min(180, tilt))

    servo.set_angle(pan=pan, tilt=tilt)

    print(f"PAN={pan} TILT={tilt}")

laser.off()
servo.cleanup()
laser.cleanup()