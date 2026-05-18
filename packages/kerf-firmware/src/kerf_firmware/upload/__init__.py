"""
kerf_firmware.upload — upload wrappers for avrdude / esptool / stm32flash / bossac.

Each wrapper subprocess-shells out to the corresponding upload tool.
If the tool binary is not on PATH, it returns an UploadResult with
status="pending" and a human-readable reason.

Public API
----------
UploadResult
    Named return type shared by all wrappers.

upload_avrdude(hex_or_bin_path, port, board_meta) -> UploadResult
upload_esptool(hex_or_bin_path, port, board_meta) -> UploadResult
upload_stm32flash(hex_or_bin_path, port, board_meta) -> UploadResult
upload_bossac(hex_or_bin_path, port, board_meta) -> UploadResult
route_upload(hex_or_bin_path, port, board_meta) -> UploadResult
"""
from __future__ import annotations

from kerf_firmware.upload.avrdude import upload as upload_avrdude
from kerf_firmware.upload.bossac import upload as upload_bossac
from kerf_firmware.upload.esptool import upload as upload_esptool
from kerf_firmware.upload.router import route_upload
from kerf_firmware.upload.stm32flash import upload as upload_stm32flash
from kerf_firmware.upload.types import UploadResult

__all__ = [
    "UploadResult",
    "upload_avrdude",
    "upload_esptool",
    "upload_stm32flash",
    "upload_bossac",
    "route_upload",
]
