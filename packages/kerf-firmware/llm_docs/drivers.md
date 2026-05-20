# Firmware Driver Catalogue

Kerf ships 12 reusable C drivers for the most common embedded sensors, actuators, and
communication ICs. Each driver is self-contained, HAL-abstracted, and RTOS-aware via the
`kerfrtos` task API (T-259).

## Quick Reference

| Driver | Part | Protocol | Header |
|--------|------|----------|--------|
| bme280 | Bosch BME280 | I2C | `drivers/bme280.h` |
| mpu6050 | InvenSense MPU-6050 | I2C | `drivers/mpu6050.h` |
| ssd1306 | Solomon SSD1306 | I2C | `drivers/ssd1306.h` |
| vl53l0x | ST VL53L0X | I2C | `drivers/vl53l0x.h` |
| pca9685 | NXP PCA9685 | I2C | `drivers/pca9685.h` |
| hx711 | AVIA HX711 | Pseudo-SPI | `drivers/hx711.h` |
| mcp2515 | Microchip MCP2515 | SPI+CAN | `drivers/mcp2515.h` |
| mfrc522 | NXP MFRC522 | SPI | `drivers/mfrc522.h` |
| max31855 | Maxim MAX31855 | SPI | `drivers/max31855.h` |
| ds18b20 | Dallas DS18B20 | 1-Wire | `drivers/ds18b20.h` |
| dht22 | AOSONG DHT22 | Single-wire | `drivers/dht22.h` |
| ws2812 | WorldSemi WS2812B | Bit-bang | `drivers/ws2812.h` |

## Driver Descriptions

### BME280 — Temperature / Humidity / Pressure (I2C)

Bosch BME280 environmental sensor. I2C address 0x76 or 0x77. 24-bit ADC with on-chip
trimming coefficients. Provides temperature (±1°C), humidity (±3% RH), and pressure
(±1 hPa). Supports forced mode and normal (periodic) mode.

**API highlights:**
```c
bme280_init(&dev, 0x76, I2C_BUS_0, sda=21, scl=22);
bme280_read(&dev, &temp_c, &humidity, &pressure_pa);
```

### MPU-6050 — 6-Axis IMU (I2C)

InvenSense MPU-6050 with 3-axis gyroscope (±250–2000°/s) and 3-axis accelerometer
(±2–16 g). I2C address 0x68 or 0x69. On-chip DMP for sensor fusion.

**API highlights:**
```c
mpu6050_init(&imu, 0x68, I2C_BUS_0, sda=21, scl=22);
mpu6050_read(&imu, &data);  // fills mpu6050_data_t
```

### SSD1306 — 128×64 OLED Display (I2C)

Solomon SSD1306 OLED controller. 1 KB frame buffer maintained in RAM. Flush to hardware
with `ssd1306_display()`. Supports pixel-level drawing operations.

**API highlights:**
```c
ssd1306_init(&oled, 0x3C, I2C_BUS_0, sda=21, scl=22);
ssd1306_draw_pixel(&oled, x, y, 1);
ssd1306_display(&oled);
```

### VL53L0X — Time-of-Flight Distance Sensor (I2C)

ST VL53L0X VCSEL-based ToF sensor. Measures 20–2000 mm with ±3% accuracy. I2C address
0x29 (can be changed in software for multi-sensor buses). Supports single-shot and
continuous modes.

**API highlights:**
```c
vl53l0x_init(&tof, 0x29, I2C_BUS_0, sda=21, scl=22);
vl53l0x_read_range_mm(&tof, &range_mm);
```

### PCA9685 — 16-Channel 12-bit PWM (I2C)

NXP PCA9685 PWM driver. 16 independent channels, 12-bit resolution, 24–1526 Hz.
Configurable I2C address (0x40–0x7F). Ideal for RC servo control and LED dimming.

**API highlights:**
```c
pca9685_init(&pwm, 0x40, I2C_BUS_0, sda=21, scl=22);
pca9685_set_freq(&pwm, 50.0f);           // 50 Hz
pca9685_set_channel_us(&pwm, 0, 1500);  // 1500 µs servo centre
```

### HX711 — 24-bit ADC for Load Cells (Pseudo-SPI)

AVIA HX711 load cell amplifier. 2-wire interface (DOUT + PD_SCK). 10/80 Hz output rate.
Channel A (gain 128 or 64) or Channel B (gain 32). Includes tare and scale calibration.

**API highlights:**
```c
hx711_init(&scale, dout=4, sck=5, HX711_GAIN_128);
hx711_tare(&scale, 10);
hx711_weight_kg(&scale, &weight_kg);
```

### MCP2515 — CAN Bus Controller (SPI)

Microchip MCP2515 standalone CAN 2.0A/B controller. Three TX buffers, two RX buffers,
six acceptance filters. Requires external MCP2551 or TJA1050 transceiver. 8 or 16 MHz
crystal. Bit timing presets for 125k–1 Mbit/s.

**API highlights:**
```c
mcp2515_init(&can, SPI_BUS_0, cs=10, MCP2515_SPEED_500KBPS, MCP2515_OSC_8MHZ);
mcp2515_send(&can, &frame);
mcp2515_recv(&can, &frame);
```

### MFRC522 — RFID Reader/Writer (SPI)

NXP MFRC522 ISO 14443A / MIFARE reader at 13.56 MHz. SPI up to 10 MHz. Supports UID
reading, authentication, and MIFARE Classic read/write. Hardware version register
returns 0x91 or 0x92.

**API highlights:**
```c
mfrc522_init(&rfid, SPI_BUS_0, cs=10, rst=9);
mfrc522_read_uid(&rfid, uid, &uid_len);
```

### MAX31855 — K-Type Thermocouple Amplifier (SPI)

Maxim MAX31855 read-only SPI device. 14-bit thermocouple temperature (0.25°C LSB,
−200°C to +1350°C) and 12-bit cold-junction reference (0.0625°C LSB). Detects open
circuit, short to GND, short to VCC.

**API highlights:**
```c
max31855_init(&tc, SPI_BUS_0, cs=10);
max31855_read_celsius(&tc, &temp_c);
```

### DS18B20 — Digital Thermometer (1-Wire)

Dallas/Maxim DS18B20. Single 4.7 kΩ pull-up wire. Family code 0x28. 9–12 bit
resolution (default 12-bit, 750 ms conversion). CRC-8 validated scratchpad.

**API highlights:**
```c
ds18b20_init(&dev, pin_dq=2);
ds18b20_read_single(&dev, &temp_c);
```

### DHT22 — Temperature + Humidity (Single-wire)

AOSONG DHT22 (AM2302). Proprietary single-wire protocol (NOT 1-Wire standard).
10 kΩ pull-up required. 0–100% RH (±2%), −40°C to +80°C (±0.5°C). 2 s minimum
reading interval. 40-bit output with 8-bit checksum.

**API highlights:**
```c
dht22_init(&dht, pin_data=4);
dht22_read(&dht, &temp_c, &humidity);
```

### WS2812B — Addressable RGB LEDs (Bit-bang)

WorldSemi WS2812B single-wire NZR protocol. 24-bit GRB per LED, cascaded. Timing:
T1H ≈ 800 ns, T0H ≈ 400 ns, RESET > 50 µs LOW. Interrupts must be disabled during
transmission. 5 V logic (level shifter from 3.3 V recommended).

**API highlights:**
```c
ws2812_init(&strip, pin_din=6, pixels, LED_COUNT);
ws2812_set_pixel(&strip, 0, r=255, g=0, b=0);
ws2812_show(&strip);
```

## LLM Tool: make_protocol_driver

Use the `make_protocol_driver` LLM tool to generate a customised driver file with
your pin assignments pre-defined as macros:

```json
{
  "protocol": "i2c",
  "target":   "bme280",
  "pins": { "sda": 21, "scl": 22 }
}
```

This returns a `.c` file with:
```c
#define KERF_PIN_SCL  22
#define KERF_PIN_SDA  21
```
injected before the first `#include`.

## HAL Abstraction

All drivers depend on platform HAL functions defined as `__attribute__((weak))` stubs:

| HAL family | Functions |
|-----------|-----------|
| I2C | `kerf_i2c_write()`, `kerf_i2c_read()` |
| SPI | `kerf_spi_cs_low()`, `kerf_spi_cs_high()`, `kerf_spi_transfer()` |
| GPIO | `kerf_gpio_set_output()`, `kerf_gpio_set_input()`, `kerf_gpio_write()`, `kerf_gpio_read()` |
| Timing | `kerf_delay_ms()`, `kerf_delay_us()`, `kerf_delay_ns()`, `kerf_millis()` |
| 1-Wire | `kerf_ow_reset()`, `kerf_ow_write_byte()`, `kerf_ow_read_byte()` |

Implement these in your board support package (BSP). On FreeRTOS targets, I2C/SPI HAL
functions should acquire the appropriate peripheral mutex before use.

## Protocol Primers

For protocol-level documentation see:
- `protocols/i2c.md` — I2C primer
- `protocols/spi.md` — SPI primer
- `protocols/uart.md` — UART primer
- `protocols/can.md` — CAN bus primer
- `protocols/onewire.md` — 1-Wire primer
- `protocols/i2s.md` — I2S audio primer

## Source Location

```
packages/kerf-firmware/src/kerf_firmware/drivers/
  bme280.{c,h}    mpu6050.{c,h}   ssd1306.{c,h}
  vl53l0x.{c,h}  pca9685.{c,h}   hx711.{c,h}
  mcp2515.{c,h}   mfrc522.{c,h}   max31855.{c,h}
  ds18b20.{c,h}   dht22.{c,h}     ws2812.{c,h}
```
