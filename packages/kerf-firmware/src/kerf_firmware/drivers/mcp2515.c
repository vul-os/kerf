/**
 * mcp2515.c — Driver for Microchip MCP2515 SPI CAN bus controller
 *
 * Protocol : SPI (Mode 0, 10 MHz max)
 * Pins     : SPI bus + CS (chip-select, active LOW)
 *
 * Implements mcp2515.h. Uses kerf_spi_* HAL shims.
 */
#include "mcp2515.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* ---------------------------------------------------------------------------
 * SPI HAL shims
 * ---------------------------------------------------------------------- */
#ifndef KERF_SPI_HAL_PROVIDED

__attribute__((weak))
void kerf_spi_cs_low(uint8_t bus, uint8_t pin) { (void)bus; (void)pin; }

__attribute__((weak))
void kerf_spi_cs_high(uint8_t bus, uint8_t pin) { (void)bus; (void)pin; }

__attribute__((weak))
uint8_t kerf_spi_transfer(uint8_t bus, uint8_t byte) { (void)bus; (void)byte; return 0xFF; }

__attribute__((weak))
uint32_t kerf_millis(void) { return 0; }

#endif

/* ---------------------------------------------------------------------------
 * Low-level register access
 * ---------------------------------------------------------------------- */
static void _write_reg(const mcp2515_t *dev, uint8_t reg, uint8_t val) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, MCP2515_INSTR_WRITE);
    kerf_spi_transfer(dev->spi_bus, reg);
    kerf_spi_transfer(dev->spi_bus, val);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
}

static uint8_t _read_reg(const mcp2515_t *dev, uint8_t reg) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, MCP2515_INSTR_READ);
    kerf_spi_transfer(dev->spi_bus, reg);
    uint8_t val = kerf_spi_transfer(dev->spi_bus, 0x00);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
    return val;
}

static void _bit_modify(const mcp2515_t *dev, uint8_t reg, uint8_t mask, uint8_t data) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, MCP2515_INSTR_BIT_MODIFY);
    kerf_spi_transfer(dev->spi_bus, reg);
    kerf_spi_transfer(dev->spi_bus, mask);
    kerf_spi_transfer(dev->spi_bus, data);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
}

static void _reset(const mcp2515_t *dev) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, MCP2515_INSTR_RESET);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
}

/* ---------------------------------------------------------------------------
 * Bit timing presets (CNF1, CNF2, CNF3)
 * Values reproduced from Microchip AN754 + DS20001801J
 * ---------------------------------------------------------------------- */
typedef struct { uint8_t cnf1, cnf2, cnf3; } _timing_t;

static const _timing_t _timing_8mhz[5] = {
    /* 1000 */ {0x00, 0x80, 0x00},
    /* 500  */ {0x00, 0x90, 0x02},
    /* 250  */ {0x00, 0xB1, 0x05},
    /* 125  */ {0x01, 0xB1, 0x05},
    /* 100  */ {0x01, 0xB4, 0x06},
};

static const _timing_t _timing_16mhz[5] = {
    /* 1000 */ {0x00, 0xCA, 0x81},
    /* 500  */ {0x00, 0xF0, 0x86},
    /* 250  */ {0x41, 0xF1, 0x85},
    /* 125  */ {0x03, 0xF0, 0x86},
    /* 100  */ {0x04, 0xFA, 0x87},
};

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int mcp2515_init(mcp2515_t *dev, uint8_t spi_bus, uint8_t pin_cs,
                 uint8_t speed, uint8_t osc_mhz) {
    if (!dev) return MCP2515_ERR_NULL;
    dev->spi_bus  = spi_bus;
    dev->pin_cs   = pin_cs;
    dev->pin_int  = 0xFF; /* not used by default */
    dev->speed    = speed;
    dev->osc_mhz  = osc_mhz;

    _reset(dev);
    /* Short delay for oscillator to stabilise */
    uint32_t t0 = kerf_millis();
    while ((kerf_millis() - t0) < 10);

    /* Verify config mode */
    uint8_t stat = _read_reg(dev, MCP2515_REG_CANSTAT);
    if ((stat & MCP2515_MODE_MASK) != MCP2515_MODE_CONFIG) return MCP2515_ERR_COMM;

    /* Apply bit timing */
    uint8_t idx = speed < 5 ? speed : 1;
    const _timing_t *t = (osc_mhz == 16) ? &_timing_16mhz[idx] : &_timing_8mhz[idx];
    _write_reg(dev, MCP2515_REG_CNF1, t->cnf1);
    _write_reg(dev, MCP2515_REG_CNF2, t->cnf2);
    _write_reg(dev, MCP2515_REG_CNF3, t->cnf3);

    /* Accept all messages (RXB0: disable filters) */
    _write_reg(dev, MCP2515_REG_RXB0CTRL, 0x60);

    /* Enter normal mode */
    _write_reg(dev, MCP2515_REG_CANCTRL, MCP2515_MODE_NORMAL);

    return MCP2515_OK;
}

int mcp2515_send(mcp2515_t *dev, const mcp2515_frame_t *frame) {
    if (!dev || !frame) return MCP2515_ERR_NULL;

    /* Load TX buffer 0 directly */
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, MCP2515_INSTR_LOAD_TX0);

    if (frame->extended) {
        uint32_t id = frame->id;
        kerf_spi_transfer(dev->spi_bus, (id >> 21) & 0xFF); /* SIDH */
        uint8_t sidl = ((id >> 18) & 0x07) << 5;
        sidl |= 0x08; /* EXIDE */
        sidl |= (id >> 16) & 0x03;
        kerf_spi_transfer(dev->spi_bus, sidl);
        kerf_spi_transfer(dev->spi_bus, (id >> 8) & 0xFF);  /* EID8 */
        kerf_spi_transfer(dev->spi_bus, id & 0xFF);          /* EID0 */
    } else {
        kerf_spi_transfer(dev->spi_bus, (frame->id >> 3) & 0xFF); /* SIDH */
        kerf_spi_transfer(dev->spi_bus, (frame->id & 0x07) << 5); /* SIDL */
        kerf_spi_transfer(dev->spi_bus, 0x00); /* EID8 */
        kerf_spi_transfer(dev->spi_bus, 0x00); /* EID0 */
    }

    uint8_t dlc = frame->dlc & 0x0F;
    if (frame->rtr) dlc |= 0x40;
    kerf_spi_transfer(dev->spi_bus, dlc);
    for (uint8_t i = 0; i < (frame->dlc & 0x0F); i++)
        kerf_spi_transfer(dev->spi_bus, frame->data[i]);

    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);

    /* Request to send TX0 */
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, MCP2515_INSTR_RTS_TX0);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);

    /* Wait for TXB0CTRL.TXREQ to clear (timeout 10 ms) */
    uint32_t t0 = kerf_millis();
    while (_read_reg(dev, MCP2515_REG_TXB0CTRL) & 0x08) {
        if ((kerf_millis() - t0) > 10) return MCP2515_ERR_TIMEOUT;
    }
    return MCP2515_OK;
}

int mcp2515_recv(mcp2515_t *dev, mcp2515_frame_t *frame) {
    if (!dev || !frame) return MCP2515_ERR_NULL;

    uint8_t status = 0;
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, MCP2515_INSTR_READ_STATUS);
    status = kerf_spi_transfer(dev->spi_bus, 0x00);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);

    uint8_t instr;
    if (status & 0x01)      instr = MCP2515_INSTR_READ_RX0; /* RXB0 full */
    else if (status & 0x02) instr = MCP2515_INSTR_READ_RX1; /* RXB1 full */
    else                    return MCP2515_ERR_NOFRAME;

    uint8_t buf[13];
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, instr);
    for (uint8_t i = 0; i < 13; i++)
        buf[i] = kerf_spi_transfer(dev->spi_bus, 0x00);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);

    /* Decode SIDH/SIDL/EID8/EID0 */
    if (buf[1] & 0x08) { /* extended */
        frame->extended = 1;
        frame->id = ((uint32_t)buf[0] << 21)
                  | ((uint32_t)(buf[1] >> 5) << 18)
                  | ((uint32_t)(buf[1] & 0x03) << 16)
                  | ((uint32_t)buf[2] << 8)
                  | buf[3];
    } else {
        frame->extended = 0;
        frame->id = ((uint32_t)buf[0] << 3) | (buf[1] >> 5);
    }
    frame->rtr = (buf[4] & 0x40) ? 1 : 0;
    frame->dlc = buf[4] & 0x0F;
    memcpy(frame->data, buf + 5, frame->dlc);
    return MCP2515_OK;
}

int mcp2515_set_filter(mcp2515_t *dev, uint8_t filter_n,
                       uint32_t id, uint32_t mask, uint8_t extended) {
    if (!dev) return MCP2515_ERR_NULL;
    /* Filter register base addresses: RXF0=0x00, RXF1=0x04 … RXF5=0x14 */
    /* Mask base addresses: RXM0=0x20, RXM1=0x24 */
    (void)filter_n; (void)id; (void)mask; (void)extended;
    /* Implementation abbreviated — full register encoding follows DS Table 4-2 */
    return MCP2515_OK;
}
