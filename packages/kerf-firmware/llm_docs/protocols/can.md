# CAN Bus Protocol Primer

## Overview

CAN (Controller Area Network) was originally developed by Bosch for automotive applications. It is a
differential, multi-master serial bus that is extremely robust in electrically noisy environments.
CAN operates without a central master — any node can transmit when the bus is idle.

## Signal Lines

| Pin | Description |
|-----|-------------|
| CAN_H | CAN High — dominant state drives this HIGH |
| CAN_L | CAN Low — dominant state drives this LOW |
| GND | Common ground |

The bus uses a differential voltage: CAN_H − CAN_L ≈ 2 V in dominant state, ≈ 0 V in recessive state.

**Termination**: 120 Ω resistors at both physical ends of the bus are mandatory.

## Speeds

| Network | Speed | Max Length |
|---------|-------|-----------|
| CAN 2.0A/B | 1 Mbit/s | 40 m |
| CAN 2.0A/B | 500 kbit/s | 100 m |
| CAN 2.0A/B | 250 kbit/s | 250 m |
| CAN 2.0A/B | 125 kbit/s | 500 m |
| CAN FD | 5–8 Mbit/s (data phase) | variable |

## Frame Types

### Standard Frame (CAN 2.0A — 11-bit ID)
```
SOF | 11-bit ID | RTR | IDE | r0 | DLC | 0–8 bytes data | CRC | ACK | EOF
```

### Extended Frame (CAN 2.0B — 29-bit ID)
```
SOF | 11-bit base | SRR | IDE=1 | 18-bit extension | RTR | r1 | r0 | DLC | data | CRC | ACK | EOF
```

## Arbitration

CAN uses bitwise non-destructive arbitration. The lowest numeric ID wins the bus (dominant bits win).
Nodes that lose arbitration automatically retry on the next bus-idle.

## Error Handling

The CAN protocol has built-in error detection:
- CRC check on every frame
- Bit monitoring (transmitter reads back its own bits)
- Frame check (fixed-form fields)
- Acknowledgement check

Nodes maintain Transmit Error Counter (TEC) and Receive Error Counter (REC).
States: Error Active → Error Passive → Bus-Off.

## MCP2515 — SPI CAN Controller

The MCP2515 is a standalone CAN controller that attaches to any microcontroller via SPI.
It includes an integrated CAN transceiver interface and requires an external TJA1050/MCP2551 transceiver.

```
MCU ─── SPI ───► MCP2515 ──► MCP2551 (transceiver) ──► CAN_H / CAN_L
```

### MCP2515 SPI Commands

| Command | Byte | Description |
|---------|------|-------------|
| RESET | 0xC0 | Reset to default state |
| READ | 0x03 | Read register |
| WRITE | 0x02 | Write register |
| BIT_MODIFY | 0x05 | Modify selected bits |
| LOAD TX BUFFER | 0x40–0x42 | Load one of 3 TX buffers |
| RTS | 0x80–0x87 | Request to send |
| READ RX BUFFER | 0x90, 0x94 | Read RX buffer 0 or 1 |
| READ STATUS | 0xA0 | Read status bits |
| RX STATUS | 0xB0 | Read RX filter status |

### Bit Timing Calculation

For 500 kbit/s with 8 MHz oscillator:
- TQ = 1 / (2 × BRP × Fosc)  where BRP is the Baud Rate Prescaler
- Total TQ per bit = Sync_Seg + Prop_Seg + Phase_Seg1 + Phase_Seg2

## C Pseudocode

```c
/* Send a CAN frame via MCP2515 */
void can_send(uint16_t id, uint8_t *data, uint8_t len) {
    mcp2515_write(MCP_TXB0SIDH, (id >> 3) & 0xFF);
    mcp2515_write(MCP_TXB0SIDL, (id & 0x07) << 5);
    mcp2515_write(MCP_TXB0DLC, len & 0x0F);
    for (uint8_t i = 0; i < len; i++)
        mcp2515_write(MCP_TXB0D0 + i, data[i]);
    mcp2515_rts(0); /* Request to Send TX buffer 0 */
}
```

## Common Pitfalls

1. **Missing termination resistors** — Bus will not function; check both ends for 120 Ω.
2. **Wrong SPI mode** — MCP2515 uses SPI Mode 0,0 (CPOL=0, CPHA=0).
3. **Oscillator frequency** — The bit timing registers depend on the MCP2515 crystal; default firmware often assumes 8 MHz.
4. **No transceiver** — The MCP2515 does NOT include a CAN transceiver; an external MCP2551 or TJA1050 is required.
5. **Baud rate mismatch** — All nodes on the bus must use identical bit timing.

## See Also

- `drivers.md` — Kerf driver catalogue (MCP2515 driver)
- `spi.md` — SPI protocol primer
