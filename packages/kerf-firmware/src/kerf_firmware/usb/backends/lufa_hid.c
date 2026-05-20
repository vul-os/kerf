/*
 * lufa_hid.c — LUFA backend for kerf_usb_hid.h
 *
 * Target board: ATmega32U4 — Arduino Pro Micro, Leonardo, Micro.
 *
 * LUFA HID keyboard report descriptor follows the standard boot-protocol
 * 8-byte format:
 *   Byte 0: modifier bitmask
 *   Byte 1: reserved (0x00)
 *   Byte 2–7: keycodes (up to 6-key rollover)
 *
 * F13 keycode = 0x68.
 *
 * KERF_LUFA_STUB: compile-without-LUFA mode.
 */

#include "../kerf_usb_hid.h"
#include <string.h>

#ifdef KERF_LUFA_STUB
#include <stdint.h>

typedef struct { } USB_ClassInfo_HID_Device_t;
static USB_ClassInfo_HID_Device_t _HIDInterface;

#define HID_Device_SendReport(iface, id, rep, len) ((bool)1)
#define USB_Init()           ((void)0)
#define USB_USBTask()        ((void)0)
#define HID_Device_USBTask(i) ((void)0)

#else
#include <LUFA/Drivers/USB/USB.h>
#include <LUFA/Drivers/USB/Class/HIDClass.h>
extern USB_ClassInfo_HID_Device_t _HIDInterface;
#endif /* KERF_LUFA_STUB */

/* ── Internal report IDs ─────────────────────────────────────────────────── */
#define RPT_KEYBOARD  1
#define RPT_MOUSE     2
#define RPT_GAMEPAD   3

/* ── Init ────────────────────────────────────────────────────────────────── */

void kerf_usb_hid_init(void)
{
#ifndef KERF_LUFA_STUB
    USB_Init();
#endif
}

/* ── Keyboard ────────────────────────────────────────────────────────────── */

int kerf_usb_hid_keyboard_send(const kerf_hid_keyboard_report_t *report)
{
#ifdef KERF_LUFA_STUB
    (void)report;
    return 0;
#else
    bool ok = HID_Device_SendReport(&_HIDInterface, RPT_KEYBOARD,
                                     report, sizeof(*report));
    return ok ? 0 : -1;
#endif
}

int kerf_usb_hid_keyboard_press(uint8_t modifier, uint8_t keycode)
{
    kerf_hid_keyboard_report_t rep;
    memset(&rep, 0, sizeof(rep));
    rep.modifier   = modifier;
    rep.keycode[0] = keycode;
    int rc = kerf_usb_hid_keyboard_send(&rep);
    if (rc != 0)
        return rc;
    return kerf_usb_hid_keyboard_release();
}

int kerf_usb_hid_keyboard_release(void)
{
    kerf_hid_keyboard_report_t rep;
    memset(&rep, 0, sizeof(rep));
    return kerf_usb_hid_keyboard_send(&rep);
}

/* ── Mouse ───────────────────────────────────────────────────────────────── */

int kerf_usb_hid_mouse_send(const kerf_hid_mouse_report_t *report)
{
#ifdef KERF_LUFA_STUB
    (void)report;
    return 0;
#else
    bool ok = HID_Device_SendReport(&_HIDInterface, RPT_MOUSE,
                                     report, sizeof(*report));
    return ok ? 0 : -1;
#endif
}

/* ── Gamepad ─────────────────────────────────────────────────────────────── */

int kerf_usb_hid_gamepad_send(const kerf_hid_gamepad_report_t *report)
{
#ifdef KERF_LUFA_STUB
    (void)report;
    return 0;
#else
    bool ok = HID_Device_SendReport(&_HIDInterface, RPT_GAMEPAD,
                                     report, sizeof(*report));
    return ok ? 0 : -1;
#endif
}

/* ── Task ────────────────────────────────────────────────────────────────── */

void kerf_usb_hid_task(void)
{
#ifndef KERF_LUFA_STUB
    USB_USBTask();
    HID_Device_USBTask(&_HIDInterface);
#endif
}
