"""Aerospace fastener sizing and selection utilities.

Public API
----------
joint_allowable(fastener, materials) -> dict
    Return the effective allowable loads for a fastener in a given joint,
    accounting for bearing, shear and tension.

pick_fastener(load, mode, joint_thickness, prefer_spec) -> dict | None
    Select the lightest catalogue entry that satisfies the applied load.

Notes on allowable calculations
--------------------------------
Bearing allowable per sheet:
    P_br = F_bru * D * t
where F_bru is the ultimate bearing stress of the *weaker* material and t is
the sheet thickness being checked.  This is a conservative single-plane
value; the caller is responsible for applying the appropriate fitting factor
(typically 1.15 for structural joints) before comparing with design loads.

Shear and tension allowables are taken directly from the catalogue entry
(which are already published ultimate values, not design values — apply
SF = 1.5 for structural use).

Material bearing stress defaults (ksi) — conservative published F_bru:
    aluminum-2024-t3   : 160 ksi
    aluminum-7075-t6   : 212 ksi
    titanium-6al-4v    : 260 ksi
    alloy-steel-4130   : 320 ksi
    stainless-304      : 200 ksi
    carbon-fiber-cfrp  :  80 ksi  (conservative laminate, bearing-critical)
    default            : 120 ksi
"""

from __future__ import annotations

from typing import Any

from .catalogue import CATALOGUE, get_by_spec, filter_catalogue

# ---------------------------------------------------------------------------
# Default bearing-stress table (ksi) for common airframe materials
# ---------------------------------------------------------------------------
_BEARING_STRESS_KSI: dict[str, float] = {
    "aluminum-2024-t3": 160.0,
    "aluminum-7075-t6": 212.0,
    "titanium-6al-4v": 260.0,
    "alloy-steel-4130": 320.0,
    "stainless-304": 200.0,
    "carbon-fiber-cfrp": 80.0,
    "default": 120.0,
}


def _bearing_stress(material: str) -> float:
    """Return F_bru in ksi for *material* (case-insensitive match)."""
    key = material.lower().strip()
    for k, v in _BEARING_STRESS_KSI.items():
        if k in key or key in k:
            return v
    return _BEARING_STRESS_KSI["default"]


def joint_allowable(
    fastener: dict[str, Any],
    materials: list[dict[str, Any]],
) -> dict[str, float]:
    """Return effective joint allowables for *fastener* in the given *materials* stack.

    Parameters
    ----------
    fastener:
        A catalogue entry dict (must contain at least ``diameter_in``,
        ``shear_kip``, ``tension_kip``).
    materials:
        List of layer dicts, each with:
            ``material`` : str  — material name (used to look up F_bru)
            ``thickness_in`` : float  — layer thickness in inches

        At minimum one layer is required.  For a single-shear joint the
        bearing allowable is computed against the *thinnest* layer.  For
        multi-layer joints each layer is checked and the minimum governs.

    Returns
    -------
    dict with keys:
        ``shear_kip``   — fastener ultimate shear allowable (from catalogue)
        ``tension_kip`` — fastener ultimate tension allowable (from catalogue)
        ``bearing_kip`` — minimum bearing allowable across all layers (kip)
        ``governing``   — which limit governs ("shear", "tension", or "bearing")
    """
    if not materials:
        raise ValueError("materials list must contain at least one layer")

    d_in: float = fastener["diameter_in"]
    shear_kip: float = fastener["shear_kip"]
    tension_kip: float = fastener["tension_kip"]

    # Bearing: P_br = F_bru * D * t  (ksi * in * in = kip/in → multiply by 1 for kip)
    bearing_kip: float = float("inf")
    for layer in materials:
        mat_name: str = layer.get("material", "default")
        t: float = float(layer.get("thickness_in", 0.0))
        if t <= 0.0:
            continue
        f_bru: float = _bearing_stress(mat_name)
        layer_br: float = f_bru * d_in * t  # kip
        if layer_br < bearing_kip:
            bearing_kip = layer_br

    if bearing_kip == float("inf"):
        bearing_kip = min(shear_kip, tension_kip)

    # Governing mode
    min_val = min(shear_kip, tension_kip, bearing_kip)
    if abs(min_val - shear_kip) < 1e-9:
        governing = "shear"
    elif abs(min_val - tension_kip) < 1e-9:
        governing = "tension"
    else:
        governing = "bearing"

    return {
        "shear_kip": shear_kip,
        "tension_kip": tension_kip,
        "bearing_kip": round(bearing_kip, 4),
        "governing": governing,
    }


def pick_fastener(
    load: float,
    mode: str,
    joint_thickness: float,
    prefer_spec: str | None = None,
) -> dict[str, Any] | None:
    """Select the lightest fastener from the catalogue that satisfies *load*.

    Parameters
    ----------
    load : float
        Applied load in kip (single-shear equivalent for shear mode, or
        axial for tension mode).
    mode : str
        ``"shear"`` or ``"tension"``.
    joint_thickness : float
        Total joint stack thickness in inches.  Used to filter on grip range
        and to compute bearing allowable.
    prefer_spec : str | None
        If given and the matching catalogue entry satisfies the load, it is
        returned immediately without searching the rest of the catalogue.
        This allows the caller to enforce a preferred fastener family/size.

    Returns
    -------
    The selected fastener entry dict, or None if no suitable fastener exists.
    """
    if mode not in ("shear", "tension"):
        raise ValueError(f"mode must be 'shear' or 'tension', got {mode!r}")
    if load <= 0:
        raise ValueError("load must be positive")

    field = "shear_kip" if mode == "shear" else "tension_kip"

    # --- Try preferred spec first ---
    if prefer_spec is not None:
        candidate = get_by_spec(prefer_spec)
        if candidate is not None:
            g_min, g_max = candidate["grip_range"]
            if (
                candidate[field] >= load
                and g_min <= joint_thickness <= g_max + 0.063
            ):
                return candidate
        # If preferred spec doesn't fit, fall through to search

    # --- Search catalogue for smallest diameter that satisfies the load ---
    # Sort by diameter then by shear/tension to prefer lightest option
    suitable = [
        e for e in CATALOGUE
        if e[field] >= load
        and e["grip_range"][0] <= joint_thickness <= e["grip_range"][1] + 0.063
    ]

    if not suitable:
        return None

    # Sort: lightest (smallest dia) first, then smallest allowable (closest fit)
    suitable.sort(key=lambda e: (e["diameter_in"], e[field]))
    return suitable[0]
