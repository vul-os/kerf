"""
kerf_marine LLM tools — hydrostatics + stability + seakeeping + scantlings for the chat agent.

Tools
-----
marine_hydrostatics     Compute displacement, KB, BM, GM, TPC, MCT1cm from offsets
marine_stability_gz     Compute GZ righting arm curve (wall-sided or KN table)
marine_box_barge        Quick analytic box-barge hydrostatics (no offset table needed)
marine_seakeeping_rao   Compute heave/pitch/roll RAOs via strip theory (STF)
marine_seakeeping_stats Compute significant motion amplitudes in irregular seas
marine_scantlings       ISO 12215-5 hull construction scantlings determination
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


# ---------------------------------------------------------------------------
# marine_scantlings  (ISO 12215-5)
# ---------------------------------------------------------------------------

marine_scantlings_spec = ToolSpec(
    name="marine_scantlings",
    description=(
        "ISO 12215-5:2008 hull construction scantlings for small craft (2.5–24 m). "
        "\n\n"
        "Computes: (1) design pressures for bottom / side / deck panels; "
        "(2) minimum plate thickness for FRP, aluminium, or steel; "
        "(3) minimum stiffener section modulus; "
        "(4) optional longitudinal hull-girder strength check (Msw + Mwave vs SM). "
        "\n\n"
        "Design categories: A (ocean), B (offshore), C (inshore), D (sheltered). "
        "Motor-craft uses dynamic acceleration nCG (V, deadrise). Sailing craft sets Pbm=0. "
        "\n\n"
        "Materials: 'frp_eglass' (E-glass/polyester), 'frp_epoxy' (E-glass/epoxy), "
        "'al5083' (Al 5083-H116), 'al6061' (Al 6061-T6), 'steel_s235', 'steel_s355'. "
        "\n\n"
        "Reference: ISO 12215-5:2008 §8 (pressures), §11.4 (plating), §11.5 (stiffeners), "
        "§12 + Annex C (longitudinal strength). "
        "Larsson & Eliasson 'Principles of Yacht Design' §11."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "LWL":     {"type": "number", "description": "Waterline length (m)."},
            "BWL":     {"type": "number", "description": "Waterline beam (m)."},
            "mLDC":    {"type": "number", "description": "Loaded displacement mass (kg)."},
            "V":       {"type": "number", "description": "Maximum speed in calm water (kn). Use 0 for sailing craft."},
            "beta_04": {"type": "number", "description": "Deadrise angle at 0.4*LWL (°). Default 20."},
            "b_mm":    {"type": "number", "description": "Panel short side (mm)."},
            "l_mm":    {"type": "number", "description": "Panel long side (mm)."},
            "lu_mm":   {"type": "number", "description": "Stiffener unsupported span (mm)."},
            "s_mm":    {"type": "number", "description": "Stiffener spacing (mm)."},
            "material": {
                "type": "string",
                "enum": ["frp_eglass", "frp_epoxy", "al5083", "al6061", "steel_s235", "steel_s355"],
                "description": "Hull material.",
            },
            "category": {
                "type": "string",
                "enum": ["A", "B", "C", "D"],
                "description": "ISO 12215-5 design category. Default 'A'.",
            },
            "zone": {
                "type": "string",
                "enum": ["bottom", "side", "deck"],
                "description": "Hull zone for panel. Default 'bottom'.",
            },
            "is_sailing": {"type": "boolean", "description": "True for sailing craft. Default false."},
            "z_mm":       {"type": "number", "description": "Panel crown / camber height (mm). Default 0."},
            "Cb":         {"type": "number", "description": "Block coefficient (0–1). Default 0.6."},
            # Hull section for longitudinal check (optional)
            "section_A_deck":  {"type": "number", "description": "Hull section deck area (m²)."},
            "section_A_keel":  {"type": "number", "description": "Hull section keel area (m²)."},
            "section_d":       {"type": "number", "description": "Hull depth keel-to-deck (m)."},
            "section_A_side":  {"type": "number", "description": "Side shell area per side (m²)."},
            "section_d_mid":   {"type": "number", "description": "Side centroid above keel (m)."},
        },
        "required": ["LWL", "BWL", "mLDC", "b_mm", "l_mm", "lu_mm", "s_mm", "material"],
    },
)

_MATERIAL_MAP = {
    "frp_eglass": "MATERIAL_E_GLASS_FRP",
    "frp_epoxy":  "MATERIAL_E_GLASS_EPOXY",
    "al5083":     "MATERIAL_AL5083",
    "al6061":     "MATERIAL_AL6061T6",
    "steel_s235": "MATERIAL_STEEL_S235",
    "steel_s355": "MATERIAL_STEEL_S355",
}


# ---------------------------------------------------------------------------
# marine_vpp
# ---------------------------------------------------------------------------

marine_vpp_spec = ToolSpec(
    name="marine_vpp",
    description=(
        "Velocity Prediction Programme (VPP) for sailing vessels — "
        "Kerwin-Larsson aero/hydrodynamic force balance following the ORC/IMS framework.  "
        "Sweeps true wind speed (TWS) and true wind angle (TWA) to produce a speed polar.  "
        "Uses ITTC 1957 friction, Delft Series residuary resistance (Keuning & Sonnenberg 1998), "
        "and an empirical sail-force model.  "
        "Returns boat speed, heel angle, and drive force at each (TWS, TWA) combination."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "L_wl": {"type": "number", "description": "Waterline length (m)."},
            "B_wl": {"type": "number", "description": "Waterline beam (m)."},
            "T_c":  {"type": "number", "description": "Canoe body draught (m) — hull depth excluding fin keel."},
            "T_keel": {"type": "number", "description": "Total draught including keel (m)."},
            "displacement_t": {"type": "number", "description": "Displacement (metric tonnes). Default 5.0."},
            "Cm": {"type": "number", "description": "Midship section coefficient. Default 0.65."},
            "Cp": {"type": "number", "description": "Prismatic coefficient. Default 0.565."},
            "sail_area_m2": {"type": "number", "description": "Total upwind sail area (m²). Default 60."},
            "centre_of_effort_m": {"type": "number", "description": "Centre of effort height above waterline (m). Default 7."},
            "tws_knots": {
                "type": "array",
                "items": {"type": "number"},
                "description": "True wind speeds to sweep (knots). Default [8, 12, 16].",
            },
            "twa_deg_list": {
                "type": "array",
                "items": {"type": "number"},
                "description": "True wind angles to sweep (degrees). Default standard 45-180.",
            },
            "hull_name": {"type": "string", "description": "Vessel label for output. Default 'vessel'."},
        },
        "required": ["L_wl", "B_wl", "T_c", "T_keel"],
    },
)


async def run_marine_vpp(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_marine.vpp import HullData, generate_polar, VPPPoint

        hull = HullData(
            L_wl=float(args["L_wl"]),
            B_wl=float(args["B_wl"]),
            T_c=float(args["T_c"]),
            T_keel=float(args["T_keel"]),
            displacement_t=float(args.get("displacement_t", 5.0)),
            Cm=float(args.get("Cm", 0.65)),
            Cp=float(args.get("Cp", 0.565)),
            sail_area_m2=float(args.get("sail_area_m2", 60.0)),
            centre_of_effort_m=float(args.get("centre_of_effort_m", 7.0)),
        )

        tws_knots = [float(v) for v in args.get("tws_knots", [8.0, 12.0, 16.0])]
        twa_list = [float(v) for v in args["twa_deg_list"]] if "twa_deg_list" in args else None
        hull_name = str(args.get("hull_name", "vessel"))

        polar = generate_polar(hull, tws_knots=tws_knots, twa_deg_list=twa_list, hull_name=hull_name)

        # Summarise points
        points_summary = [
            {
                "tws_kn": round(p.tws * 1.944, 2),
                "twa_deg": round(p.twa_deg, 1),
                "boat_speed_kn": round(p.boat_speed * 1.944, 3),
                "heel_deg": round(p.heel_deg, 2),
            }
            for p in polar.points
        ]

        payload: dict[str, Any] = {
            "ok": True,
            "hull_name": polar.hull_name,
            "n_tws": len(tws_knots),
            "n_twa": len(polar.twa_deg_list),
            "n_points": len(polar.points),
            "tws_knots": tws_knots,
            "twa_deg_list": polar.twa_deg_list,
            "polar_points": points_summary,
            "warnings": polar.warnings,
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "MARINE_VPP_ERROR")


# ---------------------------------------------------------------------------
# marine_scantling_check  (ISO 12215-5 + ABS Steel Vessels + DNV)
# ---------------------------------------------------------------------------

marine_scantling_check_spec = ToolSpec(
    name="marine_scantling_check",
    description=(
        "Hull structural scantling rule checks (PASS/FAIL + utilisation) against "
        "one or more published class-society rule sets:\n"
        "  • ISO 12215-5:2008  — small craft (2.5–24 m), any material\n"
        "  • ABS Rules for Building and Classing Steel Vessels (2024) Pt.3 Ch.2 §3 "
        "— local shell-plating and stiffener scantlings (hydrostatic pressure + wave)\n"
        "  • DNV Rules for Classification of Ships (July 2023) Pt.3 Ch.1 Sec.7 "
        "— local plate/stiffener scantlings (slamming + hydrostatic pressure)\n\n"
        "Implements the published open-formula skeleton of each rule: design pressures "
        "(hydrostatic head, dynamic/slamming), plate-thickness equations, and stiffener "
        "section-modulus equations. Cites the specific rule clause in every output.\n\n"
        "HONEST SCOPE: These are the published engineering formulae, not the full "
        "proprietary rule suites (Lloyd's full rule, BV NR 467, ABS DLA, DNV fatigue) "
        "which require licensed class-society rule-tree software.\n\n"
        "For each requested rule_set the tool returns:\n"
        "  - Design pressure used (kPa) with cited formula\n"
        "  - Required plate thickness (mm) + PASS/FAIL vs t_actual_mm\n"
        "  - Required stiffener section modulus (cm³) + PASS/FAIL vs SM_actual_cm3\n"
        "  - Utilisation ratios (required / actual; ≤ 1.0 = pass)\n"
        "  - Cited rule clause string\n\n"
        "Materials: 'frp_eglass', 'frp_epoxy', 'al5083', 'al6061', 'steel_s235', 'steel_s355'.\n"
        "Rule sets (rule_sets array): 'iso', 'abs', 'dnv'. Any combination allowed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            # Panel geometry
            "b_mm":  {"type": "number", "description": "Panel short side / plate spacing (mm)."},
            "l_mm":  {"type": "number", "description": "Panel long side (mm)."},
            "lu_mm": {"type": "number", "description": "Stiffener unsupported span (mm)."},
            "s_mm":  {"type": "number", "description": "Stiffener spacing (mm)."},
            "material": {
                "type": "string",
                "enum": ["frp_eglass", "frp_epoxy", "al5083", "al6061", "steel_s235", "steel_s355"],
                "description": "Hull material.",
            },
            "rule_sets": {
                "type": "array",
                "items": {"type": "string", "enum": ["iso", "abs", "dnv"]},
                "description": "Rule sets to check. Any of: 'iso' (ISO 12215-5), 'abs' (ABS Steel Vessels), 'dnv' (DNV Ships). Default ['iso'].",
            },
            "zone": {
                "type": "string",
                "enum": ["bottom", "side", "deck", "bulkhead"],
                "description": "Hull zone. Default 'bottom'.",
            },
            # ISO 12215-5 inputs
            "LWL":       {"type": "number", "description": "Waterline length (m). Required for ISO rule."},
            "BWL":       {"type": "number", "description": "Waterline beam (m). Required for ISO rule."},
            "mLDC":      {"type": "number", "description": "Loaded displacement mass (kg). Required for ISO rule."},
            "V":         {"type": "number", "description": "Max speed (kn). Required for ISO motor-craft."},
            "beta_04":   {"type": "number", "description": "Deadrise at 0.4*LWL (°). Default 20."},
            "category":  {"type": "string", "enum": ["A", "B", "C", "D"], "description": "ISO design category (A=ocean .. D=sheltered). Default 'A'."},
            "z_mm":      {"type": "number", "description": "Panel crown/camber height (mm). Default 0."},
            "is_sailing":{"type": "boolean", "description": "True for sailing craft (ISO rule). Default false."},
            # ABS / DNV inputs
            "h_panel_m": {"type": "number", "description": "Hydrostatic head — depth below waterline to panel centre (m). E.g. draft for keel, 0 for weather deck."},
            "V_kn":      {"type": "number", "description": "Design speed (kn) for DNV slamming pressure. Default 0."},
            "Cw":        {"type": "number", "description": "ABS wave correction coefficient (kPa). Default 0 (sheltered)."},
            "draft_m":   {"type": "number", "description": "Vessel draft (m). Default 2.0."},
            # Actual scantlings for PASS/FAIL
            "t_actual_mm":   {"type": "number", "description": "Provided plate thickness (mm). If omitted, required thickness is returned but no PASS/FAIL."},
            "SM_actual_cm3": {"type": "number", "description": "Provided stiffener section modulus (cm³). If omitted, required SM is returned but no PASS/FAIL."},
            "both_ends_fixed":{"type": "boolean", "description": "True → fixed-end stiffener (C=1/12); False → pin-pin (C=1/8). Default true."},
        },
        "required": ["b_mm", "l_mm", "lu_mm", "s_mm", "material"],
    },
)


async def run_marine_scantling_check(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_marine.scantling_check import marine_scantling_check
        import kerf_marine.scantlings as sc

        b_mm  = float(args["b_mm"])
        l_mm  = float(args["l_mm"])
        lu_mm = float(args["lu_mm"])
        s_mm  = float(args["s_mm"])
        z_mm  = float(args.get("z_mm", 0.0))

        mat_key  = args.get("material", "al5083")
        mat_attr = _MATERIAL_MAP.get(mat_key, "MATERIAL_AL5083")
        material = getattr(sc, mat_attr)

        rule_sets = list(args.get("rule_sets", ["iso"]))
        zone      = str(args.get("zone", "bottom"))

        # ISO inputs
        LWL    = float(args.get("LWL",    10.0))
        BWL    = float(args.get("BWL",    3.0))
        mLDC   = float(args.get("mLDC",   5000.0))
        V      = float(args.get("V",      15.0))
        beta   = float(args.get("beta_04", 20.0))
        cat_str = str(args.get("category", "A")).upper()
        category = sc.DesignCategory(cat_str)
        is_sailing = bool(args.get("is_sailing", False))

        # ABS / DNV inputs
        h_panel_m = float(args.get("h_panel_m", 1.5))
        V_kn      = float(args.get("V_kn", 0.0))
        Cw        = float(args.get("Cw", 0.0))
        draft_m   = float(args.get("draft_m", 2.0))

        # Actual scantlings
        t_actual    = float(args["t_actual_mm"])   if "t_actual_mm"   in args else None
        SM_actual   = float(args["SM_actual_cm3"]) if "SM_actual_cm3" in args else None
        fixed       = bool(args.get("both_ends_fixed", True))

        multi = marine_scantling_check(
            b_mm=b_mm, l_mm=l_mm, lu_mm=lu_mm, s_mm=s_mm,
            material=material, rule_sets=rule_sets, zone=zone,
            LWL=LWL, BWL=BWL, mLDC=mLDC, V=V, beta_04=beta,
            category=category, z_mm=z_mm, is_sailing=is_sailing,
            h_panel_m=h_panel_m, V_kn=V_kn, Cw=Cw, draft_m=draft_m,
            t_actual_mm=t_actual, SM_actual_cm3=SM_actual,
            both_ends_fixed=fixed,
        )
        return ok_payload(multi.as_dict())
    except Exception as exc:
        return err_payload(str(exc), "MARINE_SCANTLING_CHECK_ERROR")


async def run_marine_scantlings(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        import kerf_marine.scantlings as sc

        LWL    = float(args["LWL"])
        BWL    = float(args["BWL"])
        mLDC   = float(args["mLDC"])
        V      = float(args.get("V", 0.0))
        beta   = float(args.get("beta_04", 20.0))
        b_mm   = float(args["b_mm"])
        l_mm   = float(args["l_mm"])
        lu_mm  = float(args["lu_mm"])
        s_mm   = float(args["s_mm"])
        z_mm   = float(args.get("z_mm", 0.0))
        Cb     = float(args.get("Cb", 0.6))

        mat_key = args.get("material", "al5083")
        mat_attr = _MATERIAL_MAP.get(mat_key, "MATERIAL_AL5083")
        material = getattr(sc, mat_attr)

        cat_str = args.get("category", "A").upper()
        category = sc.DesignCategory(cat_str)

        zone       = str(args.get("zone", "bottom"))
        is_sailing = bool(args.get("is_sailing", False))

        # Optional hull section for longitudinal check
        section = None
        if all(k in args for k in ["section_A_deck", "section_A_keel", "section_d",
                                    "section_A_side", "section_d_mid"]):
            section = sc.HullSectionProps(
                A_deck=float(args["section_A_deck"]),
                A_keel=float(args["section_A_keel"]),
                d=float(args["section_d"]),
                A_side=float(args["section_A_side"]),
                d_mid=float(args["section_d_mid"]),
            )

        report = sc.scantlings_report(
            LWL=LWL, BWL=BWL, mLDC=mLDC, V=V, beta_04=beta,
            b_mm=b_mm, l_mm=l_mm, lu_mm=lu_mm, s_mm=s_mm,
            material=material, category=category,
            zone=zone, section=section, Cb=Cb, z_mm=z_mm,
            is_sailing=is_sailing,
        )
        return ok_payload(report.as_dict())
    except Exception as exc:
        return err_payload(str(exc), "MARINE_SCANTLINGS_ERROR")
