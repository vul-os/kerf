/**
 * vl53l0x.c — Driver for ST VL53L0X time-of-flight distance sensor
 *
 * Protocol : I2C
 * Pins     : SDA (configurable), SCL (configurable)
 *
 * Implements vl53l0x.h. The initialisation sequence follows ST's
 * VL53L0X API application note AN4907.
 */
#include "vl53l0x.h"

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
uint32_t kerf_millis(void) { return 0; }

#endif

/* ---------------------------------------------------------------------------
 * Register helpers
 * ---------------------------------------------------------------------- */
static int _write8(const vl53l0x_t *dev, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = {reg, val};
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 2);
}

static int _write16(const vl53l0x_t *dev, uint8_t reg, uint16_t val) {
    uint8_t buf[3] = {reg, (uint8_t)(val >> 8), (uint8_t)(val & 0xFF)};
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 3);
}

static int _read8(const vl53l0x_t *dev, uint8_t reg, uint8_t *val) {
    return kerf_i2c_read(dev->i2c_bus, dev->i2c_addr, reg, val, 1);
}

static int _read16(const vl53l0x_t *dev, uint8_t reg, uint16_t *val) {
    uint8_t buf[2];
    int rc = kerf_i2c_read(dev->i2c_bus, dev->i2c_addr, reg, buf, 2);
    if (rc == 0) *val = (uint16_t)((buf[0] << 8) | buf[1]);
    return rc;
}

/* ---------------------------------------------------------------------------
 * Initialisation (abbreviated ST API sequence)
 * ---------------------------------------------------------------------- */
int vl53l0x_init(vl53l0x_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl) {
    if (!dev) return VL53L0X_ERR_NULL;
    dev->i2c_addr         = addr;
    dev->i2c_bus          = i2c_bus;
    dev->pin_sda          = pin_sda;
    dev->pin_scl          = pin_scl;
    dev->timing_budget_us = 33000;

    /* Verify model ID */
    uint8_t id = 0;
    if (_read8(dev, VL53L0X_REG_IDENTIFICATION_MODEL_ID, &id) != 0) return VL53L0X_ERR_COMM;
    if (id != VL53L0X_MODEL_ID) return VL53L0X_ERR_ID;

    /* Set 2.8 V I2C mode */
    _write8(dev, 0x88, 0x00);
    _write8(dev, 0x80, 0x01);
    _write8(dev, 0xFF, 0x01);
    _write8(dev, 0x00, 0x00);

    /* Read stop variable for later use in single-shot ranging */
    uint8_t sv;
    _read8(dev, 0x91, &sv);
    dev->stop_variable = sv;

    _write8(dev, 0x00, 0x01);
    _write8(dev, 0xFF, 0x00);
    _write8(dev, 0x80, 0x00);

    /* Disable SIGNAL_RATE_MSRC and SIGNAL_RATE_PRE_RANGE limit checks */
    uint8_t config;
    _read8(dev, 0x60, &config);
    _write8(dev, 0x60, config | 0x12);

    /* Set signal rate limit to 0.25 MCPS (Q9.7 format) */
    _write16(dev, 0x44, 32);

    /* Enable LIMIT_CHECK_SIGMA */
    _write8(dev, 0x24, 0x01);

    return VL53L0X_OK;
}

int vl53l0x_set_address(vl53l0x_t *dev, uint8_t new_addr) {
    if (!dev) return VL53L0X_ERR_NULL;
    if (_write8(dev, 0x8A, new_addr & 0x7F) != 0) return VL53L0X_ERR_COMM;
    dev->i2c_addr = new_addr;
    return VL53L0X_OK;
}

int vl53l0x_set_timing_budget_us(vl53l0x_t *dev, uint32_t budget_us) {
    if (!dev) return VL53L0X_ERR_NULL;
    dev->timing_budget_us = budget_us;
    /* Full implementation requires reading current sequence steps and computing
     * VCSEL pulse periods — abbreviated here. */
    return VL53L0X_OK;
}

int vl53l0x_read_range_mm(vl53l0x_t *dev, uint16_t *range_mm) {
    if (!dev || !range_mm) return VL53L0X_ERR_NULL;

    /* Trigger single-shot measurement */
    _write8(dev, 0x80, 0x01);
    _write8(dev, 0xFF, 0x01);
    _write8(dev, 0x00, 0x00);
    _write8(dev, 0x91, dev->stop_variable);
    _write8(dev, 0x00, 0x01);
    _write8(dev, 0xFF, 0x00);
    _write8(dev, 0x80, 0x00);
    _write8(dev, VL53L0X_REG_SYSRANGE_START, 0x01);

    /* Wait for measurement bit to clear */
    uint8_t sysrange;
    uint32_t t0 = kerf_millis();
    do {
        if (kerf_millis() - t0 > 500) return VL53L0X_ERR_TIMEOUT;
        if (_read8(dev, VL53L0X_REG_SYSRANGE_START, &sysrange) != 0)
            return VL53L0X_ERR_COMM;
    } while (sysrange & 0x01);

    /* Wait for data ready */
    uint8_t irq;
    t0 = kerf_millis();
    do {
        if (kerf_millis() - t0 > 500) return VL53L0X_ERR_TIMEOUT;
        if (_read8(dev, VL53L0X_REG_RESULT_INTERRUPT_STATUS, &irq) != 0)
            return VL53L0X_ERR_COMM;
    } while ((irq & 0x07) == 0);

    /* Read result (register pair 0x1E/0x1F) */
    if (_read16(dev, VL53L0X_REG_RESULT_RANGE_MM, range_mm) != 0)
        return VL53L0X_ERR_COMM;

    /* Clear interrupt */
    _write8(dev, VL53L0X_REG_SYSTEM_INTERRUPT_CLEAR, 0x01);

    return VL53L0X_OK;
}

int vl53l0x_start_continuous(vl53l0x_t *dev, uint32_t period_ms) {
    if (!dev) return VL53L0X_ERR_NULL;
    _write8(dev, 0x80, 0x01);
    _write8(dev, 0xFF, 0x01);
    _write8(dev, 0x00, 0x00);
    _write8(dev, 0x91, dev->stop_variable);
    _write8(dev, 0x00, 0x01);
    _write8(dev, 0xFF, 0x00);
    _write8(dev, 0x80, 0x00);
    if (period_ms != 0) {
        /* Timed mode */
        uint16_t osc_rate;
        _read16(dev, VL53L0X_REG_OSC_CALIBRATE_VAL, &osc_rate);
        if (osc_rate) period_ms *= osc_rate;
        _write16(dev, 0x04, (uint16_t)period_ms);
        _write8(dev, VL53L0X_REG_SYSRANGE_START, VL53L0X_MODE_TIMED | 0x02);
    } else {
        _write8(dev, VL53L0X_REG_SYSRANGE_START, VL53L0X_MODE_CONTINUOUS | 0x02);
    }
    return VL53L0X_OK;
}

int vl53l0x_stop_continuous(vl53l0x_t *dev) {
    if (!dev) return VL53L0X_ERR_NULL;
    _write8(dev, VL53L0X_REG_SYSRANGE_START, 0x01);
    _write8(dev, 0xFF, 0x01);
    _write8(dev, 0x00, 0x00);
    _write8(dev, 0x91, 0x00);
    _write8(dev, 0x00, 0x01);
    _write8(dev, 0xFF, 0x00);
    return VL53L0X_OK;
}

int vl53l0x_read_range_continuous_mm(vl53l0x_t *dev, uint16_t *range_mm) {
    if (!dev || !range_mm) return VL53L0X_ERR_NULL;
    uint8_t irq;
    uint32_t t0 = kerf_millis();
    do {
        if (kerf_millis() - t0 > 100) return VL53L0X_ERR_TIMEOUT;
        if (_read8(dev, VL53L0X_REG_RESULT_INTERRUPT_STATUS, &irq) != 0)
            return VL53L0X_ERR_COMM;
    } while ((irq & 0x07) == 0);

    if (_read16(dev, VL53L0X_REG_RESULT_RANGE_MM, range_mm) != 0)
        return VL53L0X_ERR_COMM;

    _write8(dev, VL53L0X_REG_SYSTEM_INTERRUPT_CLEAR, 0x01);
    return VL53L0X_OK;
}
