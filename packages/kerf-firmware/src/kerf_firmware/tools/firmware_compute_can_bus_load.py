"""LLM tool: firmware_compute_can_bus_load — CAN bus utilisation analyser.

Computes the total CAN bus load (% utilisation) for a set of periodic messages
at a given bit-rate and flags when the load exceeds the CAN specification's
recommended 30–40% maximum for deterministic behaviour.

References
----------
  CAN 2.0B specification (Robert Bosch GmbH, 1991) §A/B — frame format.
  ISO 11898-1:2015 §10 — data-link layer bit timing.
  SAE J1939-21:2010 §5.2 — recommended maximum bus load (40%).
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.can_bus_load import CanMessage, compute_can_bus_load


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_compute_can_bus_load",
    description=(
        "Compute CAN bus utilisation (% of bit-rate consumed) for a set of periodic "
        "CAN messages.  Returns per-message load breakdown and flags when total load "
        "exceeds the J1939-21 §5.2 recommended maximum of 40% (deterministic latency "
        "cannot be guaranteed above this threshold) and the conservative ISO 26262 "
        "ASIL-D planning threshold of 30%.\n\n"
        "Frame bit model (CAN 2.0B, ISO 11898-1:2015 §10):\n"
        "  Standard 11-bit ID: 47 + 8·data_bytes + 24 avg stuffing bits per frame.\n"
        "  Extended 29-bit ID: 67 + 8·data_bytes + 24 avg stuffing bits per frame.\n"
        "  Bus load = Σ(frames_per_sec × bits_per_frame) / bit_rate_bps × 100%.\n\n"
        "Depth-bar oracle (500 kbps, 10 × 8-byte standard-ID messages, 100 ms period):\n"
        "  bits_per_frame = 47 + 64 + 24 = 135; frames/s = 10; "
        "total = 13,500 bps; load = 2.7%.  OK.\n\n"
        "NOTE: stuffing overhead is the 24-bit average (typical random data); "
        "worst-case can be higher — add ≥ 10% headroom for production use. "
        "Error frames and aperiodic bursts are not modelled."
    ),
    input_schema={
        "type": "object",
        "required": ["messages", "bit_rate_bps"],
        "properties": {
            "messages": {
                "type": "array",
                "description": (
                    "List of periodic CAN messages to analyse. "
                    "Each message requires: name, can_id, data_bytes (0–8), period_ms. "
                    "Optional: extended_id (bool, default false for 11-bit ID). "
                    "Model event-driven messages at their worst-case burst period."
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "can_id", "data_bytes", "period_ms"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Human-readable message name, e.g. 'ENGINE_SPEED'.",
                        },
                        "can_id": {
                            "type": "integer",
                            "description": (
                                "CAN identifier. 0–0x7FF for standard 11-bit ID; "
                                "0–0x1FFFFFFF for extended 29-bit ID. "
                                "Must match extended_id flag."
                            ),
                            "minimum": 0,
                            "maximum": 536870911,
                        },
                        "data_bytes": {
                            "type": "integer",
                            "description": "DLC — number of data bytes per frame (0–8 per CAN 2.0B §A.6).",
                            "minimum": 0,
                            "maximum": 8,
                        },
                        "period_ms": {
                            "type": "number",
                            "description": "Transmission period in milliseconds (must be > 0).",
                            "exclusiveMinimum": 0,
                        },
                        "extended_id": {
                            "type": "boolean",
                            "description": (
                                "True for CAN 2.0B extended 29-bit ID frame (67 fixed bits). "
                                "False (default) for standard 11-bit ID frame (47 fixed bits). "
                                "J1939-21 uses extended ID exclusively."
                            ),
                            "default": False,
                        },
                    },
                },
                "minItems": 1,
            },
            "bit_rate_bps": {
                "type": "integer",
                "description": (
                    "CAN bus bit-rate in bits per second. "
                    "Common values: 125000 (125 kbps), 250000, 500000 (500 kbps), "
                    "1000000 (1 Mbps — CAN 2.0B maximum per ISO 11898-2)."
                ),
                "minimum": 1,
                "examples": [125000, 250000, 500000, 1000000],
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_compute_can_bus_load(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute CAN bus load computation and return a JSON payload."""
    raw_messages = args.get("messages")
    bit_rate_bps = args.get("bit_rate_bps")

    if not raw_messages:
        return err_payload("'messages' is required and must be non-empty", "BAD_ARGS")
    if not isinstance(raw_messages, list):
        return err_payload("'messages' must be a JSON array", "BAD_ARGS")
    if bit_rate_bps is None:
        return err_payload("'bit_rate_bps' is required", "BAD_ARGS")
    try:
        bit_rate_bps = int(bit_rate_bps)
    except (TypeError, ValueError) as exc:
        return err_payload(f"'bit_rate_bps' must be an integer: {exc}", "BAD_ARGS")
    if bit_rate_bps <= 0:
        return err_payload("'bit_rate_bps' must be > 0", "BAD_ARGS")

    # Parse message list
    messages: list[CanMessage] = []
    for i, item in enumerate(raw_messages):
        if not isinstance(item, dict):
            return err_payload(f"messages[{i}] must be a JSON object", "BAD_ARGS")
        try:
            name = str(item["name"])
            can_id = int(item["can_id"])
            data_bytes = int(item["data_bytes"])
            period_ms = float(item["period_ms"])
        except KeyError as exc:
            return err_payload(f"messages[{i}] missing required field {exc}", "BAD_ARGS")
        except (TypeError, ValueError) as exc:
            return err_payload(f"messages[{i}] invalid value: {exc}", "BAD_ARGS")

        extended_id = bool(item.get("extended_id", False))

        try:
            messages.append(CanMessage(
                name=name,
                can_id=can_id,
                data_bytes=data_bytes,
                period_ms=period_ms,
                extended_id=extended_id,
            ))
        except ValueError as exc:
            return err_payload(f"messages[{i}] invalid: {exc}", "BAD_ARGS")

    try:
        report = compute_can_bus_load(messages, bit_rate_bps)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Computation error: {exc}", "COMPUTE_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_compute_can_bus_load_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_compute_can_bus_load(a, ctx)
