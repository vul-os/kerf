"""
FEniCSx utilities for stress/modal/thermal analysis.

Bonded contact approach: shared-node (conformal mesh) via Gmsh physical groups.
When a .fem spec lists multiple material regions (bodies), Gmsh is expected to
produce a conformal tetrahedral mesh where bodies share nodes at the interface.
Each body gets its own physical volume tag; interface facets are implicit (shared
nodes mean continuity of displacement — exactly the tied/bonded condition).
No Lagrange multiplier coupling is needed.  If the mesh is non-conformal, a
Lagrange-multiplier approach would be required; that is deferred because Gmsh
occ.fragment() already gives conformal interfaces for Boolean-fused solids.
"""

import tempfile
from pathlib import Path

import numpy as np

_DOLFINX_AVAILABLE = False
try:
    import dolfinx  # noqa: F401
    _DOLFINX_AVAILABLE = True
except ImportError:
    pass

ENGINE_PENDING_WARNING = "Engine pending — FEniCSx (dolfinx) not yet installed."


def run_static_analysis(mesh_path: str, material_props: dict,
                        boundary_conditions: list, loads: list,
                        analysis_type: str = "linear_static") -> dict:
    if not _DOLFINX_AVAILABLE:
        return {
            "status": "pending",
            "warnings": [ENGINE_PENDING_WARNING],
            "errors": [],
        }
    if analysis_type == "linear_static":
        return _run_linear_static(mesh_path, material_props, boundary_conditions, loads)
    elif analysis_type == "modal":
        return _run_modal(mesh_path, material_props, boundary_conditions)
    elif analysis_type == "thermal":
        return _run_thermal(mesh_path, material_props, boundary_conditions, loads)
    else:
        raise ValueError(f"unknown analysis_type: {analysis_type}")


# ---------------------------------------------------------------------------
# Mesh conversion helper
# ---------------------------------------------------------------------------

def _msh_to_xdmf(msh_path: str, xdmf_path: str, facet_xdmf_path: str) -> None:
    """
    Convert Gmsh .msh → two XDMF files (volume mesh + facet meshtags) using
    meshio.  Handles both 3-D (tetra) and 2-D (triangle) meshes.
    """
    import meshio

    msh = meshio.read(msh_path)

    # --- volume cells ---
    vol_type = None
    vol_data = None
    for cb in msh.cells:
        if cb.type in ("tetra", "tetra10"):
            vol_type = "tetra"
            vol_data = cb.data if cb.type == "tetra" else cb.data[:, :4]
            break
    if vol_type is None:
        for cb in msh.cells:
            if cb.type in ("triangle", "triangle6"):
                vol_type = "triangle"
                vol_data = cb.data if cb.type == "triangle" else cb.data[:, :3]
                break
    if vol_type is None:
        raise ValueError("No volumetric cells (tetra/triangle) found in mesh")

    # collect physical group tags per volume cell
    vol_cell_data = {}
    for key, blocks in msh.cell_data.items():
        # meshio stores cell_data keyed by field name; blocks are per cell-type
        for i_cb, cb in enumerate(msh.cells):
            if cb.type.startswith("tetra") or cb.type.startswith("triangle"):
                if i_cb < len(blocks):
                    vol_cell_data[key] = blocks[i_cb]
                break

    vol_mesh = meshio.Mesh(
        points=msh.points,
        cells=[(vol_type, vol_data)],
        cell_data={k: [v] for k, v in vol_cell_data.items()} if vol_cell_data else {},
    )
    meshio.write(xdmf_path, vol_mesh)

    # --- facet cells (for Neumann/Dirichlet tags) ---
    facet_type = "line" if vol_type == "triangle" else "triangle"
    facet_data = None
    facet_tags = None
    for i_cb, cb in enumerate(msh.cells):
        if cb.type == facet_type:
            facet_data = cb.data
            # look for gmsh:physical tag on this cell block
            for key, blocks in msh.cell_data.items():
                if i_cb < len(blocks):
                    facet_tags = blocks[i_cb]
                    break
            break

    if facet_data is not None and len(facet_data) > 0:
        facet_mesh = meshio.Mesh(
            points=msh.points,
            cells=[(facet_type, facet_data)],
            cell_data={"gmsh:physical": [facet_tags]} if facet_tags is not None else {},
        )
        meshio.write(facet_xdmf_path, facet_mesh)
    else:
        # Write a minimal placeholder so dolfinx XDMF read doesn't crash
        meshio.write(facet_xdmf_path, meshio.Mesh(
            points=msh.points,
            cells=[(facet_type, np.zeros((0, 3 if facet_type == "triangle" else 2), dtype=int))],
        ))


# ---------------------------------------------------------------------------
# Linear static (small-strain linear elasticity)
# ---------------------------------------------------------------------------

def _run_linear_static(mesh_path: str, material_props: dict,
                       boundary_conditions: list, loads: list) -> dict:
    import dolfinx
    import dolfinx.fem
    import dolfinx.fem.petsc
    import dolfinx.io
    import dolfinx.mesh as dmesh
    import ufl
    from mpi4py import MPI
    from petsc4py import PETSc

    comm = MPI.COMM_WORLD

    E = float(material_props["E"])
    nu = float(material_props["nu"])
    yield_strength = float(material_props.get("yield_strength", 250e6))

    # Lamé parameters
    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))

    with tempfile.TemporaryDirectory() as tmp:
        xdmf_vol = str(Path(tmp) / "vol.xdmf")
        xdmf_fac = str(Path(tmp) / "fac.xdmf")
        _msh_to_xdmf(mesh_path, xdmf_vol, xdmf_fac)

        with dolfinx.io.XDMFFile(comm, xdmf_vol, "r") as f:
            domain = f.read_mesh(ghost_mode=dmesh.GhostMode.shared_facet)
            # try to read cell tags (physical volume groups for multi-body)
            try:
                cell_tags = f.read_meshtags(domain, name="gmsh:physical")
            except Exception:
                cell_tags = None

        tdim = domain.topology.dim
        fdim = tdim - 1
        domain.topology.create_connectivity(fdim, tdim)

        # Read facet tags if available
        facet_tags = None
        try:
            with dolfinx.io.XDMFFile(comm, xdmf_fac, "r") as f:
                facet_tags = f.read_meshtags(domain, name="gmsh:physical")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Function space: P1 Lagrange vector (displacement)
    # ------------------------------------------------------------------
    V = dolfinx.fem.functionspace(domain, ("Lagrange", 1, (tdim,)))

    # ------------------------------------------------------------------
    # UFL forms — standard small-strain linear elasticity
    #   σ(u) = λ tr(ε(u)) I + 2μ ε(u)
    #   ε(u) = sym(∇u)
    #   Weak form: ∫ σ(u):ε(v) dx = ∫ f·v dx + ∫ t·v ds
    # ------------------------------------------------------------------
    def eps(v):
        return ufl.sym(ufl.grad(v))

    def sigma(v):
        return lam * ufl.tr(eps(v)) * ufl.Identity(tdim) + 2.0 * mu * eps(v)

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)

    # Bilinear form
    a_form = ufl.inner(sigma(u), eps(v)) * ufl.dx

    # ------------------------------------------------------------------
    # Dirichlet BCs
    # ------------------------------------------------------------------
    bcs = []

    for bc_spec in boundary_conditions:
        bc_type = bc_spec.get("type", "fixed")
        tags = bc_spec.get("face_tags", [])

        if not tags:
            # Fallback: locate boundary geometrically if no tags provided
            # (shouldn't happen in normal use, but keeps things robust)
            facets = dmesh.locate_entities_boundary(
                domain, fdim, lambda x: np.ones(x.shape[1], dtype=bool)
            )
        else:
            if facet_tags is not None:
                mask = np.isin(facet_tags.values, tags)
                facets = facet_tags.indices[mask]
            else:
                # No facet tags loaded — fall back to all boundary facets
                facets = dmesh.locate_entities_boundary(
                    domain, fdim, lambda x: np.ones(x.shape[1], dtype=bool)
                )

        if len(facets) == 0:
            continue

        dofs = dolfinx.fem.locate_dofs_topological(V, fdim, facets)

        if bc_type == "fixed":
            bc_val = dolfinx.fem.Constant(domain, PETSc.ScalarType([0.0] * tdim))
            bcs.append(dolfinx.fem.dirichletbc(bc_val, dofs, V))
        elif bc_type == "displacement":
            ux = float(bc_spec.get("ux", 0.0))
            uy = float(bc_spec.get("uy", 0.0))
            uz = float(bc_spec.get("uz", 0.0)) if tdim == 3 else 0.0
            vals = [ux, uy, uz] if tdim == 3 else [ux, uy]
            bc_val = dolfinx.fem.Constant(domain, PETSc.ScalarType(vals))
            bcs.append(dolfinx.fem.dirichletbc(bc_val, dofs, V))

    # ------------------------------------------------------------------
    # Neumann loads (traction + pressure)
    # ------------------------------------------------------------------
    # Build facet meshtags for Neumann surfaces
    neumann_facets_list = []
    marker_id = 100

    for load_spec in loads:
        tags = load_spec.get("face_tags", [])
        if not tags:
            continue

        if facet_tags is not None:
            mask = np.isin(facet_tags.values, tags)
            lf = facet_tags.indices[mask]
        else:
            lf = np.array([], dtype=np.int32)

        if len(lf) > 0:
            neumann_facets_list.append((lf, marker_id, load_spec, tags))
            marker_id += 1

    # Assemble ds measure from combined facet tags
    if neumann_facets_list:
        all_nf = np.concatenate([x[0] for x in neumann_facets_list])
        all_nm = np.concatenate([
            np.full(len(x[0]), x[1], dtype=np.int32) for x in neumann_facets_list
        ])
        sort_idx = np.argsort(all_nf)
        neumann_mt = dmesh.meshtags(domain, fdim, all_nf[sort_idx], all_nm[sort_idx])
        ds = ufl.Measure("ds", domain=domain, subdomain_data=neumann_mt)
    else:
        ds = ufl.Measure("ds", domain=domain)

    # Build RHS linear form
    f_body = dolfinx.fem.Constant(domain, PETSc.ScalarType([0.0] * tdim))
    L_form = ufl.inner(f_body, v) * ufl.dx

    for lf, mid, load_spec, _tags in neumann_facets_list:
        load_type = load_spec.get("type", "force")
        value = float(load_spec.get("value", 0.0))

        if load_type == "pressure":
            # Pressure = normal traction (inward); direction computed from geometry
            # Use scalar pressure; positive value = compressive (into surface)
            # FEniCSx: t = -p * n  (n outward normal)
            n = ufl.FacetNormal(domain)
            t = dolfinx.fem.Constant(domain, PETSc.ScalarType(-value))
            L_form = L_form + ufl.inner(t * n, v) * ds(mid)
        elif load_type == "force":
            # Distribute force over tagged facets (uniform traction)
            # Direction: user can supply vector or we default to -z / -y
            direction = load_spec.get("direction", None)
            if direction is None:
                if tdim == 3:
                    direction = [0.0, 0.0, -1.0]
                else:
                    direction = [0.0, -1.0]
            t_vec = dolfinx.fem.Constant(domain, PETSc.ScalarType(
                [float(d) * value for d in direction[:tdim]]
            ))
            L_form = L_form + ufl.inner(t_vec, v) * ds(mid)
        elif load_type == "traction":
            direction = load_spec.get("direction", [0.0] * tdim)
            t_vec = dolfinx.fem.Constant(domain, PETSc.ScalarType(
                [float(d) * value for d in direction[:tdim]]
            ))
            L_form = L_form + ufl.inner(t_vec, v) * ds(mid)

    # ------------------------------------------------------------------
    # Solve
    # ------------------------------------------------------------------
    problem = dolfinx.fem.petsc.LinearProblem(
        a_form, L_form, bcs=bcs,
        petsc_options={"ksp_type": "preonly", "pc_type": "lu",
                       "pc_factor_mat_solver_type": "mumps"},
    )
    u_sol = problem.solve()

    # ------------------------------------------------------------------
    # Post-process: displacement magnitudes + von Mises stress
    # ------------------------------------------------------------------
    u_arr = u_sol.x.array.reshape(-1, tdim)
    disp_mag = np.linalg.norm(u_arr, axis=1)
    max_disp = float(np.max(disp_mag)) if len(disp_mag) > 0 else 0.0

    # Von Mises stress — interpolated into a DG0 scalar field
    # σ_vm = sqrt( 3/2 * s:s )  where s = σ - (1/3) tr(σ) I  (deviatoric)
    Q = dolfinx.fem.functionspace(domain, ("DG", 0))

    def von_mises_expr(v_field):
        s = sigma(v_field) - (1.0 / 3.0) * ufl.tr(sigma(v_field)) * ufl.Identity(tdim)
        return ufl.sqrt(3.0 / 2.0 * ufl.inner(s, s))

    vm_expr = dolfinx.fem.Expression(
        von_mises_expr(u_sol),
        Q.element.interpolation_points(),
    )
    vm_fn = dolfinx.fem.Function(Q)
    vm_fn.interpolate(vm_expr)
    vm_arr = vm_fn.x.array.copy()

    max_stress = float(np.max(vm_arr)) if len(vm_arr) > 0 else 0.0
    fos = float(yield_strength / max_stress) if max_stress > 0 else float("inf")

    # Per-node displacement components (for downstream use / FEMView extension)
    node_disp = [
        {"ux": float(row[0]), "uy": float(row[1]),
         "uz": float(row[2]) if tdim == 3 else 0.0,
         "mag": float(m)}
        for row, m in zip(u_arr.tolist(), disp_mag.tolist())
    ]

    return {
        "max_vonmises_stress": max_stress,
        "max_displacement": max_disp,
        "fos": fos,
        "displacements": disp_mag.tolist(),
        "stresses": vm_arr.tolist(),
        "node_displacements": node_disp,
        "bonded_contact": "shared-node (conformal Gmsh occ.fragment mesh)",
        "warnings": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Modal analysis
# ---------------------------------------------------------------------------

def _run_modal(mesh_path: str, material_props: dict,
               boundary_conditions: list) -> dict:
    import dolfinx
    import dolfinx.fem
    import dolfinx.fem.petsc
    import dolfinx.io
    import dolfinx.mesh as dmesh
    import ufl
    from mpi4py import MPI
    from petsc4py import PETSc

    comm = MPI.COMM_WORLD

    E = float(material_props["E"])
    nu = float(material_props["nu"])
    rho = float(material_props.get("rho", 7850.0))

    lam = E * nu / ((1.0 + nu) * (1.0 - 2.0 * nu))
    mu = E / (2.0 * (1.0 + nu))

    with tempfile.TemporaryDirectory() as tmp:
        xdmf_vol = str(Path(tmp) / "vol.xdmf")
        xdmf_fac = str(Path(tmp) / "fac.xdmf")
        _msh_to_xdmf(mesh_path, xdmf_vol, xdmf_fac)

        with dolfinx.io.XDMFFile(comm, xdmf_vol, "r") as f:
            domain = f.read_mesh(ghost_mode=dmesh.GhostMode.shared_facet)

    tdim = domain.topology.dim
    fdim = tdim - 1
    domain.topology.create_connectivity(fdim, tdim)

    V = dolfinx.fem.functionspace(domain, ("Lagrange", 1, (tdim,)))

    def eps(v):
        return ufl.sym(ufl.grad(v))

    def sigma(v):
        return lam * ufl.tr(eps(v)) * ufl.Identity(tdim) + 2.0 * mu * eps(v)

    u = ufl.TrialFunction(V)
    v = ufl.TestFunction(V)

    k_form = dolfinx.fem.form(ufl.inner(sigma(u), eps(v)) * ufl.dx)
    m_form = dolfinx.fem.form(rho * ufl.inner(u, v) * ufl.dx)

    K = dolfinx.fem.petsc.assemble_matrix(k_form)
    M = dolfinx.fem.petsc.assemble_matrix(m_form)
    K.assemble()
    M.assemble()

    try:
        from slepc4py import SLEPc
    except ImportError:
        return {
            "frequencies": [],
            "warnings": ["SLEPc not installed — modal analysis unavailable"],
            "errors": [],
        }

    eps_solver = SLEPc.EPS().create(comm)
    eps_solver.setOperators(K, M)
    eps_solver.setProblemType(SLEPc.EPS.ProblemType.GHEP)
    eps_solver.setDimensions(nev=10)
    eps_solver.setTolerances(tol=1e-6, max_it=1000)
    eps_solver.solve()

    nconv = eps_solver.getConverged()
    frequencies = []
    for i in range(min(nconv, 10)):
        eigval = eps_solver.getEigenvalue(i)
        omega2 = eigval.real
        if omega2 > 0:
            freq = float(np.sqrt(omega2) / (2.0 * np.pi))
            frequencies.append(freq)

    return {
        "frequencies": frequencies,
        "warnings": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Thermal (steady-state heat conduction)
# ---------------------------------------------------------------------------

def _run_thermal(mesh_path: str, material_props: dict,
                 boundary_conditions: list, loads: list) -> dict:
    import dolfinx
    import dolfinx.fem
    import dolfinx.fem.petsc
    import dolfinx.io
    import dolfinx.mesh as dmesh
    import ufl
    from mpi4py import MPI
    from petsc4py import PETSc

    comm = MPI.COMM_WORLD

    k_cond = float(material_props.get("k", 205.0))

    with tempfile.TemporaryDirectory() as tmp:
        xdmf_vol = str(Path(tmp) / "vol.xdmf")
        xdmf_fac = str(Path(tmp) / "fac.xdmf")
        _msh_to_xdmf(mesh_path, xdmf_vol, xdmf_fac)

        with dolfinx.io.XDMFFile(comm, xdmf_vol, "r") as f:
            domain = f.read_mesh(ghost_mode=dmesh.GhostMode.shared_facet)

        facet_tags = None
        try:
            with dolfinx.io.XDMFFile(comm, xdmf_fac, "r") as f:
                facet_tags = f.read_meshtags(domain, name="gmsh:physical")
        except Exception:
            pass

    tdim = domain.topology.dim
    fdim = tdim - 1
    domain.topology.create_connectivity(fdim, tdim)

    V = dolfinx.fem.functionspace(domain, ("Lagrange", 1))

    T = ufl.TrialFunction(V)
    q = ufl.TestFunction(V)
    k = dolfinx.fem.Constant(domain, PETSc.ScalarType(k_cond))
    Q_src = dolfinx.fem.Constant(domain, PETSc.ScalarType(0.0))

    a_form = k * ufl.inner(ufl.grad(T), ufl.grad(q)) * ufl.dx
    L_form = Q_src * q * ufl.dx

    bcs = []
    for bc_spec in boundary_conditions:
        tags = bc_spec.get("face_tags", [])
        if facet_tags is not None and tags:
            mask = np.isin(facet_tags.values, tags)
            facets = facet_tags.indices[mask]
        else:
            facets = dmesh.locate_entities_boundary(
                domain, fdim, lambda x: np.ones(x.shape[1], dtype=bool)
            )
        if len(facets) == 0:
            continue
        dofs = dolfinx.fem.locate_dofs_topological(V, fdim, facets)
        T_val = float(bc_spec.get("temperature", 0.0))
        bc_const = dolfinx.fem.Constant(domain, PETSc.ScalarType(T_val))
        bcs.append(dolfinx.fem.dirichletbc(bc_const, dofs, V))

    problem = dolfinx.fem.petsc.LinearProblem(
        a_form, L_form, bcs=bcs,
        petsc_options={"ksp_type": "preonly", "pc_type": "lu"},
    )
    T_sol = problem.solve()

    return {
        "temperatures": T_sol.x.array.tolist(),
        "warnings": [],
        "errors": [],
    }
