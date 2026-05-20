/*
 * tinyusb_midi.c — TinyUSB backend for kerf_usb_midi.h
 *
 * Target boards: Teensy 4.0/4.1 (Cortex-M7), Teensy 3.2/3.6 (Cortex-M4),
 *                RP2040, SAMD21/51, nRF52840, ESP32-S2/S3.
 *
 * Compile this file when KERF_USB_BACKEND_TINYUSB is defined.
 * Do NOT compile lufa_midi.c on the same target.
 *
 * TinyUSB dependency: https://github.com/hathach/tinyusb
 * Include path must contain tusb.h (provided by the board's BSP).
 *
 * Build guards
 * ------------
 * The file compiles cleanly even when the TinyUSB headers are absent (stub
 * path) so the Kerf test harness (subprocess-mocked gcc) can syntax-check it
 * without a real toolchain + BSP present.  The stubs are activated when
 * KERF_TINYUSB_STUB is defined (set automatically in the test build).
 */

#include "../kerf_usb_midi.h"

/* ── TinyUSB / stub headers ─────────────────────────────────────────────── */

#ifdef KERF_TINYUSB_STUB
/* Minimal stubs so the file compiles without TinyUSB installed. */
#include <stdint.h>
#include <stddef.h>
#include <string.h>

typedef uint8_t  uint8_t;   /* already defined */
#define tud_midi_available()        0
#define tud_midi_stream_read(a, n)  0
#define tud_midi_stream_write(cn, p, n) ((void)(p), (n))
#define tud_task()                  ((void)0)
#define tusb_init()                 1

#else
/* Real TinyUSB build. */
#include "tusb.h"
#endif /* KERF_TINYUSB_STUB */

/* ── Module state ────────────────────────────────────────────────────────── */

static kerf_midi_note_cb_t _note_cb = NULL;
static kerf_midi_cc_cb_t   _cc_cb   = NULL;

/* ── Init ────────────────────────────────────────────────────────────────── */

void kerf_usb_midi_init(void)
{
#ifndef KERF_TINYUSB_STUB
    tusb_init();
#endif
}

/* ── Transmit ────────────────────────────────────────────────────────────── */

int kerf_usb_midi_send_note(uint8_t channel, uint8_t note,
                             uint8_t velocity, uint8_t on)
{
    /*
     * USB-MIDI packet: 4 bytes
     *   [0] Cable/code-index  (0x09 = Note-On, 0x08 = Note-Off)
     *   [1] Status byte       (0x90 | channel) or (0x80 | channel)
     *   [2] Note number
     *   [3] Velocity
     */
    uint8_t status = on ? (0x90u | (channel & 0x0Fu))
                        : (0x80u | (channel & 0x0Fu));
    uint8_t code   = on ? 0x09u : 0x08u;
    uint8_t pkt[4] = { code, status, note & 0x7Fu, velocity & 0x7Fu };

#ifdef KERF_TINYUSB_STUB
    (void)pkt;
    return 0;
#else
    uint32_t written = tud_midi_stream_write(0, pkt, 4);
    return (written == 4) ? 0 : -1;
#endif
}

int kerf_usb_midi_send_cc(uint8_t channel, uint8_t control, uint8_t value)
{
    /*
     * USB-MIDI CC packet:
     *   [0] 0x0B  (code-index = Control Change)
     *   [1] 0xB0 | channel
     *   [2] control number
     *   [3] value
     */
    uint8_t pkt[4] = {
        0x0Bu,
        (uint8_t)(0xB0u | (channel & 0x0Fu)),
        control & 0x7Fu,
        value   & 0x7Fu,
    };

#ifdef KERF_TINYUSB_STUB
    (void)pkt;
    return 0;
#else
    uint32_t written = tud_midi_stream_write(0, pkt, 4);
    return (written == 4) ? 0 : -1;
#endif
}

/* ── Callbacks ───────────────────────────────────────────────────────────── */

void kerf_usb_midi_set_on_note(kerf_midi_note_cb_t cb)
{
    _note_cb = cb;
}

void kerf_usb_midi_set_on_cc(kerf_midi_cc_cb_t cb)
{
    _cc_cb = cb;
}

/* ── Main-loop task ──────────────────────────────────────────────────────── */

void kerf_usb_midi_task(void)
{
#ifndef KERF_TINYUSB_STUB
    tud_task();
#endif

    /*
     * Drain the receive FIFO.  Each USB-MIDI packet is 4 bytes.
     * Dispatch note-on/off and CC messages to the registered callbacks.
     */
#ifndef KERF_TINYUSB_STUB
    uint8_t pkt[4];
    while (tud_midi_available())
    {
        uint32_t n = tud_midi_stream_read(pkt, 4);
        if (n < 4)
            continue;

        uint8_t msg_type = pkt[1] & 0xF0u;
        uint8_t channel  = pkt[1] & 0x0Fu;

        if ((msg_type == 0x90u || msg_type == 0x80u) && _note_cb)
        {
            uint8_t is_on = (msg_type == 0x90u) && (pkt[3] > 0);
            _note_cb(channel, pkt[2], pkt[3], is_on);
        }
        else if (msg_type == 0xB0u && _cc_cb)
        {
            _cc_cb(channel, pkt[2], pkt[3]);
        }
    }
#endif
}
