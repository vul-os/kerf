/*
 * kerf_usb_midi.h — Kerf USB-MIDI class driver, board-agnostic public API.
 *
 * Backend selection:
 *   Define KERF_USB_BACKEND_TINYUSB  (Arm / ESP32 boards: Teensy 4.x,
 *                                      RP2040, SAMD21/51, nRF52840, ESP32-S2/S3)
 *   Define KERF_USB_BACKEND_LUFA     (ATmega32U4: Pro Micro, Leonardo, Micro)
 *
 * The calling code must include only this header; the correct backend
 * implementation file (tinyusb_midi.c or lufa_midi.c) is compiled by the
 * build system based on the resolved board arch.
 *
 * API
 * ---
 *   kerf_usb_midi_init()
 *   kerf_usb_midi_send_note(channel, note, velocity, on)
 *   kerf_usb_midi_send_cc(channel, control, value)
 *   kerf_usb_midi_set_on_note(cb)   — register note-on/off callback
 *   kerf_usb_midi_set_on_cc(cb)     — register control-change callback
 *   kerf_usb_midi_task()            — call from main loop (TinyUSB only)
 */

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* ── Callback typedefs ──────────────────────────────────────────────────── */

/**
 * Called when a MIDI note-on (velocity > 0) or note-off (velocity == 0 or
 * explicit note-off) is received from the USB host.
 *
 * @param channel   MIDI channel 0–15
 * @param note      MIDI note number 0–127
 * @param velocity  Velocity 0–127 (0 = note-off)
 * @param on        1 = note-on, 0 = note-off
 */
typedef void (*kerf_midi_note_cb_t)(uint8_t channel, uint8_t note,
                                     uint8_t velocity, uint8_t on);

/**
 * Called when a Control-Change (CC) message is received from the USB host.
 *
 * @param channel  MIDI channel 0–15
 * @param control  CC number 0–127
 * @param value    CC value 0–127
 */
typedef void (*kerf_midi_cc_cb_t)(uint8_t channel, uint8_t control,
                                   uint8_t value);

/* ── Initialisation ─────────────────────────────────────────────────────── */

/**
 * Initialise the USB stack and enumerate as a USB-MIDI device.
 * Call once before the main loop.
 */
void kerf_usb_midi_init(void);

/* ── Transmit helpers ────────────────────────────────────────────────────── */

/**
 * Send a Note-On or Note-Off MIDI message.
 *
 * @param channel   MIDI channel 0–15
 * @param note      MIDI note number 0–127
 * @param velocity  Velocity 0–127
 * @param on        1 = Note-On, 0 = Note-Off
 * @return          0 on success, negative on error / buffer full
 */
int kerf_usb_midi_send_note(uint8_t channel, uint8_t note,
                             uint8_t velocity, uint8_t on);

/**
 * Send a Control-Change (CC) MIDI message.
 *
 * @param channel  MIDI channel 0–15
 * @param control  CC number 0–127
 * @param value    CC value 0–127
 * @return         0 on success, negative on error / buffer full
 */
int kerf_usb_midi_send_cc(uint8_t channel, uint8_t control, uint8_t value);

/* ── Receive callbacks ───────────────────────────────────────────────────── */

/** Register (or replace) the note-on/off callback. Pass NULL to disable. */
void kerf_usb_midi_set_on_note(kerf_midi_note_cb_t cb);

/** Register (or replace) the CC callback. Pass NULL to disable. */
void kerf_usb_midi_set_on_cc(kerf_midi_cc_cb_t cb);

/* ── Main-loop hook (TinyUSB) ────────────────────────────────────────────── */

/**
 * Must be called from the main loop to service the TinyUSB task and
 * drain the receive FIFO.  On LUFA boards this is a no-op (USB_USBTask
 * is called from an ISR).
 */
void kerf_usb_midi_task(void);

#ifdef __cplusplus
}
#endif
