/**
 * hx711.c — Driver for AVIA Semiconductor HX711 24-bit ADC (load cell)
 *
 * Protocol : Pseudo-SPI (2-wire: PD_SCK + DOUT)
 * Pins     : PD_SCK (clock output), DOUT (data/ready input)
 *
 * Implements hx711.h. Uses GPIO HAL shims kerf_gpio_write(), kerf_gpio_read(),
 * kerf_delay_us(), kerf_millis().
 */
#include "hx711.h"

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
void kerf_delay_us(uint32_t us) { (void)us; }

__attribute__((weak))
uint32_t kerf_millis(void) { return 0; }

#endif

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int hx711_init(hx711_t *dev, uint8_t dout, uint8_t sck, uint8_t gain) {
    if (!dev) return HX711_ERR_NULL;
    dev->pin_dout    = dout;
    dev->pin_sck     = sck;
    dev->offset      = 0;
    dev->scale       = 1.0f;

    switch (gain) {
        case HX711_GAIN_32:  dev->gain_pulses = 2; break;
        case HX711_GAIN_64:  dev->gain_pulses = 3; break;
        default:             dev->gain_pulses = 1; break; /* 128 */
    }

    kerf_gpio_set_output(sck);
    kerf_gpio_set_input(dout);
    kerf_gpio_write(sck, 0); /* SCK idle LOW */

    return HX711_OK;
}

int hx711_is_ready(const hx711_t *dev) {
    if (!dev) return 0;
    return kerf_gpio_read(dev->pin_dout) == 0;
}

int hx711_read_raw(hx711_t *dev, int32_t *value) {
    if (!dev || !value) return HX711_ERR_NULL;

    /* Wait for DOUT to go LOW (timeout ~400 ms) */
    uint32_t t0 = kerf_millis();
    while (!hx711_is_ready(dev)) {
        if ((kerf_millis() - t0) > 400) return HX711_ERR_TIMEOUT;
    }

    uint32_t raw = 0;
    /* Clock out 24 bits, MSB first */
    for (int i = 0; i < 24; i++) {
        kerf_gpio_write(dev->pin_sck, 1);
        kerf_delay_us(1);
        raw = (raw << 1) | kerf_gpio_read(dev->pin_dout);
        kerf_gpio_write(dev->pin_sck, 0);
        kerf_delay_us(1);
    }

    /* Extra pulses select channel/gain for NEXT reading */
    for (int i = 0; i < dev->gain_pulses; i++) {
        kerf_gpio_write(dev->pin_sck, 1);
        kerf_delay_us(1);
        kerf_gpio_write(dev->pin_sck, 0);
        kerf_delay_us(1);
    }

    /* Sign-extend 24-bit two's complement value to int32_t */
    if (raw & 0x800000) raw |= 0xFF000000;
    *value = (int32_t)raw;
    return HX711_OK;
}

int hx711_tare(hx711_t *dev, uint8_t times) {
    if (!dev) return HX711_ERR_NULL;
    int64_t sum = 0;
    for (uint8_t i = 0; i < times; i++) {
        int32_t raw;
        int rc = hx711_read_raw(dev, &raw);
        if (rc != HX711_OK) return rc;
        sum += raw;
    }
    dev->offset = (int32_t)(sum / times);
    return HX711_OK;
}

void hx711_set_scale(hx711_t *dev, float scale) {
    if (!dev) return;
    dev->scale = scale;
}

int hx711_weight_kg(hx711_t *dev, float *weight_kg) {
    if (!dev || !weight_kg) return HX711_ERR_NULL;
    int32_t raw;
    int rc = hx711_read_raw(dev, &raw);
    if (rc != HX711_OK) return rc;
    *weight_kg = ((float)(raw - dev->offset)) / dev->scale;
    return HX711_OK;
}

void hx711_power_down(hx711_t *dev) {
    if (!dev) return;
    kerf_gpio_write(dev->pin_sck, 1);
    kerf_delay_us(80); /* > 60 µs triggers power-down */
}

void hx711_power_up(hx711_t *dev) {
    if (!dev) return;
    kerf_gpio_write(dev->pin_sck, 0);
}
