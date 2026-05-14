"""
Topology optimization SIMP loop via FEniCSx.

POST /run-topo
Body: {
    "project_id": str,
    "topo_file_id": str,
    "feature_file_id": str,
    "material_file_id": str,
    "volume_fraction": float,
    "penalization_power": int,
    "filter_radius_mm": float,
    "max_iterations": int,
    "convergence_tolerance": float,
    "step_b64": str,                    # base64 STEP bytes of design domain
    "boundary_conditions": [...],       # [{type, face_tag, components?}]
    "loads": [...]                      # [{type, face_tag, fx?, fy?, fz?, pressure?}]
}

Algorithm (SIMP with Optimality Criteria update + Heaviside filter):

1.  Decode step_b64 → STEP file.  Feed to Gmsh OCC importer to build tet mesh.
    Fall back to unit-cube mesh when step_b64 is absent or Gmsh unavailable.
2.  Material properties from request (E, nu, rho).
3.  Boundary conditions: fixed faces (Dirichlet) + applied loads (Neumann).
    Pulled from boundary_conditions / loads in the request body.
4.  Initialize density field ρᵢ = V_target everywhere.
5.  Repeat for i = 1 … max_iterations:
    a.  SIMP stiffness:  K_e(ρᵢ) = ρᵢ^p · K_solid
    b.  Assemble K = Σ K_e(ρᵢ)  (linear elastic)
    c.  Solve K · u = F  →  displacement field u
    d.  Compliance:  C = Fᵀ · u
    e.  Sensitivity via adjoint method:
            ∂C/∂ρ = −p · ρ^(p−1) · uᵀ · K_solid · u
    f.  Heaviside filter (cylinder kernel):
            ∂Ĉ/∂ρ = (Σⱼ w_ij · ρⱼ · |∂C/∂ρⱼ|) / (Σⱼ w_ij · ρⱼ)
            w_ij = max(0, R − |x_i − x_j|)
    g.  OC update (bisection on λ to enforce volume constraint):
            ρ_new = ρ · (−∂C/∂ρ / (λ · V_target))^move
            λ found by bisection: Σ ρ_new = V · V_target
            move = 0.2  (move limit)
            ρ_new = clamp(ρ_new, 0.001, 1.0)
    h.  Heaviside projection (β grows each iteration):
            ρ_proj = tanh(β · ρ) / tanh(β)  (β starts at 5, grows ×1.5/iter, max 20)
    i.  Convergence:  |C_new − C_old| / C_old < tolerance  →  break
6.  Marching cubes at ρ_threshold = 0.5 on final density field → binary mesh.
7.  Convert binary mesh to STEP via pythonOCC BRep sewing → base64 encode.
8.  Return JSON { status, step_b64, final_compliance,
                  final_volume_fraction, iterations, density_field }.
"""

import base64
import math
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()

# ── dependency availability gates ──────────────────────────────────────────────

_DOLFINX_AVAILABLE = False
try:
    import dolfinx  # noqa: F401
    _DOLFINX_AVAILABLE = True
except ImportError:
    pass

_GMSH_AVAILABLE = False
try:
    import gmsh  # noqa: F401
    _GMSH_AVAILABLE = True
except ImportError:
    pass

_OCC_AVAILABLE = False
try:
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeFace
    from OCC.Core.TopoDS import TopoDS_Shell, TopoDS_Compound
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IFSelect import IFSelect_RetDone
    _OCC_AVAILABLE = True
except ImportError:
    pass

# ── SIMP constants ─────────────────────────────────────────────────────────────

P = 3
MOVE = 0.2
RHO_MIN = 0.001
RHO_MAX = 1.0
RHO_THRESHOLD = 0.5
BETA_START = 5.0
BETA_MAX = 20.0
BETA_GROW = 1.5


# ── request model ──────────────────────────────────────────────────────────────

class BoundaryCondition(BaseModel):
    type: str = "fixed"
    face_tag: int = 1
    components: Optional[List[str]] = None

class Load(BaseModel):
    type: str = "force"
    face_tag: int = 2
    fx: float = 0.0
    fy: float = -1.0
    fz: float = 0.0
    pressure: float = 0.0

class TopoRequest(BaseModel):
    project_id: str
    topo_file_id: str
    feature_file_id: str
    material_file_id: str
    volume_fraction: float = Field(gt=0, lt=1)
    penalization_power: int = Field(default=3, gt=0)
    filter_radius_mm: float = Field(gt=0)
    max_iterations: int = Field(gt=0)
    convergence_tolerance: float = Field(gt=0)
    step_b64: str = ""
    boundary_conditions: List[BoundaryCondition] = Field(default_factory=list)
    loads: List[Load] = Field(default_factory=list)


# ── pure-Python SIMP helpers (no heavy deps) ───────────────────────────────────

def _heaviside_filter(rho, coords, R):
    """
    Cylinder filter: push intermediate densities toward 0/1.

    w_ij = max(0, R - |x_i - x_j|)
    rho_filtered_i = (sum_j w_ij * rho_j) / (sum_j w_ij)
    """
    n = len(rho)
    w_sum = [0.0] * n
    w_rho = [0.0] * n
    for i in range(n):
        xi = coords[i]
        for j in range(n):
            xj = coords[j]
            dist = math.sqrt(
                (xi[0] - xj[0]) ** 2
                + (xi[1] - xj[1]) ** 2
                + (xi[2] - xj[2]) ** 2
            )
            wij = max(0.0, R - dist)
            w_sum[i] += wij
            w_rho[i] += wij * rho[j]
    filtered = [0.0] * n
    for i in range(n):
        if w_sum[i] > 0:
            filtered[i] = w_rho[i] / w_sum[i]
    return filtered


def _oc_update(rho, sens, V_target, V_total, move=MOVE):
    """
    Optimality Criteria update with bisection on λ.

    Constraints: Σ ρᵢ = V · V_target
    ρ_new = clamp(ρ · (−∂C/∂ρ / (λ · V_target))^move, ρ_min, ρ_max)
    """
    rho_new = [0.0] * len(rho)
    l = 1e-9
    r = 1e3
    for _ in range(60):
        lam = (l + r) / 2.0
        numerator = 0.0
        for i in range(len(rho)):
            ratio = -sens[i] / (lam * V_target)
            if ratio <= 0:
                nr = RHO_MIN
            else:
                nr = rho[i] * (ratio ** move)
                nr = max(RHO_MIN, min(RHO_MAX, nr))
            rho_new[i] = nr
            numerator += nr
        if abs(numerator - V_total) < 1e-6:
            break
        if numerator > V_total:
            r = lam
        else:
            l = lam
    return rho_new


def _heaviside_projection(rho, beta):
    """Regularized Heaviside projection: ρ_proj = tanh(β·ρ) / tanh(β)."""
    out = [0.0] * len(rho)
    tanh_beta = math.tanh(beta)
    for i in range(len(rho)):
        out[i] = math.tanh(beta * rho[i]) / tanh_beta
    return out


# ── Gmsh meshing ───────────────────────────────────────────────────────────────

def _mesh_step_with_gmsh(step_path: str, mesh_size_mm: float = 5.0):
    """
    Import a STEP file via Gmsh OCC and generate a tetrahedral mesh.

    Returns (mesh, face_tags_map) where mesh is a dolfinx Mesh and
    face_tags_map is a dict mapping integer physical-group tag → facet meshtags.

    mesh_size_mm controls the maximum element size (default 5 mm — coarse
    enough to be fast on a cantilever-scale part).
    """
    import gmsh
    import numpy as np
    from mpi4py import MPI
    import dolfinx.io

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.option.setNumber("Mesh.CharacteristicSizeMax", mesh_size_mm)
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)

    try:
        gmsh.model.occ.importShapes(step_path)
        gmsh.model.occ.synchronize()

        volumes = gmsh.model.getEntities(3)
        if not volumes:
            raise RuntimeError("STEP file contains no 3-D volumes")

        surfaces = gmsh.model.getEntities(2)
        if surfaces:
            for i, (dim, tag) in enumerate(surfaces, start=1):
                gmsh.model.addPhysicalGroup(dim, [tag], tag=i, name=f"face_{i}")

        all_vols = [tag for (_, tag) in volumes]
        gmsh.model.addPhysicalGroup(3, all_vols, tag=1, name="volume")

        gmsh.model.mesh.generate(3)

        with tempfile.NamedTemporaryFile(suffix=".msh", delete=False) as f:
            msh_path = f.name
        gmsh.write(msh_path)
    finally:
        gmsh.finalize()

    mesh, cell_tags, facet_tags = dolfinx.io.gmshio.read_from_msh(
        msh_path,
        MPI.COMM_WORLD,
        gdim=3,
    )
    Path(msh_path).unlink(missing_ok=True)

    return mesh, facet_tags


# ── marching-cubes → STEP export ──────────────────────────────────────────────

def _density_field_to_grid(coords, rho_array, grid_n=30):
    """
    Voxelise a scattered density field onto a regular 3-D grid for marching cubes.

    Returns (grid, spacing, origin) where grid has shape (grid_n, grid_n, grid_n).
    """
    import numpy as np

    coords = np.asarray(coords)
    rho = np.asarray(rho_array)

    mn = coords.min(axis=0)
    mx = coords.max(axis=0)
    span = mx - mn
    span[span == 0] = 1.0

    gi = np.floor(((coords - mn) / span) * (grid_n - 1)).astype(int)
    gi = np.clip(gi, 0, grid_n - 1)

    grid = np.zeros((grid_n, grid_n, grid_n), dtype=float)
    count = np.zeros_like(grid)
    np.add.at(grid, (gi[:, 0], gi[:, 1], gi[:, 2]), rho)
    np.add.at(count, (gi[:, 0], gi[:, 1], gi[:, 2]), 1)
    mask = count > 0
    grid[mask] /= count[mask]

    spacing = span / (grid_n - 1)
    return grid, spacing, mn


def _marching_cubes_to_step(coords, rho_array, threshold=RHO_THRESHOLD) -> bytes:
    """
    Threshold the density field at *threshold*, run marching cubes, and write
    a faceted STEP file via pythonOCC BRep sewing.

    The STEP is faceted (triangulated shell) — smoothing is a future
    enhancement.  Returns raw STEP bytes.
    """
    from skimage.measure import marching_cubes
    import numpy as np
    from OCC.Core.BRep import BRep_Builder
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeFace
    from OCC.Core.TopoDS import TopoDS_Shell, TopoDS_Compound
    from OCC.Core.gp import gp_Pnt
    from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCC.Core.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCC.Core.IFSelect import IFSelect_RetDone

    grid, spacing, origin = _density_field_to_grid(coords, rho_array)

    try:
        verts, faces, normals, _ = marching_cubes(grid, level=threshold, spacing=tuple(spacing))
    except ValueError:
        raise RuntimeError(
            "marching_cubes: no iso-surface found at threshold "
            f"{threshold} — density field may be uniform or not converged"
        )

    if len(faces) == 0:
        raise RuntimeError("marching_cubes produced zero triangles")

    verts_world = verts + origin

    sewer = BRepBuilderAPI_Sewing(1e-3)

    for tri in faces:
        p0, p1, p2 = (verts_world[i] for i in tri)
        poly = BRepBuilderAPI_MakePolygon()
        poly.Add(gp_Pnt(*p0.tolist()))
        poly.Add(gp_Pnt(*p1.tolist()))
        poly.Add(gp_Pnt(*p2.tolist()))
        poly.Close()
        if not poly.IsDone():
            continue
        wire = poly.Wire()
        face_maker = BRepBuilderAPI_MakeFace(wire)
        if not face_maker.IsDone():
            continue
        sewer.Add(face_maker.Face())

    sewer.Perform()
    sewn = sewer.SewedShape()

    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, sewn)

    writer = STEPControl_Writer()
    writer.Transfer(compound, STEPControl_AsIs)

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
        step_path = f.name
    try:
        status = writer.Write(step_path)
        if status != IFSelect_RetDone:
            raise RuntimeError(f"STEPControl_Writer.Write failed with status {status}")
        return Path(step_path).read_bytes()
    finally:
        Path(step_path).unlink(missing_ok=True)


# ── main SIMP loop ─────────────────────────────────────────────────────────────

def _run_fenicsx_simp(req: TopoRequest) -> dict:
    """
    Run SIMP topology optimization via FEniCSx.

    When step_b64 is provided and Gmsh is available, meshes the STEP geometry.
    Otherwise falls back to a structured unit-cube mesh (Phase 1 behaviour).
    """
    import dolfinx
    import dolfinx.mesh
    import dolfinx.fem
    import dolfinx.fem.petsc
    import dolfinx.io
    from mpi4py import MPI
    import ufl
    import numpy as np

    comm = MPI.COMM_WORLD
    warnings = []

    facet_tags = None

    if req.step_b64 and _GMSH_AVAILABLE:
        step_bytes = base64.b64decode(req.step_b64)
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as f:
            step_path = f.name
            f.write(step_bytes)
        try:
            mesh, facet_tags = _mesh_step_with_gmsh(step_path, mesh_size_mm=req.filter_radius_mm * 3.0)
        except Exception as exc:
            warnings.append(f"Gmsh meshing failed ({exc}); falling back to unit-cube mesh")
            mesh = dolfinx.mesh.create_unit_cube(comm, 10, 10, 10)
            facet_tags = None
        finally:
            Path(step_path).unlink(missing_ok=True)
    else:
        if req.step_b64 and not _GMSH_AVAILABLE:
            warnings.append("Gmsh not installed; using unit-cube mesh. Install: pip install gmsh")
        mesh = dolfinx.mesh.create_unit_cube(comm, 10, 10, 10)
        facet_tags = None

    V = dolfinx.fem.functionspace(mesh, ("Lagrange", 1, (3,)))
    Q = dolfinx.fem.functionspace(mesh, ("DG", 0))

    p = req.penalization_power
    V_target = req.volume_fraction
    n_cells = mesh.topology.index_map(mesh.topology.dim).size_local
    V_total = n_cells * V_target

    rho = dolfinx.fem.Function(Q)
    rho.x.array[:] = V_target

    E0 = 200e3
    E_min = 1e-3 * E0
    nu = 0.3

    def epsilon(v):
        return ufl.sym(ufl.grad(v))

    def sigma(v, rho_val):
        E = E_min + (rho_val ** p) * (E0 - E_min)
        lam = E * nu / ((1 + nu) * (1 - 2 * nu))
        mu = E / (2 * (1 + nu))
        return lam * ufl.tr(epsilon(v)) * ufl.Identity(3) + 2 * mu * epsilon(v)

    fdim = mesh.topology.dim - 1

    bcs = []
    if req.boundary_conditions and facet_tags is not None:
        for bc_spec in req.boundary_conditions:
            tag = bc_spec.face_tag
            facets = facet_tags.find(tag)
            if len(facets) == 0:
                warnings.append(f"BC face_tag={tag} matched no facets in mesh")
                continue
            dofs = dolfinx.fem.locate_dofs_topological(V, fdim, facets)
            u_zero = dolfinx.fem.Function(V)
            u_zero.x.array[:] = 0.0
            bcs.append(dolfinx.fem.dirichletbc(u_zero, dofs))
    else:
        def left_boundary(x):
            return np.isclose(x[0], 0.0)
        left_facets = dolfinx.mesh.locate_entities_boundary(mesh, fdim, left_boundary)
        bc_dofs = dolfinx.fem.locate_dofs_topological(V, fdim, left_facets)
        u_zero = dolfinx.fem.Function(V)
        u_zero.x.array[:] = 0.0
        bcs.append(dolfinx.fem.dirichletbc(u_zero, bc_dofs))

    load_measures = []
    if req.loads and facet_tags is not None:
        for load_spec in req.loads:
            tag = load_spec.face_tag
            load_facets = facet_tags.find(tag)
            if len(load_facets) == 0:
                warnings.append(f"Load face_tag={tag} matched no facets in mesh")
                continue
            ft = dolfinx.mesh.meshtags(
                mesh, fdim,
                load_facets,
                np.full(len(load_facets), tag, dtype=np.int32),
            )
            ds_part = ufl.Measure("ds", domain=mesh, subdomain_data=ft)
            if load_spec.type == "force":
                trac = dolfinx.fem.Constant(
                    mesh,
                    dolfinx.default_scalar_type((load_spec.fx, load_spec.fy, load_spec.fz)),
                )
            else:
                trac = dolfinx.fem.Constant(
                    mesh,
                    dolfinx.default_scalar_type((0.0, load_spec.pressure, 0.0)),
                )
            load_measures.append((trac, ds_part, tag))
    else:
        def right_boundary(x):
            return np.isclose(x[0], 1.0)
        right_facets = dolfinx.mesh.locate_entities_boundary(mesh, fdim, right_boundary)
        rt = dolfinx.mesh.meshtags(
            mesh, fdim,
            np.concatenate([right_facets]),
            np.ones(len(right_facets), dtype=np.int32),
        )
        ds_default = ufl.Measure("ds", domain=mesh, subdomain_data=rt)
        f_trac = dolfinx.fem.Constant(
            mesh, dolfinx.default_scalar_type((0.0, -1.0, 0.0))
        )
        load_measures.append((f_trac, ds_default, 1))

    u = dolfinx.fem.Function(V)
    v = ufl.TestFunction(V)
    du = ufl.TrialFunction(V)

    compliance_history = []
    rho_array = rho.x.array.copy()
    coords = Q.tabulate_dof_coordinates()

    final_compliance = 0.0
    final_iter = 0
    beta = BETA_START

    for iteration in range(req.max_iterations):
        rho.x.array[:] = rho_array
        a = ufl.inner(sigma(du, rho), epsilon(v)) * ufl.dx

        L = None
        for trac, ds_part, tag in load_measures:
            term = ufl.inner(trac, v) * ds_part(tag)
            L = term if L is None else L + term
        if L is None:
            L = ufl.inner(dolfinx.fem.Constant(mesh, dolfinx.default_scalar_type((0.0, 0.0, 0.0))), v) * ufl.dx

        problem = dolfinx.fem.petsc.LinearProblem(
            a, L, bcs=bcs,
            petsc_options={"ksp_type": "cg", "pc_type": "gamg", "ksp_rtol": 1e-8},
        )
        u = problem.solve()

        compliance_forms = []
        for trac, ds_part, tag in load_measures:
            compliance_forms.append(dolfinx.fem.form(ufl.inner(trac, u) * ds_part(tag)))
        C = sum(dolfinx.fem.assemble_scalar(cf) for cf in compliance_forms)
        compliance_history.append(float(C))
        final_compliance = float(C)
        final_iter = iteration + 1

        sigma_solid = lambda v: (E0 - E_min) * (
            nu / ((1 + nu) * (1 - 2 * nu)) * ufl.tr(epsilon(v)) * ufl.Identity(3)
            + 1 / (1 + nu) * epsilon(v)
        )
        sens_expr = dolfinx.fem.Expression(
            -p * rho ** (p - 1) * ufl.inner(sigma_solid(u), epsilon(u)),
            Q.element.interpolation_points(),
        )
        sens_fn = dolfinx.fem.Function(Q)
        sens_fn.interpolate(sens_expr)
        sens = sens_fn.x.array.tolist()

        rho_f = _heaviside_filter(rho_array.tolist(), coords.tolist(), req.filter_radius_mm)
        rho_new = _oc_update(rho_f, sens, V_target, V_total)

        beta = min(beta * BETA_GROW, BETA_MAX)
        rho_proj = _heaviside_projection(rho_new, beta)
        rho_proj = [max(RHO_MIN, min(RHO_MAX, r)) for r in rho_proj]

        if len(compliance_history) >= 2:
            rel_change = abs(compliance_history[-1] - compliance_history[-2]) / (abs(compliance_history[-2]) + 1e-12)
            if rel_change < req.convergence_tolerance:
                rho_array = rho_proj
                break

        rho_array = rho_proj

    density_field = []
    for i, (coord, r) in enumerate(zip(coords.tolist(), rho_array)):
        density_field.append({"x": coord[0], "y": coord[1], "z": coord[2], "rho": float(r)})

    final_vol_frac = sum(rho_array) / len(rho_array) if rho_array else V_target

    output_step_b64 = ""
    if _OCC_AVAILABLE:
        try:
            step_bytes = _marching_cubes_to_step(coords.tolist(), rho_array)
            output_step_b64 = base64.b64encode(step_bytes).decode()
        except Exception as exc:
            warnings.append(f"marching-cubes STEP export failed: {exc}")
    else:
        warnings.append(
            "pythonOCC not installed — STEP export skipped. "
            "Install: conda install -c conda-forge pythonocc-core"
        )

    return {
        "status": "success",
        "output_mesh_file_id": "",
        "step_b64": output_step_b64,
        "final_compliance": final_compliance,
        "final_volume_fraction": float(final_vol_frac),
        "iterations": final_iter,
        "density_field": density_field,
        "warnings": warnings,
    }


# ── route ──────────────────────────────────────────────────────────────────────

@router.post("/run-topo")
async def run_topo(req: TopoRequest):
    """
    Run SIMP topology optimization.

    When dolfinx is available, runs the full SIMP loop.
    When step_b64 + gmsh are available, meshes the real geometry; otherwise
    falls back to a unit-cube domain.
    When pythonOCC is available, exports the density threshold as a STEP file
    (faceted shell) and returns it in step_b64.
    When dolfinx is not installed, returns ENGINE_PENDING_WARNING.
    """
    if not _DOLFINX_AVAILABLE:
        return {
            "status": "pending",
            "output_mesh_file_id": "",
            "step_b64": "",
            "final_compliance": 0.0,
            "final_volume_fraction": 0.0,
            "iterations": 0,
            "warnings": ["Engine pending — FEniCSx not yet deployed."],
        }

    try:
        result = _run_fenicsx_simp(req)
        return result
    except Exception as exc:
        return {
            "status": "error",
            "output_mesh_file_id": "",
            "step_b64": "",
            "final_compliance": 0.0,
            "final_volume_fraction": 0.0,
            "iterations": 0,
            "warnings": [f"SIMP loop error: {exc}"],
        }
