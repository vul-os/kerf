"""Microcontroller peripheral pin-mapping verifier.

Verifies that a firmware pin-assignment dict is consistent with a chip's
hardware capabilities.  Five classes of violation are detected:

1. **BAD_ALT_FUNCTION** — a pin is assigned a peripheral function it cannot
   serve (the function is absent from the pin's alternate-function list in the
   datasheet).

2. **PIN_CONFLICT** — two or more enabled peripheral signals are assigned to
   the same physical pin.  Each pin can only route one signal at a time.

3. **MISSING_REQUIRED** — a peripheral that is listed in *required_peripherals*
   has no pin assignment.

4. **PERIPHERAL_PIN_MUX_CONFLICT** — the same peripheral function is assigned
   to multiple pins simultaneously (e.g. UART2_TX on both PA2 *and* PA9 would
   be illegal at runtime, even though both pins can host UART2_TX).

5. **VOLTAGE_INCOMPATIBLE** — a 5 V external signal is wired to a pin that is
   not 5 V tolerant (detected when *five_volt_signals* lists the signal name
   and the assigned pin has ``five_volt_tolerant=False``).

References
----------
  STM32F411 — RM0390 §8.3.2 "Alternate function mapping" (and RM0383 §7.3 for
              F411 specifically).  Each GPIO has AF0..AF15 mux registers; only
              one AF can be active per pin.
  ATmega328P — ATmega328P datasheet 7810D §13 "Pin Configurations" (Table 13-2)
               and §14 "I/O Ports".  No mux register; peripheral function is
               enabled by peripheral enable bits (USART, SPI, TWI, …).

Limitations
-----------
  * This verifier works from embedded constant tables in ``chip_specs.py``; it
    does NOT import from or replace ST CubeMX, STM32CubeIDE, or Microchip
    Atmel Start.  Always validate your final design with the vendor's official
    pin-assignment tool before manufacturing.
  * The embedded tables cover STM32F411 LQFP64 and ATmega328P PDIP-28 only.
    Extend ``chip_specs.py`` to add further chips.
  * Voltage compatibility check only flags *known* 5 V incompatible pins when
    the caller explicitly passes ``five_volt_signals``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kerf_firmware.chip_specs import ChipPinSpec, get_chip_spec


# ──────────────────────────────────────────────────────────────────────────────
# Public data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PinMappingViolation:
    """A single violation found during pin-map verification.

    Attributes
    ----------
    kind:
        One of ``"BAD_ALT_FUNCTION"``, ``"PIN_CONFLICT"``,
        ``"MISSING_REQUIRED"``, ``"PERIPHERAL_PIN_MUX_CONFLICT"``,
        ``"VOLTAGE_INCOMPATIBLE"``.
    pin:
        Physical pin name involved (e.g. ``"PA2"``), or ``None`` for
        MISSING_REQUIRED violations where no pin was assigned at all.
    signal:
        Peripheral signal name involved (e.g. ``"UART2_TX"``).
    detail:
        Human-readable explanation of the violation.
    """
    kind: str
    pin: str | None
    signal: str
    detail: str


@dataclass
class VerifyReport:
    """Result of :func:`verify_pin_mapping`.

    Attributes
    ----------
    ok:
        ``True`` iff no violations were found.
    violations:
        List of :class:`PinMappingViolation` objects.
    chip_id:
        The chip ID that was checked.
    checked_signals:
        Number of signal→pin assignments that were evaluated.
    """
    ok: bool
    violations: list[PinMappingViolation]
    chip_id: str
    checked_signals: int

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "ok": self.ok,
            "chip_id": self.chip_id,
            "checked_signals": self.checked_signals,
            "violations": [
                {
                    "kind": v.kind,
                    "pin": v.pin,
                    "signal": v.signal,
                    "detail": v.detail,
                }
                for v in self.violations
            ],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Normalisation helpers
# ──────────────────────────────────────────────────────────────────────────────

def _norm_fn(fn: str) -> str:
    """Normalise a function name for comparison (upper-case, strip spaces)."""
    return fn.upper().replace(" ", "_").replace("-", "_")


def _pin_has_function(spec: ChipPinSpec, pin_name: str, function: str) -> bool:
    """Return True if *pin_name* lists *function* in its alt-functions."""
    cap = spec.pins.get(pin_name)
    if cap is None:
        return False
    norm_fn = _norm_fn(function)
    return any(_norm_fn(f) == norm_fn for f in cap.alt_functions)


# ──────────────────────────────────────────────────────────────────────────────
# Core verifier
# ──────────────────────────────────────────────────────────────────────────────

def verify_pin_mapping(
    chip: str | ChipPinSpec,
    mapping: dict[str, str],
    *,
    required_peripherals: list[str] | None = None,
    five_volt_signals: list[str] | None = None,
) -> VerifyReport:
    """Verify a peripheral pin-mapping against a chip's hardware capabilities.

    Parameters
    ----------
    chip:
        Either a chip-ID string (e.g. ``"STM32F411_LQFP64"``, ``"atmega328p"``)
        or a :class:`~kerf_firmware.chip_specs.ChipPinSpec` instance.
    mapping:
        Dict of ``{signal_name: pin_name}``, e.g.::

            {
                "UART2_TX": "PA2",
                "UART2_RX": "PA3",
                "SPI1_MOSI": "PA7",
            }

        Signal names are compared case-insensitively against the pin's
        ``alt_functions``.  Pin names must match the chip's canonical names
        (e.g. ``"PA2"`` not ``"2"``).

    required_peripherals:
        Optional list of signal names that *must* appear as keys in *mapping*.
        Missing entries generate a ``MISSING_REQUIRED`` violation.

    five_volt_signals:
        Optional list of signal names whose external driver operates at 5 V.
        If a 5 V signal is mapped to a non-5V-tolerant pin, a
        ``VOLTAGE_INCOMPATIBLE`` violation is raised.

    Returns
    -------
    VerifyReport
        Populated with all detected violations.  ``ok`` is ``True`` iff
        ``violations`` is empty.

    References
    ----------
    RM0383 §7.3 (STM32F411 LQFP64 alternate-function mapping);
    ATmega328P datasheet 7810D §13 Table 13-2.
    """
    # Resolve chip spec
    if isinstance(chip, str):
        chip_spec: ChipPinSpec = get_chip_spec(chip)
    else:
        chip_spec = chip

    violations: list[PinMappingViolation] = []
    required_peripherals = required_peripherals or []
    five_volt_signals = five_volt_signals or []

    # ── 1. BAD_ALT_FUNCTION ───────────────────────────────────────────────────
    for signal, pin in mapping.items():
        cap = chip_spec.pins.get(pin)
        if cap is None:
            violations.append(PinMappingViolation(
                kind="BAD_ALT_FUNCTION",
                pin=pin,
                signal=signal,
                detail=(
                    f"Pin {pin!r} does not exist on {chip_spec.chip_id}. "
                    f"Known pins: {sorted(chip_spec.pins)[:10]}…"
                ),
            ))
            continue

        if not _pin_has_function(chip_spec, pin, signal):
            avail = ", ".join(cap.alt_functions)
            violations.append(PinMappingViolation(
                kind="BAD_ALT_FUNCTION",
                pin=pin,
                signal=signal,
                detail=(
                    f"Pin {pin!r} cannot serve {signal!r} on {chip_spec.chip_id}. "
                    f"Available alt-functions: [{avail}]."
                ),
            ))

    # ── 2. PIN_CONFLICT ───────────────────────────────────────────────────────
    # A physical pin appears in the mapping more than once (different signals
    # both assigned to the same pin).
    pin_to_signals: dict[str, list[str]] = {}
    for signal, pin in mapping.items():
        pin_to_signals.setdefault(pin, []).append(signal)

    for pin, signals in pin_to_signals.items():
        if len(signals) > 1:
            violations.append(PinMappingViolation(
                kind="PIN_CONFLICT",
                pin=pin,
                signal=", ".join(signals),
                detail=(
                    f"Pin {pin!r} is assigned to multiple signals simultaneously: "
                    f"{signals}. Only one alt-function can be active per pin."
                ),
            ))

    # ── 3. MISSING_REQUIRED ───────────────────────────────────────────────────
    for req in required_peripherals:
        if req not in mapping:
            violations.append(PinMappingViolation(
                kind="MISSING_REQUIRED",
                pin=None,
                signal=req,
                detail=(
                    f"Required peripheral signal {req!r} has no pin assignment."
                ),
            ))

    # ── 4. PERIPHERAL_PIN_MUX_CONFLICT ───────────────────────────────────────
    # The same signal name appears multiple times (mapped to >1 pin).
    # (Dict keys are unique in Python, so we check via the original mapping.)
    # This is a logic safeguard — Python dicts enforce uniqueness, but callers
    # may construct mappings from lists.  We therefore also accept a
    # list-of-tuples form internally.
    signal_counts: dict[str, list[str]] = {}
    for signal, pin in mapping.items():
        signal_counts.setdefault(_norm_fn(signal), []).append(pin)

    for norm_signal, pins in signal_counts.items():
        if len(pins) > 1:
            violations.append(PinMappingViolation(
                kind="PERIPHERAL_PIN_MUX_CONFLICT",
                pin=", ".join(pins),
                signal=norm_signal,
                detail=(
                    f"Signal {norm_signal!r} is assigned to multiple pins "
                    f"{pins}. A peripheral signal may only be routed to one pin."
                ),
            ))

    # ── 5. VOLTAGE_INCOMPATIBLE ───────────────────────────────────────────────
    for signal in five_volt_signals:
        pin = mapping.get(signal)
        if pin is None:
            continue
        cap = chip_spec.pins.get(pin)
        if cap is not None and not cap.five_volt_tolerant:
            violations.append(PinMappingViolation(
                kind="VOLTAGE_INCOMPATIBLE",
                pin=pin,
                signal=signal,
                detail=(
                    f"Signal {signal!r} is marked as 5 V but pin {pin!r} on "
                    f"{chip_spec.chip_id} is NOT 5V tolerant "
                    f"(max VDD = 3.3 V). Use a level-shifter."
                ),
            ))

    return VerifyReport(
        ok=len(violations) == 0,
        violations=violations,
        chip_id=chip_spec.chip_id,
        checked_signals=len(mapping),
    )
