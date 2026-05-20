/**
 * kerf_ota.h — OTA (over-the-air) firmware update API
 *
 * Public API for the device-side OTA update library.
 * Platform backends: esp32_backend.c, stm32_backend.c, samd_backend.c
 *
 * AVR (ATmega328P / ATmega2560) is OUT OF SCOPE — insufficient flash for a
 * dual-partition layout.  On AVR builds, kerf_ota_check() returns
 * KERF_OTA_ERR_AVR_UNSUPPORTED immediately.
 *
 * Flow:
 *   1. kerf_ota_check(url, current_version, public_key_bytes, 32)
 *        → polls GET <url>/manifest  (JSON: version/sha256/ed25519_sig/dl_url)
 *        → compares version; if no update available, returns KERF_OTA_OK_NO_UPDATE
 *        → verifies ed25519 signature of the protected header region
 *        → if bad signature → returns KERF_OTA_ERR_BAD_SIGNATURE  (NO flash write)
 *        → downloads binary to inactive partition
 *        → verifies SHA-256 of downloaded bytes
 *        → if bad hash → returns KERF_OTA_ERR_BAD_HASH
 *        → calls kerf_ota_commit_and_reboot() via the platform backend
 *
 * Compile-time platform selection:
 *   -DKERF_OTA_PLATFORM_ESP32   → esp32_backend.c
 *   -DKERF_OTA_PLATFORM_STM32   → stm32_backend.c
 *   -DKERF_OTA_PLATFORM_SAMD    → samd_backend.c
 *   -DKERF_OTA_PLATFORM_AVR     → stub that returns KERF_OTA_ERR_AVR_UNSUPPORTED
 */

#ifndef KERF_OTA_H
#define KERF_OTA_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── Return codes ────────────────────────────────────────────────────── */

typedef enum {
    KERF_OTA_OK                  = 0,  /**< Update applied; device will reboot. */
    KERF_OTA_OK_NO_UPDATE        = 1,  /**< Already on latest version. */
    KERF_OTA_ERR_NETWORK         = -1, /**< Could not reach manifest URL. */
    KERF_OTA_ERR_BAD_JSON        = -2, /**< Manifest JSON parse error. */
    KERF_OTA_ERR_BAD_SIGNATURE   = -3, /**< ed25519 signature did not verify. */
    KERF_OTA_ERR_BAD_HASH        = -4, /**< SHA-256 of downloaded image mismatch. */
    KERF_OTA_ERR_FLASH_WRITE     = -5, /**< Flash write to inactive partition failed. */
    KERF_OTA_ERR_PARTITION       = -6, /**< No inactive OTA partition found. */
    KERF_OTA_ERR_AVR_UNSUPPORTED = -7, /**< AVR does not support dual-partition OTA.
                                             Use ESP32 / STM32 / SAMD instead. */
    KERF_OTA_ERR_INTERNAL        = -99,/**< Unexpected internal error. */
} kerf_ota_result_t;

/* ── Manifest (returned by kerf_ota_parse_manifest) ─────────────────── */

#define KERF_OTA_VERSION_LEN   16
#define KERF_OTA_HASH_LEN      32   /* SHA-256 raw bytes */
#define KERF_OTA_SIG_LEN       64   /* ed25519 signature raw bytes */
#define KERF_OTA_URL_LEN       256
#define KERF_OTA_DTYPE_LEN     16

typedef struct {
    char     version[KERF_OTA_VERSION_LEN];
    uint8_t  sha256[KERF_OTA_HASH_LEN];
    uint8_t  ed25519_sig[KERF_OTA_SIG_LEN];
    char     download_url[KERF_OTA_URL_LEN];
    char     device_type[KERF_OTA_DTYPE_LEN];
    uint32_t image_size;
    uint32_t timestamp;
} kerf_ota_manifest_t;

/* ── OTA Image header (binary, little-endian, 128 bytes) ─────────────── */
/* Must match sign.py HEADER_FMT.  The signature covers bytes 0..43.      */

#define KERF_OTA_MAGIC     0x4B455246UL  /* "KERF" */
#define KERF_OTA_HDR_SIZE  128

typedef struct __attribute__((packed)) {
    uint32_t magic;           /* 0x4B455246 */
    uint32_t version_int;     /* major<<16 | minor<<8 | patch */
    uint32_t image_size;
    uint8_t  sha256[32];
    uint8_t  ed25519_sig[64];
    char     device_type[16];
    uint32_t timestamp;
} kerf_ota_header_t;

/* ── Public API ──────────────────────────────────────────────────────── */

/**
 * kerf_ota_check — poll, verify and apply an OTA update.
 *
 * @param manifest_url     URL of the manifest JSON endpoint.
 * @param current_version  Version string currently running (e.g. "1.2.3").
 * @param public_key       32-byte raw ed25519 public key embedded in firmware.
 * @param public_key_len   Must be 32.
 *
 * On AVR builds this function is a compile-time stub that returns
 * KERF_OTA_ERR_AVR_UNSUPPORTED without performing any network access.
 *
 * IMPORTANT: The signature is verified BEFORE any flash write is attempted.
 * A bad signature (wrong key, tampered image) will return
 * KERF_OTA_ERR_BAD_SIGNATURE and leave the inactive partition untouched.
 */
kerf_ota_result_t kerf_ota_check(
    const char    *manifest_url,
    const char    *current_version,
    const uint8_t *public_key,
    size_t         public_key_len
);

/**
 * kerf_ota_parse_manifest — parse a JSON manifest into kerf_ota_manifest_t.
 *
 * Called internally by kerf_ota_check; exposed for unit-testing.
 *
 * @param json_buf    NUL-terminated JSON string.
 * @param out         Output manifest struct.
 * @return KERF_OTA_OK on success, KERF_OTA_ERR_BAD_JSON on parse error.
 */
kerf_ota_result_t kerf_ota_parse_manifest(
    const char         *json_buf,
    kerf_ota_manifest_t *out
);

/**
 * kerf_ota_verify_signature — verify ed25519 signature of the protected
 * header region (bytes 0..43 of the binary header).
 *
 * Called by kerf_ota_check before any flash write.
 *
 * @param manifest     Parsed manifest (populated sha256/ed25519_sig/version).
 * @param public_key   32-byte raw public key.
 * @return KERF_OTA_OK or KERF_OTA_ERR_BAD_SIGNATURE.
 */
kerf_ota_result_t kerf_ota_verify_signature(
    const kerf_ota_manifest_t *manifest,
    const uint8_t             *public_key
);

/**
 * kerf_ota_version_compare — compare two version strings.
 *
 * @return  1 if a > b, -1 if a < b, 0 if equal.
 */
int kerf_ota_version_compare(const char *a, const char *b);

/**
 * kerf_ota_avr_unsupported_hint — returns a human-readable string explaining
 * why AVR is not supported.  The string is a compile-time constant.
 */
const char *kerf_ota_avr_unsupported_hint(void);

#ifdef __cplusplus
}
#endif

#endif /* KERF_OTA_H */
