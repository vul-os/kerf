/**
 * ds18b20.c — Driver for Dallas/Maxim DS18B20 digital thermometer
 *
 * Protocol : 1-Wire
 * Pin      : DQ (single wire, 4.7 kΩ pull-up required)
 *
 * Implements the DS18B20 driver declared in ds18b20.h.
 * The 1-Wire bit-bang routines rely on a platform HAL providing:
 *   kerf_ow_reset() / kerf_ow_write_byte() / kerf_ow_read_byte() / kerf_delay_us()
 */
#include "ds18b20.h"

#include <stddef.h>
#include <stdint.h>

/* ---------------------------------------------------------------------------
 * Platform 1-Wire HAL — replace with BSP implementations
 * ---------------------------------------------------------------------- */
#ifndef KERF_OW_HAL_PROVIDED

__attribute__((weak))
int kerf_ow_reset(uint8_t pin) { (void)pin; return -1; }

__attribute__((weak))
void kerf_ow_write_byte(uint8_t pin, uint8_t byte) { (void)pin; (void)byte; }

__attribute__((weak))
uint8_t kerf_ow_read_byte(uint8_t pin) { (void)pin; return 0xFF; }

__attribute__((weak))
void kerf_delay_ms(uint32_t ms) { (void)ms; }

#endif

/* ---------------------------------------------------------------------------
 * CRC-8 (Dallas/Maxim, polynomial 0x31)
 * ---------------------------------------------------------------------- */
static uint8_t _crc8(const uint8_t *data, uint8_t len) {
    uint8_t crc = 0;
    for (uint8_t i = 0; i < len; i++) {
        uint8_t byte = data[i];
        for (uint8_t j = 0; j < 8; j++) {
            if ((crc ^ byte) & 0x01) crc = (crc >> 1) ^ 0x8C;
            else                     crc >>= 1;
            byte >>= 1;
        }
    }
    return crc;
}

/* ---------------------------------------------------------------------------
 * Conversion time lookup (ms)
 * ---------------------------------------------------------------------- */
static uint32_t _conv_time_ms(uint8_t res) {
    switch (res) {
        case DS18B20_RES_9BIT:  return 94;
        case DS18B20_RES_10BIT: return 188;
        case DS18B20_RES_11BIT: return 375;
        default:                return 750; /* 12-bit */
    }
}

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int ds18b20_init(ds18b20_t *dev, uint8_t pin_dq) {
    if (!dev) return DS18B20_ERR_NULL;
    dev->pin_dq     = pin_dq;
    dev->resolution = DS18B20_RES_12BIT;

    /* Probe: reset and read ROM code (single-device mode) */
    if (kerf_ow_reset(pin_dq) != 0) return DS18B20_ERR_NO_DEVICE;

    kerf_ow_write_byte(pin_dq, DS18B20_CMD_READ_ROM);
    for (uint8_t i = 0; i < 8; i++)
        dev->rom[i] = kerf_ow_read_byte(pin_dq);

    if (_crc8(dev->rom, 7) != dev->rom[7]) return DS18B20_ERR_CRC;
    if (dev->rom[0] != DS18B20_FAMILY_CODE) return DS18B20_ERR_NO_DEVICE;

    return DS18B20_OK;
}

int ds18b20_set_resolution(ds18b20_t *dev, uint8_t res) {
    if (!dev) return DS18B20_ERR_NULL;

    if (kerf_ow_reset(dev->pin_dq) != 0) return DS18B20_ERR_NO_DEVICE;
    kerf_ow_write_byte(dev->pin_dq, DS18B20_CMD_SKIP_ROM);
    kerf_ow_write_byte(dev->pin_dq, DS18B20_CMD_WRITE_SCRATCH);
    kerf_ow_write_byte(dev->pin_dq, 0x7F); /* TH register (alarm high) */
    kerf_ow_write_byte(dev->pin_dq, 0x80); /* TL register (alarm low) */
    kerf_ow_write_byte(dev->pin_dq, res);   /* configuration register */

    dev->resolution = res;
    return DS18B20_OK;
}

int ds18b20_start_conversion(ds18b20_t *dev) {
    if (!dev) return DS18B20_ERR_NULL;
    if (kerf_ow_reset(dev->pin_dq) != 0) return DS18B20_ERR_NO_DEVICE;
    kerf_ow_write_byte(dev->pin_dq, DS18B20_CMD_SKIP_ROM);
    kerf_ow_write_byte(dev->pin_dq, DS18B20_CMD_CONVERT_T);
    return DS18B20_OK;
}

int ds18b20_read_scratchpad(ds18b20_t *dev, float *temp_c) {
    if (!dev || !temp_c) return DS18B20_ERR_NULL;

    if (kerf_ow_reset(dev->pin_dq) != 0) return DS18B20_ERR_NO_DEVICE;
    kerf_ow_write_byte(dev->pin_dq, DS18B20_CMD_SKIP_ROM);
    kerf_ow_write_byte(dev->pin_dq, DS18B20_CMD_READ_SCRATCH);

    uint8_t scratch[9];
    for (uint8_t i = 0; i < 9; i++)
        scratch[i] = kerf_ow_read_byte(dev->pin_dq);

    if (_crc8(scratch, 8) != scratch[8]) return DS18B20_ERR_CRC;

    /* Combine two temperature bytes into signed 16-bit value */
    int16_t raw = (int16_t)((scratch[1] << 8) | scratch[0]);
    /* Clear undefined bits for resolutions < 12-bit */
    switch (dev->resolution) {
        case DS18B20_RES_9BIT:  raw &= ~0x07; break;
        case DS18B20_RES_10BIT: raw &= ~0x03; break;
        case DS18B20_RES_11BIT: raw &= ~0x01; break;
        default: break;
    }
    *temp_c = (float)raw / 16.0f;
    return DS18B20_OK;
}

int ds18b20_read_single(ds18b20_t *dev, float *temp_c) {
    if (!dev || !temp_c) return DS18B20_ERR_NULL;
    int rc = ds18b20_start_conversion(dev);
    if (rc != DS18B20_OK) return rc;
    kerf_delay_ms(_conv_time_ms(dev->resolution));
    return ds18b20_read_scratchpad(dev, temp_c);
}
