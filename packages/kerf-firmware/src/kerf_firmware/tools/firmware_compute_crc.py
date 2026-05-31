"""LLM tool: firmware_compute_crc — CRC checksum computation for embedded protocols.

Computes CRC-8, CRC-16/CCITT, CRC-16/MODBUS, CRC-32, and CRC-32C/Castagnoli
checksums from a hex-encoded byte payload.  Returns the CRC in hex, integer,
and binary (bit-string) representations along with the polynomial used and an
honest caveat about algorithm scope.

References
----------
  Koopman, P. (2002) "CRC Polynomial Selection for Embedded Networks." FTCS-32.
  ITU-T Recommendation V.41 (1988) — CRC-CCITT.
  IEEE Std 802.3-2018 §3.2.8 — CRC-32 (Ethernet FCS).
  IETF RFC 3720 §B.4 — CRC-32C (iSCSI); RFC 4960 App B — CRC-32C (SCTP).
  Williams, R.N. (1993) "A Painless Guide to CRC Error Detection Algorithms."
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.crc_compute import CRCSpec, compute_crc, supported_algorithms


# ── Tool specification ─────────────────────────────────────────────────────────

_VALID_ALGORITHMS = supported_algorithms()

_spec = ToolSpec(
    name="firmware_compute_crc",
    description=(
        "Compute a CRC checksum (CRC-8, CRC-16/CCITT, CRC-16/MODBUS, CRC-32, or "
        "CRC-32C/Castagnoli) over a hex-encoded byte payload.  Returns the CRC value "
        "in hex, integer, and binary (zero-padded bit-string) forms, plus the "
        "polynomial used and an honest caveat about algorithm scope and limitations.\n\n"
        "Supported algorithms and their canonical parameters:\n"
        "  CRC-8              — poly 0x07, init 0x00, no reflection, no final XOR.\n"
        "  CRC-16/CCITT       — poly 0x1021, init 0xFFFF, no reflection, no final XOR "
        "(ITU-T V.41 / CCITT-FALSE / IBM-SDLC variant).\n"
        "  CRC-16/MODBUS      — reflected poly 0xA001 (≡0x8005), init 0xFFFF, "
        "LSB-first (Modbus RTU spec §2.5.1).\n"
        "  CRC-32             — reflected poly 0xEDB88320 (≡0x04C11DB7), init 0xFFFFFFFF, "
        "output XOR 0xFFFFFFFF (IEEE 802.3 / Ethernet FCS / PKZip / gzip).\n"
        "  CRC-32C/Castagnoli — reflected poly 0x82F63B78 (≡0x1EDC6F41), init 0xFFFFFFFF, "
        "output XOR 0xFFFFFFFF (iSCSI RFC 3720, SCTP RFC 4960).\n\n"
        "Official test vectors (input = ASCII '123456789' = 0x313233343536373839):\n"
        "  CRC-16/CCITT → 0x29B1;  CRC-32 → 0xCBF43926;  CRC-32C → 0xE3069283.\n\n"
        "NOTE: CRC-64 (ECMA-182, XZ), CRC-16/CCITT-TRUE (init=0), CRC-32/BZIP2 "
        "(big-endian), and CRC-32/JAMCRC (no output XOR) are NOT implemented in this "
        "tool and require a separate tool or a manual parameter override."
    ),
    input_schema={
        "type": "object",
        "required": ["data_hex", "algorithm"],
        "properties": {
            "data_hex": {
                "type": "string",
                "description": (
                    "Hex string of the bytes to checksum.  Spaces between octets are "
                    "accepted; optional 0x/0X prefixes per octet are stripped. "
                    "Examples: '313233343536373839' (ASCII '123456789'), "
                    "'DE AD BE EF', '0x01 0x02 0x03'. "
                    "Empty string ('') is accepted and returns the init-value XOR "
                    "final-XOR per algorithm."
                ),
            },
            "algorithm": {
                "type": "string",
                "description": (
                    "CRC algorithm to apply.  Case-insensitive; common aliases accepted. "
                    f"Canonical names: {', '.join(_VALID_ALGORITHMS)}."
                ),
                "enum": _VALID_ALGORITHMS,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_compute_crc(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute CRC computation and return a JSON payload."""
    data_hex = args.get("data_hex")
    algorithm = args.get("algorithm")

    if data_hex is None:
        return err_payload("'data_hex' is required", "BAD_ARGS")
    if not isinstance(data_hex, str):
        return err_payload("'data_hex' must be a string", "BAD_ARGS")
    if algorithm is None:
        return err_payload("'algorithm' is required", "BAD_ARGS")
    if not isinstance(algorithm, str):
        return err_payload("'algorithm' must be a string", "BAD_ARGS")

    spec = CRCSpec(data_hex=data_hex, algorithm=algorithm)

    try:
        result = compute_crc(spec)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Computation error: {exc}", "COMPUTE_ERROR")

    # Build binary representation (zero-padded to crc_bits)
    crc_bin = format(result.crc_int, f"0{result.crc_bits}b")

    return ok_payload({
        "algorithm": result.algorithm_used,
        "polynomial_hex": result.polynomial_hex,
        "crc_hex": result.crc_hex,
        "crc_int": result.crc_int,
        "crc_bits": result.crc_bits,
        "crc_binary": crc_bin,
        "input_bytes": len(data_hex.replace(" ", "").replace("\t", "")) // 2
        if data_hex.strip() else 0,
        "honest_caveat": result.honest_caveat,
    })


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_compute_crc_async(ctx: object, args: bytes) -> str:
    """Async wrapper that parses raw bytes args and delegates to the sync handler."""
    try:
        a = json.loads(args)
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
    return run_firmware_compute_crc(a, ctx)
