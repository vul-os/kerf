"""
kerf_cad_core.procsim.am_residual
==================================
Additive-manufacturing residual stress and distortion prediction.

Implements the inherent-strain method for LPBF (Laser Powder Bed Fusion) and
DED (Directed Energy Deposition) processes.  Layer-by-layer thermal contraction
accumulates residual stress; the part warps / curls off the build plate in a
manner analogous to a bimetallic strip (Stoney curvature formula).

Public simulation functions
---------------------------
  am_residual_1d(n_layers, layer_thickness, part_length, part_width,
                 material, process, ...)
      Layer-by-layer 1-D inherent-strain accumulation along the build axis.
      Returns per-layer stress field, accumulated curvature, tip deflection
      (warpage), and support-load estimate.

  am_orient_scan(n_layers, layer_thickness, part_length, part_width,
                 part_height, material, process, orientations)
      Scan a list of build orientations (rotation angles about the longest
      axis) and return the residual-stress metric for each, identifying the
      minimum-residual orientation.

Helper query functions (read-only, never raise)
-----------------------------------------------
  material_props(name)   -> {"ok": bool, ...thermo-mechanical fields...}
  stress_relief_soak(sigma_0, T_soak_C, t_soak_s, material)
                         -> {"ok": bool, "sigma_final": float, ...}

LLM tools (gated)
-----------------
  am_run_residual_1d, am_orient_scan, am_stress_relief_soak,
  am_material_props

Design notes
------------
* Pure Python; no numpy / scipy / external deps.
* Inherent-strain model: each newly deposited layer contracts by
    eps_inh = alpha * (T_melt - T_ambient)
  relative to the substrate stack beneath it.  The resulting elastic misfit
  stress in the new layer is
    sigma_new = E * eps_inh / (1 - nu)
  (biaxial, plane-stress).  Accumulated curvature follows from the
  Euler-Bernoulli / Stoney formula.
* Stoney (bimetallic-strip) analogy: curvature kappa ~ sigma_f * t_f / (E_s * t_s^2)
  which gives tip deflection delta = kappa * L^2 / 2.  This is cross-checked in
  the tests via warpage ∝ Δstrain * L² / t (within a band).
* Stress-relief soak: Arrhenius-type relaxation
    sigma(t) = sigma_0 * exp(-A * exp(-Q/(R*T)) * t)
  with parameters A, Q (activation energy) tabulated per material.
* Recoater collision risk: flagged when the cumulative tip deflection (curl)
  exceeds one layer thickness.
* Support load: proportional to the projected overhang area times the
  effective stress at that height.
* Never raises.  All public functions return {"ok": bool, ...}.

References
----------
Mercelis, P. & Kruth, J.-P. (2006). "Residual stresses in selective laser
    sintering and selective laser melting." Rapid Prototyping Journal 12(5).
Stoney, G.G. (1909). "The tension of metallic films deposited by electrolysis."
    Proc. R. Soc. London A 82(553): 172–175.
Simson, T. et al. (2017). "Residual stress measurements on AISI 316L samples
    manufactured by selective laser melting." Additive Manufacturing 17: 25–33.
Timoshenko, S. (1925). "Analysis of bi-metal thermostats." J. Opt. Soc. Am.
    11(3): 233–255.

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Material thermo-mechanical properties
# ---------------------------------------------------------------------------

_MATERIALS: Dict[str, Dict[str, float]] = {
    # 316L stainless steel (typical LPBF values)
    "316l": {
        "E": 193e9,          # Young's modulus [Pa]
        "nu": 0.30,          # Poisson's ratio
        "alpha": 16.0e-6,    # CTE [1/K]
        "rho": 7950.0,       # density [kg/m³]
        "T_melt": 1400.0,    # effective solidus temperature [°C]
        "sy": 170e6,         # yield strength (as-built) [Pa]
        # Arrhenius stress-relief parameters
        "sr_A": 1.0e10,      # pre-exponential [1/s]
        "sr_Q": 150e3,       # activation energy [J/mol]
    },
    # Ti-6Al-4V (grade 23, LPBF)
    "ti64": {
        "E": 114e9,
        "nu": 0.34,
        "alpha": 8.6e-6,
        "rho": 4430.0,
        "T_melt": 1604.0,
        "sy": 900e6,
        "sr_A": 5.0e9,
        "sr_Q": 180e3,
    },
    # AlSi10Mg (LPBF aluminium alloy)
    "alsi10mg": {
        "E": 70e9,
        "nu": 0.33,
        "alpha": 21.0e-6,
        "rho": 2680.0,
        "T_melt": 570.0,
        "sy": 200e6,
        "sr_A": 1.0e8,
        "sr_Q": 120e3,
    },
    # Inconel 625 (DED / LPBF nickel superalloy)
    "in625": {
        "E": 206e9,
        "nu": 0.28,
        "alpha": 12.8e-6,
        "rho": 8440.0,
        "T_melt": 1290.0,
        "sy": 275e6,
        "sr_A": 2.0e10,
        "sr_Q": 170e3,
    },
    # Maraging steel 1.2709 (DED / LPBF tooling steel)
    "maraging": {
        "E": 180e9,
        "nu": 0.30,
        "alpha": 10.1e-6,
        "rho": 8000.0,
        "T_melt": 1413.0,
        "sy": 900e6,
        "sr_A": 5.0e9,
        "sr_Q": 160e3,
    },
}

_GAS_CONSTANT = 8.314  # J/(mol·K)


def material_props(name: str) -> Dict[str, Any]:
    """Return thermo-mechanical properties for an AM material.

    Parameters
    ----------
    name : material identifier (case-insensitive).
           Supported: '316l', 'ti64', 'alsi10mg', 'in625', 'maraging'.

    Returns
    -------
    dict with ok=True and fields E, nu, alpha, rho, T_melt, sy, sr_A, sr_Q,
    or ok=False with reason.
    """
    key = name.strip().lower().replace("-", "").replace(" ", "")
    if key not in _MATERIALS:
        supported = ", ".join(sorted(_MATERIALS))
        return {
            "ok": False,
            "reason": f"unknown material '{name}'. Supported: {supported}",
        }
    props = dict(_MATERIALS[key])
    props["ok"] = True
    props["name"] = key
    return props


# ---------------------------------------------------------------------------
# Stress-relief soak
# ---------------------------------------------------------------------------

def stress_relief_soak(
    sigma_0: float,
    T_soak_C: float,
    t_soak_s: float,
    material: str = "316l",
) -> Dict[str, Any]:
    """Estimate residual-stress relaxation during a post-build stress-relief soak.

    Uses an Arrhenius-type exponential decay:
        sigma(t) = sigma_0 * exp(-A * exp(-Q/(R*T_K)) * t)

    Parameters
    ----------
    sigma_0   : initial residual stress [Pa]
    T_soak_C  : soak temperature [°C]
    t_soak_s  : soak duration [s]
    material  : material name (default '316l')

    Returns
    -------
    dict with ok=True, sigma_final [Pa], fraction_remaining, and
    relaxation_rate [1/s]; or ok=False with reason.
    """
    try:
        return _stress_relief_inner(sigma_0, T_soak_C, t_soak_s, material)
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _stress_relief_inner(
    sigma_0: float,
    T_soak_C: float,
    t_soak_s: float,
    material: str,
) -> Dict[str, Any]:
    if t_soak_s < 0.0:
        return {"ok": False, "reason": "t_soak_s must be >= 0"}
    if T_soak_C < 0.0:
        return {"ok": False, "reason": "T_soak_C must be >= 0 °C"}

    mp = material_props(material)
    if not mp["ok"]:
        return mp

    T_K = T_soak_C + 273.15
    A = mp["sr_A"]
    Q = mp["sr_Q"]
    R = _GAS_CONSTANT

    rate = A * math.exp(-Q / (R * T_K))
    sigma_final = sigma_0 * math.exp(-rate * t_soak_s)
    fraction_remaining = sigma_final / sigma_0 if sigma_0 != 0.0 else 1.0

    return {
        "ok": True,
        "sigma_0_Pa": sigma_0,
        "sigma_final_Pa": sigma_final,
        "fraction_remaining": fraction_remaining,
        "relaxation_rate_per_s": rate,
        "T_soak_C": T_soak_C,
        "t_soak_s": t_soak_s,
        "material": mp["name"],
    }


# ---------------------------------------------------------------------------
# 1-D layer-by-layer residual stress accumulation
# ---------------------------------------------------------------------------

def am_residual_1d(
    n_layers: int,
    layer_thickness: float,
    part_length: float,
    part_width: float,
    material: str = "316l",
    process: str = "lpbf",
    T_ambient: float = 25.0,
    T_preheat: float = 80.0,
    overhang_fraction: float = 0.0,
    scan_rotation_deg: float = 67.0,
) -> Dict[str, Any]:
    """Layer-by-layer 1-D inherent-strain residual stress and distortion.

    The build direction is z.  Each layer deposits elastic misfit stress
    sigma_layer = E * eps_inh / (1 - nu) (biaxial).

    Accumulated Stoney curvature at layer k:
        kappa_k = sum_{i=1..k} sigma_i * t_layer / (E * H_k^2 / 6)
    where H_k = k * t_layer is the current stack height.

    Tip deflection (warpage): delta = kappa_final * L^2 / 2.

    Parameters
    ----------
    n_layers          : number of deposited layers
    layer_thickness   : layer thickness [m]
    part_length       : longest in-plane dimension [m]
    part_width        : shorter in-plane dimension [m]
    material          : material name (default '316l')
    process           : 'lpbf' or 'ded' (affects inherent-strain scale)
    T_ambient         : ambient / chamber temperature [°C]
    T_preheat         : build-plate preheat temperature [°C]
    overhang_fraction : fraction of cross-section that is unsupported overhang
                        (0..1, used for support load estimate)
    scan_rotation_deg : inter-layer scan rotation [°]; 67° is typical for LPBF

    Returns
    -------
    dict with ok=True and:
      sigma_layers         — list[float]: biaxial stress in each layer [Pa]
      accumulated_stress   — list[float]: running sum (mean) [Pa]
      curvature_per_layer  — list[float]: incremental Stoney curvature [1/m]
      accumulated_curvature — list[float]: total curvature after each layer [1/m]
      tip_deflection_m     — final warpage (Stoney-like tip curl) [m]
      part_height_m        — total build height [m]
      recoater_collision   — True if curl > layer_thickness at any layer
      recoater_collision_layer — first layer at which collision is flagged (or None)
      support_load_N       — estimated support reaction force [N]
      max_sigma_Pa         — peak layer stress [Pa]
      stoney_curvature     — final curvature from Stoney formula [1/m]
      warnings             — list[str]
    """
    try:
        return _am_residual_1d_inner(
            n_layers=n_layers,
            layer_thickness=layer_thickness,
            part_length=part_length,
            part_width=part_width,
            material=material,
            process=process,
            T_ambient=T_ambient,
            T_preheat=T_preheat,
            overhang_fraction=overhang_fraction,
            scan_rotation_deg=scan_rotation_deg,
        )
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _inherent_strain(
    mp: Dict[str, Any],
    process: str,
    T_ambient: float,
    T_preheat: float,
) -> float:
    """Compute inherent strain for one deposited layer.

    eps_inh = alpha * (T_melt - T_effective)
    T_effective = max(T_ambient, T_preheat) to account for preheating.
    LPBF has ~1.0x scale; DED uses ~0.6x (slower solidification).
    """
    T_eff = max(T_ambient, T_preheat)
    delta_T = mp["T_melt"] - T_eff
    if delta_T < 0.0:
        delta_T = 0.0
    eps = mp["alpha"] * delta_T
    if process.lower() == "ded":
        eps *= 0.6
    return eps


def _am_residual_1d_inner(
    n_layers: int,
    layer_thickness: float,
    part_length: float,
    part_width: float,
    material: str,
    process: str,
    T_ambient: float,
    T_preheat: float,
    overhang_fraction: float,
    scan_rotation_deg: float,
) -> Dict[str, Any]:
    warnings: List[str] = []

    if n_layers < 1:
        return {"ok": False, "reason": "n_layers must be >= 1"}
    if layer_thickness <= 0.0:
        return {"ok": False, "reason": "layer_thickness must be > 0"}
    if part_length <= 0.0:
        return {"ok": False, "reason": "part_length must be > 0"}
    if part_width <= 0.0:
        return {"ok": False, "reason": "part_width must be > 0"}
    if not (0.0 <= overhang_fraction <= 1.0):
        return {"ok": False, "reason": "overhang_fraction must be in [0, 1]"}
    if process.lower() not in ("lpbf", "ded"):
        warnings.append(f"unknown process '{process}', defaulting to lpbf scaling")
        process = "lpbf"

    mp = material_props(material)
    if not mp["ok"]:
        return mp

    E = mp["E"]
    nu = mp["nu"]
    t = layer_thickness
    L = part_length

    eps_inh = _inherent_strain(mp, process, T_ambient, T_preheat)

    # Per-layer biaxial misfit stress (plane-stress biaxial)
    sigma_layer = E * eps_inh / (1.0 - nu)

    sigma_layers: List[float] = []
    accumulated_stress: List[float] = []
    curvature_per_layer: List[float] = []
    accumulated_curvature: List[float] = []

    sigma_sum = 0.0
    kappa_total = 0.0
    recoater_collision = False
    recoater_collision_layer: Optional[int] = None
    tip_deflection_m = 0.0

    for k in range(1, n_layers + 1):
        H_k = k * t  # current total build height

        sigma_layers.append(sigma_layer)
        sigma_sum += sigma_layer
        accumulated_stress.append(sigma_sum / k)

        # Stoney / Euler-Bernoulli incremental curvature for this layer
        # kappa_increment = sigma_layer * t / (E * H_k^2 / 6)
        # = 6 * sigma_layer * t / (E * H_k^2)
        kappa_inc = 6.0 * sigma_layer * t / (E * H_k * H_k)
        curvature_per_layer.append(kappa_inc)

        kappa_total += kappa_inc
        accumulated_curvature.append(kappa_total)

        # Tip deflection estimate (cantilever analogy)
        tip = kappa_total * L * L / 2.0
        tip_deflection_m = tip

        # Recoater collision: curl at top of part > 1 layer thickness
        if (not recoater_collision) and (tip > t):
            recoater_collision = True
            recoater_collision_layer = k

    part_height_m = n_layers * t

    # Final Stoney curvature (film on substrate analogy):
    # kappa_stoney = 6 * sigma_f * t_f / (E_s * t_s^2)
    # Here treat the accumulated deposited stack as the "film" and use
    # the substrate effective thickness = part_height_m.
    sigma_mean = sigma_sum / n_layers
    kappa_stoney = 6.0 * sigma_mean * t / (E * part_height_m * part_height_m)

    # Support load estimate:
    # F_support = sigma_mean * overhang_area * t
    # where overhang_area = overhang_fraction * part_length * part_width
    overhang_area = overhang_fraction * part_length * part_width
    support_load_N = sigma_mean * overhang_area * t

    if kappa_total > 1.0 / (2.0 * L):
        warnings.append(
            "Large curvature: Euler-Bernoulli small-deflection assumption may be violated."
        )

    if sigma_mean > mp["sy"]:
        warnings.append(
            f"Mean layer stress ({sigma_mean/1e6:.1f} MPa) exceeds yield strength "
            f"({mp['sy']/1e6:.1f} MPa); plastic relaxation is not modelled."
        )

    return {
        "ok": True,
        "sigma_layers": sigma_layers,
        "accumulated_stress": accumulated_stress,
        "curvature_per_layer": curvature_per_layer,
        "accumulated_curvature": accumulated_curvature,
        "tip_deflection_m": tip_deflection_m,
        "part_height_m": part_height_m,
        "recoater_collision": recoater_collision,
        "recoater_collision_layer": recoater_collision_layer,
        "support_load_N": support_load_N,
        "max_sigma_Pa": max(sigma_layers),
        "stoney_curvature": kappa_stoney,
        "inherent_strain": eps_inh,
        "material": mp["name"],
        "process": process.lower(),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Orientation scan
# ---------------------------------------------------------------------------

def am_orient_scan(
    n_layers: int,
    layer_thickness: float,
    part_length: float,
    part_width: float,
    part_height: float,
    material: str = "316l",
    process: str = "lpbf",
    T_ambient: float = 25.0,
    T_preheat: float = 80.0,
    orientations: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """Scan build orientations and return the minimum-residual orientation.

    Each orientation is a rotation angle (degrees) of the part about its
    longest axis (X).  The effective part_length and part_height are swapped
    when the orientation changes the build axis.

    Specifically, the function evaluates the Stoney tip-deflection metric
    for each orientation using the appropriate (rotated) dimensions and
    returns all results sorted by residual metric ascending.

    Parameters
    ----------
    n_layers      : nominal number of layers at the default orientation
    layer_thickness : layer thickness [m]
    part_length   : longest in-plane dimension [m]
    part_width    : shorter in-plane dimension [m]
    part_height   : nominal build height [m]
    material      : material name
    process       : 'lpbf' or 'ded'
    T_ambient     : ambient temperature [°C]
    T_preheat     : preheat temperature [°C]
    orientations  : list of rotation angles in degrees to evaluate.
                    Default: 0, 15, 30, 45, 60, 75, 90 degrees.

    Returns
    -------
    dict with ok=True and:
      results            — list of dicts {angle_deg, tip_deflection_m,
                           stoney_curvature, recoater_collision,
                           effective_n_layers, effective_length_m}
      best_angle_deg     — angle with minimum tip deflection
      best_tip_deflection_m
      sorted by tip_deflection_m ascending
    """
    try:
        return _am_orient_scan_inner(
            n_layers=n_layers,
            layer_thickness=layer_thickness,
            part_length=part_length,
            part_width=part_width,
            part_height=part_height,
            material=material,
            process=process,
            T_ambient=T_ambient,
            T_preheat=T_preheat,
            orientations=orientations,
        )
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


def _am_orient_scan_inner(
    n_layers: int,
    layer_thickness: float,
    part_length: float,
    part_width: float,
    part_height: float,
    material: str,
    process: str,
    T_ambient: float,
    T_preheat: float,
    orientations: Optional[Sequence[float]],
) -> Dict[str, Any]:
    if n_layers < 1:
        return {"ok": False, "reason": "n_layers must be >= 1"}
    if layer_thickness <= 0.0:
        return {"ok": False, "reason": "layer_thickness must be > 0"}
    if part_length <= 0.0:
        return {"ok": False, "reason": "part_length must be > 0"}
    if part_width <= 0.0:
        return {"ok": False, "reason": "part_width must be > 0"}
    if part_height <= 0.0:
        return {"ok": False, "reason": "part_height must be > 0"}

    mp = material_props(material)
    if not mp["ok"]:
        return mp

    if orientations is None:
        angles = [0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0]
    else:
        angles = list(orientations)

    if not angles:
        return {"ok": False, "reason": "orientations list must be non-empty"}

    results = []
    for angle_deg in angles:
        theta = math.radians(angle_deg)

        # Effective build height: rotate bounding-box height around Y.
        # At 0°: build_height = part_height, footprint_length = part_length.
        # At 90°: build_height = part_length, footprint_length = part_height.
        # In between: linear interpolation of the projected extents.
        c = abs(math.cos(theta))
        s = abs(math.sin(theta))

        effective_height = part_height * c + part_length * s
        effective_length = part_length * c + part_height * s

        effective_n = max(1, round(effective_height / layer_thickness))

        r = am_residual_1d(
            n_layers=effective_n,
            layer_thickness=layer_thickness,
            part_length=effective_length,
            part_width=part_width,
            material=material,
            process=process,
            T_ambient=T_ambient,
            T_preheat=T_preheat,
            overhang_fraction=s,  # more overhang at steeper angles
        )
        if not r["ok"]:
            results.append({
                "angle_deg": angle_deg,
                "tip_deflection_m": None,
                "stoney_curvature": None,
                "recoater_collision": None,
                "effective_n_layers": effective_n,
                "effective_length_m": effective_length,
                "error": r.get("reason"),
            })
        else:
            results.append({
                "angle_deg": angle_deg,
                "tip_deflection_m": r["tip_deflection_m"],
                "stoney_curvature": r["stoney_curvature"],
                "recoater_collision": r["recoater_collision"],
                "effective_n_layers": effective_n,
                "effective_length_m": effective_length,
            })

    # Sort by tip deflection ascending (None sorts to end)
    valid = [r for r in results if r["tip_deflection_m"] is not None]
    invalid = [r for r in results if r["tip_deflection_m"] is None]
    valid_sorted = sorted(valid, key=lambda x: x["tip_deflection_m"])
    results_sorted = valid_sorted + invalid

    best = valid_sorted[0] if valid_sorted else None

    return {
        "ok": True,
        "results": results_sorted,
        "best_angle_deg": best["angle_deg"] if best else None,
        "best_tip_deflection_m": best["tip_deflection_m"] if best else None,
    }


# ---------------------------------------------------------------------------
# LLM tool wrappers (gated on kerf_chat / kerf_core availability)
# ---------------------------------------------------------------------------

try:
    import json as _json
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------ #
    # am_material_props                                                    #
    # ------------------------------------------------------------------ #

    _mat_props_spec = ToolSpec(
        name="am_material_props",
        description=(
            "Return thermo-mechanical properties for an AM (additive manufacturing)\n"
            "material.\n\n"
            "Supported: '316l' (SS316L), 'ti64' (Ti-6Al-4V), 'alsi10mg', 'in625'\n"
            "(Inconel 625), 'maraging' (1.2709 maraging steel).\n\n"
            "Returns E, nu, alpha (CTE), rho, T_melt, sy, and Arrhenius\n"
            "stress-relief parameters sr_A and sr_Q.\n\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Material name. Supported: '316l', 'ti64', 'alsi10mg', 'in625', 'maraging'.",
                },
            },
            "required": ["name"],
        },
    )

    @register(_mat_props_spec, write=False)
    async def am_material_props_tool(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        if not a.get("name"):
            return _json.dumps({"ok": False, "reason": "name is required"})
        result = material_props(a["name"])
        return ok_payload(result) if result["ok"] else _json.dumps(result)

    # ------------------------------------------------------------------ #
    # am_stress_relief_soak                                                #
    # ------------------------------------------------------------------ #

    _soak_spec = ToolSpec(
        name="am_stress_relief_soak",
        description=(
            "Estimate residual-stress relaxation during a post-build stress-relief soak.\n\n"
            "Uses Arrhenius exponential decay: sigma(t) = sigma_0 * exp(-A*exp(-Q/RT)*t).\n"
            "Parameters A and Q are tabulated per material.\n\n"
            "Returns sigma_final, fraction_remaining, and relaxation_rate.\n\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "sigma_0": {
                    "type": "number",
                    "description": "Initial residual stress [Pa].",
                },
                "T_soak_C": {
                    "type": "number",
                    "description": "Soak temperature [°C].",
                },
                "t_soak_s": {
                    "type": "number",
                    "description": "Soak duration [s].",
                },
                "material": {
                    "type": "string",
                    "description": "Material name (default '316l').",
                },
            },
            "required": ["sigma_0", "T_soak_C", "t_soak_s"],
        },
    )

    @register(_soak_spec, write=False)
    async def am_stress_relief_soak_tool(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for f in ("sigma_0", "T_soak_C", "t_soak_s"):
            if a.get(f) is None:
                return _json.dumps({"ok": False, "reason": f"{f} is required"})
        kwargs: dict = {}
        if "material" in a:
            kwargs["material"] = a["material"]
        result = stress_relief_soak(
            sigma_0=float(a["sigma_0"]),
            T_soak_C=float(a["T_soak_C"]),
            t_soak_s=float(a["t_soak_s"]),
            **kwargs,
        )
        return ok_payload(result) if result["ok"] else _json.dumps(result)

    # ------------------------------------------------------------------ #
    # am_run_residual_1d                                                   #
    # ------------------------------------------------------------------ #

    _residual_1d_spec = ToolSpec(
        name="am_run_residual_1d",
        description=(
            "Run a layer-by-layer 1-D inherent-strain residual stress and distortion\n"
            "simulation for LPBF or DED additive manufacturing.\n\n"
            "Each deposited layer imparts a biaxial misfit stress proportional to\n"
            "E * alpha * (T_melt - T_preheat) / (1 - nu).  Stoney / Euler-Bernoulli\n"
            "curvature accumulates, producing tip deflection (warpage) and potential\n"
            "recoater collision.\n\n"
            "Returns per-layer stress, accumulated curvature, tip deflection, support\n"
            "load estimate, and recoater-collision flag.\n\n"
            "Cross-check: warpage ∝ Δstrain * L² / t (Stoney-like within a band).\n\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "n_layers": {
                    "type": "integer",
                    "description": "Number of deposited layers (>=1).",
                },
                "layer_thickness": {
                    "type": "number",
                    "description": "Layer thickness [m]. Must be > 0.",
                },
                "part_length": {
                    "type": "number",
                    "description": "Longest in-plane dimension [m]. Must be > 0.",
                },
                "part_width": {
                    "type": "number",
                    "description": "Shorter in-plane dimension [m]. Must be > 0.",
                },
                "material": {
                    "type": "string",
                    "description": "Material name. Supported: '316l', 'ti64', 'alsi10mg', 'in625', 'maraging'.",
                },
                "process": {
                    "type": "string",
                    "description": "AM process: 'lpbf' or 'ded' (default 'lpbf').",
                },
                "T_ambient": {
                    "type": "number",
                    "description": "Ambient temperature [°C] (default 25).",
                },
                "T_preheat": {
                    "type": "number",
                    "description": "Build-plate preheat temperature [°C] (default 80).",
                },
                "overhang_fraction": {
                    "type": "number",
                    "description": "Fraction of cross-section that is unsupported overhang [0..1] (default 0).",
                },
                "scan_rotation_deg": {
                    "type": "number",
                    "description": "Inter-layer scan rotation angle [degrees] (default 67).",
                },
            },
            "required": ["n_layers", "layer_thickness", "part_length", "part_width"],
        },
    )

    @register(_residual_1d_spec, write=False)
    async def am_run_residual_1d_tool(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for f in ("n_layers", "layer_thickness", "part_length", "part_width"):
            if a.get(f) is None:
                return _json.dumps({"ok": False, "reason": f"{f} is required"})
        kwargs2: dict = {}
        for opt in (
            "material", "process", "T_ambient", "T_preheat",
            "overhang_fraction", "scan_rotation_deg",
        ):
            if opt in a:
                kwargs2[opt] = a[opt]
        result = am_residual_1d(
            n_layers=int(a["n_layers"]),
            layer_thickness=float(a["layer_thickness"]),
            part_length=float(a["part_length"]),
            part_width=float(a["part_width"]),
            **kwargs2,
        )
        return ok_payload(result) if result["ok"] else _json.dumps(result)

    # ------------------------------------------------------------------ #
    # am_run_orient_scan                                                   #
    # ------------------------------------------------------------------ #

    _orient_scan_spec = ToolSpec(
        name="am_run_orient_scan",
        description=(
            "Scan multiple build orientations and find the one that minimises\n"
            "residual stress / tip deflection for an AM part.\n\n"
            "Rotates the part about its longest axis at each specified angle,\n"
            "recomputes effective build height and footprint, runs the inherent-\n"
            "strain model, and returns results sorted by tip deflection ascending.\n\n"
            "Returns best_angle_deg, best_tip_deflection_m, and per-angle detail.\n\n"
            "Errors: {ok:false, reason} — never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "n_layers": {
                    "type": "integer",
                    "description": "Nominal number of layers at 0° orientation.",
                },
                "layer_thickness": {
                    "type": "number",
                    "description": "Layer thickness [m].",
                },
                "part_length": {
                    "type": "number",
                    "description": "Longest in-plane dimension [m].",
                },
                "part_width": {
                    "type": "number",
                    "description": "Shorter in-plane dimension [m].",
                },
                "part_height": {
                    "type": "number",
                    "description": "Nominal build height [m].",
                },
                "material": {
                    "type": "string",
                    "description": "Material name.",
                },
                "process": {
                    "type": "string",
                    "description": "'lpbf' or 'ded'.",
                },
                "T_ambient": {
                    "type": "number",
                    "description": "Ambient temperature [°C].",
                },
                "T_preheat": {
                    "type": "number",
                    "description": "Preheat temperature [°C].",
                },
                "orientations": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "List of rotation angles [degrees] to evaluate.",
                },
            },
            "required": ["n_layers", "layer_thickness", "part_length", "part_width", "part_height"],
        },
    )

    @register(_orient_scan_spec, write=False)
    async def am_run_orient_scan_tool(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for f in ("n_layers", "layer_thickness", "part_length", "part_width", "part_height"):
            if a.get(f) is None:
                return _json.dumps({"ok": False, "reason": f"{f} is required"})
        kwargs3: dict = {}
        for opt in ("material", "process", "T_ambient", "T_preheat", "orientations"):
            if opt in a:
                kwargs3[opt] = a[opt]
        result = am_orient_scan(
            n_layers=int(a["n_layers"]),
            layer_thickness=float(a["layer_thickness"]),
            part_length=float(a["part_length"]),
            part_width=float(a["part_width"]),
            part_height=float(a["part_height"]),
            **kwargs3,
        )
        return ok_payload(result) if result["ok"] else _json.dumps(result)
