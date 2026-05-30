"""subd_gauss_bonnet_check.py
============================
Gauss-Bonnet theorem verification for Catmull-Clark SubD limit surfaces.

Checks the identity:

    ∫∫ K dA = 2π · χ

where K is Gaussian curvature, χ = V − E + F is the Euler characteristic
of the cage, and the integral is over the CC limit surface.

Method
------
1. ``integrate_gaussian_curvature(cage)`` from ``subd_limit_integrals`` is
   called for ∫∫K dA.  That function uses the discrete Gauss-Bonnet angle-
   deficit sum on the Stam-limit-position mesh (see Polthier-Schmies 1998).

2. χ is computed directly from the cage topology: V − E + F (independent of
   any subdivision level).

3. The check passes when |∫∫K dA − 2π·χ| < tolerance × |2π·χ|.
   Default tolerance = 0.05 (5 %).  For χ = 0 (torus, etc.) an absolute
   tolerance of 0.5 is used instead.

Honest-flag (boundary surfaces)
--------------------------------
The Gauss-Bonnet theorem for surfaces **with boundary** includes an extra
geodesic-curvature boundary integral:

    ∫∫ K dA + ∫_∂M κ_g ds + Σ exterior_angles = 2π · χ(M)

(do Carmo §4.5, eq. 4-19; Edelsbrunner-Harer 2010 §1.4)

This implementation sums angle deficits at **interior** vertices only, so
it naturally gives 2πχ for **closed** surfaces.  For surfaces with boundary
the returned ``integral_K`` is the partial sum (interior-vertex deficits
only) and ``valid`` will be False if the cage has boundary edges.  Users
who need the full Gauss-Bonnet check for surfaces-with-boundary must supply
the boundary geodesic curvature term separately.

References
----------
* do Carmo, M. P. (1976/2016). "Differential Geometry of Curves and
  Surfaces", §4.5 (Global Gauss-Bonnet theorem, pp. 274-282).
* Edelsbrunner, H. & Harer, J. (2010). "Computational Topology: An
  Introduction", Chapter 1 (pp. 9-32, Euler characteristic; §1.4 Gauss-
  Bonnet for smooth surfaces).
* Polthier, K. & Schmies, M. (1998). "Straightest geodesics on polyhedral
  surfaces", §2 (angle-deficit discrete Gauss-Bonnet).
* Stam, J. (1998). "Exact Evaluation of Catmull-Clark Subdivision Surfaces
  at Arbitrary Parameter Values", SIGGRAPH 98.

Public API
----------
GaussBonnetCheckReport   dataclass with all results + diagnostics
verify_gauss_bonnet(cage, tolerance=0.05) -> GaussBonnetCheckReport

LLM tool
--------
subd_verify_gauss_bonnet
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_limit_integrals import integrate_gaussian_curvature


# ---------------------------------------------------------------------------
# Euler characteristic from cage topology
# ---------------------------------------------------------------------------

def _euler_characteristic_cage(cage: SubDMesh) -> int:
    """Compute χ = V − E + F directly from the cage (no subdivision).

    Counts undirected edges by iterating all face half-edges and
    deduplicating via a frozenset key.
    """
    V = len(cage.vertices)
    F = len(cage.faces)
    edges: set = set()
    for face in cage.faces:
        n = len(face)
        for k in range(n):
            a, b = face[k], face[(k + 1) % n]
            edges.add((min(a, b), max(a, b)))
    E = len(edges)
    return V - E + F


def _has_boundary(cage: SubDMesh) -> bool:
    """Return True if the cage has any boundary (open) edges."""
    edge_count: dict = {}
    for face in cage.faces:
        n = len(face)
        for k in range(n):
            a, b = face[k], face[(k + 1) % n]
            key = (min(a, b), max(a, b))
            edge_count[key] = edge_count.get(key, 0) + 1
    return any(c == 1 for c in edge_count.values())


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------

@dataclass
class GaussBonnetCheckReport:
    """Results of the Gauss-Bonnet theorem verification on a CC SubD cage.

    Attributes
    ----------
    integral_K : float
        ∫∫ K dA computed via the discrete Gauss-Bonnet angle-deficit sum on
        the Stam-limit-position mesh (interior vertices only for surfaces
        with boundary).
    expected_2pi_chi : float
        2π · χ — the theoretically expected value for a closed surface.
    chi_from_cage : int
        Euler characteristic χ = V − E + F of the input cage.
    relative_error : float
        |integral_K − expected_2pi_chi| / |expected_2pi_chi|.
        For χ = 0 (torus etc.), ``float('nan')``; use ``absolute_error``.
    absolute_error : float
        |integral_K − expected_2pi_chi|.
    valid : bool
        True when the Gauss-Bonnet check passes within tolerance.
        - For χ ≠ 0: relative_error < tolerance.
        - For χ = 0: absolute_error < abs_tolerance (default 0.5).
        - Always False for surfaces with boundary (honest-flag; the full
          Gauss-Bonnet-with-boundary-term is not computed here).
    tolerance : float
        Relative tolerance used for the check (default 0.05 = 5%).
    has_boundary : bool
        True if the cage has open (boundary) edges.
    boundary_honest_flag : str
        Human-readable caveat when the cage has boundary edges.
    subd_levels : int
        CC pre-subdivision levels used for the integral.

    Notes
    -----
    Sphere (χ=2):       expected_2pi_chi = 4π ≈ 12.566
    Torus (χ=0):        expected_2pi_chi = 0;  integral_K ≈ 0
    Double-torus (χ=-2): expected_2pi_chi = -4π ≈ -12.566
    """
    integral_K: float = 0.0
    expected_2pi_chi: float = 0.0
    chi_from_cage: int = 0
    relative_error: float = float("nan")
    absolute_error: float = 0.0
    valid: bool = False
    tolerance: float = 0.05
    has_boundary: bool = False
    boundary_honest_flag: str = ""
    subd_levels: int = 3


_BOUNDARY_FLAG = (
    "HONEST FLAG: This cage has boundary edges.  The classical Gauss-Bonnet "
    "theorem for surfaces-with-boundary requires an additional geodesic-curvature "
    "boundary integral ∫_∂M κ_g ds + Σ exterior-angles (do Carmo §4.5 eq. 4-19; "
    "Edelsbrunner-Harer 2010 §1.4).  Only interior-vertex angle deficits are "
    "summed here; the result is NOT comparable to 2π·χ for an open surface.  "
    "valid=False is set unconditionally for surfaces with boundary."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_gauss_bonnet(
    cage: SubDMesh,
    tolerance: float = 0.05,
    subd_levels: int = 3,
    abs_tolerance_chi_zero: float = 0.5,
) -> GaussBonnetCheckReport:
    """Verify the Gauss-Bonnet theorem on a Catmull-Clark SubD limit surface.

    Checks  ∫∫ K dA = 2π · χ  within the specified tolerance.

    Parameters
    ----------
    cage : SubDMesh
        Catmull-Clark control cage.  The cage topology determines χ; the
        CC limit surface is used for the integral.
    tolerance : float
        Relative tolerance for the check (default 0.05 = 5 %).
        For χ ≠ 0: passes when |integral_K − 2π·χ| / |2π·χ| < tolerance.
        For χ = 0: passes when |integral_K| < abs_tolerance_chi_zero.
    subd_levels : int
        CC pre-subdivision levels for ``integrate_gaussian_curvature``
        (default 3).  Higher values give more accuracy near extraordinary
        vertices.
    abs_tolerance_chi_zero : float
        Absolute tolerance used when χ = 0 (default 0.5).

    Returns
    -------
    GaussBonnetCheckReport

    Notes — depth bar (do Carmo §4.5; Edelsbrunner-Harer 2010)
    -----------------------------------------------------------
    Sphere (χ=2):       ∫∫K dA = 4π ≈ 12.566  — expect valid within 5 %.
    Torus (χ=0):        ∫∫K dA = 0             — expect |Δ| < 0.5.
    Double-torus (χ=-2): ∫∫K dA = -4π ≈ -12.566 — expect valid within 5 %.

    Honest-flag: boundary surfaces
    --------------------------------
    The full Gauss-Bonnet theorem for M with boundary ∂M adds:
        ∫_∂M κ_g ds + Σ θ_i = 2π·χ(M) − ∫∫_M K dA
    (do Carmo §4.5, eq. 4-19).  This function only computes the area
    integral term; for cages with open edges valid=False is set and a
    boundary_honest_flag is included in the report.
    """
    chi = _euler_characteristic_cage(cage)
    has_bd = _has_boundary(cage)
    expected = 2.0 * math.pi * chi

    integral_K = integrate_gaussian_curvature(cage, subd_levels=subd_levels)

    abs_err = abs(integral_K - expected)

    if chi != 0:
        rel_err = abs_err / abs(expected) if abs(expected) > 1e-15 else float("nan")
    else:
        rel_err = float("nan")

    if has_bd:
        valid = False
        boundary_flag = _BOUNDARY_FLAG
    elif chi == 0:
        valid = abs_err < abs_tolerance_chi_zero
        boundary_flag = ""
    else:
        valid = (not math.isnan(rel_err)) and rel_err < tolerance
        boundary_flag = ""

    return GaussBonnetCheckReport(
        integral_K=float(integral_K),
        expected_2pi_chi=float(expected),
        chi_from_cage=chi,
        relative_error=rel_err,
        absolute_error=float(abs_err),
        valid=valid,
        tolerance=tolerance,
        has_boundary=has_bd,
        boundary_honest_flag=boundary_flag,
        subd_levels=subd_levels,
    )


# ---------------------------------------------------------------------------
# LLM tool
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

    _spec_gb = ToolSpec(
        name="subd_verify_gauss_bonnet",
        description=(
            "Verify the Gauss-Bonnet theorem on a Catmull-Clark SubD limit surface.\n"
            "\n"
            "Checks  ∫∫ K dA = 2π·χ  where χ = V−E+F of the cage.\n"
            "\n"
            "Oracle values (do Carmo §4.5):\n"
            "  Sphere (χ=2):        ∫∫K dA = 4π ≈ 12.566  (expect valid within 5%)\n"
            "  Torus  (χ=0):        ∫∫K dA = 0            (expect |Δ| < 0.5)\n"
            "  Double-torus (χ=-2): ∫∫K dA = -4π ≈ -12.566\n"
            "\n"
            "HONEST FLAG: surfaces with open boundary edges return valid=False because\n"
            "the full Gauss-Bonnet theorem includes a boundary geodesic-curvature\n"
            "integral (do Carmo §4.5 eq. 4-19) not computed here.\n"
            "\n"
            "Inputs:\n"
            "  vertices     : [[x,y,z], ...]  control cage vertices.\n"
            "  faces        : [[i,j,k,l], ...]  quad face index lists.\n"
            "  tolerance    : float  relative tolerance (default 0.05 = 5%).\n"
            "  subd_levels  : int   CC pre-subdivision depth (default 3).\n"
            "\n"
            "Returns:\n"
            "  { ok, integral_K, expected_2pi_chi, chi_from_cage,\n"
            "    relative_error, absolute_error, valid, has_boundary,\n"
            "    boundary_honest_flag, tolerance, subd_levels }"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 4,
                },
                "faces": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
                "tolerance": {"type": "number", "default": 0.05, "minimum": 0.0, "maximum": 1.0},
                "subd_levels": {"type": "integer", "default": 3, "minimum": 0, "maximum": 6},
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_spec_gb)
    async def run_subd_verify_gauss_bonnet(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")
        try:
            verts = [[float(c) for c in row] for row in a.get("vertices", [])]
            faces = [[int(i) for i in f] for f in a.get("faces", [])]
            tol = float(a.get("tolerance", 0.05))
            lvl = int(a.get("subd_levels", 3))
            cage = SubDMesh(vertices=verts, faces=faces)
        except Exception as exc:
            return err_payload(f"invalid cage: {exc}", "BAD_ARGS")

        rpt = verify_gauss_bonnet(cage, tolerance=tol, subd_levels=lvl)

        rel_err = rpt.relative_error
        return ok_payload({
            "ok": True,
            "integral_K": rpt.integral_K,
            "expected_2pi_chi": rpt.expected_2pi_chi,
            "chi_from_cage": rpt.chi_from_cage,
            "relative_error": None if (isinstance(rel_err, float) and math.isnan(rel_err)) else rel_err,
            "absolute_error": rpt.absolute_error,
            "valid": rpt.valid,
            "has_boundary": rpt.has_boundary,
            "boundary_honest_flag": rpt.boundary_honest_flag,
            "tolerance": rpt.tolerance,
            "subd_levels": rpt.subd_levels,
        })
