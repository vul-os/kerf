/*
 * kerf_usb_cdc.h — Kerf USB-CDC (Communications Device Class) driver,
 *                  board-agnostic public API.
 *
 * Enumerates the microcontroller as a virtual serial port (VCP / ttyACM0
 * on Linux, COMn on Windows) accessible from the host over USB.
 *
 * Backend selection (defined by the build system):
 *   KERF_USB_BACKEND_TINYUSB  — Arm / ESP32 / RP2040
 *   KERF_USB_BACKEND_LUFA     — ATmega32U4
 *
 * Typical usage
 * -------------
 *   kerf_usb_cdc_init();
 *   // ... main loop ...
 *   kerf_usb_cdc_task();   // service USB task + drain Rx FIFO
 *   kerf_usb_cdc_write("Hello\r\n", 7);
 *
 *   uint8_t buf[64];
 *   int n = kerf_usb_cdc_read(buf, sizeof(buf));
 *   if (n > 0) { ... process n bytes ... }
 */

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>
#include <stddef.h>

/* ── Initialisation ─────────────────────────────────────────────────────── */

/**
 * Initialise the USB stack and enumerate as a CDC ACM (virtual COM port)
 * device.  Call once before the main loop.
 */
void kerf_usb_cdc_init(void);

/* ── Connected check ────────────────────────────────────────────────────── */

/**
 * @return  1 if the host has opened the CDC serial port (DTR set),
 *          0 otherwise.
 */
int kerf_usb_cdc_connected(void);

/* ── Transmit ────────────────────────────────────────────────────────────── */

/**
 * Write *len* bytes from *buf* to the CDC TX FIFO.
 *
 * Bytes may be buffered until the next USB IN transaction.  Call
 * kerf_usb_cdc_flush() to force immediate transmission.
 *
 * @param buf  Data to transmit.
 * @param len  Number of bytes.
 * @return     Number of bytes actually written (may be less than len if
 *             the TX buffer is full), or negative on error.
 */
int kerf_usb_cdc_write(const uint8_t *buf, size_t len);

/**
 * Convenience wrapper: transmit a NUL-terminated C string.
 *
 * @param s  NUL-terminated string.
 * @return   Number of bytes written.
 */
int kerf_usb_cdc_print(const char *s);

/**
 * Flush the TX FIFO — forces any buffered bytes to be transmitted in the
 * next USB IN token.
 */
void kerf_usb_cdc_flush(void);

/* ── Receive ─────────────────────────────────────────────────────────────── */

/**
 * Read up to *max_len* bytes from the CDC RX FIFO into *buf*.
 *
 * Non-blocking — returns 0 immediately when no data is available.
 *
 * @param buf      Destination buffer.
 * @param max_len  Maximum bytes to read.
 * @return         Number of bytes read, or negative on error.
 */
int kerf_usb_cdc_read(uint8_t *buf, size_t max_len);

/**
 * @return  Number of bytes waiting in the RX FIFO.
 */
int kerf_usb_cdc_available(void);

/* ── Main-loop hook ──────────────────────────────────────────────────────── */

/**
 * Service the USB stack and drain the RX FIFO.
 * Must be called from the main loop on TinyUSB boards.
 * No-op on LUFA boards (handled by ISR / USB_USBTask).
 */
void kerf_usb_cdc_task(void);

#ifdef __cplusplus
}
#endif
