# Sơ đồ nối dây: Raspberry Pi + PCA9685 + Servo + Laser

## Sơ đồ khối phần cứng

```
                    Raspberry Pi 4
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   Camera Module    I2C (GPIO2/3)     GPIO 17
   (USB hoặc CSI)        │            (Laser)
        │                │                │
        │           PCA9685                │
        │         (I2C 0x40)               │
        │         ┌───┴───┐                │
        │         │ CH0   │ Servo Pan      │
        │         │ CH1   │ Servo Tilt     │
        │         └───────┘                │
        │                                  │
        ▼                                  ▼
   [Camera]                    [Laser module]
```

## Kết nối I2C: Raspberry Pi ↔ PCA9685

| Raspberry Pi (BCM) | PCA9685 | Ghi chú        |
|--------------------|---------|----------------|
| GPIO 2 (SDA)       | SDA     | I2C Data       |
| GPIO 3 (SCL)       | SCL     | I2C Clock      |
| 3.3V (pin 1 hoặc 17) | VCC  | Nguồn 3.3V     |
| GND (pin 6, 9, ...)  | GND   | Mass chung     |

**Lưu ý:** PCA9685 dùng 3.3V logic; nguồn động cơ servo (V+) nên lấy từ nguồn ngoài 5–6V (không nối 5V vào Pi qua PCA9685 nếu dòng lớn).

## Kết nối servo với PCA9685

| PCA9685 | Servo        | Dây servo (thường) |
|---------|-------------|---------------------|
| Channel 0 (OUT0) | Servo Pan  | Signal (cam/vàng) → OUT0; V+ → nguồn 5V; GND → GND |
| Channel 1 (OUT1) | Servo Tilt | Signal → OUT1; V+ → 5V; GND → GND |

- **V+** của 2 servo có thể chung 1 nguồn 5V (đủ dòng, ví dụ 2A).
- **GND** của Pi, PCA9685 và nguồn servo **nối chung**.

## Kết nối laser với Raspberry Pi

| Raspberry Pi | Laser module |
|--------------|--------------|
| GPIO 17 (BCM) | Signal / IN (qua transistor hoặc module 3.3V) |
| 3.3V hoặc 5V | VCC (tùy module) |
| GND          | GND |

**An toàn:** Nếu laser dòng lớn, dùng transistor hoặc relay; GPIO chỉ điều khiển cực base/coil.

## Bật I2C trên Raspberry Pi

```bash
sudo raspi-config
# Interface Options → I2C → Enable
sudo reboot
# Kiểm tra
i2cdetect -y 1
# Thấy địa chỉ 0x40 (PCA9685) là đúng
```

## Cài driver Python cho PCA9685

```bash
pip install adafruit-circuitpython-servokit
# Hoặc
pip install adafruit-circuitpython-pca9685
pip install adafruit-circuitpython-servokit
```

## Sơ đồ tóm tắt (ASCII)

```
    [Raspberry Pi 4]
         │
    ┌────┴────┬──────────────┐
    │         │              │
 Camera   I2C (SDA/SCL)   GPIO17
    │         │              │
    │    [PCA9685]        [Laser]
    │    CH0 → Pan
    │    CH1 → Tilt
    │         │
    │    [Servo Pan] [Servo Tilt]
    │         │
    └─────────┴──────────────────
```

## Chạy code với PCA9685

```bash
python run_weed_laser.py --pca9685 --show
# Hoặc
python main.py --camera 0 --fps 8 --imgsz 320
# (main.py đang dùng servo GPIO; dùng run_weed_laser.py --pca9685 cho ServoKit)
```
