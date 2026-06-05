"""
LLM tool wrapper for Paris-law fatigue crack growth + Erdogan-Sih kink angle.

Registers:
  fem_crack_growth — Paris-law da/dN = C·ΔK^m integration; a-vs-N curve;
                     mixed-mode kink angle (Erdogan-Sih 1963).

XFEM limit
----------
This tool drives crack growth using the existing SIF/J-integral values
from the kerf-fem fracture module (or ASTM geometry-factor formulae).
Full XFEM enrichment (Heaviside + tip enrichment, Moës et al. 1999) is
not implemented — that requires a full partition-of-unity FEM rework
(deferred to T-100-C). Paris-law propagation on the existing SIF is the
tractable, engineering-relevant core.

References
----------
  Paris, P. & Erdogan, F. (1963). J. Basic Eng. 85(4), 528-534.
  Erdogan, F. & Sih, G. C. (1963). J. Basic Eng. 85(4), 519-527.
  Anderson, T. L. (2005). Fracture Mechanics, 3rd ed., CRC Press, Ch. 10.
"""

from __future__ import annotations

import json
import math
from typing import List

import numpy as np

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_fem._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


_fem_crack_growth_spec = ToolSpec(
    name="fem_crack_growth",
    description=(
        "Paris-law fatigue crack-growth analysis: integrate da/dN = C·ΔK^m "
        "to produce crack-length-vs-cycles (a-vs-N) curves, plus mixed-mode "
        "kink-angle prediction via the Erdogan-Sih (1963) maximum hoop-stress "
        "criterion. Supports SENT, central-crack, and CT specimen geometries.\n\n"
        "Inputs: Paris constants C [m/cycle/(Pa√m)^m], m; stress range Δσ [Pa]; "
        "geometry (SENT / central_crack / CT); initial crack a_0; fracture "
        "toughness K_Ic [Pa√m]; optional K_I/K_II for mixed-mode kink angle.\n\n"
        "Closed-form oracle for constant-ΔK: N = (a_f - a_0) / (C·ΔK^m).\n\n"
        "XFEM caveat: uses geometry-factor SIF, NOT discontinuous enrichment — "
        "full XFEM (Moës 1999) not implemented; deferred to T-100-C.\n\n"
        "References: Paris & Erdogan (1963); Erdogan & Sih (1963); Anderson (2005)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            # Paris law
            "C": {
                "type": "number",
                "description": (
                    "Paris coefficient C [m/cycle / (Pa√m)^m]. "
                    "Typical structural steel: 3e-12 to 1e-11; aluminium: 1e-11 to 5e-11."
                ),
            },
            "m": {
                "type": "number",
                "description": "Paris exponent m (dimensionless). Typical metals: 2–4.",
            },
            "K_Ic_pa_sqrt_m": {
                "type": "number",
                "description": (
                    "Fracture toughness K_Ic [Pa√m]. "
                    "Steel: 50–200 MPa√m; 7075-T6 aluminium: ~29 MPa√m."
                ),
            },
            "K_th_pa_sqrt_m": {
                "type": "number",
                "description": (
                    "Threshold SIF range ΔK_th [Pa√m] below which da/dN → 0. "
                    "Default 0 (pure Paris law). Typical steel: 2–10 MPa√m."
                ),
            },
            "R_ratio": {
                "type": "number",
                "description": "Stress ratio R = K_min / K_max (default 0 = zero-to-max loading).",
            },
            # Loading
            "delta_sigma_pa": {
                "type": "number",
                "description": "Nominal stress range Δσ [Pa] (remote stress amplitude).",
            },
            # Geometry
            "geometry": {
                "type": "string",
                "enum": ["SENT", "central_crack", "CT"],
                "description": (
                    "Crack geometry for SIF computation. "
                    "SENT: single-edge notched tension; "
                    "central_crack: through crack in wide plate; "
                    "CT: compact tension (requires P_delta_n)."
                ),
            },
            "a_0_m": {
                "type": "number",
                "description": "Initial crack length a_0 [m].",
            },
            "plate_width_m": {
                "type": "number",
                "description": "Plate width W [m] (used for geometry factor).",
            },
            "plate_thickness_m": {
                "type": "number",
                "description": "Plate thickness B [m] (CT specimen only).",
            },
            "P_delta_n": {
                "type": "number",
                "description": "Load range ΔP [N] for CT specimen.",
            },
            # Integration control
            "N_max": {
                "type": "number",
                "description": "Maximum cycles to integrate (default 1e7).",
            },
            "n_output_points": {
                "type": "integer",
                "description": "Number of (a, N) points in output (default 100).",
            },
            # Mixed-mode kink angle
            "K_I_pa_sqrt_m": {
                "type": "number",
                "description": (
                    "Mode-I SIF K_I [Pa√m] for kink-angle computation. "
                    "If provided together with K_II, returns Erdogan-Sih kink angle θ_c."
                ),
            },
            "K_II_pa_sqrt_m": {
                "type": "number",
                "description": "Mode-II SIF K_II [Pa√m] for kink-angle computation.",
            },
        },
        "required": ["C", "m", "K_Ic_pa_sqrt_m", "delta_sigma_pa", "geometry", "a_0_m", "plate_width_m"],
    },
)


@register(_fem_crack_growth_spec)
async def run_fem_crack_growth(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    required = ["C", "m", "K_Ic_pa_sqrt_m", "delta_sigma_pa", "geometry", "a_0_m", "plate_width_m"]
    for key in required:
        if a.get(key) is None:
            return err_payload(f"{key} is required", "BAD_ARGS")

    from kerf_fem.fracture.crack_growth import (
        ParisLawParams,
        integrate_paris_law,
        paris_analytic_flat,
        paris_analytic_sent,
        sif_range_sent,
        sif_range_central_crack,
        sif_range_ct_specimen,
        kink_angle_erdogan_sih,
        effective_sif_mixed_mode,
        sigma_theta_theta,
    )

    try:
        C = float(a["C"])
        m = float(a["m"])
        K_Ic = float(a["K_Ic_pa_sqrt_m"])
        K_th = float(a.get("K_th_pa_sqrt_m", 0.0))
        R = float(a.get("R_ratio", 0.0))
        delta_sigma = float(a["delta_sigma_pa"])
        geometry = str(a["geometry"])
        a_0 = float(a["a_0_m"])
        W = float(a["plate_width_m"])
        N_max = float(a.get("N_max", 1e7))
        n_out = int(a.get("n_output_points", 100))
    except Exception as e:
        return err_payload(f"parameter error: {e}", "BAD_ARGS")

    if C <= 0:
        return err_payload("C must be positive", "BAD_ARGS")
    if m <= 0:
        return err_payload("m must be positive", "BAD_ARGS")
    if K_Ic <= 0:
        return err_payload("K_Ic_pa_sqrt_m must be positive", "BAD_ARGS")
    if a_0 <= 0:
        return err_payload("a_0_m must be positive", "BAD_ARGS")
    if W <= 0:
        return err_payload("plate_width_m must be positive", "BAD_ARGS")
    if a_0 >= W:
        return err_payload("a_0_m must be < plate_width_m", "BAD_ARGS")

    # Build SIF range function
    B = float(a.get("plate_thickness_m", 0.025))
    P_delta = float(a.get("P_delta_n", 0.0))

    if geometry == "SENT":
        def sif_fn(ai):
            return sif_range_sent(delta_sigma, ai, W)
    elif geometry == "central_crack":
        def sif_fn(ai):
            return sif_range_central_crack(delta_sigma, ai, W)
    elif geometry == "CT":
        if P_delta <= 0:
            return err_payload("CT geometry requires P_delta_n > 0", "BAD_ARGS")
        def sif_fn(ai):
            return sif_range_ct_specimen(delta_sigma, ai, W, B, P_delta)
    else:
        return err_payload(f"Unknown geometry: {geometry!r}", "BAD_ARGS")

    # Build params
    params = ParisLawParams(C=C, m=m, K_Ic=K_Ic, K_th=K_th, R_ratio=R)

    # Integrate Paris law
    try:
        store_every = max(1, int(1e6 / n_out))
        result = integrate_paris_law(
            params=params,
            sif_range_fn=sif_fn,
            a_0=a_0,
            N_max=N_max,
            store_every=store_every,
            max_steps=500_000,
            adaptive=True,
            da_max_fraction=0.005,
        )
    except Exception as e:
        return err_payload(f"Paris law integration failed: {e}", "COMPUTE_ERROR")

    # Sub-sample to n_out points
    total = len(result.cycles)
    if total > n_out:
        idx = np.linspace(0, total - 1, n_out, dtype=int)
        a_out = result.crack_lengths_m[idx].tolist()
        N_out = result.cycles[idx].tolist()
    else:
        a_out = result.crack_lengths_m.tolist()
        N_out = result.cycles.tolist()

    resp = {
        "a_vs_N": {
            "crack_length_m": a_out,
            "cycles": N_out,
        },
        "N_final": result.N_final,
        "a_final_m": result.a_final,
        "stop_reason": result.stop_reason,
        "converged": result.converged,
        "paris_params": {
            "C": C, "m": m, "K_Ic_pa_sqrt_m": K_Ic,
            "K_th_pa_sqrt_m": K_th, "R_ratio": R,
        },
        "delta_K_at_a0_pa_sqrt_m": float(sif_fn(a_0)),
        "da_dN_at_a0_m_per_cycle": float(C * sif_fn(a_0)**m),
        "geometry": geometry,
    }

    # Analytic oracle for SENT (constant-geometry approximation)
    if geometry == "SENT" and result.a_final > a_0:
        try:
            N_analytic = paris_analytic_sent(C, m, delta_sigma, W, a_0, result.a_final)
            resp["N_analytic_sent_oracle"] = N_analytic
            if N_analytic > 0 and result.N_final > 0:
                resp["relative_error_vs_analytic"] = abs(result.N_final - N_analytic) / N_analytic
        except Exception:
            pass

    # Constant-ΔK oracle (no geometry factor)
    dK0 = float(sif_fn(a_0))
    a_crit = (K_Ic / (delta_sigma * math.sqrt(math.pi)))**2  # rough a_crit without correction
    a_crit = min(a_crit, 0.9 * W)
    if a_crit > a_0 and C * dK0**m > 0:
        try:
            N_flat = paris_analytic_flat(C, m, dK0, a_0, a_crit)
            resp["N_flat_oracle_constant_dK"] = N_flat
        except Exception:
            pass

    if result.warnings:
        resp["warnings"] = result.warnings

    # Mixed-mode kink angle (Erdogan-Sih 1963)
    K_I = a.get("K_I_pa_sqrt_m")
    K_II = a.get("K_II_pa_sqrt_m")
    if K_I is not None and K_II is not None:
        try:
            K_I = float(K_I)
            K_II = float(K_II)
            theta_c = kink_angle_erdogan_sih(K_I, K_II)
            K_eff = effective_sif_mixed_mode(K_I, K_II)

            # σ_θθ profile ±π
            angles = np.linspace(-math.pi + 0.01, math.pi - 0.01, 181)
            stt = [sigma_theta_theta(K_I, K_II, th) for th in angles]

            resp["mixed_mode"] = {
                "K_I_pa_sqrt_m": K_I,
                "K_II_pa_sqrt_m": K_II,
                "kink_angle_rad": theta_c,
                "kink_angle_deg": math.degrees(theta_c),
                "K_eff_pa_sqrt_m": K_eff,
                "mode_mixity_K_II_over_K_I": K_II / K_I if abs(K_I) > 1e-30 else float("inf"),
                "sigma_theta_theta_profile": {
                    "angles_rad": angles.tolist(),
                    "sigma_times_sqrt_r": stt,
                },
            }
        except Exception as e:
            resp["mixed_mode_error"] = str(e)

    resp["notes"] = (
        "Paris law da/dN = C·ΔK^m integrated with 4th-order Runge-Kutta. "
        f"Geometry: {geometry}. Stop: {result.stop_reason}. "
        "XFEM caveat: SIF from geometry-factor formula, NOT XFEM enrichment. "
        "Full XFEM (Moës-Dolbow-Belytschko 1999) is deferred to T-100-C. "
        "Mixed-mode kink: Erdogan-Sih (1963) max hoop-stress criterion. "
        "References: Paris & Erdogan (1963) J. Basic Eng. 85:528; "
        "Erdogan & Sih (1963) J. Basic Eng. 85:519; Anderson (2005) Ch. 10."
    )
    return ok_payload(resp)


# TOOLS list for plugin.py
TOOLS = [
    ("fem_crack_growth", _fem_crack_growth_spec, run_fem_crack_growth),
]
