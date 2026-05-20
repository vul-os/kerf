/*
 * lufa_cdc.c — LUFA backend for kerf_usb_cdc.h
 *
 * Target board: ATmega32U4 — Arduino Pro Micro, Leonardo, Micro.
 *
 * KERF_LUFA_STUB: compile-without-LUFA mode.
 */

#include "../kerf_usb_cdc.h"
#include <string.h>

#ifdef KERF_LUFA_STUB
#include <stdint.h>
#include <stddef.h>

typedef struct { } USB_ClassInfo_CDC_Device_t;
static USB_ClassInfo_CDC_Device_t _CDCInterface;

#define CDC_Device_IsLineTerminationsCharReceived(i)  0
#define CDC_Device_BytesReceived(i)                   0
#define CDC_Device_ReceiveByte(i)                     0
#define CDC_Device_SendData(i, buf, n)               ((uint8_t)0)
#define CDC_Device_Flush(i)                          ((void)0)
#define USB_Init()                                   ((void)0)
#define USB_USBTask()                                ((void)0)
#define CDC_Device_USBTask(i)                        ((void)0)

static inline int _cdc_connected(void) { return 0; }

#else
#include <LUFA/Drivers/USB/USB.h>
#include <LUFA/Drivers/USB/Class/CDCClass.h>
extern USB_ClassInfo_CDC_Device_t _CDCInterface;
static inline int _cdc_connected(void)
{
    return (_CDCInterface.State.ControlLineStates.HostToDevice &
            CDC_CONTROL_LINE_OUT_DTR) ? 1 : 0;
}
#endif /* KERF_LUFA_STUB */

/* ── Init ────────────────────────────────────────────────────────────────── */

void kerf_usb_cdc_init(void)
{
#ifndef KERF_LUFA_STUB
    USB_Init();
#endif
}

/* ── Connected ───────────────────────────────────────────────────────────── */

int kerf_usb_cdc_connected(void)
{
    return _cdc_connected();
}

/* ── Transmit ────────────────────────────────────────────────────────────── */

int kerf_usb_cdc_write(const uint8_t *buf, size_t len)
{
    if (!buf || len == 0)
        return 0;
#ifdef KERF_LUFA_STUB
    (void)buf;
    return (int)len;
#else
    uint8_t err = CDC_Device_SendData(&_CDCInterface, buf, (uint16_t)len);
    if (err)
        return -1;
    return (int)len;
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
#ifndef KERF_LUFA_STUB
    CDC_Device_Flush(&_CDCInterface);
#endif
}

/* ── Receive ─────────────────────────────────────────────────────────────── */

int kerf_usb_cdc_read(uint8_t *buf, size_t max_len)
{
    if (!buf || max_len == 0)
        return 0;
#ifdef KERF_LUFA_STUB
    (void)buf;
    return 0;
#else
    int n = 0;
    while ((size_t)n < max_len && CDC_Device_BytesReceived(&_CDCInterface) > 0)
    {
        buf[n++] = CDC_Device_ReceiveByte(&_CDCInterface);
    }
    return n;
#endif
}

int kerf_usb_cdc_available(void)
{
#ifdef KERF_LUFA_STUB
    return 0;
#else
    return (int)CDC_Device_BytesReceived(&_CDCInterface);
#endif
}

/* ── Task ────────────────────────────────────────────────────────────────── */

void kerf_usb_cdc_task(void)
{
#ifndef KERF_LUFA_STUB
    USB_USBTask();
    CDC_Device_USBTask(&_CDCInterface);
#endif
}
