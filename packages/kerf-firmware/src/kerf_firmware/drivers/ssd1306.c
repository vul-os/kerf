/**
 * ssd1306.c — Driver for Solomon SSD1306 128×64 OLED controller
 *
 * Protocol : I2C
 * Pins     : SDA (configurable), SCL (configurable)
 *
 * Implements ssd1306.h. I2C co-byte: 0x00 = command, 0x40 = data.
 */
#include "ssd1306.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* ---------------------------------------------------------------------------
 * I2C HAL shims (same interface as bme280 / mpu6050)
 * ---------------------------------------------------------------------- */
#ifndef KERF_I2C_HAL_PROVIDED

__attribute__((weak))
int kerf_i2c_write(uint8_t bus, uint8_t addr, const uint8_t *data, uint8_t len) {
    (void)bus; (void)addr; (void)data; (void)len; return -1;
}

__attribute__((weak))
int kerf_i2c_read(uint8_t bus, uint8_t addr, uint8_t reg,
                  uint8_t *buf, uint8_t len) {
    (void)bus; (void)addr; (void)reg; (void)buf; (void)len; return -1;
}

#endif

/* ---------------------------------------------------------------------------
 * Internal helpers
 * ---------------------------------------------------------------------- */

/* Send a single command byte */
static int _cmd(const ssd1306_t *dev, uint8_t cmd) {
    uint8_t buf[2] = {0x00, cmd}; /* co-byte 0x00 = command stream */
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 2);
}

/* Send two-byte command */
static int _cmd2(const ssd1306_t *dev, uint8_t c1, uint8_t c2) {
    uint8_t buf[3] = {0x00, c1, c2};
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 3);
}

/* ---------------------------------------------------------------------------
 * Initialisation sequence (Solomon SSD1306 application note)
 * ---------------------------------------------------------------------- */
int ssd1306_init(ssd1306_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl) {
    if (!dev) return SSD1306_ERR_NULL;
    dev->i2c_addr = addr;
    dev->i2c_bus  = i2c_bus;
    dev->pin_sda  = pin_sda;
    dev->pin_scl  = pin_scl;
    memset(dev->buf, 0, sizeof(dev->buf));

    int rc = 0;
    rc |= _cmd(dev, SSD1306_CMD_DISPLAY_OFF);
    rc |= _cmd2(dev, SSD1306_CMD_CLK_DIVIDER,   0x80);
    rc |= _cmd2(dev, SSD1306_CMD_MULTIPLEX,      0x3F); /* 64 MUX */
    rc |= _cmd2(dev, SSD1306_CMD_DISPLAY_OFFSET, 0x00);
    rc |= _cmd(dev, SSD1306_CMD_SET_START_LINE | 0x00);
    rc |= _cmd2(dev, SSD1306_CMD_CHARGE_PUMP,    0x14); /* enable internal VCC */
    rc |= _cmd2(dev, SSD1306_CMD_MEM_ADDR_MODE,  0x00); /* horizontal */
    rc |= _cmd(dev, SSD1306_CMD_SEGMENT_REMAP | 0x01);
    rc |= _cmd(dev, SSD1306_CMD_COM_OUTPUT_DIR | 0x08);
    rc |= _cmd2(dev, SSD1306_CMD_COM_PIN_CFG,    0x12);
    rc |= _cmd2(dev, SSD1306_CMD_SET_CONTRAST,   0xCF);
    rc |= _cmd2(dev, SSD1306_CMD_PRECHARGE,      0xF1);
    rc |= _cmd2(dev, SSD1306_CMD_VCOM_DESELECT,  0x40);
    rc |= _cmd(dev, SSD1306_CMD_ENTIRE_RESUME);
    rc |= _cmd(dev, SSD1306_CMD_INVERT_OFF);
    rc |= _cmd(dev, SSD1306_CMD_DISPLAY_ON);

    return rc ? SSD1306_ERR_COMM : SSD1306_OK;
}

void ssd1306_clear(ssd1306_t *dev) {
    if (!dev) return;
    memset(dev->buf, 0x00, sizeof(dev->buf));
}

void ssd1306_fill(ssd1306_t *dev) {
    if (!dev) return;
    memset(dev->buf, 0xFF, sizeof(dev->buf));
}

void ssd1306_draw_pixel(ssd1306_t *dev, uint8_t x, uint8_t y, uint8_t on) {
    if (!dev || x >= SSD1306_WIDTH || y >= SSD1306_HEIGHT) return;
    uint16_t byte_idx = (uint16_t)x + (uint16_t)(y / 8) * SSD1306_WIDTH;
    uint8_t bit_mask  = (uint8_t)(1 << (y % 8));
    if (on) dev->buf[byte_idx] |=  bit_mask;
    else    dev->buf[byte_idx] &= ~bit_mask;
}

int ssd1306_display(ssd1306_t *dev) {
    if (!dev) return SSD1306_ERR_NULL;

    /* Set column address: 0–127 */
    _cmd(dev, SSD1306_CMD_COL_ADDR);
    _cmd(dev, 0x00);
    _cmd(dev, SSD1306_WIDTH - 1);

    /* Set page address: 0–7 */
    _cmd(dev, SSD1306_CMD_PAGE_ADDR);
    _cmd(dev, 0x00);
    _cmd(dev, SSD1306_PAGES - 1);

    /* Send all 1024 bytes in 16-byte chunks (I2C payload = co-byte + 16 bytes) */
    uint8_t chunk[17];
    chunk[0] = 0x40; /* co-byte: data stream */
    for (uint16_t i = 0; i < SSD1306_BUF_SZ; i += 16) {
        uint8_t n = (SSD1306_BUF_SZ - i < 16) ? (uint8_t)(SSD1306_BUF_SZ - i) : 16;
        memcpy(chunk + 1, dev->buf + i, n);
        if (kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, chunk, n + 1) != 0)
            return SSD1306_ERR_COMM;
    }
    return SSD1306_OK;
}

int ssd1306_set_contrast(ssd1306_t *dev, uint8_t contrast) {
    if (!dev) return SSD1306_ERR_NULL;
    return _cmd2(dev, SSD1306_CMD_SET_CONTRAST, contrast) ? SSD1306_ERR_COMM : SSD1306_OK;
}

int ssd1306_set_display_on(ssd1306_t *dev, uint8_t on) {
    if (!dev) return SSD1306_ERR_NULL;
    uint8_t cmd = on ? SSD1306_CMD_DISPLAY_ON : SSD1306_CMD_DISPLAY_OFF;
    return _cmd(dev, cmd) ? SSD1306_ERR_COMM : SSD1306_OK;
}
