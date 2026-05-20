# I2C Protocol Primer

## Overview

I2C (Inter-Integrated Circuit) is a synchronous, multi-master, multi-slave, packet-switched serial communication bus
invented by Philips Semiconductor (now NXP). It uses only two wires: SDA (serial data) and SCL (serial clock).

## Signal Lines

| Pin | Direction | Description |
|-----|-----------|-------------|
| SDA | Bidirectional | Serial Data — open-drain, requires pull-up (typically 4.7 kΩ) |
| SCL | Bidirectional | Serial Clock — open-drain, requires pull-up (typically 4.7 kΩ) |

## Electrical Characteristics

- Logic levels: 3.3 V or 5 V (level shifting required between domains)
- Pull-up resistors: 4.7 kΩ for standard mode, 2.2 kΩ for fast mode
- Bus capacitance limit: 400 pF
- Maximum number of devices on one bus: 128 (7-bit addressing) or 1024 (10-bit addressing)

## Speed Modes

| Mode | Speed |
|------|-------|
| Standard | 100 kHz |
| Fast | 400 kHz |
| Fast-Plus | 1 MHz |
| High-Speed | 3.4 MHz |

## Protocol Structure

### Start Condition
SDA goes LOW while SCL is HIGH.

### Address Phase (7-bit)
- 7 address bits (MSB first)
- 1 R/W bit: 0 = write, 1 = read
- 1 ACK bit from slave (LOW = ACK, HIGH = NACK)

### Data Phase
Each byte (8 bits, MSB first) is followed by an ACK/NACK bit from the receiver.

### Stop Condition
SDA goes HIGH while SCL is HIGH.

### Repeated Start
A new START without a preceding STOP — used to switch direction without releasing the bus.

## C Pseudocode (bare-metal)

```c
/* ESP32 / Arduino-style register-level I2C write */
void i2c_write_reg(uint8_t dev_addr, uint8_t reg, uint8_t val) {
    i2c_start();
    i2c_write_byte((dev_addr << 1) | I2C_WRITE);  /* address + W */
    i2c_ack();
    i2c_write_byte(reg);
    i2c_ack();
    i2c_write_byte(val);
    i2c_ack();
    i2c_stop();
}

uint8_t i2c_read_reg(uint8_t dev_addr, uint8_t reg) {
    i2c_start();
    i2c_write_byte((dev_addr << 1) | I2C_WRITE);
    i2c_ack();
    i2c_write_byte(reg);
    i2c_ack();
    i2c_repeated_start();
    i2c_write_byte((dev_addr << 1) | I2C_READ);
    i2c_ack();
    uint8_t val = i2c_read_byte();
    i2c_nack();
    i2c_stop();
    return val;
}
```

## Common Pitfalls

1. **Missing pull-ups** — Bus will stay LOW; all reads return 0xFF.
2. **Clock stretching** — Some slaves hold SCL LOW to signal "not ready"; master must support this.
3. **Address conflicts** — Multiple devices can share the same default address (e.g. BME280 at 0x76/0x77).
4. **Long wires** — Excess capacitance slows edge rates; use lower-value pull-ups or reduce bus length.
5. **Voltage mismatch** — Never drive a 3.3 V device's SDA with 5 V logic without a level shifter.

## Supported Devices in Kerf

- **BME280** — temperature/humidity/pressure (0x76 or 0x77)
- **MPU6050** — 6-axis IMU (0x68 or 0x69)
- **SSD1306** — 128×64 OLED display (0x3C or 0x3D)
- **VL53L0X** — time-of-flight distance sensor (0x29)
- **PCA9685** — 16-channel PWM driver (0x40–0x7F)

## See Also

- `drivers.md` — Kerf driver catalogue
- `spi.md` — SPI protocol primer
