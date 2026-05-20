/**
 * esp32_backend.c — ESP32 OTA backend for kerf_ota.h
 *
 * Uses the ESP-IDF esp_ota_ops API for dual-partition OTA:
 *   esp_ota_begin()  → esp_ota_write()  → esp_ota_end()  → esp_ota_set_boot_partition()
 *
 * Compile-time guard: this file is only compiled when
 * -DKERF_OTA_PLATFORM_ESP32 is defined.
 *
 * Platform layout:
 *   Partition table must include at least two OTA slots (ota_0, ota_1) plus
 *   an ota_data partition so ESP-IDF can track the active slot.
 *   The standard ESP-IDF menuconfig "Factory + two OTA" layout is required.
 *
 * Security:
 *   kerf_ota_verify_signature() is called in kerf_ota_check() before
 *   esp_ota_begin() — no flash write occurs if the signature is invalid.
 */

#ifdef KERF_OTA_PLATFORM_ESP32

#include "kerf_ota.h"

/* ESP-IDF headers (available when compiling for ESP32 target) */
#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_system.h"
#include "mbedtls/sha256.h"

#include <string.h>
#include <stdlib.h>

static const char *TAG = "kerf_ota";

#define OTA_RECV_TIMEOUT_MS  5000
#define OTA_CHUNK_SIZE       4096

/* --------------------------------------------------------------------------
 * Internal: fetch manifest JSON over HTTP.
 * Returns KERF_OTA_OK on success, sets json_out (caller must free).
 * -------------------------------------------------------------------------- */
static kerf_ota_result_t _fetch_manifest(const char *url, char **json_out)
{
    esp_http_client_config_t cfg = {
        .url            = url,
        .timeout_ms     = OTA_RECV_TIMEOUT_MS,
        .transport_type = HTTP_TRANSPORT_OVER_TCP,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) return KERF_OTA_ERR_NETWORK;

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        return KERF_OTA_ERR_NETWORK;
    }

    int content_len = esp_http_client_fetch_headers(client);
    if (content_len <= 0) content_len = 1024;

    char *buf = (char *)malloc(content_len + 1);
    if (!buf) {
        esp_http_client_cleanup(client);
        return KERF_OTA_ERR_INTERNAL;
    }
    int read = esp_http_client_read(client, buf, content_len);
    buf[read < 0 ? 0 : read] = '\0';
    esp_http_client_cleanup(client);

    *json_out = buf;
    return KERF_OTA_OK;
}

/* --------------------------------------------------------------------------
 * Internal: download and flash to the inactive OTA partition, verifying SHA-256.
 * -------------------------------------------------------------------------- */
static kerf_ota_result_t _download_and_flash(
    const char *url,
    const kerf_ota_manifest_t *manifest)
{
    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (!update_partition) {
        ESP_LOGE(TAG, "No OTA partition available");
        return KERF_OTA_ERR_PARTITION;
    }

    esp_ota_handle_t ota_handle;
    esp_err_t err = esp_ota_begin(update_partition, OTA_SIZE_UNKNOWN, &ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_begin failed: %s", esp_err_to_name(err));
        return KERF_OTA_ERR_FLASH_WRITE;
    }

    /* Streaming download + SHA-256 accumulation */
    esp_http_client_config_t cfg = {
        .url            = url,
        .timeout_ms     = OTA_RECV_TIMEOUT_MS,
        .transport_type = HTTP_TRANSPORT_OVER_TCP,
    };
    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        esp_ota_abort(ota_handle);
        return KERF_OTA_ERR_NETWORK;
    }
    esp_http_client_open(client, 0);
    esp_http_client_fetch_headers(client);

    mbedtls_sha256_context sha_ctx;
    mbedtls_sha256_init(&sha_ctx);
    mbedtls_sha256_starts(&sha_ctx, 0 /* SHA-256 */);

    uint8_t chunk[OTA_CHUNK_SIZE];
    uint32_t total = 0;
    int read;
    kerf_ota_result_t rc = KERF_OTA_OK;

    while ((read = esp_http_client_read(client, (char *)chunk, OTA_CHUNK_SIZE)) > 0) {
        mbedtls_sha256_update(&sha_ctx, chunk, read);
        err = esp_ota_write(ota_handle, chunk, read);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "esp_ota_write failed at offset %u", total);
            rc = KERF_OTA_ERR_FLASH_WRITE;
            break;
        }
        total += read;
    }
    esp_http_client_cleanup(client);

    if (rc != KERF_OTA_OK) {
        esp_ota_abort(ota_handle);
        return rc;
    }

    /* Verify SHA-256 */
    uint8_t digest[32];
    mbedtls_sha256_finish(&sha_ctx, digest);
    mbedtls_sha256_free(&sha_ctx);

    if (memcmp(digest, manifest->sha256, 32) != 0) {
        ESP_LOGE(TAG, "SHA-256 mismatch — aborting OTA");
        esp_ota_abort(ota_handle);
        return KERF_OTA_ERR_BAD_HASH;
    }

    err = esp_ota_end(ota_handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_end failed: %s", esp_err_to_name(err));
        return KERF_OTA_ERR_FLASH_WRITE;
    }

    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_ota_set_boot_partition failed: %s", esp_err_to_name(err));
        return KERF_OTA_ERR_FLASH_WRITE;
    }

    ESP_LOGI(TAG, "OTA complete — rebooting to slot %s", update_partition->label);
    esp_restart();  /* does not return */
    return KERF_OTA_OK;
}

/* --------------------------------------------------------------------------
 * kerf_ota_check — main entry point (ESP32 implementation)
 * -------------------------------------------------------------------------- */
kerf_ota_result_t kerf_ota_check(
    const char    *manifest_url,
    const char    *current_version,
    const uint8_t *public_key,
    size_t         public_key_len)
{
    if (public_key_len != 32) return KERF_OTA_ERR_INTERNAL;

    char *json = NULL;
    kerf_ota_result_t rc = _fetch_manifest(manifest_url, &json);
    if (rc != KERF_OTA_OK) return rc;

    kerf_ota_manifest_t manifest;
    rc = kerf_ota_parse_manifest(json, &manifest);
    free(json);
    if (rc != KERF_OTA_OK) return rc;

    if (kerf_ota_version_compare(manifest.version, current_version) <= 0) {
        return KERF_OTA_OK_NO_UPDATE;
    }

    /* IMPORTANT: verify signature BEFORE any flash write */
    rc = kerf_ota_verify_signature(&manifest, public_key);
    if (rc != KERF_OTA_OK) return rc;  /* KERF_OTA_ERR_BAD_SIGNATURE */

    return _download_and_flash(manifest.download_url, &manifest);
}

#endif /* KERF_OTA_PLATFORM_ESP32 */
