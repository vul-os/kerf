"""
EMC pre-compliance wizard — guided, end-to-end actionable workflow.

Takes a board/cable/enclosure design description, runs the existing
kerf_electronics.emc.estimate physics functions (DM loop, CM cable,
crosstalk, shielding effectiveness), compares results against a chosen
regulatory standard, and produces a prioritised findings + fix-
recommendation report with quantified before/after margins.

Pre-scan checklist
------------------
Clock harmonics up to the 10th harmonic are evaluated.
Cable resonances (λ/2 and λ/4) are flagged at the worst harmonic.
Aperture leakage is checked if an enclosure aperture is supplied.

Mitigation logic
----------------
1. DM loop: recommend reducing loop area (target half-area) and re-run
   to predict the improvement.
2. CM cable: recommend a common-mode choke (adds ~20 dB CM attenuation)
   and re-run to show predicted improvement.
3. Enclosure shield: recommend adding / upgrading shielding such that
   SE >= margin deficit; report the required SE_effective and whether
   the current configuration meets it.
4. Crosstalk: recommend increasing trace spacing (target 3× current
   spacing) and show improvement.

Contract
--------
• Never raises to callers — all errors are {"ok": False, "reason": ...}.
• @register tools mirror the emc/tools.py pattern (write=False).
• TOOLS list exported for plugin._register_tools.

Author: imranparuk
"""
from __future__ import annotations

import json
import math
import warnings
from typing import Any, Dict, List, Optional

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register
from kerf_electronics.emc.estimate import (
    emission_margin_db,
    near_field_crosstalk,
    radiated_emission_common_mode,
    radiated_emission_differential,
    shielding_effectiveness,
)

# ── Constants ──────────────────────────────────────────────────────────────────

_C = 2.998e8          # speed of light [m/s]
_DEFAULT_DISTANCE_M = 10.0

# Choke insertion-loss model: a ferrite common-mode choke at its target
# frequency typically provides 20–40 dB of CM attenuation.  We use a
# conservative 20 dB as the predicted improvement from adding a choke.
_CHOKE_CM_ATTENUATION_DB = 20.0

# DM loop-area reduction target: halving the loop area reduces f²·A emission
# by 6.02 dB (factor of 2 in E-field via A).
_LOOP_AREA_REDUCTION_FACTOR = 0.5  # target: 50 % of original area

# Trace-spacing improvement factor for crosstalk recommendation.
_SPACING_IMPROVEMENT_FACTOR = 3.0


# ── Internal helpers ───────────────────────────────────────────────────────────


def _validate_positive(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value) or value <= 0:
        return f"{name} must be a positive number, got {value!r}"
    return None


def _validate_nonneg(value, name: str) -> Optional[str]:
    if not isinstance(value, (int, float)) or math.isnan(value) or value < 0:
        return f"{name} must be >= 0, got {value!r}"
    return None


def _normalize_standard(standard: str) -> Optional[str]:
    s = str(standard).lower().strip()
    if s in ("fcc", "fcc_part15", "fcc part 15"):
        return "fcc"
    if s in ("cispr", "cispr32", "cispr_32", "cispr 32", "cispr22", "cispr_22"):
        return "cispr"
    return None


def _normalize_class(cls: str) -> Optional[str]:
    c = str(cls).upper().strip()
    if c in ("A",):
        return "A"
    if c in ("B",):
        return "B"
    return None


def _margin(emission_dbuvm: float, freq_hz: float, standard: str,
            class_: str, distance_m: float) -> dict:
    """Thin wrapper — suppresses warnings from the underlying call."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return emission_margin_db(
            e_field_dbuvm=emission_dbuvm,
            freq_hz=freq_hz,
            standard=standard,
            class_=class_,
            distance_m=distance_m,
        )


def _dm_emission(freq_hz: float, loop_area_m2: float, current_a: float,
                 distance_m: float) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return radiated_emission_differential(
            freq_hz=freq_hz,
            loop_area_m2=loop_area_m2,
            current_a=current_a,
            distance_m=distance_m,
        )


def _cm_emission(freq_hz: float, cable_length_m: float, current_a: float,
                 distance_m: float) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return radiated_emission_common_mode(
            freq_hz=freq_hz,
            cable_length_m=cable_length_m,
            current_a=current_a,
            distance_m=distance_m,
        )


def _se(freq_hz: float, thickness_m: float, sigma_r: float, mu_r: float,
        aperture_m: float) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return shielding_effectiveness(
            freq_hz=freq_hz,
            thickness_m=thickness_m,
            conductivity_relative=sigma_r,
            permeability_relative=mu_r,
            aperture_length_m=aperture_m,
        )


# ── Pre-scan checklist ─────────────────────────────────────────────────────────


def _clock_harmonics(clock_hz: float, n_harmonics: int = 10) -> List[float]:
    """Return the first n odd + even harmonics of clock_hz up to 1 GHz."""
    harmonics = []
    for n in range(1, n_harmonics + 1):
        f = n * clock_hz
        if f <= 1e9:
            harmonics.append(f)
    return harmonics


def _cable_resonance_freqs(cable_length_m: float) -> List[float]:
    """λ/2 and λ/4 resonance frequencies for a cable of the given length."""
    f_half = _C / (2.0 * cable_length_m)   # λ/2 resonance
    f_quarter = _C / (4.0 * cable_length_m) # λ/4 resonance
    return [f for f in (f_quarter, f_half) if f <= 1e9]


# ── Core wizard function ───────────────────────────────────────────────────────


def emc_precompliance(design: dict) -> dict:
    """
    EMC pre-compliance wizard.

    Runs the full EMC pre-compliance flow for a board/cable/enclosure
    description, compares against the chosen standard, and returns a
    prioritised findings + fix-recommendation report.

    Parameters (design dict keys)
    -----------------------------
    Required:
        clock_hz          : float  — fundamental clock frequency [Hz]
        loop_area_m2      : float  — PCB differential-mode loop area [m²]
        loop_current_a    : float  — DM loop current [A]

    Optional — cable (CM emission):
        cable_length_m    : float  — cable length [m] (omit → no CM analysis)
        cm_current_a      : float  — common-mode cable current [A] (default 1e-6 A)

    Optional — enclosure shielding:
        shield_thickness_m         : float — wall thickness [m] (omit → no SE analysis)
        shield_conductivity_rel    : float — relative conductivity (default 1.0 copper)
        shield_permeability_rel    : float — relative permeability (default 1.0)
        shield_aperture_length_m   : float — largest aperture [m] (default 0)

    Optional — crosstalk:
        trace_width_mm      : float — PCB trace width [mm]
        trace_spacing_mm    : float — edge-to-edge trace spacing [mm]
        trace_height_mm     : float — trace height above ground [mm]
        parallel_length_mm  : float — parallel run length [mm]

    Optional — standard / measurement:
        standard          : str   — 'fcc' or 'cispr' (default 'cispr')
        class_            : str   — 'A' or 'B' (default 'B')
        distance_m        : float — measurement distance [m] (default 10.0)
        n_harmonics       : int   — number of harmonics to scan (default 10)

    Returns
    -------
    dict with keys:
        ok              : bool
        compliant       : bool  — True if all analysed channels pass
        worst_freq_hz   : float — frequency with the worst (lowest) margin
        worst_margin_db : float — margin at worst frequency (negative = fail)
        findings        : list  — per-channel finding dicts
        recommendations : list  — prioritised fix dicts (highest leverage first)
        checklist       : dict  — pre-scan checklist results
        reason          : str   — only present when ok=False
    """
    # ── Input validation ────────────────────────────────────────────────────
    if not isinstance(design, dict):
        return {"ok": False, "reason": "design must be a dict"}

    err = _validate_positive(design.get("clock_hz"), "clock_hz")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(design.get("loop_area_m2"), "loop_area_m2")
    if err:
        return {"ok": False, "reason": err}
    err = _validate_positive(design.get("loop_current_a"), "loop_current_a")
    if err:
        return {"ok": False, "reason": err}

    clock_hz = float(design["clock_hz"])
    loop_area_m2 = float(design["loop_area_m2"])
    loop_current_a = float(design["loop_current_a"])

    # Standard / class
    raw_std = design.get("standard", "cispr")
    standard = _normalize_standard(raw_std)
    if standard is None:
        return {"ok": False, "reason": f"standard must be 'fcc' or 'cispr', got {raw_std!r}"}

    raw_cls = design.get("class_", "B")
    class_ = _normalize_class(raw_cls)
    if class_ is None:
        return {"ok": False, "reason": f"class_ must be 'A' or 'B', got {raw_cls!r}"}

    distance_m = float(design.get("distance_m", _DEFAULT_DISTANCE_M))
    err = _validate_positive(distance_m, "distance_m")
    if err:
        return {"ok": False, "reason": err}

    n_harmonics = int(design.get("n_harmonics", 10))

    # Optional cable
    cable_length_m = design.get("cable_length_m")
    cm_current_a = design.get("cm_current_a", 1e-6)
    has_cable = cable_length_m is not None
    if has_cable:
        err = _validate_positive(cable_length_m, "cable_length_m")
        if err:
            return {"ok": False, "reason": err}
        err = _validate_positive(cm_current_a, "cm_current_a")
        if err:
            return {"ok": False, "reason": err}
        cable_length_m = float(cable_length_m)
        cm_current_a = float(cm_current_a)

    # Optional enclosure
    shield_thickness_m = design.get("shield_thickness_m")
    has_shield = shield_thickness_m is not None
    if has_shield:
        err = _validate_positive(shield_thickness_m, "shield_thickness_m")
        if err:
            return {"ok": False, "reason": err}
        shield_thickness_m = float(shield_thickness_m)
        shield_sigma_r = float(design.get("shield_conductivity_rel", 1.0))
        shield_mu_r = float(design.get("shield_permeability_rel", 1.0))
        shield_aperture_m = float(design.get("shield_aperture_length_m", 0.0))
    else:
        shield_sigma_r = shield_mu_r = shield_aperture_m = None

    # Optional crosstalk
    trace_width_mm = design.get("trace_width_mm")
    trace_spacing_mm = design.get("trace_spacing_mm")
    trace_height_mm = design.get("trace_height_mm")
    parallel_length_mm = design.get("parallel_length_mm")
    has_crosstalk = all(
        v is not None
        for v in (trace_width_mm, trace_spacing_mm, trace_height_mm, parallel_length_mm)
    )
    if has_crosstalk:
        for name, val in (
            ("trace_width_mm", trace_width_mm),
            ("trace_spacing_mm", trace_spacing_mm),
            ("trace_height_mm", trace_height_mm),
            ("parallel_length_mm", parallel_length_mm),
        ):
            err = _validate_positive(val, name)
            if err:
                return {"ok": False, "reason": err}
        trace_width_mm = float(trace_width_mm)
        trace_spacing_mm = float(trace_spacing_mm)
        trace_height_mm = float(trace_height_mm)
        parallel_length_mm = float(parallel_length_mm)

    # ── Pre-scan checklist ───────────────────────────────────────────────────
    harmonics = _clock_harmonics(clock_hz, n_harmonics)
    cable_resonances: List[float] = []
    if has_cable:
        cable_resonances = _cable_resonance_freqs(cable_length_m)

    checklist: Dict[str, Any] = {
        "clock_hz": clock_hz,
        "harmonics_evaluated": harmonics,
        "cable_resonances_hz": cable_resonances if has_cable else None,
        "aperture_present": has_shield and shield_aperture_m > 0,
    }

    # ── Run DM emission across harmonics ─────────────────────────────────────
    findings: List[dict] = []
    all_margins: List[float] = []

    for h_idx, freq in enumerate(harmonics, start=1):
        dm_res = _dm_emission(freq, loop_area_m2, loop_current_a, distance_m)
        if not dm_res["ok"]:
            continue
        margin_res = _margin(dm_res["e_field_dbuvm"], freq, standard, class_, distance_m)
        if not margin_res["ok"]:
            continue
        finding = {
            "channel": "DM_loop",
            "harmonic": h_idx,
            "freq_hz": freq,
            "emission_dbuvm": dm_res["e_field_dbuvm"],
            "limit_dbuvm": margin_res["limit_dbuvm"],
            "margin_db": margin_res["margin_db"],
            "passes": margin_res["passes"],
        }
        findings.append(finding)
        all_margins.append(margin_res["margin_db"])

    # ── Run CM emission across harmonics ─────────────────────────────────────
    if has_cable:
        for h_idx, freq in enumerate(harmonics, start=1):
            cm_res = _cm_emission(freq, cable_length_m, cm_current_a, distance_m)
            if not cm_res["ok"]:
                continue
            margin_res = _margin(cm_res["e_field_dbuvm"], freq, standard, class_, distance_m)
            if not margin_res["ok"]:
                continue
            finding = {
                "channel": "CM_cable",
                "harmonic": h_idx,
                "freq_hz": freq,
                "emission_dbuvm": cm_res["e_field_dbuvm"],
                "limit_dbuvm": margin_res["limit_dbuvm"],
                "margin_db": margin_res["margin_db"],
                "passes": margin_res["passes"],
            }
            findings.append(finding)
            all_margins.append(margin_res["margin_db"])

    if not findings:
        return {
            "ok": False,
            "reason": "No valid findings produced — check inputs cover 30 MHz–1 GHz",
        }

    # ── Identify worst finding ────────────────────────────────────────────────
    worst_idx = int(min(range(len(findings)), key=lambda i: findings[i]["margin_db"]))
    worst = findings[worst_idx]
    worst_margin_db = worst["margin_db"]
    worst_freq_hz = worst["freq_hz"]
    compliant = all(f["passes"] for f in findings)

    # ── Build recommendations ─────────────────────────────────────────────────
    recommendations: List[dict] = []

    # --- DM loop-area reduction ---
    dm_worst = min(
        (f for f in findings if f["channel"] == "DM_loop"),
        key=lambda f: f["margin_db"],
        default=None,
    )
    if dm_worst is not None and dm_worst["margin_db"] < 0:
        reduced_area = loop_area_m2 * _LOOP_AREA_REDUCTION_FACTOR
        dm_after = _dm_emission(dm_worst["freq_hz"], reduced_area, loop_current_a, distance_m)
        if dm_after["ok"]:
            margin_after = _margin(
                dm_after["e_field_dbuvm"], dm_worst["freq_hz"], standard, class_, distance_m
            )
            improvement_db = (
                margin_after["margin_db"] - dm_worst["margin_db"]
                if margin_after["ok"] else None
            )
            predicted_margin = margin_after["margin_db"] if margin_after["ok"] else None
            recommendations.append({
                "priority": 1,
                "channel": "DM_loop",
                "action": "shorten_loop",
                "description": (
                    f"Reduce PCB loop area by 50 % "
                    f"(target {reduced_area * 1e6:.1f} mm² from "
                    f"{loop_area_m2 * 1e6:.1f} mm²). "
                    "Route the return current trace adjacent to the signal trace "
                    "or use a ground plane directly below."
                ),
                "target_loop_area_m2": reduced_area,
                "before_margin_db": round(dm_worst["margin_db"], 2),
                "predicted_margin_db": round(predicted_margin, 2) if predicted_margin is not None else None,
                "improvement_db": round(improvement_db, 2) if improvement_db is not None else None,
                "freq_hz": dm_worst["freq_hz"],
            })

    # --- CM choke recommendation ---
    cm_worst = min(
        (f for f in findings if f["channel"] == "CM_cable"),
        key=lambda f: f["margin_db"],
        default=None,
    )
    if cm_worst is not None and cm_worst["margin_db"] < 0:
        deficit_db = abs(cm_worst["margin_db"])
        # A choke reduces common-mode current by 20 dB (factor of 10 in current)
        choke_attenuation_factor = 10.0 ** (-_CHOKE_CM_ATTENUATION_DB / 20.0)
        cm_after_current = cm_current_a * choke_attenuation_factor
        cm_after = _cm_emission(cm_worst["freq_hz"], cable_length_m, cm_after_current, distance_m)
        margin_after_cm = None
        predicted_margin_cm = None
        improvement_cm_db = None
        if cm_after["ok"]:
            mr = _margin(cm_after["e_field_dbuvm"], cm_worst["freq_hz"], standard, class_, distance_m)
            if mr["ok"]:
                predicted_margin_cm = mr["margin_db"]
                improvement_cm_db = mr["margin_db"] - cm_worst["margin_db"]

        # Recommend choke impedance: minimum 5× deficit, in Ohms at worst freq
        # Rule of thumb: Z_choke ≥ 100 Ω for a 20 dB improvement at target freq
        choke_impedance_ohm = max(100.0, 10.0 ** (deficit_db / 20.0) * 50.0)
        recommendations.append({
            "priority": 2,
            "channel": "CM_cable",
            "action": "add_common_mode_choke",
            "description": (
                f"Add a common-mode choke on the cable at the PCB connector. "
                f"Target impedance ≥ {choke_impedance_ohm:.0f} Ω at "
                f"{cm_worst['freq_hz'] / 1e6:.1f} MHz. "
                f"A ferrite bead or wound choke with {_CHOKE_CM_ATTENUATION_DB:.0f} dB "
                "CM attenuation is recommended."
            ),
            "choke_impedance_min_ohm": round(choke_impedance_ohm, 1),
            "before_margin_db": round(cm_worst["margin_db"], 2),
            "predicted_margin_db": round(predicted_margin_cm, 2) if predicted_margin_cm is not None else None,
            "improvement_db": round(improvement_cm_db, 2) if improvement_cm_db is not None else None,
            "freq_hz": cm_worst["freq_hz"],
        })

    # --- Shield SE recommendation ---
    if has_shield:
        # Compute current SE at worst frequency
        se_res = _se(worst_freq_hz, shield_thickness_m, shield_sigma_r, shield_mu_r, shield_aperture_m)
        if se_res["ok"]:
            se_eff = se_res["se_effective_db"]
            if worst_margin_db < 0:
                required_se = se_eff + abs(worst_margin_db) + 3.0  # 3 dB guard
                recommendations.append({
                    "priority": 3,
                    "channel": "shielding",
                    "action": "add_shield",
                    "description": (
                        f"Current enclosure SE_effective = {se_eff:.1f} dB at "
                        f"{worst_freq_hz / 1e6:.1f} MHz. "
                        f"Required SE ≥ {required_se:.1f} dB to achieve 3 dB margin. "
                        "Consider thicker aluminium, reducing aperture slot length, "
                        "or adding EMI gaskets."
                    ),
                    "current_se_effective_db": round(se_eff, 2),
                    "required_se_db": round(required_se, 2),
                    "freq_hz": worst_freq_hz,
                    "aperture_limited": se_res["aperture_limited"],
                })

    # --- Crosstalk trace-spacing recommendation ---
    if has_crosstalk:
        xt_before = near_field_crosstalk(
            freq_hz=clock_hz,
            trace_width_mm=trace_width_mm,
            trace_spacing_mm=trace_spacing_mm,
            trace_height_mm=trace_height_mm,
            parallel_length_mm=parallel_length_mm,
        )
        improved_spacing = trace_spacing_mm * _SPACING_IMPROVEMENT_FACTOR
        xt_after = near_field_crosstalk(
            freq_hz=clock_hz,
            trace_width_mm=trace_width_mm,
            trace_spacing_mm=improved_spacing,
            trace_height_mm=trace_height_mm,
            parallel_length_mm=parallel_length_mm,
        )
        if xt_before["ok"] and xt_after["ok"]:
            recommendations.append({
                "priority": 4,
                "channel": "crosstalk",
                "action": "increase_trace_spacing",
                "description": (
                    f"Increase trace edge-to-edge spacing from "
                    f"{trace_spacing_mm:.2f} mm to "
                    f"{improved_spacing:.2f} mm (3× current). "
                    "This reduces K_effective from "
                    f"{xt_before['K_effective']:.4f} to "
                    f"{xt_after['K_effective']:.4f}."
                ),
                "before_K_effective": xt_before["K_effective"],
                "after_K_effective": xt_after["K_effective"],
                "target_spacing_mm": round(improved_spacing, 3),
            })

    # Sort recommendations by priority
    recommendations.sort(key=lambda r: r["priority"])

    # ── Final result ──────────────────────────────────────────────────────────
    result: dict = {
        "ok": True,
        "compliant": compliant,
        "standard": standard.upper(),
        "class_": class_,
        "distance_m": distance_m,
        "worst_freq_hz": worst_freq_hz,
        "worst_margin_db": round(worst_margin_db, 2),
        "findings": findings,
        "recommendations": recommendations,
        "checklist": checklist,
    }

    if compliant:
        result["summary"] = (
            f"Compliant — worst margin {worst_margin_db:.1f} dB at "
            f"{worst_freq_hz / 1e6:.1f} MHz "
            f"({standard.upper()} Class {class_} @ {distance_m} m)."
        )
    else:
        result["summary"] = (
            f"FAIL — worst exceedance {abs(worst_margin_db):.1f} dB at "
            f"{worst_freq_hz / 1e6:.1f} MHz "
            f"({standard.upper()} Class {class_} @ {distance_m} m). "
            f"{len(recommendations)} mitigation(s) recommended."
        )

    return result


# ── LLM tool wrapper ───────────────────────────────────────────────────────────

_EMC_WIZARD_SPEC = ToolSpec(
    name="emc_precompliance_wizard",
    description=(
        "Guided EMC pre-compliance wizard for PCB/cable/enclosure designs.\n\n"
        "Runs a full EMC pre-compliance flow: DM loop radiated emission across "
        "clock harmonics, CM cable emission (if cable supplied), enclosure "
        "shielding check (if shield supplied), and near-field crosstalk screening "
        "(if trace geometry supplied). Compares all channels against FCC Part 15 "
        "or CISPR 32 limits and returns a prioritised findings + fix-recommendation "
        "report with quantified before/after margins.\n\n"
        "Input: { clock_hz, loop_area_m2, loop_current_a, "
        "cable_length_m?, cm_current_a?, "
        "shield_thickness_m?, shield_conductivity_rel?, shield_permeability_rel?, "
        "shield_aperture_length_m?, "
        "trace_width_mm?, trace_spacing_mm?, trace_height_mm?, parallel_length_mm?, "
        "standard?, class_?, distance_m?, n_harmonics? }\n\n"
        "Returns: { ok, compliant, worst_freq_hz, worst_margin_db, "
        "findings[], recommendations[], checklist, summary }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "clock_hz": {
                "type": "number",
                "description": "Fundamental clock frequency [Hz].",
            },
            "loop_area_m2": {
                "type": "number",
                "description": (
                    "PCB differential-mode loop area [m²] "
                    "(trace length × return-path width, converted from mm²: ÷ 1e6)."
                ),
            },
            "loop_current_a": {
                "type": "number",
                "description": "DM loop current amplitude [A].",
            },
            "cable_length_m": {
                "type": "number",
                "description": "Cable length [m] (omit to skip CM analysis).",
            },
            "cm_current_a": {
                "type": "number",
                "description": "Common-mode cable current [A] (default 1 µA).",
            },
            "shield_thickness_m": {
                "type": "number",
                "description": "Enclosure wall thickness [m] (omit to skip SE analysis).",
            },
            "shield_conductivity_rel": {
                "type": "number",
                "description": "Relative conductivity σr (copper=1.0, Al≈0.61; default 1.0).",
            },
            "shield_permeability_rel": {
                "type": "number",
                "description": "Relative permeability μr (copper=1.0, steel≈1000; default 1.0).",
            },
            "shield_aperture_length_m": {
                "type": "number",
                "description": "Largest aperture/slot dimension [m] (default 0).",
            },
            "trace_width_mm": {
                "type": "number",
                "description": "PCB trace width [mm] (supply all 4 trace params for crosstalk check).",
            },
            "trace_spacing_mm": {
                "type": "number",
                "description": "Edge-to-edge trace spacing [mm].",
            },
            "trace_height_mm": {
                "type": "number",
                "description": "Trace height above ground plane [mm].",
            },
            "parallel_length_mm": {
                "type": "number",
                "description": "Parallel run length [mm].",
            },
            "standard": {
                "type": "string",
                "enum": ["fcc", "cispr"],
                "description": "Regulatory standard: 'fcc' or 'cispr' (default 'cispr').",
            },
            "class_": {
                "type": "string",
                "enum": ["A", "B"],
                "description": "Emission class: 'A' (commercial) or 'B' (residential, default).",
            },
            "distance_m": {
                "type": "number",
                "description": "Measurement distance [m] (default 10.0 m).",
            },
            "n_harmonics": {
                "type": "integer",
                "description": "Number of clock harmonics to evaluate (default 10).",
            },
        },
        "required": ["clock_hz", "loop_area_m2", "loop_current_a"],
    },
)


@register(_EMC_WIZARD_SPEC, write=False)
async def emc_precompliance_wizard(ctx: Any, args: bytes) -> str:
    try:
        design = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = emc_precompliance(design)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export ───────────────────────────────────────────────────────────────

TOOLS = [
    (_EMC_WIZARD_SPEC.name, _EMC_WIZARD_SPEC, emc_precompliance_wizard),
]
