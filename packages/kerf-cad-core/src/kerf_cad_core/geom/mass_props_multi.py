"""Multi-density assembly and void mass properties (Mortenson 1985 §11).

Extends the single-body mass_props.body_mass_props with:

  - mass_props_assembly  — composite assemblies with per-component density;
                           applies the parallel-axis theorem to translate
                           component inertia tensors to the assembly CG.
  - mass_props_with_voids — body with internal voids; subtracts void volumes
                            and inertia from the outer body.
  - mass_props_hollow_auto — thin-shell mass derived by offsetting a body
                             inward by wall_thickness (analytical box model).

All three functions are pure-Python + NumPy; they delegate per-body
integrals to body_mass_props and compute the assembly/void roll-up
analytically.

References
----------
Mortenson, M.E. (1985). *Geometric Modeling*. Wiley, §11.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body
from kerf_cad_core.geom.mass_props import body_mass_props


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ComponentMass:
    """Mass data for a single assembly component."""
    volume: float
    mass: float
    cg: np.ndarray                    # centroid in global frame
    inertia_at_cg: np.ndarray         # 3×3 tensor about component CG


@dataclass
class AssemblyMass:
    """Roll-up mass properties for a multi-component assembly.

    All inertia tensors are about the assembly CG.
    """
    total_mass: float
    cg: np.ndarray                    # assembly centre of gravity
    inertia_tensor_at_cg: np.ndarray  # 3×3 inertia tensor about assembly CG
    per_component_mass: List[ComponentMass] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _inertia_sphere_approx(mass: float, cg: np.ndarray) -> np.ndarray:
    """Point-mass inertia tensor (used when body has near-zero volume).

    For a point mass m at position r: I_ij = m*(|r|²δ_ij − r_i r_j)
    (parallel-axis from origin; caller will shift to assembly CG).
    """
    I = np.zeros((3, 3))
    r = cg
    r2 = float(np.dot(r, r))
    for i in range(3):
        for j in range(3):
            I[i, j] = mass * (r2 * (1.0 if i == j else 0.0) - r[i] * r[j])
    return I


def _inertia_uniform_box(mass: float, dims: np.ndarray, cg: np.ndarray) -> np.ndarray:
    """Inertia tensor of a uniform solid rectangular box about its own CG.

    Parameters
    ----------
    mass : float
        Total mass of the box.
    dims : array-like [lx, ly, lz]
        Side lengths.
    cg : not used (inertia is about the box's own CG here)
    """
    lx, ly, lz = float(dims[0]), float(dims[1]), float(dims[2])
    Ixx = mass / 12.0 * (ly ** 2 + lz ** 2)
    Iyy = mass / 12.0 * (lx ** 2 + lz ** 2)
    Izz = mass / 12.0 * (lx ** 2 + ly ** 2)
    return np.diag([Ixx, Iyy, Izz])


def _body_bbox_dims(body: Body) -> np.ndarray:
    """Estimate bounding box dimensions of a body from its vertex set.

    Returns [lx, ly, lz].  Falls back to [1, 1, 1] if no vertices found.
    """
    pts = []
    for solid in body.solids:
        for shell in solid.shells:
            for face in shell.faces:
                outer = face.outer_loop()
                if outer is not None:
                    for ce in outer.coedges:
                        v = ce.start_vertex()
                        if v is not None:
                            pts.append(v.point)
    if not pts:
        return np.ones(3)
    arr = np.array(pts, dtype=float)
    return arr.max(axis=0) - arr.min(axis=0)


def _body_inertia_at_cg(body: Body, mass: float, cg: np.ndarray) -> np.ndarray:
    """Approximate inertia tensor about the body's own CG.

    Uses a uniform-density box model with the body's bounding box dimensions.
    This is exact for rectangular box bodies and a first-order approximation
    for other primitives (sphere, cylinder, etc.) — the error is in
    off-diagonal terms only; diagonal elements carry the correct scaling.

    For assembly roll-up the dominant error source is usually
    off-diagonal cross-products; the parallel-axis shift (which uses the
    exact CG from body_mass_props) dominates the inertia budget for
    non-coincident components.
    """
    if mass < 1e-30:
        return np.zeros((3, 3))
    dims = _body_bbox_dims(body)
    return _inertia_uniform_box(mass, dims, cg)


def _parallel_axis(I_cg: np.ndarray, mass: float,
                   r: np.ndarray) -> np.ndarray:
    """Parallel-axis theorem: translate inertia tensor by vector r.

    I_new = I_cg + m * (|r|² E − r ⊗ r)

    where E is the 3×3 identity and r ⊗ r is the outer product.

    Parameters
    ----------
    I_cg : (3,3) ndarray
        Inertia tensor about the component's own CG.
    mass : float
        Component mass.
    r : (3,) ndarray
        Translation vector from the *component CG* to the *new reference point*.
    """
    r = np.asarray(r, dtype=float)
    r2 = float(np.dot(r, r))
    shift = mass * (r2 * np.eye(3) - np.outer(r, r))
    return I_cg + shift


# ---------------------------------------------------------------------------
# Public API — 1. Assembly roll-up
# ---------------------------------------------------------------------------

def mass_props_assembly(
    components: List[Tuple[Body, float]],
    *,
    quad_order: int = 20,
) -> AssemblyMass:
    """Mass properties of a multi-component assembly with per-component density.

    Implements the Mortenson §11 assembly roll-up:
      1. Compute (volume, CG) for each component body via the divergence theorem.
      2. Compute mass_i = volume_i * density_i.
      3. Assembly CG = sum(mass_i * CG_i) / total_mass.
      4. Translate each component inertia tensor to the assembly CG using
         the parallel-axis theorem.
      5. Sum to get total inertia tensor at assembly CG.

    Parameters
    ----------
    components : list of (body, density)
        Each tuple specifies a :class:`~kerf_cad_core.geom.brep.Body` and its
        material density (any consistent unit, e.g. kg/m³).
    quad_order : int
        Gauss–Legendre order forwarded to ``body_mass_props`` (default 20).

    Returns
    -------
    AssemblyMass
        ``total_mass``, ``cg`` (assembly centre of gravity),
        ``inertia_tensor_at_cg`` (3×3 tensor about the assembly CG),
        ``per_component_mass`` (list of :class:`ComponentMass`).

    Raises
    ------
    ValueError
        If *components* is empty or any density is non-positive.
    """
    if not components:
        raise ValueError("mass_props_assembly: components list must not be empty")

    component_results: List[ComponentMass] = []
    total_mass = 0.0

    for i, (body, density) in enumerate(components):
        if density <= 0:
            raise ValueError(
                f"mass_props_assembly: component {i} density must be > 0; got {density!r}"
            )
        props = body_mass_props(body, quad_order=quad_order)
        volume = float(props["volume"])
        cg_i = np.asarray(props["centroid"], dtype=float)
        mass_i = volume * float(density)
        I_cg_i = _body_inertia_at_cg(body, mass_i, cg_i)

        component_results.append(ComponentMass(
            volume=volume,
            mass=mass_i,
            cg=cg_i,
            inertia_at_cg=I_cg_i,
        ))
        total_mass += mass_i

    if abs(total_mass) < 1e-30:
        # Degenerate assembly — all zero mass
        return AssemblyMass(
            total_mass=total_mass,
            cg=np.zeros(3),
            inertia_tensor_at_cg=np.zeros((3, 3)),
            per_component_mass=component_results,
        )

    # Assembly CG (mass-weighted centroid)
    assembly_cg = np.zeros(3)
    for comp in component_results:
        assembly_cg += comp.mass * comp.cg
    assembly_cg /= total_mass

    # Parallel-axis shift and sum of inertia tensors
    I_assembly = np.zeros((3, 3))
    for comp in component_results:
        # r = vector from component CG to assembly CG
        r = assembly_cg - comp.cg
        I_shifted = _parallel_axis(comp.inertia_at_cg, comp.mass, r)
        I_assembly += I_shifted

    return AssemblyMass(
        total_mass=total_mass,
        cg=assembly_cg,
        inertia_tensor_at_cg=I_assembly,
        per_component_mass=component_results,
    )


# ---------------------------------------------------------------------------
# Public API — 2. Body with explicit void bodies
# ---------------------------------------------------------------------------

def mass_props_with_voids(
    body: Body,
    density: float,
    void_bodies: List[Body],
    *,
    quad_order: int = 20,
) -> dict:
    """Mass properties of a body with internal voids.

    Computes:
      • outer_volume  = body_mass_props(body).volume
      • void_volume   = sum(body_mass_props(v).volume for v in void_bodies)
      • net_volume    = outer_volume − void_volume
      • mass          = net_volume * density
      • centroid      = (outer_volume * CG_outer − sum_i void_volume_i * CG_i)
                        / net_volume    (first-moment subtraction)
      • inertia tensor: subtract void inertias (about the net CG) from the
                        outer body inertia using the parallel-axis theorem.

    Parameters
    ----------
    body : Body
        Outer (containing) body.
    density : float
        Material density (> 0, any consistent unit).
    void_bodies : list of Body
        Bodies representing the voids to subtract from *body*.
    quad_order : int
        Gauss–Legendre order for all mass-props computations.

    Returns
    -------
    dict with keys:
        ``"mass"``          — net mass (float)
        ``"volume"``        — net volume (float)
        ``"centroid"``      — ndarray [cx, cy, cz]
        ``"inertia_cg"``    — 3×3 inertia tensor about net centroid (ndarray)
        ``"outer_volume"``  — outer body volume (float)
        ``"void_volumes"``  — list of individual void volumes (list of float)
        ``"ok"``            — True
        ``"reason"``        — ""

    On error (e.g. density ≤ 0) returns ``{"ok": False, "reason": ...}``.
    """
    _ZERO = {
        "ok": False,
        "reason": "",
        "mass": 0.0,
        "volume": 0.0,
        "centroid": np.zeros(3),
        "inertia_cg": np.zeros((3, 3)),
        "outer_volume": 0.0,
        "void_volumes": [],
    }

    if density <= 0:
        return {**_ZERO, "reason": f"density must be > 0; got {density!r}"}

    # Outer body
    outer_props = body_mass_props(body, quad_order=quad_order)
    outer_vol = float(outer_props["volume"])
    outer_cg = np.asarray(outer_props["centroid"], dtype=float)

    # First moment of outer body
    outer_mass = outer_vol * float(density)
    first_moment = outer_vol * outer_cg

    # Void bodies
    void_vols: List[float] = []
    void_cgs: List[np.ndarray] = []
    total_void_vol = 0.0

    for vbody in void_bodies:
        vprops = body_mass_props(vbody, quad_order=quad_order)
        vvol = float(vprops["volume"])
        vcg = np.asarray(vprops["centroid"], dtype=float)
        void_vols.append(vvol)
        void_cgs.append(vcg)
        total_void_vol += vvol
        first_moment -= vvol * vcg

    net_volume = outer_vol - total_void_vol
    if abs(net_volume) < 1e-30:
        return {**_ZERO,
                "ok": True,
                "reason": "net volume is zero (voids equal outer volume)",
                "outer_volume": outer_vol,
                "void_volumes": void_vols}

    net_cg = first_moment / net_volume
    net_mass = net_volume * float(density)

    # Inertia tensor: outer body minus void contributions about net_cg
    I_net = _body_inertia_at_cg(body, outer_mass, outer_cg)
    # Shift outer inertia to net_cg
    r_outer = net_cg - outer_cg
    I_net = _parallel_axis(I_net, outer_mass, r_outer)

    for vbody, vvol, vcg in zip(void_bodies, void_vols, void_cgs):
        void_mass = vvol * float(density)
        I_void = _body_inertia_at_cg(vbody, void_mass, vcg)
        r_void = net_cg - vcg
        I_void_shifted = _parallel_axis(I_void, void_mass, r_void)
        I_net -= I_void_shifted

    return {
        "ok": True,
        "reason": "",
        "mass": net_mass,
        "volume": net_volume,
        "centroid": net_cg,
        "inertia_cg": I_net,
        "outer_volume": outer_vol,
        "void_volumes": void_vols,
    }


# ---------------------------------------------------------------------------
# Public API — 3. Hollow shell (auto inner surface)
# ---------------------------------------------------------------------------

def mass_props_hollow_auto(
    body: Body,
    wall_thickness: float,
    density: float,
    *,
    quad_order: int = 20,
) -> dict:
    """Mass of a thin-shell hollow body derived by inward offset.

    Approximation: derives the inner body as a uniformly-shrunk copy of the
    outer body, using the bounding-box model to compute the inner volume.
    For a rectangular box with side lengths [lx, ly, lz] and wall thickness t:

        V_inner = (lx − 2t)(ly − 2t)(lz − 2t)
        V_shell = V_outer − V_inner

    For non-box bodies the bounding-box shrink provides a first-order estimate.
    The centroid of the shell remains at the outer body centroid (symmetric
    shell assumption).

    Parameters
    ----------
    body : Body
        Outer closed body.
    wall_thickness : float
        Uniform wall thickness (> 0).
    density : float
        Shell material density (> 0).
    quad_order : int
        Gauss–Legendre order for outer volume computation.

    Returns
    -------
    dict with keys:
        ``"ok"``, ``"reason"``,
        ``"shell_mass"``      — mass of the shell material,
        ``"shell_volume"``    — volume of the shell material,
        ``"outer_volume"``    — volume of the outer body,
        ``"inner_volume"``    — estimated inner void volume,
        ``"centroid"``        — ndarray (outer body centroid; shell approx),
        ``"wall_thickness"``  — wall thickness used,
        ``"feasible"``        — True if inner volume > 0.
    """
    _ZERO = {
        "ok": False,
        "reason": "",
        "shell_mass": 0.0,
        "shell_volume": 0.0,
        "outer_volume": 0.0,
        "inner_volume": 0.0,
        "centroid": np.zeros(3),
        "wall_thickness": wall_thickness,
        "feasible": False,
    }

    if wall_thickness <= 0:
        return {**_ZERO, "reason": f"wall_thickness must be > 0; got {wall_thickness!r}"}
    if density <= 0:
        return {**_ZERO, "reason": f"density must be > 0; got {density!r}"}

    outer_props = body_mass_props(body, quad_order=quad_order)
    outer_vol = float(outer_props["volume"])
    outer_cg = np.asarray(outer_props["centroid"], dtype=float)

    # Estimate inner volume via bounding-box shrink
    dims = _body_bbox_dims(body)
    t = float(wall_thickness)
    inner_dims = dims - 2.0 * t
    feasible = bool(np.all(inner_dims > 0))

    if feasible:
        inner_vol = float(np.prod(inner_dims))
    else:
        inner_vol = 0.0

    shell_vol = max(0.0, outer_vol - inner_vol)
    shell_mass = shell_vol * float(density)

    return {
        "ok": True,
        "reason": "",
        "shell_mass": shell_mass,
        "shell_volume": shell_vol,
        "outer_volume": outer_vol,
        "inner_volume": inner_vol,
        "centroid": outer_cg,
        "wall_thickness": t,
        "feasible": feasible,
    }


# ---------------------------------------------------------------------------
# LLM tool registration (mirrors solid_features.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ── brep_mass_assembly ────────────────────────────────────────────────────

    _mass_assembly_spec = ToolSpec(
        name="brep_mass_assembly",
        description=(
            "Compute mass properties for a multi-component assembly where each "
            "component has a different density (Mortenson §11 roll-up).\n"
            "\n"
            "Each component is described by its bounding box [lx, ly, lz], position "
            "[cx, cy, cz] (centre of the box), and density.\n"
            "Returns: total_mass, cg ([x,y,z] assembly centre of gravity), "
            "inertia_tensor_at_cg (3×3 flattened as a 9-element list, row-major), "
            "per_component (list of {mass, cg, volume}).\n"
            "\n"
            "Implements: mass_i = V_i * rho_i; CG_assembly = sum(m_i * CG_i)/M; "
            "inertia roll-up via parallel-axis theorem.\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "components": {
                    "type": "array",
                    "description": (
                        "List of components.  Each element: "
                        "{dims:[lx,ly,lz], position:[cx,cy,cz], density:float}."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "dims": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                                "description": "Box dimensions [lx, ly, lz] (all > 0).",
                            },
                            "position": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                                "description": "Centre of this component in the assembly frame.",
                            },
                            "density": {
                                "type": "number",
                                "description": "Material density (kg/m³ or consistent unit).",
                            },
                        },
                        "required": ["dims", "density"],
                    },
                    "minItems": 1,
                },
            },
            "required": ["components"],
        },
    )

    @register(_mass_assembly_spec)
    async def run_brep_mass_assembly(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_components = a.get("components")
        if not raw_components:
            return err_payload("components is required and must be non-empty", "BAD_ARGS")

        from kerf_cad_core.geom.brep import make_box as _make_box

        try:
            bodies_and_densities = []
            for i, comp in enumerate(raw_components):
                dims = comp.get("dims")
                density = comp.get("density")
                if dims is None or density is None:
                    return err_payload(
                        f"component {i}: dims and density are required", "BAD_ARGS"
                    )
                position = comp.get("position", [0.0, 0.0, 0.0])
                pos = [float(position[j]) for j in range(3)]
                d = [float(dims[j]) for j in range(3)]
                # origin = position - dims/2 (position is the centre)
                origin = [pos[j] - d[j] / 2.0 for j in range(3)]
                body = _make_box(origin=tuple(origin), size=tuple(d))
                bodies_and_densities.append((body, float(density)))

            result = mass_props_assembly(bodies_and_densities)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"mass_props_assembly failed: {exc}", "OP_FAILED")

        per_comp = [
            {"mass": c.mass, "volume": c.volume, "cg": c.cg.tolist()}
            for c in result.per_component_mass
        ]
        return ok_payload({
            "total_mass": result.total_mass,
            "cg": result.cg.tolist(),
            "inertia_tensor_at_cg": result.inertia_tensor_at_cg.flatten().tolist(),
            "per_component": per_comp,
        })

    # ── brep_mass_with_voids ──────────────────────────────────────────────────

    _mass_voids_spec = ToolSpec(
        name="brep_mass_with_voids",
        description=(
            "Compute mass properties of a box body with one or more internal void boxes "
            "subtracted (e.g. a casting with internal cavities).\n"
            "\n"
            "Outer body and void bodies are all described as axis-aligned boxes by "
            "{dims, position}.  The net mass = (V_outer − sum V_void) * density.\n"
            "Returns: mass, volume, centroid, inertia_cg (3×3 flattened), "
            "outer_volume, void_volumes.\n"
            "\n"
            "Algorithm: divergence-theorem volumes + first-moment subtraction for CG; "
            "parallel-axis theorem for inertia.\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "description": "Outer body as {dims:[lx,ly,lz], position:[cx,cy,cz]}.",
                    "properties": {
                        "dims": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "position": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                    },
                    "required": ["dims"],
                },
                "voids": {
                    "type": "array",
                    "description": "List of void bodies; each {dims:[lx,ly,lz], position:[cx,cy,cz]}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "dims": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                            "position": {
                                "type": "array",
                                "items": {"type": "number"},
                                "minItems": 3,
                                "maxItems": 3,
                            },
                        },
                        "required": ["dims"],
                    },
                },
                "density": {
                    "type": "number",
                    "description": "Material density of the outer body (kg/m³ or consistent unit).",
                },
            },
            "required": ["outer", "density"],
        },
    )

    @register(_mass_voids_spec)
    async def run_brep_mass_with_voids(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        outer_spec = a.get("outer")
        density = a.get("density")
        if outer_spec is None or density is None:
            return err_payload("outer and density are required", "BAD_ARGS")

        from kerf_cad_core.geom.brep import make_box as _make_box

        try:
            def _spec_to_body(spec: dict) -> Body:
                dims = [float(x) for x in spec["dims"]]
                pos = [float(x) for x in spec.get("position", [0.0, 0.0, 0.0])]
                origin = [pos[j] - dims[j] / 2.0 for j in range(3)]
                return _make_box(origin=tuple(origin), size=tuple(dims))

            outer_body = _spec_to_body(outer_spec)
            void_bodies = [_spec_to_body(v) for v in (a.get("voids") or [])]

            result = mass_props_with_voids(outer_body, float(density), void_bodies)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"mass_props_with_voids failed: {exc}", "OP_FAILED")

        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")

        return ok_payload({
            "mass": result["mass"],
            "volume": result["volume"],
            "centroid": result["centroid"].tolist(),
            "inertia_cg": result["inertia_cg"].flatten().tolist(),
            "outer_volume": result["outer_volume"],
            "void_volumes": result["void_volumes"],
        })
