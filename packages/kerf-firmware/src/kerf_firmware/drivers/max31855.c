/**
 * max31855.c — Driver for Maxim MAX31855 SPI K-type thermocouple amplifier
 *
 * Protocol : SPI read-only (Mode 0, 5 MHz max)
 * Pins     : SPI bus + CS (active LOW); MOSI not required
 *
 * Implements max31855.h. Reads a single 32-bit big-endian word on each CS pulse.
 */
#include "max31855.h"

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

#endif

/* ---------------------------------------------------------------------------
 * Internal: read 32-bit word
 * ---------------------------------------------------------------------- */
static int _read32(const max31855_t *dev, uint32_t *raw) {
    kerf_spi_cs_low(dev->spi_bus, dev->pin_cs);
    uint32_t w = (uint32_t)kerf_spi_transfer(dev->spi_bus, 0x00) << 24;
    w |= (uint32_t)kerf_spi_transfer(dev->spi_bus, 0x00) << 16;
    w |= (uint32_t)kerf_spi_transfer(dev->spi_bus, 0x00) <<  8;
    w |= (uint32_t)kerf_spi_transfer(dev->spi_bus, 0x00);
    kerf_spi_cs_high(dev->spi_bus, dev->pin_cs);
    *raw = w;
    return MAX31855_OK;
}

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int max31855_init(max31855_t *dev, uint8_t spi_bus, uint8_t pin_cs) {
    if (!dev) return MAX31855_ERR_NULL;
    dev->spi_bus = spi_bus;
    dev->pin_cs  = pin_cs;
    return MAX31855_OK;
}

int max31855_read_raw(max31855_t *dev, uint32_t *raw) {
    if (!dev || !raw) return MAX31855_ERR_NULL;
    return _read32(dev, raw);
}

int max31855_read_celsius(max31855_t *dev, float *temp_c) {
    if (!dev || !temp_c) return MAX31855_ERR_NULL;

    uint32_t raw;
    int rc = _read32(dev, &raw);
    if (rc != MAX31855_OK) return rc;

    /* Check fault bit */
    if (raw & MAX31855_FAULT_BIT) {
        uint8_t faults = (uint8_t)(raw & MAX31855_FAULT_MASK);
        if (faults & MAX31855_FAULT_OC)  return MAX31855_ERR_OPEN;
        if (faults & MAX31855_FAULT_SCG) return MAX31855_ERR_SHORT_GND;
        if (faults & MAX31855_FAULT_SCV) return MAX31855_ERR_SHORT_VCC;
        return MAX31855_ERR_COMM;
    }

    /* Thermocouple temperature: bits 31:18 (14-bit signed, 0.25°C LSB)
     * The value is in the upper 14 bits shifted right by 18. */
    int16_t t = (int16_t)((raw >> 18) & 0x3FFF);
    if (t & 0x2000) t |= (int16_t)0xC000; /* sign-extend 14-bit to 16-bit */
    *temp_c = (float)t * 0.25f;
    return MAX31855_OK;
}

int max31855_read_internal_celsius(max31855_t *dev, float *temp_c) {
    if (!dev || !temp_c) return MAX31855_ERR_NULL;

    uint32_t raw;
    int rc = _read32(dev, &raw);
    if (rc != MAX31855_OK) return rc;

    /* Internal temperature: bits 15:4 (12-bit signed, 0.0625°C LSB) */
    int16_t t = (int16_t)((raw >> 4) & 0x0FFF);
    if (t & 0x0800) t |= (int16_t)0xF000; /* sign-extend 12-bit to 16-bit */
    *temp_c = (float)t * 0.0625f;
    return MAX31855_OK;
}

int max31855_read_faults(max31855_t *dev, uint8_t *faults) {
    if (!dev || !faults) return MAX31855_ERR_NULL;
    uint32_t raw;
    int rc = _read32(dev, &raw);
    if (rc != MAX31855_OK) return rc;
    *faults = (raw & MAX31855_FAULT_BIT) ? (uint8_t)(raw & MAX31855_FAULT_MASK) : 0;
    return MAX31855_OK;
}
