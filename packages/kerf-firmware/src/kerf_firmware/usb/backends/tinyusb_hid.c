/*
 * tinyusb_hid.c — TinyUSB backend for kerf_usb_hid.h
 *
 * Target boards: Teensy 4.0/4.1, RP2040, SAMD21/51, nRF52840, ESP32-S2/S3.
 *
 * HID report descriptor layout (standard boot-protocol keyboard):
 *   Usage Page (Generic Desktop)   — 0x05, 0x01
 *   Usage (Keyboard)                — 0x09, 0x06
 *   Collection (Application)        — 0xA1, 0x01
 *     ... modifier bits, reserved byte, 6 keycode slots ...
 *   End Collection                  — 0xC0
 *
 * The F13 keycode is 0x68 per the HID Usage Tables for USB (v1.4 §10).
 *
 * KERF_TINYUSB_STUB: compile-without-BSP mode (same as tinyusb_midi.c).
 */

#include "../kerf_usb_hid.h"

#ifdef KERF_TINYUSB_STUB
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define tud_hid_keyboard_report(id, mod, keys) 0
#define tud_hid_mouse_report(id, btn, x, y, v, h) 0
#define tud_hid_gamepad_report(id, x, y, z, rz, rx, ry, hat, btns) 0
#define tud_task()  ((void)0)
#define tusb_init() 1

#else
#include "tusb.h"
#endif /* KERF_TINYUSB_STUB */

/* ── HID report-descriptor IDs ──────────────────────────────────────────── */
#define HID_ITF_KEYBOARD  0
#define HID_ITF_MOUSE     1
#define HID_ITF_GAMEPAD   2

/* ── Init ────────────────────────────────────────────────────────────────── */

void kerf_usb_hid_init(void)
{
#ifndef KERF_TINYUSB_STUB
    tusb_init();
#endif
}

/* ── Keyboard ────────────────────────────────────────────────────────────── */

int kerf_usb_hid_keyboard_send(const kerf_hid_keyboard_report_t *report)
{
#ifdef KERF_TINYUSB_STUB
    (void)report;
    return 0;
#else
    bool ok = tud_hid_keyboard_report(
        HID_ITF_KEYBOARD,
        report->modifier,
        (uint8_t *)report->keycode);
    return ok ? 0 : -1;
#endif
}

int kerf_usb_hid_keyboard_press(uint8_t modifier, uint8_t keycode)
{
    kerf_hid_keyboard_report_t rep = { 0 };
    rep.modifier   = modifier;
    rep.keycode[0] = keycode;
    int rc = kerf_usb_hid_keyboard_send(&rep);
    if (rc != 0)
        return rc;
    return kerf_usb_hid_keyboard_release();
}

int kerf_usb_hid_keyboard_release(void)
{
    kerf_hid_keyboard_report_t rep = { 0 };
    return kerf_usb_hid_keyboard_send(&rep);
}

/* ── Mouse ───────────────────────────────────────────────────────────────── */

int kerf_usb_hid_mouse_send(const kerf_hid_mouse_report_t *report)
{
#ifdef KERF_TINYUSB_STUB
    (void)report;
    return 0;
#else
    bool ok = tud_hid_mouse_report(
        HID_ITF_MOUSE,
        report->buttons,
        report->x,
        report->y,
        report->wheel,
        0);
    return ok ? 0 : -1;
#endif
}

/* ── Gamepad ─────────────────────────────────────────────────────────────── */

int kerf_usb_hid_gamepad_send(const kerf_hid_gamepad_report_t *report)
{
#ifdef KERF_TINYUSB_STUB
    (void)report;
    return 0;
#else
    bool ok = tud_hid_gamepad_report(
        HID_ITF_GAMEPAD,
        report->x,
        report->y,
        0, 0, 0, 0,   /* z, rz, rx, ry */
        0,             /* hat */
        report->buttons);
    return ok ? 0 : -1;
#endif
}

/* ── Task ────────────────────────────────────────────────────────────────── */

void kerf_usb_hid_task(void)
{
#ifndef KERF_TINYUSB_STUB
    tud_task();
#endif
}
