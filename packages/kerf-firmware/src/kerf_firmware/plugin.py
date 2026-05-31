"""
kerf-firmware plugin registration.

Wires the firmware build/monitor routes and LLM tools into a Kerf plugin app.
The capability `firmware.build` is only advertised when PlatformIO Core CLI is
available on PATH (probed at startup). The HTTP routes are always mounted —
they return descriptive errors when PlatformIO is absent so the frontend can
show a helpful install prompt.
"""
from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


def _pio_available() -> bool:
    """Return True if PlatformIO Core CLI is on PATH."""
    return (
        shutil.which("pio") is not None
        or shutil.which("platformio") is not None
    )


async def register(app: "FastAPI", ctx):
    """Entry point called by the Kerf plugin loader."""
    # ── HTTP routes ──────────────────────────────────────────────────────────
    from kerf_firmware.routes import router as firmware_router
    app.include_router(firmware_router, prefix="/api", tags=["firmware"])

    # ── LLM tools ────────────────────────────────────────────────────────────
    provides: list[str] = []
    _register_tools(ctx, provides)

    # Advertise firmware.build only when PlatformIO is actually present.
    if _pio_available():
        if "firmware.build" not in provides:
            provides.append("firmware.build")
        logger.info("kerf-firmware: PlatformIO found — firmware.build available")
    else:
        logger.warning(
            "kerf-firmware: PlatformIO Core CLI not found on PATH — "
            "install it to enable firmware builds. "
            "pip install platformio  |  brew install platformio"
        )

    try:
        from kerf_core.plugin import PluginManifest  # type: ignore
    except ImportError:
        return {
            "name": "firmware",
            "version": "0.1.0",
            "provides": provides,
            "depends": [],
        }

    return PluginManifest(
        name="firmware",
        version="0.1.0",
        provides=provides,
        depends=[],
    )


def _register_tools(ctx, provides: list) -> None:
    """Register all firmware LLM tools into ctx.tools."""
    try:
        from kerf_firmware.tools.build_firmware import (
            build_firmware_tool,
            build_firmware_spec,
        )
        ctx.tools.register("build_firmware", build_firmware_spec, build_firmware_tool)
        provides.append("firmware.build")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load build_firmware tool: %s", exc)

    # verify_pin_mapping — cross-check firmware pin assignments vs KiCad PCB netlist
    try:
        from kerf_firmware.tools.verify_pin_mapping import _spec as _vpm_spec, verify_pin_mapping as _vpm_fn
        import json as _json

        async def _verify_pin_mapping_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                from kerf_firmware._compat import err_payload
                return err_payload(f"invalid args: {e}", "BAD_ARGS")
            return _vpm_fn(a, ctx)

        ctx.tools.register("verify_pin_mapping", _vpm_spec, _verify_pin_mapping_tool)
        provides.append("firmware.pcb_xcheck")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load verify_pin_mapping tool: %s", exc)

    # make_protocol_driver — generate C driver source for common I2C/SPI/UART sensors
    try:
        from kerf_firmware.tools.make_protocol_driver import (
            make_protocol_driver_spec,
            run_make_protocol_driver,
        )
        ctx.tools.register(
            "make_protocol_driver",
            make_protocol_driver_spec,
            run_make_protocol_driver,
        )
        provides.append("firmware.protocol_driver")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load make_protocol_driver tool: %s", exc)

    # make_arduino_sketch — template-based Arduino sketch synthesizer
    try:
        from kerf_firmware.llm_tool import make_arduino_sketch as _make_sketch
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _ToolSpec
        except ImportError:
            from kerf_firmware._compat import ToolSpec as _ToolSpec  # type: ignore

        _arduino_spec = _ToolSpec(
            name="make_arduino_sketch",
            description=(
                "Generate a complete Arduino sketch (.ino) from a natural-language description. "
                "Supports blink LED, DHT22 temperature sensor, servo + potentiometer, "
                "MPU6050 accelerometer (serial log), and PWM motor speed control. "
                "Returns {sketch: str, manifest: dict} on success or {error: str, spec: str} "
                "when no pattern matches."
            ),
            input_schema={
                "type": "object",
                "required": ["spec"],
                "properties": {
                    "spec": {
                        "type": "string",
                        "description": (
                            "Natural-language description of the sketch, e.g. "
                            "'blink LED on pin 13', 'read DHT22 on pin 4', "
                            "'control servo with potentiometer on pin 9'."
                        ),
                    },
                },
            },
        )

        async def _make_arduino_sketch_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"error": f"invalid args: {e}", "code": "BAD_ARGS"})
            spec = a.get("spec", "")
            if not spec:
                return _json.dumps({"error": "'spec' is required", "code": "BAD_ARGS"})
            result = _make_sketch(spec)
            return _json.dumps(result)

        ctx.tools.register("make_arduino_sketch", _arduino_spec, _make_arduino_sketch_tool)
        provides.append("firmware.arduino_sketch")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load make_arduino_sketch tool: %s", exc)

    # make_usb_midi_controller — generate USB-MIDI Arduino sketch
    try:
        from kerf_firmware.tools.make_usb_midi_controller import make_usb_midi_controller as _make_midi
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _ToolSpec2
        except ImportError:
            from kerf_firmware._compat import ToolSpec as _ToolSpec2  # type: ignore

        _midi_spec = _ToolSpec2(
            name="make_usb_midi_controller",
            description=(
                "Generate a USB-MIDI controller Arduino sketch (.ino) from a natural-language "
                "spec or parameter dict. Supports note-button, CC-knob, and CC-button patterns. "
                "Board selection: teensy40 → TinyUSB backend; pro-micro → LUFA backend. "
                "Returns {sketch: str, manifest: dict, backend: str} on success."
            ),
            input_schema={
                "type": "object",
                "required": ["spec"],
                "properties": {
                    "spec": {
                        "type": ["string", "object"],
                        "description": (
                            "Natural-language string (e.g. 'note button on pin 3, note 72, teensy 4') "
                            "or parameter dict with keys: button_pin, note, velocity, channel, "
                            "control, pot_pin, board."
                        ),
                    },
                },
            },
        )

        async def _make_usb_midi_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"error": f"invalid args: {e}", "code": "BAD_ARGS"})
            spec = a.get("spec", "")
            if not spec:
                return _json.dumps({"error": "'spec' is required", "code": "BAD_ARGS"})
            result = _make_midi(spec)
            return _json.dumps(result)

        ctx.tools.register("make_usb_midi_controller", _midi_spec, _make_usb_midi_tool)
        provides.append("firmware.usb_midi")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load make_usb_midi_controller tool: %s", exc)

    # firmware_flash_via_worker — cloud-relay flash job dispatcher (BYO worker)
    try:
        from kerf_firmware.tools.firmware_flash_via_worker import (
            firmware_flash_via_worker_spec,
            run_firmware_flash_via_worker,
        )
        ctx.tools.register(
            "firmware_flash_via_worker",
            firmware_flash_via_worker_spec,
            run_firmware_flash_via_worker,
        )
        provides.append("firmware.flash_via_worker")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load firmware_flash_via_worker tool: %s", exc)

    # firmware_verify_peripheral_map — MCU peripheral pin-map verifier
    try:
        from kerf_firmware.tools.firmware_verify_peripheral_map import (
            _spec as _pvmap_spec,
            run_firmware_verify_peripheral_map_async as _pvmap_fn,
        )
        ctx.tools.register(
            "firmware_verify_peripheral_map",
            _pvmap_spec,
            _pvmap_fn,
        )
        provides.append("firmware.peripheral_map_verify")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_verify_peripheral_map tool: %s", exc
        )

    # make_usb_macro_keyboard — generate USB-HID macro keyboard Arduino sketch
    try:
        from kerf_firmware.tools.make_usb_macro_keyboard import make_usb_macro_keyboard as _make_macro
        import json as _json

        try:
            from kerf_chat.tools.registry import ToolSpec as _ToolSpec3
        except ImportError:
            from kerf_firmware._compat import ToolSpec as _ToolSpec3  # type: ignore

        _macro_spec = _ToolSpec3(
            name="make_usb_macro_keyboard",
            description=(
                "Generate a USB-HID macro keyboard Arduino sketch (.ino). "
                "The sketch sends a configurable HID keycode (F1–F24, A–Z, digits, Enter, "
                "Space, Escape, or arbitrary 0x00–0xFF hex) when a button is pressed. "
                "Supports Ctrl/Shift/Alt modifiers. Board: teensy40 → TinyUSB; "
                "pro-micro → LUFA. Returns {sketch, manifest, keycode, descriptor_note}."
            ),
            input_schema={
                "type": "object",
                "required": ["spec"],
                "properties": {
                    "spec": {
                        "type": ["string", "object"],
                        "description": (
                            "Natural-language string or dict with keys: "
                            "button_pin (int), send (str, e.g. 'F13'), "
                            "modifier (str, e.g. 'ctrl'), board (str)."
                        ),
                    },
                },
            },
        )

        async def _make_usb_macro_tool(ctx, args: bytes) -> str:
            try:
                a = _json.loads(args)
            except Exception as e:
                return _json.dumps({"error": f"invalid args: {e}", "code": "BAD_ARGS"})
            spec = a.get("spec", "")
            if not spec:
                return _json.dumps({"error": "'spec' is required", "code": "BAD_ARGS"})
            result = _make_macro(spec)
            return _json.dumps(result)

        ctx.tools.register("make_usb_macro_keyboard", _macro_spec, _make_usb_macro_tool)
        provides.append("firmware.usb_hid")
    except Exception as exc:
        logger.warning("kerf-firmware: failed to load make_usb_macro_keyboard tool: %s", exc)

    # firmware_verify_clock_tree — STM32 clock-tree verifier
    try:
        from kerf_firmware.tools.firmware_verify_clock_tree import (
            _spec as _clk_spec,
            run_firmware_verify_clock_tree_async as _clk_fn,
        )
        ctx.tools.register(
            "firmware_verify_clock_tree",
            _clk_spec,
            _clk_fn,
        )
        provides.append("firmware.clock_tree_verify")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_verify_clock_tree tool: %s", exc
        )

    # firmware_verify_dma_assignments — STM32 DMA channel-conflict verifier
    try:
        from kerf_firmware.tools.firmware_verify_dma_assignments import (
            _spec as _dma_spec,
            run_firmware_verify_dma_assignments_async as _dma_fn,
        )
        ctx.tools.register(
            "firmware_verify_dma_assignments",
            _dma_spec,
            _dma_fn,
        )
        provides.append("firmware.dma_channel_verify")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_verify_dma_assignments tool: %s", exc
        )
    # firmware_verify_interrupt_priorities — Cortex-M NVIC priority verifier
    try:
        from kerf_firmware.tools.firmware_verify_interrupt_priorities import (
            _spec as _irq_spec,
            run_firmware_verify_interrupt_priorities_async as _irq_fn,
        )
        ctx.tools.register(
            "firmware_verify_interrupt_priorities",
            _irq_spec,
            _irq_fn,
        )
        provides.append("firmware.interrupt_priority_verify")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_verify_interrupt_priorities tool: %s", exc
        )
    # firmware_verify_memory_map — Cortex-M linker memory-layout verifier
    try:
        from kerf_firmware.tools.firmware_verify_memory_map import (
            _spec as _mm_spec,
            run_firmware_verify_memory_map_async as _mm_fn,
        )
        ctx.tools.register(
            "firmware_verify_memory_map",
            _mm_spec,
            _mm_fn,
        )
        provides.append("firmware.memory_map_verify")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_verify_memory_map tool: %s", exc
        )

    # firmware_compute_can_bus_load — CAN 2.0B / J1939-21 bus utilisation analyser
    try:
        from kerf_firmware.tools.firmware_compute_can_bus_load import (
            _spec as _can_spec,
            run_firmware_compute_can_bus_load_async as _can_fn,
        )
        ctx.tools.register(
            "firmware_compute_can_bus_load",
            _can_spec,
            _can_fn,
        )
        provides.append("firmware.can_bus_load")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_compute_can_bus_load tool: %s", exc
        )

    # firmware_verify_spi_timing — SPI master/slave timing compatibility verifier
    try:
        from kerf_firmware.tools.firmware_verify_spi_timing import (
            _spec as _spi_spec,
            run_firmware_verify_spi_timing_async as _spi_fn,
        )
        ctx.tools.register(
            "firmware_verify_spi_timing",
            _spi_spec,
            _spi_fn,
        )
        provides.append("firmware.spi_timing_verify")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_verify_spi_timing tool: %s", exc
        )

    # firmware_check_i2c_clock_stretch — I²C clock-stretch worst-case speed analyser
    try:
        from kerf_firmware.tools.firmware_check_i2c_clock_stretch import (
            _spec as _i2c_stretch_spec,
            run_firmware_check_i2c_clock_stretch_async as _i2c_stretch_fn,
        )
        ctx.tools.register(
            "firmware_check_i2c_clock_stretch",
            _i2c_stretch_spec,
            _i2c_stretch_fn,
        )
        provides.append("firmware.i2c_clock_stretch_check")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_check_i2c_clock_stretch tool: %s", exc
        )

    # firmware_check_uart_baud_drift — UART baud-rate drift analyser
    try:
        from kerf_firmware.tools.firmware_check_uart_baud_drift import (
            _spec as _uart_baud_spec,
            run_firmware_check_uart_baud_drift_async as _uart_baud_fn,
        )
        ctx.tools.register(
            "firmware_check_uart_baud_drift",
            _uart_baud_spec,
            _uart_baud_fn,
        )
        provides.append("firmware.uart_baud_drift_check")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_check_uart_baud_drift tool: %s", exc
        )

    # firmware_check_watchdog_interval — MCU watchdog timeout interval verifier
    try:
        from kerf_firmware.tools.firmware_check_watchdog_interval import (
            _spec as _wdg_spec,
            run_firmware_check_watchdog_interval_async as _wdg_fn,
        )
        ctx.tools.register(
            "firmware_check_watchdog_interval",
            _wdg_spec,
            _wdg_fn,
        )
        provides.append("firmware.watchdog_interval_check")
    except Exception as exc:
        logger.warning(
            "kerf-firmware: failed to load firmware_check_watchdog_interval tool: %s", exc
        )
