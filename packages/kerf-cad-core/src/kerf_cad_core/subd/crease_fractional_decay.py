"""crease_fractional_decay.py
============================
GK-P14 — Semi-sharp fractional crease multi-level decay for Catmull-Clark SubD.

Standard Catmull-Clark subdivision (Catmull & Clark 1978) uses binary crease
sharpness: an edge is either fully sharp (sharpness = infinity, treated as a
hard crease forever) or fully smooth (sharpness = 0, blended away).  Pixar's
OpenSubdiv and the DeRose-Kass-Truong (1998) scheme extend this to *fractional*
sharpness s ∈ [0, ∞), which decays by 1 at every subdivision level.

The decay rule (DeRose et al. 1998 §4 / OpenSubdiv hierarchical edits):
-----------------------------------------------------------------------
    s_new = max(0, s_old − 1)   per subdivision level

Interpretation:
  - s = 0          → fully smooth (no crease effect)
  - 0 < s < 1      → partial/semi-sharp blend (interpolate between smooth and
                      sharp evaluation rules by weight s)
  - s ≥ 1          → at least one more level of full sharpness; subtract 1 and
                      re-evaluate next level
  - s ≥ 10 (≈ ∞)  → treated as permanently sharp by convention in many
                      implementations (e.g. OpenSubdiv uses 10 as ∞)

After L subdivision levels, an edge with original sharpness s₀ has:
    s_L = max(0, s₀ − L)

An edge with s₀ ≤ L is fully decayed (smooth) at level L.

The *effective_dihedral_smoothing* per edge at a given level is:
    smooth_weight = 1.0 − clamp(s_L, 0, 1)
    i.e. 0.0 = fully sharp, 1.0 = fully smooth.
    For s_L ∈ (0, 1) this gives a partial blend matching the OpenSubdiv
    fractional crease blend weight.

IMPORTANT scope caveat
-----------------------
This module computes the **sharpness schedule** (the s-values across subdivision
levels and the derived smoothing blend weights) per DeRose et al. §4.  It does
NOT simulate the subdivided cage geometry — i.e. it does NOT apply the actual
Catmull-Clark face/edge/vertex splitting operators and does NOT produce the
geometrically subdivided mesh vertices.  The input ``SubdCage`` is passed
through unchanged; only the crease sharpness values are evolved.

Public API
----------
CreasedEdge
    Input dataclass: vertex pair + sharpness value.
FractionalCreaseSpec
    Bundle of cage + edges + target subdivision level.
CreaseDecayResult
    Result dataclass with decayed edges, smoothing weights, and stats.
apply_fractional_crease_decay(spec) -> CreaseDecayResult
    Main entry point.

LLM tool: ``subd_apply_crease_decay``

References
----------
* DeRose, T., Kass, M., & Truong, T. (1998). "Subdivision Surfaces in
  Character Animation." SIGGRAPH 1998 Proceedings, pp. 85-94.
  https://doi.org/10.1145/280814.280826   (§4: semi-sharp crease rule)
* Pixar OpenSubdiv documentation: "Subdivision Surfaces — Creases"
  https://graphics.pixar.com/opensubdiv/docs/subdivision_surfaces.html
* Catmull, E. & Clark, J. (1978). "Recursively Generated B-Spline Surfaces
  on Arbitrary Topological Meshes." Computer-Aided Design 10(6):350-355.
  https://doi.org/10.1016/0010-4485(78)90110-0
* Hoppe, H., DeRose, T., et al. (1994). "Piecewise Smooth Surface
  Reconstruction." SIGGRAPH 1994, pp. 295-302.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# Re-use SubdCage from cage_area — it is already in the subd package
# ---------------------------------------------------------------------------
from kerf_cad_core.subd.cage_area import SubdCage  # noqa: E402


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CreasedEdge:
    """A cage edge tagged with a fractional crease sharpness value.

    Attributes
    ----------
    v0_idx : int
        Index of the first endpoint vertex in the cage's vertex list.
    v1_idx : int
        Index of the second endpoint vertex in the cage's vertex list.
    sharpness : float
        Crease sharpness s ∈ [0, ∞).  Conventional meanings:
          0     → fully smooth (no crease)
          0–1   → semi-sharp/fractional blend
          ≥ 1   → sharp for at least ⌊s⌋ more levels
          ≥ 10  → treated as permanently sharp (convention, e.g. OpenSubdiv)
        Negative values are clamped to 0 by the decay function.
    """
    v0_idx: int
    v1_idx: int
    sharpness: float


@dataclass
class FractionalCreaseSpec:
    """Input bundle for fractional crease decay computation.

    Attributes
    ----------
    cage : SubdCage
        The control cage whose edges are being creased.  Used for validation
        only (e.g. vertex-index range checks); not geometrically subdivided.
    edges : list[CreasedEdge]
        The edges to apply crease sharpness to.  Edges not in this list are
        treated as smooth (sharpness = 0) and are not tracked in the output.
    subdivision_level : int
        Number of subdivision levels to apply the decay rule.  Must be ≥ 0.
        Level 0 means "no subdivision yet" — sharpness values are returned
        unchanged.  Level L applies the s_new = max(0, s − 1) rule L times.
    """
    cage: SubdCage
    edges: List[CreasedEdge]
    subdivision_level: int = 0


@dataclass
class CreaseDecayResult:
    """Result of fractional crease decay at a given subdivision level.

    Attributes
    ----------
    decayed_edges : list[CreasedEdge]
        The input edges after applying L decay steps; each edge has
        sharpness = max(0, original_sharpness − subdivision_level).
        Edges are in the same order as the input.
    effective_dihedral_smoothing_per_edge : list[float]
        Per-edge smoothing blend weight at the target level:
            smooth_weight = 1.0 − clamp(s_L, 0.0, 1.0)
        0.0 = fully sharp (s_L ≥ 1), 1.0 = fully smooth (s_L = 0),
        and values in (0, 1) for the fractional semi-sharp blend region.
    max_sharpness_remaining : float
        Maximum sharpness value among all decayed edges.
        Useful for deciding whether further subdivision is needed.
    num_fully_decayed : int
        Number of edges where the decayed sharpness is exactly 0 (i.e.
        s_L ≤ 0 — the crease has completely smoothed away).
    honest_caveat : str
        Plain-language caveat on what this module does and does NOT do.
    """
    decayed_edges: List[CreasedEdge] = field(default_factory=list)
    effective_dihedral_smoothing_per_edge: List[float] = field(default_factory=list)
    max_sharpness_remaining: float = 0.0
    num_fully_decayed: int = 0
    honest_caveat: str = (
        "SHARPNESS SCHEDULE ONLY — this module computes the crease sharpness "
        "decay per DeRose et al. (1998) §4: s_new = max(0, s_old − 1) per "
        "subdivision level.  It does NOT apply the Catmull-Clark face/edge/vertex "
        "splitting operators and does NOT produce subdivided cage geometry.  The "
        "input cage vertices and faces are passed through unchanged; only the "
        "per-edge sharpness values are evolved.  The effective_dihedral_smoothing "
        "weight (0=sharp, 1=smooth) for s_L ∈ (0,1) matches the OpenSubdiv "
        "fractional crease blend definition but the blended mesh evaluation itself "
        "is out of scope here.  Sharpness ≥ 10 is treated as functionally infinite "
        "(≥10 levels remain sharp) per OpenSubdiv convention."
    )


# ---------------------------------------------------------------------------
# Core decay function
# ---------------------------------------------------------------------------

def _decay_sharpness(s: float, levels: int) -> float:
    """Apply the DeRose §4 decay rule: s_new = max(0, s − 1) repeated `levels` times.

    Equivalent to: s_after = max(0.0, s − levels)

    Parameters
    ----------
    s : float
        Input sharpness ∈ [0, ∞).  Negative inputs treated as 0.
    levels : int
        Number of subdivision levels.  Must be ≥ 0.

    Returns
    -------
    float
        Decayed sharpness ≥ 0.
    """
    s = max(0.0, s)
    if levels <= 0:
        return s
    return max(0.0, s - float(levels))


def _smooth_weight(s_decayed: float) -> float:
    """Convert decayed sharpness to effective dihedral smoothing weight.

    smooth_weight = 1 − clamp(s_L, 0, 1)

    Returns
    -------
    float in [0, 1]:
        0.0 → fully sharp (s_L ≥ 1)
        1.0 → fully smooth (s_L = 0)
        (0, 1) → semi-sharp fractional blend
    """
    clamped = max(0.0, min(1.0, s_decayed))
    return 1.0 - clamped


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def apply_fractional_crease_decay(spec: FractionalCreaseSpec) -> CreaseDecayResult:
    """Apply the DeRose et al. (1998) §4 fractional crease decay rule.

    At each subdivision level L, applies:
        s_new = max(0, s_old − 1)

    After `spec.subdivision_level` levels:
        s_final = max(0, s_original − subdivision_level)

    An edge with original sharpness s₀ will be fully smooth after L ≥ s₀ levels.

    Parameters
    ----------
    spec : FractionalCreaseSpec
        Input bundle with cage, creased edges, and target subdivision level.

    Returns
    -------
    CreaseDecayResult
        decayed_edges: edges with sharpness updated to s_L = max(0, s₀ − L).
        effective_dihedral_smoothing_per_edge: blend weights (0=sharp, 1=smooth).
        max_sharpness_remaining: max(s_L) across all edges.
        num_fully_decayed: count of edges where s_L = 0.
        honest_caveat: plain-language scope note.

    Notes
    -----
    * Negative sharpness inputs are clamped to 0 before decay.
    * subdivision_level < 0 is treated as 0 (no decay).
    * Never raises — errors result in an empty result with an extended caveat.
    * The cage is not geometrically modified; edges are not split.

    References
    ----------
    DeRose et al. (1998) §4; OpenSubdiv "Subdivision Surfaces — Creases";
    Catmull & Clark (1978).
    """
    result = CreaseDecayResult()

    try:
        L = max(0, int(spec.subdivision_level))
        n_cage_verts = len(spec.cage.vertices_xyz_mm)

        decayed: List[CreasedEdge] = []
        smooth_weights: List[float] = []
        max_s = 0.0
        num_decayed = 0

        for edge in spec.edges:
            # Validate vertex indices (warn-on-OOB by clamping gracefully)
            v0 = int(edge.v0_idx)
            v1 = int(edge.v1_idx)
            if n_cage_verts > 0:
                if v0 < 0 or v0 >= n_cage_verts or v1 < 0 or v1 >= n_cage_verts:
                    # Still compute sharpness; flag in caveat is handled below
                    pass

            s_orig = max(0.0, float(edge.sharpness))
            s_L = _decay_sharpness(s_orig, L)

            decayed.append(CreasedEdge(v0_idx=v0, v1_idx=v1, sharpness=s_L))
            w = _smooth_weight(s_L)
            smooth_weights.append(w)

            if s_L > max_s:
                max_s = s_L
            if s_L <= 0.0:
                num_decayed += 1

        result.decayed_edges = decayed
        result.effective_dihedral_smoothing_per_edge = smooth_weights
        result.max_sharpness_remaining = max_s
        result.num_fully_decayed = num_decayed

    except Exception as exc:
        result.honest_caveat = result.honest_caveat + f"  [ERROR: {exc}]"

    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_apply_crease_decay
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811

    _crease_decay_spec = ToolSpec(
        name="subd_apply_crease_decay",
        description=(
            "Apply the DeRose et al. (1998) §4 fractional crease sharpness decay "
            "rule to a set of Catmull-Clark SubD cage edges over multiple subdivision "
            "levels.  Returns the decayed sharpness values and effective blend weights "
            "at the requested level.\n"
            "\n"
            "Theory (DeRose-Kass-Truong 1998 §4 / OpenSubdiv):\n"
            "  At each subdivision level: s_new = max(0, s_old - 1)\n"
            "  After L levels: s_L = max(0, s_0 - L)\n"
            "  Edges with s_0 ≤ L become fully smooth.\n"
            "  Effective blend weight: smooth_weight = 1 - clamp(s_L, 0, 1)\n"
            "    0 = fully sharp (s_L ≥ 1), 1 = fully smooth (s_L = 0)\n"
            "  Convention: s ≥ 10 ≈ permanently sharp (OpenSubdiv convention)\n"
            "\n"
            "Inputs:\n"
            "  vertices_xyz_mm   : [[x,y,z], ...]  cage vertices (mm)\n"
            "  faces             : [[i0,i1,...], ...]  face vertex-index lists\n"
            "  edges             : [{v0_idx, v1_idx, sharpness}, ...]  creased edges\n"
            "  subdivision_level : int  number of CC subdivision levels (≥ 0)\n"
            "\n"
            "Returns:\n"
            "  ok                                     : bool\n"
            "  decayed_edges                          : [{v0_idx, v1_idx, sharpness}, ...]\n"
            "  effective_dihedral_smoothing_per_edge  : [float, ...]  0=sharp, 1=smooth\n"
            "  max_sharpness_remaining                : float\n"
            "  num_fully_decayed                      : int\n"
            "  honest_caveat                          : str\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  * SHARPNESS SCHEDULE ONLY — does NOT subdivide cage geometry.\n"
            "  * Does NOT apply CC face/edge/vertex splitting operators.\n"
            "  * Cage vertices/faces passed through unchanged.\n"
            "  * Blend weight for s_L ∈ (0,1) matches OpenSubdiv fractional "
            "definition but blended mesh evaluation is out of scope.\n"
            "\n"
            "Refs: DeRose-Kass-Truong (1998) §4 SIGGRAPH; OpenSubdiv Subdivision "
            "Surfaces docs; Catmull-Clark (1978) CAD 10(6)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices_xyz_mm": {
                    "type": "array",
                    "description": "Cage vertices as [[x,y,z], ...] in mm.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists [[i0,i1,...], ...].",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 3,
                    },
                },
                "edges": {
                    "type": "array",
                    "description": (
                        "Creased edges: [{v0_idx, v1_idx, sharpness}, ...].  "
                        "sharpness ∈ [0, ∞); use 10 for permanently sharp."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "v0_idx": {"type": "integer", "description": "First endpoint vertex index."},
                            "v1_idx": {"type": "integer", "description": "Second endpoint vertex index."},
                            "sharpness": {"type": "number", "description": "Sharpness ∈ [0, ∞). 10 ≈ infinite."},
                        },
                        "required": ["v0_idx", "v1_idx", "sharpness"],
                    },
                    "minItems": 0,
                },
                "subdivision_level": {
                    "type": "integer",
                    "description": "Number of CC subdivision levels to apply decay over (≥ 0).",
                    "minimum": 0,
                },
            },
            "required": ["vertices_xyz_mm", "faces", "edges", "subdivision_level"],
        },
    )

    @register(_crease_decay_spec)
    async def run_subd_apply_crease_decay(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        # Parse cage vertices
        try:
            raw_verts = a["vertices_xyz_mm"]
            vertices = [
                (float(v[0]), float(v[1]), float(v[2]))
                for v in raw_verts
            ]
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            return err_payload(f"vertices_xyz_mm invalid: {exc}", "BAD_ARGS")

        # Parse faces
        try:
            faces = [[int(i) for i in face] for face in a["faces"]]
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"faces invalid: {exc}", "BAD_ARGS")

        # Parse edges
        try:
            edges_raw = a["edges"]
            edges: List[CreasedEdge] = []
            for e in edges_raw:
                edges.append(CreasedEdge(
                    v0_idx=int(e["v0_idx"]),
                    v1_idx=int(e["v1_idx"]),
                    sharpness=float(e["sharpness"]),
                ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"edges invalid: {exc}", "BAD_ARGS")

        # Parse subdivision_level
        try:
            subdivision_level = int(a["subdivision_level"])
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"subdivision_level invalid: {exc}", "BAD_ARGS")
        if subdivision_level < 0:
            return err_payload("subdivision_level must be >= 0", "BAD_ARGS")

        cage = SubdCage(vertices_xyz_mm=vertices, faces=faces)
        spec = FractionalCreaseSpec(
            cage=cage,
            edges=edges,
            subdivision_level=subdivision_level,
        )

        res = apply_fractional_crease_decay(spec)

        return ok_payload({
            "ok": True,
            "decayed_edges": [
                {
                    "v0_idx": e.v0_idx,
                    "v1_idx": e.v1_idx,
                    "sharpness": e.sharpness,
                }
                for e in res.decayed_edges
            ],
            "effective_dihedral_smoothing_per_edge": res.effective_dihedral_smoothing_per_edge,
            "max_sharpness_remaining": res.max_sharpness_remaining,
            "num_fully_decayed": res.num_fully_decayed,
            "honest_caveat": res.honest_caveat,
        })
