# 1-Wire Protocol Primer

## Overview

1-Wire is a serial protocol developed by Dallas Semiconductor (now Maxim Integrated / Analog Devices).
It uses a single data line for both communication and (in parasite-power mode) device power. The bus
is half-duplex and typically operates at about 15.4 kbit/s (standard speed) or 125 kbit/s (overdrive).

## Signal Lines

| Pin | Description |
|-----|-------------|
| DQ | Data / Power — bidirectional, open-drain, requires 4.7 kΩ pull-up to VCC |
| GND | Common ground |
| VDD | Optional external power (if not using parasite power) |

In **parasite power** mode VDD is tied to GND and the device powers itself from the DQ line capacitor.

## Timing (Standard Speed)

| Slot | Description | Duration |
|------|-------------|----------|
| Reset pulse | Master holds DQ LOW | 480–640 µs |
| Presence pulse | Slave pulls DQ LOW after master releases | 60–240 µs (detected 15–60 µs after release) |
| Write 1 slot | Master holds DQ LOW | 1–15 µs, then release |
| Write 0 slot | Master holds DQ LOW | 60–120 µs |
| Read slot | Master holds DQ LOW briefly, reads after | Master pulse 1–15 µs, read within 15 µs |

## Protocol Sequence

1. **Reset** — Master sends reset pulse; all slaves respond with presence pulse
2. **ROM command** — Master issues one of:
   - `0x33` READ ROM — read 64-bit ROM code of single device
   - `0x55` MATCH ROM — address a specific device by 64-bit ID
   - `0xCC` SKIP ROM — address all devices (or single device) without ROM addressing
   - `0xF0` SEARCH ROM — discover all device ROM codes on the bus
3. **Function command** — Device-specific commands (e.g. `0x44` CONVERT T for DS18B20)
4. **Data transfer** — Scratchpad reads/writes

## ROM Code (64-bit)

```
[ 8-bit family code | 48-bit serial number | 8-bit CRC ]
```

- DS18B20 family code: `0x28`
- DHT22 is NOT a true 1-Wire device (uses a compatible but different timing protocol)

## C Pseudocode (Bare-Metal, AVR)

```c
#define OW_PIN   PD2
#define OW_PORT  PORTD
#define OW_DDR   DDRD
#define OW_PINS  PIND

/* Drive DQ low */
static void ow_drive_low(void) {
    OW_DDR |= (1 << OW_PIN);   /* output */
    OW_PORT &= ~(1 << OW_PIN); /* LOW */
}

/* Release DQ (let pull-up bring it high) */
static void ow_release(void) {
    OW_DDR &= ~(1 << OW_PIN);  /* input */
}

static uint8_t ow_read_pin(void) {
    return (OW_PINS >> OW_PIN) & 1;
}

/* Returns 0 if device present, -1 if no presence pulse */
int ow_reset(void) {
    ow_drive_low();
    _delay_us(480);
    ow_release();
    _delay_us(70);
    uint8_t present = !ow_read_pin();
    _delay_us(410);
    return present ? 0 : -1;
}

void ow_write_bit(uint8_t bit) {
    ow_drive_low();
    if (bit) {
        _delay_us(6);
        ow_release();
        _delay_us(64);
    } else {
        _delay_us(60);
        ow_release();
        _delay_us(10);
    }
}

uint8_t ow_read_bit(void) {
    ow_drive_low();
    _delay_us(6);
    ow_release();
    _delay_us(9);
    uint8_t bit = ow_read_pin();
    _delay_us(55);
    return bit;
}

void ow_write_byte(uint8_t byte) {
    for (int i = 0; i < 8; i++) {
        ow_write_bit(byte & 1);
        byte >>= 1;
    }
}

uint8_t ow_read_byte(void) {
    uint8_t byte = 0;
    for (int i = 0; i < 8; i++) {
        byte |= (ow_read_bit() << i);
    }
    return byte;
}
```

## CRC Calculation

1-Wire uses CRC-8 (polynomial 0x31 = x^8 + x^5 + x^4 + 1).

```c
uint8_t ow_crc8(const uint8_t *data, uint8_t len) {
    uint8_t crc = 0;
    for (uint8_t i = 0; i < len; i++) {
        uint8_t byte = data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if ((crc ^ byte) & 0x01) crc = (crc >> 1) ^ 0x8C;
            else                     crc >>= 1;
            byte >>= 1;
        }
    }
    return crc;
}
```

## DHT22 Note

The DHT22 (also marketed as AM2302) uses a similar single-wire protocol but with different timing
and no ROM addressing. It is NOT compatible with the standard 1-Wire ROM search. Treat it as a
separate protocol variant.

## Common Pitfalls

1. **Missing or wrong pull-up** — 4.7 kΩ is required; too weak (>10 kΩ) causes marginal reads.
2. **Parasite power with strong pull-up** — DS18B20 conversion needs a strong pull-up (~200 Ω) during the 750 ms conversion window.
3. **Interrupt timing** — Interrupts longer than ~5 µs during a bit slot corrupt communication; disable during transfers.
4. **Multiple devices without ROM addressing** — Always use MATCH ROM when more than one device is on the bus.
5. **CRC not checked** — Scratchpad reads can be corrupted; always verify the CRC byte.

## Supported Devices in Kerf

- **DS18B20** — digital thermometer (family code 0x28)
- **DHT22** — temperature + humidity (variant protocol)

## See Also

- `drivers.md` — Kerf driver catalogue
- `uart.md` — UART protocol primer
