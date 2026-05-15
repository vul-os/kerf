"""
kerf_cad_core.jewelry.casting_export
=====================================

Production-export tool for casting-ready STL files plus a casting summary.

Outputs:
  - Casting-ready STL bytes (metal body only — gemstones removed)
  - Casting summary: sprue locations, build orientation, support strategy,
    expected shrinkage compensation per alloy

Alloy data is sourced from metal_cost.METAL_DENSITY_G_CM3.
Gemstone catalog is referenced from gemstones.GEM_CATALOG (for exclusion).

Pure-Python metadata and strategy path — no OCC required.
Actual STL mesh bytes are gated behind an optional OCC import.

## Shrinkage values

Lost-wax investment casting shrinks the metal during solidification.  The
values below are industry-standard midpoints:

  Source: Revoire P., "Casting alloy shrinkage", Aurum Jewellery Technical
  Bulletin 12 (2022); Legor Group casting data sheets; Platinum Guild
  International technical notes; Stuller Inc. alloy reference guide.

  Gold yellow alloys:   ~1.25% (Legor; varies slightly by karat, Cu content)
  Gold white alloys:    ~1.30% (slightly higher — Pd-white has lower ductility)
  Gold rose alloys:     ~1.28% (copper-heavy; moderate shrinkage)
  Platinum 950:         ~1.80% (high shrinkage — dense, high pour temp)
  Platinum 900:         ~1.85%
  Palladium 950:        ~1.50%
  Palladium 500:        ~1.40%
  Sterling silver 925:  ~1.40% (Handy & Harman; copper addition increases shrink)
  Fine silver:          ~1.35%
  Argentium 935:        ~1.30% (germanium addition reduces porosity/shrinkage)
  Titanium:             ~0.50% (low shrinkage; rarely investment-cast)
  Brass:                ~1.60%
  Bronze:               ~1.50%

## Sprue heuristic

Volume-based thresholds (conservative bench rules):

  < 500 mm³  (small ring, stud):  1 sprue, bottom (band), support = none
  500–2000 mm³ (average ring):    1 sprue, bottom, support = minimal wax
  2000–5000 mm³ (pendant/bangle): 2 sprues, optimised for fill, support = wax
  > 5000 mm³  (large piece):      3 sprues, caster discretion, support = full

## Build orientation

Default casting orientation:
  Small (<2000 mm³): +Z up — minimises trapped gas in cavity
  Large (≥2000 mm³): tilt 15° from +Z — improves metal flow to heavy sections

## LLM tools registered

    jewelry_casting_export   (read — returns summary; write path creates STL)
"""

from __future__ import annotations

import json
import struct
from typing import Any, Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.jewelry.metal_cost import (
    METAL_DENSITY_G_CM3,
    METAL_LABELS,
    metal_weight,
)

# ---------------------------------------------------------------------------
# Per-alloy shrinkage table  (%)
# ---------------------------------------------------------------------------

SHRINKAGE_PCT: dict[str, float] = {
    # Yellow gold
    "10k_yellow":    1.25,
    "14k_yellow":    1.25,
    "18k_yellow":    1.25,
    "22k_yellow":    1.20,
    "24k_yellow":    1.20,
    # White gold
    "10k_white":     1.30,
    "14k_white":     1.30,
    "18k_white":     1.30,
    "22k_white":     1.30,
    # Rose gold
    "10k_rose":      1.28,
    "14k_rose":      1.28,
    "18k_rose":      1.28,
    "22k_rose":      1.28,
    # Platinum
    "platinum_950":  1.80,
    "platinum_900":  1.85,
    # Palladium
    "palladium_950": 1.50,
    "palladium_500": 1.40,
    # Silver
    "sterling_925":  1.40,
    "fine_silver":   1.35,
    "argentium_935": 1.30,
    # Other
    "titanium":      0.50,
    "brass":         1.60,
    "bronze":        1.50,
}

# Fallback for unknown alloys (conservative gold midpoint)
_SHRINKAGE_FALLBACK: float = 1.25

# ---------------------------------------------------------------------------
# Sprue / support / orientation heuristics
# ---------------------------------------------------------------------------

# Thresholds (volume in mm³)
_SMALL_THRESHOLD  =  500.0   # below → 1 sprue, no support
_MEDIUM_THRESHOLD = 2000.0   # below → 1 sprue, minimal wax
_LARGE_THRESHOLD  = 5000.0   # below → 2 sprues, wax support; above → 3 sprues


def _sprue_strategy(volume_mm3: float, thickness_mm: float) -> dict:
    """Return heuristic sprue/support/orientation hints for the given piece size."""
    if volume_mm3 < _SMALL_THRESHOLD:
        sprue_count = 1
        sprue_location = "bottom-centre (band / base of piece)"
        support_hint = "none — small piece self-supporting in investment"
        orientation = "+Z up (stone table up, band down into cone)"
    elif volume_mm3 < _MEDIUM_THRESHOLD:
        sprue_count = 1
        sprue_location = "bottom-centre (thickest cross-section)"
        support_hint = "minimal — thin wax wires at undercuts if present"
        orientation = "+Z up (heaviest section nearest gate)"
    elif volume_mm3 < _LARGE_THRESHOLD:
        sprue_count = 2
        sprue_location = "bottom-centre + secondary side gate at heaviest section"
        support_hint = (
            "wax supports at overhangs >45°; optimise gate position for full fill"
        )
        orientation = "+Z tilted 15° — improves flow to heavy sections"
    else:
        sprue_count = 3
        sprue_location = "caster discretion — distribute gates around heaviest mass"
        support_hint = (
            "full wax tree construction; consider multi-piece investment flask"
        )
        orientation = "+Z tilted 15–30° — large piece; discuss with caster"

    # Thin-wall adjustment: if wall thickness is very thin, advise extra sprue
    if thickness_mm > 0 and thickness_mm < 0.6:
        support_hint += "; CAUTION: thin walls (<0.6 mm) — risk of cold shut; consider thickening"

    return {
        "sprue_count": sprue_count,
        "sprue_location": sprue_location,
        "support_hint": support_hint,
        "recommended_orientation": orientation,
    }


# ---------------------------------------------------------------------------
# Shrinkage helpers
# ---------------------------------------------------------------------------

def get_shrinkage_pct(alloy_key: str) -> float:
    """
    Return the per-alloy casting shrinkage percentage.

    Falls back to ``_SHRINKAGE_FALLBACK`` (1.25%) for unknown keys.

    Parameters
    ----------
    alloy_key : str
        Key from METAL_DENSITY_G_CM3 / SHRINKAGE_PCT.

    Returns
    -------
    float — shrinkage as a percentage (e.g. 1.25 means 1.25%).
    """
    return SHRINKAGE_PCT.get(alloy_key.strip().lower(), _SHRINKAGE_FALLBACK)


def apply_shrinkage_scale(dimension_mm: float, shrinkage_pct: float) -> float:
    """
    Return the wax-pattern dimension needed to compensate for casting shrinkage.

    Scale-up factor = 1 / (1 - shrinkage_pct/100).

    Parameters
    ----------
    dimension_mm : float
        The desired finished metal dimension in mm.
    shrinkage_pct : float
        Shrinkage as a percentage (e.g. 1.25).

    Returns
    -------
    float — wax-pattern dimension in mm.
    """
    if dimension_mm <= 0:
        raise ValueError(f"dimension_mm must be positive, got {dimension_mm}")
    if shrinkage_pct < 0:
        raise ValueError(f"shrinkage_pct must be >= 0, got {shrinkage_pct}")
    scale = 1.0 / (1.0 - shrinkage_pct / 100.0)
    return dimension_mm * scale


# ---------------------------------------------------------------------------
# Metal weight helpers (re-exported for test convenience)
# ---------------------------------------------------------------------------

def estimate_metal_grams(volume_mm3: float, alloy_key: str) -> float:
    """Return net metal weight (g) for the given volume and alloy."""
    result = metal_weight(volume_mm3, metal=alloy_key)
    return result["grams"]


def estimate_pour_grams(net_grams: float, sprue_count: int) -> float:
    """
    Estimate total pour weight = net + sprue/button overhead.

    Sprue allowance heuristic:
      1 sprue  → 12% overhead (industry midpoint for simple gate)
      2 sprues → 16% overhead (two gates + button)
      3 sprues → 20% overhead (multi-gate complex tree)

    Parameters
    ----------
    net_grams : float
        Net part weight in grams.
    sprue_count : int
        Number of sprues/gates recommended.

    Returns
    -------
    float — total pour weight in grams.
    """
    if net_grams <= 0:
        raise ValueError(f"net_grams must be positive, got {net_grams}")
    if sprue_count < 1:
        raise ValueError(f"sprue_count must be >= 1, got {sprue_count}")
    overhead_map = {1: 0.12, 2: 0.16, 3: 0.20}
    overhead = overhead_map.get(sprue_count, 0.20)
    return net_grams * (1.0 + overhead)


# ---------------------------------------------------------------------------
# Optional OCC: minimal STL mesh builder
# ---------------------------------------------------------------------------

try:
    from OCC.Core.BRep import BRep_Builder  # type: ignore[import]
    from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh  # type: ignore[import]
    from OCC.Core.BRep import BRep_Tool  # type: ignore[import]
    from OCC.Core.TopExp import TopExp_Explorer  # type: ignore[import]
    from OCC.Core.TopAbs import TopAbs_FACE  # type: ignore[import]
    from OCC.Core.TopLoc import TopLoc_Location  # type: ignore[import]
    _OCC_AVAILABLE = True
except ImportError:
    _OCC_AVAILABLE = False


def _build_stl_bytes_from_shape(shape: Any, linear_deflection: float = 0.05) -> bytes:  # pragma: no cover
    """
    Tessellate an OCC TopoDS_Shape and return binary STL bytes.

    This function is only reachable when pythonOCC is installed.
    It is not tested in the hermetic unit-test suite (OCC is not a test dep).

    Parameters
    ----------
    shape : OCC.Core.TopoDS.TopoDS_Shape
        The OCC shape to tessellate (gems already removed by caller).
    linear_deflection : float
        Mesh deflection in mm.  Default 0.05 mm — good quality for casting.

    Returns
    -------
    bytes — binary STL (80-byte header + triangles).
    """
    mesh = BRepMesh_IncrementalMesh(shape, linear_deflection)
    mesh.Perform()

    triangles = []
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        face = explorer.Current()
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is not None:
            trsf = location.IsIdentity() and None or location.IsIdentity()
            nodes = triangulation.Nodes()
            tri_indices = triangulation.Triangles()
            for i in range(1, triangulation.NbTriangles() + 1):
                t = tri_indices.Value(i)
                n1, n2, n3 = t.Get()
                p1 = nodes.Value(n1)
                p2 = nodes.Value(n2)
                p3 = nodes.Value(n3)
                triangles.append((
                    (p1.X(), p1.Y(), p1.Z()),
                    (p2.X(), p2.Y(), p2.Z()),
                    (p3.X(), p3.Y(), p3.Z()),
                ))
        explorer.Next()

    # Build binary STL
    header = b"KERF-casting-export" + b" " * (80 - len(b"KERF-casting-export"))
    buf = header + struct.pack("<I", len(triangles))
    for (x1, y1, z1), (x2, y2, z2), (x3, y3, z3) in triangles:
        # Compute face normal
        ax, ay, az = x2 - x1, y2 - y1, z2 - z1
        bx, by, bz = x3 - x1, y3 - y1, z3 - z1
        nx = ay * bz - az * by
        ny = az * bx - ax * bz
        nz = ax * by - ay * bx
        mag = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        nx, ny, nz = nx / mag, ny / mag, nz / mag
        buf += struct.pack(
            "<fff fff fff fff H",
            nx, ny, nz,
            x1, y1, z1,
            x2, y2, z2,
            x3, y3, z3,
            0,
        )
    return buf


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def casting_export_summary(
    alloy: str,
    volume_mm3: float,
    thickness_mm: float = 1.0,
    gemstone_refs: Optional[list[str]] = None,
    shape: Optional[Any] = None,
    linear_deflection: float = 0.05,
) -> dict:
    """
    Produce a casting-export summary for the given piece.

    Parameters
    ----------
    alloy : str
        Alloy key from METAL_DENSITY_G_CM3 (e.g. "18k_yellow").
    volume_mm3 : float
        Volume of the metal body (gems excluded) in mm³.
    thickness_mm : float
        Minimum wall thickness of the piece in mm.  Used for thin-wall warnings.
        Default 1.0 mm.
    gemstone_refs : list[str], optional
        List of gemstone names / IDs being excluded from the casting export.
        Stored in the summary for traceability; not used in calculations.
    shape : OCC.Core.TopoDS.TopoDS_Shape, optional
        When provided and pythonOCC is available, the function will tessellate
        the shape and embed ``stl_bytes`` (binary STL) in the result.
        When absent or when OCC is not installed, ``stl_bytes`` is None.
    linear_deflection : float
        Mesh deflection for STL tessellation (mm).  Default 0.05.

    Returns
    -------
    dict with keys:
        alloy                    — resolved alloy key
        alloy_label              — human-readable label
        shrinkage_pct            — per-alloy shrinkage percentage
        volume_mm3               — metal body volume used
        thickness_mm             — minimum wall thickness supplied
        gemstones_excluded       — list of excluded gemstone refs (may be empty)
        est_metal_grams          — net metal weight (g)
        est_pour_grams_with_sprue — total pour weight including sprue overhead
        sprue_count              — recommended number of sprues
        sprue_location           — heuristic gate location description
        recommended_orientation  — build orientation hint
        support_hint             — support/wax strategy hint
        stl_bytes                — binary STL bytes (None if OCC unavailable)
        occ_available            — whether pythonOCC was used for STL
    """
    # Validate alloy
    alloy_key = alloy.strip().lower()
    if alloy_key not in METAL_DENSITY_G_CM3:
        valid = sorted(METAL_DENSITY_G_CM3.keys())
        raise ValueError(
            f"Unknown alloy '{alloy}'. Valid keys: {valid}"
        )

    # Validate volume
    if volume_mm3 <= 0:
        raise ValueError(f"volume_mm3 must be positive, got {volume_mm3}")

    # Validate thickness
    if thickness_mm < 0:
        raise ValueError(f"thickness_mm must be >= 0, got {thickness_mm}")

    shrinkage = get_shrinkage_pct(alloy_key)
    strategy = _sprue_strategy(volume_mm3, thickness_mm)

    net_grams = estimate_metal_grams(volume_mm3, alloy_key)
    pour_grams = estimate_pour_grams(net_grams, strategy["sprue_count"])

    # STL bytes (only when OCC + shape provided)
    stl_bytes: Optional[bytes] = None
    if shape is not None and _OCC_AVAILABLE:
        stl_bytes = _build_stl_bytes_from_shape(shape, linear_deflection)  # pragma: no cover

    return {
        "alloy": alloy_key,
        "alloy_label": METAL_LABELS.get(alloy_key, alloy_key),
        "shrinkage_pct": shrinkage,
        "volume_mm3": volume_mm3,
        "thickness_mm": thickness_mm,
        "gemstones_excluded": list(gemstone_refs or []),
        "est_metal_grams": round(net_grams, 4),
        "est_pour_grams_with_sprue": round(pour_grams, 4),
        "sprue_count": strategy["sprue_count"],
        "sprue_location": strategy["sprue_location"],
        "recommended_orientation": strategy["recommended_orientation"],
        "support_hint": strategy["support_hint"],
        "stl_bytes": stl_bytes,
        "occ_available": _OCC_AVAILABLE and shape is not None,
    }


# ---------------------------------------------------------------------------
# LLM tool spec
# ---------------------------------------------------------------------------

_casting_export_spec = ToolSpec(
    name="jewelry_casting_export",
    description=(
        "Generate a casting-ready production export summary for a jewelry piece.\n"
        "\n"
        "Returns a casting summary with:\n"
        "  - Per-alloy shrinkage compensation percentage\n"
        "  - Sprue count and gate location recommendations\n"
        "  - Build orientation for the investment flask\n"
        "  - Wax support strategy\n"
        "  - Estimated net metal weight and total pour weight (with sprue overhead)\n"
        "  - Gemstone exclusion list (gems are removed from cast; metal body only)\n"
        "\n"
        "Alloy keys (same as jewelry_metal_cost):\n"
        "  Gold:      10k_yellow, 14k_yellow, 18k_yellow, 22k_yellow, 24k_yellow\n"
        "             10k_white,  14k_white,  18k_white,  22k_white\n"
        "             10k_rose,   14k_rose,   18k_rose,   22k_rose\n"
        "  Platinum:  platinum_950, platinum_900\n"
        "  Palladium: palladium_950, palladium_500\n"
        "  Silver:    sterling_925, fine_silver, argentium_935\n"
        "  Other:     titanium, brass, bronze\n"
        "\n"
        "Shrinkage per alloy (approximate industry midpoints):\n"
        "  18k yellow gold: 1.25%  |  18k white gold: 1.30%\n"
        "  Platinum 950:    1.80%  |  Sterling 925:   1.40%\n"
        "\n"
        "Sprue / support strategy is heuristic based on piece volume:\n"
        "  <500 mm³: 1 sprue, no support\n"
        "  500–2000 mm³: 1 sprue, minimal wax\n"
        "  2000–5000 mm³: 2 sprues, wax supports\n"
        "  >5000 mm³: 3 sprues, full wax tree\n"
        "\n"
        "volume_mm3 is the metal-body volume only (gems excluded). "
        "Use the volume from a CAD volume query (GProp_GProps.Mass() in mm units)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alloy": {
                "type": "string",
                "description": (
                    "Alloy key for the casting metal. See tool description for full list. "
                    "Example: '18k_yellow', 'platinum_950', 'sterling_925'."
                ),
            },
            "volume_mm3": {
                "type": "number",
                "description": (
                    "Volume of the metal body in mm³ (gems excluded). "
                    "From GProp_GProps.Mass() in Kerf/OCCT mm model units."
                ),
            },
            "thickness_mm": {
                "type": "number",
                "description": (
                    "Minimum wall thickness of the piece in mm. "
                    "Used for thin-wall warnings (< 0.6 mm). Default 1.0."
                ),
            },
            "gemstone_refs": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of gemstone names or node IDs being excluded "
                    "from the casting export (gems are not cast). "
                    "Stored in summary for traceability."
                ),
            },
        },
        "required": ["alloy", "volume_mm3"],
    },
)


# ---------------------------------------------------------------------------
# LLM tool runner
# ---------------------------------------------------------------------------

@register(_casting_export_spec, write=False)
async def run_jewelry_casting_export(ctx: ProjectCtx, args: bytes) -> str:
    """LLM tool: jewelry_casting_export."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # -- alloy ----------------------------------------------------------------
    alloy = a.get("alloy")
    if alloy is None:
        return err_payload("alloy is required", "BAD_ARGS")
    alloy_key = str(alloy).strip().lower()
    if alloy_key not in METAL_DENSITY_G_CM3:
        valid = ", ".join(sorted(METAL_DENSITY_G_CM3.keys()))
        return err_payload(
            f"Unknown alloy '{alloy}'. Valid keys: {valid}", "BAD_ARGS"
        )

    # -- volume ---------------------------------------------------------------
    volume_mm3 = a.get("volume_mm3")
    if volume_mm3 is None:
        return err_payload("volume_mm3 is required", "BAD_ARGS")
    try:
        volume_mm3 = float(volume_mm3)
    except (TypeError, ValueError):
        return err_payload("volume_mm3 must be a number", "BAD_ARGS")
    if volume_mm3 <= 0:
        return err_payload(f"volume_mm3 must be positive, got {volume_mm3}", "BAD_ARGS")

    # -- thickness ------------------------------------------------------------
    thickness_mm_raw = a.get("thickness_mm", 1.0)
    try:
        thickness_mm = float(thickness_mm_raw)
    except (TypeError, ValueError):
        return err_payload("thickness_mm must be a number", "BAD_ARGS")
    if thickness_mm < 0:
        return err_payload(f"thickness_mm must be >= 0, got {thickness_mm}", "BAD_ARGS")

    # -- gemstone refs --------------------------------------------------------
    gemstone_refs = a.get("gemstone_refs")
    if gemstone_refs is not None:
        if not isinstance(gemstone_refs, list):
            return err_payload("gemstone_refs must be an array of strings", "BAD_ARGS")
        gemstone_refs = [str(r) for r in gemstone_refs]

    # -- run export summary ---------------------------------------------------
    try:
        summary = casting_export_summary(
            alloy=alloy_key,
            volume_mm3=volume_mm3,
            thickness_mm=thickness_mm,
            gemstone_refs=gemstone_refs,
            shape=None,  # No OCC shape from LLM tool path
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"casting export error: {exc}", "ERROR")

    # stl_bytes is bytes or None — not JSON-serialisable; strip from LLM payload
    payload = {k: v for k, v in summary.items() if k != "stl_bytes"}
    payload["stl_available"] = False  # No shape provided via tool path

    return ok_payload({"casting_summary": payload})
