"""
Signal-integrity eye-diagram pre-compliance wizard.

Wraps the shipped SI tooling (kerf_electronics.si.solver + kerf_electronics.eye.model)
into an actionable, end-to-end workflow:

  si_eye_precompliance(channel)
  ─────────────────────────────
  1. Pre-scan checklist
       • Reflection penalty from Z0 mismatch   (microstrip_z0 / stripline_z0)
       • Via-stub resonance flag                (quarter-wave stub model)
       • Crosstalk-induced jitter estimate      (first-order NEXT coupling)

  2. Statistical / peak-distortion eye
       • Insertion loss at Nyquist (skin + dielectric loss from loss_db_per_m)
       • ISI from pulse-response broadening     (RC/Bessel + skin + dielectric)
       • Random + deterministic jitter budget   (Tj = Dj + 2·Rj·Q(BER))
       → eye height (V, normalised) and eye width (UI)

  3. Mask comparison
       • Pass/fail vs PCIe Gen-3 / USB 3 / generic Vmask + Tmask

  4. Prioritised findings + highest-leverage fix
       • Shorten trace by X mm
       • Add CTLE / FFE de-emphasis (modelled as a flat IL reduction)
       • Drop data rate
       • Change Z0 (reduce reflection penalty)
     Each fix is quantified by re-running the eye model with the modified
     channel and reporting the before → after margin change.

Contract
────────
• Never raises to callers — all errors are {"ok": False, "reason": ...}.
• @register tools mirror the si/tools.py pattern (write=False).
• TOOLS list exported for plugin._register_tools.

Loss model
──────────
Insertion loss [dB] at Nyquist (fN = data_rate_gbps / 2 [GHz]):

    IL_dB = IL_dc_dB + sqrt(f_GHz) * sqrt_f_coeff + f_GHz * f_coeff

where:
  IL_dc_dB    = DC loss from conductor resistance    (≈ 0 for typical trace)
  sqrt_f_coeff = skin-effect coefficient  [dB / sqrt(GHz)]
  f_coeff      = dielectric-loss coefficient [dB / GHz]

This separates skin and dielectric loss, consistent with the standard
channel model used in IBIS-AMI and industry SI tools (see Bogatin 2004
§7; Johnson & Graham 2003 §3.7).

When the caller supplies just `loss_db_per_m`, we treat it as a flat
Nyquist loss rate and use the eye.model formulas directly (unchanged).

Via stub resonance:
    f_res_GHz ≈ 75 / stub_length_mm     (quarter-wave, εr_eff ≈ 4)
    flagged when f_res_GHz is within ±30% of fN.

Author: imranparuk
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# Pure-math physics — do NOT reimplement, just reuse.
from kerf_electronics.si.solver import (
    microstrip_z0,
    stripline_z0,
    reflection_coefficient,
    propagation_delay_ps_per_mm,
    crosstalk_next,
)
from kerf_electronics.eye.model import eye_estimate as _eye_estimate


# ── Unit-conversion constant ───────────────────────────────────────────────────
_MM_PER_INCH = 25.4
_INCHES_PER_MM = 1.0 / _MM_PER_INCH


# ── Standard eye masks (normalised heights and widths in UI) ──────────────────
#   height : minimum eye opening normalised to ±1 V swing (i.e. 0–2 range)
#   width_ui: minimum eye width [UI]
#
#  PCIe Gen 3 (8 GT/s):  typ 50 mV mask, 0.4 UI width (OIF CEI-25G approximation)
#  USB 3.1 Gen 1 (5 Gbps): ≈ 0.2 UI width
#  Generic (conservative): 0.2 height, 0.3 UI

_EYE_MASKS: Dict[str, Dict[str, float]] = {
    "pcie_gen3":  {"height": 0.10, "width_ui": 0.40},
    "usb3_gen1":  {"height": 0.15, "width_ui": 0.20},
    "usb3_gen2":  {"height": 0.12, "width_ui": 0.25},
    "generic":    {"height": 0.20, "width_ui": 0.30},
}

# ── Fix model constants ────────────────────────────────────────────────────────

# CTLE/FFE equalization is modelled as a reduction in effective IL [dB].
# A 3 dB equalization gain is a conservative but realistic single-stage estimate.
_EQ_GAIN_DB = 3.0

# Trace shortening target: reduce to 70 % of original length (30 % reduction).
_SHORTEN_FRACTION = 0.70

# Preferred Z0 target (50 Ω single-ended, standard termination).
_Z0_TARGET_OHMS = 50.0

# Via stub resonance: quarter-wave model with effective εr = 4.0 (FR4).
_ER_VIA_STUB = 4.0


# ── Internal helpers ───────────────────────────────────────────────────────────


def _vp(err_str: Any, name: str) -> Optional[str]:
    """Return error string if value is not a positive finite number."""
    if not isinstance(err_str, (int, float)) or math.isnan(err_str) or err_str <= 0:
        return f"{name} must be a positive number, got {err_str!r}"
    return None


def _vnn(val: Any, name: str) -> Optional[str]:
    """Return error string if value is not a non-negative finite number."""
    if not isinstance(val, (int, float)) or math.isnan(val) or val < 0:
        return f"{name} must be >= 0, got {val!r}"
    return None


def _loss_db_at_nyquist(channel: dict) -> float:
    """
    Compute total insertion loss [dB] at Nyquist from channel description.

    Supports two modes:
    1. loss_db_per_m supplied   → flat Nyquist loss rate × length_mm / 1000
    2. skin_loss_db_per_sqrt_ghz + dielectric_loss_db_per_ghz
                                → frequency-resolved model at fN = data_rate/2

    If neither is supplied, returns 0 (lossless channel — caller must
    supply at least one loss parameter to get a meaningful result).
    """
    data_rate_gbps = float(channel["data_rate_gbps"])
    length_mm = float(channel["length_mm"])
    f_nyquist_ghz = data_rate_gbps / 2.0

    # Mode 1: flat loss per metre
    if "loss_db_per_m" in channel:
        loss_per_m = float(channel["loss_db_per_m"])
        return loss_per_m * length_mm / 1000.0

    # Mode 2: frequency-resolved skin + dielectric
    skin_coeff = float(channel.get("skin_loss_db_per_sqrt_ghz", 0.0))
    diel_coeff = float(channel.get("dielectric_loss_db_per_ghz", 0.0))
    via_loss_db = float(channel.get("via_loss_db", 0.0))
    conn_loss_db = float(channel.get("connector_loss_db", 0.0))
    pkg_loss_db = float(channel.get("package_loss_db", 0.0))

    # Per-unit loss at Nyquist
    il_per_mm = (
        skin_coeff * math.sqrt(f_nyquist_ghz) / 1000.0
        + diel_coeff * f_nyquist_ghz / 1000.0
    )
    return il_per_mm * length_mm + via_loss_db + conn_loss_db + pkg_loss_db


def _loss_db_per_inch_from_channel(channel: dict) -> float:
    """
    Return insertion-loss rate [dB/inch] at Nyquist, derived from total IL.

    Used to feed kerf_electronics.eye.model.eye_estimate which expects
    loss_db_per_inch and length_inch.
    """
    loss_total = _loss_db_at_nyquist(channel)
    length_mm = float(channel["length_mm"])
    length_inch = length_mm * _INCHES_PER_MM
    if length_inch <= 0:
        return 0.0
    return loss_total / length_inch


def _compute_eye(channel: dict) -> dict:
    """
    Run eye_estimate for the given channel.

    Returns the eye_estimate dict (ok/eye_height/eye_width_ui/…).
    """
    length_mm = float(channel["length_mm"])
    length_inch = length_mm * _INCHES_PER_MM
    data_rate_gbps = float(channel["data_rate_gbps"])
    bit_rate_bps = data_rate_gbps * 1e9

    ldi = _loss_db_per_inch_from_channel(channel)

    rise_time_tx_s = float(channel.get("rise_time_tx_ps", 30.0)) * 1e-12
    isi_fraction = float(channel.get("isi_fraction", 0.05))
    gamma = float(channel.get("reflection_gamma", 0.0))

    return _eye_estimate(
        loss_db_per_inch=max(ldi, 1e-9),
        length_inch=max(length_inch, 1e-9),
        bit_rate_bps=bit_rate_bps,
        rise_time_tx_s=rise_time_tx_s,
        isi_fraction=isi_fraction,
        reflection_gamma=gamma,
    )


def _z0_from_channel(channel: dict) -> Optional[float]:
    """
    Compute Z0 from trace geometry if stackup fields are present.

    Returns float or None if insufficient geometry supplied.
    """
    structure = channel.get("structure", "")
    W = channel.get("trace_width_mm")
    H = channel.get("dielectric_height_mm")
    er = channel.get("er")
    T = channel.get("copper_thickness_mm", 0.035)

    if not all(isinstance(v, (int, float)) and v > 0 for v in (W, H, er)):
        return None

    try:
        if structure == "stripline":
            return stripline_z0(float(W), float(H), float(T), float(er))
        else:
            return microstrip_z0(float(W), float(H), float(T), float(er))
    except Exception:
        return None


def _reflection_gamma_from_z0(z0: float, z_load: float = 1e6) -> float:
    """Reflection coefficient magnitude at an open-ended load (default) or z_load."""
    gamma = reflection_coefficient(z_load, z0)
    return abs(gamma)


def _via_stub_resonance_ghz(stub_length_mm: float, er_eff: float = _ER_VIA_STUB) -> float:
    """Quarter-wave stub resonance frequency [GHz]."""
    # f_res = c / (4 * L * sqrt(er_eff))   where c = 300 mm/ns = 3e5 m/ms
    c_mm_ps = 0.299792458  # mm/ps
    f_res_ghz = c_mm_ps / (4.0 * stub_length_mm * math.sqrt(er_eff)) * 1000.0
    return f_res_ghz


def _margin_from_eye(eye: dict, mask: dict) -> Dict[str, float]:
    """Return height and width margins (positive = passing)."""
    return {
        "margin_height": eye["eye_height"] - mask["height"],
        "margin_width_ui": eye["eye_width_ui"] - mask["width_ui"],
    }


# ── Core wizard ────────────────────────────────────────────────────────────────


def si_eye_precompliance(channel: dict) -> dict:
    """
    Signal-integrity eye-diagram pre-compliance wizard.

    Parameters (channel dict keys)
    ──────────────────────────────
    Required:
        data_rate_gbps    : float — signalling data rate [Gbps], e.g. 8.0 for PCIe Gen 3
        length_mm         : float — trace (channel) length [mm]

    Loss model — supply one of:
        loss_db_per_m     : float — flat Nyquist IL rate [dB/m]  (simplest)
        skin_loss_db_per_sqrt_ghz : float — skin-effect IL coefficient [dB / sqrt(GHz) / m]
                                            (multiply by length in m internally)
        dielectric_loss_db_per_ghz : float — dielectric IL coefficient [dB / GHz / m]

    Optional — trace geometry (enables Z0 reflection pre-check):
        structure         : str   — 'microstrip' (default) or 'stripline'
        trace_width_mm    : float — trace width [mm]
        dielectric_height_mm : float — H (microstrip) or B (stripline) [mm]
        er                : float — substrate εr (FR4 ≈ 4.5)
        copper_thickness_mm : float — copper thickness [mm] (default 0.035)
        z_load_ohms       : float — load impedance [Ω] for reflection calc (default open = 1 MΩ)

    Optional — via stub (enables resonance pre-check):
        via_stub_length_mm : float — via stub length below signal layer [mm]
        via_loss_db        : float — additional loss from vias [dB] (default 0)

    Optional — connector / package:
        connector_loss_db  : float — connector insertion loss [dB] (default 0)
        package_loss_db    : float — IC package loss [dB] (default 0)

    Optional — jitter:
        rj_ps              : float — random jitter 1-sigma [ps] (default 2 ps)
        dj_ps              : float — deterministic jitter p-p [ps] (default 10 ps)
        ber                : float — target BER (default 1e-12)

    Optional — transmitter:
        rise_time_tx_ps    : float — Tx 10-90% rise time [ps] (default 30 ps)
        isi_fraction       : float — fractional ISI penalty 0–1 (default 0.05)
        reflection_gamma   : float — |Γ| from Z0 mismatch (default: computed from
                                     geometry if stackup supplied, else 0)

    Optional — mask:
        mask               : str  — 'pcie_gen3', 'usb3_gen1', 'usb3_gen2', 'generic'
                                    (default: 'generic')
        mask_height        : float — override mask minimum eye height
        mask_width_ui      : float — override mask minimum eye width [UI]

    Optional — crosstalk:
        aggressor_spacing_mm  : float — edge-to-edge spacing to nearest aggressor [mm]
        aggressor_swing_mv    : float — aggressor signal swing [mV] (default 800 mV)

    Returns
    ───────
    dict with keys:
        ok                : bool
        compliant         : bool   — True if eye passes the mask
        eye_height        : float  — vertical eye opening (normalised)
        eye_width_ui      : float  — horizontal eye opening [UI]
        margin_height     : float  — eye_height - mask_height (positive = margin)
        margin_width_ui   : float  — eye_width_ui - mask_width_ui (positive = margin)
        mask_used         : dict   — mask definition applied
        loss_db           : float  — total IL at Nyquist [dB]
        jitter            : dict   — Tj, Rj, Dj, Q factor
        checklist         : dict   — reflection/via/xtalk pre-scan results
        findings          : list   — per-issue finding dicts
        recommendations   : list   — prioritised fix dicts with before/after margins
        summary           : str    — human-readable one-line verdict
        reason            : str    — present only when ok=False
    """
    if not isinstance(channel, dict):
        return {"ok": False, "reason": "channel must be a dict"}

    # ── Required fields ────────────────────────────────────────────────────────
    err = _vp(channel.get("data_rate_gbps"), "data_rate_gbps")
    if err:
        return {"ok": False, "reason": err}
    err = _vp(channel.get("length_mm"), "length_mm")
    if err:
        return {"ok": False, "reason": err}

    data_rate_gbps = float(channel["data_rate_gbps"])
    length_mm = float(channel["length_mm"])
    bit_rate_bps = data_rate_gbps * 1e9

    # ── Loss check: need at least one source ───────────────────────────────────
    has_flat = "loss_db_per_m" in channel
    has_skin = "skin_loss_db_per_sqrt_ghz" in channel
    has_diel = "dielectric_loss_db_per_ghz" in channel
    if not (has_flat or has_skin or has_diel):
        return {
            "ok": False,
            "reason": (
                "At least one loss parameter is required: "
                "loss_db_per_m, skin_loss_db_per_sqrt_ghz, or dielectric_loss_db_per_ghz"
            ),
        }

    # Validate loss values if present
    if has_flat:
        err = _vp(channel.get("loss_db_per_m"), "loss_db_per_m")
        if err:
            return {"ok": False, "reason": err}
    if has_skin:
        err = _vnn(channel.get("skin_loss_db_per_sqrt_ghz"), "skin_loss_db_per_sqrt_ghz")
        if err:
            return {"ok": False, "reason": err}
    if has_diel:
        err = _vnn(channel.get("dielectric_loss_db_per_ghz"), "dielectric_loss_db_per_ghz")
        if err:
            return {"ok": False, "reason": err}

    # Validate optional positive fields
    for field in ("via_loss_db", "connector_loss_db", "package_loss_db"):
        if field in channel:
            err = _vnn(channel[field], field)
            if err:
                return {"ok": False, "reason": err}

    for field in ("rj_ps", "dj_ps", "rise_time_tx_ps"):
        if field in channel:
            err = _vnn(channel[field], field)
            if err:
                return {"ok": False, "reason": err}

    for field in ("isi_fraction", "reflection_gamma"):
        if field in channel:
            err = _vnn(channel[field], field)
            if err:
                return {"ok": False, "reason": err}

    # ── Mask selection ─────────────────────────────────────────────────────────
    mask_name = str(channel.get("mask", "generic")).lower()
    mask = dict(_EYE_MASKS.get(mask_name, _EYE_MASKS["generic"]))
    if "mask_height" in channel:
        mh = channel["mask_height"]
        if not isinstance(mh, (int, float)) or mh < 0:
            return {"ok": False, "reason": f"mask_height must be >= 0, got {mh!r}"}
        mask["height"] = float(mh)
    if "mask_width_ui" in channel:
        mw = channel["mask_width_ui"]
        if not isinstance(mw, (int, float)) or mw < 0:
            return {"ok": False, "reason": f"mask_width_ui must be >= 0, got {mw!r}"}
        mask["width_ui"] = float(mw)

    # ── Z0 / reflection pre-scan ───────────────────────────────────────────────
    computed_z0 = _z0_from_channel(channel)
    z_load = float(channel.get("z_load_ohms", 1e6))
    if z_load <= 0:
        z_load = 1e6

    # If reflection_gamma not supplied but we have geometry, compute it
    if "reflection_gamma" not in channel and computed_z0 is not None:
        z_load_r = float(channel.get("z_load_ohms", _Z0_TARGET_OHMS))
        gamma_geom = abs(reflection_coefficient(z_load_r, computed_z0))
        channel = dict(channel)
        channel["reflection_gamma"] = gamma_geom

    gamma = float(channel.get("reflection_gamma", 0.0))

    # Z0 mismatch flag: significant if gamma > 0.1 (>10% reflection)
    z0_mismatch = gamma > 0.10
    z0_penalty_vh = gamma * (10.0 ** (-_loss_db_at_nyquist(channel) / 20.0))

    # ── Via stub resonance pre-scan ────────────────────────────────────────────
    via_stub_mm = channel.get("via_stub_length_mm")
    via_resonance_flag = False
    via_resonance_ghz = None
    f_nyquist_ghz = data_rate_gbps / 2.0

    if isinstance(via_stub_mm, (int, float)) and via_stub_mm > 0:
        via_resonance_ghz = _via_stub_resonance_ghz(float(via_stub_mm))
        # Flag if resonance is within ±30% of Nyquist
        rel_diff = abs(via_resonance_ghz - f_nyquist_ghz) / f_nyquist_ghz
        via_resonance_flag = rel_diff <= 0.30

    # ── Crosstalk-induced jitter pre-scan ──────────────────────────────────────
    xtalk_jitter_ps = 0.0
    xtalk_flag = False
    aggressor_spacing_mm = channel.get("aggressor_spacing_mm")
    aggressor_swing_mv = float(channel.get("aggressor_swing_mv", 800.0))

    if isinstance(aggressor_spacing_mm, (int, float)) and aggressor_spacing_mm > 0:
        H_for_xtalk = float(channel.get("dielectric_height_mm", 0.1))
        if H_for_xtalk <= 0:
            H_for_xtalk = 0.1
        try:
            xt_res = crosstalk_next(
                S=float(aggressor_spacing_mm),
                H=H_for_xtalk,
                aggressor_swing_mv=aggressor_swing_mv,
            )
            # Convert NEXT voltage to jitter: first-order approximation
            # ΔV_noise → ΔT_jitter ≈ ΔV / slew_rate
            # slew rate ≈ swing / (0.4 * UI) for 0–100% in 0.4 UI
            ui_ps = 1e12 / bit_rate_bps
            swing_mv = aggressor_swing_mv
            slew_mv_per_ps = swing_mv / (0.4 * ui_ps) if ui_ps > 0 else 1.0
            xtalk_jitter_ps = xt_res["next_mv"] / slew_mv_per_ps
            xtalk_flag = xtalk_jitter_ps > (0.02 * ui_ps)  # >2% UI is significant
        except Exception:
            pass

    # ── Jitter budget ──────────────────────────────────────────────────────────
    rj_ps = float(channel.get("rj_ps", 2.0))
    dj_ps = float(channel.get("dj_ps", 10.0))
    ber = float(channel.get("ber", 1e-12))

    # Add xtalk jitter to Dj (it is deterministic/bounded)
    dj_total_ps = dj_ps + xtalk_jitter_ps

    # Q factor from BER
    def _q_from_ber(b: float) -> float:
        if b <= 0 or b >= 0.5:
            return 7.035
        from kerf_electronics.eye.model import _q_factor
        return _q_factor(b)

    q = _q_from_ber(ber)
    tj_ps = dj_total_ps + 2.0 * rj_ps * q
    ui_ps = 1e12 / bit_rate_bps
    tj_ui = tj_ps / ui_ps if ui_ps > 0 else 0.0

    jitter_result = {
        "rj_ps": round(rj_ps, 4),
        "dj_ps": round(dj_ps, 4),
        "xtalk_dj_ps": round(xtalk_jitter_ps, 4),
        "dj_total_ps": round(dj_total_ps, 4),
        "tj_ps": round(tj_ps, 4),
        "tj_ui": round(tj_ui, 6),
        "q_factor": round(q, 4),
        "ber": ber,
        "ui_ps": round(ui_ps, 4),
    }

    # ── Baseline eye ───────────────────────────────────────────────────────────
    eye_base = _compute_eye(channel)
    if not eye_base.get("ok"):
        return {"ok": False, "reason": f"eye estimation failed: {eye_base.get('reason', '?')}"}

    loss_db = eye_base["loss_db"]

    # Adjust eye width for jitter (subtract Tj in UI from the geometric eye width)
    eye_height_base = eye_base["eye_height"]
    eye_width_base = max(0.0, eye_base["eye_width_ui"] - tj_ui)

    # Margins vs mask
    margin_h = eye_height_base - mask["height"]
    margin_w = eye_width_base - mask["width_ui"]
    compliant = (margin_h >= 0.0) and (margin_w >= 0.0)

    # ── Pre-scan checklist ─────────────────────────────────────────────────────
    checklist: Dict[str, Any] = {
        "z0_mismatch": {
            "flagged": z0_mismatch,
            "gamma": round(gamma, 4),
            "z0_ohms": round(computed_z0, 2) if computed_z0 is not None else None,
            "penalty_eye_height": round(z0_penalty_vh, 6),
            "description": (
                f"Reflection |Γ|={gamma:.3f} adds {z0_penalty_vh:.4f} V eye-height penalty. "
                "Terminate to Z0 or match driver/load impedance."
                if z0_mismatch else
                "Z0 reflection penalty is negligible."
            ),
        },
        "via_stub_resonance": {
            "flagged": via_resonance_flag,
            "stub_length_mm": via_stub_mm,
            "resonance_ghz": round(via_resonance_ghz, 3) if via_resonance_ghz is not None else None,
            "nyquist_ghz": round(f_nyquist_ghz, 3),
            "description": (
                f"Via stub resonance at {via_resonance_ghz:.2f} GHz is near Nyquist "
                f"({f_nyquist_ghz:.2f} GHz) — back-drill the stub to remove it."
                if via_resonance_flag else
                "Via stub resonance is not near Nyquist." if via_resonance_ghz is not None else
                "No via stub supplied."
            ),
        },
        "crosstalk_jitter": {
            "flagged": xtalk_flag,
            "spacing_mm": aggressor_spacing_mm,
            "xtalk_jitter_ps": round(xtalk_jitter_ps, 4),
            "xtalk_jitter_ui": round(xtalk_jitter_ps / ui_ps, 6) if ui_ps > 0 else 0.0,
            "description": (
                f"Crosstalk-induced jitter {xtalk_jitter_ps:.2f} ps "
                f"({xtalk_jitter_ps / ui_ps * 100:.1f}% UI) is significant — "
                "increase aggressor spacing or add guard traces."
                if xtalk_flag else
                "Crosstalk-induced jitter is within acceptable limits."
                if aggressor_spacing_mm is not None else
                "No aggressor spacing supplied — crosstalk check skipped."
            ),
        },
    }

    # ── Findings ───────────────────────────────────────────────────────────────
    findings: List[dict] = []

    if margin_h < 0:
        findings.append({
            "issue": "eye_height_insufficient",
            "margin_height": round(margin_h, 6),
            "eye_height": round(eye_height_base, 6),
            "mask_height": mask["height"],
            "description": (
                f"Eye height {eye_height_base:.4f} is below mask minimum "
                f"{mask['height']:.4f} (deficit {abs(margin_h):.4f})."
            ),
        })

    if margin_w < 0:
        findings.append({
            "issue": "eye_width_insufficient",
            "margin_width_ui": round(margin_w, 6),
            "eye_width_ui": round(eye_width_base, 6),
            "mask_width_ui": mask["width_ui"],
            "description": (
                f"Eye width {eye_width_base:.4f} UI is below mask minimum "
                f"{mask['width_ui']:.4f} UI (deficit {abs(margin_w):.4f} UI)."
            ),
        })

    if z0_mismatch:
        findings.append({
            "issue": "z0_mismatch",
            "gamma": round(gamma, 4),
            "z0_ohms": round(computed_z0, 2) if computed_z0 is not None else None,
            "description": (
                f"Z0 mismatch: |Γ|={gamma:.3f} reduces eye height by "
                f"{z0_penalty_vh:.4f}."
            ),
        })

    if via_resonance_flag:
        findings.append({
            "issue": "via_stub_resonance",
            "resonance_ghz": round(via_resonance_ghz, 3),
            "nyquist_ghz": round(f_nyquist_ghz, 3),
            "description": (
                f"Via stub resonance at {via_resonance_ghz:.2f} GHz coincides with "
                f"Nyquist at {f_nyquist_ghz:.2f} GHz — notch will deepen the eye."
            ),
        })

    if xtalk_flag:
        findings.append({
            "issue": "crosstalk_jitter",
            "xtalk_jitter_ps": round(xtalk_jitter_ps, 4),
            "description": (
                f"Crosstalk adds {xtalk_jitter_ps:.2f} ps Dj "
                f"({xtalk_jitter_ps / ui_ps * 100:.1f}% UI)."
            ),
        })

    # ── Recommendations ────────────────────────────────────────────────────────
    recommendations: List[dict] = []
    priority = 1

    # ── Fix 1: Shorten the trace ──────────────────────────────────────────────
    if not compliant:
        short_channel = dict(channel)
        short_channel["length_mm"] = length_mm * _SHORTEN_FRACTION
        eye_short = _compute_eye(short_channel)
        if eye_short.get("ok"):
            eye_short_w = max(0.0, eye_short["eye_width_ui"] - tj_ui)
            marg_h_short = eye_short["eye_height"] - mask["height"]
            marg_w_short = eye_short_w - mask["width_ui"]
            recommendations.append({
                "priority": priority,
                "action": "shorten_trace",
                "description": (
                    f"Shorten trace from {length_mm:.1f} mm to "
                    f"{length_mm * _SHORTEN_FRACTION:.1f} mm "
                    f"(−{length_mm * (1 - _SHORTEN_FRACTION):.1f} mm, "
                    f"{int((1 - _SHORTEN_FRACTION) * 100)}% reduction). "
                    "Reduces insertion loss and ISI."
                ),
                "target_length_mm": round(length_mm * _SHORTEN_FRACTION, 2),
                "before_eye_height": round(eye_height_base, 6),
                "after_eye_height": round(eye_short["eye_height"], 6),
                "before_eye_width_ui": round(eye_width_base, 6),
                "after_eye_width_ui": round(eye_short_w, 6),
                "before_margin_height": round(margin_h, 6),
                "after_margin_height": round(marg_h_short, 6),
                "before_margin_width_ui": round(margin_w, 6),
                "after_margin_width_ui": round(marg_w_short, 6),
                "improvement_eye_height": round(eye_short["eye_height"] - eye_height_base, 6),
                "improvement_eye_width_ui": round(eye_short_w - eye_width_base, 6),
            })
            priority += 1

    # ── Fix 2: Add CTLE/FFE equalization (modelled as IL reduction) ───────────
    if not compliant:
        eq_channel = dict(channel)
        # Reduce effective IL by _EQ_GAIN_DB: scale loss_db_per_m or skin/diel coeff
        if "loss_db_per_m" in eq_channel:
            # Reduce total IL by EQ_GAIN_DB — scale down loss_db_per_m
            orig_loss = _loss_db_at_nyquist(channel)
            new_loss = max(0.0, orig_loss - _EQ_GAIN_DB)
            length_m = length_mm / 1000.0
            eq_channel["loss_db_per_m"] = new_loss / length_m if length_m > 0 else float(eq_channel["loss_db_per_m"])
        else:
            # Scale down skin and dielectric coefficients proportionally
            orig_loss = _loss_db_at_nyquist(channel)
            if orig_loss > 0:
                scale = max(0.0, orig_loss - _EQ_GAIN_DB) / orig_loss
                if "skin_loss_db_per_sqrt_ghz" in eq_channel:
                    eq_channel["skin_loss_db_per_sqrt_ghz"] = float(eq_channel["skin_loss_db_per_sqrt_ghz"]) * scale
                if "dielectric_loss_db_per_ghz" in eq_channel:
                    eq_channel["dielectric_loss_db_per_ghz"] = float(eq_channel["dielectric_loss_db_per_ghz"]) * scale

        eye_eq = _compute_eye(eq_channel)
        if eye_eq.get("ok"):
            eye_eq_w = max(0.0, eye_eq["eye_width_ui"] - tj_ui)
            marg_h_eq = eye_eq["eye_height"] - mask["height"]
            marg_w_eq = eye_eq_w - mask["width_ui"]
            recommendations.append({
                "priority": priority,
                "action": "add_equalization",
                "description": (
                    f"Add CTLE or FFE de-emphasis providing ≥{_EQ_GAIN_DB:.0f} dB "
                    "equalization gain at Nyquist. "
                    "Modelled as reducing effective insertion loss by "
                    f"{_EQ_GAIN_DB:.0f} dB."
                ),
                "eq_gain_db": _EQ_GAIN_DB,
                "before_eye_height": round(eye_height_base, 6),
                "after_eye_height": round(eye_eq["eye_height"], 6),
                "before_eye_width_ui": round(eye_width_base, 6),
                "after_eye_width_ui": round(eye_eq_w, 6),
                "before_margin_height": round(margin_h, 6),
                "after_margin_height": round(marg_h_eq, 6),
                "before_margin_width_ui": round(margin_w, 6),
                "after_margin_width_ui": round(marg_w_eq, 6),
                "improvement_eye_height": round(eye_eq["eye_height"] - eye_height_base, 6),
                "improvement_eye_width_ui": round(eye_eq_w - eye_width_base, 6),
            })
            priority += 1

    # ── Fix 3: Drop data rate by 20% ──────────────────────────────────────────
    if not compliant:
        reduced_rate = data_rate_gbps * 0.8
        dr_channel = dict(channel)
        dr_channel["data_rate_gbps"] = reduced_rate
        eye_dr = _compute_eye(dr_channel)
        if eye_dr.get("ok"):
            ui_ps_new = 1e12 / (reduced_rate * 1e9)
            eye_dr_w = max(0.0, eye_dr["eye_width_ui"] - tj_ui * (ui_ps / ui_ps_new) if ui_ps_new > 0 else 0.0)
            marg_h_dr = eye_dr["eye_height"] - mask["height"]
            marg_w_dr = eye_dr_w - mask["width_ui"]
            recommendations.append({
                "priority": priority,
                "action": "reduce_data_rate",
                "description": (
                    f"Reduce data rate from {data_rate_gbps:.1f} Gbps to "
                    f"{reduced_rate:.1f} Gbps (−20%). "
                    "Wider UI reduces jitter penalty and improves ISI."
                ),
                "before_data_rate_gbps": round(data_rate_gbps, 3),
                "after_data_rate_gbps": round(reduced_rate, 3),
                "before_eye_height": round(eye_height_base, 6),
                "after_eye_height": round(eye_dr["eye_height"], 6),
                "before_eye_width_ui": round(eye_width_base, 6),
                "after_eye_width_ui": round(eye_dr_w, 6),
                "before_margin_height": round(margin_h, 6),
                "after_margin_height": round(marg_h_dr, 6),
                "before_margin_width_ui": round(margin_w, 6),
                "after_margin_width_ui": round(marg_w_dr, 6),
                "improvement_eye_height": round(eye_dr["eye_height"] - eye_height_base, 6),
                "improvement_eye_width_ui": round(eye_dr_w - eye_width_base, 6),
            })
            priority += 1

    # ── Fix 4: Improve Z0 matching (reduce gamma) ──────────────────────────────
    if z0_mismatch and not compliant:
        matched_channel = dict(channel)
        # Target matched termination: reduce gamma to near-zero
        matched_channel["reflection_gamma"] = 0.01
        eye_matched = _compute_eye(matched_channel)
        if eye_matched.get("ok"):
            eye_matched_w = max(0.0, eye_matched["eye_width_ui"] - tj_ui)
            marg_h_matched = eye_matched["eye_height"] - mask["height"]
            marg_w_matched = eye_matched_w - mask["width_ui"]
            target_z0 = _Z0_TARGET_OHMS if computed_z0 is None else computed_z0
            recommendations.append({
                "priority": priority,
                "action": "match_z0",
                "description": (
                    f"Terminate line to Z0 ≈ {target_z0:.1f} Ω to reduce |Γ| from "
                    f"{gamma:.3f} to <0.01. "
                    "Add series (source) or parallel (load) termination resistor."
                ),
                "current_gamma": round(gamma, 4),
                "target_gamma": 0.01,
                "target_z0_ohms": round(target_z0, 1),
                "before_eye_height": round(eye_height_base, 6),
                "after_eye_height": round(eye_matched["eye_height"], 6),
                "before_eye_width_ui": round(eye_width_base, 6),
                "after_eye_width_ui": round(eye_matched_w, 6),
                "before_margin_height": round(margin_h, 6),
                "after_margin_height": round(marg_h_matched, 6),
                "before_margin_width_ui": round(margin_w, 6),
                "after_margin_width_ui": round(marg_w_matched, 6),
                "improvement_eye_height": round(eye_matched["eye_height"] - eye_height_base, 6),
                "improvement_eye_width_ui": round(eye_matched_w - eye_width_base, 6),
            })
            priority += 1

    # ── Sort by priority ───────────────────────────────────────────────────────
    recommendations.sort(key=lambda r: r["priority"])

    # ── Summary string ─────────────────────────────────────────────────────────
    if compliant:
        summary = (
            f"Compliant — eye height margin {margin_h:+.4f}, "
            f"eye width margin {margin_w:+.4f} UI "
            f"vs {mask_name} mask at {data_rate_gbps:.1f} Gbps."
        )
    else:
        deficits = []
        if margin_h < 0:
            deficits.append(f"height deficit {abs(margin_h):.4f}")
        if margin_w < 0:
            deficits.append(f"width deficit {abs(margin_w):.4f} UI")
        summary = (
            f"FAIL — {', '.join(deficits)} vs {mask_name} mask at "
            f"{data_rate_gbps:.1f} Gbps / {length_mm:.1f} mm. "
            f"{len(recommendations)} fix(es) recommended."
        )

    return {
        "ok": True,
        "compliant": compliant,
        "eye_height": round(eye_height_base, 6),
        "eye_width_ui": round(eye_width_base, 6),
        "margin_height": round(margin_h, 6),
        "margin_width_ui": round(margin_w, 6),
        "mask_used": {"name": mask_name, **mask},
        "loss_db": round(loss_db, 4),
        "jitter": jitter_result,
        "checklist": checklist,
        "findings": findings,
        "recommendations": recommendations,
        "summary": summary,
    }


# ── LLM tool wrapper ───────────────────────────────────────────────────────────

_SI_EYE_WIZARD_SPEC = ToolSpec(
    name="si_eye_precompliance_wizard",
    description=(
        "Guided signal-integrity eye-diagram pre-compliance wizard for high-speed "
        "PCB serial links.\n\n"
        "Builds a statistical/peak-distortion eye from a channel description (data rate, "
        "trace length, insertion-loss model, via/connector/package losses, jitter budget), "
        "compares vs a chosen mask (PCIe Gen 3 / USB 3 / generic), produces a pre-scan "
        "checklist (Z0 reflection, via stub resonance, crosstalk jitter), and returns "
        "prioritised fixes (shorten trace / add CTLE-FFE / drop data rate / match Z0) "
        "with quantified before→after eye-margin changes.\n\n"
        "Input: { data_rate_gbps, length_mm, "
        "loss_db_per_m | skin_loss_db_per_sqrt_ghz + dielectric_loss_db_per_ghz, "
        "trace_width_mm?, dielectric_height_mm?, er?, structure?, "
        "via_stub_length_mm?, via_loss_db?, connector_loss_db?, package_loss_db?, "
        "rise_time_tx_ps?, isi_fraction?, reflection_gamma?, "
        "rj_ps?, dj_ps?, ber?, "
        "aggressor_spacing_mm?, aggressor_swing_mv?, "
        "mask?, mask_height?, mask_width_ui? }\n\n"
        "Returns: { ok, compliant, eye_height, eye_width_ui, margin_height, "
        "margin_width_ui, mask_used, loss_db, jitter, checklist, findings[], "
        "recommendations[], summary }"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "data_rate_gbps": {
                "type": "number",
                "description": "Signalling data rate [Gbps], e.g. 8.0 for PCIe Gen 3.",
            },
            "length_mm": {
                "type": "number",
                "description": "Trace (channel) length [mm].",
            },
            "loss_db_per_m": {
                "type": "number",
                "description": (
                    "Flat Nyquist insertion-loss rate [dB/m]. "
                    "Typical FR4: 40–80 dB/m at 5 GHz. "
                    "Supply this OR skin + dielectric coefficients."
                ),
            },
            "skin_loss_db_per_sqrt_ghz": {
                "type": "number",
                "description": (
                    "Skin-effect IL coefficient [dB / sqrt(GHz) / m]. "
                    "Typical copper trace: 3–7 dB / sqrt(GHz) / m."
                ),
            },
            "dielectric_loss_db_per_ghz": {
                "type": "number",
                "description": (
                    "Dielectric IL coefficient [dB / GHz / m]. "
                    "Typical FR4: 2–5 dB / GHz / m."
                ),
            },
            "structure": {
                "type": "string",
                "enum": ["microstrip", "stripline"],
                "description": "Trace type for Z0 calculation (default: 'microstrip').",
            },
            "trace_width_mm": {
                "type": "number",
                "description": "Trace width [mm] (required for Z0 check).",
            },
            "dielectric_height_mm": {
                "type": "number",
                "description": "Dielectric height H (microstrip) or B (stripline) [mm].",
            },
            "er": {
                "type": "number",
                "description": "Substrate relative permittivity εr (FR4 ≈ 4.5).",
            },
            "copper_thickness_mm": {
                "type": "number",
                "description": "Copper thickness [mm] (default 0.035 = 1 oz).",
            },
            "z_load_ohms": {
                "type": "number",
                "description": "Load impedance [Ω] for reflection calculation (default 50 Ω).",
            },
            "via_stub_length_mm": {
                "type": "number",
                "description": "Via stub length below signal layer [mm] (enables stub resonance check).",
            },
            "via_loss_db": {
                "type": "number",
                "description": "Additional insertion loss from vias [dB] (default 0).",
            },
            "connector_loss_db": {
                "type": "number",
                "description": "Connector insertion loss [dB] (default 0).",
            },
            "package_loss_db": {
                "type": "number",
                "description": "IC package insertion loss [dB] (default 0).",
            },
            "rise_time_tx_ps": {
                "type": "number",
                "description": "Transmitter 10-90% rise time [ps] (default 30 ps).",
            },
            "isi_fraction": {
                "type": "number",
                "description": "Fractional ISI penalty (0–1, default 0.05).",
            },
            "reflection_gamma": {
                "type": "number",
                "description": (
                    "Reflection coefficient |Γ| (0–1). "
                    "If omitted and trace geometry is supplied, computed from Z0."
                ),
            },
            "rj_ps": {
                "type": "number",
                "description": "Random jitter 1-sigma [ps] (default 2 ps).",
            },
            "dj_ps": {
                "type": "number",
                "description": "Deterministic jitter peak-to-peak [ps] (default 10 ps).",
            },
            "ber": {
                "type": "number",
                "description": "Target bit-error ratio (default 1e-12).",
            },
            "aggressor_spacing_mm": {
                "type": "number",
                "description": "Edge-to-edge spacing to nearest aggressor trace [mm].",
            },
            "aggressor_swing_mv": {
                "type": "number",
                "description": "Aggressor signal swing [mV] (default 800 mV).",
            },
            "mask": {
                "type": "string",
                "enum": ["pcie_gen3", "usb3_gen1", "usb3_gen2", "generic"],
                "description": "Eye-diagram mask to compare against (default 'generic').",
            },
            "mask_height": {
                "type": "number",
                "description": "Override mask minimum eye height (normalised, >= 0).",
            },
            "mask_width_ui": {
                "type": "number",
                "description": "Override mask minimum eye width [UI] (>= 0).",
            },
        },
        "required": ["data_rate_gbps", "length_mm"],
    },
)


@register(_SI_EYE_WIZARD_SPEC, write=False)
async def si_eye_precompliance_wizard(ctx: Any, args: bytes) -> str:
    try:
        channel = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    result = si_eye_precompliance(channel)
    if not result.get("ok"):
        return err_payload(result.get("reason", "unknown error"), "BAD_ARGS")
    return ok_payload(result)


# ── TOOLS export ───────────────────────────────────────────────────────────────

TOOLS = [
    (_SI_EYE_WIZARD_SPEC.name, _SI_EYE_WIZARD_SPEC, si_eye_precompliance_wizard),
]
