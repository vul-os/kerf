/**
 * pca9685.c — Driver for NXP PCA9685 16-channel 12-bit PWM controller
 *
 * Protocol : I2C
 * Pins     : SDA (configurable), SCL (configurable)
 *
 * Implements pca9685.h.
 */
#include "pca9685.h"

#include <stddef.h>
#include <stdint.h>

/* ---------------------------------------------------------------------------
 * I2C HAL shims
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

__attribute__((weak))
void kerf_delay_ms(uint32_t ms) { (void)ms; }

#endif

/* ---------------------------------------------------------------------------
 * Helpers
 * ---------------------------------------------------------------------- */
static int _write8(const pca9685_t *dev, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = {reg, val};
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 2);
}

static int _read8(const pca9685_t *dev, uint8_t reg, uint8_t *val) {
    return kerf_i2c_read(dev->i2c_bus, dev->i2c_addr, reg, val, 1);
}

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int pca9685_init(pca9685_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl) {
    if (!dev) return PCA9685_ERR_NULL;
    dev->i2c_addr  = addr;
    dev->i2c_bus   = i2c_bus;
    dev->pin_sda   = pin_sda;
    dev->pin_scl   = pin_scl;
    dev->period_us = 20000.0f; /* default 50 Hz */

    /* Software reset (write 0x06 to general call address 0x00) */
    uint8_t rst[2] = {0x00, 0x06};
    kerf_i2c_write(dev->i2c_bus, 0x00, rst, 2);
    kerf_delay_ms(10);

    /* Enable auto-increment, clear sleep bit */
    if (_write8(dev, PCA9685_REG_MODE1,
                PCA9685_MODE1_AI | PCA9685_MODE1_ALLCALL) != 0)
        return PCA9685_ERR_COMM;

    /* Totem-pole outputs */
    if (_write8(dev, PCA9685_REG_MODE2, PCA9685_MODE2_OUTDRV) != 0)
        return PCA9685_ERR_COMM;

    kerf_delay_ms(1);
    return PCA9685_OK;
}

int pca9685_set_freq(pca9685_t *dev, float freq_hz) {
    if (!dev) return PCA9685_ERR_NULL;
    if (freq_hz < 24.0f || freq_hz > 1526.0f) return PCA9685_ERR_RANGE;

    /* Prescaler = round(25 MHz / (4096 × freq)) − 1 */
    float prescale_f = (float)PCA9685_INTERNAL_OSC_HZ / (4096.0f * freq_hz) - 1.0f;
    uint8_t prescale = (uint8_t)(prescale_f + 0.5f);

    /* Must be in sleep mode to write prescaler */
    uint8_t mode1;
    if (_read8(dev, PCA9685_REG_MODE1, &mode1) != 0) return PCA9685_ERR_COMM;
    uint8_t sleep_mode = (mode1 & ~PCA9685_MODE1_RESTART) | PCA9685_MODE1_SLEEP;
    _write8(dev, PCA9685_REG_MODE1, sleep_mode);
    _write8(dev, PCA9685_REG_PRESCALE, prescale);
    _write8(dev, PCA9685_REG_MODE1, mode1);
    kerf_delay_ms(1);
    /* Restart */
    _write8(dev, PCA9685_REG_MODE1, mode1 | PCA9685_MODE1_RESTART);

    dev->period_us = 1000000.0f / freq_hz;
    return PCA9685_OK;
}

int pca9685_set_channel(pca9685_t *dev, uint8_t channel,
                        uint16_t on_tick, uint16_t off_tick) {
    if (!dev) return PCA9685_ERR_NULL;
    if (channel >= PCA9685_CHANNELS) return PCA9685_ERR_RANGE;

    uint8_t base = (uint8_t)(PCA9685_REG_LED0_ON_L + 4 * channel);
    uint8_t buf[5] = {
        base,
        (uint8_t)(on_tick  & 0xFF),
        (uint8_t)(on_tick  >> 8),
        (uint8_t)(off_tick & 0xFF),
        (uint8_t)(off_tick >> 8),
    };
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 5) ? PCA9685_ERR_COMM : PCA9685_OK;
}

int pca9685_set_channel_duty(pca9685_t *dev, uint8_t channel, float duty_pct) {
    if (!dev) return PCA9685_ERR_NULL;
    if (duty_pct < 0.0f) duty_pct = 0.0f;
    if (duty_pct > 100.0f) duty_pct = 100.0f;

    if (duty_pct == 0.0f)   return pca9685_set_channel(dev, channel, 0, 4096);
    if (duty_pct == 100.0f) return pca9685_set_channel(dev, channel, 4096, 0);

    uint16_t off = (uint16_t)(duty_pct / 100.0f * 4096.0f);
    return pca9685_set_channel(dev, channel, 0, off);
}

int pca9685_set_channel_us(pca9685_t *dev, uint8_t channel, float pulse_us) {
    if (!dev) return PCA9685_ERR_NULL;
    if (dev->period_us <= 0.0f) return PCA9685_ERR_RANGE;
    float duty = (pulse_us / dev->period_us) * 100.0f;
    return pca9685_set_channel_duty(dev, channel, duty);
}

int pca9685_all_off(pca9685_t *dev) {
    if (!dev) return PCA9685_ERR_NULL;
    uint8_t buf[5] = {PCA9685_REG_ALL_LED_ON_L, 0x00, 0x00, 0x00, 0x10};
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 5) ? PCA9685_ERR_COMM : PCA9685_OK;
}

int pca9685_sleep(pca9685_t *dev) {
    if (!dev) return PCA9685_ERR_NULL;
    uint8_t mode1;
    if (_read8(dev, PCA9685_REG_MODE1, &mode1) != 0) return PCA9685_ERR_COMM;
    return _write8(dev, PCA9685_REG_MODE1, mode1 | PCA9685_MODE1_SLEEP) ? PCA9685_ERR_COMM : PCA9685_OK;
}

int pca9685_wake(pca9685_t *dev) {
    if (!dev) return PCA9685_ERR_NULL;
    uint8_t mode1;
    if (_read8(dev, PCA9685_REG_MODE1, &mode1) != 0) return PCA9685_ERR_COMM;
    mode1 &= ~PCA9685_MODE1_SLEEP;
    _write8(dev, PCA9685_REG_MODE1, mode1);
    kerf_delay_ms(1);
    return _write8(dev, PCA9685_REG_MODE1, mode1 | PCA9685_MODE1_RESTART) ? PCA9685_ERR_COMM : PCA9685_OK;
}
