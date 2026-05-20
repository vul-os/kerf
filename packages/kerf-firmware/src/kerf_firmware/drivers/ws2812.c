/**
 * ws2812.c — Driver for WS2812 / WS2812B addressable RGB LEDs
 *
 * Protocol : Timed single-wire bit-bang
 * Pin      : DIN (configured via ws2812_init pin_din argument)
 *
 * Implements ws2812.h. Timing is implemented via kerf_gpio_write() +
 * kerf_delay_ns(). On AVR/ARM targets replace delay_ns with NOP loops
 * calibrated to the CPU clock. Interrupts are disabled during ws2812_show()
 * to prevent timing corruption.
 */
#include "ws2812.h"

#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* ---------------------------------------------------------------------------
 * Platform HAL shims
 * ---------------------------------------------------------------------- */
#ifndef KERF_GPIO_HAL_PROVIDED

__attribute__((weak))
void kerf_gpio_set_output(uint8_t pin) { (void)pin; }

__attribute__((weak))
void kerf_gpio_write(uint8_t pin, uint8_t val) { (void)pin; (void)val; }

/* Delays ~N nanoseconds (platform must implement for correct timing) */
__attribute__((weak))
void kerf_delay_ns(uint32_t ns) { (void)ns; }

__attribute__((weak))
void kerf_delay_us(uint32_t us) { (void)us; }

/* Disable / re-enable global interrupts */
__attribute__((weak))
void kerf_irq_disable(void) {}

__attribute__((weak))
void kerf_irq_enable(void) {}

#endif

/* ---------------------------------------------------------------------------
 * WS2812B timing constants (nanoseconds)
 * ---------------------------------------------------------------------- */
#define WS2812_T1H_NS   800   /**< High time for logical 1 */
#define WS2812_T1L_NS   450   /**< Low  time for logical 1 */
#define WS2812_T0H_NS   400   /**< High time for logical 0 */
#define WS2812_T0L_NS   850   /**< Low  time for logical 0 */
#define WS2812_RESET_US  55   /**< Reset pulse duration */

/* ---------------------------------------------------------------------------
 * Bit transmit — inline for minimal jitter
 * ---------------------------------------------------------------------- */
static void _send_bit(uint8_t pin, uint8_t bit) {
    if (bit) {
        kerf_gpio_write(pin, 1);
        kerf_delay_ns(WS2812_T1H_NS);
        kerf_gpio_write(pin, 0);
        kerf_delay_ns(WS2812_T1L_NS);
    } else {
        kerf_gpio_write(pin, 1);
        kerf_delay_ns(WS2812_T0H_NS);
        kerf_gpio_write(pin, 0);
        kerf_delay_ns(WS2812_T0L_NS);
    }
}

static void _send_byte(uint8_t pin, uint8_t byte) {
    for (int b = 7; b >= 0; b--)
        _send_bit(pin, (byte >> b) & 1);
}

/* ---------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

int ws2812_init(ws2812_t *dev, uint8_t pin_din,
                ws2812_pixel_t *pixels, uint16_t count) {
    if (!dev || !pixels) return WS2812_ERR_NULL;
    dev->pin_din = pin_din;
    dev->pixels  = pixels;
    dev->count   = count;

    kerf_gpio_set_output(pin_din);
    kerf_gpio_write(pin_din, 0);
    memset(pixels, 0, (uint32_t)count * sizeof(ws2812_pixel_t));
    return WS2812_OK;
}

int ws2812_set_pixel(ws2812_t *dev, uint16_t index,
                     uint8_t r, uint8_t g, uint8_t b) {
    if (!dev || !dev->pixels) return WS2812_ERR_NULL;
    if (index >= dev->count) return WS2812_ERR_NULL;
    dev->pixels[index].r = r;
    dev->pixels[index].g = g;
    dev->pixels[index].b = b;
    return WS2812_OK;
}

void ws2812_fill(ws2812_t *dev, uint8_t r, uint8_t g, uint8_t b) {
    if (!dev || !dev->pixels) return;
    for (uint16_t i = 0; i < dev->count; i++) {
        dev->pixels[i].r = r;
        dev->pixels[i].g = g;
        dev->pixels[i].b = b;
    }
}

void ws2812_clear(ws2812_t *dev) {
    ws2812_fill(dev, 0, 0, 0);
}

int ws2812_show(ws2812_t *dev) {
    if (!dev || !dev->pixels) return WS2812_ERR_NULL;

    kerf_irq_disable();

    for (uint16_t i = 0; i < dev->count; i++) {
        /* WS2812 wire order: G, R, B */
        _send_byte(dev->pin_din, dev->pixels[i].g);
        _send_byte(dev->pin_din, dev->pixels[i].r);
        _send_byte(dev->pin_din, dev->pixels[i].b);
    }

    kerf_irq_enable();

    /* Reset pulse */
    kerf_gpio_write(dev->pin_din, 0);
    kerf_delay_us(WS2812_RESET_US);

    return WS2812_OK;
}
