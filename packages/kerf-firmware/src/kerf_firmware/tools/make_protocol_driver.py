"""
make_protocol_driver.py — LLM tool: make_protocol_driver

Generates a customised .c driver file from one of the 12 pre-built Kerf
firmware drivers, with pin assignments substituted from the caller's spec.

Schema:
  {
    "protocol": "i2c" | "spi" | "uart" | "can" | "onewire" | "bitbang",
    "target":   "bme280" | "ds18b20" | "mpu6050" | "hx711" | "mcp2515" |
                "ssd1306" | "ws2812" | "mfrc522" | "vl53l0x" | "dht22" |
                "pca9685" | "max31855",
    "pins": {
      -- I2C drivers --
      "sda": <int>,    -- GPIO pin number for SDA
      "scl": <int>,    -- GPIO pin number for SCL
      -- SPI drivers --
      "miso": <int>,   -- optional: MISO pin
      "mosi": <int>,   -- optional: MOSI pin
      "sck":  <int>,   -- optional: SCK pin
      "cs":   <int>,   -- Chip select pin
      -- 1-Wire / bit-bang --
      "dq":   <int>,   -- 1-Wire data pin
      "din":  <int>,   -- LED data-in pin (WS2812)
      "dout": <int>,   -- Data-out pin (HX711)
      "sck":  <int>,   -- Clock pin (HX711)
      "data": <int>,   -- Data pin (DHT22)
      "rst":  <int>,   -- optional: reset pin (MFRC522)
    }
  }

Returns:
  ok_payload({
    "driver":    "<target>.c",   -- filename
    "source":    "<C source code>",
    "header":    "<target>.h",
    "pins_used": { ... },        -- echoed pin assignments
    "protocol":  "...",
    "note":      "..."
  })
  err_payload(...) on failure.

Error codes:
  BAD_ARGS   — Invalid or missing arguments.
  UNKNOWN_TARGET  — Requested driver not in catalogue.
  UNKNOWN_PROTOCOL — Protocol not supported.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
except ImportError:
    # Stub for offline / test usage
    def register(spec):  # type: ignore[misc]
        def _d(fn):
            return fn
        return _d

    class ToolSpec:  # type: ignore[no-redef]
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    def ok_payload(data):  # type: ignore[misc]
        return json.dumps({"ok": True, "data": data})

    def err_payload(msg, code="ERROR"):  # type: ignore[misc]
        return json.dumps({"ok": False, "error": msg, "code": code})

try:
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    ProjectCtx = object  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

_DRIVERS_DIR = Path(__file__).resolve().parent.parent / "drivers"

# Maps target name → (protocol, [required_pin_keys], [optional_pin_keys])
_CATALOGUE: dict[str, tuple[str, list[str], list[str]]] = {
    "bme280":   ("i2c",     ["sda", "scl"], []),
    "mpu6050":  ("i2c",     ["sda", "scl"], []),
    "ssd1306":  ("i2c",     ["sda", "scl"], []),
    "vl53l0x":  ("i2c",     ["sda", "scl"], []),
    "pca9685":  ("i2c",     ["sda", "scl"], []),
    "hx711":    ("spi",     ["dout", "sck"], []),
    "mcp2515":  ("can",     ["cs"], ["miso", "mosi", "sck"]),
    "mfrc522":  ("spi",     ["cs"], ["miso", "mosi", "sck", "rst"]),
    "max31855":  ("spi",    ["cs"], ["miso", "mosi", "sck"]),
    "ds18b20":  ("onewire", ["dq"], []),
    "dht22":    ("onewire", ["data"], []),
    "ws2812":   ("bitbang", ["din"], []),
}

_KNOWN_PROTOCOLS = {"i2c", "spi", "uart", "can", "onewire", "bitbang", "i2s"}


def _load_driver_source(target: str) -> tuple[str | None, str | None]:
    """Return (c_source, h_source) for the given target, or (None, None)."""
    c_path = _DRIVERS_DIR / f"{target}.c"
    h_path = _DRIVERS_DIR / f"{target}.h"
    c_src = c_path.read_text(encoding="utf-8") if c_path.exists() else None
    h_src = h_path.read_text(encoding="utf-8") if h_path.exists() else None
    return c_src, h_src


def _substitute_pins(source: str, pins: dict[str, int]) -> tuple[str, dict[str, int]]:
    """
    Insert a /* KERF_PINS */ comment block at the top of the source file that
    defines each pin as a preprocessor macro, so the downstream BSP can use them
    directly.  E.g.:

        #define KERF_PIN_SDA  21
        #define KERF_PIN_SCL  22

    We do NOT do textual substitution inside the driver body — the macros provide
    the override seam.  Returns (modified_source, pins_used).
    """
    if not pins:
        return source, {}

    pin_block_lines = ["/* === Kerf auto-generated pin assignments === */"]
    pins_used: dict[str, int] = {}
    for name, number in sorted(pins.items()):
        if not isinstance(number, int):
            continue
        macro = f"KERF_PIN_{name.upper()}"
        pin_block_lines.append(f"#ifndef {macro}")
        pin_block_lines.append(f"#  define {macro}  {number}")
        pin_block_lines.append(f"#endif")
        pins_used[name] = number

    if not pins_used:
        return source, {}

    pin_block = "\n".join(pin_block_lines) + "\n\n"

    # Insert after the first include of the own header (e.g. #include "bme280.h")
    lines = source.split("\n")
    insert_after = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#include "') and stripped.endswith('.h"'):
            insert_after = i + 1
            break

    lines.insert(insert_after, pin_block)
    return "\n".join(lines), pins_used


# ---------------------------------------------------------------------------
# Tool specification
# ---------------------------------------------------------------------------

make_protocol_driver_spec = ToolSpec(
    name="make_protocol_driver",
    description=(
        "Generate a customised firmware driver .c file for a specific sensor or "
        "actuator. Provide the protocol family, the target part name, and the GPIO "
        "pin assignments. Returns the complete C source with pin macros injected."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "protocol": {
                "type": "string",
                "description": "Protocol family: i2c, spi, uart, can, onewire, bitbang, i2s",
            },
            "target": {
                "type": "string",
                "description": (
                    "Driver target: bme280, ds18b20, mpu6050, hx711, mcp2515, ssd1306, "
                    "ws2812, mfrc522, vl53l0x, dht22, pca9685, max31855"
                ),
            },
            "pins": {
                "type": "object",
                "description": "GPIO pin assignments. Keys depend on protocol (sda, scl, cs, dq, din, ...).",
                "additionalProperties": {"type": "integer"},
            },
        },
        "required": ["protocol", "target", "pins"],
    },
)


@register(make_protocol_driver_spec)
async def run_make_protocol_driver(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    protocol = str(a.get("protocol", "")).strip().lower()
    target   = str(a.get("target", "")).strip().lower()
    pins     = a.get("pins", {})

    if not protocol:
        return err_payload("'protocol' is required", "BAD_ARGS")
    if not target:
        return err_payload("'target' is required", "BAD_ARGS")
    if not isinstance(pins, dict):
        return err_payload("'pins' must be an object", "BAD_ARGS")

    if protocol not in _KNOWN_PROTOCOLS:
        return err_payload(
            f"Unknown protocol '{protocol}'. Supported: {sorted(_KNOWN_PROTOCOLS)}",
            "UNKNOWN_PROTOCOL",
        )

    if target not in _CATALOGUE:
        return err_payload(
            f"Unknown driver target '{target}'. Available: {sorted(_CATALOGUE.keys())}",
            "UNKNOWN_TARGET",
        )

    # Validate that protocol matches the catalogue entry
    canonical_proto, required_pins, optional_pins = _CATALOGUE[target]
    if protocol != canonical_proto:
        return err_payload(
            f"Driver '{target}' uses protocol '{canonical_proto}', not '{protocol}'. "
            f"Pass protocol='{canonical_proto}'.",
            "BAD_ARGS",
        )

    # Check required pins
    missing = [p for p in required_pins if p not in pins]
    if missing:
        return err_payload(
            f"Missing required pin(s) for {target}/{protocol}: {missing}. "
            f"Required: {required_pins}",
            "BAD_ARGS",
        )

    # Load driver source
    c_src, h_src = _load_driver_source(target)
    if c_src is None:
        return err_payload(
            f"Driver source for '{target}' not found on this server",
            "UNKNOWN_TARGET",
        )

    # Inject pin macros
    c_modified, pins_used = _substitute_pins(c_src, pins)

    note = (
        f"Pin macros injected as #define KERF_PIN_<NAME> <value>. "
        f"Override by defining them before including {target}.h. "
        f"Compile with: gcc -fsyntax-only -x c {target}.c (requires HAL stubs)."
    )

    return ok_payload({
        "driver":    f"{target}.c",
        "source":    c_modified,
        "header":    f"{target}.h",
        "pins_used": pins_used,
        "protocol":  protocol,
        "note":      note,
    })
