# Aerospace — CFD, Trajectory, and Structural Analysis

`kerf-aero` integrates aerodynamics and aerospace-domain workflows into Kerf
projects. It provides CFD mesh import, panel-method aerodynamic analysis,
six-degrees-of-freedom (6-DOF) trajectory simulation, and structural margin
checks for aerospace components — all linked to the same files and LLM chat
context as your CAD.

---

## Overview

| Property | Value |
|---|---|
| Package | `kerf-aero` |
| Plugin entry-point | `kerf_aero.plugin:register` |
| Capability tag | `aero.analysis` |
| Source | `packages/kerf-aero/` |

---

## File types

| Extension | Kind | Description |
|---|---|---|
| `.stl` | `stl_mesh` | STL surface mesh — input to CFD/panel solvers |
| `.aero` | `aero_study` | JSON: aerodynamic study configuration and cached results |
| `.traj` | `trajectory` | JSON: 6-DOF trajectory simulation definition and time-series results |
| `.atm` | `atmosphere_profile` | Tabular atmosphere model (altitude, density, temperature, pressure) |
| `.adb` | `aero_database` | Aerodynamic coefficient database (CL, CD, CM vs α, β, Mach) — CSV or HDF5 |
| `.su2` | `su2_config` | SU2 CFD solver configuration file |

---

## Key concepts

### Aerodynamic coefficients

Kerf stores aerodynamic data in the standard coefficient form:

| Symbol | Name | Description |
|---|---|---|
| CL | Lift coefficient | L / (½ ρ V² S) |
| CD | Drag coefficient | D / (½ ρ V² S) |
| CM | Pitching moment coefficient | M / (½ ρ V² S c) |
| CY | Side-force coefficient | Y / (½ ρ V² S) |
| Cn | Yaw moment coefficient | N / (½ ρ V² S b) |
| Cl | Roll moment coefficient | L_roll / (½ ρ V² S b) |

Reference area `S`, reference chord `c`, and reference span `b` are defined in
the `.aero` study file.

### Atmosphere models

| Model | ID | Altitude range |
|---|---|---|
| US Standard Atmosphere 1976 | `isa76` | 0–86 km |
| NRLMSISE-00 | `nrlmsise00` | 0–1000 km |
| Custom tabular | `custom` | User-supplied `.atm` file |

---

## LLM tools

### `run_panel_analysis`

Run a vortex-lattice or source-panel aerodynamic analysis on an STL surface.
Uses [AVL](https://web.mit.edu/drela/Public/web/avl/) (MIT, subprocess) for
vortex-lattice and a built-in source-panel solver for bodies of revolution.

```json
{
  "mesh_file_id": "<uuid of .stl>",
  "alpha_range": [-5, 20],
  "alpha_step": 1,
  "mach": 0.3,
  "reference": {
    "area": 1.2,
    "chord": 0.4,
    "span": 3.0,
    "x_ref": 0.5
  }
}
```

Returns a polar table (α, CL, CD, CM) and the neutral point location as a
fraction of the reference chord. Results are cached in the `.aero` study file.

---

### `run_trajectory`

Simulate a 6-DOF trajectory from launch/release conditions to impact/MECO.

```json
{
  "traj_file_id": "<uuid of .traj>",
  "aero_file_id": "<uuid of .aero>",
  "atmosphere": "isa76",
  "dt": 0.01,
  "max_time": 300
}
```

Integration uses RK4. Returns time-series arrays:

```json
{
  "t": [0.0, 0.01, ...],
  "x": [...], "y": [...], "z": [...],
  "vx": [...], "vy": [...], "vz": [...],
  "pitch": [...], "yaw": [...], "roll": [...],
  "mach": [...], "dynamic_pressure": [...],
  "apogee_m": 4823.1,
  "range_m": 12043.7,
  "max_mach": 1.82
}
```

---

### `check_structural_margins`

Check load factors and structural margins at max-Q and max-G waypoints along a
trajectory, given a material property set and a cross-section geometry.

```json
{
  "traj_file_id": "<uuid>",
  "material": "al6061-t6",
  "wall_thickness_mm": 3.0,
  "outer_diameter_mm": 120.0
}
```

Built-in materials: `al6061-t6`, `al7075-t6`, `ti6al4v`, `steel-4130`,
`cfrp-ud`, `cfrp-woven`, `fiberglass`.

Returns margins of safety for axial load, bending, and hoop stress at each
critical point.

---

### `import_aero_database`

Import aerodynamic coefficient data from a CSV or HDF5 aerodynamic database
and attach it to an `.aero` study file.

```json
{
  "file_id": "<uuid of .adb file>",
  "study_file_id": "<uuid of .aero file>",
  "alpha_col": "alpha_deg",
  "cl_col": "CL",
  "cd_col": "CD"
}
```

Once imported, `run_trajectory` can interpolate CL/CD/CM from the database
rather than from the panel-method results.

---

## HTTP routes

| Method | Path | Description |
|---|---|---|
| `POST` | `/aero/panel-analysis` | Run vortex-lattice or panel aerodynamic analysis |
| `POST` | `/aero/trajectory` | 6-DOF trajectory integration |
| `POST` | `/aero/structural-margins` | Load-factor margin check at critical waypoints |
| `POST` | `/aero/import-adb` | Import aerodynamic coefficient database |
| `GET` | `/aero/atmosphere/{model}` | Tabular atmosphere query (altitude → density/pressure) |

---

## Typical workflow

1. Export a surface mesh from the CAD view as `.stl`.
2. Create an `.aero` study file (or ask the LLM to call `run_panel_analysis`
   directly with the mesh file ID).
3. Review the polar table: check CL/CD ratio and neutral-point margin.
4. Create a `.traj` file with initial conditions. Call `run_trajectory`.
5. Call `check_structural_margins` on the trajectory to confirm the airframe
   survives max-Q.

---

## Related documentation

| Topic | Path |
|---|---|
| FEM / structural analysis | `packages/kerf-fem/` |
| Imports (STEP/IGES) | `docs/imports.md` |
| Plugin development | `docs/plugins-development.md` |
| SDK scripting | `docs/sdk.md` |
