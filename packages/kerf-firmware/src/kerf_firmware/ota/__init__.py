"""kerf_firmware.ota — OTA (over-the-air) firmware update support.

Host side:  sign.py — package and sign a firmware image with ed25519.
Device side: C headers (kerf_ota.h) + platform backends (esp32, stm32, samd).

AVR (ATmega328P / ATmega2560) is explicitly out of scope: insufficient flash
for a dual-partition layout.  kerf_ota_check() returns the sentinel
KERF_OTA_ERR_AVR_UNSUPPORTED on AVR builds.
"""
from __future__ import annotations

from kerf_firmware.ota.sign import OTAManifest, OTASigner, OTAVerifier

__all__ = ["OTAManifest", "OTASigner", "OTAVerifier"]
