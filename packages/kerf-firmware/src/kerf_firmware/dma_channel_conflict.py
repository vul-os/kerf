"""DMA controller channel-assignment conflict verifier for STM32 microcontrollers.

Verifies that a set of (peripheral, controller, stream, channel) DMA assignments
is consistent with the hardware request-mapping tables from the STM32 reference
manuals.  Three classes of violation are detected:

1. **INVALID_ASSIGNMENT** — the (controller, stream, channel, peripheral)
   combination does not appear in the hardware table for the chip.  The
   peripheral either cannot be served by that stream at all, or the correct
   stream/channel is different.  Suggestions list every valid alternative from
   the embedded table.

2. **STREAM_CONFLICT** — two or more peripherals are assigned to the same
   (controller, stream).  Only one DMA request source may be active on a stream
   at a time; having two peripherals configured for the same stream causes one
   to silently lose transfers at runtime.

3. **UNKNOWN_CONTROLLER** — the assignment references a DMA controller name
   (e.g. "DMA3") that does not exist on the chip.

HONEST CAVEAT — STATIC CONFLICT DETECTION ONLY
-----------------------------------------------
This verifier performs **static** conflict detection.  It does NOT model:

  * DMA arbitration priority — stream 0 is highest priority within a
    controller, stream 7 is lowest.  A high-bandwidth peripheral (e.g. ADC
    continuous conversion) placed on a low-priority stream relative to
    lower-bandwidth peripherals is architecturally suboptimal but is NOT
    flagged by this verifier.  Use STM32CubeMX bandwidth estimator for
    throughput analysis.
  * Double-buffer mode, FIFO thresholds, or burst-size interactions.
  * MDMA / BDMA controllers on STM32H7 and later (not supported).
  * Whether DMA is actually enabled in firmware (no HAL/CubeLL configuration
    awareness).

References
----------
  RM0383 Rev 3 §10.3.3 Table 27 — STM32F411 DMA1 request mapping
  RM0383 Rev 3 §10.3.3 Table 28 — STM32F411 DMA2 request mapping
  RM0090 Rev 19 §10.3.3 Table 42 — STM32F407 DMA1 request mapping
  RM0090 Rev 19 §10.3.3 Table 43 — STM32F407 DMA2 request mapping
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

from kerf_firmware.dma_specs import DMAStreamEntry, DMASpec, get_dma_spec


# ──────────────────────────────────────────────────────────────────────────────
# Public input / output data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DMAAssignment:
    """One DMA channel assignment to verify.

    Attributes
    ----------
    peripheral:
        Peripheral signal name, e.g. ``"SPI1_TX"``, ``"USART2_RX"``,
        ``"ADC1"``.  Case-insensitive; matched against the embedded table.
    controller:
        DMA controller, e.g. ``"DMA1"`` or ``"DMA2"``.  Case-insensitive.
    stream:
        Stream number (0–7 for STM32F4xx).
    channel:
        Channel selection (0–7 for STM32F4xx).  Selects which peripheral
        request line is active on this stream.
    label:
        Optional human-readable label for this assignment (e.g. a variable
        name from a CubeMX project).  Used only in violation messages.
    """
    peripheral: str
    controller: str
    stream: int
    channel: int
    label: str = ""


@dataclass
class DMAViolation:
    """A single DMA conflict or misconfiguration violation.

    Attributes
    ----------
    kind:
        One of:
        ``"INVALID_ASSIGNMENT"`` — (controller, stream, channel, peripheral)
        is not in the hardware table;
        ``"STREAM_CONFLICT"`` — two peripherals share the same stream;
        ``"UNKNOWN_CONTROLLER"`` — controller name does not exist on the chip.
    assignment:
        The :class:`DMAAssignment` that triggered the violation.
    detail:
        Human-readable explanation.
    suggestions:
        For ``INVALID_ASSIGNMENT``: list of valid (controller, stream, channel)
        tuples from the hardware table where this peripheral *could* be placed.
        Empty list for other violation kinds.
    """
    kind: str
    assignment: DMAAssignment
    detail: str
    suggestions: List[Tuple[str, int, int]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "peripheral": self.assignment.peripheral,
            "controller": self.assignment.controller,
            "stream": self.assignment.stream,
            "channel": self.assignment.channel,
            "label": self.assignment.label,
            "detail": self.detail,
            "suggestions": [
                {"controller": c, "stream": s, "channel": ch}
                for c, s, ch in self.suggestions
            ],
        }


@dataclass
class DMAConflictReport:
    """Result of :func:`verify_dma_assignments`.

    Attributes
    ----------
    ok:
        ``True`` iff no violations were found.
    violations:
        List of :class:`DMAViolation` objects.
    chip:
        The chip identifier that was checked (canonical form).
    checked:
        Number of assignments that were evaluated.
    """
    ok: bool
    violations: List[DMAViolation]
    chip: str
    checked: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "chip": self.chip,
            "checked": self.checked,
            "violations": [v.as_dict() for v in self.violations],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Core verifier
# ──────────────────────────────────────────────────────────────────────────────

def verify_dma_assignments(
    chip: str | DMASpec,
    assignments: Sequence[DMAAssignment],
) -> DMAConflictReport:
    """Verify DMA controller stream-channel-peripheral assignments.

    Parameters
    ----------
    chip:
        Chip family string (e.g. ``"STM32F411"``, ``"stm32f411re"``,
        ``"STM32F407"``) or a :class:`~kerf_firmware.dma_specs.DMASpec` instance.
        Aliases are resolved via ``get_dma_spec()``.
    assignments:
        Sequence of :class:`DMAAssignment` objects to check.  Each describes
        one peripheral's DMA configuration as (peripheral, controller, stream,
        channel).  Multiple assignments for the same stream are detected as a
        ``STREAM_CONFLICT``.

    Returns
    -------
    DMAConflictReport
        Contains all detected violations.  ``ok`` is ``True`` iff
        ``violations`` is empty.

    Violation rules (RM0383 §10.3.3 Tables 27–28)
    -----------------------------------------------
    1. **UNKNOWN_CONTROLLER** — controller not in chip's controller list.
    2. **INVALID_ASSIGNMENT** — (controller, stream, channel, peripheral)
       not in hardware table. Suggestions list every valid alternative.
    3. **STREAM_CONFLICT** — two assignments use same (controller, stream).

    References
    ----------
    RM0383 Rev 3 §10.3.3 Tables 27 (DMA1) and 28 (DMA2) — STM32F411.
    RM0090 Rev 19 §10.3.3 Tables 42 (DMA1) and 43 (DMA2) — STM32F407.
    """
    if isinstance(chip, str):
        dma_spec: DMASpec = get_dma_spec(chip)
    else:
        dma_spec = chip

    violations: list[DMAViolation] = []
    known_controllers = {c.upper() for c in dma_spec.controllers}

    # ── 1. UNKNOWN_CONTROLLER ─────────────────────────────────────────────────
    for a in assignments:
        c_up = a.controller.upper()
        if c_up not in known_controllers:
            violations.append(DMAViolation(
                kind="UNKNOWN_CONTROLLER",
                assignment=a,
                detail=(
                    f"Controller {a.controller!r} does not exist on "
                    f"{dma_spec.chip_id}. "
                    f"Known controllers: {sorted(dma_spec.controllers)}."
                ),
            ))

    # ── 2. INVALID_ASSIGNMENT ─────────────────────────────────────────────────
    for a in assignments:
        c_up = a.controller.upper()
        if c_up not in known_controllers:
            continue  # already reported above

        p_up = a.peripheral.upper()
        # Look for exact match (controller, stream, channel, peripheral)
        exact = [
            e for e in dma_spec.entries
            if e.controller.upper() == c_up
            and e.stream == a.stream
            and e.channel == a.channel
            and e.peripheral.upper() == p_up
        ]
        if exact:
            continue  # valid

        # Build suggestions: all valid (controller, stream, channel) for this peripheral
        alt_entries = dma_spec.valid_channels_for_peripheral(a.peripheral)
        suggestions = [(e.controller, e.stream, e.channel) for e in alt_entries]

        # Construct diagnostic detail
        # Check if peripheral is valid on this stream at all (wrong channel only)
        on_stream_any_channel = [
            e for e in dma_spec.entries
            if e.controller.upper() == c_up
            and e.stream == a.stream
            and e.peripheral.upper() == p_up
        ]
        if on_stream_any_channel:
            valid_chs = [str(e.channel) for e in on_stream_any_channel]
            detail = (
                f"Peripheral {a.peripheral!r} on {a.controller}/Stream{a.stream} "
                f"requires channel {', '.join(valid_chs)}, not channel {a.channel}. "
                f"(RM0383 §10.3.3 Table {'27' if c_up == 'DMA1' else '28'})"
            )
        elif alt_entries:
            alt_strs = [
                f"{e.controller}/Stream{e.stream}/Ch{e.channel}"
                for e in alt_entries[:4]
            ]
            detail = (
                f"Peripheral {a.peripheral!r} cannot be served by "
                f"{a.controller}/Stream{a.stream}/Ch{a.channel}. "
                f"Valid assignments from RM0383 §10.3.3: {', '.join(alt_strs)}."
            )
        else:
            detail = (
                f"Peripheral {a.peripheral!r} is not listed in the DMA "
                f"request-mapping table for {dma_spec.chip_id}. "
                f"Check spelling or whether this peripheral uses DMA."
            )

        violations.append(DMAViolation(
            kind="INVALID_ASSIGNMENT",
            assignment=a,
            detail=detail,
            suggestions=suggestions,
        ))

    # ── 3. STREAM_CONFLICT ────────────────────────────────────────────────────
    # Group valid assignments by (controller, stream)
    stream_map: dict[tuple[str, int], list[DMAAssignment]] = {}
    for a in assignments:
        c_up = a.controller.upper()
        if c_up not in known_controllers:
            continue
        key = (c_up, a.stream)
        stream_map.setdefault(key, []).append(a)

    for (ctrl, stream), asgns in stream_map.items():
        if len(asgns) > 1:
            names = [a.peripheral for a in asgns]
            label_part = (
                " / ".join(a.label for a in asgns if a.label) or ""
            )
            detail = (
                f"Stream conflict: {ctrl}/Stream{stream} is assigned to "
                f"multiple peripherals: {names}. "
                f"Only one DMA request source can be active on a stream. "
                + (f"Labels: {label_part}." if label_part else "")
            )
            for a in asgns:
                violations.append(DMAViolation(
                    kind="STREAM_CONFLICT",
                    assignment=a,
                    detail=detail,
                ))

    return DMAConflictReport(
        ok=len(violations) == 0,
        violations=violations,
        chip=dma_spec.chip_id,
        checked=len(assignments),
    )
