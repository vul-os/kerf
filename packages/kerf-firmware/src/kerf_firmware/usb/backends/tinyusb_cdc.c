/*
 * tinyusb_cdc.c — TinyUSB backend for kerf_usb_cdc.h
 *
 * Target boards: Teensy 4.0/4.1, RP2040, SAMD21/51, nRF52840, ESP32-S2/S3.
 *
 * KERF_TINYUSB_STUB: compile-without-BSP mode.
 */

#include "../kerf_usb_cdc.h"
#include <stddef.h>
#include <string.h>

#ifdef KERF_TINYUSB_STUB
#include <stdint.h>

/* Minimal stubs */
static uint8_t _stub_rx_buf[256];
static int     _stub_rx_head = 0;
static int     _stub_rx_tail = 0;

#define tud_task()                         ((void)0)
#define tusb_init()                        1
#define tud_cdc_connected()                0
#define tud_cdc_write(buf, n)              ((uint32_t)(n))
#define tud_cdc_write_flush()              ((void)0)
#define tud_cdc_available()                (_stub_rx_tail - _stub_rx_head)
#define tud_cdc_read(buf, n)               0

#else
#include "tusb.h"
#endif /* KERF_TINYUSB_STUB */

/* ── Init ────────────────────────────────────────────────────────────────── */

void kerf_usb_cdc_init(void)
{
#ifndef KERF_TINYUSB_STUB
    tusb_init();
#endif
}

/* ── Connected ───────────────────────────────────────────────────────────── */

int kerf_usb_cdc_connected(void)
{
#ifdef KERF_TINYUSB_STUB
    return 0;
#else
    return tud_cdc_connected() ? 1 : 0;
#endif
}

/* ── Transmit ────────────────────────────────────────────────────────────── */

int kerf_usb_cdc_write(const uint8_t *buf, size_t len)
{
    if (!buf || len == 0)
        return 0;
#ifdef KERF_TINYUSB_STUB
    (void)buf;
    return (int)len;
#else
    uint32_t written = tud_cdc_write(buf, (uint32_t)len);
    return (int)written;
#endif
}

int kerf_usb_cdc_print(const char *s)
{
    if (!s)
        return 0;
    return kerf_usb_cdc_write((const uint8_t *)s, strlen(s));
}

void kerf_usb_cdc_flush(void)
{
#ifndef KERF_TINYUSB_STUB
    tud_cdc_write_flush();
#endif
}

/* ── Receive ─────────────────────────────────────────────────────────────── */

int kerf_usb_cdc_read(uint8_t *buf, size_t max_len)
{
    if (!buf || max_len == 0)
        return 0;
#ifdef KERF_TINYUSB_STUB
    (void)buf;
    return 0;
#else
    uint32_t avail = tud_cdc_available();
    if (avail == 0)
        return 0;
    uint32_t to_read = avail < (uint32_t)max_len ? avail : (uint32_t)max_len;
    return (int)tud_cdc_read(buf, to_read);
#endif
}

int kerf_usb_cdc_available(void)
{
#ifdef KERF_TINYUSB_STUB
    return 0;
#else
    return (int)tud_cdc_available();
#endif
}

/* ── Task ────────────────────────────────────────────────────────────────── */

void kerf_usb_cdc_task(void)
{
#ifndef KERF_TINYUSB_STUB
    tud_task();
#endif
}
