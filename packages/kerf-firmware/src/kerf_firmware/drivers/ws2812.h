/**
 * ws2812.h — Driver for WorldSemi WS2812 / WS2812B addressable RGB LEDs
 *
 * Protocol : Timed single-wire bit-bang (NZR — Non-Zero Return)
 * Pin      : DIN (single data line, 5 V logic; 300–500 Ω series resistor recommended)
 *
 * Datasheet: https://cdn-shop.adafruit.com/datasheets/WS2812B.pdf
 *
 * WS2812B uses a proprietary timing protocol where each bit is encoded as:
 *   1-bit: T1H ≈ 800 ns HIGH, T1L ≈ 450 ns LOW
 *   0-bit: T0H ≈ 400 ns HIGH, T0L ≈ 850 ns LOW
 * 24 bits (GRB order) per LED, cascaded; RESET = DIN LOW > 50 µs.
 *
 * Usage:
 *   #define LED_COUNT 30
 *   static ws2812_pixel_t strip[LED_COUNT];
 *   ws2812_t dev;
 *   ws2812_init(&dev, DIN_PIN, strip, LED_COUNT);
 *   ws2812_set_pixel(&dev, 0, 255, 0, 0);  // LED 0 = red
 *   ws2812_show(&dev);
 */
#ifndef KERF_DRIVERS_WS2812_H
#define KERF_DRIVERS_WS2812_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Pixel storage (GRB order matches the wire protocol)
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t g; /**< Green channel (wire: first) */
    uint8_t r; /**< Red channel (wire: second) */
    uint8_t b; /**< Blue channel (wire: third) */
} ws2812_pixel_t;

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t          pin_din;   /**< GPIO pin connected to LED DIN */
    ws2812_pixel_t  *pixels;    /**< Caller-supplied pixel buffer */
    uint16_t         count;     /**< Number of LEDs in the chain */
} ws2812_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define WS2812_OK       0
#define WS2812_ERR_NULL -1

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * ws2812_init — Attach the driver to a GPIO pin and a pixel buffer.
 *
 * @param dev      Device handle.
 * @param pin_din  GPIO pin connected to the first LED DIN.
 * @param pixels   Caller-allocated array of ws2812_pixel_t, length = count.
 * @param count    Number of LEDs in the strip.
 */
int ws2812_init(ws2812_t *dev, uint8_t pin_din,
                ws2812_pixel_t *pixels, uint16_t count);

/**
 * ws2812_set_pixel — Set a single pixel colour by RGB values.
 *
 * @param index  LED index (0 = closest to MCU).
 * @param r      Red 0–255.
 * @param g      Green 0–255.
 * @param b      Blue 0–255.
 */
int ws2812_set_pixel(ws2812_t *dev, uint16_t index,
                     uint8_t r, uint8_t g, uint8_t b);

/**
 * ws2812_fill — Set all pixels to the same RGB colour.
 */
void ws2812_fill(ws2812_t *dev, uint8_t r, uint8_t g, uint8_t b);

/**
 * ws2812_clear — Turn all pixels off.
 */
void ws2812_clear(ws2812_t *dev);

/**
 * ws2812_show — Transmit the pixel buffer to the strip via the bit-bang protocol.
 *
 * Disables interrupts during transmission to maintain timing accuracy.
 * The function takes approximately (count × 24 × 1.25 µs) + 50 µs reset.
 */
int ws2812_show(ws2812_t *dev);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_WS2812_H */
