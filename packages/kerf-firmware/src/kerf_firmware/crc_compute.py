"""CRC checksum computation for embedded protocol verification.

Implements table-driven CRC algorithms:
  CRC-8         (poly 0x07, no reflection, init 0x00)
  CRC-16/CCITT  (poly 0x1021, no reflection, init 0xFFFF) — ITU-T V.41
  CRC-16/MODBUS (poly 0x8005/0xA001 reflected, init 0xFFFF) — Modbus RTU spec
  CRC-32        (poly 0x04C11DB7/0xEDB88320 reflected, init 0xFFFFFFFF) — IEEE 802.3
  CRC-32C       (Castagnoli, poly 0x1EDC6F41/0x82F63B78 reflected, init 0xFFFFFFFF) — iSCSI/SCTP

References
----------
  Koopman, P. (2002) "CRC Polynomial Selection for Embedded Networks." FTCS-32.
  Koopman, P. & Chakravarty, T. (2004) "Cyclic Redundancy Code (CRC) Polynomial
      Selection for Embedded Networks." DSN-2004.
  ITU-T Recommendation V.41 (1988) — CRC-CCITT / CRC-16-CCITT.
  IEEE Std 802.3-2018 §3.2.8 — CRC-32 frame check sequence.
  IETF RFC 3720 §B.4 (iSCSI, CRC-32C); RFC 4960 Appendix B (SCTP, CRC-32C).
  Williams, R.N. (1993) "A Painless Guide to CRC Error Detection Algorithms."
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CRCSpec:
    """Input specification for a CRC computation.

    Parameters
    ----------
    data_hex:
        Hex string representing the bytes to process.  May include spaces or
        ``0x`` / ``0X`` prefixes between octets.  Case-insensitive.
        Example: ``"313233343536373839"`` (ASCII "123456789").
    algorithm:
        One of ``"CRC-8"``, ``"CRC-16/CCITT"``, ``"CRC-16/MODBUS"``,
        ``"CRC-32"``, or ``"CRC-32C/Castagnoli"``.
    """
    data_hex: str
    algorithm: str


@dataclass
class CRCResult:
    """Result of a CRC computation.

    Parameters
    ----------
    crc_hex:
        CRC value as a zero-padded uppercase hex string, e.g. ``"29B1"``.
    crc_int:
        CRC value as a plain Python integer.
    crc_bits:
        Width of the CRC register in bits (8, 16, or 32).
    algorithm_used:
        Canonical name of the algorithm that was applied.
    polynomial_hex:
        Polynomial constant used (reflected form for reflected algorithms,
        normal form for non-reflected), e.g. ``"0x1021"``.
    honest_caveat:
        Plain-text note about limitations and scope.
    """
    crc_hex: str
    crc_int: int
    crc_bits: int
    algorithm_used: str
    polynomial_hex: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Table-building helpers
# ---------------------------------------------------------------------------

def _make_crc8_table(poly: int) -> list[int]:
    """Build a 256-entry lookup table for an 8-bit CRC (no reflection)."""
    table: list[int] = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ poly) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
        table.append(crc)
    return table


def _make_crc16_table_normal(poly: int) -> list[int]:
    """Build a 256-entry lookup table for a 16-bit CRC (no reflection)."""
    table: list[int] = []
    for byte in range(256):
        crc = byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ poly) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
        table.append(crc)
    return table


def _make_crc_table_reflected(poly_reflected: int, width: int) -> list[int]:
    """Build a 256-entry lookup table for a reflected (LSB-first) CRC.

    Parameters
    ----------
    poly_reflected:
        Bit-reversed polynomial, e.g. 0xA001 (CRC-16/MODBUS), 0xEDB88320 (CRC-32).
    width:
        Register width in bits (16 or 32).
    """
    mask = (1 << width) - 1
    table: list[int] = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            if crc & 1:
                crc = ((crc >> 1) ^ poly_reflected) & mask
            else:
                crc = (crc >> 1) & mask
        table.append(crc)
    return table


# ---------------------------------------------------------------------------
# Pre-built tables (module-level, built once)
# ---------------------------------------------------------------------------

_TABLE_CRC8: list[int] = _make_crc8_table(0x07)

_TABLE_CRC16_CCITT: list[int] = _make_crc16_table_normal(0x1021)

_TABLE_CRC16_MODBUS: list[int] = _make_crc_table_reflected(0xA001, 16)

_TABLE_CRC32: list[int] = _make_crc_table_reflected(0xEDB88320, 32)

_TABLE_CRC32C: list[int] = _make_crc_table_reflected(0x82F63B78, 32)


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------

def _crc8(data: bytes, table: list[int], init: int = 0x00) -> int:
    crc = init & 0xFF
    for byte in data:
        crc = table[(crc ^ byte) & 0xFF]
    return crc


def _crc16_normal(data: bytes, table: list[int], init: int) -> int:
    """Non-reflected CRC-16 (big-endian shift register)."""
    crc = init & 0xFFFF
    for byte in data:
        crc = ((crc << 8) ^ table[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
    return crc


def _crc16_reflected(data: bytes, table: list[int], init: int) -> int:
    """Reflected CRC-16 (LSB-first processing)."""
    crc = init & 0xFFFF
    for byte in data:
        crc = ((crc >> 8) ^ table[(crc ^ byte) & 0xFF]) & 0xFFFF
    return crc


def _crc32_reflected(data: bytes, table: list[int], init: int) -> int:
    """Reflected CRC-32 (LSB-first processing, output XOR 0xFFFFFFFF)."""
    crc = init & 0xFFFFFFFF
    for byte in data:
        crc = ((crc >> 8) ^ table[(crc ^ byte) & 0xFF]) & 0xFFFFFFFF
    return crc ^ 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Algorithm registry
# ---------------------------------------------------------------------------

_ALGORITHMS: dict[str, dict] = {
    "CRC-8": {
        "bits": 8,
        "poly_hex": "0x07",
        "init": 0x00,
        "fn": lambda data: _crc8(data, _TABLE_CRC8, 0x00),
        "caveat": (
            "CRC-8 (poly 0x07, init 0x00, no reflection, no final XOR). "
            "Hamming distance ≤ 4 for frames up to 119 bits (Koopman 2002 Table I). "
            "NOT recommended for safety-critical links over CAN/LIN — use CRC-16/CRC-32. "
            "CRC-64 and CCITT-augmented variants require a separate tool."
        ),
    },
    "CRC-16/CCITT": {
        "bits": 16,
        "poly_hex": "0x1021",
        "init": 0xFFFF,
        "fn": lambda data: _crc16_normal(data, _TABLE_CRC16_CCITT, 0xFFFF),
        "caveat": (
            "CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no final XOR). "
            "Also known as CRC-CCITT, CRC-16-IBM-SDLC. ITU-T V.41 specifies the basic "
            "polynomial; the init=0xFFFF variant is the 'FALSE' / KERMIT-FALSE flavour. "
            "Hamming distance 4 for frames up to 32,751 bits (Koopman 2002). "
            "Bitwise-reflection variant (CRC-16/CCITT-TRUE, init=0x0000) and "
            "CRC-16/CCITT-AUGMENTED differ and require separate handling."
        ),
    },
    "CRC-16/MODBUS": {
        "bits": 16,
        "poly_hex": "0xA001",
        "init": 0xFFFF,
        "fn": lambda data: _crc16_reflected(data, _TABLE_CRC16_MODBUS, 0xFFFF),
        "caveat": (
            "CRC-16/MODBUS (reflected poly 0xA001 = bit-reverse of 0x8005, init 0xFFFF, "
            "LSB-first processing, no final XOR). Defined in Modbus RTU spec §2.5.1. "
            "Distinct from CRC-16/IBM (init=0x0000) and CRC-16/ARC. "
            "Hamming distance 4 for frames up to 32,767 bits (Koopman 2002 Table II). "
            "Covers standard Modbus frames (max 256 bytes = 2048 bits) with HD=4."
        ),
    },
    "CRC-32": {
        "bits": 32,
        "poly_hex": "0xEDB88320",
        "init": 0xFFFFFFFF,
        "fn": lambda data: _crc32_reflected(data, _TABLE_CRC32, 0xFFFFFFFF),
        "caveat": (
            "CRC-32/ISO-HDLC (reflected poly 0xEDB88320 = bit-reverse of 0x04C11DB7, "
            "init 0xFFFFFFFF, LSB-first, output XOR 0xFFFFFFFF). "
            "IEEE 802.3-2018 §3.2.8 Ethernet FCS; also used in PKZip, gzip, PNG, SATA. "
            "Hamming distance 4 for frames up to 268,435,455 bytes. "
            "CRC-32/BZIP2 (big-endian, no input reflection) and CRC-32/JAMCRC "
            "(no output XOR) differ and require separate handling."
        ),
    },
    "CRC-32C/Castagnoli": {
        "bits": 32,
        "poly_hex": "0x82F63B78",
        "init": 0xFFFFFFFF,
        "fn": lambda data: _crc32_reflected(data, _TABLE_CRC32C, 0xFFFFFFFF),
        "caveat": (
            "CRC-32C (Castagnoli, reflected poly 0x82F63B78 = bit-reverse of 0x1EDC6F41, "
            "init 0xFFFFFFFF, LSB-first, output XOR 0xFFFFFFFF). "
            "IETF RFC 3720 (iSCSI), RFC 4960 (SCTP). "
            "Better error-detection than CRC-32/ISO-HDLC for small packets "
            "(Koopman & Chakravarty 2004). "
            "CRC-64 variants (CRC-64/XZ, CRC-64/ECMA-182) require a separate tool."
        ),
    },
}

# Case-insensitive and partial-match aliases
_ALIASES: dict[str, str] = {
    "crc-8": "CRC-8",
    "crc8": "CRC-8",
    "crc-16/ccitt": "CRC-16/CCITT",
    "crc16/ccitt": "CRC-16/CCITT",
    "crc-16-ccitt": "CRC-16/CCITT",
    "crc16ccitt": "CRC-16/CCITT",
    "crc-ccitt": "CRC-16/CCITT",
    "crc-16/modbus": "CRC-16/MODBUS",
    "crc16/modbus": "CRC-16/MODBUS",
    "crc-16-modbus": "CRC-16/MODBUS",
    "crc16modbus": "CRC-16/MODBUS",
    "crc-32": "CRC-32",
    "crc32": "CRC-32",
    "crc-32/iso-hdlc": "CRC-32",
    "crc32/iso-hdlc": "CRC-32",
    "crc-32c": "CRC-32C/Castagnoli",
    "crc32c": "CRC-32C/Castagnoli",
    "crc-32c/castagnoli": "CRC-32C/Castagnoli",
    "crc32c/castagnoli": "CRC-32C/Castagnoli",
    "crc-32/castagnoli": "CRC-32C/Castagnoli",
}


def _resolve_algorithm(name: str) -> str:
    """Return canonical algorithm name or raise ValueError."""
    canonical = _ALGORITHMS.get(name)
    if canonical is not None:
        return name
    lower = name.lower()
    if lower in _ALIASES:
        return _ALIASES[lower]
    valid = ", ".join(sorted(_ALGORITHMS.keys()))
    raise ValueError(
        f"Unknown algorithm {name!r}. Valid: {valid}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_hex_data(data_hex: str) -> bytes:
    """Parse a hex string into bytes.

    Accepts optional spaces between octets and optional ``0x``/``0X`` prefixes.
    Raises ``ValueError`` if the string is not valid hex.
    """
    cleaned = (
        data_hex
        .replace(" ", "")
        .replace("\t", "")
        .replace("\n", "")
        .replace(",", "")
    )
    # Strip leading 0x/0X tokens if present between bytes
    if cleaned.lower().startswith("0x"):
        cleaned = cleaned[2:]
    # Handle "0x" between bytes: e.g. "0x31 0x32" → "3132"
    import re
    cleaned = re.sub(r"0[xX]", "", cleaned)
    if len(cleaned) % 2 != 0:
        raise ValueError(
            f"Hex string has odd number of nibbles after normalisation: {cleaned!r}"
        )
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid hex data: {exc}") from exc


def compute_crc(spec: CRCSpec) -> CRCResult:
    """Compute the CRC checksum described by *spec*.

    Parameters
    ----------
    spec:
        A :class:`CRCSpec` with ``data_hex`` and ``algorithm``.

    Returns
    -------
    CRCResult
        Contains the CRC value in hex, integer, and bit-width forms, plus the
        canonical algorithm name, polynomial, and an honest caveat string.

    Raises
    ------
    ValueError
        If ``data_hex`` cannot be parsed or ``algorithm`` is not recognised.
    """
    algo_key = _resolve_algorithm(spec.algorithm)
    algo = _ALGORITHMS[algo_key]

    data = parse_hex_data(spec.data_hex)

    crc_int = algo["fn"](data)
    bits: int = algo["bits"]
    nibbles = bits // 4
    fmt = f"{{:0{nibbles}X}}"
    crc_hex = fmt.format(crc_int)

    return CRCResult(
        crc_hex=crc_hex,
        crc_int=crc_int,
        crc_bits=bits,
        algorithm_used=algo_key,
        polynomial_hex=algo["poly_hex"],
        honest_caveat=algo["caveat"],
    )


def supported_algorithms() -> list[str]:
    """Return the list of canonical algorithm names supported by this module."""
    return list(_ALGORITHMS.keys())
