/**
 * stm32_backend.c — STM32 OTA backend for kerf_ota.h
 *
 * Uses a standard "bootloader + App A + App B" three-region flash layout:
 *   Region 0 (bootloader): 0x0800_0000 .. 0x0800_FFFF  (64 KiB)
 *   Region 1 (App A / slot 0): from KERF_OTA_SLOT_A_ADDR, KERF_OTA_SLOT_SIZE
 *   Region 2 (App B / slot 1): from KERF_OTA_SLOT_B_ADDR, KERF_OTA_SLOT_SIZE
 *
 * The bootloader reads a 4-byte magic at KERF_OTA_BOOT_FLAG_ADDR to decide
 * which slot to boot.  After a successful OTA the magic is written to select
 * the new slot.  On next power-on the bootloader jumps there.
 *
 * Compile with -DKERF_OTA_PLATFORM_STM32.
 * Override slot addresses via -DKERF_OTA_SLOT_A_ADDR / _B_ADDR.
 *
 * Network transport: assumed to be provided by a user-supplied
 * kerf_ota_http_get(url, buf, buf_len) callback registered via
 * kerf_ota_register_http_backend().  Allows using lwIP, W5500, ESP-AT, etc.
 *
 * Security:
 *   Signature is verified before HAL_FLASH_Program() is called.
 */

#ifdef KERF_OTA_PLATFORM_STM32

#include "kerf_ota.h"
#include "stm32_hal_compat.h"   /* HAL_FLASH_Unlock/Lock/Program, HAL_Delay */

#include <string.h>
#include <stdlib.h>

/* ── Slot layout defaults (override via compiler flags) ─────────────── */

#ifndef KERF_OTA_SLOT_A_ADDR
#  define KERF_OTA_SLOT_A_ADDR   0x08010000UL   /* STM32F4 typical */
#endif
#ifndef KERF_OTA_SLOT_B_ADDR
#  define KERF_OTA_SLOT_B_ADDR   0x08060000UL
#endif
#ifndef KERF_OTA_SLOT_SIZE
#  define KERF_OTA_SLOT_SIZE     0x00050000UL   /* 320 KiB */
#endif
#ifndef KERF_OTA_BOOT_FLAG_ADDR
#  define KERF_OTA_BOOT_FLAG_ADDR  0x08008000UL  /* last 4 bytes of bootloader */
#endif

#define BOOT_FLAG_SLOT_A   0xA5A5A5A5UL
#define BOOT_FLAG_SLOT_B   0x5A5A5A5AUL

/* ── HTTP backend callback ───────────────────────────────────────────── */

typedef int (*kerf_http_get_fn)(
    const char *url, uint8_t *buf, size_t buf_len, size_t *bytes_written);

static kerf_http_get_fn _http_backend = NULL;

void kerf_ota_register_http_backend(kerf_http_get_fn fn)
{
    _http_backend = fn;
}

/* ── Internal helpers ────────────────────────────────────────────────── */

static uint32_t _inactive_slot_addr(void)
{
    /* Read the current boot flag to determine active slot */
    uint32_t flag = *((volatile uint32_t *)KERF_OTA_BOOT_FLAG_ADDR);
    if (flag == BOOT_FLAG_SLOT_A) return KERF_OTA_SLOT_B_ADDR;
    return KERF_OTA_SLOT_A_ADDR;  /* default / first boot → flash slot A */
}

static uint32_t _inactive_boot_flag(void)
{
    uint32_t flag = *((volatile uint32_t *)KERF_OTA_BOOT_FLAG_ADDR);
    return (flag == BOOT_FLAG_SLOT_A) ? BOOT_FLAG_SLOT_B : BOOT_FLAG_SLOT_A;
}

static kerf_ota_result_t _erase_slot(uint32_t addr)
{
    /* Platform-specific flash erase — uses HAL shim */
    HAL_FLASH_Unlock();
    kerf_ota_result_t rc = KERF_OTA_OK;

    FLASH_EraseInitTypeDef erase_init = {
        .TypeErase    = FLASH_TYPEERASE_SECTORS,
        .Banks        = FLASH_BANK_1,
        .Sector       = ((addr - 0x08000000UL) / 0x4000), /* rough sector calc */
        .NbSectors    = KERF_OTA_SLOT_SIZE / 0x4000,
        .VoltageRange = FLASH_VOLTAGE_RANGE_3,
    };
    uint32_t sector_error = 0;
    if (HAL_FLASHEx_Erase(&erase_init, &sector_error) != HAL_OK) {
        rc = KERF_OTA_ERR_FLASH_WRITE;
    }
    HAL_FLASH_Lock();
    return rc;
}

static kerf_ota_result_t _write_slot(uint32_t addr, const uint8_t *data, size_t len)
{
    HAL_FLASH_Unlock();
    kerf_ota_result_t rc = KERF_OTA_OK;
    for (size_t i = 0; i < len; i += 4) {
        uint32_t word;
        memcpy(&word, data + i, 4);
        if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, addr + i, word) != HAL_OK) {
            rc = KERF_OTA_ERR_FLASH_WRITE;
            break;
        }
    }
    HAL_FLASH_Lock();
    return rc;
}

static kerf_ota_result_t _set_boot_flag(uint32_t flag_value)
{
    /* The boot flag sits at a known address in the bootloader data area.
       Requires the bootloader to have left this word writable (typical pattern:
       leave the last 4 bytes of the bootloader region as OTA metadata). */
    HAL_FLASH_Unlock();
    kerf_ota_result_t rc = KERF_OTA_OK;
    if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD, KERF_OTA_BOOT_FLAG_ADDR,
                          flag_value) != HAL_OK) {
        rc = KERF_OTA_ERR_FLASH_WRITE;
    }
    HAL_FLASH_Lock();
    return rc;
}

/* ── SHA-256 (uses ROM / hardware SHA on STM32H7; falls back to sw impl) */

#ifdef STM32H7xx
#  include "stm32h7xx_hal_hash.h"
static void _sha256(const uint8_t *data, size_t len, uint8_t *digest)
{
    HASH_HandleTypeDef hhash = {0};
    hhash.Init.DataType = HASH_DATATYPE_8B;
    HAL_HASH_Init(&hhash);
    HAL_HASH_SHA256_Start(&hhash, (uint8_t *)data, len, digest, HAL_MAX_DELAY);
}
#else
/* Minimal software SHA-256 placeholder — replace with mbedTLS or a known-good
   software SHA-256 for your target.  The IMPORTANT invariant is that this is
   called AFTER signature verification so a wrong hash only rejects after sig ok. */
#include "sha256_sw.h"   /* user-provided or mbedTLS portable subset */
static void _sha256(const uint8_t *data, size_t len, uint8_t *digest)
{
    sha256_sw(data, len, digest);
}
#endif

/* ── kerf_ota_check ─────────────────────────────────────────────────── */

kerf_ota_result_t kerf_ota_check(
    const char    *manifest_url,
    const char    *current_version,
    const uint8_t *public_key,
    size_t         public_key_len)
{
    if (public_key_len != 32) return KERF_OTA_ERR_INTERNAL;
    if (!_http_backend)       return KERF_OTA_ERR_NETWORK;

    /* 1. Fetch manifest */
    static char json_buf[1024];
    size_t json_len = 0;
    if (_http_backend(manifest_url, (uint8_t *)json_buf, sizeof(json_buf) - 1,
                      &json_len) != 0) {
        return KERF_OTA_ERR_NETWORK;
    }
    json_buf[json_len] = '\0';

    kerf_ota_manifest_t manifest;
    kerf_ota_result_t rc = kerf_ota_parse_manifest(json_buf, &manifest);
    if (rc != KERF_OTA_OK) return rc;

    /* 2. Version check */
    if (kerf_ota_version_compare(manifest.version, current_version) <= 0)
        return KERF_OTA_OK_NO_UPDATE;

    /* 3. Signature check — BEFORE any flash write */
    rc = kerf_ota_verify_signature(&manifest, public_key);
    if (rc != KERF_OTA_OK) return rc;

    /* 4. Download image */
    uint32_t inactive_addr = _inactive_slot_addr();
    static uint8_t image_buf[KERF_OTA_SLOT_SIZE];
    size_t image_len = 0;
    if (_http_backend(manifest.download_url, image_buf,
                      sizeof(image_buf), &image_len) != 0) {
        return KERF_OTA_ERR_NETWORK;
    }

    /* 5. SHA-256 verify */
    uint8_t digest[32];
    _sha256(image_buf, image_len, digest);
    if (memcmp(digest, manifest.sha256, 32) != 0)
        return KERF_OTA_ERR_BAD_HASH;

    /* 6. Erase + write inactive slot */
    rc = _erase_slot(inactive_addr);
    if (rc != KERF_OTA_OK) return rc;

    rc = _write_slot(inactive_addr, image_buf, image_len);
    if (rc != KERF_OTA_OK) return rc;

    /* 7. Update boot flag + soft-reset */
    rc = _set_boot_flag(_inactive_boot_flag());
    if (rc != KERF_OTA_OK) return rc;

    HAL_NVIC_SystemReset();  /* does not return */
    return KERF_OTA_OK;
}

#endif /* KERF_OTA_PLATFORM_STM32 */
