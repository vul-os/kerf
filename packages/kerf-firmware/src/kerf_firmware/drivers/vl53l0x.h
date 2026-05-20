/**
 * vl53l0x.h — Driver for ST VL53L0X time-of-flight distance sensor
 *
 * Protocol : I2C
 * I2C address: 0x29 (default, can be changed in software)
 *
 * Datasheet: https://www.st.com/en/imaging-and-photonics-solutions/vl53l0x.html
 *
 * The VL53L0X measures distance from ~20 mm to 2000 mm using a 940 nm VCSEL
 * laser and a SPAD (single photon avalanche diode) array. It uses ST's
 * FlightSense technology.
 *
 * Usage:
 *   vl53l0x_t tof;
 *   vl53l0x_init(&tof, 0x29, I2C_BUS_0, SDA_PIN, SCL_PIN);
 *   uint16_t dist_mm;
 *   vl53l0x_read_range_mm(&tof, &dist_mm);
 */
#ifndef KERF_DRIVERS_VL53L0X_H
#define KERF_DRIVERS_VL53L0X_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Key registers
 * ---------------------------------------------------------------------- */
#define VL53L0X_REG_SYSRANGE_START              0x00
#define VL53L0X_REG_SYSTEM_THRESH_HIGH          0x0C
#define VL53L0X_REG_SYSTEM_THRESH_LOW           0x0E
#define VL53L0X_REG_SYSTEM_SEQUENCE_CONFIG      0x01
#define VL53L0X_REG_RESULT_INTERRUPT_STATUS     0x13
#define VL53L0X_REG_RESULT_RANGE_STATUS         0x14
#define VL53L0X_REG_RESULT_RANGE_MM             0x1E  /**< 16-bit range result */
#define VL53L0X_REG_CROSSTALK_COMPENSATION      0x20
#define VL53L0X_REG_OSC_CALIBRATE_VAL           0xF8
#define VL53L0X_REG_GPIO_HV_MUX_ACTIVE_HIGH     0x84
#define VL53L0X_REG_SYSTEM_INTERRUPT_CLEAR      0x0B
#define VL53L0X_REG_IDENTIFICATION_MODEL_ID     0xC0
#define VL53L0X_REG_IDENTIFICATION_REVISION_ID  0xC2

#define VL53L0X_MODEL_ID     0xEE
#define VL53L0X_RANGE_ERR    0xFFFF  /**< Returned when range is out of bounds */

/* Ranging modes */
#define VL53L0X_MODE_SINGLE       0x00
#define VL53L0X_MODE_CONTINUOUS   0x02
#define VL53L0X_MODE_TIMED        0x04

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t  i2c_addr;      /**< Default 0x29 */
    uint8_t  i2c_bus;       /**< I2C bus index */
    uint8_t  pin_sda;       /**< SDA GPIO */
    uint8_t  pin_scl;       /**< SCL GPIO */
    uint8_t  stop_variable;  /**< Calibration byte read at init */
    uint32_t timing_budget_us; /**< Ranging timing budget in microseconds */
} vl53l0x_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define VL53L0X_OK          0
#define VL53L0X_ERR_COMM   -1
#define VL53L0X_ERR_ID     -2
#define VL53L0X_ERR_TIMEOUT -3
#define VL53L0X_ERR_NULL   -4

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * vl53l0x_init — Initialise the VL53L0X and perform reference SPAD calibration.
 */
int vl53l0x_init(vl53l0x_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl);

/**
 * vl53l0x_set_address — Change the I2C device address.
 * Useful when multiple VL53L0X sensors share a bus.
 */
int vl53l0x_set_address(vl53l0x_t *dev, uint8_t new_addr);

/**
 * vl53l0x_set_timing_budget_us — Set the measurement timing budget.
 * Longer budget = higher accuracy. Minimum 20000 µs.
 */
int vl53l0x_set_timing_budget_us(vl53l0x_t *dev, uint32_t budget_us);

/**
 * vl53l0x_read_range_mm — Perform a single-shot ranging measurement.
 *
 * @param range_mm  Output: distance in mm (VL53L0X_RANGE_ERR = out of range).
 */
int vl53l0x_read_range_mm(vl53l0x_t *dev, uint16_t *range_mm);

/**
 * vl53l0x_start_continuous — Start continuous ranging mode.
 * @param period_ms  Measurement period (0 = as fast as possible).
 */
int vl53l0x_start_continuous(vl53l0x_t *dev, uint32_t period_ms);

/**
 * vl53l0x_stop_continuous — Stop continuous ranging.
 */
int vl53l0x_stop_continuous(vl53l0x_t *dev);

/**
 * vl53l0x_read_range_continuous_mm — Read latest measurement in continuous mode.
 * Returns VL53L0X_ERR_TIMEOUT if no new data within ~100 ms.
 */
int vl53l0x_read_range_continuous_mm(vl53l0x_t *dev, uint16_t *range_mm);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_VL53L0X_H */
