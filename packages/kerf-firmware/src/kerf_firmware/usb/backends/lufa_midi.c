/*
 * lufa_midi.c — LUFA backend for kerf_usb_midi.h
 *
 * Target board: ATmega32U4 — Arduino Pro Micro, Leonardo, Micro.
 *
 * LUFA dependency: https://github.com/abcminiuser/lufa
 * Requires LUFA MIDI class driver headers in the include path.
 *
 * Build with: -mmcu=atmega32u4 -DF_CPU=16000000UL -DF_USB=16000000UL
 *
 * KERF_LUFA_STUB: compile-without-LUFA mode for Kerf test harness.
 */

#include "../kerf_usb_midi.h"
#include <string.h>

#ifdef KERF_LUFA_STUB
/* Minimal stubs — activated when LUFA headers are absent */
#include <stdint.h>

typedef struct { uint8_t data[4]; } MIDI_EventPacket_t;
typedef struct { } USB_ClassInfo_MIDI_Device_t;

static USB_ClassInfo_MIDI_Device_t _MIDIInterface;

#define MIDI_Device_SendEventPacket(iface, pkt)   ((bool)1)
#define MIDI_Device_Flush(iface)                  ((void)0)
#define MIDI_Device_ReceiveEventPacket(iface, pkt) ((bool)0)
#define USB_Init()                                 ((void)0)
#define USB_USBTask()                              ((void)0)
#define MIDI_Device_USBTask(iface)                 ((void)0)
#define MIDI_COMMAND_NOTE_ON  0x09
#define MIDI_COMMAND_NOTE_OFF 0x08
#define MIDI_COMMAND_CONTROL_CHANGE 0x0B

#else
/* Real LUFA build */
#include <LUFA/Drivers/USB/USB.h>
#include <LUFA/Drivers/USB/Class/MIDIClass.h>
extern USB_ClassInfo_MIDI_Device_t _MIDIInterface;
#endif /* KERF_LUFA_STUB */

/* ── Module state ────────────────────────────────────────────────────────── */

static kerf_midi_note_cb_t _note_cb = NULL;
static kerf_midi_cc_cb_t   _cc_cb   = NULL;

/* ── Init ────────────────────────────────────────────────────────────────── */

void kerf_usb_midi_init(void)
{
#ifndef KERF_LUFA_STUB
    USB_Init();
#endif
}

/* ── Transmit ────────────────────────────────────────────────────────────── */

int kerf_usb_midi_send_note(uint8_t channel, uint8_t note,
                             uint8_t velocity, uint8_t on)
{
    MIDI_EventPacket_t pkt;
    memset(&pkt, 0, sizeof(pkt));

#ifdef KERF_LUFA_STUB
    uint8_t code   = on ? (uint8_t)MIDI_COMMAND_NOTE_ON
                        : (uint8_t)MIDI_COMMAND_NOTE_OFF;
    uint8_t status = on ? (uint8_t)(0x90u | (channel & 0x0Fu))
                        : (uint8_t)(0x80u | (channel & 0x0Fu));
    pkt.data[0] = code;
    pkt.data[1] = status;
    pkt.data[2] = note     & 0x7Fu;
    pkt.data[3] = velocity & 0x7Fu;
    (void)pkt;
    return 0;
#else
    pkt.Data1 = on ? (uint8_t)(0x90u | (channel & 0x0Fu))
                   : (uint8_t)(0x80u | (channel & 0x0Fu));
    pkt.Data2 = note     & 0x7Fu;
    pkt.Data3 = velocity & 0x7Fu;
    pkt.Event = MIDI_EVENT(0, on ? MIDI_COMMAND_NOTE_ON : MIDI_COMMAND_NOTE_OFF);
    bool ok = MIDI_Device_SendEventPacket(&_MIDIInterface, &pkt);
    MIDI_Device_Flush(&_MIDIInterface);
    return ok ? 0 : -1;
#endif
}

int kerf_usb_midi_send_cc(uint8_t channel, uint8_t control, uint8_t value)
{
    MIDI_EventPacket_t pkt;
    memset(&pkt, 0, sizeof(pkt));

#ifdef KERF_LUFA_STUB
    pkt.data[0] = (uint8_t)MIDI_COMMAND_CONTROL_CHANGE;
    pkt.data[1] = (uint8_t)(0xB0u | (channel & 0x0Fu));
    pkt.data[2] = control & 0x7Fu;
    pkt.data[3] = value   & 0x7Fu;
    (void)pkt;
    return 0;
#else
    pkt.Data1 = (uint8_t)(0xB0u | (channel & 0x0Fu));
    pkt.Data2 = control & 0x7Fu;
    pkt.Data3 = value   & 0x7Fu;
    pkt.Event = MIDI_EVENT(0, MIDI_COMMAND_CONTROL_CHANGE);
    bool ok = MIDI_Device_SendEventPacket(&_MIDIInterface, &pkt);
    MIDI_Device_Flush(&_MIDIInterface);
    return ok ? 0 : -1;
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

/* ── Main-loop task (no-op on LUFA — USB handled by ISR) ────────────────── */

void kerf_usb_midi_task(void)
{
#ifndef KERF_LUFA_STUB
    USB_USBTask();
    MIDI_Device_USBTask(&_MIDIInterface);

    MIDI_EventPacket_t pkt;
    while (MIDI_Device_ReceiveEventPacket(&_MIDIInterface, &pkt))
    {
        uint8_t msg_type = pkt.Data1 & 0xF0u;
        uint8_t channel  = pkt.Data1 & 0x0Fu;

        if ((msg_type == 0x90u || msg_type == 0x80u) && _note_cb)
        {
            uint8_t is_on = (msg_type == 0x90u) && (pkt.Data3 > 0);
            _note_cb(channel, pkt.Data2, pkt.Data3, is_on);
        }
        else if (msg_type == 0xB0u && _cc_cb)
        {
            _cc_cb(channel, pkt.Data2, pkt.Data3);
        }
    }
#endif
}
