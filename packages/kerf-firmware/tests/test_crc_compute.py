"""Tests for kerf_firmware.crc_compute and firmware_compute_crc LLM tool.

Official test vectors (input = ASCII "123456789" hex 313233343536373839):
  CRC-8            → 0xF4      (poly 0x07, init 0x00)
  CRC-16/CCITT     → 0x29B1   (poly 0x1021, init 0xFFFF, CCITT-FALSE)
  CRC-16/MODBUS    → 0x4B37   (poly 0xA001 reflected, init 0xFFFF)
  CRC-32           → 0xCBF43926 (poly 0xEDB88320 reflected, init 0xFFFFFFFF)
  CRC-32C          → 0xE3069283 (poly 0x82F63B78 reflected, init 0xFFFFFFFF)

Sources: Williams (1993) "Painless Guide"; reveng.sourceforge.net catalogue;
IETF RFC 3720 §B.4 (CRC-32C); crccalc.com independent verification.
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.crc_compute import (
    CRCSpec,
    CRCResult,
    compute_crc,
    parse_hex_data,
    supported_algorithms,
)


# ---------------------------------------------------------------------------
# ASCII "123456789" hex string — the standard CRC test vector
# ---------------------------------------------------------------------------
CHECK_HEX = "313233343536373839"


# ---------------------------------------------------------------------------
# 1. parse_hex_data
# ---------------------------------------------------------------------------

class TestParseHexData:
    def test_clean_hex(self):
        assert parse_hex_data("DEADBEEF") == bytes([0xDE, 0xAD, 0xBE, 0xEF])

    def test_spaced_hex(self):
        assert parse_hex_data("DE AD BE EF") == bytes([0xDE, 0xAD, 0xBE, 0xEF])

    def test_0x_prefixed(self):
        assert parse_hex_data("0xDE 0xAD 0xBE 0xEF") == bytes([0xDE, 0xAD, 0xBE, 0xEF])

    def test_empty_string(self):
        assert parse_hex_data("") == b""

    def test_lowercase(self):
        assert parse_hex_data("deadbeef") == bytes([0xDE, 0xAD, 0xBE, 0xEF])

    def test_odd_nibbles_raises(self):
        with pytest.raises(ValueError, match="odd number"):
            parse_hex_data("ABC")

    def test_invalid_hex_raises(self):
        with pytest.raises(ValueError):
            parse_hex_data("ZZZZ")


# ---------------------------------------------------------------------------
# 2. CRC-8 (poly 0x07, init 0x00)
# ---------------------------------------------------------------------------

class TestCRC8:
    def test_check_vector(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-8"))
        assert r.crc_int == 0xF4, f"Expected 0xF4 got 0x{r.crc_int:02X}"

    def test_check_vector_hex_str(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-8"))
        assert r.crc_hex == "F4"

    def test_bits(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-8"))
        assert r.crc_bits == 8

    def test_polynomial_reported(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-8"))
        assert r.polynomial_hex == "0x07"

    def test_empty_input(self):
        # init=0x00, no bytes processed → CRC = 0x00
        r = compute_crc(CRCSpec(data_hex="", algorithm="CRC-8"))
        assert r.crc_int == 0x00

    def test_single_byte_ff(self):
        r = compute_crc(CRCSpec(data_hex="FF", algorithm="CRC-8"))
        # 0xFF through CRC-8 table (poly 0x07): known value
        assert isinstance(r.crc_int, int)
        assert 0 <= r.crc_int <= 0xFF

    def test_algorithm_alias_lowercase(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="crc-8"))
        assert r.crc_int == 0xF4

    def test_algorithm_alias_crc8(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="crc8"))
        assert r.crc_int == 0xF4


# ---------------------------------------------------------------------------
# 3. CRC-16/CCITT (official vector: 0x29B1)
# ---------------------------------------------------------------------------

class TestCRC16CCITT:
    def test_check_vector(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/CCITT"))
        assert r.crc_int == 0x29B1, f"Expected 0x29B1 got 0x{r.crc_int:04X}"

    def test_check_vector_hex_str(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/CCITT"))
        assert r.crc_hex == "29B1"

    def test_bits(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/CCITT"))
        assert r.crc_bits == 16

    def test_polynomial_reported(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/CCITT"))
        assert r.polynomial_hex == "0x1021"

    def test_empty_input(self):
        # init=0xFFFF, no bytes → CRC = 0xFFFF (no final XOR)
        r = compute_crc(CRCSpec(data_hex="", algorithm="CRC-16/CCITT"))
        assert r.crc_int == 0xFFFF

    def test_single_byte_00(self):
        r = compute_crc(CRCSpec(data_hex="00", algorithm="CRC-16/CCITT"))
        # 0x00 byte: crc = (0xFFFF << 8 ^ table[(0xFF ^ 0x00)]) & 0xFFFF
        assert isinstance(r.crc_int, int)
        assert 0 <= r.crc_int <= 0xFFFF

    def test_alias_crc_ccitt(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="crc-ccitt"))
        assert r.crc_int == 0x29B1

    def test_spaced_hex_input(self):
        spaced = " ".join(CHECK_HEX[i:i+2] for i in range(0, len(CHECK_HEX), 2))
        r = compute_crc(CRCSpec(data_hex=spaced, algorithm="CRC-16/CCITT"))
        assert r.crc_int == 0x29B1


# ---------------------------------------------------------------------------
# 4. CRC-16/MODBUS (official vector: 0x4B37)
# ---------------------------------------------------------------------------

class TestCRC16MODBUS:
    def test_check_vector(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/MODBUS"))
        assert r.crc_int == 0x4B37, f"Expected 0x4B37 got 0x{r.crc_int:04X}"

    def test_check_vector_hex_str(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/MODBUS"))
        assert r.crc_hex == "4B37"

    def test_bits(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/MODBUS"))
        assert r.crc_bits == 16

    def test_polynomial_reported(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-16/MODBUS"))
        assert r.polynomial_hex == "0xA001"

    def test_empty_input(self):
        # init=0xFFFF, reflected, no final XOR → CRC = 0xFFFF
        r = compute_crc(CRCSpec(data_hex="", algorithm="CRC-16/MODBUS"))
        assert r.crc_int == 0xFFFF

    def test_single_byte_01(self):
        r = compute_crc(CRCSpec(data_hex="01", algorithm="CRC-16/MODBUS"))
        assert isinstance(r.crc_int, int)
        assert 0 <= r.crc_int <= 0xFFFF

    def test_alias_lowercase(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="crc-16/modbus"))
        assert r.crc_int == 0x4B37

    def test_modbus_known_short_frame(self):
        # Modbus RTU: read coils (addr=0x01, func=0x01, start=0x0000, qty=0x0008)
        # FC request PDU before CRC: 01 01 00 00 00 08
        # CRC register = 0xCC3D; Modbus RTU transmits low byte first (0x3D), then high (0xCC).
        # The CRC integer value is 0xCC3D (Williams LSB-first convention).
        r = compute_crc(CRCSpec(data_hex="010100000008", algorithm="CRC-16/MODBUS"))
        assert r.crc_int == 0xCC3D, f"Expected 0xCC3D got 0x{r.crc_int:04X}"


# ---------------------------------------------------------------------------
# 5. CRC-32 (official vector: 0xCBF43926)
# ---------------------------------------------------------------------------

class TestCRC32:
    def test_check_vector(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32"))
        assert r.crc_int == 0xCBF43926, f"Expected 0xCBF43926 got 0x{r.crc_int:08X}"

    def test_check_vector_hex_str(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32"))
        assert r.crc_hex == "CBF43926"

    def test_bits(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32"))
        assert r.crc_bits == 32

    def test_polynomial_reported(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32"))
        assert r.polynomial_hex == "0xEDB88320"

    def test_empty_input(self):
        # init=0xFFFFFFFF XOR final 0xFFFFFFFF → 0x00000000
        r = compute_crc(CRCSpec(data_hex="", algorithm="CRC-32"))
        assert r.crc_int == 0x00000000

    def test_single_byte_00(self):
        r = compute_crc(CRCSpec(data_hex="00", algorithm="CRC-32"))
        # 0x00 → CRC-32 = 0xD202EF8D (known / verifiable)
        assert r.crc_int == 0xD202EF8D, f"Got 0x{r.crc_int:08X}"

    def test_alias_crc32(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="crc32"))
        assert r.crc_int == 0xCBF43926

    def test_alias_iso_hdlc(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32/ISO-HDLC"))
        assert r.crc_int == 0xCBF43926

    def test_binary_width(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32"))
        # crc_bits=32, binary must be 32 chars
        crc_bin = format(r.crc_int, f"0{r.crc_bits}b")
        assert len(crc_bin) == 32


# ---------------------------------------------------------------------------
# 6. CRC-32C/Castagnoli (official vector: 0xE3069283)
# ---------------------------------------------------------------------------

class TestCRC32C:
    def test_check_vector(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32C/Castagnoli"))
        assert r.crc_int == 0xE3069283, f"Expected 0xE3069283 got 0x{r.crc_int:08X}"

    def test_check_vector_hex_str(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32C/Castagnoli"))
        assert r.crc_hex == "E3069283"

    def test_bits(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32C/Castagnoli"))
        assert r.crc_bits == 32

    def test_polynomial_reported(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32C/Castagnoli"))
        assert r.polynomial_hex == "0x82F63B78"

    def test_empty_input(self):
        # init=0xFFFFFFFF XOR final 0xFFFFFFFF → 0x00000000
        r = compute_crc(CRCSpec(data_hex="", algorithm="CRC-32C/Castagnoli"))
        assert r.crc_int == 0x00000000

    def test_single_byte_00(self):
        r = compute_crc(CRCSpec(data_hex="00", algorithm="CRC-32C/Castagnoli"))
        # CRC-32C of single 0x00 byte = 0x527D5351 (Williams reflected-LSB-first convention,
        # init=0xFFFFFFFF, final XOR 0xFFFFFFFF; verified against check-vector 0xE3069283).
        assert r.crc_int == 0x527D5351, f"Got 0x{r.crc_int:08X}"

    def test_alias_crc32c(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="crc32c"))
        assert r.crc_int == 0xE3069283

    def test_alias_crc_32c(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32C"))
        assert r.crc_int == 0xE3069283


# ---------------------------------------------------------------------------
# 7. CRCResult dataclass fields
# ---------------------------------------------------------------------------

class TestCRCResult:
    def test_result_is_dataclass(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-32"))
        assert isinstance(r, CRCResult)
        assert hasattr(r, "crc_hex")
        assert hasattr(r, "crc_int")
        assert hasattr(r, "crc_bits")
        assert hasattr(r, "algorithm_used")
        assert hasattr(r, "polynomial_hex")
        assert hasattr(r, "honest_caveat")

    def test_honest_caveat_nonempty(self):
        for algo in supported_algorithms():
            r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm=algo))
            assert len(r.honest_caveat) > 20, f"Caveat too short for {algo}"

    def test_algorithm_used_canonical(self):
        r = compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="crc32c"))
        assert r.algorithm_used == "CRC-32C/Castagnoli"


# ---------------------------------------------------------------------------
# 8. Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_unknown_algorithm_raises(self):
        with pytest.raises(ValueError, match="Unknown algorithm"):
            compute_crc(CRCSpec(data_hex=CHECK_HEX, algorithm="CRC-99"))

    def test_invalid_hex_raises(self):
        with pytest.raises(ValueError):
            compute_crc(CRCSpec(data_hex="ZZZZ", algorithm="CRC-32"))

    def test_odd_nibble_hex_raises(self):
        with pytest.raises(ValueError):
            compute_crc(CRCSpec(data_hex="ABC", algorithm="CRC-8"))


# ---------------------------------------------------------------------------
# 9. supported_algorithms()
# ---------------------------------------------------------------------------

class TestSupportedAlgorithms:
    def test_returns_five(self):
        algos = supported_algorithms()
        assert len(algos) == 5

    def test_contains_expected(self):
        algos = supported_algorithms()
        for expected in [
            "CRC-8", "CRC-16/CCITT", "CRC-16/MODBUS", "CRC-32", "CRC-32C/Castagnoli"
        ]:
            assert expected in algos, f"Missing {expected}"


# ---------------------------------------------------------------------------
# 10. LLM tool handler (firmware_compute_crc)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def _call(self, **kwargs) -> dict:
        from kerf_firmware.tools.firmware_compute_crc import run_firmware_compute_crc
        return json.loads(run_firmware_compute_crc(kwargs))

    def test_tool_crc32_check_vector(self):
        r = self._call(data_hex=CHECK_HEX, algorithm="CRC-32")
        assert r["crc_hex"] == "CBF43926"
        assert r["crc_int"] == 0xCBF43926

    def test_tool_crc32c_check_vector(self):
        r = self._call(data_hex=CHECK_HEX, algorithm="CRC-32C/Castagnoli")
        assert r["crc_hex"] == "E3069283"

    def test_tool_crc16_ccitt_check_vector(self):
        r = self._call(data_hex=CHECK_HEX, algorithm="CRC-16/CCITT")
        assert r["crc_hex"] == "29B1"

    def test_tool_missing_data_hex(self):
        r = self._call(algorithm="CRC-32")
        assert r.get("code") == "BAD_ARGS"
        assert "data_hex" in r.get("error", "")

    def test_tool_missing_algorithm(self):
        r = self._call(data_hex=CHECK_HEX)
        assert r.get("code") == "BAD_ARGS"
        assert "algorithm" in r.get("error", "")

    def test_tool_bad_algorithm(self):
        r = self._call(data_hex=CHECK_HEX, algorithm="CRC-99")
        assert r.get("code") == "BAD_ARGS"

    def test_tool_binary_field_present(self):
        r = self._call(data_hex=CHECK_HEX, algorithm="CRC-32")
        assert "crc_binary" in r
        assert len(r["crc_binary"]) == 32

    def test_tool_honest_caveat_present(self):
        r = self._call(data_hex=CHECK_HEX, algorithm="CRC-8")
        assert "honest_caveat" in r
        assert len(r["honest_caveat"]) > 20

    def test_tool_empty_input(self):
        r = self._call(data_hex="", algorithm="CRC-32")
        assert r["crc_int"] == 0x00000000

    def test_async_wrapper(self):
        import asyncio
        from kerf_firmware.tools.firmware_compute_crc import run_firmware_compute_crc_async
        args_bytes = json.dumps({"data_hex": CHECK_HEX, "algorithm": "CRC-32"}).encode()
        result = asyncio.run(run_firmware_compute_crc_async(None, args_bytes))
        parsed = json.loads(result)
        assert parsed["crc_int"] == 0xCBF43926
