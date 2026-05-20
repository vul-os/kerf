/**
 * pca9685.h — Driver for NXP PCA9685 16-channel 12-bit PWM controller
 *
 * Protocol : I2C
 * I2C address: 0x40–0x7F (hardware configurable via A0–A5 pins)
 *
 * Datasheet: https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf
 *
 * The PCA9685 provides 16 independent PWM channels with 12-bit (0–4095)
 * resolution and a configurable frequency (24–1526 Hz). Commonly used for:
 * - RC servo control (50 Hz, 1000–2000 µs pulse)
 * - LED dimming (any frequency)
 * - General motor control
 *
 * Usage:
 *   pca9685_t pwm;
 *   pca9685_init(&pwm, 0x40, I2C_BUS_0, SDA_PIN, SCL_PIN);
 *   pca9685_set_freq(&pwm, 50);           // 50 Hz for RC servos
 *   pca9685_set_channel_us(&pwm, 0, 1500); // Channel 0 = 1500 µs (centre)
 */
#ifndef KERF_DRIVERS_PCA9685_H
#define KERF_DRIVERS_PCA9685_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Register map
 * ---------------------------------------------------------------------- */
#define PCA9685_REG_MODE1         0x00
#define PCA9685_REG_MODE2         0x01
#define PCA9685_REG_SUBADR1       0x02
#define PCA9685_REG_SUBADR2       0x03
#define PCA9685_REG_SUBADR3       0x04
#define PCA9685_REG_ALLCALLADR    0x05
#define PCA9685_REG_LED0_ON_L     0x06  /**< Base register for channel 0 */
#define PCA9685_REG_ALL_LED_ON_L  0xFA  /**< Write to all channels at once */
#define PCA9685_REG_PRESCALE      0xFE  /**< PWM frequency prescaler */

/* MODE1 bits */
#define PCA9685_MODE1_RESTART     0x80
#define PCA9685_MODE1_EXTCLK      0x40
#define PCA9685_MODE1_AI          0x20  /**< Auto-increment */
#define PCA9685_MODE1_SLEEP       0x10
#define PCA9685_MODE1_SUB1        0x08
#define PCA9685_MODE1_SUB2        0x04
#define PCA9685_MODE1_SUB3        0x02
#define PCA9685_MODE1_ALLCALL     0x01

/* MODE2 bits */
#define PCA9685_MODE2_INVRT       0x10  /**< Invert output polarity */
#define PCA9685_MODE2_OCH         0x08  /**< Output change on ACK vs STOP */
#define PCA9685_MODE2_OUTDRV      0x04  /**< Totem-pole (1) vs open-drain (0) */

#define PCA9685_CHANNELS          16
#define PCA9685_INTERNAL_OSC_HZ   25000000UL  /**< Internal oscillator: 25 MHz */

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t  i2c_addr;  /**< 0x40–0x7F */
    uint8_t  i2c_bus;   /**< I2C bus index */
    uint8_t  pin_sda;   /**< SDA GPIO */
    uint8_t  pin_scl;   /**< SCL GPIO */
    float    period_us; /**< PWM period in microseconds (set by set_freq) */
} pca9685_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define PCA9685_OK          0
#define PCA9685_ERR_COMM   -1
#define PCA9685_ERR_RANGE  -2
#define PCA9685_ERR_NULL   -3

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * pca9685_init — Wake from sleep, enable auto-increment.
 */
int pca9685_init(pca9685_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl);

/**
 * pca9685_set_freq — Set the PWM frequency in Hz (24–1526 Hz).
 * Must be called before setting channel duty cycles.
 */
int pca9685_set_freq(pca9685_t *dev, float freq_hz);

/**
 * pca9685_set_channel — Set a channel's ON and OFF counts (0–4095 each).
 *
 * @param channel  0–15.
 * @param on_tick  Tick at which the output goes HIGH (0 = immediately).
 * @param off_tick Tick at which the output goes LOW.
 */
int pca9685_set_channel(pca9685_t *dev, uint8_t channel,
                        uint16_t on_tick, uint16_t off_tick);

/**
 * pca9685_set_channel_duty — Set a channel by duty cycle percentage (0–100).
 */
int pca9685_set_channel_duty(pca9685_t *dev, uint8_t channel, float duty_pct);

/**
 * pca9685_set_channel_us — Set a channel by pulse width in microseconds.
 * Useful for RC servo control (typical range: 1000–2000 µs).
 *
 * @param pulse_us  Pulse width in microseconds.
 */
int pca9685_set_channel_us(pca9685_t *dev, uint8_t channel, float pulse_us);

/**
 * pca9685_all_off — Turn all 16 channels off immediately.
 */
int pca9685_all_off(pca9685_t *dev);

/**
 * pca9685_sleep — Enter low-power sleep mode.
 */
int pca9685_sleep(pca9685_t *dev);

/**
 * pca9685_wake — Exit sleep mode and restart PWM.
 */
int pca9685_wake(pca9685_t *dev);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_PCA9685_H */
