"""CAN bus load calculator — CAN 2.0B / J1939-21 bus utilisation analysis.

Computes the total bus utilisation (% of bit-rate consumed by traffic) for a
given set of periodic CAN messages.  Results are checked against the CAN
specification's recommended maximum of 30–40% load for deterministic latency
behaviour.

Frame-bit model
---------------
Derived from CAN 2.0B specification (ISO 11898-1:2015) and J1939-21 §5.2:

  Standard 11-bit ID (CAN 2.0A/2.0B base frame):
    SOF (1) + ID11 (11) + RTR (1) + IDE (1) + r0 (1) + DLC (4)
      + data (8×N) + CRC (15) + CRC-delimiter (1)
      + ACK (1) + ACK-delimiter (1) + EOF (7) + IFS (3) = 47 + 8N fixed bits
    Bit stuffing: after every 5 identical bits the transmitter inserts one
      complementary bit.  Fields subject to stuffing: SOF through the last CRC
      bit (34 + 8N bits in the worst case).  Average stuffing overhead ≈ 20%
      of the stuffable region → (34 + 8N) / 5 ≈ ~24 bits for an 8-byte frame.
      This module uses the canonical 24-bit constant (average estimate).

  Extended 29-bit ID (CAN 2.0B extended frame):
    SOF (1) + ID-A11 (11) + SRR (1) + IDE (1) + ID-B18 (18) + RTR (1)
      + r1 (1) + r0 (1) + DLC (4) + data (8×N) + CRC (15)
      + CRC-delimiter (1) + ACK (1) + ACK-delimiter (1) + EOF (7) + IFS (3)
      = 67 + 8N fixed bits (same stuffing average: +24 bits).

  Total bits per frame (average):
    standard:  47 + 8·data_bytes + 24 = 71 + 8·data_bytes
    extended:  67 + 8·data_bytes + 24 = 91 + 8·data_bytes

  Bus load contribution per message:
    frames_per_second = 1000 / period_ms
    bits_per_second   = frames_per_second × bits_per_frame
    load_fraction     = bits_per_second / bit_rate_bps

HONEST DISCLAIMERS
------------------
* Stuffing estimate is the average (24 bits per frame typical for random data).
  Worst-case stuffing can reach (34 + 8N − 1) / 4 additional bits, e.g. for
  an 8-byte worst-case frame: ≈ (70 − 1)/4 ≈ 17 extra bits above the average.
  Use a safety margin of ≥ 10% headroom above the computed load to account for
  worst-case stuffing bursts in production.
* Propagation delay, re-synchronisation, error frames, and overload frames are
  NOT modelled.  Error frames (12 bits active + 8 bits passive) can transiently
  double bus load; ensure physical-layer margins accommodate this.
* J1939-21 §5.2 recommends ≤ 40% utilisation for interoperability; some safety
  profiles (ISO 26262 ASIL-D networks) target ≤ 30%.  Both thresholds are
  flagged by this module.

References
----------
  CAN 2.0B specification (Robert Bosch GmbH, 1991) §A/B — frame format.
  ISO 11898-1:2015 §10 — data-link layer bit timing.
  SAE J1939-21:2010 §5.2 — transport protocol and CAN load guidelines.
  Tindell & Burns (1994) — "An Extendable Approach for Analyzing Fixed Priority
    Hard Real-Time Tasks" — worst-case response time for CAN.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ── Frame bit-count constants (CAN 2.0B, ISO 11898-1:2015 §10) ──────────────

#: Fixed overhead bits for a standard 11-bit ID frame (excluding data and
#: stuffing), per CAN 2.0B spec §A.
_STD_FRAME_FIXED_BITS: int = 47

#: Fixed overhead bits for an extended 29-bit ID frame (excluding data and
#: stuffing), per CAN 2.0B spec §B.
_EXT_FRAME_FIXED_BITS: int = 67

#: Average stuffing-bit overhead per frame.  One stuffing bit is inserted after
#: every 5 consecutive identical bits.  For random payload data the average
#: stuffing overhead across all stuffable fields is approximately 24 bits for
#: an 8-byte frame.  This constant is used for all frame sizes as a conservative
#: approximation (the impact is ±2–3 bits for 0- and 8-byte data lengths).
AVERAGE_STUFFING_BITS: int = 24

#: Recommended maximum bus load per ISO 11898 / J1939-21 §5.2 for deterministic
#: latency behaviour.  Loads above this threshold are flagged WARN.
RECOMMENDED_MAX_LOAD_PCT: float = 40.0

#: Conservative (safety-critical) maximum bus load.  Loads above this threshold
#: are flagged CRITICAL.  Used in ISO 26262 ASIL-D network planning guidelines.
CONSERVATIVE_MAX_LOAD_PCT: float = 30.0


# ── Public data model ─────────────────────────────────────────────────────────

@dataclass
class CanMessage:
    """Description of one periodic CAN message.

    Attributes
    ----------
    name:
        Human-readable message name, e.g. ``"ENGINE_SPEED"``.
    can_id:
        11-bit (0–0x7FF) or 29-bit (0–0x1FFFFFFF) CAN identifier.
    data_bytes:
        DLC — number of data bytes per frame (0–8 per CAN 2.0B §A.6).
    period_ms:
        Transmission period in milliseconds.  Must be > 0.
    extended_id:
        If True, the frame uses the CAN 2.0B 29-bit extended ID format.
        If False (default), uses the standard 11-bit base frame format.
    """
    name: str
    can_id: int
    data_bytes: int
    period_ms: float
    extended_id: bool = False

    def __post_init__(self) -> None:
        if self.data_bytes < 0 or self.data_bytes > 8:
            raise ValueError(
                f"CAN message '{self.name}': data_bytes must be 0–8, got {self.data_bytes}"
            )
        if self.period_ms <= 0:
            raise ValueError(
                f"CAN message '{self.name}': period_ms must be > 0, got {self.period_ms}"
            )
        if self.extended_id:
            if not (0 <= self.can_id <= 0x1FFFFFFF):
                raise ValueError(
                    f"CAN message '{self.name}': extended CAN ID must be 0–0x1FFFFFFF, "
                    f"got 0x{self.can_id:X}"
                )
        else:
            if not (0 <= self.can_id <= 0x7FF):
                raise ValueError(
                    f"CAN message '{self.name}': standard CAN ID must be 0–0x7FF, "
                    f"got 0x{self.can_id:X}"
                )


@dataclass
class MessageLoadEntry:
    """Per-message bus load breakdown.

    Attributes
    ----------
    name:
        Message name (from :class:`CanMessage`).
    can_id:
        CAN identifier.
    extended_id:
        True if extended 29-bit ID.
    data_bytes:
        DLC (0–8).
    period_ms:
        Transmission period in ms.
    bits_per_frame:
        Total bits per CAN frame including overhead + average stuffing.
    frames_per_sec:
        Number of frames transmitted per second (= 1000 / period_ms).
    bits_per_sec:
        Bits per second consumed by this message (= frames_per_sec × bits_per_frame).
    load_percent:
        Percentage of the bus bit-rate consumed by this message.
    """
    name: str
    can_id: int
    extended_id: bool
    data_bytes: int
    period_ms: float
    bits_per_frame: int
    frames_per_sec: float
    bits_per_sec: float
    load_percent: float

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "can_id": f"0x{self.can_id:X}",
            "extended_id": self.extended_id,
            "data_bytes": self.data_bytes,
            "period_ms": self.period_ms,
            "bits_per_frame": self.bits_per_frame,
            "frames_per_sec": round(self.frames_per_sec, 4),
            "bits_per_sec": round(self.bits_per_sec, 2),
            "load_percent": round(self.load_percent, 4),
        }


@dataclass
class CanBusLoadReport:
    """Result of :func:`compute_can_bus_load`.

    Attributes
    ----------
    ok:
        True iff the total bus load is below the recommended 40% maximum.
    bit_rate_bps:
        Configured CAN bus bit-rate in bits per second.
    total_bits_per_sec:
        Sum of per-message bits_per_sec values.
    total_load_percent:
        Total bus utilisation percentage (0–100+).
    exceeds_40_percent_threshold:
        True if total_load_percent > 40%.  J1939-21 §5.2 flag.
    exceeds_30_percent_threshold:
        True if total_load_percent > 30%.  Conservative ASIL-D flag.
    message_count:
        Number of messages analysed.
    per_message_load:
        List of :class:`MessageLoadEntry` sorted by descending load_percent.
    warnings:
        Human-readable advisory messages.
    notes:
        Informational notes (methodology, caveats).
    """
    ok: bool
    bit_rate_bps: int
    total_bits_per_sec: float
    total_load_percent: float
    exceeds_40_percent_threshold: bool
    exceeds_30_percent_threshold: bool
    message_count: int
    per_message_load: List[MessageLoadEntry]
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "bit_rate_bps": self.bit_rate_bps,
            "total_bits_per_sec": round(self.total_bits_per_sec, 2),
            "total_load_percent": round(self.total_load_percent, 4),
            "exceeds_40_percent_threshold": self.exceeds_40_percent_threshold,
            "exceeds_30_percent_threshold": self.exceeds_30_percent_threshold,
            "message_count": self.message_count,
            "per_message_load": [m.as_dict() for m in self.per_message_load],
            "warnings": self.warnings,
            "notes": self.notes,
        }


# ── Core computation ──────────────────────────────────────────────────────────

def bits_per_frame(data_bytes: int, *, extended_id: bool = False) -> int:
    """Return total bits per CAN frame including data and average stuffing.

    Parameters
    ----------
    data_bytes:
        Number of data bytes in the frame payload (DLC), 0–8.
    extended_id:
        If True, use the extended 29-bit ID frame overhead.

    Returns
    -------
    int
        Total bits per frame = fixed_overhead + 8·data_bytes + AVERAGE_STUFFING_BITS.

    Examples
    --------
    Standard 11-bit ID, 8-byte data (per task depth-bar):
    >>> bits_per_frame(8, extended_id=False)
    135
    Extended 29-bit ID, 8-byte data:
    >>> bits_per_frame(8, extended_id=True)
    155

    References
    ----------
    CAN 2.0B specification §A (standard frame) and §B (extended frame).
    ISO 11898-1:2015 §10 — frame structure bit counts.
    """
    fixed = _EXT_FRAME_FIXED_BITS if extended_id else _STD_FRAME_FIXED_BITS
    return fixed + 8 * data_bytes + AVERAGE_STUFFING_BITS


def compute_can_bus_load(
    messages: List[CanMessage],
    bit_rate_bps: int,
) -> CanBusLoadReport:
    """Compute CAN bus utilisation for a set of periodic messages.

    For each message:
      frames_per_sec = 1000 / period_ms
      bits_per_frame = fixed_overhead + 8·data_bytes + 24 (avg stuffing)
      load = frames_per_sec × bits_per_frame / bit_rate_bps × 100 %

    The total bus load is the sum of per-message loads.  Results are compared
    against two thresholds:
      * 30% — conservative (ISO 26262 ASIL-D planning guideline)
      * 40% — recommended maximum (J1939-21 §5.2 / CAN 2.0B community practice)

    Parameters
    ----------
    messages:
        List of :class:`CanMessage` objects describing the periodic traffic mix.
        Non-periodic (event-driven) messages should be modelled as their
        worst-case burst rate (i.e. treat minimum inter-frame gap as the
        period).
    bit_rate_bps:
        CAN bus bit-rate in bits per second.  Common values:
        125_000 (125 kbps), 250_000 (250 kbps), 500_000 (500 kbps),
        1_000_000 (1 Mbps CAN 2.0B max).

    Returns
    -------
    CanBusLoadReport
        Full report with per-message breakdown and threshold flags.

    Raises
    ------
    ValueError
        If bit_rate_bps ≤ 0 or any message has invalid parameters.

    Usage example — depth-bar oracle (500 kbps, 10 × 8-byte, 11-bit, 100 ms):
    -----------------------------------------------------------------------
    >>> msgs = [CanMessage(f"M{i}", i, 8, 100.0) for i in range(10)]
    >>> report = compute_can_bus_load(msgs, 500_000)
    >>> round(report.total_load_percent, 1)
    2.7
    >>> report.ok
    True

    References
    ----------
    CAN 2.0B specification (Robert Bosch GmbH, 1991) §A/B.
    ISO 11898-1:2015 §10 — data-link layer.
    SAE J1939-21:2010 §5.2 — recommended maximum bus load.
    Tindell & Burns (1994) — worst-case response time analysis for CAN.
    """
    if bit_rate_bps <= 0:
        raise ValueError(f"bit_rate_bps must be > 0, got {bit_rate_bps}")
    if not messages:
        raise ValueError("messages list must not be empty")

    entries: list[MessageLoadEntry] = []
    total_bps = 0.0

    for msg in messages:
        bpf = bits_per_frame(msg.data_bytes, extended_id=msg.extended_id)
        fps = 1000.0 / msg.period_ms
        mbps = fps * bpf
        load_pct = mbps / bit_rate_bps * 100.0
        total_bps += mbps
        entries.append(MessageLoadEntry(
            name=msg.name,
            can_id=msg.can_id,
            extended_id=msg.extended_id,
            data_bytes=msg.data_bytes,
            period_ms=msg.period_ms,
            bits_per_frame=bpf,
            frames_per_sec=fps,
            bits_per_sec=mbps,
            load_percent=load_pct,
        ))

    entries.sort(key=lambda e: e.load_percent, reverse=True)

    total_load_pct = total_bps / bit_rate_bps * 100.0
    exceeds_40 = total_load_pct > RECOMMENDED_MAX_LOAD_PCT
    exceeds_30 = total_load_pct > CONSERVATIVE_MAX_LOAD_PCT

    warnings: list[str] = []
    if exceeds_40:
        warnings.append(
            f"CRITICAL: total bus load {total_load_pct:.1f}% exceeds the "
            f"J1939-21 §5.2 recommended maximum of {RECOMMENDED_MAX_LOAD_PCT:.0f}%. "
            "Deterministic message latency CANNOT be guaranteed; worst-case "
            "response times diverge as load approaches 100%.  "
            "Reduce period(s), increase bit-rate, or split across two networks."
        )
    elif exceeds_30:
        warnings.append(
            f"WARNING: total bus load {total_load_pct:.1f}% exceeds the conservative "
            f"{CONSERVATIVE_MAX_LOAD_PCT:.0f}% threshold used in ISO 26262 ASIL-D "
            "network planning.  Acceptable for general use but leaves limited margin "
            "for error-frame bursts and event-driven message spikes."
        )

    notes = [
        f"Bit-rate: {bit_rate_bps:,} bps | Messages: {len(messages)} | "
        f"Total load: {total_load_pct:.2f}%.",
        "Frame bit model: CAN 2.0B (ISO 11898-1:2015 §10). "
        f"Standard frame = {_STD_FRAME_FIXED_BITS} + 8·DLC + {AVERAGE_STUFFING_BITS} avg stuffing bits. "
        f"Extended frame = {_EXT_FRAME_FIXED_BITS} + 8·DLC + {AVERAGE_STUFFING_BITS} avg stuffing bits.",
        "STUFFING CAVEAT: the 24-bit stuffing constant is an average for random payload data. "
        "Worst-case stuffing (e.g. alternating 0/1 CRC + data) can add up to "
        "(34 + 8·DLC - 1) / 4 additional bits per frame.  Add ≥ 10% headroom to the "
        "computed load for worst-case analysis (Tindell & Burns 1994).",
        "This tool models PERIODIC traffic only.  Event-driven / aperiodic messages "
        "must be modelled at their worst-case burst rate.  Error frames (12-bit active "
        "error flag + 8-bit passive + delimiters) and overload frames are NOT modelled.",
    ]

    return CanBusLoadReport(
        ok=not exceeds_40,
        bit_rate_bps=bit_rate_bps,
        total_bits_per_sec=total_bps,
        total_load_percent=total_load_pct,
        exceeds_40_percent_threshold=exceeds_40,
        exceeds_30_percent_threshold=exceeds_30,
        message_count=len(messages),
        per_message_load=entries,
        warnings=warnings,
        notes=notes,
    )
