/**
 * mfrc522.c — Driver for NXP MFRC522 SPI RFID reader/writer
 *
 * Protocol : SPI (Mode 0, 10 MHz max)
 * Pins     : SPI bus + CS (active LOW) + RST (active LOW)
 *
 * Implements mfrc522.h. SPI read byte: set bit 7 (0x80). Write: clear bit 7.
 */
#include "mfrc522.h"

#include <stddef.h>
#include <stdint.h>

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
void kerf_gpio_write(uint8_t pin, uint8_t val) { (void)pin; (void)val; }

__attribute__((weak))
void kerf_delay_ms(uint32_t ms) { (void)ms; }

#endif

/* ---------------------------------------------------------------------------
 * Register I/O
 * ---------------------------------------------------------------------- */
static void _write_reg(const mfrc522_t *dev, uint8_t reg, uint8_t val) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, (reg << 1) & 0x7E);    /* write: bit 7=0 */
    kerf_spi_transfer(dev->spi_bus, val);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
}

static uint8_t _read_reg(const mfrc522_t *dev, uint8_t reg) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, ((reg << 1) & 0x7E) | 0x80); /* read: bit 7=1 */
    uint8_t val = kerf_spi_transfer(dev->spi_bus, 0x00);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
    return val;
}

static void _set_bits(const mfrc522_t *dev, uint8_t reg, uint8_t mask) {
    _write_reg(dev, reg, _read_reg(dev, reg) | mask);
}

static void _clr_bits(const mfrc522_t *dev, uint8_t reg, uint8_t mask) {
    _write_reg(dev, reg, _read_reg(dev, reg) & (~mask));
}

/* Write N bytes to FIFO */
static void _write_fifo(const mfrc522_t *dev, const uint8_t *data, uint8_t len) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, (MFRC522_REG_FIFO_DATA << 1) & 0x7E);
    for (uint8_t i = 0; i < len; i++)
        kerf_spi_transfer(dev->spi_bus, data[i]);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
}

/* Read N bytes from FIFO */
static void _read_fifo(const mfrc522_t *dev, uint8_t *buf, uint8_t len) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    kerf_spi_transfer(dev->spi_bus, ((MFRC522_REG_FIFO_DATA << 1) & 0x7E) | 0x80);
    for (uint8_t i = 0; i < len; i++)
        buf[i] = kerf_spi_transfer(dev->spi_bus, 0x00);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
}

/* ---------------------------------------------------------------------------
 * Transceive: send bytes, receive response via IRQ polling
 * ---------------------------------------------------------------------- */
static int _transceive(const mfrc522_t *dev,
                       const uint8_t *tx, uint8_t tx_len,
                       uint8_t *rx, uint8_t *rx_len,
                       uint8_t last_bits) {
    /* Prepare */
    _write_reg(dev, MFRC522_REG_COM_I_EN, 0x77);   /* IRQ enables */
    _write_reg(dev, MFRC522_REG_COM_IRQ,  0x7F);   /* clear IRQs */
    _set_bits(dev,  MFRC522_REG_FIFO_LEVEL, 0x80); /* flush FIFO */
    _write_reg(dev, MFRC522_REG_COMMAND, MFRC522_CMD_IDLE);

    _write_fifo(dev, tx, tx_len);
    _write_reg(dev, MFRC522_REG_BIT_FRAMING, last_bits);
    _write_reg(dev, MFRC522_REG_COMMAND, MFRC522_CMD_TRANSCEIVE);
    _set_bits(dev, MFRC522_REG_BIT_FRAMING, 0x80); /* StartSend */

    /* Poll for completion (25 ms timeout) */
    uint16_t i = 2500;
    uint8_t irq;
    do {
        irq = _read_reg(dev, MFRC522_REG_COM_IRQ);
        i--;
    } while (i && !(irq & 0x01) && !(irq & 0x30));

    _clr_bits(dev, MFRC522_REG_BIT_FRAMING, 0x80);

    if (!i) return MFRC522_ERR_TIMEOUT;
    if (_read_reg(dev, MFRC522_REG_ERROR) & 0x13) return MFRC522_ERR_COMM;

    if (rx && rx_len) {
        uint8_t n = _read_reg(dev, MFRC522_REG_FIFO_LEVEL);
        if (n > *rx_len) n = *rx_len;
        *rx_len = n;
        _read_fifo(dev, rx, n);
    }
    return MFRC522_OK;
}

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int mfrc522_init(mfrc522_t *dev, uint8_t spi_bus, uint8_t pin_cs, uint8_t pin_rst) {
    if (!dev) return MFRC522_ERR_NULL;
    dev->spi_bus = spi_bus;
    dev->pin_cs  = pin_cs;
    dev->pin_rst = pin_rst;

    /* Hardware reset */
    kerf_gpio_write(pin_rst, 0);
    kerf_delay_ms(10);
    kerf_gpio_write(pin_rst, 1);
    kerf_delay_ms(50);

    /* Soft reset */
    _write_reg(dev, MFRC522_REG_COMMAND, MFRC522_CMD_SOFT_RESET);
    kerf_delay_ms(50);

    /* Configure timer: 25 ms auto-timeout */
    _write_reg(dev, MFRC522_REG_T_MODE,       0x80);
    _write_reg(dev, MFRC522_REG_T_PRESCALER,  0xA9);
    _write_reg(dev, MFRC522_REG_T_RELOAD_H,   0x03);
    _write_reg(dev, MFRC522_REG_T_RELOAD_L,   0xE8);
    _write_reg(dev, MFRC522_REG_TX_ASK,       0x40); /* 100% ASK modulation */
    _write_reg(dev, MFRC522_REG_MODE,         0x3D); /* CRC preset 6363 */

    /* Turn on antenna */
    _set_bits(dev, MFRC522_REG_TX_CONTROL, 0x03);

    return MFRC522_OK;
}

int mfrc522_is_card_present(mfrc522_t *dev) {
    if (!dev) return 0;
    uint8_t buf[2];
    uint8_t len = 2;
    uint8_t req = PICC_CMD_REQA;
    _write_reg(dev, MFRC522_REG_BIT_FRAMING, 0x07); /* 7 bits */
    return _transceive(dev, &req, 1, buf, &len, 0x07) == MFRC522_OK;
}

int mfrc522_read_uid(mfrc522_t *dev, uint8_t *uid, uint8_t *uid_len) {
    if (!dev || !uid || !uid_len) return MFRC522_ERR_NULL;

    /* REQA */
    if (!mfrc522_is_card_present(dev)) return MFRC522_ERR_NO_CARD;

    /* Anticollision CL1 */
    uint8_t cmd[2] = {PICC_CMD_SEL_CL1, 0x20};
    uint8_t rx[5];
    uint8_t rx_len = 5;
    int rc = _transceive(dev, cmd, 2, rx, &rx_len, 0);
    if (rc != MFRC522_OK) return rc;

    /* SELECT CL1 */
    uint8_t sel[9] = {PICC_CMD_SEL_CL1, 0x70, rx[0], rx[1], rx[2], rx[3], rx[4], 0, 0};
    /* CRC is added by the chip; use CalcCRC command (simplified: skip CRC for now) */
    uint8_t sel_rx[3];
    uint8_t sel_len = 3;
    rc = _transceive(dev, sel, 7, sel_rx, &sel_len, 0);
    if (rc != MFRC522_OK) return rc;

    /* Copy UID bytes (skip CT tag if present) */
    uint8_t off = (rx[0] == PICC_CMD_CT) ? 1 : 0;
    uint8_t n = 4 - off;
    for (uint8_t i = 0; i < n; i++)
        uid[i] = rx[i + off];
    *uid_len = n;

    return MFRC522_OK;
}

int mfrc522_halt(mfrc522_t *dev) {
    if (!dev) return MFRC522_ERR_NULL;
    uint8_t cmd[4] = {PICC_CMD_HLTA, 0, 0, 0};
    _transceive(dev, cmd, 4, NULL, NULL, 0);
    return MFRC522_OK;
}

uint8_t mfrc522_version(mfrc522_t *dev) {
    if (!dev) return 0;
    return _read_reg(dev, MFRC522_REG_VERSION);
}
