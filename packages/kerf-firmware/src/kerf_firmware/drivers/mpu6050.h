/**
 * mpu6050.h — Driver for InvenSense MPU-6050 6-axis IMU (gyro + accelerometer)
 *
 * Protocol : I2C
 * I2C address: 0x68 (AD0=GND) or 0x69 (AD0=VCC)
 *
 * Datasheet: https://invensense.tdk.com/products/motion-tracking/6-axis/mpu-6050/
 *
 * The MPU-6050 provides 3-axis gyroscope and 3-axis accelerometer data
 * plus an on-chip temperature sensor. It includes a Digital Motion Processor
 * (DMP) for offloaded sensor fusion.
 *
 * Usage:
 *   mpu6050_t imu;
 *   mpu6050_init(&imu, 0x68, I2C_BUS_0, SDA_PIN, SCL_PIN);
 *   mpu6050_data_t data;
 *   mpu6050_read(&imu, &data);
 */
#ifndef KERF_DRIVERS_MPU6050_H
#define KERF_DRIVERS_MPU6050_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Key register addresses
 * ---------------------------------------------------------------------- */
#define MPU6050_REG_SMPLRT_DIV      0x19
#define MPU6050_REG_CONFIG          0x1A
#define MPU6050_REG_GYRO_CONFIG     0x1B
#define MPU6050_REG_ACCEL_CONFIG    0x1C
#define MPU6050_REG_FIFO_EN         0x23
#define MPU6050_REG_INT_ENABLE      0x38
#define MPU6050_REG_ACCEL_XOUT_H    0x3B
#define MPU6050_REG_TEMP_OUT_H      0x41
#define MPU6050_REG_GYRO_XOUT_H     0x43
#define MPU6050_REG_PWR_MGMT_1      0x6B
#define MPU6050_REG_WHO_AM_I        0x75

#define MPU6050_WHO_AM_I_VAL        0x68

/* -------------------------------------------------------------------------
 * Full-scale range selectors
 * ---------------------------------------------------------------------- */
/* Accelerometer full-scale (ACCEL_CONFIG bits 4:3) */
#define MPU6050_ACCEL_FS_2G         0x00  /**< ±2 g, 16384 LSB/g */
#define MPU6050_ACCEL_FS_4G         0x08  /**< ±4 g,  8192 LSB/g */
#define MPU6050_ACCEL_FS_8G         0x10  /**< ±8 g,  4096 LSB/g */
#define MPU6050_ACCEL_FS_16G        0x18  /**< ±16 g, 2048 LSB/g */

/* Gyroscope full-scale (GYRO_CONFIG bits 4:3) */
#define MPU6050_GYRO_FS_250DPS      0x00  /**< ±250 °/s, 131 LSB/°/s */
#define MPU6050_GYRO_FS_500DPS      0x08  /**< ±500 °/s,  65.5 LSB/°/s */
#define MPU6050_GYRO_FS_1000DPS     0x10  /**< ±1000 °/s, 32.8 LSB/°/s */
#define MPU6050_GYRO_FS_2000DPS     0x18  /**< ±2000 °/s, 16.4 LSB/°/s */

/* -------------------------------------------------------------------------
 * Data structures
 * ---------------------------------------------------------------------- */
typedef struct {
    float accel_x;  /**< Acceleration X in m/s² */
    float accel_y;  /**< Acceleration Y in m/s² */
    float accel_z;  /**< Acceleration Z in m/s² */
    float gyro_x;   /**< Angular rate X in °/s */
    float gyro_y;   /**< Angular rate Y in °/s */
    float gyro_z;   /**< Angular rate Z in °/s */
    float temp_c;   /**< Die temperature in °C */
} mpu6050_data_t;

typedef struct {
    uint8_t i2c_addr;   /**< 0x68 or 0x69 */
    uint8_t i2c_bus;    /**< I2C bus index */
    uint8_t pin_sda;    /**< SDA GPIO pin */
    uint8_t pin_scl;    /**< SCL GPIO pin */
    float   accel_scale; /**< LSB to m/s² factor */
    float   gyro_scale;  /**< LSB to °/s factor */
} mpu6050_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define MPU6050_OK          0
#define MPU6050_ERR_COMM   -1
#define MPU6050_ERR_ID     -2
#define MPU6050_ERR_NULL   -3

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * mpu6050_init — Wake the MPU-6050 and configure default full-scale ranges.
 *
 * @param dev      Device handle.
 * @param addr     I2C address (0x68 or 0x69).
 * @param i2c_bus  I2C peripheral index.
 * @param pin_sda  SDA GPIO.
 * @param pin_scl  SCL GPIO.
 */
int mpu6050_init(mpu6050_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl);

/**
 * mpu6050_set_accel_range — Change accelerometer full-scale range.
 * @param range  One of MPU6050_ACCEL_FS_*.
 */
int mpu6050_set_accel_range(mpu6050_t *dev, uint8_t range);

/**
 * mpu6050_set_gyro_range — Change gyroscope full-scale range.
 * @param range  One of MPU6050_GYRO_FS_*.
 */
int mpu6050_set_gyro_range(mpu6050_t *dev, uint8_t range);

/**
 * mpu6050_read — Read all sensor axes plus temperature.
 * @param data  Output struct.
 */
int mpu6050_read(mpu6050_t *dev, mpu6050_data_t *data);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_MPU6050_H */
