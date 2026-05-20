/**
 * mpu6050.c — Driver for InvenSense MPU-6050 6-axis IMU
 *
 * Protocol : I2C
 * Pins     : SDA (configurable), SCL (configurable)
 *
 * Implements mpu6050.h. Uses the same kerf_i2c_* HAL as the BME280 driver.
 */
#include "mpu6050.h"

#include <stddef.h>
#include <stdint.h>

/* ---------------------------------------------------------------------------
 * HAL shims
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
 * Helpers
 * ---------------------------------------------------------------------- */
static int _write_reg(const mpu6050_t *dev, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = {reg, val};
    return kerf_i2c_write(dev->i2c_bus, dev->i2c_addr, buf, 2);
}

static int _read_regs(const mpu6050_t *dev, uint8_t reg, uint8_t *buf, uint8_t len) {
    return kerf_i2c_read(dev->i2c_bus, dev->i2c_addr, reg, buf, len);
}

static inline int16_t _be16(const uint8_t *b) {
    return (int16_t)((b[0] << 8) | b[1]);
}

/* ---------------------------------------------------------------------------
 * Scale table
 * ---------------------------------------------------------------------- */
static float _accel_scale(uint8_t range) {
    /* 9.80665 m/s² per g */
    switch (range) {
        case MPU6050_ACCEL_FS_2G:  return 9.80665f / 16384.0f;
        case MPU6050_ACCEL_FS_4G:  return 9.80665f /  8192.0f;
        case MPU6050_ACCEL_FS_8G:  return 9.80665f /  4096.0f;
        case MPU6050_ACCEL_FS_16G: return 9.80665f /  2048.0f;
        default:                   return 9.80665f / 16384.0f;
    }
}

static float _gyro_scale(uint8_t range) {
    switch (range) {
        case MPU6050_GYRO_FS_250DPS:  return 1.0f / 131.0f;
        case MPU6050_GYRO_FS_500DPS:  return 1.0f /  65.5f;
        case MPU6050_GYRO_FS_1000DPS: return 1.0f /  32.8f;
        case MPU6050_GYRO_FS_2000DPS: return 1.0f /  16.4f;
        default:                      return 1.0f / 131.0f;
    }
}

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int mpu6050_init(mpu6050_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl) {
    if (!dev) return MPU6050_ERR_NULL;
    dev->i2c_addr  = addr;
    dev->i2c_bus   = i2c_bus;
    dev->pin_sda   = pin_sda;
    dev->pin_scl   = pin_scl;

    /* Verify WHO_AM_I */
    uint8_t who = 0;
    if (_read_regs(dev, MPU6050_REG_WHO_AM_I, &who, 1) != 0) return MPU6050_ERR_COMM;
    if (who != MPU6050_WHO_AM_I_VAL) return MPU6050_ERR_ID;

    /* Wake from sleep (PWR_MGMT_1 = 0x00) */
    if (_write_reg(dev, MPU6050_REG_PWR_MGMT_1, 0x00) != 0) return MPU6050_ERR_COMM;

    /* Default ranges */
    dev->accel_scale = _accel_scale(MPU6050_ACCEL_FS_2G);
    dev->gyro_scale  = _gyro_scale(MPU6050_GYRO_FS_250DPS);
    _write_reg(dev, MPU6050_REG_ACCEL_CONFIG, MPU6050_ACCEL_FS_2G);
    _write_reg(dev, MPU6050_REG_GYRO_CONFIG,  MPU6050_GYRO_FS_250DPS);

    return MPU6050_OK;
}

int mpu6050_set_accel_range(mpu6050_t *dev, uint8_t range) {
    if (!dev) return MPU6050_ERR_NULL;
    if (_write_reg(dev, MPU6050_REG_ACCEL_CONFIG, range) != 0) return MPU6050_ERR_COMM;
    dev->accel_scale = _accel_scale(range);
    return MPU6050_OK;
}

int mpu6050_set_gyro_range(mpu6050_t *dev, uint8_t range) {
    if (!dev) return MPU6050_ERR_NULL;
    if (_write_reg(dev, MPU6050_REG_GYRO_CONFIG, range) != 0) return MPU6050_ERR_COMM;
    dev->gyro_scale = _gyro_scale(range);
    return MPU6050_OK;
}

int mpu6050_read(mpu6050_t *dev, mpu6050_data_t *data) {
    if (!dev || !data) return MPU6050_ERR_NULL;

    uint8_t raw[14];
    /* Read 14 bytes starting at ACCEL_XOUT_H: 6 accel + 2 temp + 6 gyro */
    if (_read_regs(dev, MPU6050_REG_ACCEL_XOUT_H, raw, 14) != 0) return MPU6050_ERR_COMM;

    data->accel_x = (float)_be16(raw + 0)  * dev->accel_scale;
    data->accel_y = (float)_be16(raw + 2)  * dev->accel_scale;
    data->accel_z = (float)_be16(raw + 4)  * dev->accel_scale;
    /* Temperature: TEMP_degC = (raw / 340.0) + 36.53 */
    data->temp_c  = (float)_be16(raw + 6)  / 340.0f + 36.53f;
    data->gyro_x  = (float)_be16(raw + 8)  * dev->gyro_scale;
    data->gyro_y  = (float)_be16(raw + 10) * dev->gyro_scale;
    data->gyro_z  = (float)_be16(raw + 12) * dev->gyro_scale;

    return MPU6050_OK;
}
