/**
 * bme280.h — Driver for Bosch BME280 temperature/humidity/pressure sensor
 *
 * Protocol : I2C (primary) or SPI
 * Default I2C address: 0x76 (SDO=GND) or 0x77 (SDO=VCC)
 *
 * Datasheet: https://www.bosch-sensortec.com/products/environmental-sensors/humidity-sensors-bme280/
 *
 * This driver targets the kerfrtos-aware API so it can run inside a FreeRTOS
 * task on AVR / ARM-M / xtensa / RISC-V targets.
 *
 * Usage:
 *   bme280_t dev;
 *   bme280_init(&dev, 0x76, I2C_BUS_0, SDA_PIN, SCL_PIN);
 *   bme280_read(&dev, &temp_c, &humidity_pct, &pressure_pa);
 */
#ifndef KERF_DRIVERS_BME280_H
#define KERF_DRIVERS_BME280_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Register map (BME280)
 * ---------------------------------------------------------------------- */
#define BME280_REG_CALIB00      0x88
#define BME280_REG_ID           0xD0
#define BME280_REG_RESET        0xE0
#define BME280_REG_CALIB26      0xE1
#define BME280_REG_CTRL_HUM     0xF2
#define BME280_REG_STATUS       0xF3
#define BME280_REG_CTRL_MEAS    0xF4
#define BME280_REG_CONFIG       0xF5
#define BME280_REG_PRESS_MSB    0xF7
#define BME280_REG_TEMP_MSB     0xFA
#define BME280_REG_HUM_MSB      0xFD

#define BME280_CHIP_ID          0x60
#define BME280_RESET_WORD       0xB6

/* Oversampling settings */
#define BME280_OSRS_SKIP        0x00
#define BME280_OSRS_1X          0x01
#define BME280_OSRS_2X          0x02
#define BME280_OSRS_4X          0x03
#define BME280_OSRS_8X          0x04
#define BME280_OSRS_16X         0x05

/* Mode */
#define BME280_MODE_SLEEP       0x00
#define BME280_MODE_FORCED      0x01
#define BME280_MODE_NORMAL      0x03

/* -------------------------------------------------------------------------
 * Compensation (trimming) coefficients
 * ---------------------------------------------------------------------- */
typedef struct {
    uint16_t dig_T1;
    int16_t  dig_T2;
    int16_t  dig_T3;
    uint16_t dig_P1;
    int16_t  dig_P2;
    int16_t  dig_P3;
    int16_t  dig_P4;
    int16_t  dig_P5;
    int16_t  dig_P6;
    int16_t  dig_P7;
    int16_t  dig_P8;
    int16_t  dig_P9;
    uint8_t  dig_H1;
    int16_t  dig_H2;
    uint8_t  dig_H3;
    int16_t  dig_H4;
    int16_t  dig_H5;
    int8_t   dig_H6;
} bme280_calib_t;

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t       i2c_addr;   /**< 0x76 or 0x77 */
    uint8_t       i2c_bus;    /**< I2C bus/port index */
    uint8_t       pin_sda;    /**< SDA GPIO pin number */
    uint8_t       pin_scl;    /**< SCL GPIO pin number */
    bme280_calib_t calib;     /**< Trimming coefficients loaded at init */
    int32_t       t_fine;     /**< Internal temperature for compensation */
} bme280_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define BME280_OK               0
#define BME280_ERR_COMM        -1
#define BME280_ERR_ID          -2
#define BME280_ERR_NULL        -3

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * bme280_init — Initialise the BME280 device.
 *
 * @param dev      Pointer to an uninitialised bme280_t handle.
 * @param addr     I2C address (BME280_ADDR_LOW = 0x76 or BME280_ADDR_HIGH = 0x77).
 * @param i2c_bus  I2C bus/peripheral index (0 = first bus).
 * @param pin_sda  GPIO pin number for SDA.
 * @param pin_scl  GPIO pin number for SCL.
 * @return BME280_OK on success, negative error code otherwise.
 */
int bme280_init(bme280_t *dev, uint8_t addr, uint8_t i2c_bus,
                uint8_t pin_sda, uint8_t pin_scl);

/**
 * bme280_read — Trigger a forced-mode measurement and read results.
 *
 * @param dev         Initialised device handle.
 * @param temp_c      Output: temperature in degrees Celsius (e.g. 23.51).
 * @param humidity    Output: relative humidity in % (e.g. 54.3).
 * @param pressure_pa Output: pressure in Pascals (e.g. 101325.0).
 * @return BME280_OK on success.
 */
int bme280_read(bme280_t *dev, float *temp_c, float *humidity,
                float *pressure_pa);

/**
 * bme280_soft_reset — Send a soft reset command.
 */
int bme280_soft_reset(bme280_t *dev);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_BME280_H */
