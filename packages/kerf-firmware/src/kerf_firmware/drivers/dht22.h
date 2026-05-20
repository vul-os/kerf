/**
 * dht22.h — Driver for AOSONG DHT22 (AM2302) temperature and humidity sensor
 *
 * Protocol : Single-wire proprietary (similar to 1-Wire but NOT compatible)
 * Pin      : DATA (single bidirectional line, 10 kΩ pull-up to VCC)
 *
 * Datasheet: https://www.sparkfun.com/datasheets/Sensors/Temperature/DHT22.pdf
 *
 * The DHT22 measures relative humidity (0–100% RH, ±2%) and temperature
 * (-40°C to +80°C, ±0.5°C). Minimum 2 second interval between readings.
 * Outputs 40 bits: 16-bit humidity × 10, 16-bit temperature × 10, 8-bit checksum.
 *
 * Usage:
 *   dht22_t dht;
 *   dht22_init(&dht, DATA_PIN);
 *   float temp, humidity;
 *   dht22_read(&dht, &temp, &humidity);
 */
#ifndef KERF_DRIVERS_DHT22_H
#define KERF_DRIVERS_DHT22_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Timing constants
 * ---------------------------------------------------------------------- */
#define DHT22_START_LOW_MS    1     /**< Host start signal LOW ≥ 1 ms */
#define DHT22_START_HIGH_US   30    /**< Host release and wait 20–40 µs */
#define DHT22_RESPONSE_US     80    /**< Device response pulse HIGH/LOW ~80 µs */
#define DHT22_BIT_LOW_US      50    /**< Start of each bit: ~50 µs LOW */
#define DHT22_BIT_1_HIGH_US   70    /**< Logical 1: ~70 µs HIGH */
#define DHT22_BIT_0_HIGH_US   26    /**< Logical 0: 26–28 µs HIGH */
#define DHT22_THRESHOLD_US    40    /**< Threshold to distinguish 0 vs 1 */
#define DHT22_MIN_INTERVAL_MS 2000  /**< Minimum time between readings */

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t  pin_data;         /**< GPIO pin for the DATA line */
    uint32_t last_read_ms;     /**< Timestamp of last successful read */
    float    last_temp_c;      /**< Cached temperature */
    float    last_humidity;    /**< Cached humidity */
} dht22_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define DHT22_OK            0
#define DHT22_ERR_TIMEOUT  -1
#define DHT22_ERR_CHECKSUM -2
#define DHT22_ERR_NULL     -3
#define DHT22_ERR_TOO_SOON -4   /**< Minimum interval not elapsed */

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * dht22_init — Initialise the DHT22 driver.
 *
 * @param dev      Device handle.
 * @param pin_data GPIO pin connected to the DHT22 DATA pin.
 */
int dht22_init(dht22_t *dev, uint8_t pin_data);

/**
 * dht22_read — Read temperature and humidity.
 *
 * Blocks for the full bit-bang acquisition (~5 ms).
 * Returns DHT22_ERR_TOO_SOON if called within 2 s of the last read.
 *
 * @param temp_c    Output: temperature in °C.
 * @param humidity  Output: relative humidity in %.
 */
int dht22_read(dht22_t *dev, float *temp_c, float *humidity);

/**
 * dht22_read_cached — Return the most recent valid reading without talking to
 * the hardware. Useful in ISR or fast-poll contexts.
 */
int dht22_read_cached(const dht22_t *dev, float *temp_c, float *humidity);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_DHT22_H */
