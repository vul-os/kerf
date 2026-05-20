/**
 * bme280.c — Driver for Bosch BME280 temperature/humidity/pressure sensor
 *
 * Protocol : I2C
 * Pins     : SDA (configurable), SCL (configurable)
 *
 * This file implements the BME280 driver declared in bme280.h.
 * It is self-contained and depends only on the platform I2C HAL
 * (kerf_i2c_write / kerf_i2c_read provided by the board support package).
 *
 * Compensation formulas reproduced from Bosch BST-BME280-DS002 datasheet §4.2.3.
 */
#include "bme280.h"

#include <stddef.h>
#include <stdint.h>

/* ---------------------------------------------------------------------------
 * Platform HAL shim — replace with actual board I2C calls.
 * On FreeRTOS targets these should take the i2c_bus mutex before calling.
 * ---------------------------------------------------------------------- */
#ifndef KERF_I2C_HAL_PROVIDED

#include <string.h>

/* Weak stub implementations — always fail unless overridden by the BSP. */
__attribute__((weak))
int kerf_i2c_write(uint8_t bus, uint8_t addr, const uint8_t *data, uint8_t len) {
    (void)bus; (void)addr; (void)data; (void)len;
    return -1; /* not implemented */
}

__attribute__((weak))
int kerf_i2c_read(uint8_t bus, uint8_t addr, uint8_t reg,
                  uint8_t *buf, uint8_t len) {
    (void)bus; (void)addr; (void)reg; (void)buf; (void)len;
    return -1;
}

#endif /* KERF_I2C_HAL_PROVIDED */

/* ---------------------------------------------------------------------------
 * Internal helpers
 * ---------------------------------------------------------------------- */

static int _write_reg(const bme280_t *dev, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = {reg, val};
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 2);
}

static int _read_regs(const bme280_t *dev, uint8_t reg, uint8_t *buf, uint8_t len) {
    return kerf_i2c_read(dev->i2c_bus, dev->i2c_addr, reg, buf, len);
}

/* Load all calibration bytes from non-volatile register pages. */
static int _load_calib(bme280_t *dev) {
    uint8_t raw[26];
    if (_read_regs(dev, BME280_REG_CALIB00, raw, 24) != 0) return BME280_ERR_COMM;

    bme280_calib_t *c = &dev->calib;
    c->dig_T1 = (uint16_t)(raw[0]  | (raw[1]  << 8));
    c->dig_T2 = (int16_t) (raw[2]  | (raw[3]  << 8));
    c->dig_T3 = (int16_t) (raw[4]  | (raw[5]  << 8));
    c->dig_P1 = (uint16_t)(raw[6]  | (raw[7]  << 8));
    c->dig_P2 = (int16_t) (raw[8]  | (raw[9]  << 8));
    c->dig_P3 = (int16_t) (raw[10] | (raw[11] << 8));
    c->dig_P4 = (int16_t) (raw[12] | (raw[13] << 8));
    c->dig_P5 = (int16_t) (raw[14] | (raw[15] << 8));
    c->dig_P6 = (int16_t) (raw[16] | (raw[17] << 8));
    c->dig_P7 = (int16_t) (raw[18] | (raw[19] << 8));
    c->dig_P8 = (int16_t) (raw[20] | (raw[21] << 8));
    c->dig_P9 = (int16_t) (raw[22] | (raw[23] << 8));

    uint8_t h[7];
    uint8_t h1;
    if (_read_regs(dev, 0xA1, &h1, 1) != 0) return BME280_ERR_COMM;
    if (_read_regs(dev, BME280_REG_CALIB26, h, 7) != 0) return BME280_ERR_COMM;

    c->dig_H1 = h1;
    c->dig_H2 = (int16_t)(h[0] | (h[1] << 8));
    c->dig_H3 = h[2];
    c->dig_H4 = (int16_t)((h[3] << 4) | (h[4] & 0x0F));
    c->dig_H5 = (int16_t)((h[5] << 4) | (h[4] >> 4));
    c->dig_H6 = (int8_t)h[6];
    return BME280_OK;
}

/* ---------------------------------------------------------------------------
 * Compensation functions (from datasheet §4.2.3 integer version)
 * ---------------------------------------------------------------------- */

static int32_t _compensate_temp(bme280_t *dev, int32_t adc_T) {
    const bme280_calib_t *c = &dev->calib;
    int32_t var1 = ((((adc_T >> 3) - ((int32_t)c->dig_T1 << 1)))
                    * (int32_t)c->dig_T2) >> 11;
    int32_t var2 = (((((adc_T >> 4) - (int32_t)c->dig_T1)
                      * ((adc_T >> 4) - (int32_t)c->dig_T1)) >> 12)
                    * (int32_t)c->dig_T3) >> 14;
    dev->t_fine = var1 + var2;
    return (dev->t_fine * 5 + 128) >> 8; /* returns temp * 100 in Celsius */
}

static uint32_t _compensate_pressure(const bme280_t *dev, int32_t adc_P) {
    const bme280_calib_t *c = &dev->calib;
    int64_t var1 = (int64_t)dev->t_fine - 128000;
    int64_t var2 = var1 * var1 * (int64_t)c->dig_P6;
    var2 += ((var1 * (int64_t)c->dig_P5) << 17);
    var2 += ((int64_t)c->dig_P4 << 35);
    var1  = ((var1 * var1 * (int64_t)c->dig_P3) >> 8)
            + ((var1 * (int64_t)c->dig_P2) << 12);
    var1  = (((int64_t)1 << 47) + var1) * (int64_t)c->dig_P1 >> 33;
    if (var1 == 0) return 0;
    int64_t p = 1048576 - adc_P;
    p = (((p << 31) - var2) * 3125) / var1;
    var1 = ((int64_t)c->dig_P9 * (p >> 13) * (p >> 13)) >> 25;
    var2 = ((int64_t)c->dig_P8 * p) >> 19;
    p = ((p + var1 + var2) >> 8) + ((int64_t)c->dig_P7 << 4);
    return (uint32_t)p; /* Q24.8 fixed point — divide by 256 for Pa */
}

static uint32_t _compensate_humidity(const bme280_t *dev, int32_t adc_H) {
    const bme280_calib_t *c = &dev->calib;
    int32_t v = dev->t_fine - 76800;
    v = (((adc_H << 14) - ((int32_t)c->dig_H4 << 20) - ((int32_t)c->dig_H5 * v))
         + 16384) >> 15;
    v = v * (((((v * (int32_t)c->dig_H6) >> 10)
               * (((v * (int32_t)c->dig_H3) >> 11) + 32768)) >> 10) + 2097152)
        * c->dig_H2 / 8192 + 819200 / 65536;
    v = v - (((((v >> 15) * (v >> 15)) >> 7) * (int32_t)c->dig_H1) >> 4);
    if (v < 0) v = 0;
    if (v > 419430400) v = 419430400;
    return (uint32_t)(v >> 12); /* Q22.10 fixed point — divide by 1024 for % */
}

/* ---------------------------------------------------------------------------
 * Public API implementation
 * ---------------------------------------------------------------------- */

int bme280_init(bme280_t *dev, uint8_t addr, uint8_t i2c_bus,
                uint8_t pin_sda, uint8_t pin_scl) {
    if (!dev) return BME280_ERR_NULL;
    dev->i2c_addr = addr;
    dev->i2c_bus  = i2c_bus;
    dev->pin_sda  = pin_sda;
    dev->pin_scl  = pin_scl;
    dev->t_fine   = 0;

    /* Verify chip ID */
    uint8_t chip_id = 0;
    if (_read_regs(dev, BME280_REG_ID, &chip_id, 1) != 0) return BME280_ERR_COMM;
    if (chip_id != BME280_CHIP_ID) return BME280_ERR_ID;

    /* Load compensation coefficients */
    if (_load_calib(dev) != BME280_OK) return BME280_ERR_COMM;

    /* Set 1× oversampling for all channels, normal mode */
    if (_write_reg(dev, BME280_REG_CTRL_HUM, BME280_OSRS_1X) != 0) return BME280_ERR_COMM;
    uint8_t ctrl = (BME280_OSRS_1X << 5) | (BME280_OSRS_1X << 2) | BME280_MODE_NORMAL;
    if (_write_reg(dev, BME280_REG_CTRL_MEAS, ctrl) != 0) return BME280_ERR_COMM;

    return BME280_OK;
}

int bme280_read(bme280_t *dev, float *temp_c, float *humidity,
                float *pressure_pa) {
    if (!dev || !temp_c || !humidity || !pressure_pa) return BME280_ERR_NULL;

    uint8_t raw[8];
    if (_read_regs(dev, BME280_REG_PRESS_MSB, raw, 8) != 0) return BME280_ERR_COMM;

    int32_t adc_P = ((int32_t)raw[0] << 12) | ((int32_t)raw[1] << 4) | (raw[2] >> 4);
    int32_t adc_T = ((int32_t)raw[3] << 12) | ((int32_t)raw[4] << 4) | (raw[5] >> 4);
    int32_t adc_H = ((int32_t)raw[6] << 8)  |  raw[7];

    int32_t  t_raw = _compensate_temp(dev, adc_T);
    uint32_t p_raw = _compensate_pressure(dev, adc_P);
    uint32_t h_raw = _compensate_humidity(dev, adc_H);

    *temp_c      = (float)t_raw / 100.0f;
    *pressure_pa = (float)p_raw / 256.0f;
    *humidity    = (float)h_raw / 1024.0f;

    return BME280_OK;
}

int bme280_soft_reset(bme280_t *dev) {
    if (!dev) return BME280_ERR_NULL;
    return _write_reg(dev, BME280_REG_RESET, BME280_RESET_WORD);
}
