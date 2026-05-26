# Hệ Thống Phát Hiện & Diệt Cỏ Tự Động

## Tổng Quan Quy Trình

```
┌─────────────────────────────────────────────────────────────────┐
│                   RASPBERRY PI 4 (Main)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Camera Input                                                │
│     ├─ USB camera / CSI camera (PiCamera2)                      │
│     └─ Real-time frame capture (10-15 FPS)                      │
│            │                                                    │
│            ▼                                                    │
│  2. YOLO Detection                                              │
│     ├─ YOLOv8n inference (imgsz=320 for speed)                  │
│     ├─ Detect weed objects                                      │
│     ├─ Extract bounding boxes                                   │
│     └─ Calculate confidence scores                              │
│            │                                                    │
│            ▼                                                    │
│  3. Servo Angle Calculation                                     │
│     ├─ Convert bbox coordinates → pan/tilt angles              │
│     ├─ Apply calibration offsets                                │
│     └─ Clamp angles to safe range (20-160°)                     │
│            │                                                    │
│            ▼                                                    │
│  4. MQTT Publishing                                             │
│     ├─ Send: esp32/servo/pan {"angle": 90}                      │
│     ├─ Send: esp32/servo/tilt {"angle": 45}                     │
│     ├─ Send: esp32/laser/pulse {"duration": 0.3}               │
│     └─ Publish every frame or after voting window               │
│            │                                                    │
│            │ (WiFi: typically < 100ms latency)                 │
│            │                                                    │
└─────────────────────────────────────────────────────────────────┘
                            │
                  ┌─────────┴─────────┐
                  │  MQTT Broker      │
                  │  (Mosquitto)      │
                  │  Port 1883        │
                  └─────────┬─────────┘
                            │
                            │
┌─────────────────────────────────────────────────────────────────┐
│                   ESP32 (Remote Control)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. WiFi Connection                                             │
│     └─ Connect to network (2.4GHz)                              │
│                                                                 │
│  2. MQTT Subscribe                                              │
│     ├─ esp32/servo/pan                                          │
│     ├─ esp32/servo/tilt                                         │
│     ├─ esp32/laser/pulse                                        │
│     ├─ esp32/laser/on                                           │
│     └─ esp32/laser/off                                          │
│                                                                 │
│  3. Receive Commands                                            │
│     ├─ Parse JSON payload                                       │
│     └─ Extract angle / duration values                          │
│            │                                                    │
│            ▼                                                    │
│  4. PWM Control                                                 │
│     ├─ Pin 15 (Pan Servo): PWM 50Hz, 1.0-2.0ms                 │
│     ├─ Pin 4 (Tilt Servo): PWM 50Hz, 1.0-2.0ms                 │
│     └─ Angle range: 0-180° (safe: 20-160°)                     │
│            │                                                    │
│            ▼                                                    │
│  5. Laser Control                                               │
│     ├─ Pin 2 (Laser): HIGH (on) or LOW (off)                   │
│     ├─ Pulse mode: on for X milliseconds                        │
│     └─ Safety: OFF by default, bật khi phát hiện cỏ            │
│            │                                                    │
└─────────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
    Pan Servo          Tilt Servo           Laser Module
    (GPIO 15)          (GPIO 4)             (GPIO 2)
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                            ▼
                    ╔══════════════════╗
                    ║  Destroy Weeds   ║
                    ║   in Field!      ║
                    ╚══════════════════╝
```

## Thành Phần Chính

### Raspberry Pi 4 (Chủ)
- **Camera**: USB hoặc CSI (PiCamera2)
- **YOLO**: YOLOv8n detection
- **MQTT Client**: Gửi commands tới ESP32
- **Servo Controller**: Local (nếu dùng GPIO/PCA9685)
- **Laser Controller**: Local (nếu dùng GPIO)

### ESP32 (Tớ)
- **WiFi**: Kết nối mạng 2.4GHz
- **MQTT Client**: Subscribe topics từ Pi4
- **PWM Generator**: Điều khiển servo qua PWM
- **GPIO**: Điều khiển laser

### Cấu Hình Điều Khiển

| Mode | Servo | Laser | Description |
|------|-------|-------|-------------|
| **Local** | GPIO Pi | GPIO Pi | Traditional (servo rung nhiều) |
| **PCA9685** | PCA9685 I2C | GPIO Pi | Better servo stability |
| **ESP32** | ESP32 PWM | ESP32 GPIO | Fully remote via WiFi |
| **Hybrid1** | PCA9685 | ESP32 | Servo smooth + laser remote |
| **Hybrid2** | ESP32 | GPIO Pi | Servo remote + laser fast |

## Cài Đặt Nhanh

### 1. MQTT Broker Setup (Raspberry Pi)

```bash
# Install Mosquitto
sudo apt-get update
sudo apt-get install mosquitto mosquitto-clients

# Start service
sudo systemctl start mosquitto
sudo systemctl enable mosquitto

# Verify running
sudo systemctl status mosquitto
```

### 2. ESP32 Firmware (C++)

```bash
# 1. Install Arduino IDE
#    Download: https://www.arduino.cc/en/software

# 2. Add ESP32 board support in Arduino IDE
#    File > Preferences > Additional Board Manager URLs
#    Add: https://dl.espressif.com/dl/package_esp32_index.json

# 3. Install libraries in Arduino IDE
#    Sketch > Include Library > Manage Libraries
#    - Search "PubSubClient" (by Nick O'Leary)
#    - Search "ArduinoJson" (by Benoit Blanchon)

# 4. Edit weed_detection.ino (lines 32-36)
#    const char* SSID = "YOUR_SSID";
#    const char* WIFI_PASSWORD = "YOUR_PASSWORD";
#    const char* MQTT_BROKER = "192.168.1.100"; // Pi IP

# 5. Upload to ESP32
#    Tools > Board > esp32 > ESP32 Dev Module
#    Tools > Port > COM3
#    Sketch > Upload
```

### 3. Python Setup (Raspberry Pi)

```bash
# Install dependencies
pip install -r requirements.txt

# Test MQTT connection
mosquitto_pub -h 192.168.1.100 -t "esp32/servo/pan" -m '{"angle": 90}'

# Monitor ESP32
mosquitto_sub -h 192.168.1.100 -t "esp32/#" -v
```

### 4. Run Weed Detector

```bash
# Option 1: ESP32 controls both servo & laser (recommended)
python run_weed_laser.py --esp32 --esp32-broker 192.168.1.100 --show

# Option 2: ESP32 servo only
python run_weed_laser.py --esp32-servo-only --esp32-broker 192.168.1.100 --show

# Option 3: ESP32 laser only
python run_weed_laser.py --esp32-laser-only --esp32-broker 192.168.1.100 --show

# Option 4: Local GPIO only (traditional)
python run_weed_laser.py --show

# Option 5: PCA9685 servo + ESP32 laser
python run_weed_laser.py --pca9685 --esp32-laser-only --esp32-broker 192.168.1.100 --show
```

## Hiệu Suất & Latency

### Latency Breakdown (mS)

```
┌─────────────────────────────────────────┐
│ Total SCAN → FIRE Latency: ~300-500ms   │
├─────────────────────────────────────────┤
│ 1. Camera capture:         ~33ms (30 FPS)
│ 2. YOLO inference:        ~80-150ms      
│ 3. MQTT publish:           ~50ms         
│ 4. WiFi transmission:      ~20-50ms      
│ 5. ESP32 receive:          ~10ms         
│ 6. Servo movement:         ~100ms        
│ 7. Laser pulse:            ~300ms        
└─────────────────────────────────────────┘
```

### Performance Tips

1. **Tăng tốc độ**: Giảm `--imgsz` từ 640 → 320
2. **Giảm rung**: Tăng `--settle` từ 0.12s → 0.2s
3. **Ổn định**: Bật `--track` (botsort tracker)
4. **Khử flicker**: Điều chỉnh `--vote-window` + `--min-hits`

## File Structure

```
detect-iot/
├── run_weed_laser.py          # Main detection script
├── main.py                     # Alternative entry point
├── requirements.txt            # Python dependencies
│
├── hardware/
│   ├── servo_control.py        # GPIO servo (local)
│   ├── servo_pca9685.py        # PCA9685 servo (I2C)
│   ├── laser_control.py        # GPIO laser (local)
│   └── esp32_control.py        # ESP32 MQTT client
│
├── esp32_firmware/
│   ├── weed_detection.ino      # C++ firmware (Arduino)
│   ├── SETUP_CPP.md            # C++ setup guide
│   ├── wifi_config.json        # WiFi + MQTT config (deprecated, now in .ino)
│   ├── mqtt_client.py          # MicroPython MQTT (deprecated)
│   └── main.py                 # MicroPython (deprecated)
│
├── models/
│   ├── best.pt                 # YOLO model (PyTorch)
│   └── best.onnx               # YOLO model (ONNX)
│
├── config/
│   ├── weed.yaml               # Dataset config
│   └── weed_single.yaml        # Single class config
│
├── utils/
│   ├── camera_pi.py            # PiCamera2 wrapper
│   ├── coordinate_convert.py   # Bbox → servo angles
│   └── rt_tasks.py             # Real-time utilities
│
├── training/
│   └── train.py                # YOLO training script
│
├── scripts/
│   ├── deploy_to_esp32.sh      # Flash ESP32 (shell)
│   ├── deploy_to_esp32.ps1     # Flash ESP32 (PowerShell)
│   ├── setup_esp32_mqtt.py     # MQTT broker setup
│   └── ... (other utilities)
│
├── ESP32_SETUP.md              # ESP32 detailed guide
├── ESP32_EXAMPLES.md           # Usage examples
├── ESP32_CHECKLIST.md          # Deployment checklist
└── README.md                   # This file
```

## MQTT Topics Reference

### Subscribe (ESP32 receives from Pi)

| Topic | Payload | Purpose |
|-------|---------|---------|
| `esp32/servo/pan` | `{"angle": 0-180}` | Set pan servo angle |
| `esp32/servo/tilt` | `{"angle": 0-180}` | Set tilt servo angle |
| `esp32/laser/pulse` | `{"duration": 0.3}` | Pulse laser for N seconds |
| `esp32/laser/on` | `{}` | Turn laser on continuously |
| `esp32/laser/off` | `{}` | Turn laser off |

### Publish (ESP32 sends to Pi)

| Topic | Payload | Interval |
|-------|---------|----------|
| `esp32/status` | `{"uptime": s, "temp": °C, "pan": °, ...}` | 10 seconds |

## Troubleshooting

### ESP32 not connecting to WiFi
```bash
# Check in Arduino Serial Monitor (115200 baud)
[WiFi] Connecting to: YOUR_SSID
...
[WiFi] Connected! IP: 192.168.1.50

# If fails: WiFi must be 2.4GHz (not 5GHz)
```

### Servo doesn't respond
```bash
# Test manually
mosquitto_pub -h 192.168.1.100 -t "esp32/servo/pan" -m '{"angle": 0}'

# Check ESP32 logs for received message
```

### Laser doesn't fire
```bash
# Test on/off
mosquitto_pub -h 192.168.1.100 -t "esp32/laser/on" -m '{}'
mosquitto_pub -h 192.168.1.100 -t "esp32/laser/off" -m '{}'

# Verify 5V power at laser module
```

### High latency (slow servo response)
```bash
# Monitor with:
python run_weed_laser.py --esp32 --state-debug-log

# Should see: SCAN->FIRE latency < 1 second
# If > 1s: check WiFi signal or reduce imgsz
```

## Next Steps

1. **Hardware Assembly**: Wire servo + laser to ESP32
2. **Firmware Upload**: Flash C++ firmware via Arduino IDE
3. **Network Setup**: Connect both Pi4 and ESP32 to same WiFi
4. **Testing**: Run manual MQTT tests (mosquitto_pub/sub)
5. **Integration**: Start weed detection script
6. **Calibration**: Adjust `--offset-pan` / `--offset-tilt`
7. **Field Deployment**: Mount on robot/drone

## References

- [MQTT Specification](http://mqtt.org/)
- [ESP32 Pinout](https://randomnerdtutorials.com/esp32-pinout-reference/)
- [Servo Motor Guide](https://www.servocity.com/servo-motor-tutorials)
- [YOLOv8 Documentation](https://docs.ultralytics.com/)
- [Raspberry Pi GPIO](https://www.raspberrypi.com/documentation/computers/gpio.html)

---

**Status**: ✅ Ready for deployment

**Last Updated**: May 2026

**Version**: 2.0 (C++ Firmware)
