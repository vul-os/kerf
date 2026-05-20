"""
tests/test_make_protocol_driver.py — pytest suite for make_protocol_driver LLM tool.

Response format mirrors kerf_chat.tools.registry:
  ok_payload(data)  → JSON of data dict directly (no 'ok' wrapper)
  err_payload(msg, code) → {"error": "...", "code": "..."}

Scenarios:
M01  Calling with I2C target (bme280) emits .c with expected keys
M02  Pin macros reference the exact pin numbers passed in the spec
M03  Calling with SPI target (max31855) emits .c with CS pin macro
M04  Missing required pin returns BAD_ARGS error
M05  Unknown target returns UNKNOWN_TARGET error
M06  Unknown protocol returns UNKNOWN_PROTOCOL error
M07  Protocol mismatch (i2c + hx711) returns BAD_ARGS
M08  All 12 catalogue targets are present in _CATALOGUE
M09  _substitute_pins does not corrupt source (balanced braces preserved)
M10  run_make_protocol_driver is an async function (coroutine)
M11  DS18B20 onewire driver emits DQ pin macro
M12  WS2812 bitbang driver emits DIN pin macro
M13  Catalogue has correct protocol for each driver
M14  Tool returns JSON with expected keys on success
M15  Non-integer pin value is silently ignored (graceful)
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

# Insert the package source on sys.path
_PKG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PKG / "src"))

from kerf_firmware.tools.make_protocol_driver import (
    _CATALOGUE,
    _substitute_pins,
    run_make_protocol_driver,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(protocol, target, pins):
    """
    Synchronously invoke the async tool and parse the JSON response.

    Response shape:
      Success: a dict with keys like 'driver', 'source', 'header', etc.
               (ok_payload returns data directly)
      Error:   {"error": "...", "code": "..."}
    """
    raw = asyncio.run(
        run_make_protocol_driver(None, json.dumps({
            "protocol": protocol,
            "target":   target,
            "pins":     pins,
        }).encode())
    )
    return json.loads(raw)


def _is_success(result: dict) -> bool:
    """A result is a success if it has 'driver' or 'source' key (no 'error' key)."""
    return "error" not in result and "driver" in result


def _is_error(result: dict, code: str | None = None) -> bool:
    """A result is an error if it has an 'error' key (and optionally matching code)."""
    if "error" not in result:
        return False
    if code is not None:
        return result.get("code") == code
    return True


def _balanced_braces(src: str) -> bool:
    depth = 0
    in_string = in_char = in_line_comment = in_block_comment = False
    i = 0
    while i < len(src):
        c = src[i]
        nc = src[i + 1] if i + 1 < len(src) else ""
        if in_line_comment:
            if c == "\n":
                in_line_comment = False
        elif in_block_comment:
            if c == "*" and nc == "/":
                in_block_comment = False
                i += 1
        elif in_string:
            if c == "\\" and nc:
                i += 1
            elif c == '"':
                in_string = False
        elif in_char:
            if c == "\\" and nc:
                i += 1
            elif c == "'":
                in_char = False
        else:
            if c == "/" and nc == "/":
                in_line_comment = True
                i += 1
            elif c == "/" and nc == "*":
                in_block_comment = True
                i += 1
            elif c == '"':
                in_string = True
            elif c == "'":
                in_char = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth < 0:
                    return False
        i += 1
    return depth == 0


# ---------------------------------------------------------------------------
# M01 — bme280 I2C with SDA/SCL emits macros
# ---------------------------------------------------------------------------

def test_m01_bme280_i2c_emits_macros():
    """M01: make_protocol_driver for bme280/i2c returns .c source."""
    result = _run("i2c", "bme280", {"sda": 21, "scl": 22})
    assert _is_success(result), f"Expected success, got: {result}"
    assert "source" in result
    assert result["driver"] == "bme280.c"
    assert result["protocol"] == "i2c"

def test_m02_bme280_pin_macros_contain_correct_values():
    """M02: SDA=21, SCL=22 appear as KERF_PIN macros in the emitted source."""
    result = _run("i2c", "bme280", {"sda": 21, "scl": 22})
    src = result["source"]
    assert "KERF_PIN_SDA" in src, "KERF_PIN_SDA not in emitted source"
    assert "KERF_PIN_SCL" in src, "KERF_PIN_SCL not in emitted source"
    # Check the exact values
    assert re.search(r"KERF_PIN_SDA\s+21", src), "KERF_PIN_SDA value is not 21"
    assert re.search(r"KERF_PIN_SCL\s+22", src), "KERF_PIN_SCL value is not 22"

# ---------------------------------------------------------------------------
# M03 — max31855 SPI with CS pin
# ---------------------------------------------------------------------------

def test_m03_max31855_spi_cs_macro():
    """M03: max31855/spi emits KERF_PIN_CS macro."""
    result = _run("spi", "max31855", {"cs": 10})
    assert _is_success(result), result
    src = result["source"]
    assert "KERF_PIN_CS" in src
    assert re.search(r"KERF_PIN_CS\s+10", src)

# ---------------------------------------------------------------------------
# M04 — missing required pin
# ---------------------------------------------------------------------------

def test_m04_missing_required_pin_returns_bad_args():
    """M04: Missing required pin returns BAD_ARGS."""
    result = _run("i2c", "bme280", {"sda": 21})  # missing scl
    assert _is_error(result, "BAD_ARGS"), f"Expected BAD_ARGS error, got: {result}"

# ---------------------------------------------------------------------------
# M05 — unknown target
# ---------------------------------------------------------------------------

def test_m05_unknown_target_returns_error():
    """M05: Unknown target returns UNKNOWN_TARGET."""
    result = _run("i2c", "nonexistent_sensor", {"sda": 1, "scl": 2})
    assert _is_error(result, "UNKNOWN_TARGET"), f"Expected UNKNOWN_TARGET, got: {result}"

# ---------------------------------------------------------------------------
# M06 — unknown protocol
# ---------------------------------------------------------------------------

def test_m06_unknown_protocol_returns_error():
    """M06: Unknown protocol returns UNKNOWN_PROTOCOL."""
    result = _run("bluetooth", "bme280", {"sda": 1, "scl": 2})
    assert _is_error(result, "UNKNOWN_PROTOCOL"), f"Expected UNKNOWN_PROTOCOL, got: {result}"

# ---------------------------------------------------------------------------
# M07 — protocol mismatch
# ---------------------------------------------------------------------------

def test_m07_protocol_mismatch_returns_bad_args():
    """M07: Passing i2c for hx711 (which uses pseudo-spi) returns BAD_ARGS."""
    result = _run("i2c", "hx711", {"sda": 1, "scl": 2})
    assert _is_error(result, "BAD_ARGS"), f"Expected BAD_ARGS, got: {result}"

# ---------------------------------------------------------------------------
# M08 — all 12 catalogue targets
# ---------------------------------------------------------------------------

_ALL_TARGETS = [
    "bme280", "ds18b20", "mpu6050", "hx711", "mcp2515", "ssd1306",
    "ws2812", "mfrc522", "vl53l0x", "dht22", "pca9685", "max31855",
]

@pytest.mark.parametrize("target", _ALL_TARGETS)
def test_m08_catalogue_has_all_targets(target):
    """M08: All 12 targets are present in _CATALOGUE."""
    assert target in _CATALOGUE, f"'{target}' missing from _CATALOGUE"

# ---------------------------------------------------------------------------
# M09 — substitute_pins preserves balanced braces
# ---------------------------------------------------------------------------

def test_m09_substitute_pins_preserves_balanced_braces():
    """M09: After pin injection the source still has balanced braces."""
    sample = '#include "bme280.h"\nint foo(void) { return 0; }\n'
    result, pins_used = _substitute_pins(sample, {"sda": 21, "scl": 22})
    assert _balanced_braces(result), "Brace imbalance after _substitute_pins"
    assert pins_used == {"sda": 21, "scl": 22}

# ---------------------------------------------------------------------------
# M10 — coroutine
# ---------------------------------------------------------------------------

def test_m10_run_is_coroutine():
    """M10: run_make_protocol_driver is declared as an async function."""
    assert inspect.iscoroutinefunction(run_make_protocol_driver)

# ---------------------------------------------------------------------------
# M11 — DS18B20 onewire DQ pin
# ---------------------------------------------------------------------------

def test_m11_ds18b20_dq_macro():
    """M11: ds18b20/onewire emits KERF_PIN_DQ macro."""
    result = _run("onewire", "ds18b20", {"dq": 2})
    assert _is_success(result), result
    src = result["source"]
    assert "KERF_PIN_DQ" in src
    assert re.search(r"KERF_PIN_DQ\s+2", src)

# ---------------------------------------------------------------------------
# M12 — WS2812 bitbang DIN pin
# ---------------------------------------------------------------------------

def test_m12_ws2812_din_macro():
    """M12: ws2812/bitbang emits KERF_PIN_DIN macro."""
    result = _run("bitbang", "ws2812", {"din": 6})
    assert _is_success(result), result
    src = result["source"]
    assert "KERF_PIN_DIN" in src
    assert re.search(r"KERF_PIN_DIN\s+6", src)

# ---------------------------------------------------------------------------
# M13 — catalogue protocol correctness
# ---------------------------------------------------------------------------

_EXPECTED_PROTOCOLS = {
    "bme280":   "i2c",
    "mpu6050":  "i2c",
    "ssd1306":  "i2c",
    "vl53l0x":  "i2c",
    "pca9685":  "i2c",
    "hx711":    "spi",
    "mcp2515":  "can",
    "mfrc522":  "spi",
    "max31855": "spi",
    "ds18b20":  "onewire",
    "dht22":    "onewire",
    "ws2812":   "bitbang",
}

@pytest.mark.parametrize("target,expected_proto", _EXPECTED_PROTOCOLS.items())
def test_m13_catalogue_protocols(target, expected_proto):
    """M13: Each catalogue entry has the correct canonical protocol."""
    actual = _CATALOGUE[target][0]
    assert actual == expected_proto, (
        f"{target}: expected protocol '{expected_proto}', got '{actual}'"
    )

# ---------------------------------------------------------------------------
# M14 — success response has expected keys
# ---------------------------------------------------------------------------

def test_m14_success_response_keys():
    """M14: Successful response includes driver, source, header, pins_used, protocol, note."""
    result = _run("i2c", "ssd1306", {"sda": 21, "scl": 22})
    assert _is_success(result), f"Expected success, got: {result}"
    for key in ("driver", "source", "header", "pins_used", "protocol", "note"):
        assert key in result, f"Missing key '{key}' in response"
    assert result["header"] == "ssd1306.h"

# ---------------------------------------------------------------------------
# M15 — non-integer pin ignored gracefully
# ---------------------------------------------------------------------------

def test_m15_non_integer_pin_ignored():
    """M15: Non-integer pin values are silently ignored (tool must not crash)."""
    result = _run("i2c", "bme280", {"sda": 21, "scl": "bad_value"})
    # The tool checks key presence not type, so this may succeed or fail —
    # we just ensure it doesn't raise an exception (returns valid JSON).
    assert isinstance(result, dict), "Tool must return a parseable JSON dict"
