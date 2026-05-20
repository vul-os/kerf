/**
 * mcp2515.h — Driver for Microchip MCP2515 SPI CAN bus controller
 *
 * Protocol : SPI (Mode 0, CPOL=0 CPHA=0), up to 10 MHz
 * External : MCP2551 or TJA1050 CAN transceiver required for physical bus
 * Crystal  : Typically 8 MHz or 16 MHz (affects bit-timing register values)
 *
 * Datasheet: https://ww1.microchip.com/downloads/en/DeviceDoc/MCP2515-Stand-Alone-CAN-Controller-with-SPI-20001801J.pdf
 *
 * The MCP2515 provides full CAN 2.0A (11-bit ID) and 2.0B (29-bit ID)
 * support. It has three TX buffers, two RX buffers, and six acceptance filters.
 *
 * Usage:
 *   mcp2515_t can;
 *   mcp2515_init(&can, SPI_BUS_0, CS_PIN, MCP2515_SPEED_500KBPS, MCP2515_OSC_8MHZ);
 *   mcp2515_frame_t frame = {.id=0x123, .dlc=4, .data={1,2,3,4}};
 *   mcp2515_send(&can, &frame);
 */
#ifndef KERF_DRIVERS_MCP2515_H
#define KERF_DRIVERS_MCP2515_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * SPI instructions
 * ---------------------------------------------------------------------- */
#define MCP2515_INSTR_RESET       0xC0
#define MCP2515_INSTR_READ        0x03
#define MCP2515_INSTR_WRITE       0x02
#define MCP2515_INSTR_BIT_MODIFY  0x05
#define MCP2515_INSTR_LOAD_TX0    0x40
#define MCP2515_INSTR_LOAD_TX1    0x42
#define MCP2515_INSTR_LOAD_TX2    0x44
#define MCP2515_INSTR_RTS_TX0     0x81
#define MCP2515_INSTR_RTS_TX1     0x82
#define MCP2515_INSTR_RTS_TX2     0x84
#define MCP2515_INSTR_READ_RX0    0x90
#define MCP2515_INSTR_READ_RX1    0x94
#define MCP2515_INSTR_READ_STATUS 0xA0
#define MCP2515_INSTR_RX_STATUS   0xB0

/* -------------------------------------------------------------------------
 * Key registers
 * ---------------------------------------------------------------------- */
#define MCP2515_REG_CANCTRL       0x0F
#define MCP2515_REG_CANSTAT       0x0E
#define MCP2515_REG_CNF1          0x2A
#define MCP2515_REG_CNF2          0x29
#define MCP2515_REG_CNF3          0x28
#define MCP2515_REG_CANINTE       0x2B
#define MCP2515_REG_CANINTF       0x2C
#define MCP2515_REG_EFLG          0x2D
#define MCP2515_REG_TXB0CTRL      0x30
#define MCP2515_REG_TXB0SIDH      0x31
#define MCP2515_REG_TXB0SIDL      0x32
#define MCP2515_REG_TXB0DLC       0x35
#define MCP2515_REG_TXB0D0        0x36
#define MCP2515_REG_RXB0CTRL      0x60
#define MCP2515_REG_RXB0SIDH      0x61

/* CANCTRL mode bits */
#define MCP2515_MODE_NORMAL       0x00
#define MCP2515_MODE_SLEEP        0x20
#define MCP2515_MODE_LOOPBACK     0x40
#define MCP2515_MODE_LISTENONLY   0x60
#define MCP2515_MODE_CONFIG       0x80
#define MCP2515_MODE_MASK         0xE0

/* -------------------------------------------------------------------------
 * Bit timing presets (CNF1/CNF2/CNF3 for 8 MHz crystal)
 * ---------------------------------------------------------------------- */
#define MCP2515_SPEED_1000KBPS  0
#define MCP2515_SPEED_500KBPS   1
#define MCP2515_SPEED_250KBPS   2
#define MCP2515_SPEED_125KBPS   3
#define MCP2515_SPEED_100KBPS   4

#define MCP2515_OSC_8MHZ        8
#define MCP2515_OSC_16MHZ       16

/* -------------------------------------------------------------------------
 * CAN frame
 * ---------------------------------------------------------------------- */
typedef struct {
    uint32_t id;        /**< 11-bit (standard) or 29-bit (extended) ID */
    uint8_t  extended;  /**< 1 = extended 29-bit ID, 0 = standard 11-bit */
    uint8_t  rtr;       /**< 1 = remote frame */
    uint8_t  dlc;       /**< Data length code (0–8) */
    uint8_t  data[8];   /**< Payload */
} mcp2515_frame_t;

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t spi_bus;    /**< SPI bus index */
    uint8_t pin_cs;     /**< Chip select GPIO (active LOW) */
    uint8_t pin_int;    /**< Interrupt GPIO (optional, active LOW) */
    uint8_t speed;      /**< MCP2515_SPEED_* constant */
    uint8_t osc_mhz;    /**< Crystal frequency (8 or 16) */
} mcp2515_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define MCP2515_OK              0
#define MCP2515_ERR_COMM       -1
#define MCP2515_ERR_TIMEOUT    -2
#define MCP2515_ERR_NULL       -3
#define MCP2515_ERR_TXFULL     -4
#define MCP2515_ERR_NOFRAME    -5

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * mcp2515_init — Reset the MCP2515, configure bit timing, enter normal mode.
 *
 * @param dev      Device handle.
 * @param spi_bus  SPI peripheral index.
 * @param pin_cs   Chip-select GPIO.
 * @param speed    MCP2515_SPEED_* constant.
 * @param osc_mhz  Crystal in MHz (8 or 16).
 */
int mcp2515_init(mcp2515_t *dev, uint8_t spi_bus, uint8_t pin_cs,
                 uint8_t speed, uint8_t osc_mhz);

/**
 * mcp2515_send — Send a CAN frame via TX buffer 0.
 * Blocks until the frame is sent or times out (~10 ms).
 */
int mcp2515_send(mcp2515_t *dev, const mcp2515_frame_t *frame);

/**
 * mcp2515_recv — Receive a CAN frame from RX buffer 0 or 1.
 * Returns MCP2515_ERR_NOFRAME if no frame is waiting.
 */
int mcp2515_recv(mcp2515_t *dev, mcp2515_frame_t *frame);

/**
 * mcp2515_set_filter — Configure an acceptance filter.
 *
 * @param filter_n  Filter index 0–5.
 * @param id        Filter ID.
 * @param mask      Acceptance mask (1 = must match, 0 = don't care).
 * @param extended  1 for 29-bit IDs.
 */
int mcp2515_set_filter(mcp2515_t *dev, uint8_t filter_n,
                       uint32_t id, uint32_t mask, uint8_t extended);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_MCP2515_H */
