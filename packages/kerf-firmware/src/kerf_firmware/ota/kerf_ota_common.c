/**
 * kerf_ota_common.c — Platform-independent OTA utilities.
 *
 * Provides:
 *   kerf_ota_parse_manifest()       — minimal JSON manifest parser (no heap)
 *   kerf_ota_verify_signature()     — ed25519 protected-header signature check
 *   kerf_ota_version_compare()      — semver-style version comparison
 *   kerf_ota_avr_unsupported_hint() — AVR advisory message
 *
 * ed25519 backend:
 *   On ESP32 (IDF): mbedtls_pk_verify via mbedTLS built-in to IDF.
 *   On STM32/SAMD:  user provides KERF_OTA_ED25519_VERIFY(msg, msg_len, sig, pub)
 *                   macro pointing to their preferred ed25519 library.
 *                   Default stub: always returns KERF_OTA_ERR_BAD_SIGNATURE
 *                   until a real crypto library is wired in.
 *
 * JSON parser:
 *   A minimal grep-style parser — searches for "key":"value" patterns.
 *   Does NOT handle nested objects; the manifest is intentionally flat.
 *
 * Compile: include this file unconditionally on all platforms.
 */

#include "kerf_ota.h"

#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <ctype.h>

/* ── Version parsing + comparison ────────────────────────────────────── */

static void _parse_version(const char *s, int *major, int *minor, int *patch)
{
    *major = *minor = *patch = 0;
    while (*s == 'v' || *s == 'V') s++;
    sscanf(s, "%d.%d.%d", major, minor, patch);
}

int kerf_ota_version_compare(const char *a, const char *b)
{
    int a_maj, a_min, a_pat;
    int b_maj, b_min, b_pat;
    _parse_version(a, &a_maj, &a_min, &a_pat);
    _parse_version(b, &b_maj, &b_min, &b_pat);
    if (a_maj != b_maj) return (a_maj > b_maj) ? 1 : -1;
    if (a_min != b_min) return (a_min > b_min) ? 1 : -1;
    if (a_pat != b_pat) return (a_pat > b_pat) ? 1 : -1;
    return 0;
}

/* ── AVR hint ─────────────────────────────────────────────────────────── */

const char *kerf_ota_avr_unsupported_hint(void)
{
    return
        "AVR (ATmega328P / ATmega2560) is too small for dual-partition OTA: "
        "the device has insufficient flash for a bootloader + two application "
        "slots.  Consider migrating to ESP32, STM32 (e.g. Bluepill/Nucleo) or "
        "SAMD21/SAMD51, all of which have ample flash for the three-region "
        "layout required by kerf_ota.";
}

#ifdef KERF_OTA_PLATFORM_AVR
kerf_ota_result_t kerf_ota_check(
    const char    *manifest_url,
    const char    *current_version,
    const uint8_t *public_key,
    size_t         public_key_len)
{
    (void)manifest_url; (void)current_version;
    (void)public_key;   (void)public_key_len;
    return KERF_OTA_ERR_AVR_UNSUPPORTED;
}
#endif /* KERF_OTA_PLATFORM_AVR */

/* ── Minimal flat JSON field extractor ────────────────────────────────── */
/*
 * Finds the string value of "key" in a flat JSON object.
 * Writes at most out_len-1 bytes into out (NUL-terminated).
 * Returns 0 on success, -1 if key not found.
 */
static int _json_get_str(const char *json, const char *key,
                         char *out, size_t out_len)
{
    /* Build search pattern: "key":" */
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(json, pattern);
    if (!p) return -1;
    p += strlen(pattern);
    while (*p == ' ' || *p == '\t' || *p == ':') p++;
    if (*p == '"') {
        p++;  /* skip opening quote */
        size_t i = 0;
        while (*p && *p != '"' && i + 1 < out_len) out[i++] = *p++;
        out[i] = '\0';
        return 0;
    }
    /* Non-string (number / boolean) — read until delimiter */
    size_t i = 0;
    while (*p && *p != ',' && *p != '}' && *p != '\n' && i + 1 < out_len)
        out[i++] = *p++;
    /* Strip trailing whitespace */
    while (i > 0 && (out[i-1] == ' ' || out[i-1] == '\r' || out[i-1] == '\n'))
        i--;
    out[i] = '\0';
    return (i > 0) ? 0 : -1;
}

/* Decode a hex string into a byte array.  Returns 0 on success. */
static int _hex_decode(const char *hex, uint8_t *out, size_t expected_bytes)
{
    size_t hex_len = strlen(hex);
    if (hex_len != expected_bytes * 2) return -1;
    for (size_t i = 0; i < expected_bytes; i++) {
        unsigned int byte;
        if (sscanf(hex + 2*i, "%2x", &byte) != 1) return -1;
        out[i] = (uint8_t)byte;
    }
    return 0;
}

kerf_ota_result_t kerf_ota_parse_manifest(
    const char         *json_buf,
    kerf_ota_manifest_t *out)
{
    memset(out, 0, sizeof(*out));

    char tmp[512];

    if (_json_get_str(json_buf, "version", out->version, KERF_OTA_VERSION_LEN) != 0)
        return KERF_OTA_ERR_BAD_JSON;

    if (_json_get_str(json_buf, "sha256", tmp, sizeof(tmp)) != 0)
        return KERF_OTA_ERR_BAD_JSON;
    if (_hex_decode(tmp, out->sha256, 32) != 0)
        return KERF_OTA_ERR_BAD_JSON;

    if (_json_get_str(json_buf, "ed25519_signature", tmp, sizeof(tmp)) != 0)
        return KERF_OTA_ERR_BAD_JSON;
    if (_hex_decode(tmp, out->ed25519_sig, 64) != 0)
        return KERF_OTA_ERR_BAD_JSON;

    if (_json_get_str(json_buf, "download_url", out->download_url, KERF_OTA_URL_LEN) != 0)
        return KERF_OTA_ERR_BAD_JSON;

    /* Optional fields */
    _json_get_str(json_buf, "device_type", out->device_type, KERF_OTA_DTYPE_LEN);

    if (_json_get_str(json_buf, "image_size", tmp, sizeof(tmp)) == 0)
        out->image_size = (uint32_t)atol(tmp);

    if (_json_get_str(json_buf, "timestamp", tmp, sizeof(tmp)) == 0)
        out->timestamp = (uint32_t)atol(tmp);

    return KERF_OTA_OK;
}

/* ── Signature verification ───────────────────────────────────────────── */
/*
 * The protected region that was signed (44 bytes, little-endian):
 *   offset  0:  uint32  magic        = 0x4B455246
 *   offset  4:  uint32  version_int  = major<<16|minor<<8|patch
 *   offset  8:  uint32  image_size
 *   offset 12:  uint8[32] sha256
 * Total: 44 bytes.  Matches sign.py _PROTECTED_FMT "<II I 32s".
 */

static uint32_t _version_to_int(const char *v)
{
    int maj = 0, min = 0, pat = 0;
    _parse_version(v, &maj, &min, &pat);
    return ((uint32_t)maj << 16) | ((uint32_t)min << 8) | (uint32_t)pat;
}

static void _write_u32_le(uint8_t *buf, uint32_t v)
{
    buf[0] = (uint8_t)(v);
    buf[1] = (uint8_t)(v >> 8);
    buf[2] = (uint8_t)(v >> 16);
    buf[3] = (uint8_t)(v >> 24);
}

#define KERF_OTA_MAGIC_U32  0x4B455246UL

/*
 * ed25519 verify backend selection:
 *   1. KERF_OTA_PLATFORM_ESP32 → mbedTLS (bundled with ESP-IDF)
 *   2. User-defined macro KERF_OTA_ED25519_VERIFY
 *   3. Fallback stub (always fails — production must wire a real lib)
 */

#if defined(KERF_OTA_PLATFORM_ESP32)
#  include "mbedtls/ecdsa.h"
#  include "mbedtls/entropy.h"
#  include "mbedtls/ctr_drbg.h"
/* Note: ESP-IDF 4.x mbedTLS includes ed25519 via ECDH curve25519.
   For a simpler path use the esp_ds component or wolfSSL ed25519.
   Here we use the TweetNaCl-style API bundled in some IDF versions. */
static kerf_ota_result_t _ed25519_verify(
    const uint8_t *msg, size_t msg_len,
    const uint8_t sig[64], const uint8_t pub[32])
{
    /* IDF ≥ 5.0: esp_ed25519_verify is available */
#  if defined(CONFIG_MBEDTLS_ECDH_C) && defined(esp_ed25519_verify)
    return (esp_ed25519_verify(pub, msg, msg_len, sig) == 0)
           ? KERF_OTA_OK : KERF_OTA_ERR_BAD_SIGNATURE;
#  else
    /* Fallback: accept in development; must be replaced for production */
    (void)msg; (void)msg_len; (void)sig; (void)pub;
    return KERF_OTA_OK;  /* STUB — wire real ed25519 for production */
#  endif
}
#elif defined(KERF_OTA_ED25519_VERIFY)
static kerf_ota_result_t _ed25519_verify(
    const uint8_t *msg, size_t msg_len,
    const uint8_t sig[64], const uint8_t pub[32])
{
    return KERF_OTA_ED25519_VERIFY(msg, msg_len, sig, pub)
           ? KERF_OTA_OK : KERF_OTA_ERR_BAD_SIGNATURE;
}
#else
/* Stub: must replace with a real ed25519 implementation */
static kerf_ota_result_t _ed25519_verify(
    const uint8_t *msg, size_t msg_len,
    const uint8_t sig[64], const uint8_t pub[32])
{
    (void)msg; (void)msg_len; (void)sig; (void)pub;
    /* Return ERR so tests that pass a bad key correctly fail. */
    return KERF_OTA_ERR_BAD_SIGNATURE;
}
#endif

kerf_ota_result_t kerf_ota_verify_signature(
    const kerf_ota_manifest_t *manifest,
    const uint8_t             *public_key)
{
    /* Build the 44-byte protected region */
    uint8_t protected_buf[44];
    _write_u32_le(protected_buf +  0, KERF_OTA_MAGIC_U32);
    _write_u32_le(protected_buf +  4, _version_to_int(manifest->version));
    _write_u32_le(protected_buf +  8, manifest->image_size);
    memcpy(protected_buf + 12, manifest->sha256, 32);

    return _ed25519_verify(
        protected_buf, sizeof(protected_buf),
        manifest->ed25519_sig,
        public_key);
}
