/**
 * ssd1306.h — Driver for Solomon SSD1306 128×64 monochrome OLED controller
 *
 * Protocol : I2C (default) or SPI (4-wire)
 * I2C addr : 0x3C (SA0=GND) or 0x3D (SA0=VCC)
 *
 * Datasheet: https://www.solomon-systech.com/product/ssd1306/
 *
 * The SSD1306 drives a 128×64 dot-matrix OLED panel. It contains an on-chip
 * 1 KB GDDRAM (graphic display data RAM) that maps directly to the pixel grid.
 * This driver targets the I2C interface.
 *
 * Usage:
 *   ssd1306_t oled;
 *   ssd1306_init(&oled, 0x3C, I2C_BUS_0, SDA_PIN, SCL_PIN);
 *   ssd1306_clear(&oled);
 *   ssd1306_draw_pixel(&oled, 10, 10, 1);
 *   ssd1306_display(&oled);
 */
#ifndef KERF_DRIVERS_SSD1306_H
#define KERF_DRIVERS_SSD1306_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SSD1306_WIDTH   128
#define SSD1306_HEIGHT   64
#define SSD1306_PAGES    (SSD1306_HEIGHT / 8)   /**< 8 pages of 8 rows each */
#define SSD1306_BUF_SZ   (SSD1306_WIDTH * SSD1306_PAGES)  /**< 1024 bytes */

/* -------------------------------------------------------------------------
 * Key commands (subset)
 * ---------------------------------------------------------------------- */
#define SSD1306_CMD_DISPLAY_OFF     0xAE
#define SSD1306_CMD_DISPLAY_ON      0xAF
#define SSD1306_CMD_SET_CONTRAST    0x81
#define SSD1306_CMD_ENTIRE_ON       0xA5
#define SSD1306_CMD_ENTIRE_RESUME   0xA4
#define SSD1306_CMD_INVERT_OFF      0xA6
#define SSD1306_CMD_INVERT_ON       0xA7
#define SSD1306_CMD_MEM_ADDR_MODE   0x20
#define SSD1306_CMD_COL_ADDR        0x21
#define SSD1306_CMD_PAGE_ADDR       0x22
#define SSD1306_CMD_SET_START_LINE  0x40
#define SSD1306_CMD_CHARGE_PUMP     0x8D
#define SSD1306_CMD_SEGMENT_REMAP   0xA0
#define SSD1306_CMD_MULTIPLEX       0xA8
#define SSD1306_CMD_COM_OUTPUT_DIR  0xC0
#define SSD1306_CMD_DISPLAY_OFFSET  0xD3
#define SSD1306_CMD_COM_PIN_CFG     0xDA
#define SSD1306_CMD_CLK_DIVIDER     0xD5
#define SSD1306_CMD_PRECHARGE       0xD9
#define SSD1306_CMD_VCOM_DESELECT   0xDB

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t i2c_addr;           /**< 0x3C or 0x3D */
    uint8_t i2c_bus;            /**< I2C bus index */
    uint8_t pin_sda;            /**< SDA GPIO */
    uint8_t pin_scl;            /**< SCL GPIO */
    uint8_t buf[SSD1306_BUF_SZ]; /**< 1 KB frame buffer */
} ssd1306_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define SSD1306_OK          0
#define SSD1306_ERR_COMM   -1
#define SSD1306_ERR_NULL   -2

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * ssd1306_init — Initialise the SSD1306 with the standard startup sequence.
 */
int ssd1306_init(ssd1306_t *dev, uint8_t addr, uint8_t i2c_bus,
                 uint8_t pin_sda, uint8_t pin_scl);

/**
 * ssd1306_clear — Fill the frame buffer with zeros (all pixels off).
 */
void ssd1306_clear(ssd1306_t *dev);

/**
 * ssd1306_fill — Fill the frame buffer with 0xFF (all pixels on).
 */
void ssd1306_fill(ssd1306_t *dev);

/**
 * ssd1306_draw_pixel — Set or clear a single pixel in the frame buffer.
 * @param x    Column 0–127.
 * @param y    Row 0–63.
 * @param on   1 = pixel on, 0 = pixel off.
 */
void ssd1306_draw_pixel(ssd1306_t *dev, uint8_t x, uint8_t y, uint8_t on);

/**
 * ssd1306_display — Flush the frame buffer to the OLED hardware.
 */
int ssd1306_display(ssd1306_t *dev);

/**
 * ssd1306_set_contrast — Set display contrast 0–255.
 */
int ssd1306_set_contrast(ssd1306_t *dev, uint8_t contrast);

/**
 * ssd1306_set_display_on — Turn the display on or off.
 */
int ssd1306_set_display_on(ssd1306_t *dev, uint8_t on);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_SSD1306_H */
