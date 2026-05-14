# Running Finite-Element Analysis

Kerf can run a stress analysis on a STEP file using Gmsh for meshing
and either FEniCSx or CalculiX as the solver. The analysis returns:

- **Max von-Mises stress** — peak stress across the mesh
- **Displacement** — max displacement magnitude in X/Y/Z
- **FoS (Factor of Safety)** — ratio of yield strength to max von-Mises
- **Modal frequencies** — first N natural frequencies (optional)

## Workflow

1. Upload a STEP file via `POST /api/projects/{pid}/files` or the asset upload endpoint.
2. Call `fem_run` with the file UUID, material properties, boundary conditions, and loads.
3. Poll `fem_job_status` with the same file UUID until `status` is `done` or `error`.
4. On `done`, the `result` object contains the analysis output.

## `fem_run` tool

```
file_id          UUID of the STEP file (required)
material_props   {E, nu, rho, yield_strength} (required)
boundary_conditions  [{type, face_tags, ux?, uy?, uz?}] (required, at least 1)
loads            [{type, face_tags, value}] (required, at least 1)
mesh_size        Target element size in metres (optional, default 0.01)
solver           "fenicsx" | "calculix" (optional, default "fenicsx")
```

### Material properties

| Field            | Units      | Description                       |
|------------------|------------|-----------------------------------|
| `E`              | Pa         | Young's modulus                   |
| `nu`             | —          | Poisson's ratio                   |
| `rho`            | kg/m³      | Density                           |
| `yield_strength` | Pa         | Yield strength for FoS calculation |

Example for steel:

```json
{"E": 200e9, "nu": 0.3, "rho": 7850.0, "yield_strength": 250e6}
```

### Boundary conditions

`type: "fixed"` — fully constrained (zero displacement).

`type: "displacement"` — prescribe specific displacement components.

`face_tags` are Gmsh physical group IDs. When meshing via the FEM pipeline
the physical groups are assigned automatically; use `1` for the entire
bottom face of a simple part (Y=0 plane), `2` for side faces, etc. The
LLM should suggest reasonable face tags based on part geometry.

### Loads

`type: "pressure"` — normal traction (Pa) applied as −p·n on the face (positive value = compressive).

`type: "force"` — total force (N) distributed uniformly over the face; optional `direction` array `[dx, dy, dz]` (unit vector, default −z in 3D).

`type: "traction"` — uniform traction vector (Pa); requires `direction` unit vector and `value` magnitude in Pa.

## `fem_job_status` tool

```
file_id   UUID of the file to poll (required)
```

Returns:

```json
{
  "file_id": "<uuid>",
  "status": "queued" | "running" | "done" | "error" | "pending",
  "result": {
    "max_vonmises_stress": 1.2e8,
    "max_displacement": 0.0023,
    "fos": 2.08,
    "displacements": [0.001, 0.002, ...],
    "stresses": [8.5e7, 9.1e7, ...],
    "node_displacements": [{"ux": 0.0, "uy": -0.002, "uz": 0.0, "mag": 0.002}, ...],
    "bonded_contact": "shared-node (conformal Gmsh occ.fragment mesh)",
    "frequencies": [120.5, 340.2, 610.8],
    "warnings": []
  },
  "error": "..." // only when status == "error"
}
```

- `displacements` — per-node magnitude array (length = number of mesh nodes).
- `stresses` — per-element von Mises stress array (DG0, length = number of mesh cells).
- `node_displacements` — per-node `{ux, uy, uz, mag}` components; useful for deformed-shape rendering.
- `bonded_contact` — documents the contact strategy used ("shared-node (conformal Gmsh occ.fragment mesh)").
  When dolfinx is not installed the result has `status: "pending"` and a `warnings` entry.

## REST endpoint

```
POST /api/projects/{pid}/files/{fid}/fem
```

Body:

```json
{
  "material_props": {"E": 200e9, "nu": 0.3, "rho": 7850.0, "yield_strength": 250e6},
  "boundary_conditions": [{"type": "fixed", "face_tags": [1]}],
  "loads": [{"type": "pressure", "face_tags": [2], "value": 1e6}],
  "mesh_size": 0.01,
  "solver": "fenicsx"
}
```

Response `202 Accepted`:

```json
{"job_id": "<uuid>", "status": "queued"}
```

## Notes

- The Gmsh mesher reads STEP via `gmsh.model.occ.importShapes` and generates a 3D tetrahedral mesh.
- FEniCSx solves small-strain linear elasticity: σ = λ tr(ε) I + 2μ ε, weak form ∫ σ:ε(v) dx = ∫ f·v dx + ∫ t·v ds.
- Dirichlet BCs set zero (or prescribed) displacement on tagged boundary facets. Neumann loads apply traction or pressure on tagged facets.
- FoS is computed as `yield_strength / max_vonmises_stress`.
- Bonded contact (multi-body assemblies) uses the shared-node approach: Gmsh `occ.fragment()` produces a conformal tetrahedral mesh where touching bodies share nodes, enforcing displacement continuity at the interface without Lagrange multipliers.
- Modal analysis is performed when `solver: "fenicsx"` and `analysis_type: "modal"` (requires SLEPc); CalculiX modal analysis is a future enhancement.
- When dolfinx is not installed, the route returns `{"status": "pending", "warnings": ["Engine pending — FEniCSx (dolfinx) not yet installed."]}` rather than a 500 error.
- Physical face tags in Gmsh correspond to CAD faces. For simple geometry, the LLM should infer face tags from the STEP topology or document them explicitly in `boundary_conditions`.