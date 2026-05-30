"""BREP-MESH-MASS-PROPS: volume, centroid, and inertia tensor from a triangle mesh.

Algorithm
---------
Uses the divergence theorem applied directly to a triangulated surface — the
same physical basis as mass_props.py, but operating on explicit triangles
rather than a parametric B-rep.

For each triangle with vertices v0, v1, v2 and area-weighted outward normal::

    d = (v1 - v0) × (v2 - v0)

the contributions are:

    Volume:    V = (1/6) Σ v0 · d
    Centroid:  Cx·V = (1/24) Σ dx · (x0²+x1²+x2²+x0x1+x0x2+x1x2)
    Second moments: ∫∫∫ x² dV = (1/60) Σ dx · f3(x0,x1,x2)  (Eberly 2002 eq. 11)
    Cross moments:  ∫∫∫ xy dV = (1/120) Σ dx · (y0·g0x+y1·g1x+y2·g2x)

where f3, g0, g1, g2 are computed by the Eberly recurrence (Table 1).

Principal axes are the eigenvectors of the symmetric inertia tensor (numpy.linalg.eigh).

References
----------
* Mirtich, B. (1996). Fast and Accurate Computation of Polyhedral Mass Properties.
  *Journal of Graphics Tools*, 1(2), 31–50.
* Mortenson, M.E. (1985). *Geometric Modeling*. Wiley, §11.4.
* Eberly, D. (2002). Polyhedral Mass Properties (Revisited). Geometric Tools.
  https://www.geometrictools.com/Documentation/PolyhedralMassProperties.pdf

Honest flags
------------
* Assumes a **closed, orientable mesh** with **outward-facing normals** (counter-
  clockwise winding when viewed from outside).
* **Open meshes**, **inverted normals**, or **non-manifold geometry** give wrong-sign
  or incorrect values.  The function raises ``ValueError`` when the computed signed
  volume is ≤ 0 (indicating an open or inside-out mesh); callers that need to
  handle open meshes should pass ``allow_open=True``.
* Near-degenerate triangles accumulate floating-point error in proportion to the
  number of triangles.
* Pure-Python + NumPy only; no OCCT, no Cython.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MassPropsReport:
    """Mass properties derived from a triangle mesh.

    Attributes
    ----------
    volume : float
        Signed volume (positive for outward-normal closed mesh).
    mass : float
        volume * density.
    centroid : numpy.ndarray, shape (3,)
        Centre of mass in world coordinates.
    inertia_tensor : numpy.ndarray, shape (3, 3)
        Symmetric inertia tensor about the centroid (kg·m² or consistent units).
    principal_moments : numpy.ndarray, shape (3,)
        Eigenvalues of ``inertia_tensor``, ascending order.
    principal_axes : numpy.ndarray, shape (3, 3)
        Columns are the principal-axis unit vectors (eigenvectors).
    triangle_count : int
        Number of triangles processed.
    """

    volume: float
    mass: float
    centroid: np.ndarray
    inertia_tensor: np.ndarray
    principal_moments: np.ndarray = field(default_factory=lambda: np.zeros(3))
    principal_axes: np.ndarray = field(default_factory=lambda: np.eye(3))
    triangle_count: int = 0


# ---------------------------------------------------------------------------
# Eberly recurrence for second-moment sub-expressions
# ---------------------------------------------------------------------------

def _eberly(a0: np.ndarray, a1: np.ndarray, a2: np.ndarray):
    """Eberly 2002 recurrence for polyhedral mass properties.

    Returns (f2, f3, g0, g1, g2) for one Cartesian coordinate.

    f2 is used for centroid (eq. 8); f3 for diagonal second moments (eq. 11);
    g0/g1/g2 for cross moments (eq. 12).
    """
    tmp0 = a0 + a1
    tmp1 = a0 * a0
    tmp2 = tmp1 + a1 * tmp0
    f1 = tmp0 + a2
    f2 = tmp2 + a2 * f1
    f3 = a0 * tmp1 + a1 * tmp2 + a2 * f2
    g0 = f2 + a0 * (f1 + a0)
    g1 = f2 + a1 * (f1 + a1)
    g2 = f2 + a2 * (f1 + a2)
    return f2, f3, g0, g1, g2


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_mesh_mass_props(
    vertices: Sequence,
    triangles: Sequence,
    density: float = 1.0,
    allow_open: bool = False,
) -> MassPropsReport:
    """Compute volume, centroid, and inertia tensor of a closed triangle mesh.

    Parameters
    ----------
    vertices : array-like, shape (N, 3)
        Vertex positions.
    triangles : array-like, shape (M, 3)
        Triangle index triples into ``vertices``.  Winding must be consistent
        (counter-clockwise viewed from outside = outward normals).
    density : float
        Mass per unit volume.  Default 1.0.
    allow_open : bool
        If True, skip the ``volume ≤ 0`` closed-mesh guard.

    Returns
    -------
    MassPropsReport

    Raises
    ------
    ValueError
        If the mesh is empty, or if the signed volume is ≤ 0 and
        ``allow_open`` is False.

    Notes
    -----
    Algorithm: Mirtich 1996 §3 / Mortenson §11.4 / Eberly 2002.
    Area-weighted outward normal per triangle: d = (v1-v0) × (v2-v0).
    All six independent second moments accumulated in one O(M) pass.

    Honest: assumes closed orientable mesh with outward-facing normals.
    Non-manifold geometry, inverted normals, or open meshes give wrong-sign
    or incorrect magnitudes — callers should validate topology before calling.
    """
    verts = np.asarray(vertices, dtype=float)
    tris = np.asarray(triangles, dtype=int)

    if verts.ndim != 2 or verts.shape[1] != 3:
        raise ValueError(f"vertices must have shape (N, 3); got {verts.shape}")
    if tris.ndim != 2 or tris.shape[1] != 3:
        raise ValueError(f"triangles must have shape (M, 3); got {tris.shape}")
    if len(tris) == 0:
        raise ValueError("triangles array is empty")

    v0 = verts[tris[:, 0]]  # (M, 3)
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]

    # Area-weighted outward normal: d = (v1-v0) × (v2-v0)
    # |d| = 2·area; direction = outward (CCW winding from outside).
    d = np.cross(v1 - v0, v2 - v0)   # (M, 3)
    dx, dy, dz = d[:, 0], d[:, 1], d[:, 2]

    # ── Volume ────────────────────────────────────────────────────────
    # V = (1/6) Σ v0 · d   (Mirtich 1996 eq. 1 / Mortenson §11.4)
    volume = float(np.einsum('ij,ij->', v0, d)) / 6.0

    if not allow_open and volume <= 0.0:
        raise ValueError(
            f"Computed signed volume {volume:.6g} ≤ 0.  "
            "This indicates an open mesh, inverted-normal mesh, or degenerate "
            "geometry.  Fix the mesh topology or pass allow_open=True to bypass."
        )

    # ── Centroid ──────────────────────────────────────────────────────
    # Cx·V = (1/24) Σ dx · (x0²+x1²+x2²+x0x1+x0x2+x1x2)   [Mirtich eq. 9]
    x0, y0, z0 = v0[:, 0], v0[:, 1], v0[:, 2]
    x1, y1, z1 = v1[:, 0], v1[:, 1], v1[:, 2]
    x2, y2, z2 = v2[:, 0], v2[:, 1], v2[:, 2]

    def _q2(a0, a1, a2):
        return a0*a0 + a1*a1 + a2*a2 + a0*a1 + a0*a2 + a1*a2

    fx = float(np.sum(dx * _q2(x0, x1, x2))) / 24.0
    fy = float(np.sum(dy * _q2(y0, y1, y2))) / 24.0
    fz = float(np.sum(dz * _q2(z0, z1, z2))) / 24.0

    if abs(volume) < 1e-30:
        centroid = np.zeros(3)
    else:
        centroid = np.array([fx / volume, fy / volume, fz / volume])

    # ── Second moments (Eberly 2002 recurrence) ───────────────────────
    # Precompute (f2, f3, g0, g1, g2) for each axis.
    f2x, f3x, g0x, g1x, g2x = _eberly(x0, x1, x2)
    f2y, f3y, g0y, g1y, g2y = _eberly(y0, y1, y2)
    f2z, f3z, g0z, g1z, g2z = _eberly(z0, z1, z2)

    # ∫∫∫ x² dV, ∫∫∫ y² dV, ∫∫∫ z² dV  (Eberly eq. 11)
    Vxx = float(np.sum(dx * f3x)) / 60.0
    Vyy = float(np.sum(dy * f3y)) / 60.0
    Vzz = float(np.sum(dz * f3z)) / 60.0

    # ∫∫∫ x·y dV, ∫∫∫ x·z dV, ∫∫∫ y·z dV  (Eberly eq. 12)
    Vxy = float(np.sum(dx * (y0 * g0x + y1 * g1x + y2 * g2x))) / 120.0
    Vxz = float(np.sum(dx * (z0 * g0x + z1 * g1x + z2 * g2x))) / 120.0
    Vyz = float(np.sum(dy * (z0 * g0y + z1 * g1y + z2 * g2y))) / 120.0

    # ── Inertia tensor about origin → shift to centroid ───────────────
    # Ixx_origin = ρ (∫y² dV + ∫z² dV);  Ixy_origin = −ρ ∫xy dV
    # Parallel-axis: Iij_cg = Iij_origin − m (|r|² δij − ri rj)
    m = density * volume
    cx, cy, cz = float(centroid[0]), float(centroid[1]), float(centroid[2])

    Ixx_o = density * (Vyy + Vzz)
    Iyy_o = density * (Vxx + Vzz)
    Izz_o = density * (Vxx + Vyy)
    Ixy_o = -density * Vxy
    Ixz_o = -density * Vxz
    Iyz_o = -density * Vyz

    r2 = cx * cx + cy * cy + cz * cz
    Ixx_cg = Ixx_o - m * (r2 - cx * cx)
    Iyy_cg = Iyy_o - m * (r2 - cy * cy)
    Izz_cg = Izz_o - m * (r2 - cz * cz)
    Ixy_cg = Ixy_o + m * cx * cy
    Ixz_cg = Ixz_o + m * cx * cz
    Iyz_cg = Iyz_o + m * cy * cz

    inertia_tensor = np.array([
        [Ixx_cg, Ixy_cg, Ixz_cg],
        [Ixy_cg, Iyy_cg, Iyz_cg],
        [Ixz_cg, Iyz_cg, Izz_cg],
    ])

    # Principal axes via symmetric eigensolver
    evals, evecs = np.linalg.eigh(inertia_tensor)  # ascending eigenvalues

    return MassPropsReport(
        volume=volume,
        mass=m,
        centroid=centroid,
        inertia_tensor=inertia_tensor,
        principal_moments=evals,
        principal_axes=evecs,
        triangle_count=int(len(tris)),
    )


# ---------------------------------------------------------------------------
# LLM tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _mesh_mass_spec = ToolSpec(
        name="brep_mesh_mass_props",
        description=(
            "Compute volume, mass, centroid, and inertia tensor of a **triangle mesh** "
            "(STL import, 3D scan reconstruction, or fast approximation of a B-rep solid).\n"
            "\n"
            "Input: vertices as a list of [x,y,z] triples; "
            "triangles as integer index triples (0-based); optional density (default 1.0).\n"
            "\n"
            "Algorithm: divergence theorem on triangles — Mirtich 1996 §3 / Mortenson §11.4 / "
            "Eberly 2002.  All six second moments in one O(M) pass.\n"
            "\n"
            "Returns: volume, mass, centroid [x,y,z], inertia_tensor (3×3 flattened "
            "row-major as 9 numbers), principal_moments [λ1,λ2,λ3], "
            "principal_axes (3×3 column eigenvectors, flattened), triangle_count.\n"
            "\n"
            "Honest: assumes closed orientable mesh with outward-facing normals (CCW "
            "winding from outside).  Open mesh / inverted normals → ok:false with "
            "reason='OPEN_MESH'.  Non-manifold geometry may give wrong magnitudes without "
            "raising.  Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "List of [x, y, z] vertex positions.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "minItems": 3,
                },
                "triangles": {
                    "type": "array",
                    "description": "List of [i0, i1, i2] index triples (0-based).",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "minItems": 1,
                },
                "density": {
                    "type": "number",
                    "description": "Material density (kg/m³ or consistent unit). Default 1.0.",
                },
                "allow_open": {
                    "type": "boolean",
                    "description": "Skip closed-mesh guard. Default false.",
                },
            },
            "required": ["vertices", "triangles"],
        },
    )

    @register(_mesh_mass_spec)
    async def run_brep_mesh_mass_props(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        vertices = a.get("vertices")
        triangles = a.get("triangles")
        if vertices is None:
            return err_payload("vertices is required", "BAD_ARGS")
        if triangles is None:
            return err_payload("triangles is required", "BAD_ARGS")

        density = float(a.get("density", 1.0))
        allow_open = bool(a.get("allow_open", False))

        try:
            result = compute_mesh_mass_props(
                vertices=vertices,
                triangles=triangles,
                density=density,
                allow_open=allow_open,
            )
        except ValueError as exc:
            code = "OPEN_MESH" if "volume" in str(exc).lower() else "BAD_ARGS"
            return err_payload(str(exc), code)
        except Exception as exc:
            return err_payload(f"compute_mesh_mass_props failed: {exc}", "OP_FAILED")

        return ok_payload({
            "volume": result.volume,
            "mass": result.mass,
            "centroid": result.centroid.tolist(),
            "inertia_tensor": result.inertia_tensor.flatten().tolist(),
            "principal_moments": result.principal_moments.tolist(),
            "principal_axes": result.principal_axes.flatten().tolist(),
            "triangle_count": result.triangle_count,
        })
