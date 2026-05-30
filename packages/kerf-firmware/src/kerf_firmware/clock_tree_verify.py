"""Clock-tree configuration verifier for STM32 microcontrollers.

Implements real clock-tree arithmetic for HSE/HSI/LSE/LSI oscillator sources,
PLL multipliers + dividers, SYSCLK, AHB/APB1/APB2 prescalers, and derived
peripheral clocks.  All constraints are sourced from:

  STM32F411 — RM0383 Rev 3 §6 "Reset and clock control (RCC)"
               Table 13 "PLL characteristics";
               DS10086 Rev 7 §5.3.2 Table 10 "General operating conditions".
  STM32F407 — RM0090 Rev 19 §6; DS8626 Rev 11 §5.3.2.

Clock-tree arithmetic (RM0383 §6.3.2)
--------------------------------------
For a PLL sourced from HSE::

    f_PLL_in   = f_HSE / PLLM          (must be 1–2 MHz)
    f_VCO      = f_PLL_in × PLLN       (must be 100–432 MHz)
    f_SYSCLK   = f_VCO / PLLP          (PLLP ∈ {2, 4, 6, 8})
    f_USB_SDIO = f_VCO / PLLQ          (must be 48 MHz for USB FS)
    f_AHB      = f_SYSCLK / HPRE
    f_APB1     = f_AHB / PPRE1
    f_APB2     = f_AHB / PPRE2

For HSI source, f_HSE is replaced by 16 MHz (nominally).

HONEST CAVEAT — LOOKUP-TABLE BASED
------------------------------------
This verifier uses embedded constraint tables from ``clock_tree_specs.py``.
It does NOT include:
  * Analytic PLL phase-noise or jitter models (no characterisation data).
  * Cycle-to-cycle jitter budgets (silicon-dependent, not in RM0383).
  * Spread-spectrum clock-dithering effects.
  * Temperature / voltage derating (VDD < 2.7 V lowers SYSCLK max on F411).

For timing-sensitive designs (USB HS, camera IF, SDIO) always verify with
STM32CubeMX RCC configurator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from kerf_firmware.clock_tree_specs import ClockTreeSpec, get_clock_spec


# ──────────────────────────────────────────────────────────────────────────────
# Public data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ClockConfig:
    """Input clock-tree configuration to verify.

    Parameters
    ----------
    source:
        Clock source: ``"HSE"``, ``"HSI"``, ``"HSE_BYPASS"``.
    hse_hz:
        External crystal/oscillator frequency in Hz.  Only used when source
        is ``"HSE"`` or ``"HSE_BYPASS"``.  Common value: 8 000 000.
    pll_m:
        PLLM divider (2–63).  Divides source clock before PLL VCO.
    pll_n:
        PLLN multiplier (2–432).  Multiplies the VCO input.
    pll_p:
        PLLP divider (2, 4, 6, or 8).  Divides VCO output to give SYSCLK.
    pll_q:
        PLLQ divider (2–15).  Divides VCO to give USB / SDIO / RNG clock.
        Set to 0 to indicate "USB not used" (skips USB frequency check).
    hpre:
        AHB prescaler (1, 2, 4, 8, 16, 64, 128, 256, 512).
    ppre1:
        APB1 prescaler (1, 2, 4, 8, 16).
    ppre2:
        APB2 prescaler (1, 2, 4, 8, 16).
    peripheral_clocks:
        Optional dict of ``{peripheral_name: frequency_hz}`` for
        additional per-peripheral clock frequency checks.
    use_pll:
        If ``False``, SYSCLK is driven directly by the source without PLL.
    """
    source: str = "HSE"
    hse_hz: int = 8_000_000
    pll_m: int = 8
    pll_n: int = 192
    pll_p: int = 4
    pll_q: int = 8
    hpre: int = 1
    ppre1: int = 4
    ppre2: int = 2
    peripheral_clocks: Dict[str, int] = field(default_factory=dict)
    use_pll: bool = True


@dataclass
class ClockViolation:
    """A single clock-tree constraint violation.

    Attributes
    ----------
    kind:
        One of: ``"VCO_OUT_OF_RANGE"``, ``"PLL_INPUT_OUT_OF_RANGE"``,
        ``"SYSCLK_EXCEEDED"``, ``"APB1_EXCEEDED"``, ``"APB2_EXCEEDED"``,
        ``"AHB_EXCEEDED"``, ``"PERIPHERAL_CLOCK_EXCEEDED"``,
        ``"PERIPHERAL_CLOCK_EXACT_MISMATCH"``, ``"HSE_OUT_OF_RANGE"``,
        ``"INVALID_PLLP"``, ``"INVALID_PRESCALER"``.
    parameter:
        The clock parameter that violated the constraint.
    actual_hz:
        The computed frequency in Hz.
    limit_hz:
        The constraining limit in Hz (max or exact).
    detail:
        Human-readable description citing the datasheet clause.
    """
    kind: str
    parameter: str
    actual_hz: int
    limit_hz: int
    detail: str


@dataclass
class PeripheralClockResult:
    """Result of a single peripheral clock check."""
    peripheral: str
    clock_hz: int
    ok: bool
    violation: Optional[ClockViolation] = None


@dataclass
class ClockTreeReport:
    """Full result of :func:`verify_clock_tree`."""
    ok: bool
    chip: str
    source_hz: int
    pll_input_hz: int
    vco_hz: int
    sysclk_hz: int
    ahb_hz: int
    apb1_hz: int
    apb2_hz: int
    usb_clk_hz: Optional[int]
    peripheral_results: List[PeripheralClockResult]
    violations: List[ClockViolation]
    caveats: List[str]

    def as_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "ok": self.ok,
            "chip": self.chip,
            "clocks": {
                "source_hz": self.source_hz,
                "pll_input_hz": self.pll_input_hz,
                "vco_hz": self.vco_hz,
                "sysclk_hz": self.sysclk_hz,
                "ahb_hz": self.ahb_hz,
                "apb1_hz": self.apb1_hz,
                "apb2_hz": self.apb2_hz,
                "usb_clk_hz": self.usb_clk_hz,
            },
            "peripheral_results": [
                {
                    "peripheral": r.peripheral,
                    "clock_hz": r.clock_hz,
                    "ok": r.ok,
                    "violation": (
                        {
                            "kind": r.violation.kind,
                            "parameter": r.violation.parameter,
                            "actual_hz": r.violation.actual_hz,
                            "limit_hz": r.violation.limit_hz,
                            "detail": r.violation.detail,
                        }
                        if r.violation else None
                    ),
                }
                for r in self.peripheral_results
            ],
            "violations": [
                {
                    "kind": v.kind,
                    "parameter": v.parameter,
                    "actual_hz": v.actual_hz,
                    "limit_hz": v.limit_hz,
                    "detail": v.detail,
                }
                for v in self.violations
            ],
            "caveats": self.caveats,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Valid prescaler sets
# ──────────────────────────────────────────────────────────────────────────────

_VALID_HPRE = {1, 2, 4, 8, 16, 64, 128, 256, 512}
_VALID_PPRE = {1, 2, 4, 8, 16}
_VALID_PLLP = {2, 4, 6, 8}


# ──────────────────────────────────────────────────────────────────────────────
# Core verifier
# ──────────────────────────────────────────────────────────────────────────────

def verify_clock_tree(
    chip: "str | ClockTreeSpec",
    config: ClockConfig,
) -> ClockTreeReport:
    """Verify an STM32 clock-tree configuration against datasheet constraints.

    Performs real clock-tree arithmetic per RM0383 §6 / RM0090 §6:

    1. Validates PLL VCO input frequency (fHSx / PLLM, must be 1–2 MHz).
    2. Computes and validates VCO output frequency (VCO_in × PLLN).
    3. Computes SYSCLK (VCO / PLLP) and checks against chip maximum.
    4. Computes AHB / APB1 / APB2 and checks their maximums.
    5. Checks USB clock (VCO / PLLQ) is exactly 48 MHz ± 500 ppm.
    6. Checks each peripheral's clock against its constraint table entry.

    Parameters
    ----------
    chip:
        Chip family string (e.g. ``"STM32F411"``), an alias, or a
        :class:`~kerf_firmware.clock_tree_specs.ClockTreeSpec`.
    config:
        :class:`ClockConfig` describing the clock-tree settings.

    Returns
    -------
    ClockTreeReport
        Fully populated report.  ``ok`` is ``True`` iff no violations.

    References
    ----------
    RM0383 Rev 3 §6.3.2 — PLL configuration register (RCC_PLLCFGR).
    RM0383 Rev 3 Table 13 — PLL characteristics.
    DS10086 Rev 7 §5.3.2 Table 10 — Maximum operating frequencies.
    """
    if isinstance(chip, str):
        spec: ClockTreeSpec = get_clock_spec(chip)
    else:
        spec = chip

    violations: List[ClockViolation] = []
    peripheral_results: List[PeripheralClockResult] = []
    caveats: List[str] = [
        "LOOKUP-TABLE ONLY: no analytic PLL phase-noise / jitter model. "
        "Cycle-to-cycle jitter is silicon-dependent; validate with "
        "STM32CubeMX for timing-sensitive interfaces (USB HS, SDIO, camera).",
        "Temperature/voltage derating not applied. "
        "At VDD < 2.7 V the STM32F411 SYSCLK max drops to 84 MHz "
        "(DS10086 §5.3.2, Table 10 note 1).",
    ]

    # ── Determine source frequency ────────────────────────────────────────────
    source_upper = config.source.upper()
    if source_upper in ("HSE", "HSE_BYPASS"):
        source_hz = config.hse_hz
        if not (spec.hse_min_hz <= source_hz <= spec.hse_max_hz):
            violations.append(ClockViolation(
                kind="HSE_OUT_OF_RANGE",
                parameter="HSE",
                actual_hz=source_hz,
                limit_hz=spec.hse_max_hz,
                detail=(
                    f"HSE frequency {source_hz:,} Hz is outside the "
                    f"allowed range {spec.hse_min_hz:,}–{spec.hse_max_hz:,} Hz "
                    f"for {spec.chip_family} (RM0383 §6.3.1, Table 13)."
                ),
            ))
    elif source_upper == "HSI":
        source_hz = spec.hsi_hz
    else:
        violations.append(ClockViolation(
            kind="INVALID_PRESCALER",
            parameter="source",
            actual_hz=0,
            limit_hz=0,
            detail=f"Unknown clock source {config.source!r}. Expected 'HSE', 'HSE_BYPASS', or 'HSI'.",
        ))
        source_hz = spec.hsi_hz

    # ── Validate prescaler values ─────────────────────────────────────────────
    if config.hpre not in _VALID_HPRE:
        violations.append(ClockViolation(
            kind="INVALID_PRESCALER",
            parameter="HPRE",
            actual_hz=config.hpre,
            limit_hz=0,
            detail=f"HPRE={config.hpre} is not valid. Valid: {sorted(_VALID_HPRE)}.",
        ))
    if config.ppre1 not in _VALID_PPRE:
        violations.append(ClockViolation(
            kind="INVALID_PRESCALER",
            parameter="PPRE1",
            actual_hz=config.ppre1,
            limit_hz=0,
            detail=f"PPRE1={config.ppre1} is not valid. Valid: {sorted(_VALID_PPRE)}.",
        ))
    if config.ppre2 not in _VALID_PPRE:
        violations.append(ClockViolation(
            kind="INVALID_PRESCALER",
            parameter="PPRE2",
            actual_hz=config.ppre2,
            limit_hz=0,
            detail=f"PPRE2={config.ppre2} is not valid. Valid: {sorted(_VALID_PPRE)}.",
        ))

    # ── Without PLL: SYSCLK = source directly ────────────────────────────────
    if not config.use_pll:
        sysclk_hz = source_hz
        pll_input_hz = 0
        vco_hz = 0
        usb_clk_hz = None
    else:
        # ── PLL arithmetic (RM0383 §6.3.2) ───────────────────────────────────
        if config.pll_p not in _VALID_PLLP:
            violations.append(ClockViolation(
                kind="INVALID_PLLP",
                parameter="PLLP",
                actual_hz=config.pll_p,
                limit_hz=0,
                detail=(
                    f"PLLP={config.pll_p} is not valid. "
                    f"PLLP must be one of {{2, 4, 6, 8}} (RM0383 §6.3.2 RCC_PLLCFGR)."
                ),
            ))

        if config.pll_m < 2 or config.pll_m > 63:
            violations.append(ClockViolation(
                kind="INVALID_PRESCALER",
                parameter="PLLM",
                actual_hz=config.pll_m,
                limit_hz=0,
                detail=f"PLLM={config.pll_m} out of range 2–63 (RM0383 §6.3.2).",
            ))

        pll_input_hz = source_hz // config.pll_m if config.pll_m > 0 else 0

        if pll_input_hz < spec.pll_input_min_hz or pll_input_hz > spec.pll_input_max_hz:
            violations.append(ClockViolation(
                kind="PLL_INPUT_OUT_OF_RANGE",
                parameter="PLL_VCO_IN",
                actual_hz=pll_input_hz,
                limit_hz=spec.pll_input_max_hz,
                detail=(
                    f"PLL VCO input frequency = {source_hz:,} / {config.pll_m} "
                    f"= {pll_input_hz:,} Hz is outside the "
                    f"{spec.pll_input_min_hz:,}–{spec.pll_input_max_hz:,} Hz range "
                    f"(RM0383 Table 13). Typical target: exactly 1 MHz or 2 MHz."
                ),
            ))

        if config.pll_n < 2 or config.pll_n > 432:
            violations.append(ClockViolation(
                kind="INVALID_PRESCALER",
                parameter="PLLN",
                actual_hz=config.pll_n,
                limit_hz=0,
                detail=f"PLLN={config.pll_n} out of range 2–432 (RM0383 §6.3.2).",
            ))

        vco_hz = pll_input_hz * config.pll_n

        if vco_hz < spec.pll_vco_min_hz or vco_hz > spec.pll_vco_max_hz:
            violations.append(ClockViolation(
                kind="VCO_OUT_OF_RANGE",
                parameter="VCO",
                actual_hz=vco_hz,
                limit_hz=spec.pll_vco_max_hz,
                detail=(
                    f"PLL VCO = {pll_input_hz:,} × {config.pll_n} "
                    f"= {vco_hz:,} Hz is outside the "
                    f"{spec.pll_vco_min_hz:,}–{spec.pll_vco_max_hz:,} Hz range "
                    f"for {spec.chip_family} (RM0383 Table 13)."
                ),
            ))

        pllp = config.pll_p if config.pll_p in _VALID_PLLP else 2
        sysclk_hz = vco_hz // pllp

        if config.pll_q and config.pll_q >= 2:
            usb_clk_hz = vco_hz // config.pll_q
        else:
            usb_clk_hz = None

    # ── SYSCLK check ──────────────────────────────────────────────────────────
    if sysclk_hz > spec.sysclk_max_hz:
        ds_ref = "DS10086" if "F411" in spec.chip_family else "DS8626"
        violations.append(ClockViolation(
            kind="SYSCLK_EXCEEDED",
            parameter="SYSCLK",
            actual_hz=sysclk_hz,
            limit_hz=spec.sysclk_max_hz,
            detail=(
                f"SYSCLK = {sysclk_hz:,} Hz exceeds the {spec.chip_family} maximum "
                f"of {spec.sysclk_max_hz:,} Hz "
                f"({ds_ref} §5.3.2 Table 10). Reduce PLLP or PLLN."
            ),
        ))

    # ── AHB / APB bus clocks ──────────────────────────────────────────────────
    hpre = config.hpre if config.hpre in _VALID_HPRE else 1
    ppre1 = config.ppre1 if config.ppre1 in _VALID_PPRE else 1
    ppre2 = config.ppre2 if config.ppre2 in _VALID_PPRE else 1

    ahb_hz = sysclk_hz // hpre
    apb1_hz = ahb_hz // ppre1
    apb2_hz = ahb_hz // ppre2

    if ahb_hz > spec.ahb_max_hz:
        violations.append(ClockViolation(
            kind="AHB_EXCEEDED",
            parameter="AHB",
            actual_hz=ahb_hz,
            limit_hz=spec.ahb_max_hz,
            detail=(
                f"AHB clock = {ahb_hz:,} Hz exceeds {spec.chip_family} max "
                f"{spec.ahb_max_hz:,} Hz (RM0383 §6.2). Increase HPRE."
            ),
        ))

    if apb1_hz > spec.apb1_max_hz:
        violations.append(ClockViolation(
            kind="APB1_EXCEEDED",
            parameter="APB1",
            actual_hz=apb1_hz,
            limit_hz=spec.apb1_max_hz,
            detail=(
                f"APB1 clock = {apb1_hz:,} Hz exceeds {spec.chip_family} max "
                f"{spec.apb1_max_hz:,} Hz (RM0383 §6.2 note 1). Increase PPRE1."
            ),
        ))

    if apb2_hz > spec.apb2_max_hz:
        violations.append(ClockViolation(
            kind="APB2_EXCEEDED",
            parameter="APB2",
            actual_hz=apb2_hz,
            limit_hz=spec.apb2_max_hz,
            detail=(
                f"APB2 clock = {apb2_hz:,} Hz exceeds {spec.chip_family} max "
                f"{spec.apb2_max_hz:,} Hz (RM0383 §6.2 note 1). Increase PPRE2."
            ),
        ))

    # ── USB clock check ───────────────────────────────────────────────────────
    if usb_clk_hz is not None and "USB_OTG_FS" in spec.peripheral_constraints:
        usb_constraint = spec.peripheral_constraints["USB_OTG_FS"]
        usb_ok, usb_viol = _check_peripheral_freq("USB_OTG_FS", usb_clk_hz, usb_constraint)
        peripheral_results.append(PeripheralClockResult(
            peripheral="USB_OTG_FS",
            clock_hz=usb_clk_hz,
            ok=usb_ok,
            violation=usb_viol,
        ))
        if not usb_ok and usb_viol:
            violations.append(usb_viol)

    # ── Per-peripheral clock checks ───────────────────────────────────────────
    # Only clocks that flow directly (without additional prescalers) are
    # auto-derived.  ADC and SPI clocks require hardware prescalers that are
    # not in the RCC PLL config; they are ONLY checked when the caller
    # supplies explicit values in config.peripheral_clocks.
    # I2C and SDIO are checked against the bus clock directly.
    derived: Dict[str, int] = {}
    if apb1_hz:
        derived["I2C1"] = apb1_hz
        derived["TIM_APB1"] = apb1_hz * (2 if ppre1 > 1 else 1)
    if apb2_hz:
        derived["TIM_APB2"] = apb2_hz * (2 if ppre2 > 1 else 1)
    if usb_clk_hz is not None:
        derived["SDIO"] = usb_clk_hz

    # Caller-supplied values override/add derived clocks.
    # ADC, SPI etc. are only checked when the caller provides them.
    derived.update(config.peripheral_clocks)

    for pname, pfreq in derived.items():
        if pname == "USB_OTG_FS":
            continue
        constraint = spec.peripheral_constraints.get(pname)
        if constraint is None:
            continue
        ok, viol = _check_peripheral_freq(pname, pfreq, constraint)
        peripheral_results.append(PeripheralClockResult(
            peripheral=pname,
            clock_hz=pfreq,
            ok=ok,
            violation=viol,
        ))
        if not ok and viol:
            violations.append(viol)

    return ClockTreeReport(
        ok=len(violations) == 0,
        chip=spec.chip_family,
        source_hz=source_hz,
        pll_input_hz=pll_input_hz,
        vco_hz=vco_hz,
        sysclk_hz=sysclk_hz,
        ahb_hz=ahb_hz,
        apb1_hz=apb1_hz,
        apb2_hz=apb2_hz,
        usb_clk_hz=usb_clk_hz,
        peripheral_results=peripheral_results,
        violations=violations,
        caveats=caveats,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _check_peripheral_freq(
    name: str,
    freq_hz: int,
    constraint: Any,
) -> "tuple[bool, Optional[ClockViolation]]":
    """Return (ok, violation_or_None) for a single peripheral clock check."""
    if constraint.exact_hz is not None:
        delta_ppm = abs(freq_hz - constraint.exact_hz) * 1_000_000 / constraint.exact_hz
        if delta_ppm > constraint.tolerance_ppm:
            return False, ClockViolation(
                kind="PERIPHERAL_CLOCK_EXACT_MISMATCH",
                parameter=name,
                actual_hz=freq_hz,
                limit_hz=constraint.exact_hz,
                detail=(
                    f"{name} requires exactly {constraint.exact_hz:,} Hz "
                    f"(±{constraint.tolerance_ppm} ppm) but got {freq_hz:,} Hz "
                    f"(delta = {delta_ppm:.1f} ppm). {constraint.note}"
                ),
            )
    else:
        if freq_hz > constraint.max_hz:
            return False, ClockViolation(
                kind="PERIPHERAL_CLOCK_EXCEEDED",
                parameter=name,
                actual_hz=freq_hz,
                limit_hz=constraint.max_hz,
                detail=(
                    f"{name} clock = {freq_hz:,} Hz exceeds maximum "
                    f"{constraint.max_hz:,} Hz. {constraint.note}"
                ),
            )
        if constraint.min_hz > 0 and freq_hz < constraint.min_hz:
            return False, ClockViolation(
                kind="PERIPHERAL_CLOCK_EXCEEDED",
                parameter=name,
                actual_hz=freq_hz,
                limit_hz=constraint.min_hz,
                detail=(
                    f"{name} clock = {freq_hz:,} Hz is below minimum "
                    f"{constraint.min_hz:,} Hz. {constraint.note}"
                ),
            )

    return True, None
