# UART Protocol Primer

## Overview

UART (Universal Asynchronous Receiver/Transmitter) is the oldest and simplest serial protocol. It is
asynchronous — no shared clock line. Both sides must be pre-configured with the same baud rate.

## Signal Lines

| Pin | Description |
|-----|-------------|
| TX | Transmit — connects to the remote device's RX |
| RX | Receive — connects to the remote device's TX |
| RTS | Request To Send (optional hardware flow control) |
| CTS | Clear To Send (optional hardware flow control) |
| GND | Common ground (always required) |

Note: TX and RX cross-connect (TX of device A → RX of device B).

## Frame Format

```
IDLE  START  D0  D1  D2  D3  D4  D5  D6  D7  PARITY  STOP
 ‾‾‾‾  ╗____╔__╔__╔__╔__╔__╔__╔__╔__╔_______╔‾‾‾‾
```

- **Start bit**: Always LOW (1 bit)
- **Data bits**: 5, 6, 7, or 8 bits (8 is standard)
- **Parity bit**: None, Even, or Odd (optional)
- **Stop bits**: 1 or 2 bits HIGH

The most common configuration: **8N1** (8 data bits, No parity, 1 stop bit).

## Baud Rates

Standard baud rates: 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600.

The 115200 baud rate is the de-facto standard for debug/console output on microcontrollers.

## C Example (AVR bare-metal)

```c
#define F_CPU 16000000UL
#define BAUD  115200

#include <avr/io.h>
#include <util/setbaud.h>

void uart_init(void) {
    UBRR0H = UBRRH_VALUE;
    UBRR0L = UBRRL_VALUE;
#if USE_2X
    UCSR0A |= (1 << U2X0);
#else
    UCSR0A &= ~(1 << U2X0);
#endif
    UCSR0C = (1 << UCSZ01) | (1 << UCSZ00); /* 8-bit, 1 stop, no parity */
    UCSR0B = (1 << TXEN0) | (1 << RXEN0);   /* Enable TX and RX */
}

void uart_putc(char c) {
    while (!(UCSR0A & (1 << UDRE0)));
    UDR0 = c;
}

char uart_getc(void) {
    while (!(UCSR0A & (1 << RXC0)));
    return UDR0;
}
```

## C Example (ARM Cortex-M / STM32 HAL)

```c
/* Assuming HAL_UART_Init() has been called with huart1 */
void uart_send_string(const char *str) {
    HAL_UART_Transmit(&huart1, (uint8_t *)str, strlen(str), HAL_MAX_DELAY);
}

uint8_t uart_recv_byte(void) {
    uint8_t byte;
    HAL_UART_Receive(&huart1, &byte, 1, HAL_MAX_DELAY);
    return byte;
}
```

## RS-232 vs TTL UART vs RS-485

| Standard | Voltage | Differential | Topology |
|----------|---------|--------------|----------|
| TTL UART | 0–3.3 V or 0–5 V | No | Point-to-point |
| RS-232 | ±3 to ±15 V | No | Point-to-point |
| RS-485 | ±1.5 to ±6 V | Yes | Multi-drop bus |

A MAX232 or similar chip is needed to convert TTL UART to RS-232 levels.

## Common Pitfalls

1. **Baud rate mismatch** — Results in garbled data. Both sides must be identical.
2. **TX-TX or RX-RX connection** — TX must connect to the remote RX and vice versa.
3. **Voltage level mismatch** — A 5 V TX driving a 3.3 V RX will damage the 3.3 V device.
4. **Missing GND** — Without a common ground reference UART will not work.
5. **Buffer overflow** — On embedded targets without DMA, fast baud rates can overrun small receive buffers.

## See Also

- `drivers.md` — Kerf driver catalogue
- `i2c.md`, `spi.md` — Alternative serial protocols
