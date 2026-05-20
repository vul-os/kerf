# SPI Protocol Primer

## Overview

SPI (Serial Peripheral Interface) is a synchronous serial communication protocol developed by Motorola.
It uses four wires and supports full-duplex communication at speeds typically up to 80 MHz.

## Signal Lines

| Pin | Direction | Description |
|-----|-----------|-------------|
| SCLK / SCK | Master → Slave | Serial clock |
| MOSI | Master → Slave | Master Out Slave In — data from master |
| MISO | Slave → Master | Master In Slave Out — data from slave |
| CS / SS / NSS | Master → Slave | Chip Select (active LOW) — one per slave |

## Clock Modes (CPOL / CPHA)

| Mode | CPOL | CPHA | Clock idle | Sample edge |
|------|------|------|-----------|-------------|
| 0 | 0 | 0 | LOW | Rising |
| 1 | 0 | 1 | LOW | Falling |
| 2 | 1 | 0 | HIGH | Falling |
| 3 | 1 | 1 | HIGH | Rising |

Most devices use Mode 0 (CPOL=0, CPHA=0). Check the device datasheet.

## Transaction Structure

1. Assert CS LOW
2. Simultaneously clock MOSI (master sends) and MISO (slave responds)
3. Deassert CS HIGH

```
CS:    ‾‾‾‾╗____________________________╔‾‾‾‾
SCLK:      ╚═╗_╔═╗_╔═╗_╔═╗_╔═╗_╔═╗_╔═╝
MOSI:       B7 B6 B5 B4 B3 B2 B1 B0
MISO:       Q7 Q6 Q5 Q4 Q3 Q2 Q1 Q0
```

## C Pseudocode (bare-metal)

```c
/* Bit-bang SPI (Mode 0) */
uint8_t spi_transfer(uint8_t tx) {
    uint8_t rx = 0;
    for (int i = 7; i >= 0; i--) {
        MOSI_PIN = (tx >> i) & 1;
        SCK_HIGH();
        rx |= (MISO_READ() << i);
        SCK_LOW();
    }
    return rx;
}

uint8_t spi_read_reg(uint8_t reg) {
    CS_LOW();
    spi_transfer(reg | 0x80);  /* read flag — device-specific */
    uint8_t val = spi_transfer(0x00);
    CS_HIGH();
    return val;
}

void spi_write_reg(uint8_t reg, uint8_t val) {
    CS_LOW();
    spi_transfer(reg & 0x7F);  /* write flag — device-specific */
    spi_transfer(val);
    CS_HIGH();
}
```

## Hardware SPI (AVR example)

```c
void spi_init(void) {
    DDRB |= (1 << PB3) | (1 << PB5) | (1 << PB2); /* MOSI, SCK, SS as outputs */
    SPCR = (1 << SPE) | (1 << MSTR) | (1 << SPR0); /* Enable, Master, Fosc/16 */
}

uint8_t spi_transfer_hw(uint8_t data) {
    SPDR = data;
    while (!(SPSR & (1 << SPIF)));
    return SPDR;
}
```

## Common Pitfalls

1. **Wrong clock mode** — The most common SPI bug; verify CPOL/CPHA in the device datasheet.
2. **CS timing** — Some devices require CS to be deasserted between bytes (word mode).
3. **Max clock speed** — Check the device's maximum SPI clock; do not exceed it.
4. **Shared bus, multiple devices** — Only one CS may be asserted LOW at a time.
5. **LSB vs MSB first** — Most devices are MSB-first but some (e.g. certain ADCs) are LSB-first.

## Supported Devices in Kerf

- **HX711** — 24-bit ADC for load cells (pseudo-SPI, dedicated protocol)
- **MCP2515** — CAN bus controller
- **SSD1306** — OLED display (also supports I2C)
- **MFRC522** — RFID reader/writer
- **MAX31855** — K-type thermocouple amplifier (read-only SPI)

## See Also

- `drivers.md` — Kerf driver catalogue
- `i2c.md` — I2C protocol primer
- `can.md` — CAN bus primer (MCP2515 uses SPI)
