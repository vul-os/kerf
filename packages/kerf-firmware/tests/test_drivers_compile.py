"""
tests/test_drivers_compile.py — Compile-oracle tests for the 12 Kerf firmware drivers.

Compile paths (in preference order):
1. Cross-compile: avr-gcc / arm-none-eabi-gcc / xtensa-esp32-elf-gcc / riscv64-unknown-elf-gcc
   → compile each driver for ≥ 1 matching arch
2. Host-gcc syntax-only: gcc -fsyntax-only -x c -std=c99 with a generated stub header
   → validates that each .c file is syntactically valid C
3. Structural-only (no compiler at all):
   → balanced-brace check, presence of documented function signatures,
     presence of #include "<target>.h"

The test selects the best available path automatically.

Scenarios:
D01  All 12 driver .c files exist
D02  All 12 driver .h files exist
D03  Each .c includes its own .h
D04  Each .h has a header guard (#ifndef / #define)
D05  Each .c has the expected public function signatures
D06  Braces are balanced in each .c
D07  Compile check (cross, host-syntax, or skip-structural-only)
D08  make_protocol_driver tool source exists and can be imported
D09  Protocol primer .md files exist (one per protocol)
D10  drivers.md catalogue index exists
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PKG = Path(__file__).resolve().parent.parent
_DRIVERS = _PKG / "src" / "kerf_firmware" / "drivers"
_TOOLS   = _PKG / "src" / "kerf_firmware" / "tools"
_LLMDOCS = _PKG / "llm_docs"

_TARGETS = [
    "bme280", "ds18b20", "mpu6050", "hx711", "mcp2515", "ssd1306",
    "ws2812", "mfrc522", "vl53l0x", "dht22", "pca9685", "max31855",
]

_PROTOCOLS = ["i2c", "spi", "uart", "can", "onewire", "i2s"]

# ---------------------------------------------------------------------------
# Compiler detection
# ---------------------------------------------------------------------------
_CROSS_COMPILERS = {
    "avr":   "avr-gcc",
    "arm":   "arm-none-eabi-gcc",
    "esp32": "xtensa-esp32-elf-gcc",
    "riscv": "riscv64-unknown-elf-gcc",
}

def _find_cross_compiler():
    """Return (arch, path) for the first available cross-compiler, or (None, None)."""
    for arch, exe in _CROSS_COMPILERS.items():
        if shutil.which(exe):
            return arch, exe
    return None, None

def _find_host_gcc():
    """Return path to host gcc if -fsyntax-only is supported, else None."""
    gcc = shutil.which("gcc") or shutil.which("cc")
    if not gcc:
        return None
    try:
        r = subprocess.run(
            [gcc, "--version"], capture_output=True, timeout=5
        )
        if r.returncode == 0:
            return gcc
    except Exception:
        pass
    return None

_CROSS_ARCH, _CROSS_GCC = _find_cross_compiler()
_HOST_GCC = _find_host_gcc()

# ---------------------------------------------------------------------------
# Compile mode
# ---------------------------------------------------------------------------
if _CROSS_GCC:
    _COMPILE_MODE = "cross"
elif _HOST_GCC:
    _COMPILE_MODE = "host-syntax"
else:
    _COMPILE_MODE = "structural-only"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c_path(target: str) -> Path:
    return _DRIVERS / f"{target}.c"

def _h_path(target: str) -> Path:
    return _DRIVERS / f"{target}.h"

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")

def _balanced_braces(src: str) -> bool:
    """Return True if all { } braces are balanced."""
    depth = 0
    in_string = False
    in_char = False
    in_line_comment = False
    in_block_comment = False
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

# Public function signatures expected in each driver
_EXPECTED_SIGNATURES: dict[str, list[str]] = {
    "bme280":   ["bme280_init", "bme280_read", "bme280_soft_reset"],
    "ds18b20":  ["ds18b20_init", "ds18b20_read_single", "ds18b20_read_scratchpad"],
    "mpu6050":  ["mpu6050_init", "mpu6050_read"],
    "hx711":    ["hx711_init", "hx711_read_raw", "hx711_tare", "hx711_weight_kg"],
    "mcp2515":  ["mcp2515_init", "mcp2515_send", "mcp2515_recv"],
    "ssd1306":  ["ssd1306_init", "ssd1306_display", "ssd1306_draw_pixel"],
    "ws2812":   ["ws2812_init", "ws2812_show", "ws2812_set_pixel"],
    "mfrc522":  ["mfrc522_init", "mfrc522_read_uid"],
    "vl53l0x":  ["vl53l0x_init", "vl53l0x_read_range_mm"],
    "dht22":    ["dht22_init", "dht22_read"],
    "pca9685":  ["pca9685_init", "pca9685_set_freq", "pca9685_set_channel_us"],
    "max31855": ["max31855_init", "max31855_read_celsius"],
}

# ---------------------------------------------------------------------------
# D01 / D02 — file existence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", _TARGETS)
def test_d01_c_file_exists(target):
    """D01: .c file exists for every driver."""
    assert _c_path(target).exists(), f"{target}.c not found in {_DRIVERS}"

@pytest.mark.parametrize("target", _TARGETS)
def test_d02_h_file_exists(target):
    """D02: .h file exists for every driver."""
    assert _h_path(target).exists(), f"{target}.h not found in {_DRIVERS}"

# ---------------------------------------------------------------------------
# D03 — .c includes its own .h
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", _TARGETS)
def test_d03_c_includes_own_header(target):
    """D03: Each .c #includes its matching .h."""
    src = _read(_c_path(target))
    pattern = re.compile(rf'#include\s+["\<]{re.escape(target)}\.h["\>]')
    assert pattern.search(src), f"{target}.c does not include {target}.h"

# ---------------------------------------------------------------------------
# D04 — header guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", _TARGETS)
def test_d04_header_guard(target):
    """D04: Each .h has an include guard (#ifndef ... #define ...)."""
    src = _read(_h_path(target))
    assert "#ifndef" in src, f"{target}.h missing #ifndef guard"
    assert "#define" in src, f"{target}.h missing #define in guard"
    assert "#endif"  in src, f"{target}.h missing #endif"

# ---------------------------------------------------------------------------
# D05 — expected function signatures present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", _TARGETS)
def test_d05_function_signatures(target):
    """D05: Expected public functions are declared in .h and defined in .c."""
    h_src = _read(_h_path(target))
    c_src = _read(_c_path(target))
    for fn in _EXPECTED_SIGNATURES.get(target, []):
        assert fn in h_src, f"{fn} not found in {target}.h"
        assert fn in c_src, f"{fn} not found in {target}.c"

# ---------------------------------------------------------------------------
# D06 — balanced braces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target", _TARGETS)
def test_d06_balanced_braces(target):
    """D06: C source files have balanced braces."""
    src = _read(_c_path(target))
    assert _balanced_braces(src), f"Unbalanced braces in {target}.c"

# ---------------------------------------------------------------------------
# D07 — compile check
# ---------------------------------------------------------------------------

def _make_stub_header(target: str) -> str:
    """Generate a minimal stub header so host gcc can parse the .c without the HAL."""
    return f"""
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* HAL stubs for syntax-only compilation */
static inline int  kerf_i2c_write(unsigned char b, unsigned char a, const unsigned char *d, unsigned char l) {{ (void)b;(void)a;(void)d;(void)l; return 0; }}
static inline int  kerf_i2c_read(unsigned char b, unsigned char a, unsigned char r, unsigned char *buf, unsigned char l) {{ (void)b;(void)a;(void)r;(void)buf;(void)l; return 0; }}
static inline void kerf_spi_cs_low(unsigned char b, unsigned char p) {{ (void)b;(void)p; }}
static inline void kerf_spi_cs_high(unsigned char b, unsigned char p) {{ (void)b;(void)p; }}
static inline unsigned char kerf_spi_transfer(unsigned char b, unsigned char x) {{ (void)b;(void)x; return 0; }}
static inline void kerf_gpio_set_output(unsigned char p) {{ (void)p; }}
static inline void kerf_gpio_set_input(unsigned char p) {{ (void)p; }}
static inline void kerf_gpio_write(unsigned char p, unsigned char v) {{ (void)p;(void)v; }}
static inline unsigned char kerf_gpio_read(unsigned char p) {{ (void)p; return 1; }}
static inline void kerf_delay_ms(unsigned int ms) {{ (void)ms; }}
static inline void kerf_delay_us(unsigned int us) {{ (void)us; }}
static inline void kerf_delay_ns(unsigned int ns) {{ (void)ns; }}
static inline unsigned int kerf_millis(void) {{ return 0; }}
static inline void kerf_irq_disable(void) {{}}
static inline void kerf_irq_enable(void) {{}}
static inline int  kerf_ow_reset(unsigned char p) {{ (void)p; return 0; }}
static inline void kerf_ow_write_byte(unsigned char p, unsigned char b) {{ (void)p;(void)b; }}
static inline unsigned char kerf_ow_read_byte(unsigned char p) {{ (void)p; return 0; }}
static inline unsigned int kerf_pulse_in_us(unsigned char p, unsigned char l, unsigned int t) {{ (void)p;(void)l;(void)t; return 0; }}
#define KERF_I2C_HAL_PROVIDED 1
#define KERF_SPI_HAL_PROVIDED 1
#define KERF_GPIO_HAL_PROVIDED 1
#define KERF_OW_HAL_PROVIDED 1
"""

@pytest.mark.skipif(
    _COMPILE_MODE == "structural-only",
    reason="No compiler available — structural checks only",
)
@pytest.mark.parametrize("target", _TARGETS)
def test_d07_compile(target):
    """D07: Each driver .c is syntactically valid C (host gcc -fsyntax-only)."""
    c_file = _c_path(target)
    h_file = _h_path(target)

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # Write the real header into the temp dir
        (tmp / f"{target}.h").write_text(h_file.read_text(encoding="utf-8"),
                                          encoding="utf-8")

        # Write the stub override header
        (tmp / "kerf_hal_stub.h").write_text(_make_stub_header(target),
                                              encoding="utf-8")

        # Patch the .c: prepend #include "kerf_hal_stub.h"
        c_src = c_file.read_text(encoding="utf-8")
        patched_c = f'#include "kerf_hal_stub.h"\n{c_src}'
        patched_path = tmp / f"{target}.c"
        patched_path.write_text(patched_c, encoding="utf-8")

        if _COMPILE_MODE == "cross":
            # Use cross compiler for a real compile (just syntax + type check)
            arch_flags = {
                "avr":   ["-mmcu=atmega328p"],
                "arm":   ["-mcpu=cortex-m4", "-mthumb"],
                "esp32": [],
                "riscv": ["-march=rv32imac", "-mabi=ilp32"],
            }
            cmd = [_CROSS_GCC, "-fsyntax-only", "-std=c99",
                   f"-I{tmp}", "-x", "c", str(patched_path)]
            cmd[1:1] = arch_flags.get(_CROSS_ARCH, [])
        else:
            # host-syntax mode
            cmd = [_HOST_GCC, "-fsyntax-only", "-std=c99",
                   f"-I{tmp}", str(patched_path)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (
            f"Compile check failed for {target}:\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

# ---------------------------------------------------------------------------
# D08 — make_protocol_driver tool importable
# ---------------------------------------------------------------------------

def test_d08_tool_file_exists():
    """D08: make_protocol_driver.py exists."""
    tool_path = _TOOLS / "make_protocol_driver.py"
    assert tool_path.exists(), f"Tool not found: {tool_path}"

def test_d08_tool_importable():
    """D08: make_protocol_driver module can be imported."""
    sys.path.insert(0, str(_PKG / "src"))
    try:
        import kerf_firmware.tools.make_protocol_driver as mpd  # noqa: F401
        assert hasattr(mpd, "_CATALOGUE"), "Missing _CATALOGUE in make_protocol_driver"
        assert hasattr(mpd, "run_make_protocol_driver"), "Missing run_make_protocol_driver"
    finally:
        sys.path.pop(0)

# ---------------------------------------------------------------------------
# D09 — protocol primers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("proto", _PROTOCOLS)
def test_d09_protocol_primer_exists(proto):
    """D09: Each protocol primer .md exists in llm_docs/protocols/."""
    md = _LLMDOCS / "protocols" / f"{proto}.md"
    assert md.exists(), f"Missing protocol primer: {md}"
    content = md.read_text(encoding="utf-8")
    # Should have a top-level H1 heading
    assert content.startswith("# "), f"{proto}.md does not start with an H1 heading"

# ---------------------------------------------------------------------------
# D10 — drivers.md catalogue
# ---------------------------------------------------------------------------

def test_d10_drivers_catalogue_exists():
    """D10: drivers.md catalogue index exists in llm_docs/."""
    md = _LLMDOCS / "drivers.md"
    assert md.exists(), f"Missing drivers catalogue: {md}"
    content = md.read_text(encoding="utf-8")
    # Should mention all 12 targets
    for target in _TARGETS:
        assert target in content, f"drivers.md does not mention driver '{target}'"
