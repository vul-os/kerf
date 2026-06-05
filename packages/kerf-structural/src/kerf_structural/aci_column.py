"""
ACI 318-19 Rectangular Column Design — Axial + P-M Interaction.

Provides two LLM-callable tools:

  structural_aci_column_axial
      ACI 318-19 §22.4.2 — short tied/spiral column maximum axial capacity.
      Returns φPn for LRFD; applies 0.80 (tied) or 0.85 (spiral) reduction.

  structural_aci_column_pm
      ACI 318-19 uniaxial P-M interaction diagram for a rectangular column.
      Sweeps from pure compression (c→∞) to pure flexure (c→c_bal),
      returning (Pu, Mu) pairs with φ applied (LRFD).

Units: US customary — kips, inches, kip-in, psi.

References
----------
ACI 318-19 §22.4.2   (max. axial strength).
ACI 318-19 §22.2.2   (equivalent stress-block depth β₁).
ACI 318-19 §21.2     (ductility-controlled φ factors).
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_structural._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx


# ---------------------------------------------------------------------------
# structural_aci_column_axial
# ---------------------------------------------------------------------------

aci_column_axial_spec = ToolSpec(
    name="structural_aci_column_axial",
    description=(
        "ACI 318-19 §22.4.2 — short rectangular tied/spiral column maximum "
        "design axial capacity φPn.\n"
        "\n"
        "Pn,max = 0.85·f'c·(Ag - Ast) + fy·Ast\n"
        "φ = 0.65 (tied columns, ACI §21.2.2) or φ = 0.75 (spiral).\n"
        "Applied reduction: φPn,max = φ × 0.80Pn (tied) or φ × 0.85Pn (spiral).\n"
        "\n"
        "Returns Pn, φPn, Ast, ρg, and whether Pu ≤ φPn.\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b":           {"type": "number", "description": "Column width (in)"},
            "h":           {"type": "number", "description": "Column depth (in)"},
            "Ast":         {"type": "number", "description": "Total longitudinal steel area (in²)"},
            "fc":          {"type": "number", "description": "f'c (psi), default 4000"},
            "fy":          {"type": "number", "description": "fy (psi), default 60000"},
            "column_type": {"type": "string", "description": "'tied' or 'spiral', default 'tied'"},
            "Pu":          {"type": "number", "description": "Factored axial demand (kips), default 0"},
        },
        "required": ["b", "h", "Ast"],
    },
)


@register(aci_column_axial_spec, write=False)
async def run_aci_column_axial(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    try:
        from kerf_cad_core.concrete.design import column_axial
        b           = float(a["b"])
        h           = float(a["h"])
        Ast         = float(a["Ast"])
        fc          = float(a.get("fc",    4_000))
        fy          = float(a.get("fy",   60_000))
        col_type    = str(a.get("column_type", "tied"))
        Pu          = float(a.get("Pu",        0.0))
        res = column_axial(b=b, h=h, Ast=Ast, fc_psi=fc, fy_psi=fy, column_type=col_type)
    except (KeyError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    # column_axial always returns a dict (never raises); check for required key
    if "phi_Pn_kip" not in res:
        return err_payload(res.get("warnings", ["unknown error"])[0], "DESIGN_FAIL")

    phi_Pn = res["phi_Pn_kip"]
    return ok_payload({
        "ok":          True,
        "b_in":        b,
        "h_in":        h,
        "Ag_in2":      round(b * h, 4),
        "Ast_in2":     round(Ast, 4),
        "rho_g":       round(res["rho_g"], 5),
        "fc_psi":      fc,
        "fy_psi":      fy,
        "column_type": col_type,
        "Pn_max_kip":  round(res["Pn_kip"], 2),
        "phi_Pn_kip":  round(phi_Pn, 2),
        "phi":         res["phi"],
        "Pu_kip":      round(Pu, 2),
        "adequate":    bool(Pu <= phi_Pn),
        "warnings":    res.get("warnings", []),
        "code_section": "ACI 318-19 §22.4.2",
    })


# ---------------------------------------------------------------------------
# structural_aci_column_pm
# ---------------------------------------------------------------------------

aci_column_pm_spec = ToolSpec(
    name="structural_aci_column_pm",
    description=(
        "ACI 318-19 uniaxial P-M interaction diagram for a rectangular column.\n"
        "\n"
        "Sweeps from pure compression (c→∞) to pure flexure, returning n_points\n"
        "(φPn_kip, φMn_kipin) pairs.  Each point applies the ACI ductility-\n"
        "controlled φ factor (0.65–0.90 for tied; 0.75–0.90 for spiral).\n"
        "\n"
        "The column has two layers of steel (top/compression + bottom/tension).\n"
        "Optionally checks whether a (Pu, Mu) demand point is inside the diagram.\n"
        "\n"
        "Returns: interaction_pts [[phi_Pn, phi_Mn]...], phi_Po_kip,\n"
        "phi_Mn0_kipin (pure bending capacity), demand_ok (if Pu/Mu supplied).\n"
        "Errors: {ok:false, reason}.  Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "b":           {"type": "number", "description": "Column width (in)"},
            "h":           {"type": "number", "description": "Column height/depth (in)"},
            "d":           {"type": "number", "description": "Depth to tension (bottom) steel centroid (in)"},
            "d_prime":     {"type": "number", "description": "Depth to compression (top) steel centroid (in)"},
            "As_top":      {"type": "number", "description": "Compression-side steel area (in²)"},
            "As_bot":      {"type": "number", "description": "Tension-side steel area (in²)"},
            "fc":          {"type": "number", "description": "f'c (psi), default 4000"},
            "fy":          {"type": "number", "description": "fy (psi), default 60000"},
            "column_type": {"type": "string", "description": "'tied' or 'spiral', default 'tied'"},
            "n_points":    {"type": "integer", "description": "Points on diagram, default 20"},
            "Pu":          {"type": "number", "description": "Demand axial compression (kips) — optional"},
            "Mu_kip_in":   {"type": "number", "description": "Demand moment (kip-in) — optional"},
        },
        "required": ["b", "h", "d", "d_prime", "As_top", "As_bot"],
    },
)


@register(aci_column_pm_spec, write=False)
async def run_aci_column_pm(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    try:
        from kerf_cad_core.concrete.design import column_pm_interaction
        b           = float(a["b"])
        h           = float(a["h"])
        d           = float(a["d"])
        d_prime     = float(a["d_prime"])
        As_top      = float(a["As_top"])
        As_bot      = float(a["As_bot"])
        fc          = float(a.get("fc",        4_000))
        fy          = float(a.get("fy",       60_000))
        col_type    = str(a.get("column_type", "tied"))
        n_points    = int(a.get("n_points",       20))
        Pu          = a.get("Pu")
        Mu_kip_in   = a.get("Mu_kip_in")

        res = column_pm_interaction(
            b=b, h=h, d=d, d_prime=d_prime,
            As_top=As_top, As_bot=As_bot,
            fc_psi=fc, fy_psi=fy,
            column_type=col_type, n_points=n_points,
        )
    except (KeyError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "INTERNAL")

    # column_pm_interaction always returns a dict; check required key
    if "points" not in res:
        return err_payload("no points returned", "INTERNAL")

    # Convert list-of-dicts to list-of-[phi_Pn, phi_Mn] pairs
    raw_pts = res["points"]  # list of {"phi_Pn_kip": ..., "phi_Mn_kipin": ...}
    pts_pairs = [(p["phi_Pn_kip"], p["phi_Mn_kipin"]) for p in raw_pts]

    # Check demand point against the interaction diagram
    demand_ok = None
    if Pu is not None and Mu_kip_in is not None:
        demand_ok = _check_demand(pts_pairs, float(Pu), float(Mu_kip_in))

    # Sample at most 30 points to keep payload small
    sampled = pts_pairs[::max(1, len(pts_pairs) // 30)]
    Ast_total = As_top + As_bot
    out = {
        "ok":              True,
        "b_in":            b,
        "h_in":            h,
        "d_in":            d,
        "d_prime_in":      d_prime,
        "As_top_in2":      round(As_top, 4),
        "As_bot_in2":      round(As_bot, 4),
        "Ast_in2":         round(Ast_total, 4),
        "rho_g":           round(Ast_total / (b * h), 5),
        "phi_Po_kip":      round(res["phi_Po_kip"], 2),
        "phi_Mn0_kipin":   round(res["phi_Mn0_kipin"], 2),
        "interaction_pts": [[round(p, 2), round(m, 2)] for p, m in sampled],
        "n_pts_total":     len(pts_pairs),
        "warnings":        res.get("warnings", []),
        "code_section":    "ACI 318-19 §22.4.2 / §21.2",
    }
    if demand_ok is not None:
        out["Pu_kip"]    = float(Pu)
        out["Mu_kip_in"] = float(Mu_kip_in)
        out["demand_ok"] = demand_ok

    return ok_payload(out)


def _check_demand(pts: list[tuple], Pu: float, Mu: float) -> bool:
    """Return True if (Pu, Mu) is inside the P-M envelope.

    pts: list of (phi_Pn, phi_Mn) from high compression → pure bending.
    """
    if not pts:
        return False
    # pts are sorted high-Pn to low-Pn (compression→flexure)
    for i in range(len(pts) - 1):
        P0, M0 = pts[i]
        P1, M1 = pts[i + 1]
        p_hi = max(P0, P1)
        p_lo = min(P0, P1)
        if p_lo <= Pu <= p_hi:
            # Linear interpolation of phi_Mn at Pu
            dP = P1 - P0
            if abs(dP) < 1e-9:
                M_limit = max(M0, M1)
            else:
                t = (Pu - P0) / dP
                M_limit = M0 + t * (M1 - M0)
            return Mu <= M_limit
    # Above the pure-compression limit
    if Pu > pts[0][0]:
        return False
    # Below the pure-bending axis — check against φMn,pure
    return Mu <= pts[-1][1]
