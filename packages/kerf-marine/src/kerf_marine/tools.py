"""
kerf_marine LLM tools — hydrostatics + stability + seakeeping for the chat agent.

Tools
-----
marine_hydrostatics     Compute displacement, KB, BM, GM, TPC, MCT1cm from offsets
marine_stability_gz     Compute GZ righting arm curve (wall-sided or KN table)
marine_box_barge        Quick analytic box-barge hydrostatics (no offset table needed)
marine_seakeeping_rao   Compute heave/pitch/roll RAOs via strip theory (STF)
marine_seakeeping_stats Compute significant motion amplitudes in irregular seas
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_marine._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# marine_hydrostatics
# ---------------------------------------------------------------------------

marine_hydrostatics_spec = ToolSpec(
    name="marine_hydrostatics",
    description=(
        "Compute full hydrostatic properties for a ship hull from an offsets table. "
        "Returns displacement (tonnes), LCB, KB, BM (transverse and longitudinal), "
        "KM, waterplane area, TPC (tonnes per cm immersion), MCT1cm, and LCF. "
        "\n\nOffsets table format: list of [station_m, waterline_m, half_breadth_m] rows. "
        "Stations run from aft (0) to forward. Waterlines run from 0 (keel) to draft. "
        "Half-breadths are half the beam at each (station, waterline) point. "
        "\n\nFor a box barge the analytic formulas hold: "
        "displacement = rho·L·B·T, KB = T/2, BM = B²/(12T)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "offsets": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "List of [station_m, waterline_m, half_breadth_m] rows.",
            },
            "draft": {
                "type": "number",
                "description": "Waterline draft (m).",
            },
            "rho": {
                "type": "number",
                "description": "Water density t/m³. Default 1.025 (sea water).",
            },
            "kg": {
                "type": "number",
                "description": "Vertical centre of gravity above keel KG (m). Default 0.",
            },
            "method": {
                "type": "string",
                "enum": ["simpson", "trapz"],
                "description": "Integration method. Default 'simpson'.",
            },
        },
        "required": ["offsets", "draft"],
    },
)


async def run_marine_hydrostatics(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_marine.sections import OffsetTable
        from kerf_marine.hydrostatics import compute_hydrostatics, RHO_SW

        offsets = args["offsets"]
        draft = float(args["draft"])
        rho = float(args.get("rho", RHO_SW))
        kg = float(args.get("kg", 0.0))
        method = str(args.get("method", "simpson"))

        table = OffsetTable()
        for row in offsets:
            station, wl, hb = float(row[0]), float(row[1]), float(row[2])
            table.add(station, wl, hb)

        ht = compute_hydrostatics(table, draft, rho=rho, kg=kg, method=method)
        return ok_payload(ht.as_dict())
    except Exception as exc:
        return err_payload(str(exc), "MARINE_HYDROSTATICS_ERROR")


# ---------------------------------------------------------------------------
# marine_box_barge
# ---------------------------------------------------------------------------

marine_box_barge_spec = ToolSpec(
    name="marine_box_barge",
    description=(
        "Compute analytic hydrostatics for a rectangular box barge. "
        "No offset table required — uses exact closed-form formulas: "
        "displacement = rho·L·B·T, KB = T/2, BM = B²/(12T). "
        "Also returns TPC, MCT1cm, waterplane area, LCB, LCF (all at midship)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "length": {
                "type": "number",
                "description": "Length between perpendiculars (m).",
            },
            "beam": {
                "type": "number",
                "description": "Full beam (m).",
            },
            "draft": {
                "type": "number",
                "description": "Even-keel draft (m).",
            },
            "rho": {
                "type": "number",
                "description": "Water density t/m³. Default 1.025 (sea water).",
            },
            "kg": {
                "type": "number",
                "description": "KG above keel (m). Default 0.",
            },
        },
        "required": ["length", "beam", "draft"],
    },
)


async def run_marine_box_barge(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_marine.hydrostatics import box_barge_hydrostatics, RHO_SW

        L = float(args["length"])
        B = float(args["beam"])
        T = float(args["draft"])
        rho = float(args.get("rho", RHO_SW))
        kg = float(args.get("kg", 0.0))

        ht = box_barge_hydrostatics(L, B, T, rho=rho, kg=kg)
        return ok_payload(ht.as_dict())
    except Exception as exc:
        return err_payload(str(exc), "MARINE_BOX_BARGE_ERROR")


# ---------------------------------------------------------------------------
# marine_stability_gz
# ---------------------------------------------------------------------------

marine_stability_gz_spec = ToolSpec(
    name="marine_stability_gz",
    description=(
        "Compute the GZ righting arm curve and intact stability criteria. "
        "Two modes: "
        "\n1. Wall-sided formula (provide gm and bm): "
        "   GZ(φ) = sin(φ)·(GM + ½·BM·tan²(φ)). "
        "\n2. KN table (provide kn_angles, kn_values, kg): "
        "   GZ(φ) = KN(φ) − KG·sin(φ). "
        "\n\nReturns GZ curve points, vanishing angle, area 0–30°, area 0–40°, "
        "area 30–40°, max GZ, and IMO A.749 criteria pass/fail flags."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gm": {
                "type": "number",
                "description": "Initial metacentric height GM (m). Required for wall-sided mode.",
            },
            "bm": {
                "type": "number",
                "description": "Transverse metacentric radius BM (m). Required for wall-sided mode.",
            },
            "kn_angles": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Heel angles (°) for KN cross-curve table.",
            },
            "kn_values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "KN lever values (m) at each angle.",
            },
            "kg": {
                "type": "number",
                "description": "KG (m) — required for KN-table mode.",
            },
            "angle_step": {
                "type": "number",
                "description": "Step size for GZ evaluation (°). Default 5.",
            },
            "max_angle": {
                "type": "number",
                "description": "Maximum heel angle to evaluate (°). Default 90.",
            },
        },
    },
)


async def run_marine_stability_gz(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_marine.stability import (
            gz_curve_wall_sided, gz_curve_from_kn,
        )

        angle_step = float(args.get("angle_step", 5.0))
        max_angle = float(args.get("max_angle", 90.0))

        if "kn_angles" in args and "kn_values" in args:
            kn_angles = [float(a) for a in args["kn_angles"]]
            kn_values = [float(v) for v in args["kn_values"]]
            kg = float(args.get("kg", 0.0))
            curve = gz_curve_from_kn(kn_angles, kn_values, kg)
        elif "gm" in args and "bm" in args:
            gm = float(args["gm"])
            bm = float(args["bm"])
            curve = gz_curve_wall_sided(
                gm, bm,
                angle_step_deg=angle_step,
                max_angle_deg=max_angle,
            )
        else:
            return err_payload(
                "Provide either (gm, bm) for wall-sided or "
                "(kn_angles, kn_values, kg) for KN-table mode.",
                "MARINE_GZ_BAD_ARGS",
            )

        payload = curve.as_dict()
        payload["imo_criteria"] = curve.imo_criteria()
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "MARINE_GZ_ERROR")


# ---------------------------------------------------------------------------
# marine_seakeeping_rao
# ---------------------------------------------------------------------------

marine_seakeeping_rao_spec = ToolSpec(
    name="marine_seakeeping_rao",
    description=(
        "Compute heave, pitch, and roll Response Amplitude Operators (RAOs) "
        "using Salvesen-Tuck-Faltinsen (STF) strip theory with Lewis-form sections. "
        "\n\n"
        "Provide hull sections as a list of [x_m, B_wl_m, T_s_m, A_s_m2] rows "
        "(longitudinal position from aft, full waterline beam, local draft, section area). "
        "Alternatively supply a Wigley hull via wigley_L/B/T parameters. "
        "\n\n"
        "Returns RAO amplitude and phase at each wave frequency for heave (m/m), "
        "pitch (rad/m), and roll (rad/m). "
        "\n\n"
        "Approximations: Diffraction uses Haskind relation at zero speed (O(Fn) error). "
        "Roll includes viscous damping fraction (default 5 % of critical)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "description": "List of [x_m, B_wl_m, T_s_m, A_s_m2] strip rows (aft to fwd).",
            },
            "wigley_L": {"type": "number", "description": "Wigley hull length (m) — alternative to sections."},
            "wigley_B": {"type": "number", "description": "Wigley hull beam (m)."},
            "wigley_T": {"type": "number", "description": "Wigley hull draft (m)."},
            "wigley_n": {"type": "integer", "description": "Number of Wigley sections (default 21)."},
            "displacement": {"type": "number", "description": "Ship displacement / mass (t)."},
            "kyy": {"type": "number", "description": "Pitch radius of gyration (m). Default 0.25*L."},
            "kxx": {"type": "number", "description": "Roll radius of gyration (m). Default 0.35*B."},
            "lcg": {"type": "number", "description": "LCG from aft (m). Default midship."},
            "kg": {"type": "number", "description": "KG above keel (m). Default T/2."},
            "gm_transverse": {"type": "number", "description": "GM transverse (m). Default 1.0."},
            "gm_longitudinal": {"type": "number", "description": "GML longitudinal (m). Default 100."},
            "U": {"type": "number", "description": "Forward speed (m/s). Default 0."},
            "mu_deg": {"type": "number", "description": "Heading (°): 180=head, 90=beam, 0=following. Default 180."},
            "omega_list": {
                "type": "array", "items": {"type": "number"},
                "description": "List of wave frequencies (rad/s) to evaluate. Default: 0.2–2.5 in 20 steps.",
            },
            "roll_damping_fraction": {"type": "number", "description": "Viscous roll damping fraction (0–0.3). Default 0.05."},
            "rho": {"type": "number", "description": "Water density t/m³. Default 1.025."},
        },
    },
)


async def run_marine_seakeeping_rao(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import math
        from kerf_marine.seakeeping import (
            HullSection, compute_rao, wigley_hull_sections,
        )
        from kerf_marine.hydrostatics import RHO_SW

        rho = float(args.get("rho", RHO_SW))

        # Build sections
        if "sections" in args:
            raw = args["sections"]
            sections = [HullSection(x=float(r[0]), B_wl=float(r[1]), T_s=float(r[2]), A_s=float(r[3])) for r in raw]
        elif "wigley_L" in args and "wigley_B" in args and "wigley_T" in args:
            L = float(args["wigley_L"])
            B = float(args["wigley_B"])
            T = float(args["wigley_T"])
            n = int(args.get("wigley_n", 21))
            sections = wigley_hull_sections(L, B, T, n)
        else:
            return err_payload("Provide 'sections' list or wigley_L/B/T parameters.", "MARINE_RAO_BAD_ARGS")

        if not sections:
            return err_payload("No hull sections provided.", "MARINE_RAO_BAD_ARGS")

        L_hull = sections[-1].x - sections[0].x or 1.0
        mid = (sections[0].x + sections[-1].x) / 2.0
        B_mid = sections[len(sections) // 2].B_wl
        T_typ = sections[len(sections) // 2].T_s

        displacement = float(args.get("displacement", rho * L_hull * B_mid * T_typ * 0.67))
        kyy = float(args.get("kyy", 0.25 * L_hull))
        kxx = float(args.get("kxx", 0.35 * B_mid))
        lcg = float(args.get("lcg", mid))
        kg = float(args.get("kg", T_typ / 2.0))
        gm_transverse = float(args.get("gm_transverse", 1.0))
        gm_longitudinal = float(args.get("gm_longitudinal", 100.0))
        U = float(args.get("U", 0.0))
        mu_deg = float(args.get("mu_deg", 180.0))
        roll_damp = float(args.get("roll_damping_fraction", 0.05))

        if "omega_list" in args:
            omegas = [float(o) for o in args["omega_list"]]
        else:
            omegas = [0.2 + i * (2.5 - 0.2) / 19 for i in range(20)]

        results = []
        for om in omegas:
            r = compute_rao(
                sections, om, displacement, kyy, kxx, lcg, kg,
                gm_transverse, gm_longitudinal,
                U=U, mu_deg=mu_deg,
                roll_damping_fraction=roll_damp,
                rho=rho,
            )
            results.append(r.as_dict())

        return ok_payload({"rao_points": results, "n_sections": len(sections), "L_m": round(L_hull, 3)})
    except Exception as exc:
        return err_payload(str(exc), "MARINE_RAO_ERROR")


# ---------------------------------------------------------------------------
# marine_seakeeping_stats
# ---------------------------------------------------------------------------

marine_seakeeping_stats_spec = ToolSpec(
    name="marine_seakeeping_stats",
    description=(
        "Compute significant heave, pitch, and roll amplitudes in irregular seas "
        "using STF strip theory + JONSWAP or Pierson-Moskowitz spectrum. "
        "\n\n"
        "Returns spectral moments m0/m2, significant amplitude (2√m0), "
        "mean zero-crossing period, and most probable maximum in 100 wave cycles. "
        "\n\n"
        "Same hull input as marine_seakeeping_rao."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "description": "List of [x_m, B_wl_m, T_s_m, A_s_m2] rows.",
            },
            "wigley_L": {"type": "number"},
            "wigley_B": {"type": "number"},
            "wigley_T": {"type": "number"},
            "wigley_n": {"type": "integer"},
            "displacement": {"type": "number", "description": "Ship mass (t)."},
            "kyy": {"type": "number"},
            "kxx": {"type": "number"},
            "lcg": {"type": "number"},
            "kg": {"type": "number"},
            "gm_transverse": {"type": "number"},
            "gm_longitudinal": {"type": "number"},
            "Hs": {"type": "number", "description": "Significant wave height (m)."},
            "Tp": {"type": "number", "description": "Peak wave period (s)."},
            "U": {"type": "number", "description": "Forward speed (m/s). Default 0."},
            "mu_deg": {"type": "number", "description": "Heading (°). Default 180."},
            "spectrum": {"type": "string", "enum": ["jonswap", "pm"], "description": "Wave spectrum type. Default jonswap."},
            "gamma": {"type": "number", "description": "JONSWAP peak factor. Default 3.3."},
            "omega_min": {"type": "number", "description": "Min frequency (rad/s). Default 0.1."},
            "omega_max": {"type": "number", "description": "Max frequency (rad/s). Default 3.0."},
            "n_omega": {"type": "integer", "description": "Number of frequency points. Default 60."},
            "roll_damping_fraction": {"type": "number"},
            "rho": {"type": "number"},
        },
        "required": ["Hs", "Tp"],
    },
)


async def run_marine_seakeeping_stats(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_marine.seakeeping import (
            HullSection, compute_response_statistics, wigley_hull_sections,
        )
        from kerf_marine.hydrostatics import RHO_SW

        rho = float(args.get("rho", RHO_SW))

        if "sections" in args:
            raw = args["sections"]
            sections = [HullSection(x=float(r[0]), B_wl=float(r[1]), T_s=float(r[2]), A_s=float(r[3])) for r in raw]
        elif "wigley_L" in args and "wigley_B" in args and "wigley_T" in args:
            L = float(args["wigley_L"])
            B = float(args["wigley_B"])
            T = float(args["wigley_T"])
            n = int(args.get("wigley_n", 21))
            sections = wigley_hull_sections(L, B, T, n)
        else:
            return err_payload("Provide 'sections' or wigley_L/B/T.", "MARINE_STATS_BAD_ARGS")

        L_hull = sections[-1].x - sections[0].x or 1.0
        mid = (sections[0].x + sections[-1].x) / 2.0
        B_mid = sections[len(sections) // 2].B_wl
        T_typ = sections[len(sections) // 2].T_s

        displacement = float(args.get("displacement", rho * L_hull * B_mid * T_typ * 0.67))
        kyy = float(args.get("kyy", 0.25 * L_hull))
        kxx = float(args.get("kxx", 0.35 * B_mid))
        lcg = float(args.get("lcg", mid))
        kg = float(args.get("kg", T_typ / 2.0))
        gm_transverse = float(args.get("gm_transverse", 1.0))
        gm_longitudinal = float(args.get("gm_longitudinal", 100.0))
        Hs = float(args["Hs"])
        Tp = float(args["Tp"])
        U = float(args.get("U", 0.0))
        mu_deg = float(args.get("mu_deg", 180.0))
        spectrum = str(args.get("spectrum", "jonswap"))
        gamma = float(args.get("gamma", 3.3))
        omega_min = float(args.get("omega_min", 0.1))
        omega_max = float(args.get("omega_max", 3.0))
        n_omega = int(args.get("n_omega", 60))
        roll_damp = float(args.get("roll_damping_fraction", 0.05))

        stats = compute_response_statistics(
            sections, displacement, kyy, kxx, lcg, kg,
            gm_transverse, gm_longitudinal,
            Hs=Hs, Tp=Tp, U=U, mu_deg=mu_deg,
            spectrum=spectrum, gamma=gamma,
            omega_min=omega_min, omega_max=omega_max, n_omega=n_omega,
            roll_damping_fraction=roll_damp, rho=rho,
        )

        return ok_payload({
            "Hs_input_m": Hs, "Tp_input_s": Tp,
            "spectrum": spectrum,
            "motions": [s.as_dict() for s in stats],
        })
    except Exception as exc:
        return err_payload(str(exc), "MARINE_STATS_ERROR")
