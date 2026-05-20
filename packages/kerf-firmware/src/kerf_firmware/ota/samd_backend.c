/**
 * samd_backend.c — SAMD21/SAMD51 OTA backend for kerf_ota.h
 *
 * Layout: bootloader (first 8 KiB, BOOTPROT = 2) + App A + App B.
 * The bootloader (Adafruit UF2/BOSSAC-compatible double-reset-detect pattern)
 * checks a 4-byte flag at a fixed SRAM address preserved across resets.
 *
 * For Kerf OTA the flag address lives in the last 8 bytes of the non-volatile
 * user row (NVM User Row on SAMD21: 0x804000, 64 bytes).
 *
 * Compile with -DKERF_OTA_PLATFORM_SAMD.
 *
 * Network transport: same kerf_ota_register_http_backend() pattern as STM32.
 *
 * Security:
 *   Signature verified before NVM_Write().
 */

#ifdef KERF_OTA_PLATFORM_SAMD

#include "kerf_ota.h"

/* SAMD ASF / CMSIS headers — available when building with Arduino / ASF SDK */
#include <sam.h>
#include "nvm.h"     /* Atmel ASF NVM driver */

#include <string.h>
#include <stdlib.h>

/* ── Layout ─────────────────────────────────────────────────────────── */

#ifndef KERF_OTA_SAMD_SLOT_A_ADDR
#  define KERF_OTA_SAMD_SLOT_A_ADDR   0x00004000UL   /* after 16 KiB bootloader */
#endif
#ifndef KERF_OTA_SAMD_SLOT_B_ADDR
#  define KERF_OTA_SAMD_SLOT_B_ADDR   0x00020000UL
#endif
#ifndef KERF_OTA_SAMD_SLOT_SIZE
#  define KERF_OTA_SAMD_SLOT_SIZE     0x0001C000UL   /* 112 KiB */
#endif
#ifndef KERF_OTA_SAMD_FLAG_ADDR
#  define KERF_OTA_SAMD_FLAG_ADDR     0x00804038UL   /* NVM User Row, offset 56 */
#endif

#define SAMD_BOOT_FLAG_SLOT_A   0xA5A5A5A5UL
#define SAMD_BOOT_FLAG_SLOT_B   0x5A5A5A5AUL

/* ── HTTP backend ────────────────────────────────────────────────────── */

typedef int (*kerf_http_get_fn)(
    const char *url, uint8_t *buf, size_t buf_len, size_t *bytes_written);

static kerf_http_get_fn _http_backend = NULL;

void kerf_ota_register_http_backend(kerf_http_get_fn fn) { _http_backend = fn; }

/* ── NVM helpers ─────────────────────────────────────────────────────── */

static kerf_ota_result_t _nvm_erase_row(uint32_t addr)
{
    enum status_code sc = nvm_erase_row(addr);
    return (sc == STATUS_OK) ? KERF_OTA_OK : KERF_OTA_ERR_FLASH_WRITE;
}

static kerf_ota_result_t _nvm_write(uint32_t addr, const uint8_t *data, size_t len)
{
    /* NVM page-write loop */
    const uint16_t page_size = nvm_get_parameters()->page_size;
    for (size_t offset = 0; offset < len; offset += page_size) {
        size_t chunk = (len - offset < page_size) ? len - offset : page_size;
        enum status_code sc = nvm_write_buffer(
            addr + offset, (const uint8_t *)data + offset, chunk);
        if (sc != STATUS_OK) return KERF_OTA_ERR_FLASH_WRITE;
    }
    return KERF_OTA_OK;
}

static uint32_t _inactive_addr(void)
{
    uint32_t flag = *((volatile uint32_t *)KERF_OTA_SAMD_FLAG_ADDR);
    return (flag == SAMD_BOOT_FLAG_SLOT_A)
        ? KERF_OTA_SAMD_SLOT_B_ADDR
        : KERF_OTA_SAMD_SLOT_A_ADDR;
}

/* ── SHA-256 (software via mbedTLS portable or ASF crypto) ──────────── */

#include "sha256_sw.h"  /* same portable shim as stm32_backend.c */

/* ── kerf_ota_check ─────────────────────────────────────────────────── */

kerf_ota_result_t kerf_ota_check(
    const char    *manifest_url,
    const char    *current_version,
    const uint8_t *public_key,
    size_t         public_key_len)
{
    if (public_key_len != 32) return KERF_OTA_ERR_INTERNAL;
    if (!_http_backend)       return KERF_OTA_ERR_NETWORK;

    static char json_buf[1024];
    size_t json_len = 0;
    if (_http_backend(manifest_url, (uint8_t *)json_buf,
                      sizeof(json_buf) - 1, &json_len) != 0)
        return KERF_OTA_ERR_NETWORK;
    json_buf[json_len] = '\0';

    kerf_ota_manifest_t manifest;
    kerf_ota_result_t rc = kerf_ota_parse_manifest(json_buf, &manifest);
    if (rc != KERF_OTA_OK) return rc;

    if (kerf_ota_version_compare(manifest.version, current_version) <= 0)
        return KERF_OTA_OK_NO_UPDATE;

    /* Verify signature BEFORE any NVM writes */
    rc = kerf_ota_verify_signature(&manifest, public_key);
    if (rc != KERF_OTA_OK) return rc;

    uint32_t inactive_addr = _inactive_addr();

    static uint8_t image_buf[KERF_OTA_SAMD_SLOT_SIZE];
    size_t image_len = 0;
    if (_http_backend(manifest.download_url, image_buf,
                      sizeof(image_buf), &image_len) != 0)
        return KERF_OTA_ERR_NETWORK;

    uint8_t digest[32];
    sha256_sw(image_buf, image_len, digest);
    if (memcmp(digest, manifest.sha256, 32) != 0)
        return KERF_OTA_ERR_BAD_HASH;

    /* Erase rows covering the inactive slot */
    const uint16_t row_size = nvm_get_parameters()->page_size * 4;
    for (uint32_t off = 0; off < KERF_OTA_SAMD_SLOT_SIZE; off += row_size) {
        rc = _nvm_erase_row(inactive_addr + off);
        if (rc != KERF_OTA_OK) return rc;
    }

    rc = _nvm_write(inactive_addr, image_buf, image_len);
    if (rc != KERF_OTA_OK) return rc;

    /* Flip boot flag */
    uint32_t new_flag = (inactive_addr == KERF_OTA_SAMD_SLOT_A_ADDR)
                        ? SAMD_BOOT_FLAG_SLOT_A
                        : SAMD_BOOT_FLAG_SLOT_B;
    /* Write to NVM user row (requires a special unlock sequence on SAMD) */
    nvm_execute_command(NVM_COMMAND_ERASE_AUX_ROW, KERF_OTA_SAMD_FLAG_ADDR, 0);
    nvm_execute_command(NVM_COMMAND_WRITE_AUX_PAGE, KERF_OTA_SAMD_FLAG_ADDR,
                        (uint32_t)&new_flag);

    /* Reset — will be caught by bootloader which reads the flag */
    NVIC_SystemReset();
    return KERF_OTA_OK;
}

#endif /* KERF_OTA_PLATFORM_SAMD */
