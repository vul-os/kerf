"""Cortex-M NVIC interrupt priority assignment verifier for STM32 microcontrollers.

Verifies that a set of (peripheral, priority) NVIC assignments is consistent
with Cortex-M priority rules and recommended application-level priority bands.
Four classes of violation are detected:

1. **OUT_OF_RANGE** — priority value outside [0, 2^priority_bits - 1].  On
   STM32F4xx (4-bit field) valid values are 0..15.  An out-of-range value in
   the NVIC_IPR register silently wraps/truncates hardware, so this is a
   hard error.  (ARM Cortex-M Generic User Guide §B3.3)

2. **SAME_PREEMPT_PRIORITY** — two or more peripherals are assigned the same
   preemption priority level.  Per ARM Cortex-M Generic User Guide §B3.3,
   when two IRQs at the same preemption priority are both pending, the one
   with the lower IRQ number is selected; there is NO temporal ordering
   guarantee for software.  This is flagged as a potential non-determinism
   hazard unless explicitly acknowledged.

3. **RT_IN_LOW_BAND** — a peripheral classified as real-time critical
   (e.g. TIM, EXTI) has been assigned a priority in the LOW band (9..15),
   meaning it will be pre-empted by NORMAL-band interrupts.  This inverts
   the expected priority hierarchy.

4. **NON_RT_IN_RT_BAND** — a non-real-time peripheral (USB, ADC, RTC) has
   been placed in the RT band (0..3), consuming a high-priority slot
   unnecessarily and potentially starving real-time ISRs.

HONEST CAVEAT — STATIC ANALYSIS ONLY
-------------------------------------
This verifier performs **static** analysis on the declared priority values.
It does NOT model:
  * Actual ISR execution time (WCET).  A "correct" priority assignment can still
    cause latency violations if ISR bodies are too long.
  * BASEPRI masking effect on specific code paths — the verifier checks only
    that BASEPRI_threshold > 0 (i.e. masking is configured) and that it is in
    a reasonable range.  It does NOT trace BASEPRI write/restore sequences.
  * Priority inheritance from FreeRTOS/CMSIS-RTOS mutexes.
  * The FAULTMASK / PRIMASK interaction.
  * Tail-chaining or late-arrival timing on Cortex-M pipeline.

Use ARM DS-5, Tracealyzer, or a hardware logic-analyser for runtime interrupt
timing measurement.

References
----------
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §B3.3 — NVIC_IPR registers
    and AIRCR.PRIGROUP preemption/sub-priority split.
  ARM Cortex-M Generic User Guide §B1.5.4 — BASEPRI register.
  RM0383 Rev 3 §10 — STM32F411 NVIC, 62 maskable IRQs.
  RM0090 Rev 19 §10 — STM32F407 NVIC, 82 maskable IRQs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kerf_firmware.interrupt_specs import (
    InterruptSpec,
    IRQSpec,
    RT_BAND,
    NORMAL_BAND,
    LOW_BAND,
    get_interrupt_spec,
)


# ──────────────────────────────────────────────────────────────────────────────
# Public input / output data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IRQAssignment:
    """One NVIC priority assignment to verify.

    Attributes
    ----------
    peripheral:
        Peripheral name, e.g. ``"TIM2"``, ``"USART1"``, ``"EXTI0"``,
        ``"OTG_FS"``.  Case-insensitive; matched via :meth:`InterruptSpec.irq_by_name`.
    priority:
        Raw NVIC_IPR priority value (0..15 for STM32F4xx 4-bit field).
        Priority 0 = highest actual priority; 15 = lowest.
        (ARM Cortex-M Generic User Guide §B3.3 — "lower priority number wins")
    label:
        Optional human-readable label (e.g. a CubeMX variable name).
        Used only in violation messages.
    """
    peripheral: str
    priority: int
    label: str = ""


@dataclass
class PriorityViolation:
    """A single NVIC priority violation.

    Attributes
    ----------
    kind:
        One of:
        ``"OUT_OF_RANGE"``         — priority value outside valid range.
        ``"SAME_PREEMPT_PRIORITY"`` — two peripherals share a preemption level.
        ``"RT_IN_LOW_BAND"``       — RT peripheral has a low-priority number.
        ``"NON_RT_IN_RT_BAND"``    — non-RT peripheral in the RT band.
        ``"UNKNOWN_PERIPHERAL"``   — peripheral name not in chip's IRQ table.
        ``"BASEPRI_MISCONFIGURED"`` — BASEPRI threshold is out of range or 0
                                      when critical sections are declared.
    assignment:
        The :class:`IRQAssignment` that triggered the violation.
    detail:
        Human-readable explanation.
    peers:
        For ``SAME_PREEMPT_PRIORITY``: list of peripheral names that share
        the same preemption priority level.  Empty for other kinds.
    """
    kind: str
    assignment: IRQAssignment
    detail: str
    peers: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "peripheral": self.assignment.peripheral,
            "priority": self.assignment.priority,
            "label": self.assignment.label,
            "detail": self.detail,
            "peers": self.peers,
        }


@dataclass
class InterruptPriorityReport:
    """Result of :func:`verify_interrupt_priorities`.

    Attributes
    ----------
    ok:
        ``True`` iff no violations were found.
    violations:
        List of :class:`PriorityViolation` objects.
    chip:
        Canonical chip identifier.
    checked:
        Number of IRQ assignments evaluated.
    prigroup:
        AIRCR.PRIGROUP value used for preemption-level calculations.
    num_preempt_levels:
        Number of independent preemption levels given *prigroup*.
    notes:
        Advisory notes (e.g. BASEPRI configuration tips).
    """
    ok: bool
    violations: List[PriorityViolation]
    chip: str
    checked: int
    prigroup: int
    num_preempt_levels: int
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "chip": self.chip,
            "checked": self.checked,
            "prigroup": self.prigroup,
            "num_preempt_levels": self.num_preempt_levels,
            "violations": [v.as_dict() for v in self.violations],
            "notes": self.notes,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Helper: preemption priority from raw priority value
# ──────────────────────────────────────────────────────────────────────────────

def _preempt_priority(raw: int, priority_bits: int, prigroup: int) -> int:
    """Extract the preemption-priority field from a raw NVIC_IPR value.

    ARM Cortex-M Generic User Guide §B3.3 Table B3-2:
      PRIGROUP splits the 8-bit NVIC_IPR byte at bit position PRIGROUP.
      Using the CMSIS NVIC_EncodePriority convention:
        preempt_bits = min(priority_bits, max(0, 7 - prigroup))
        sub_bits     = priority_bits - preempt_bits
      The preemption priority occupies the upper preempt_bits of the raw value.

    Parameters
    ----------
    raw:
        Raw priority value (0..2^priority_bits - 1).
    priority_bits:
        Number of implemented priority bits (4 for STM32F4xx).
    prigroup:
        AIRCR.PRIGROUP value (3..7 typical for Cortex-M).

    Returns
    -------
    int
        Preemption priority value (0..2^preempt_bits - 1).
    """
    # CMSIS NVIC_EncodePriority formula
    preempt_bits = min(priority_bits, max(0, 7 - prigroup))
    sub_bits = priority_bits - preempt_bits
    # Preemption priority is the upper preempt_bits of raw
    preempt_val = raw >> sub_bits
    mask = (1 << preempt_bits) - 1
    return preempt_val & mask


# ──────────────────────────────────────────────────────────────────────────────
# Core verifier
# ──────────────────────────────────────────────────────────────────────────────

def verify_interrupt_priorities(
    chip: str | InterruptSpec,
    assignments: Sequence[IRQAssignment],
    *,
    prigroup: Optional[int] = None,
    basepri_threshold: Optional[int] = None,
    allow_same_preempt: bool = False,
) -> InterruptPriorityReport:
    """Verify Cortex-M NVIC interrupt priority assignments.

    Parameters
    ----------
    chip:
        Chip family string (e.g. ``"STM32F411"``, ``"stm32f411re"``,
        ``"STM32F407"``) or an :class:`~kerf_firmware.interrupt_specs.InterruptSpec`
        instance.  Aliases are resolved via :func:`get_interrupt_spec`.
    assignments:
        Sequence of :class:`IRQAssignment` objects.  Each describes one
        peripheral's NVIC priority configuration.
    prigroup:
        AIRCR.PRIGROUP value to use for preemption-priority extraction.  If
        ``None``, the chip's :attr:`~InterruptSpec.prigroup_default` is used.
        (ARM Cortex-M Generic User Guide §B3.3)
    basepri_threshold:
        If provided, the BASEPRI value used for critical-section masking.
        BASEPRI = 0 disables masking entirely (all IRQs fire); BASEPRI = N
        masks all IRQs with priority >= N.  The verifier checks that the value
        is in [1, max_priority] when specified.
        (ARM Cortex-M Generic User Guide §B1.5.4)
    allow_same_preempt:
        If ``True``, suppress ``SAME_PREEMPT_PRIORITY`` violations.  Use when
        you deliberately share preemption levels and accept the tie-break
        behavior (lower IRQ number wins).

    Returns
    -------
    InterruptPriorityReport
        Full report including all violations and advisory notes.

    Violation rules
    ---------------
    1. **UNKNOWN_PERIPHERAL** — peripheral name not in the chip's IRQ table.
    2. **OUT_OF_RANGE** — priority value outside [0, max_priority].
    3. **SAME_PREEMPT_PRIORITY** — two peripherals share a preemption level
       (non-deterministic tie-break); unless *allow_same_preempt* is True.
    4. **RT_IN_LOW_BAND** — RT peripheral placed in LOW_BAND (9..15).
    5. **NON_RT_IN_RT_BAND** — LOW-classified peripheral in RT_BAND (0..3).
    6. **BASEPRI_MISCONFIGURED** — BASEPRI is 0 (masking disabled) or outside
       valid range.

    References
    ----------
    ARM Cortex-M Generic User Guide (ARM DUI 0553B) §B3.3 — NVIC priority.
    ARM Cortex-M Generic User Guide §B1.5.4 — BASEPRI.
    RM0383 Rev 3 §10 — STM32F411 NVIC.
    RM0090 Rev 19 §10 — STM32F407 NVIC.

    Oracle examples
    ---------------
    * TIM2 at priority 1, ADC at priority 8 → ADC won't preempt TIM2 → OK.
    * Two peripherals both at priority 5 → SAME_PREEMPT_PRIORITY flagged.
    """
    if isinstance(chip, str):
        irq_spec: InterruptSpec = get_interrupt_spec(chip)
    else:
        irq_spec = chip

    pg = prigroup if prigroup is not None else irq_spec.prigroup_default
    max_prio = irq_spec.min_priority   # highest numeric value = lowest priority
    num_preempt = irq_spec.num_preempt_levels(pg)

    violations: list[PriorityViolation] = []
    notes: list[str] = []

    # ── 1. UNKNOWN_PERIPHERAL ────────────────────────────────────────────────
    for a in assignments:
        irq = irq_spec.irq_by_name(a.peripheral)
        if irq is None:
            violations.append(PriorityViolation(
                kind="UNKNOWN_PERIPHERAL",
                assignment=a,
                detail=(
                    f"Peripheral {a.peripheral!r} is not in the IRQ vector "
                    f"table for {irq_spec.chip_id} (RM0383 §10). "
                    f"Check spelling or whether this peripheral has a dedicated IRQ."
                ),
            ))

    # ── 2. OUT_OF_RANGE ──────────────────────────────────────────────────────
    for a in assignments:
        if a.priority < 0 or a.priority > max_prio:
            violations.append(PriorityViolation(
                kind="OUT_OF_RANGE",
                assignment=a,
                detail=(
                    f"Priority {a.priority} is outside the valid range "
                    f"[0, {max_prio}] for {irq_spec.chip_id} "
                    f"({irq_spec.priority_bits}-bit field, "
                    f"ARM Cortex-M Generic UG §B3.3). "
                    f"Hardware truncates NVIC_IPR to {irq_spec.priority_bits} "
                    f"bits, silently changing the effective priority."
                ),
            ))

    # ── 3. SAME_PREEMPT_PRIORITY ─────────────────────────────────────────────
    if not allow_same_preempt:
        # Group valid (in-range, known) assignments by preemption priority
        preempt_map: Dict[int, List[IRQAssignment]] = {}
        for a in assignments:
            if a.priority < 0 or a.priority > max_prio:
                continue  # already reported in OUT_OF_RANGE
            if irq_spec.irq_by_name(a.peripheral) is None:
                continue  # UNKNOWN_PERIPHERAL — skip
            pp = _preempt_priority(a.priority, irq_spec.priority_bits, pg)
            preempt_map.setdefault(pp, []).append(a)

        for pp, group in preempt_map.items():
            if len(group) > 1:
                names = [g.peripheral for g in group]
                for a in group:
                    violations.append(PriorityViolation(
                        kind="SAME_PREEMPT_PRIORITY",
                        assignment=a,
                        detail=(
                            f"Peripherals {names} all have preemption priority "
                            f"{pp} (raw priorities: "
                            f"{[g.priority for g in group]}). "
                            f"When both are pending simultaneously the Cortex-M "
                            f"hardware selects the one with the lower IRQ number — "
                            f"NOT whichever was asserted first. This creates "
                            f"non-deterministic scheduling if order matters. "
                            f"(ARM Cortex-M Generic UG §B3.3)"
                        ),
                        peers=[g.peripheral for g in group if g.peripheral != a.peripheral],
                    ))

    # ── 4. RT_IN_LOW_BAND ───────────────────────────────────────────────────
    for a in assignments:
        if a.priority < 0 or a.priority > max_prio:
            continue
        irq = irq_spec.irq_by_name(a.peripheral)
        if irq is None:
            continue
        if irq.rt_class == "RT" and a.priority in LOW_BAND:
            violations.append(PriorityViolation(
                kind="RT_IN_LOW_BAND",
                assignment=a,
                detail=(
                    f"Peripheral {a.peripheral!r} is classified as real-time "
                    f"critical (RT) but has priority {a.priority} which is in "
                    f"the LOW band ({LOW_BAND.start}..{LOW_BAND.stop - 1}). "
                    f"NORMAL-band peripherals (priority {NORMAL_BAND.start}..{NORMAL_BAND.stop - 1}) "
                    f"will pre-empt this ISR. "
                    f"Recommended RT band: 0..{RT_BAND.stop - 1}. "
                    f"(ARM Cortex-M Generic UG §B3.3 — lower number = higher priority)"
                ),
            ))

    # ── 5. NON_RT_IN_RT_BAND ────────────────────────────────────────────────
    for a in assignments:
        if a.priority < 0 or a.priority > max_prio:
            continue
        irq = irq_spec.irq_by_name(a.peripheral)
        if irq is None:
            continue
        if irq.rt_class == "LOW" and a.priority in RT_BAND:
            violations.append(PriorityViolation(
                kind="NON_RT_IN_RT_BAND",
                assignment=a,
                detail=(
                    f"Peripheral {a.peripheral!r} is classified as non-real-time "
                    f"(LOW) but has priority {a.priority} which is in the RT band "
                    f"({RT_BAND.start}..{RT_BAND.stop - 1}). "
                    f"This occupies a high-priority slot unnecessarily and may "
                    f"starve real-time ISRs (TIM, EXTI). "
                    f"Recommended LOW band: {LOW_BAND.start}..{LOW_BAND.stop - 1}."
                ),
            ))

    # ── 6. BASEPRI_MISCONFIGURED ─────────────────────────────────────────────
    if basepri_threshold is not None:
        if basepri_threshold == 0:
            # BASEPRI=0 disables masking — all interrupts fire regardless of priority
            # Synthesize a dummy assignment to hang the violation on
            _dummy = IRQAssignment(peripheral="BASEPRI", priority=0, label="")
            violations.append(PriorityViolation(
                kind="BASEPRI_MISCONFIGURED",
                assignment=_dummy,
                detail=(
                    "BASEPRI = 0 disables priority masking entirely — all IRQs "
                    "will fire regardless of their priority number. "
                    "To mask interrupts with priority >= N, set BASEPRI = N "
                    "where N is in [1, " + str(max_prio) + "]. "
                    "(ARM Cortex-M Generic UG §B1.5.4)"
                ),
            ))
        elif basepri_threshold > max_prio:
            _dummy2 = IRQAssignment(
                peripheral="BASEPRI",
                priority=basepri_threshold,
                label="",
            )
            violations.append(PriorityViolation(
                kind="BASEPRI_MISCONFIGURED",
                assignment=_dummy2,
                detail=(
                    f"BASEPRI = {basepri_threshold} exceeds the maximum priority "
                    f"value {max_prio} for {irq_spec.chip_id}. "
                    f"Hardware implements only {irq_spec.priority_bits} bits; "
                    f"values above {max_prio} are truncated. "
                    f"(ARM Cortex-M Generic UG §B1.5.4)"
                ),
            ))
        else:
            notes.append(
                f"BASEPRI = {basepri_threshold}: masks all interrupts with "
                f"priority >= {basepri_threshold} (i.e. priorities "
                f"{basepri_threshold}..{max_prio} are disabled in critical sections). "
                f"Interrupts with priority < {basepri_threshold} (0..{basepri_threshold - 1}) "
                f"will still fire."
            )

    # ── Advisory note: PRIGROUP context ──────────────────────────────────────
    notes.append(
        f"Using PRIGROUP={pg}: {num_preempt} preemption levels × "
        f"{irq_spec.num_sub_levels(pg)} sub-priority levels "
        f"({irq_spec.priority_bits}-bit field, "
        f"ARM Cortex-M Generic UG §B3.3 Table B3-2)."
    )

    return InterruptPriorityReport(
        ok=len(violations) == 0,
        violations=violations,
        chip=irq_spec.chip_id,
        checked=len(assignments),
        prigroup=pg,
        num_preempt_levels=num_preempt,
        notes=notes,
    )
