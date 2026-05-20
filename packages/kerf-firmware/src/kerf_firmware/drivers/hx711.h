/**
 * hx711.h — Driver for AVIA Semiconductor HX711 24-bit ADC for load cells
 *
 * Protocol : Pseudo-SPI (dedicated 2-wire serial: PD_SCK + DOUT)
 * Pins     : PD_SCK (clock, GPIO output), DOUT (data ready + data, GPIO input)
 *
 * Datasheet: https://www.digikey.com/htmldatasheets/production/1836471/0/0/1/hx711.pdf
 *
 * The HX711 is a precision 24-bit A/D converter designed for weigh-scale and
 * industrial control applications. It communicates via a proprietary 2-wire
 * serial protocol (NOT standard SPI — no CS, clock idles LOW, data is read
 * on falling edge of PD_SCK).
 *
 * Usage:
 *   hx711_t scale;
 *   hx711_init(&scale, DOUT_PIN, SCK_PIN, HX711_GAIN_128);
 *   hx711_tare(&scale, 10);
 *   float weight_kg = hx711_weight_kg(&scale, 50.0f);  // 50 kg reference
 */
#ifndef KERF_DRIVERS_HX711_H
#define KERF_DRIVERS_HX711_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Channel / gain selection (number of extra SCK pulses after 24)
 * ---------------------------------------------------------------------- */
#define HX711_GAIN_128  1  /**< Channel A, gain 128 (default) */
#define HX711_GAIN_32   2  /**< Channel B, gain 32 */
#define HX711_GAIN_64   3  /**< Channel A, gain 64 */

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t pin_dout;   /**< Data output pin (GPIO input) */
    uint8_t pin_sck;    /**< Power-down / serial clock pin (GPIO output) */
    uint8_t gain_pulses; /**< Extra clock pulses that set channel + gain */
    int32_t offset;     /**< Tare offset (raw ADC counts) */
    float   scale;      /**< Scale factor: kg per raw ADC count */
} hx711_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define HX711_OK            0
#define HX711_ERR_TIMEOUT  -1
#define HX711_ERR_NULL     -2

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * hx711_init — Initialise the HX711 driver.
 *
 * @param dev    Device handle.
 * @param dout   GPIO pin connected to HX711 DOUT.
 * @param sck    GPIO pin connected to HX711 PD_SCK.
 * @param gain   HX711_GAIN_128 / HX711_GAIN_64 / HX711_GAIN_32.
 */
int hx711_init(hx711_t *dev, uint8_t dout, uint8_t sck, uint8_t gain);

/**
 * hx711_is_ready — Returns 1 if DOUT is LOW (conversion complete).
 */
int hx711_is_ready(const hx711_t *dev);

/**
 * hx711_read_raw — Read a single 24-bit ADC sample (blocking).
 * Waits up to ~400 ms for DOUT to go low.
 *
 * @param value  Output: signed 24-bit sample (sign-extended to int32_t).
 */
int hx711_read_raw(hx711_t *dev, int32_t *value);

/**
 * hx711_tare — Average N readings and store the offset.
 *
 * @param times  Number of samples to average (typical: 10–20).
 */
int hx711_tare(hx711_t *dev, uint8_t times);

/**
 * hx711_set_scale — Set the calibration scale factor.
 *
 * @param scale  Raw ADC counts per kilogram (determined by calibration).
 */
void hx711_set_scale(hx711_t *dev, float scale);

/**
 * hx711_weight_kg — Return the current weight in kilograms.
 * Uses the stored offset and scale factor.
 */
int hx711_weight_kg(hx711_t *dev, float *weight_kg);

/**
 * hx711_power_down — Put HX711 into power-down mode (PD_SCK HIGH > 60 µs).
 */
void hx711_power_down(hx711_t *dev);

/**
 * hx711_power_up — Bring HX711 out of power-down (PD_SCK LOW).
 */
void hx711_power_up(hx711_t *dev);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_HX711_H */
