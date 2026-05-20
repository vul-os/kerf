/**
 * ds18b20.h — Driver for Dallas/Maxim DS18B20 digital thermometer
 *
 * Protocol : 1-Wire
 * Pin      : DQ (single data/power line, requires 4.7 kΩ pull-up to VCC)
 *
 * Datasheet: https://www.analog.com/en/products/ds18b20.html
 *
 * The DS18B20 measures temperature from -55°C to +125°C with ±0.5°C accuracy
 * in the -10°C to +85°C range. Resolution is selectable: 9, 10, 11, or 12 bit.
 *
 * Usage (single device on bus):
 *   ds18b20_t dev;
 *   ds18b20_init(&dev, DQ_PIN);
 *   float temp;
 *   ds18b20_read_single(&dev, &temp);
 */
#ifndef KERF_DRIVERS_DS18B20_H
#define KERF_DRIVERS_DS18B20_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * ROM commands
 * ---------------------------------------------------------------------- */
#define DS18B20_CMD_SEARCH_ROM      0xF0
#define DS18B20_CMD_READ_ROM        0x33
#define DS18B20_CMD_MATCH_ROM       0x55
#define DS18B20_CMD_SKIP_ROM        0xCC
#define DS18B20_CMD_ALARM_SEARCH    0xEC

/* -------------------------------------------------------------------------
 * Function commands
 * ---------------------------------------------------------------------- */
#define DS18B20_CMD_CONVERT_T       0x44
#define DS18B20_CMD_WRITE_SCRATCH   0x4E
#define DS18B20_CMD_READ_SCRATCH    0xBE
#define DS18B20_CMD_COPY_SCRATCH    0x48
#define DS18B20_CMD_RECALL_E2       0xB8
#define DS18B20_CMD_READ_POWER      0xB4

/* -------------------------------------------------------------------------
 * Resolution settings (configuration register bits 5:6)
 * ---------------------------------------------------------------------- */
#define DS18B20_RES_9BIT            0x00   /**< 93.75 ms conversion */
#define DS18B20_RES_10BIT           0x20   /**< 187.5 ms conversion */
#define DS18B20_RES_11BIT           0x40   /**< 375 ms conversion */
#define DS18B20_RES_12BIT           0x60   /**< 750 ms conversion (default) */

#define DS18B20_FAMILY_CODE         0x28

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t pin_dq;             /**< GPIO pin number for 1-Wire DQ line */
    uint8_t rom[8];             /**< 64-bit ROM code (family + serial + CRC) */
    uint8_t resolution;         /**< One of DS18B20_RES_* constants */
} ds18b20_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define DS18B20_OK              0
#define DS18B20_ERR_NO_DEVICE  -1
#define DS18B20_ERR_CRC        -2
#define DS18B20_ERR_NULL       -3

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * ds18b20_init — Initialise the DS18B20 driver and probe the 1-Wire bus.
 *
 * @param dev     Pointer to an uninitialised ds18b20_t handle.
 * @param pin_dq  GPIO pin number connected to the DS18B20 DQ pin.
 * @return DS18B20_OK if at least one device is present.
 */
int ds18b20_init(ds18b20_t *dev, uint8_t pin_dq);

/**
 * ds18b20_set_resolution — Change temperature conversion resolution.
 *
 * @param dev   Initialised handle.
 * @param res   DS18B20_RES_9BIT … DS18B20_RES_12BIT.
 */
int ds18b20_set_resolution(ds18b20_t *dev, uint8_t res);

/**
 * ds18b20_read_single — Convert and read temperature from a single device.
 *
 * Blocks for the conversion time (up to 750 ms at 12-bit resolution).
 *
 * @param dev     Initialised handle.
 * @param temp_c  Output: temperature in degrees Celsius.
 * @return DS18B20_OK on success.
 */
int ds18b20_read_single(ds18b20_t *dev, float *temp_c);

/**
 * ds18b20_start_conversion — Issue CONVERT T without waiting.
 * Call ds18b20_read_scratchpad() after the conversion time has elapsed.
 */
int ds18b20_start_conversion(ds18b20_t *dev);

/**
 * ds18b20_read_scratchpad — Read 9-byte scratchpad and return temperature.
 */
int ds18b20_read_scratchpad(ds18b20_t *dev, float *temp_c);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_DS18B20_H */
