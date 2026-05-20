/**
 * max31855.h — Driver for Maxim MAX31855 SPI K-type thermocouple amplifier
 *
 * Protocol : SPI read-only (Mode 0, CPOL=0 CPHA=0), up to 5 MHz
 * Pins     : SPI bus + CS (active LOW); no MOSI needed (read-only device)
 *
 * Datasheet: https://datasheets.maximintegrated.com/en/ds/MAX31855.pdf
 *
 * The MAX31855 performs cold-junction compensation and digitises thermocouple
 * EMF. It provides:
 *   - 14-bit thermocouple temperature, 0.25°C resolution, −200°C to +1350°C
 *   - 12-bit internal (cold-junction) temperature, 0.0625°C resolution
 *   - Fault flags: open circuit, short to VCC, short to GND
 *
 * Usage:
 *   max31855_t tc;
 *   max31855_init(&tc, SPI_BUS_0, CS_PIN);
 *   float temp;
 *   max31855_read_celsius(&tc, &temp);
 */
#ifndef KERF_DRIVERS_MAX31855_H
#define KERF_DRIVERS_MAX31855_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Fault flags (bits 2:0 of the 32-bit data word)
 * ---------------------------------------------------------------------- */
#define MAX31855_FAULT_OC      0x01  /**< Open circuit (no thermocouple) */
#define MAX31855_FAULT_SCG     0x02  /**< Short to GND */
#define MAX31855_FAULT_SCV     0x04  /**< Short to VCC */
#define MAX31855_FAULT_MASK    0x07

/* Bit 16 of the 32-bit word is the combined fault flag */
#define MAX31855_FAULT_BIT     (1UL << 16)

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t spi_bus;   /**< SPI bus index */
    uint8_t pin_cs;    /**< Chip select (active LOW) */
} max31855_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define MAX31855_OK             0
#define MAX31855_ERR_COMM      -1
#define MAX31855_ERR_OPEN      -2  /**< Open circuit */
#define MAX31855_ERR_SHORT_GND -3  /**< Short to GND */
#define MAX31855_ERR_SHORT_VCC -4  /**< Short to VCC */
#define MAX31855_ERR_NULL      -5

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * max31855_init — Initialise the MAX31855 driver.
 *
 * @param dev      Device handle.
 * @param spi_bus  SPI peripheral index.
 * @param pin_cs   Chip-select GPIO (active LOW).
 */
int max31855_init(max31855_t *dev, uint8_t spi_bus, uint8_t pin_cs);

/**
 * max31855_read_raw — Read the raw 32-bit data word from the MAX31855.
 *
 * Bit layout (MSB → LSB):
 *   [31:18] Thermocouple temperature (14-bit signed, 0.25°C LSB)
 *   [17]    Reserved
 *   [16]    Fault flag
 *   [15:4]  Internal (cold-junction) temperature (12-bit signed, 0.0625°C LSB)
 *   [3]     Reserved
 *   [2]     SCV fault
 *   [1]     SCG fault
 *   [0]     OC fault
 */
int max31855_read_raw(max31855_t *dev, uint32_t *raw);

/**
 * max31855_read_celsius — Read thermocouple temperature in °C.
 *
 * @param temp_c  Output: thermocouple temperature in degrees Celsius.
 * @return MAX31855_OK, or fault code if a wiring fault is detected.
 */
int max31855_read_celsius(max31855_t *dev, float *temp_c);

/**
 * max31855_read_internal_celsius — Read the cold-junction reference temperature.
 *
 * @param temp_c  Output: internal (PCB/cold-junction) temperature in °C.
 */
int max31855_read_internal_celsius(max31855_t *dev, float *temp_c);

/**
 * max31855_read_faults — Return fault flag byte (MAX31855_FAULT_* bits).
 * Returns 0 if no faults.
 */
int max31855_read_faults(max31855_t *dev, uint8_t *faults);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_MAX31855_H */
