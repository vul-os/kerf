/**
 * dht22.c — Driver for AOSONG DHT22 temperature and humidity sensor
 *
 * Protocol : Single-wire proprietary
 * Pin      : DATA (configured via dht22_init pin_data argument)
 *
 * Implements dht22.h. Platform HAL: kerf_gpio_set_{input,output}, kerf_gpio_write,
 * kerf_gpio_read, kerf_delay_ms, kerf_delay_us, kerf_millis.
 */
#include "dht22.h"

#include <stddef.h>
#include <stdint.h>

/* ---------------------------------------------------------------------------
 * GPIO / timing HAL shims
 * ---------------------------------------------------------------------- */
#ifndef KERF_GPIO_HAL_PROVIDED

__attribute__((weak))
void kerf_gpio_set_output(uint8_t pin) { (void)pin; }

__attribute__((weak))
void kerf_gpio_set_input(uint8_t pin) { (void)pin; }

__attribute__((weak))
void kerf_gpio_write(uint8_t pin, uint8_t val) { (void)pin; (void)val; }

__attribute__((weak))
uint8_t kerf_gpio_read(uint8_t pin) { (void)pin; return 1; }

__attribute__((weak))
void kerf_delay_ms(uint32_t ms) { (void)ms; }

__attribute__((weak))
void kerf_delay_us(uint32_t us) { (void)us; }

__attribute__((weak))
uint32_t kerf_millis(void) { return 0; }

/* Measure how long (in µs) the pin stays at the given level (timeout ~1 ms) */
__attribute__((weak))
uint32_t kerf_pulse_in_us(uint8_t pin, uint8_t level, uint32_t timeout_us) {
    (void)pin; (void)level; (void)timeout_us;
    return 0;
}

#endif

/* ---------------------------------------------------------------------------
 * Internal: bit-bang acquisition
 * Returns 0 on success, negative on error.
 * ---------------------------------------------------------------------- */
static int _acquire(const dht22_t *dev, uint8_t data[5]) {
    uint8_t pin = dev->pin_data;

    /* Host start signal */
    kerf_gpio_set_output(pin);
    kerf_gpio_write(pin, 0);
    kerf_delay_ms(DHT22_START_LOW_MS);
    kerf_gpio_write(pin, 1);
    kerf_delay_us(DHT22_START_HIGH_US);
    kerf_gpio_set_input(pin);

    /* Wait for device response LOW */
    if (kerf_pulse_in_us(pin, 0, 100) == 0) return DHT22_ERR_TIMEOUT;
    /* Wait for device response HIGH */
    if (kerf_pulse_in_us(pin, 1, 100) == 0) return DHT22_ERR_TIMEOUT;

    /* Read 40 bits */
    for (int byte_n = 0; byte_n < 5; byte_n++) {
        data[byte_n] = 0;
        for (int bit_n = 7; bit_n >= 0; bit_n--) {
            /* Wait for bit LOW preamble */
            if (kerf_pulse_in_us(pin, 0, 100) == 0) return DHT22_ERR_TIMEOUT;
            /* Measure HIGH duration */
            uint32_t hi = kerf_pulse_in_us(pin, 1, 100);
            if (hi == 0) return DHT22_ERR_TIMEOUT;
            if (hi > DHT22_THRESHOLD_US)
                data[byte_n] |= (1 << bit_n); /* logical 1 */
        }
    }
    return 0;
}

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int dht22_init(dht22_t *dev, uint8_t pin_data) {
    if (!dev) return DHT22_ERR_NULL;
    dev->pin_data      = pin_data;
    dev->last_read_ms  = 0;
    dev->last_temp_c   = 0.0f;
    dev->last_humidity = 0.0f;

    kerf_gpio_set_output(pin_data);
    kerf_gpio_write(pin_data, 1); /* idle HIGH */
    return DHT22_OK;
}

int dht22_read(dht22_t *dev, float *temp_c, float *humidity) {
    if (!dev || !temp_c || !humidity) return DHT22_ERR_NULL;

    uint32_t now = kerf_millis();
    if (dev->last_read_ms && (now - dev->last_read_ms) < DHT22_MIN_INTERVAL_MS)
        return DHT22_ERR_TOO_SOON;

    uint8_t data[5];
    int rc = _acquire(dev, data);
    if (rc != 0) return rc;

    /* Verify checksum */
    uint8_t csum = (uint8_t)((data[0] + data[1] + data[2] + data[3]) & 0xFF);
    if (csum != data[4]) return DHT22_ERR_CHECKSUM;

    /* Decode humidity: bytes 0–1, 16-bit, ×0.1 */
    uint16_t rh_raw = (uint16_t)((data[0] << 8) | data[1]);
    *humidity = (float)rh_raw * 0.1f;

    /* Decode temperature: bytes 2–3, 16-bit, MSB sign bit, ×0.1 */
    uint16_t t_raw = (uint16_t)((data[2] & 0x7F) << 8) | data[3];
    *temp_c = (float)t_raw * 0.1f;
    if (data[2] & 0x80) *temp_c = -(*temp_c);

    dev->last_temp_c   = *temp_c;
    dev->last_humidity = *humidity;
    dev->last_read_ms  = kerf_millis();

    return DHT22_OK;
}

int dht22_read_cached(const dht22_t *dev, float *temp_c, float *humidity) {
    if (!dev || !temp_c || !humidity) return DHT22_ERR_NULL;
    *temp_c   = dev->last_temp_c;
    *humidity = dev->last_humidity;
    return DHT22_OK;
}
