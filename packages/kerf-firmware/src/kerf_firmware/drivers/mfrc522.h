/**
 * mfrc522.h — Driver for NXP MFRC522 SPI RFID reader/writer
 *
 * Protocol : SPI (Mode 0, CPOL=0 CPHA=0), up to 10 MHz
 * Also supports I2C and UART but SPI is most common
 *
 * Datasheet: https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf
 *
 * The MFRC522 reads and writes ISO/IEC 14443 A/MIFARE contactless cards and
 * tags at 13.56 MHz. Common applications: access control, payment, inventory.
 *
 * Usage:
 *   mfrc522_t rfid;
 *   mfrc522_init(&rfid, SPI_BUS_0, CS_PIN, RST_PIN);
 *   uint8_t uid[10]; uint8_t uid_len;
 *   if (mfrc522_read_uid(&rfid, uid, &uid_len) == MFRC522_OK) { ... }
 */
#ifndef KERF_DRIVERS_MFRC522_H
#define KERF_DRIVERS_MFRC522_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* -------------------------------------------------------------------------
 * Key register addresses
 * ---------------------------------------------------------------------- */
#define MFRC522_REG_COMMAND       0x01
#define MFRC522_REG_COM_I_EN      0x02
#define MFRC522_REG_DIV_I_EN      0x03
#define MFRC522_REG_COM_IRQ       0x04
#define MFRC522_REG_DIV_IRQ       0x05
#define MFRC522_REG_ERROR         0x06
#define MFRC522_REG_STATUS1       0x07
#define MFRC522_REG_STATUS2       0x08
#define MFRC522_REG_FIFO_DATA     0x09
#define MFRC522_REG_FIFO_LEVEL    0x0A
#define MFRC522_REG_WATER_LEVEL   0x0B
#define MFRC522_REG_CONTROL       0x0C
#define MFRC522_REG_BIT_FRAMING   0x0D
#define MFRC522_REG_COLL          0x0E
#define MFRC522_REG_MODE          0x11
#define MFRC522_REG_TX_MODE       0x12
#define MFRC522_REG_RX_MODE       0x13
#define MFRC522_REG_TX_CONTROL    0x14
#define MFRC522_REG_TX_ASK        0x15
#define MFRC522_REG_T_MODE        0x2A
#define MFRC522_REG_T_PRESCALER   0x2B
#define MFRC522_REG_T_RELOAD_H    0x2C
#define MFRC522_REG_T_RELOAD_L    0x2D
#define MFRC522_REG_VERSION       0x37

/* PCD commands */
#define MFRC522_CMD_IDLE          0x00
#define MFRC522_CMD_MEM           0x01
#define MFRC522_CMD_GEN_RANDOM_ID 0x02
#define MFRC522_CMD_CALC_CRC      0x03
#define MFRC522_CMD_TRANSMIT      0x04
#define MFRC522_CMD_NO_CMD_CHANGE 0x07
#define MFRC522_CMD_RECEIVE       0x08
#define MFRC522_CMD_TRANSCEIVE    0x0C
#define MFRC522_CMD_MF_AUTHENT    0x0E
#define MFRC522_CMD_SOFT_RESET    0x0F

/* PICC (card) commands — ISO 14443A */
#define PICC_CMD_REQA             0x26
#define PICC_CMD_WUPA             0x52
#define PICC_CMD_CT               0x88  /* Cascade tag */
#define PICC_CMD_SEL_CL1          0x93
#define PICC_CMD_SEL_CL2          0x95
#define PICC_CMD_SEL_CL3          0x97
#define PICC_CMD_HLTA             0x50
#define PICC_CMD_MF_AUTH_KEY_A    0x60
#define PICC_CMD_MF_AUTH_KEY_B    0x61
#define PICC_CMD_MF_READ          0x30
#define PICC_CMD_MF_WRITE         0xA0

/* -------------------------------------------------------------------------
 * Device handle
 * ---------------------------------------------------------------------- */
typedef struct {
    uint8_t spi_bus;    /**< SPI bus index */
    uint8_t pin_cs;     /**< Chip select (active LOW) */
    uint8_t pin_rst;    /**< Reset pin (active LOW) */
} mfrc522_t;

/* -------------------------------------------------------------------------
 * Return codes
 * ---------------------------------------------------------------------- */
#define MFRC522_OK              0
#define MFRC522_ERR_COMM       -1
#define MFRC522_ERR_TIMEOUT    -2
#define MFRC522_ERR_NULL       -3
#define MFRC522_ERR_NO_CARD    -4
#define MFRC522_ERR_CRC        -5
#define MFRC522_ERR_COLLISION  -6

/* -------------------------------------------------------------------------
 * Public API
 * ---------------------------------------------------------------------- */

/**
 * mfrc522_init — Hard-reset and configure the MFRC522.
 */
int mfrc522_init(mfrc522_t *dev, uint8_t spi_bus, uint8_t pin_cs, uint8_t pin_rst);

/**
 * mfrc522_is_card_present — Returns 1 if a card is in the RF field.
 */
int mfrc522_is_card_present(mfrc522_t *dev);

/**
 * mfrc522_read_uid — Perform ISO 14443A anti-collision and read the card UID.
 *
 * @param uid      Output buffer (at least 10 bytes).
 * @param uid_len  Output: actual UID length (4, 7, or 10 bytes).
 */
int mfrc522_read_uid(mfrc522_t *dev, uint8_t *uid, uint8_t *uid_len);

/**
 * mfrc522_halt — Send HLTA command to put the card to sleep.
 */
int mfrc522_halt(mfrc522_t *dev);

/**
 * mfrc522_version — Read the hardware version register (should be 0x91 or 0x92).
 */
uint8_t mfrc522_version(mfrc522_t *dev);

#ifdef __cplusplus
}
#endif

#endif /* KERF_DRIVERS_MFRC522_H */
