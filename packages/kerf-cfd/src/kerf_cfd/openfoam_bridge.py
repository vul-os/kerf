"""
OpenFOAM bridge — case generator, polyMesh writer, field result parser, and
execution helpers.

High-level workflow
-------------------
1. Call :func:`write_case` to generate a full OpenFOAM case directory tree
   (wraps :func:`~openfoam_case_template.build_case` and adds BC mapping +
   optional polyMesh serialisation from a Kerf mesh object).
2. Optionally run ``blockMesh`` to generate the mesh via :func:`run_blockmesh`.
3. Call :func:`run_solver` to shell out to ``simpleFoam`` or ``pimpleFoam``.
4. Call :func:`read_results` to parse ASCII field files at a time step into
   numpy arrays (U, p, k, ε) wrapped in a :class:`ResultBundle`.
5. Call :func:`parse_postprocessing` to extract scalar timeseries from the
   ``postProcessing/`` directory.

Case generator — :func:`write_case`
------------------------------------
Produces the canonical directory tree::

    <case>/
        system/{controlDict, fvSchemes, fvSolution, blockMeshDict}
        constant/{transportProperties, turbulenceProperties, polyMesh/…}
        0/{U, p, k, epsilon | omega, nut}

Supported solvers:  ``simpleFoam`` (steady RANS) and ``pisoFoam`` / ``pimpleFoam``
(transient RANS).  Turbulence: ``laminar``, ``kOmegaSST``, ``kEpsilon``.

polyMesh writer — :func:`write_polymesh`
-----------------------------------------
Converts from either:
  a. A :class:`~kerf_cfd.mesh_3d.Mesh3D` object (T-101-B format), or
  b. A generic dict-of-arrays mesh::

       {
         "points":    [[x,y,z], ...],          # N_pts × 3
         "faces":     [[v0,v1,…], ...],         # N_faces, variable nv
         "owner":     [cell_id, ...],           # N_faces
         "neighbour": [cell_id, ...],           # N_internal_faces
         "patches":   {"name": {"start":i,"nFaces":n,"type":t}, ...}
       }

into OpenFOAM ``polyMesh/{points, faces, owner, neighbour, boundary}``.

BC mapping
-----------
Kerf BC keys map to OpenFOAM patch types:

    "inlet"    → ``patch``  (fixedValue U, zeroGradient p)
    "outlet"   → ``patch``  (zeroGradient U, fixedValue p=0)
    "wall"     → ``wall``   (noSlip U, zeroGradient p)
    "symmetry" → ``symmetry``

Result parser — :func:`read_results`
--------------------------------------
Parses OpenFOAM's ASCII ``internalField`` format::

    <N>
    (
    value0
    value1
    ...
    )

Returns a :class:`ResultBundle` (numpy arrays for U, p, k, ε).

Graceful degrade
----------------
When the requested binary is not on PATH the runner functions return
``status == "pending"`` rather than raising — consistent with
``calculix_utils.py`` and ``fenicsx_utils.py``.

Hagen-Poiseuille analytic oracle
---------------------------------
``pipe_friction_factor_laminar(Re)`` returns the Darcy-Weisbach friction
factor for laminar pipe flow:

    f = 64 / Re                        (Moody chart laminar branch)

Reference: White F.M., Fluid Mechanics, 8th ed., §6.4;
           Munson, Okiishi, Huebsch, Rothmayer, Fundamentals of Fluid
           Mechanics, 7th ed., §8.3.

Scope / limits
--------------
- polyMesh writer and field reader are pure Python; no OpenFOAM install needed.
- Field reader supports ASCII ``writeFormat`` only.
- Errors in subprocess execution appear in the ``errors`` list, not exceptions.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# T-101-C: OpenFOAMCaseSpec / OpenFOAMExportResult / export_to_openfoam
# ---------------------------------------------------------------------------

@dataclass
class OpenFOAMCaseSpec:
    """
    Specification for exporting a Kerf CFD case to an OpenFOAM 11 case directory.

    Parameters
    ----------
    case_name : str
        Name of the case (used as the root directory name when *output_dir* is
        a parent; not enforced on the filesystem path).
    mesh_vertices_xyz : list[tuple[float, float, float]]
        List of (x, y, z) vertex coordinates.
    mesh_cells : list[list[int]]
        Cell connectivity — each entry is a list of vertex indices (hex: 8
        nodes; tet: 4 nodes).  Mixed element types are supported.
    boundary_patches : dict[str, dict]
        Mapping of patch name → patch descriptor.  Each descriptor must contain:
          ``type``  — one of ``"wall"``, ``"inlet"``, ``"outlet"``, ``"symmetry"``
          ``faces`` — list of face indices (into a face list derived from cells)
                      OR list of vertex-index lists defining the patch faces.
    inlet_velocity_m_per_s : float
        Mean inlet velocity magnitude (m/s, x-direction).
    outlet_pressure_pa : float
        Static pressure at the outlet patch (Pa).
    fluid_density_kg_m3 : float
        Fluid density (kg/m³).  Default 1.225 (air at 15 °C, 1 atm).
    fluid_viscosity_pa_s : float
        Dynamic viscosity (Pa·s).  Default 1.8e-5 (air).
    turbulence_model : str
        RANS turbulence model.  One of ``"kEpsilon"`` (default), ``"kOmegaSST"``,
        ``"laminar"``.
    solver : str
        OpenFOAM solver application.  Default ``"simpleFoam"`` (steady RANS).
    end_time_s : float
        End time / iteration count.  Default 1000.0.
    write_interval : int
        Write interval (time steps).  Default 100.

    Notes
    -----
    Physical pressure:  OpenFOAM's ``p`` field is kinematic pressure p/ρ
    (m²/s²).  ``outlet_pressure_pa`` is divided by ``fluid_density_kg_m3``
    internally when writing the 0/p boundary condition.

    Reference: OpenFOAM 11 User Guide §4 — case structure.
    """
    case_name: str
    mesh_vertices_xyz: list
    mesh_cells: list
    boundary_patches: dict
    inlet_velocity_m_per_s: float
    outlet_pressure_pa: float
    fluid_density_kg_m3: float = 1.225
    fluid_viscosity_pa_s: float = 1.8e-5
    turbulence_model: str = "kEpsilon"
    solver: str = "simpleFoam"
    end_time_s: float = 1000.0
    write_interval: int = 100


@dataclass
class OpenFOAMExportResult:
    """
    Result of :func:`export_to_openfoam`.

    Parameters
    ----------
    output_dir_path : str
        Absolute path to the generated OpenFOAM case root directory.
    files_generated : list[str]
        Relative paths (from the case root) of every file written.
    num_cells : int
        Number of mesh cells in the exported case.
    num_boundary_patches : int
        Number of named boundary patches.
    mesh_quality_warnings : list[str]
        Non-fatal mesh quality observations (e.g. degenerate faces, large
        aspect-ratio cells).  Empty list if no warnings.
    honest_caveat : str
        Plain-language description of what was NOT done and what the user must
        do manually to run the case with OpenFOAM.
    """
    output_dir_path: str
    files_generated: list
    num_cells: int
    num_boundary_patches: int
    mesh_quality_warnings: list
    honest_caveat: str


# ---------------------------------------------------------------------------
# polyMesh helpers for export_to_openfoam
# ---------------------------------------------------------------------------

def _cells_to_polymesh_dict(
    vertices: list,
    cells: list,
    boundary_patches: dict,
) -> dict:
    """
    Convert vertex + cell connectivity to a dict-of-arrays suitable for
    :func:`write_polymesh`.

    Supports:
    - Tet cells (4 vertices) — 4 triangular faces
    - Hex cells (8 vertices) — 6 quadrilateral faces

    Mixed-element meshes are accepted.  Face orientation is not guaranteed to
    follow the OpenFOAM right-hand-rule normal pointing outward from the owner
    cell; for real CFD runs the user should run ``checkMesh`` after importing.

    Boundary patches in *boundary_patches* may specify ``"faces"`` as:
    - list[int]  — face indices into the computed face list (applied after
                   internal faces are determined)
    - list[list[int]]  — explicit per-face vertex-index lists (matched by
                         sorted vertex tuple)

    When ``"faces"`` is absent or empty the patch is registered with 0 faces
    (placeholder).
    """
    # Build all cell faces
    def _tet_faces(cell):
        """Return the 4 triangular faces of a tet in counter-clockwise order."""
        a, b, c, d = cell[0], cell[1], cell[2], cell[3]
        return [(a, b, c), (a, b, d), (a, c, d), (b, c, d)]

    def _hex_faces(cell):
        """Return the 6 quadrilateral faces of a hex (0-indexed as blockMesh)."""
        v = cell
        return [
            (v[0], v[3], v[2], v[1]),  # bottom
            (v[4], v[5], v[6], v[7]),  # top
            (v[0], v[1], v[5], v[4]),  # front
            (v[2], v[3], v[7], v[6]),  # back
            (v[0], v[4], v[7], v[3]),  # left
            (v[1], v[2], v[6], v[5]),  # right
        ]

    # face_key (sorted tuple) → list of (cell_id, face_vertices)
    face_owners_raw: dict[tuple, list] = {}
    for cell_id, cell in enumerate(cells):
        n = len(cell)
        if n == 4:
            raw_faces = _tet_faces(cell)
        elif n == 8:
            raw_faces = _hex_faces(cell)
        else:
            # Generic: treat each (n-1)-combination as a face
            from itertools import combinations
            raw_faces = [tuple(combo) for combo in combinations(cell, n - 1)]
        for fverts in raw_faces:
            key = tuple(sorted(fverts))
            if key not in face_owners_raw:
                face_owners_raw[key] = []
            face_owners_raw[key].append((cell_id, fverts))

    # Separate internal (shared) and boundary faces
    internal_faces = []
    internal_owner = []
    internal_neighbour = []
    boundary_face_list = []
    boundary_owner_list = []

    for key, owners in sorted(face_owners_raw.items()):
        if len(owners) == 2:
            (oid, ofverts), (nid, _) = owners
            if oid > nid:
                oid, nid = nid, oid
                ofverts = owners[1][1]
            internal_faces.append(tuple(ofverts))
            internal_owner.append(oid)
            internal_neighbour.append(nid)
        else:
            cell_id, fverts = owners[0]
            boundary_face_list.append(tuple(fverts))
            boundary_owner_list.append(cell_id)

    # Build a lookup: sorted-key → boundary face index (into boundary_face_list)
    boundary_key_to_idx: dict[tuple, int] = {
        tuple(sorted(f)): i for i, f in enumerate(boundary_face_list)
    }

    # Assign boundary patch names to boundary face indices
    n_internal = len(internal_faces)
    patch_assignments: dict[str, list[int]] = {}  # patch_name → boundary face indices

    for pname, pdef in boundary_patches.items():
        faces_spec = pdef.get("faces", [])
        assigned: list[int] = []
        if faces_spec:
            first = faces_spec[0]
            if isinstance(first, (list, tuple)):
                # Explicit vertex lists
                for fv in faces_spec:
                    k = tuple(sorted(fv))
                    if k in boundary_key_to_idx:
                        assigned.append(boundary_key_to_idx[k])
            else:
                # Integers: treat as raw boundary face indices
                for fi in faces_spec:
                    if isinstance(fi, int) and 0 <= fi < len(boundary_face_list):
                        assigned.append(fi)
        patch_assignments[pname] = sorted(set(assigned))

    # Collect all assigned boundary face indices in patch order
    assigned_set: set[int] = set()
    for idxs in patch_assignments.values():
        assigned_set.update(idxs)

    # Unassigned boundary faces → implicit "default" wall patch
    unassigned = [
        i for i in range(len(boundary_face_list)) if i not in assigned_set
    ]

    # Build ordered face list: internal | patch_0 | patch_1 | … | unassigned
    all_faces = list(internal_faces)
    all_owner = list(internal_owner)
    all_neighbour_arr = list(internal_neighbour)

    patches_dict: dict[str, Any] = {}
    offset = n_internal

    for pname, idxs in patch_assignments.items():
        ptype = boundary_patches[pname].get("type", "wall")
        patches_dict[pname] = {
            "start": offset,
            "nFaces": len(idxs),
            "type": ptype,
        }
        for bi in idxs:
            all_faces.append(boundary_face_list[bi])
            all_owner.append(boundary_owner_list[bi])
        offset += len(idxs)

    if unassigned:
        patches_dict["defaultWalls"] = {
            "start": offset,
            "nFaces": len(unassigned),
            "type": "wall",
        }
        for bi in unassigned:
            all_faces.append(boundary_face_list[bi])
            all_owner.append(boundary_owner_list[bi])

    return {
        "points": list(vertices),
        "faces": all_faces,
        "owner": all_owner,
        "neighbour": all_neighbour_arr,
        "patches": patches_dict,
    }


def _mesh_quality_warnings(vertices: list, cells: list) -> list[str]:
    """Return non-fatal mesh quality warnings without raising."""
    warnings = []
    if not vertices:
        warnings.append("Mesh has no vertices.")
        return warnings
    if not cells:
        warnings.append("Mesh has no cells.")
        return warnings

    # Check for degenerate cells (duplicate vertex indices)
    for i, cell in enumerate(cells):
        if len(set(cell)) < len(cell):
            warnings.append(
                f"Cell {i} has duplicate vertex indices — degenerate element."
            )
            if len(warnings) >= 10:
                warnings.append("(further quality warnings suppressed)")
                break

    # Rough aspect-ratio check for tet/hex cells
    if len(warnings) < 10:
        for i, cell in enumerate(cells[:500]):
            coords = [vertices[v] for v in cell if v < len(vertices)]
            if len(coords) < 2:
                continue
            from_origin = coords[0]
            dists = [
                math.sqrt(
                    (c[0] - coords[0][0]) ** 2
                    + (c[1] - coords[0][1]) ** 2
                    + (c[2] - coords[0][2]) ** 2
                )
                for c in coords[1:]
            ]
            if dists and max(dists) > 0 and min(dists) / max(dists) < 0.001:
                warnings.append(
                    f"Cell {i} has high aspect ratio "
                    f"(min_edge/max_edge < 0.001)."
                )
    return warnings


# ---------------------------------------------------------------------------
# Primary public export API
# ---------------------------------------------------------------------------

def export_to_openfoam(
    spec: "OpenFOAMCaseSpec",
    output_dir: str,
) -> "OpenFOAMExportResult":
    """
    Export a Kerf CFD case to a valid OpenFOAM 11 case directory structure.

    This function writes the complete case tree that an external OpenFOAM
    installation can run without modification (assuming a valid mesh).  It is
    a pure file-I/O adapter — it does NOT invoke OpenFOAM binaries, does NOT
    validate the mesh against OpenFOAM's own checkers, and does NOT guarantee
    convergence of the chosen solver.

    Directory tree written
    ----------------------
    ::

        <output_dir>/
            0/
                U            (velocity field, fixedValue at inlet)
                p            (kinematic pressure, fixedValue at outlet)
                k            (TKE — kEpsilon or kOmegaSST only)
                epsilon      (ε — kEpsilon only)
                omega        (ω — kOmegaSST only)
                nut          (turbulent viscosity)
            constant/
                transportProperties
                turbulenceProperties
                polyMesh/
                    points
                    faces
                    owner
                    neighbour
                    boundary
            system/
                controlDict
                fvSchemes
                fvSolution

    Parameters
    ----------
    spec : OpenFOAMCaseSpec
        Case specification (mesh, BCs, fluid properties, solver settings).
    output_dir : str
        Absolute path to the destination directory (created if absent).

    Returns
    -------
    OpenFOAMExportResult
        Result dataclass with path, file manifest, cell count, and honest
        caveats.

    Raises
    ------
    ValueError
        If the mesh is empty (no vertices or no cells).
    OSError
        If the output directory cannot be created or files cannot be written.

    Notes
    -----
    Kinematic pressure convention: OpenFOAM's ``p`` field stores p/ρ (m²/s²).
    ``outlet_pressure_pa`` is divided by ``fluid_density_kg_m3`` before writing.

    Kinematic viscosity: ν = μ/ρ is computed from ``fluid_viscosity_pa_s`` and
    ``fluid_density_kg_m3``.

    Reference: OpenFOAM 11 User Guide §4 (case structure); White §6.4.
    """
    if not spec.mesh_vertices_xyz:
        raise ValueError(
            "export_to_openfoam: mesh_vertices_xyz is empty — cannot export a case "
            "with no vertices."
        )
    if not spec.mesh_cells:
        raise ValueError(
            "export_to_openfoam: mesh_cells is empty — cannot export a case "
            "with no cells."
        )

    root = Path(output_dir).resolve()
    system_dir = root / "system"
    constant_dir = root / "constant"
    poly_dir = constant_dir / "polyMesh"
    zero_dir = root / "0"

    for d in (system_dir, constant_dir, poly_dir, zero_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Derived quantities
    nu = spec.fluid_viscosity_pa_s / spec.fluid_density_kg_m3  # kinematic viscosity
    p_outlet_kinematic = spec.outlet_pressure_pa / spec.fluid_density_kg_m3
    u_inlet = spec.inlet_velocity_m_per_s

    # Turbulence initial conditions (reasonable defaults)
    turb_intensity = 0.05  # 5%
    k_inlet = 1.5 * (turb_intensity * u_inlet) ** 2
    epsilon_inlet = 0.09 * k_inlet ** 1.5 / 0.1  # assuming L_turb = 0.1 m
    omega_inlet = math.sqrt(k_inlet) / 0.1 if k_inlet > 0 else 1.0

    # Patch names by type
    inlet_patches = [
        n for n, d in spec.boundary_patches.items() if d.get("type") == "inlet"
    ]
    outlet_patches = [
        n for n, d in spec.boundary_patches.items() if d.get("type") == "outlet"
    ]

    # Mesh quality check (non-fatal)
    quality_warnings = _mesh_quality_warnings(
        spec.mesh_vertices_xyz, spec.mesh_cells
    )

    # Build polyMesh dict from spec
    mesh_dict = _cells_to_polymesh_dict(
        spec.mesh_vertices_xyz,
        spec.mesh_cells,
        spec.boundary_patches,
    )

    # 1. Write polyMesh files
    write_polymesh(poly_dir, mesh_dict)

    # 2. Write 0/ field files
    _export_write_fields(
        zero_dir,
        bcs=spec.boundary_patches,
        turbulence_model=spec.turbulence_model,
        u_inlet=u_inlet,
        p_outlet_kinematic=p_outlet_kinematic,
        k_inlet=k_inlet,
        epsilon_inlet=epsilon_inlet,
        omega_inlet=omega_inlet,
    )

    # 3. Write constant/ files
    _export_write_transport(constant_dir / "transportProperties", nu)
    _export_write_turbulence(
        constant_dir / "turbulenceProperties", spec.turbulence_model
    )

    # 4. Write system/ files
    solver = spec.solver
    if solver == "pisoFoam":
        solver = "pimpleFoam"
    _export_write_control_dict(
        system_dir / "controlDict",
        solver=solver,
        end_time=spec.end_time_s,
        write_interval=spec.write_interval,
    )
    _export_write_fv_schemes(system_dir / "fvSchemes", solver=solver)
    _export_write_fv_solution(system_dir / "fvSolution", solver=solver)

    # Collect manifest
    files_generated: list[str] = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            files_generated.append(str(f.relative_to(root)))

    num_cells = len(spec.mesh_cells)
    num_patches = len(spec.boundary_patches)

    honest_caveat = (
        "This is a file-export adapter only.  OpenFOAM was NOT invoked and the "
        "mesh was NOT validated.  To run the case: (1) install OpenFOAM 11; "
        "(2) run 'checkMesh -case {out}' to verify mesh quality; (3) run "
        "'{solver} -case {out}' to solve; (4) post-process with ParaView or "
        "'foamToVTK'.  Note: polyMesh is written from Kerf cell connectivity — "
        "face orientation may require correction via 'renumberMesh'.  "
        "Turbulence initial conditions (k, ε, ω) are estimated from 5% inlet "
        "turbulence intensity with L_turb = 0.1 m; adjust in 0/ if needed."
    ).format(out=str(root), solver=spec.solver)

    return OpenFOAMExportResult(
        output_dir_path=str(root),
        files_generated=files_generated,
        num_cells=num_cells,
        num_boundary_patches=num_patches,
        mesh_quality_warnings=quality_warnings,
        honest_caveat=honest_caveat,
    )


# ---------------------------------------------------------------------------
# Field writers for export_to_openfoam (independent of write_case / build_case)
# ---------------------------------------------------------------------------

def _export_foam_header(foam_class: str, location: str, obj: str) -> str:
    return (
        "FoamFile\n{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        f"    class       {foam_class};\n"
        f"    location    \"{location}\";\n"
        f"    object      {obj};\n"
        "}"
    )


_EXPORT_PATCH_TYPE: dict[str, str] = {
    "inlet": "patch",
    "outlet": "patch",
    "wall": "wall",
    "symmetry": "symmetry",
    "empty": "empty",
    "patch": "patch",
    "cyclic": "cyclic",
}


def _export_write_fields(
    zero_dir: Path,
    *,
    bcs: dict,
    turbulence_model: str,
    u_inlet: float,
    p_outlet_kinematic: float,
    k_inlet: float,
    epsilon_inlet: float,
    omega_inlet: float,
) -> None:
    """Write 0/ field files for export_to_openfoam."""

    def _bc_lines_U(patch_name: str, bc_type: str) -> list[str]:
        lines = [f"    {patch_name}", "    {"]
        if bc_type == "inlet":
            lines += [
                "        type            fixedValue;",
                f"        value           uniform ({u_inlet:g} 0 0);",
            ]
        elif bc_type == "outlet":
            lines += ["        type            zeroGradient;"]
        elif bc_type == "wall":
            lines += ["        type            noSlip;"]
        elif bc_type == "symmetry":
            lines += ["        type            symmetry;"]
        else:
            lines += ["        type            zeroGradient;"]
        lines.append("    }")
        return lines

    def _bc_lines_p(patch_name: str, bc_type: str) -> list[str]:
        lines = [f"    {patch_name}", "    {"]
        if bc_type == "outlet":
            lines += [
                "        type            fixedValue;",
                f"        value           uniform {p_outlet_kinematic:g};",
            ]
        elif bc_type == "symmetry":
            lines += ["        type            symmetry;"]
        else:
            lines += ["        type            zeroGradient;"]
        lines.append("    }")
        return lines

    def _bc_lines_k(patch_name: str, bc_type: str) -> list[str]:
        lines = [f"    {patch_name}", "    {"]
        if bc_type == "inlet":
            lines += [
                "        type            fixedValue;",
                f"        value           uniform {k_inlet:g};",
            ]
        elif bc_type == "wall":
            lines += [
                "        type            kqRWallFunction;",
                f"        value           uniform {k_inlet:g};",
            ]
        elif bc_type == "symmetry":
            lines += ["        type            symmetry;"]
        else:
            lines += ["        type            zeroGradient;"]
        lines.append("    }")
        return lines

    def _bc_lines_epsilon(patch_name: str, bc_type: str) -> list[str]:
        lines = [f"    {patch_name}", "    {"]
        if bc_type == "inlet":
            lines += [
                "        type            fixedValue;",
                f"        value           uniform {epsilon_inlet:g};",
            ]
        elif bc_type == "wall":
            lines += [
                "        type            epsilonWallFunction;",
                f"        value           uniform {epsilon_inlet:g};",
            ]
        elif bc_type == "symmetry":
            lines += ["        type            symmetry;"]
        else:
            lines += ["        type            zeroGradient;"]
        lines.append("    }")
        return lines

    def _bc_lines_omega(patch_name: str, bc_type: str) -> list[str]:
        lines = [f"    {patch_name}", "    {"]
        if bc_type == "inlet":
            lines += [
                "        type            fixedValue;",
                f"        value           uniform {omega_inlet:g};",
            ]
        elif bc_type == "wall":
            lines += [
                "        type            omegaWallFunction;",
                f"        value           uniform {omega_inlet:g};",
            ]
        elif bc_type == "symmetry":
            lines += ["        type            symmetry;"]
        else:
            lines += ["        type            zeroGradient;"]
        lines.append("    }")
        return lines

    def _bc_lines_nut(patch_name: str, bc_type: str) -> list[str]:
        lines = [f"    {patch_name}", "    {"]
        if bc_type == "wall":
            lines += [
                "        type            nutkWallFunction;",
                "        value           uniform 0;",
            ]
        elif bc_type == "symmetry":
            lines += ["        type            symmetry;"]
        else:
            lines += [
                "        type            calculated;",
                "        value           uniform 0;",
            ]
        lines.append("    }")
        return lines

    def _build_bc_block(bc_fn) -> str:
        lines = ["boundaryField", "{"]
        for pname, pdef in bcs.items():
            ptype = pdef.get("type", "wall") if isinstance(pdef, dict) else "wall"
            lines.extend(bc_fn(pname, ptype))
        lines.append("}")
        return "\n".join(lines)

    # U
    (zero_dir / "U").write_text(
        f"{_export_foam_header('volVectorField', '0', 'U')}\n\n"
        f"dimensions      [0 1 -1 0 0 0 0];\n\n"
        f"internalField   uniform (0 0 0);\n\n"
        f"{_build_bc_block(_bc_lines_U)}\n"
    )

    # p
    (zero_dir / "p").write_text(
        f"{_export_foam_header('volScalarField', '0', 'p')}\n\n"
        f"dimensions      [0 2 -2 0 0 0 0];\n\n"
        f"internalField   uniform 0;\n\n"
        f"{_build_bc_block(_bc_lines_p)}\n"
    )

    # nut
    (zero_dir / "nut").write_text(
        f"{_export_foam_header('volScalarField', '0', 'nut')}\n\n"
        f"dimensions      [0 2 -1 0 0 0 0];\n\n"
        f"internalField   uniform 0;\n\n"
        f"{_build_bc_block(_bc_lines_nut)}\n"
    )

    # k (kEpsilon or kOmegaSST)
    if turbulence_model in ("kEpsilon", "kOmegaSST"):
        (zero_dir / "k").write_text(
            f"{_export_foam_header('volScalarField', '0', 'k')}\n\n"
            f"dimensions      [0 2 -2 0 0 0 0];\n\n"
            f"internalField   uniform {k_inlet:g};\n\n"
            f"{_build_bc_block(_bc_lines_k)}\n"
        )

    # epsilon
    if turbulence_model == "kEpsilon":
        (zero_dir / "epsilon").write_text(
            f"{_export_foam_header('volScalarField', '0', 'epsilon')}\n\n"
            f"dimensions      [0 2 -3 0 0 0 0];\n\n"
            f"internalField   uniform {epsilon_inlet:g};\n\n"
            f"{_build_bc_block(_bc_lines_epsilon)}\n"
        )

    # omega
    if turbulence_model == "kOmegaSST":
        (zero_dir / "omega").write_text(
            f"{_export_foam_header('volScalarField', '0', 'omega')}\n\n"
            f"dimensions      [0 0 -1 0 0 0 0];\n\n"
            f"internalField   uniform {omega_inlet:g};\n\n"
            f"{_build_bc_block(_bc_lines_omega)}\n"
        )


def _export_write_transport(path: Path, nu: float) -> None:
    path.write_text(
        f"{_export_foam_header('dictionary', 'constant', 'transportProperties')}\n\n"
        f"transportModel  Newtonian;\n\n"
        f"nu              {nu:g};\n"
    )


def _export_write_turbulence(path: Path, turbulence_model: str) -> None:
    model_map = {
        "kEpsilon": ("kEpsilon", "on"),
        "kOmegaSST": ("kOmegaSST", "on"),
        "laminar": ("laminar", "off"),
    }
    ras_model, turb_on = model_map.get(turbulence_model, ("kEpsilon", "on"))
    path.write_text(
        f"{_export_foam_header('dictionary', 'constant', 'turbulenceProperties')}\n\n"
        f"simulationType  RAS;\n\n"
        f"RAS\n{{\n"
        f"    RASModel    {ras_model};\n"
        f"    turbulence  {turb_on};\n"
        f"    printCoeffs on;\n"
        f"}}\n"
    )


def _export_write_control_dict(
    path: Path, *, solver: str, end_time: float, write_interval: int
) -> None:
    path.write_text(
        f"{_export_foam_header('dictionary', 'system', 'controlDict')}\n\n"
        f"application     {solver};\n\n"
        f"startFrom       startTime;\n"
        f"startTime       0;\n"
        f"stopAt          endTime;\n"
        f"endTime         {end_time:g};\n\n"
        f"deltaT          1;\n\n"
        f"writeControl    timeStep;\n"
        f"writeInterval   {write_interval};\n\n"
        f"purgeWrite      0;\n"
        f"writeFormat     ascii;\n"
        f"writePrecision  6;\n"
        f"writeCompression off;\n\n"
        f"timeFormat      general;\n"
        f"timePrecision   6;\n\n"
        f"runTimeModifiable true;\n"
    )


def _export_write_fv_schemes(path: Path, *, solver: str) -> None:
    time_scheme = "steadyState" if solver == "simpleFoam" else "Euler"
    path.write_text(
        f"{_export_foam_header('dictionary', 'system', 'fvSchemes')}\n\n"
        f"ddtSchemes\n{{\n"
        f"    default         {time_scheme};\n"
        f"}}\n\n"
        f"gradSchemes\n{{\n"
        f"    default         Gauss linear;\n"
        f"}}\n\n"
        f"divSchemes\n{{\n"
        f"    default         none;\n"
        f"    div(phi,U)      Gauss linearUpwind grad(U);\n"
        f"    div(phi,k)      Gauss linearUpwind grad(k);\n"
        f"    div(phi,epsilon) Gauss linearUpwind grad(epsilon);\n"
        f"    div(phi,omega)  Gauss linearUpwind grad(omega);\n"
        f"    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n"
        f"}}\n\n"
        f"laplacianSchemes\n{{\n"
        f"    default         Gauss linear corrected;\n"
        f"}}\n\n"
        f"interpolationSchemes\n{{\n"
        f"    default         linear;\n"
        f"}}\n\n"
        f"snGradSchemes\n{{\n"
        f"    default         corrected;\n"
        f"}}\n\n"
        f"wallDist\n{{\n"
        f"    method          meshWave;\n"
        f"}}\n"
    )


def _export_write_fv_solution(path: Path, *, solver: str) -> None:
    if solver == "simpleFoam":
        algo = (
            "SIMPLE\n{\n"
            "    nNonOrthogonalCorrectors 0;\n"
            "    consistent      yes;\n"
            "    residualControl\n    {\n"
            "        p               1e-4;\n"
            "        U               1e-4;\n"
            "        \"(k|omega|epsilon)\" 1e-4;\n"
            "    }\n}\n\n"
            "relaxationFactors\n{\n"
            "    fields { p 0.3; }\n"
            "    equations { U 0.7; k 0.7; omega 0.7; epsilon 0.7; }\n"
            "}"
        )
    else:
        algo = (
            "PIMPLE\n{\n"
            "    nOuterCorrectors 1;\n"
            "    nCorrectors      2;\n"
            "    nNonOrthogonalCorrectors 0;\n"
            "}"
        )

    path.write_text(
        f"{_export_foam_header('dictionary', 'system', 'fvSolution')}\n\n"
        f"solvers\n{{\n"
        f"    p\n    {{\n"
        f"        solver          GAMG;\n"
        f"        smoother        GaussSeidel;\n"
        f"        tolerance       1e-7;\n"
        f"        relTol          0.01;\n"
        f"    }}\n\n"
        f"    \"(U|k|omega|epsilon|nut)\"\n    {{\n"
        f"        solver          smoothSolver;\n"
        f"        smoother        symGaussSeidel;\n"
        f"        tolerance       1e-8;\n"
        f"        relTol          0.1;\n"
        f"    }}\n"
        f"}}\n\n"
        f"{algo}\n"
    )

# ---------------------------------------------------------------------------
# Optional numpy (result parser returns lists when absent)
# ---------------------------------------------------------------------------

try:
    import numpy as np  # type: ignore
    _HAS_NUMPY = True
except ImportError:
    np = None  # type: ignore
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# ResultBundle — returned by read_results()
# ---------------------------------------------------------------------------

@dataclass
class ResultBundle:
    """
    Parsed OpenFOAM field data at a single time step.

    All arrays are 1-D numpy arrays (or lists of floats/tuples when numpy is
    absent).  Vector fields (U) are shape ``(N_cells, 3)`` numpy arrays or
    ``list[tuple[float, float, float]]``.

    Parameters
    ----------
    time_value : float
        The time-step value (from the directory name).
    n_cells : int
        Number of internal cells.
    U : array-like | None
        Velocity field, shape (N, 3).
    p : array-like | None
        Kinematic pressure field, shape (N,).
    k : array-like | None
        Turbulent kinetic energy, shape (N,).  Present for k-ε / k-ω SST.
    epsilon : array-like | None
        Turbulent dissipation rate ε, shape (N,).  Present for k-ε.
    omega : array-like | None
        Specific dissipation rate ω, shape (N,).  Present for k-ω SST.
    nut : array-like | None
        Turbulent (eddy) viscosity, shape (N,).
    mesh_topology : dict | None
        Raw mesh topology dict if the polyMesh directory was also parsed.
    """

    time_value: float = 0.0
    n_cells: int = 0
    U: Any = None
    p: Any = None
    k: Any = None
    epsilon: Any = None
    omega: Any = None
    nut: Any = None
    mesh_topology: dict | None = None


# ---------------------------------------------------------------------------
# OpenFOAM ASCII field parser
# ---------------------------------------------------------------------------

# FoamFile header key-value regex
_FOAM_KV_RE = re.compile(r"^\s*(\w+)\s+(.+?)\s*;\s*$")
# Internal/boundary field line patterns
_UNIFORM_SCALAR_RE = re.compile(r"uniform\s+(\S+)")
_UNIFORM_VECTOR_RE = re.compile(r"uniform\s+\(\s*(\S+)\s+(\S+)\s+(\S+)\s*\)")


def _parse_foam_field_file(path: Path) -> dict[str, Any]:
    """
    Parse an OpenFOAM ASCII field file.

    Returns a dict with:
        foam_class  str   — e.g. "volScalarField" or "volVectorField"
        object_name str   — file object name
        dimensions  str   — dimension set string
        internal_field_type  str  — "uniform" or "nonuniform"
        internal_values     list  — floats for scalar, list-of-3-tuples for vector

    Raises
    ------
    ValueError
        If the file does not contain a recognisable FoamFile header or
        internalField block.
    """
    text = path.read_text(errors="replace")

    # Extract FoamFile header
    foam_class = ""
    object_name = ""
    in_header = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "FoamFile":
            in_header = True
            continue
        if in_header:
            m = _FOAM_KV_RE.match(stripped)
            if m:
                key, val = m.group(1), m.group(2).strip('"')
                if key == "class":
                    foam_class = val
                elif key == "object":
                    object_name = val
            if stripped == "}":
                in_header = False
                break

    if not foam_class:
        raise ValueError(f"No FoamFile header found in {path}")

    is_vector = "Vector" in foam_class

    # Extract dimensions block
    dims_match = re.search(r"dimensions\s+(\[.*?\])\s*;", text)
    dimensions = dims_match.group(1) if dims_match else ""

    # Extract internalField
    # Could be:  internalField   uniform 0;
    #            internalField   uniform (0 0 0);
    #            internalField   nonuniform List<scalar>\n<N>\n(\n...);
    #            internalField   nonuniform List<vector>\n<N>\n(\n...);

    internal_match = re.search(r"internalField\s+(.*)", text)
    if not internal_match:
        raise ValueError(f"No internalField found in {path}")

    after = internal_match.group(1).strip()
    values: list[Any] = []
    field_type = "uniform"

    if after.startswith("uniform"):
        field_type = "uniform"
        vm = _UNIFORM_VECTOR_RE.search(after)
        if vm:
            values = [(float(vm.group(1)), float(vm.group(2)), float(vm.group(3)))]
        else:
            sm = _UNIFORM_SCALAR_RE.search(after)
            if sm:
                # Strip trailing semicolons that OpenFOAM includes on the same line
                raw_val = sm.group(1).rstrip(";")
                try:
                    values = [float(raw_val)]
                except ValueError:
                    pass
    elif "nonuniform" in after:
        field_type = "nonuniform"
        # Find the data-block list: "nonuniform List<…>\nN\n(\n...\n);"
        # We must find the *outermost* matching paren pair for the data block,
        # not just the first ')' (which might be inside a vector entry).
        start_pos = internal_match.start()
        # Find the opening '(' of the data block (the one that opens the list,
        # not any '(' inside vector entries which come after it)
        paren_start = -1
        # Scan from the start of internalField for the first '(' that is at
        # the start of a line (i.e. the list delimiter, not a vector component).
        scan_start = start_pos + len("internalField")
        # The data '(' is the first one on its own line (possibly preceded only
        # by whitespace).  We find it by looking for a newline followed by '('.
        for i in range(scan_start, len(text)):
            if text[i] == "\n":
                # Peek ahead past whitespace
                j = i + 1
                while j < len(text) and text[j] in (" ", "\t"):
                    j += 1
                if j < len(text) and text[j] == "(":
                    paren_start = j
                    break
        # Fallback: just use the first '(' after the keyword
        if paren_start == -1:
            paren_start = text.find("(", scan_start)
        if paren_start == -1:
            raise ValueError(f"Cannot parse nonuniform internalField block in {path}")
        # Find the matching closing ')' using a depth counter
        depth = 0
        paren_end = -1
        for i in range(paren_start, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    paren_end = i
                    break
        if paren_end == -1:
            raise ValueError(f"Unmatched '(' in nonuniform internalField in {path}")
        data_text = text[paren_start + 1 : paren_end]
        raw_lines = [l.strip() for l in data_text.splitlines() if l.strip()]
        if is_vector:
            for line in raw_lines:
                vm = re.match(r"\(\s*(\S+)\s+(\S+)\s+(\S+)\s*\)", line)
                if vm:
                    values.append((float(vm.group(1)), float(vm.group(2)), float(vm.group(3))))
        else:
            for line in raw_lines:
                try:
                    values.append(float(line))
                except ValueError:
                    pass
    else:
        raise ValueError(f"Unknown internalField format in {path}: {after[:80]!r}")

    return {
        "foam_class": foam_class,
        "object_name": object_name,
        "dimensions": dimensions,
        "internal_field_type": field_type,
        "internal_values": values,
    }


def _to_array(values: list[Any], n_cells: int, is_vector: bool, uniform_fill: bool):
    """
    Expand a parsed internal-field value list into a full N-cell array.

    For uniform fields, if n_cells > 0 the single value is tiled to n_cells.
    If n_cells == 0 (unknown), the raw single-element list is returned as-is
    (caller can still access the value via index 0 or iteration).

    If numpy is available returns ndarray; otherwise returns a list.
    """
    if uniform_fill and len(values) == 1:
        if is_vector:
            v = values[0]
            if n_cells > 0:
                if _HAS_NUMPY:
                    return np.tile(np.array(v, dtype=float), (n_cells, 1))
                return [v] * n_cells
            else:
                # n_cells unknown — return single-entry representation
                if _HAS_NUMPY:
                    return np.array([v], dtype=float)
                return [v]
        else:
            v = values[0]
            if n_cells > 0:
                if _HAS_NUMPY:
                    return np.full(n_cells, v, dtype=float)
                return [v] * n_cells
            else:
                # n_cells unknown — return single-entry representation
                if _HAS_NUMPY:
                    return np.array([v], dtype=float)
                return [v]
    else:
        if is_vector:
            if _HAS_NUMPY:
                return np.array(values, dtype=float)
            return values
        else:
            if _HAS_NUMPY:
                return np.array(values, dtype=float)
            return values


def read_results(
    case_dir: str | Path,
    time_step: str = "latestTime",
) -> ResultBundle:
    """
    Parse OpenFOAM ASCII field files at the requested time step.

    Parameters
    ----------
    case_dir : str | Path
        Root of the OpenFOAM case directory.
    time_step : str
        Either a numeric time-step string (e.g. ``"0.5"``) or
        ``"latestTime"`` to use the highest-numbered time directory.

    Returns
    -------
    ResultBundle
        Parsed arrays for U, p, k, epsilon / omega, nut.  Fields absent from
        the time directory are ``None``.

    Raises
    ------
    FileNotFoundError
        If no suitable time directory is found.
    ValueError
        If field files contain unrecognisable format.
    """
    case_dir = Path(case_dir).resolve()

    # Discover numeric time directories (exclude "0" initial conditions unless
    # that's the only option, and "constant" / "system" / "postProcessing")
    def _is_time_dir(p: Path) -> bool:
        if not p.is_dir():
            return False
        try:
            float(p.name)
            return True
        except ValueError:
            return False

    time_dirs = sorted(
        [p for p in case_dir.iterdir() if _is_time_dir(p)],
        key=lambda p: float(p.name),
    )

    if not time_dirs:
        raise FileNotFoundError(f"No numeric time directories found in {case_dir}")

    if time_step == "latestTime":
        chosen = time_dirs[-1]
    else:
        # Exact match on name, then float match
        match = None
        for td in time_dirs:
            if td.name == time_step:
                match = td
                break
        if match is None:
            try:
                target = float(time_step)
                for td in time_dirs:
                    if math.isclose(float(td.name), target, rel_tol=1e-9):
                        match = td
                        break
            except ValueError:
                pass
        if match is None:
            raise FileNotFoundError(
                f"Time directory {time_step!r} not found in {case_dir}. "
                f"Available: {[t.name for t in time_dirs]}"
            )
        chosen = match

    time_value = float(chosen.name)
    bundle = ResultBundle(time_value=time_value)

    # Estimate n_cells from the first parseable scalar field
    # We parse each field lazily; n_cells is filled from the first success.

    field_map = {
        "U": ("U", True),
        "p": ("p", False),
        "k": ("k", False),
        "epsilon": ("epsilon", False),
        "omega": ("omega", False),
        "nut": ("nut", False),
    }

    for attr, (fname, is_vector) in field_map.items():
        fpath = chosen / fname
        if not fpath.is_file():
            continue
        try:
            parsed = _parse_foam_field_file(fpath)
        except (ValueError, OSError):
            continue

        uniform_fill = parsed["internal_field_type"] == "uniform"
        raw = parsed["internal_values"]

        # Determine n_cells: nonuniform gives exact count; uniform we keep as 1
        # until we know n_cells from another field or the mesh.
        if not uniform_fill:
            n = len(raw)
            if bundle.n_cells == 0:
                bundle.n_cells = n
        else:
            n = bundle.n_cells  # might still be 0

        arr = _to_array(raw, n, is_vector, uniform_fill)
        setattr(bundle, attr, arr)

    # Try to read n_cells from polyMesh/owner if still unknown
    if bundle.n_cells == 0:
        owner_file = case_dir / "constant" / "polyMesh" / "owner"
        if owner_file.is_file():
            try:
                topo = _parse_polymesh(case_dir / "constant" / "polyMesh")
                bundle.n_cells = topo.get("n_cells", 0)
                bundle.mesh_topology = topo
            except (ValueError, OSError):
                pass

    return bundle


# ---------------------------------------------------------------------------
# polyMesh writer
# ---------------------------------------------------------------------------

_POLYMESH_HEADER = """\
FoamFile
{{
    version     2.0;
    format      ascii;
    class       {foam_class};
    location    "constant/polyMesh";
    object      {obj};
}}
"""

# BC type → OpenFOAM patch type
_BC_PATCH_TYPE: dict[str, str] = {
    "inlet": "patch",
    "outlet": "patch",
    "wall": "wall",
    "symmetry": "symmetry",
    "empty": "empty",
    "patch": "patch",
    "cyclic": "cyclic",
    "processor": "processor",
}


def write_polymesh(
    poly_dir: Path,
    mesh,
) -> None:
    """
    Write OpenFOAM ``polyMesh/{points, faces, owner, neighbour, boundary}``
    files from a mesh object.

    Parameters
    ----------
    poly_dir : Path
        Destination directory (``constant/polyMesh``).  Created if absent.
    mesh : Mesh3D | dict
        Either a :class:`~kerf_cfd.mesh_3d.Mesh3D` instance or a dict with
        keys ``points``, ``faces``, ``owner``, ``neighbour``, ``patches``.

    Dict-of-arrays format
    ---------------------
    ::

        {
          "points":    [[x,y,z], ...],          # N_pts × 3
          "faces":     [[v0,v1,…], ...],         # N_faces, variable nv
          "owner":     [cell_id, ...],           # N_faces
          "neighbour": [cell_id, ...],           # N_internal_faces (sorted first)
          "patches":   {
              "inlet":  {"start": 0, "nFaces": 4, "type": "patch"},
              "outlet": {"start": 4, "nFaces": 4, "type": "patch"},
              ...
          }
        }

    Notes
    -----
    If a :class:`Mesh3D` is supplied, a minimal single-patch ``boundary``
    is written (all boundary faces tagged as "walls").  For production use
    supply the dict-of-arrays form with named patches.
    """
    poly_dir = Path(poly_dir)
    poly_dir.mkdir(parents=True, exist_ok=True)

    # Normalise to dict-of-arrays form
    if hasattr(mesh, "vertices"):
        # Mesh3D instance (T-101-B format)
        mesh_dict = _mesh3d_to_dict(mesh)
    else:
        mesh_dict = mesh  # already dict-of-arrays

    points = mesh_dict["points"]
    faces = mesh_dict["faces"]
    owner = mesh_dict["owner"]
    neighbour = mesh_dict.get("neighbour", [])
    patches = mesh_dict.get("patches", {})

    _write_points_file(poly_dir / "points", points)
    _write_faces_file(poly_dir / "faces", faces)
    _write_owner_file(poly_dir / "owner", owner, len(faces))
    _write_neighbour_file(poly_dir / "neighbour", neighbour)
    _write_boundary_file(poly_dir / "boundary", patches)


def _mesh3d_to_dict(mesh3d) -> dict[str, Any]:
    """Convert a Mesh3D instance to the dict-of-arrays polyMesh format."""
    points = list(mesh3d.vertices)

    # Build face list: each boundary triangle becomes one face; interior faces
    # derived from tetrahedra edges.  For a pure boundary representation we
    # use the mesh3d.faces (boundary triangles only).
    # We construct a minimal two-region topology:
    #   - All elements share internal faces
    #   - Boundary faces are the outer shell

    # Index internal faces (shared by two tets)
    from itertools import combinations
    face_owners: dict[tuple[int, ...], list[int]] = {}
    for cell_id, tet in enumerate(mesh3d.elements):
        for triple in combinations(sorted(tet), 3):
            face_owners.setdefault(triple, []).append(cell_id)

    internal_faces: list[tuple[int, ...]] = []
    internal_owner: list[int] = []
    internal_neighbour: list[int] = []
    for face_key, owners in sorted(face_owners.items()):
        if len(owners) == 2:
            o, n = sorted(owners)
            internal_faces.append(face_key)
            internal_owner.append(o)
            internal_neighbour.append(n)

    # Boundary faces
    boundary_face_list: list[tuple[int, ...]] = []
    boundary_owner_list: list[int] = []
    for face_key, owners in face_owners.items():
        if len(owners) == 1:
            boundary_face_list.append(face_key)
            boundary_owner_list.append(owners[0])

    all_faces = internal_faces + boundary_face_list
    all_owner = internal_owner + boundary_owner_list
    all_neighbour = internal_neighbour

    n_internal = len(internal_faces)
    patches = {
        "walls": {
            "start": n_internal,
            "nFaces": len(boundary_face_list),
            "type": "wall",
        }
    }

    return {
        "points": points,
        "faces": all_faces,
        "owner": all_owner,
        "neighbour": all_neighbour,
        "patches": patches,
    }


def _fmt_scalar_list(name: str, values: list, foam_class: str, obj: str) -> str:
    header = _POLYMESH_HEADER.format(foam_class=foam_class, obj=obj)
    lines = [header, "", f"{len(values)}", "("]
    lines.extend(str(v) for v in values)
    lines.append(")")
    lines.append("")
    return "\n".join(lines)


def _write_points_file(path: Path, points: list) -> None:
    header = _POLYMESH_HEADER.format(foam_class="vectorField", obj="points")
    lines = [header, "", f"{len(points)}", "("]
    for pt in points:
        lines.append(f"({pt[0]:g} {pt[1]:g} {pt[2]:g})")
    lines.append(")")
    lines.append("")
    path.write_text("\n".join(lines))


def _write_faces_file(path: Path, faces: list) -> None:
    header = _POLYMESH_HEADER.format(foam_class="faceList", obj="faces")
    lines = [header, "", f"{len(faces)}", "("]
    for face in faces:
        verts = " ".join(str(v) for v in face)
        lines.append(f"{len(face)}({verts})")
    lines.append(")")
    lines.append("")
    path.write_text("\n".join(lines))


def _write_owner_file(path: Path, owner: list[int], n_faces: int) -> None:
    header = _POLYMESH_HEADER.format(foam_class="labelList", obj="owner")
    # Prepend note about n_faces for OpenFOAM readers
    lines = [
        header,
        "",
        f"// nFaces: {n_faces}",
        f"{len(owner)}",
        "(",
    ]
    lines.extend(str(v) for v in owner)
    lines.append(")")
    lines.append("")
    path.write_text("\n".join(lines))


def _write_neighbour_file(path: Path, neighbour: list[int]) -> None:
    header = _POLYMESH_HEADER.format(foam_class="labelList", obj="neighbour")
    lines = [header, "", f"{len(neighbour)}", "("]
    lines.extend(str(v) for v in neighbour)
    lines.append(")")
    lines.append("")
    path.write_text("\n".join(lines))


def _write_boundary_file(path: Path, patches: dict[str, Any]) -> None:
    header = _POLYMESH_HEADER.format(foam_class="polyBoundaryMesh", obj="boundary")
    lines = [header, "", f"{len(patches)}", "("]
    for pname, pdata in patches.items():
        ptype = _BC_PATCH_TYPE.get(pdata.get("type", "patch"), "patch")
        start = pdata.get("start", 0)
        nf = pdata.get("nFaces", 0)
        lines.append(f"    {pname}")
        lines.append("    {")
        lines.append(f"        type            {ptype};")
        lines.append(f"        nFaces          {nf};")
        lines.append(f"        startFace       {start};")
        lines.append("    }")
    lines.append(")")
    lines.append("")
    path.write_text("\n".join(lines))


def _parse_polymesh(poly_dir: Path) -> dict[str, Any]:
    """
    Read an OpenFOAM polyMesh directory and return a topology dict.

    Returns
    -------
    dict with keys:
        n_points, n_faces, n_internal_faces, n_cells, patches (dict)
    """
    result: dict[str, Any] = {}
    owner_path = poly_dir / "owner"
    neighbour_path = poly_dir / "neighbour"
    boundary_path = poly_dir / "boundary"
    points_path = poly_dir / "points"

    if owner_path.is_file():
        text = owner_path.read_text(errors="replace")
        # Count entries between the first '(' ... ')'
        m = re.search(r"\(\s*(.*?)\s*\)", text, re.DOTALL)
        if m:
            entries = [x for x in m.group(1).split() if x.lstrip("-").isdigit()]
            result["n_faces"] = len(entries)
            if entries:
                result["n_cells"] = max(int(x) for x in entries) + 1

    if neighbour_path.is_file():
        text = neighbour_path.read_text(errors="replace")
        m = re.search(r"\(\s*(.*?)\s*\)", text, re.DOTALL)
        if m:
            entries = [x for x in m.group(1).split() if x.lstrip("-").isdigit()]
            result["n_internal_faces"] = len(entries)

    if points_path.is_file():
        text = points_path.read_text(errors="replace")
        m = re.search(r"\(\s*(.*?)\s*\)", text, re.DOTALL)
        if m:
            # Each point is "(x y z)"
            result["n_points"] = text.count("(") - 2  # rough count minus header/list parens

    if boundary_path.is_file():
        text = boundary_path.read_text(errors="replace")
        patches: dict[str, Any] = {}
        # Match patch blocks
        for pm in re.finditer(
            r"(\w+)\s*\{[^}]*type\s+(\w+)\s*;[^}]*nFaces\s+(\d+)\s*;[^}]*startFace\s+(\d+)\s*;[^}]*\}",
            text,
            re.DOTALL,
        ):
            patches[pm.group(1)] = {
                "type": pm.group(2),
                "nFaces": int(pm.group(3)),
                "start": int(pm.group(4)),
            }
        result["patches"] = patches

    return result


# ---------------------------------------------------------------------------
# BC-mapped 0/ field writers
# ---------------------------------------------------------------------------

# Maps Kerf BC key → (U_bc_type, p_bc_type, U_value_spec)
_BC_FIELD_MAP: dict[str, dict[str, str]] = {
    "inlet": {
        "U_type": "fixedValue",
        "p_type": "zeroGradient",
        "k_type": "fixedValue",
        "epsilon_type": "fixedValue",
        "omega_type": "fixedValue",
    },
    "outlet": {
        "U_type": "zeroGradient",
        "p_type": "fixedValue",
        "k_type": "zeroGradient",
        "epsilon_type": "zeroGradient",
        "omega_type": "zeroGradient",
    },
    "wall": {
        "U_type": "noSlip",
        "p_type": "zeroGradient",
        "k_type": "kqRWallFunction",
        "epsilon_type": "epsilonWallFunction",
        "omega_type": "omegaWallFunction",
    },
    "symmetry": {
        "U_type": "symmetry",
        "p_type": "symmetry",
        "k_type": "symmetry",
        "epsilon_type": "symmetry",
        "omega_type": "symmetry",
    },
    "empty": {
        "U_type": "empty",
        "p_type": "empty",
        "k_type": "empty",
        "epsilon_type": "empty",
        "omega_type": "empty",
    },
}


def _build_bc_block(
    bcs: dict[str, Any],
    field: str,
    type_key: str,
    default_type: str,
    default_value: str | None = None,
    *,
    inlet_velocity: tuple[float, float, float] | None = None,
    k_inlet: float = 0.001,
    epsilon_inlet: float = 0.001,
    omega_inlet: float = 1.0,
    p_outlet: float = 0.0,
) -> str:
    """Build the boundaryField block for a single OpenFOAM field file."""
    lines: list[str] = ["boundaryField", "{"]
    for patch_name, bc_def in bcs.items():
        bc_type = bc_def if isinstance(bc_def, str) else bc_def.get("type", "wall")
        mapping = _BC_FIELD_MAP.get(bc_type, _BC_FIELD_MAP["wall"])
        otype = mapping.get(type_key, default_type)

        lines.append(f"    {patch_name}")
        lines.append("    {")
        lines.append(f"        type            {otype};")

        # Field-specific value entries
        if field == "U" and bc_type == "inlet":
            v = inlet_velocity or (1.0, 0.0, 0.0)
            lines.append(f"        value           uniform ({v[0]:g} {v[1]:g} {v[2]:g});")
        elif field == "p" and bc_type == "outlet":
            lines.append(f"        value           uniform {p_outlet:g};")
        elif field == "k" and bc_type in ("inlet", "wall"):
            if bc_type == "inlet":
                lines.append(f"        value           uniform {k_inlet:g};")
            else:
                lines.append(f"        value           uniform {k_inlet:g};")
        elif field == "epsilon" and bc_type in ("inlet", "wall"):
            lines.append(f"        value           uniform {epsilon_inlet:g};")
        elif field == "omega" and bc_type in ("inlet", "wall"):
            lines.append(f"        value           uniform {omega_inlet:g};")
        elif field in ("k", "epsilon", "omega") and otype not in ("zeroGradient", "empty", "symmetry"):
            lines.append(f"        value           uniform 0;")

        lines.append("    }")

    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# write_case() — high-level case generator with BC mapping
# ---------------------------------------------------------------------------

def write_case(
    case_dir: str | Path,
    mesh=None,
    bcs: dict[str, Any] | None = None,
    solver_config: dict[str, Any] | None = None,
) -> Path:
    """
    Write a complete OpenFOAM case directory.

    This is the primary public API for the OpenFOAM bridge.  It combines:
    - :func:`~openfoam_case_template.build_case` for system/ + constant/ + 0/
    - :func:`write_polymesh` if a mesh object is supplied
    - BC-mapped 0/ field files if ``bcs`` is supplied

    Parameters
    ----------
    case_dir : str | Path
        Destination directory (created if absent).
    mesh : Mesh3D | dict | None
        Optional mesh.  If supplied, written to ``constant/polyMesh/``.
        See :func:`write_polymesh` for formats.
    bcs : dict | None
        Boundary-condition mapping:
        ``{"inlet": "inlet", "outlet": "outlet", "walls": "wall", ...}``.
        Keys are OpenFOAM patch names; values are Kerf BC type strings.
        When None the default (inlet/outlet/walls) from ``build_case`` applies.
    solver_config : dict | None
        Solver configuration keys (all optional):

        ``solver``              str  — "simpleFoam" (default) or "pisoFoam" / "pimpleFoam"
        ``turbulence_model``    str  — "laminar" (default), "kEpsilon", "kOmegaSST"
        ``nu``                  float — kinematic viscosity (m²/s, default 1e-5)
        ``u_inlet``             float — inlet U magnitude (m/s, default 1.0)
        ``inlet_direction``     list  — [ux, uy, uz] unit vector (default [1,0,0])
        ``end_time``            float — end time / iterations (default 500)
        ``delta_t``             float — time step (default 1.0)
        ``write_interval``      float — write interval (default 100)
        ``k_inlet``             float — k at inlet (default 0.001)
        ``omega_inlet``         float — ω at inlet (default 1.0)
        ``epsilon_inlet``       float — ε at inlet (default 0.001)
        ``geometry``            dict  — blockMeshDict geometry overrides

    Returns
    -------
    Path
        Resolved path to the case root.
    """
    from kerf_cfd.openfoam_case_template import build_case

    cfg = solver_config or {}
    solver = cfg.get("solver", "simpleFoam")
    # pisoFoam is a valid OF solver but our template uses pimpleFoam; map it
    if solver == "pisoFoam":
        solver = "pimpleFoam"

    turbulence_model = cfg.get("turbulence_model", "laminar")
    nu = float(cfg.get("nu", 1e-5))
    u_inlet = float(cfg.get("u_inlet", 1.0))
    end_time = float(cfg.get("end_time", 500.0))
    delta_t = float(cfg.get("delta_t", 1.0))
    write_interval = float(cfg.get("write_interval", 100.0))
    k_inlet = float(cfg.get("k_inlet", 0.001))
    omega_inlet = float(cfg.get("omega_inlet", 1.0))
    epsilon_inlet = float(cfg.get("epsilon_inlet", 0.001))
    geometry = cfg.get("geometry")
    inlet_direction = cfg.get("inlet_direction", [1.0, 0.0, 0.0])
    inlet_velocity = tuple(float(x) * u_inlet for x in inlet_direction)

    # 1. Write canonical case tree via build_case
    root = build_case(
        case_dir,
        solver=solver,
        turbulence_model=turbulence_model,
        nu=nu,
        u_inlet=u_inlet,
        end_time=end_time,
        delta_t=delta_t,
        write_interval=write_interval,
        geometry=geometry or {},
        k_inlet=k_inlet,
        omega_inlet=omega_inlet,
        epsilon_inlet=epsilon_inlet,
    )

    # 2. Write polyMesh from supplied mesh (if any)
    if mesh is not None:
        write_polymesh(root / "constant" / "polyMesh", mesh)

    # 3. Rewrite 0/ fields with BC-mapped boundary conditions
    if bcs is not None:
        _rewrite_bc_fields(
            root / "0",
            bcs=bcs,
            turbulence_model=turbulence_model,
            inlet_velocity=inlet_velocity,
            k_inlet=k_inlet,
            epsilon_inlet=epsilon_inlet,
            omega_inlet=omega_inlet,
        )

    return root


def _foam_field_header(foam_class: str, location: str, obj: str) -> str:
    return (
        "FoamFile\n"
        "{\n"
        "    version     2.0;\n"
        "    format      ascii;\n"
        f"    class       {foam_class};\n"
        f"    location    \"{location}\";\n"
        f"    object      {obj};\n"
        "}"
    )


def _rewrite_bc_fields(
    zero_dir: Path,
    *,
    bcs: dict[str, Any],
    turbulence_model: str,
    inlet_velocity: tuple[float, float, float],
    k_inlet: float,
    epsilon_inlet: float,
    omega_inlet: float,
) -> None:
    """Rewrite 0/ field files with BC-mapped boundary conditions."""
    u_mag = math.sqrt(sum(x * x for x in inlet_velocity))

    # --- U ---
    u_bc_block = _build_bc_block(
        bcs, "U", "U_type", "zeroGradient",
        inlet_velocity=inlet_velocity,
        k_inlet=k_inlet, epsilon_inlet=epsilon_inlet, omega_inlet=omega_inlet,
    )
    (zero_dir / "U").write_text(
        f"{_foam_field_header('volVectorField', '0', 'U')}\n\n"
        f"dimensions      [0 1 -1 0 0 0 0];\n\n"
        f"internalField   uniform (0 0 0);\n\n"
        f"{u_bc_block}\n"
    )

    # --- p ---
    p_bc_block = _build_bc_block(
        bcs, "p", "p_type", "zeroGradient",
        inlet_velocity=inlet_velocity,
        k_inlet=k_inlet, epsilon_inlet=epsilon_inlet, omega_inlet=omega_inlet,
    )
    (zero_dir / "p").write_text(
        f"{_foam_field_header('volScalarField', '0', 'p')}\n\n"
        f"dimensions      [0 2 -2 0 0 0 0];\n\n"
        f"internalField   uniform 0;\n\n"
        f"{p_bc_block}\n"
    )

    # --- nut ---
    nut_lines: list[str] = ["boundaryField", "{"]
    for patch_name, bc_def in bcs.items():
        bc_type = bc_def if isinstance(bc_def, str) else bc_def.get("type", "wall")
        if bc_type == "wall":
            nut_lines.extend([f"    {patch_name}", "    {",
                               "        type            nutkWallFunction;",
                               "        value           uniform 0;", "    }"])
        else:
            nut_lines.extend([f"    {patch_name}", "    {",
                               "        type            calculated;",
                               "        value           uniform 0;", "    }"])
    nut_lines.append("}")
    (zero_dir / "nut").write_text(
        f"{_foam_field_header('volScalarField', '0', 'nut')}\n\n"
        f"dimensions      [0 2 -1 0 0 0 0];\n\n"
        f"internalField   uniform 0;\n\n"
        + "\n".join(nut_lines) + "\n"
    )

    # --- k ---
    if turbulence_model in ("kEpsilon", "kOmegaSST"):
        k_bc_block = _build_bc_block(
            bcs, "k", "k_type", "zeroGradient",
            inlet_velocity=inlet_velocity,
            k_inlet=k_inlet, epsilon_inlet=epsilon_inlet, omega_inlet=omega_inlet,
        )
        (zero_dir / "k").write_text(
            f"{_foam_field_header('volScalarField', '0', 'k')}\n\n"
            f"dimensions      [0 2 -2 0 0 0 0];\n\n"
            f"internalField   uniform {k_inlet:g};\n\n"
            f"{k_bc_block}\n"
        )

    # --- epsilon ---
    if turbulence_model == "kEpsilon":
        eps_bc_block = _build_bc_block(
            bcs, "epsilon", "epsilon_type", "zeroGradient",
            inlet_velocity=inlet_velocity,
            k_inlet=k_inlet, epsilon_inlet=epsilon_inlet, omega_inlet=omega_inlet,
        )
        (zero_dir / "epsilon").write_text(
            f"{_foam_field_header('volScalarField', '0', 'epsilon')}\n\n"
            f"dimensions      [0 2 -3 0 0 0 0];\n\n"
            f"internalField   uniform {epsilon_inlet:g};\n\n"
            f"{eps_bc_block}\n"
        )

    # --- omega ---
    if turbulence_model == "kOmegaSST":
        om_bc_block = _build_bc_block(
            bcs, "omega", "omega_type", "zeroGradient",
            inlet_velocity=inlet_velocity,
            k_inlet=k_inlet, epsilon_inlet=epsilon_inlet, omega_inlet=omega_inlet,
        )
        (zero_dir / "omega").write_text(
            f"{_foam_field_header('volScalarField', '0', 'omega')}\n\n"
            f"dimensions      [0 0 -1 0 0 0 0];\n\n"
            f"internalField   uniform {omega_inlet:g};\n\n"
            f"{om_bc_block}\n"
        )


# ---------------------------------------------------------------------------
# Binary availability (lazy-cached)
# ---------------------------------------------------------------------------

_BINARY_CACHE: dict[str, bool] = {}


def _binary_available(name: str) -> bool:
    if name not in _BINARY_CACHE:
        _BINARY_CACHE[name] = shutil.which(name) is not None
    return _BINARY_CACHE[name]


ENGINE_PENDING_WARNING = (
    "Engine pending — OpenFOAM ({binary}) not installed or not in PATH."
)


# ---------------------------------------------------------------------------
# Analytic oracle — Hagen-Poiseuille (Darcy-Weisbach laminar)
# ---------------------------------------------------------------------------

def pipe_friction_factor_laminar(Re: float) -> float:
    """
    Darcy-Weisbach friction factor for laminar pipe flow.

        f = 64 / Re

    Valid for Re < 2300 (laminar regime).

    Parameters
    ----------
    Re : float
        Reynolds number (must be > 0).

    Returns
    -------
    float
        Darcy-Weisbach friction factor.

    Raises
    ------
    ValueError
        If Re <= 0.

    Reference
    ---------
    White F.M., Fluid Mechanics, 8th ed., §6.4, eq. (6.13).
    """
    if Re <= 0:
        raise ValueError(f"Reynolds number must be positive; got {Re}")
    return 64.0 / Re


def pipe_pressure_drop_hagen_poiseuille(
    u_mean: float,
    length: float,
    diameter: float,
    nu: float,
    rho: float = 1.0,
) -> dict[str, float]:
    """
    Compute Hagen-Poiseuille pressure drop for laminar pipe flow.

        ΔP = f * (L/D) * (ρ U²) / 2   with  f = 64/Re,  Re = U*D/ν

    Parameters
    ----------
    u_mean : float
        Mean cross-section velocity (m/s).
    length : float
        Pipe length (m).
    diameter : float
        Pipe (hydraulic) diameter (m).
    nu : float
        Kinematic viscosity (m²/s).
    rho : float
        Fluid density (kg/m³), default 1.

    Returns
    -------
    dict with keys:
        Re              Reynolds number
        f               Darcy friction factor (64/Re)
        delta_p         pressure drop (Pa)
        dp_per_length   pressure gradient (Pa/m)

    Reference
    ---------
    White F.M., Fluid Mechanics, 8th ed., §8.2, eq. (8.12).
    """
    Re = u_mean * diameter / nu
    f = pipe_friction_factor_laminar(Re)
    dynamic_pressure = 0.5 * rho * u_mean ** 2
    delta_p = f * (length / diameter) * dynamic_pressure
    return {
        "Re": Re,
        "f": f,
        "delta_p": delta_p,
        "dp_per_length": delta_p / length,
    }


# ---------------------------------------------------------------------------
# blockMesh runner
# ---------------------------------------------------------------------------

def run_blockmesh(case_dir: str | Path, timeout: int = 120) -> dict[str, Any]:
    """
    Run ``blockMesh`` in *case_dir*.

    Returns
    -------
    dict with keys:
        status      "ok" | "pending" | "error"
        warnings    list[str]
        errors      list[str]
        stdout      str  (raw blockMesh output)
        elapsed     float  (wall seconds)
    """
    case_dir = Path(case_dir).resolve()

    if not _binary_available("blockMesh"):
        return {
            "status": "pending",
            "warnings": [ENGINE_PENDING_WARNING.format(binary="blockMesh")],
            "errors": [],
            "stdout": "",
            "elapsed": 0.0,
        }

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            ["blockMesh", "-case", str(case_dir)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "warnings": [],
            "errors": [f"blockMesh timed out after {timeout}s"],
            "stdout": "",
            "elapsed": time.monotonic() - t0,
        }
    elapsed = time.monotonic() - t0

    if result.returncode != 0:
        return {
            "status": "error",
            "warnings": [],
            "errors": [
                f"blockMesh exited with code {result.returncode}",
                result.stderr.strip(),
            ],
            "stdout": result.stdout,
            "elapsed": elapsed,
        }

    return {
        "status": "ok",
        "warnings": [],
        "errors": [],
        "stdout": result.stdout,
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# Solver runner
# ---------------------------------------------------------------------------

def run_solver(
    case_dir: str | Path,
    solver: str = "simpleFoam",
    *,
    timeout: int = 600,
    log_file: str | None = None,
) -> dict[str, Any]:
    """
    Run *solver* on *case_dir*.

    The solver is invoked as::

        <solver> -case <case_dir>

    stdout is captured and optionally written to *log_file* inside *case_dir*.

    Returns
    -------
    dict with keys:
        status      "ok" | "pending" | "error"
        warnings    list[str]
        errors      list[str]
        stdout      str
        returncode  int | None
        elapsed     float  (wall seconds)
    """
    case_dir = Path(case_dir).resolve()

    if not _binary_available(solver):
        return {
            "status": "pending",
            "warnings": [ENGINE_PENDING_WARNING.format(binary=solver)],
            "errors": [],
            "stdout": "",
            "returncode": None,
            "elapsed": 0.0,
        }

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            [solver, "-case", str(case_dir)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "warnings": [],
            "errors": [f"{solver} timed out after {timeout}s"],
            "stdout": "",
            "returncode": None,
            "elapsed": time.monotonic() - t0,
        }
    elapsed = time.monotonic() - t0

    if log_file is not None:
        (case_dir / log_file).write_text(result.stdout)

    if result.returncode != 0:
        return {
            "status": "error",
            "warnings": [],
            "errors": [
                f"{solver} exited with code {result.returncode}",
                result.stderr.strip(),
            ],
            "stdout": result.stdout,
            "returncode": result.returncode,
            "elapsed": elapsed,
        }

    return {
        "status": "ok",
        "warnings": [],
        "errors": [],
        "stdout": result.stdout,
        "returncode": result.returncode,
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# postProcessing/ parser
# ---------------------------------------------------------------------------

# Match lines like:  0.001   (1.23e-4 -2.3e-5 0)   # forces
_VECTOR_RE = re.compile(
    r"^\s*(\S+)"                  # time/iteration
    r"\s+\("                      # opening paren
    r"\s*(\S+)\s+(\S+)\s+(\S+)"  # x y z
    r"\s*\)"                      # closing paren
)
# Match lines like:   0.001   1.23e-4             # scalar field
_SCALAR_RE = re.compile(r"^\s*(\S+)\s+(\S+)\s*$")


def _safe_float(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, OverflowError):
        return None


def parse_forces_dat(dat_path: str | Path) -> list[dict[str, Any]]:
    """
    Parse an OpenFOAM ``postProcessing/forces/<time>/force.dat`` file.

    Each non-comment line has the form::

        <time>  (<Fx> <Fy> <Fz>)  (<Mx> <My> <Mz>)

    Returns a list of dicts:
        time, Fx, Fy, Fz, Mx, My, Mz
    """
    records: list[dict[str, Any]] = []
    dat_path = Path(dat_path)
    if not dat_path.exists():
        return records

    for raw_line in dat_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Two vector groups: forces then moments
        # Format: time  (Fx Fy Fz)  (Mx My Mz)
        m = re.match(
            r"^\s*(\S+)"
            r"\s+\(\s*(\S+)\s+(\S+)\s+(\S+)\s*\)"
            r"\s+\(\s*(\S+)\s+(\S+)\s+(\S+)\s*\)",
            raw_line,
        )
        if m:
            t, fx, fy, fz, mx, my, mz = m.groups()
            row: dict[str, Any] = {
                "time": _safe_float(t),
                "Fx": _safe_float(fx),
                "Fy": _safe_float(fy),
                "Fz": _safe_float(fz),
                "Mx": _safe_float(mx),
                "My": _safe_float(my),
                "Mz": _safe_float(mz),
            }
            records.append(row)
    return records


def parse_scalar_dat(dat_path: str | Path) -> list[dict[str, Any]]:
    """
    Parse a two-column (time, value) postProcessing data file.

    Returns a list of dicts with keys ``time`` and ``value``.
    """
    records: list[dict[str, Any]] = []
    dat_path = Path(dat_path)
    if not dat_path.exists():
        return records

    for raw_line in dat_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SCALAR_RE.match(line)
        if m:
            t_str, v_str = m.groups()
            records.append({
                "time": _safe_float(t_str),
                "value": _safe_float(v_str),
            })
    return records


def parse_postprocessing(case_dir: str | Path) -> dict[str, Any]:
    """
    Walk ``<case_dir>/postProcessing/`` and collect all result files.

    Returns
    -------
    dict with keys:
        status          "ok" | "empty"
        function_names  list[str]   — names of function-object subdirectories found
        data            dict        — keyed by "<function>/<time>/<filename>"
                                      value is list of parsed row dicts

    Each row dict has at minimum a ``time`` key; forces files add
    Fx/Fy/Fz/Mx/My/Mz; scalar files add ``value``.
    """
    case_dir = Path(case_dir).resolve()
    pp_dir = case_dir / "postProcessing"

    if not pp_dir.is_dir():
        return {
            "status": "empty",
            "function_names": [],
            "data": {},
        }

    function_names: list[str] = []
    data: dict[str, Any] = {}

    for fn_dir in sorted(pp_dir.iterdir()):
        if not fn_dir.is_dir():
            continue
        function_names.append(fn_dir.name)

        for time_dir in sorted(fn_dir.iterdir()):
            if not time_dir.is_dir():
                continue

            for dat_file in sorted(time_dir.iterdir()):
                if not dat_file.is_file():
                    continue
                key = f"{fn_dir.name}/{time_dir.name}/{dat_file.name}"

                name_lower = dat_file.name.lower()
                if "force" in name_lower:
                    data[key] = parse_forces_dat(dat_file)
                else:
                    data[key] = parse_scalar_dat(dat_file)

    return {
        "status": "ok" if data else "empty",
        "function_names": function_names,
        "data": data,
    }


# ---------------------------------------------------------------------------
# High-level convenience
# ---------------------------------------------------------------------------

def run_case(
    case_dir: str | Path,
    solver: str = "simpleFoam",
    *,
    run_blockmesh_first: bool = True,
    solver_timeout: int = 600,
    log_file: str | None = "log.simpleFoam",
) -> dict[str, Any]:
    """
    Run a complete OpenFOAM case: optionally blockMesh, then the solver,
    then parse postProcessing/.

    Returns
    -------
    dict with keys:
        status          "ok" | "pending" | "error"
        blockmesh       dict  (result of run_blockmesh, or None)
        solver          dict  (result of run_solver)
        postprocessing  dict  (result of parse_postprocessing, or None)
        warnings        list[str]
        errors          list[str]
    """
    case_dir = Path(case_dir).resolve()
    warnings: list[str] = []
    errors: list[str] = []

    bm_result: dict[str, Any] | None = None
    if run_blockmesh_first:
        bm_result = run_blockmesh(case_dir)
        if bm_result["status"] == "pending":
            return {
                "status": "pending",
                "blockmesh": bm_result,
                "solver": None,
                "postprocessing": None,
                "warnings": bm_result["warnings"],
                "errors": [],
            }
        if bm_result["status"] == "error":
            return {
                "status": "error",
                "blockmesh": bm_result,
                "solver": None,
                "postprocessing": None,
                "warnings": [],
                "errors": bm_result["errors"],
            }

    solver_result = run_solver(case_dir, solver, timeout=solver_timeout,
                               log_file=log_file)
    warnings.extend(solver_result.get("warnings", []))
    errors.extend(solver_result.get("errors", []))

    if solver_result["status"] == "pending":
        return {
            "status": "pending",
            "blockmesh": bm_result,
            "solver": solver_result,
            "postprocessing": None,
            "warnings": warnings,
            "errors": errors,
        }

    if solver_result["status"] == "error":
        return {
            "status": "error",
            "blockmesh": bm_result,
            "solver": solver_result,
            "postprocessing": None,
            "warnings": warnings,
            "errors": errors,
        }

    pp_result = parse_postprocessing(case_dir)

    return {
        "status": "ok",
        "blockmesh": bm_result,
        "solver": solver_result,
        "postprocessing": pp_result,
        "warnings": warnings,
        "errors": errors,
    }
