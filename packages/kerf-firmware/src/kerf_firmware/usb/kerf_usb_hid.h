/*
 * kerf_usb_hid.h — Kerf USB-HID class driver, board-agnostic public API.
 *
 * Supports three HID subclasses:
 *   - Keyboard  (boot-protocol + 6-key NKRO report)
 *   - Mouse     (X/Y/wheel + buttons)
 *   - Gamepad   (8-bit X/Y + 16 buttons)
 *
 * Backend selection (defined by the build system):
 *   KERF_USB_BACKEND_TINYUSB  — Arm / ESP32 / RP2040
 *   KERF_USB_BACKEND_LUFA     — ATmega32U4
 *
 * HID Report descriptor constants
 * --------------------------------
 * The HID keyboard report descriptor for a standard boot-protocol keyboard
 * is embedded in the backend translation units.  The expected descriptor
 * prefix that callers/tests can verify is published here as a macro for
 * documentation purposes only.
 *
 * HID Usage page 0x01 (Generic Desktop) + Usage 0x06 (Keyboard) is the
 * canonical USB HID keyboard descriptor.  The full 8-byte boot keyboard
 * report is: [modifier, reserved, key0 … key5].
 *
 * F13 through F24 are HID keycodes 0x68 – 0x73.
 */

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

/* ── HID keycode aliases (subset) ───────────────────────────────────────── */

#define KERF_HID_KEY_NONE   0x00
#define KERF_HID_KEY_A      0x04
#define KERF_HID_KEY_Z      0x1D
#define KERF_HID_KEY_1      0x1E
#define KERF_HID_KEY_F1     0x3A
#define KERF_HID_KEY_F12    0x45
#define KERF_HID_KEY_F13    0x68
#define KERF_HID_KEY_F14    0x69
#define KERF_HID_KEY_F15    0x6A
#define KERF_HID_KEY_F16    0x6B
#define KERF_HID_KEY_F17    0x6C
#define KERF_HID_KEY_F18    0x6D
#define KERF_HID_KEY_F19    0x6E
#define KERF_HID_KEY_F20    0x6F
#define KERF_HID_KEY_F21    0x70
#define KERF_HID_KEY_F22    0x71
#define KERF_HID_KEY_F23    0x72
#define KERF_HID_KEY_F24    0x73
#define KERF_HID_KEY_ENTER  0x28
#define KERF_HID_KEY_SPACE  0x2C
#define KERF_HID_KEY_ESC    0x29

/* ── HID modifier bitmask ───────────────────────────────────────────────── */

#define KERF_HID_MOD_LCTRL  (1u << 0)
#define KERF_HID_MOD_LSHIFT (1u << 1)
#define KERF_HID_MOD_LALT   (1u << 2)
#define KERF_HID_MOD_LGUI   (1u << 3)
#define KERF_HID_MOD_RCTRL  (1u << 4)
#define KERF_HID_MOD_RSHIFT (1u << 5)
#define KERF_HID_MOD_RALT   (1u << 6)
#define KERF_HID_MOD_RGUI   (1u << 7)

/* ── Keyboard report (6-key rollover boot protocol) ─────────────────────── */

typedef struct {
    uint8_t modifier;    /**< Bitmask of KERF_HID_MOD_* */
    uint8_t reserved;    /**< Always 0 */
    uint8_t keycode[6];  /**< Up to 6 simultaneous keycodes */
} kerf_hid_keyboard_report_t;

/* ── Mouse report ────────────────────────────────────────────────────────── */

typedef struct {
    uint8_t buttons; /**< Button bitmask: bit0=left, bit1=right, bit2=middle */
    int8_t  x;       /**< X displacement -127..127 */
    int8_t  y;       /**< Y displacement -127..127 */
    int8_t  wheel;   /**< Scroll wheel -127..127 */
} kerf_hid_mouse_report_t;

/* ── Gamepad report ──────────────────────────────────────────────────────── */

typedef struct {
    int8_t   x;        /**< Left stick X -127..127 */
    int8_t   y;        /**< Left stick Y -127..127 */
    uint16_t buttons;  /**< 16 button bitmask */
} kerf_hid_gamepad_report_t;

/* ── Initialisation ─────────────────────────────────────────────────────── */

/**
 * Initialise the USB stack and enumerate as a composite USB-HID device
 * (keyboard + mouse + gamepad interfaces).
 * Call once before the main loop.
 */
void kerf_usb_hid_init(void);

/* ── Keyboard ────────────────────────────────────────────────────────────── */

/**
 * Send a keyboard HID report.
 * @param report  Pointer to a filled kerf_hid_keyboard_report_t.
 * @return        0 on success, negative on error.
 */
int kerf_usb_hid_keyboard_send(const kerf_hid_keyboard_report_t *report);

/**
 * Convenience: press a single key (with optional modifier), then release.
 * Sends two HID reports: key-down then key-up.
 *
 * @param modifier  Modifier bitmask (0 for none).
 * @param keycode   HID keycode (KERF_HID_KEY_*).
 * @return          0 on success.
 */
int kerf_usb_hid_keyboard_press(uint8_t modifier, uint8_t keycode);

/** Send an all-zeros (key-up) keyboard report. */
int kerf_usb_hid_keyboard_release(void);

/* ── Mouse ───────────────────────────────────────────────────────────────── */

/**
 * Send a mouse HID report.
 * @param report  Pointer to a filled kerf_hid_mouse_report_t.
 * @return        0 on success, negative on error.
 */
int kerf_usb_hid_mouse_send(const kerf_hid_mouse_report_t *report);

/* ── Gamepad ─────────────────────────────────────────────────────────────── */

/**
 * Send a gamepad HID report.
 * @param report  Pointer to a filled kerf_hid_gamepad_report_t.
 * @return        0 on success, negative on error.
 */
int kerf_usb_hid_gamepad_send(const kerf_hid_gamepad_report_t *report);

/* ── Main-loop hook ──────────────────────────────────────────────────────── */

/**
 * Service the USB stack. Call from the main loop on TinyUSB boards.
 * No-op on LUFA boards (handled by ISR).
 */
void kerf_usb_hid_task(void);

#ifdef __cplusplus
}
#endif
