"""
CalculiX utilities for static and modal analysis.
Writes .inp file, runs ccx, parses .dat (eigenvalues) and .frd (mode shapes).
"""

import logging
import math
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_CALCULIX_AVAILABLE: Optional[bool] = None


def _ccx_available() -> bool:
    global _CALCULIX_AVAILABLE
    if _CALCULIX_AVAILABLE is None:
        _CALCULIX_AVAILABLE = shutil.which("ccx") is not None
    return _CALCULIX_AVAILABLE


ENGINE_PENDING_WARNING = "Engine pending — CalculiX (ccx) not installed or not in PATH."


def run_static_analysis(mesh_path: str, material_props: dict,
                        boundary_conditions: list, loads: list,
                        analysis_type: str = "linear_static") -> dict:
    if not _ccx_available():
        return {
            "status": "pending",
            "warnings": [ENGINE_PENDING_WARNING],
            "errors": [],
        }
    if analysis_type == "linear_static":
        return _run_calculix_static(mesh_path, material_props, boundary_conditions, loads)
    elif analysis_type == "modal":
        return _run_calculix_modal(mesh_path, material_props, boundary_conditions)
    elif analysis_type == "thermal":
        return _run_calculix_thermal(mesh_path, material_props, boundary_conditions, loads)
    elif analysis_type == "nonlinear_plastic":
        return _run_calculix_nonlinear_plastic(mesh_path, material_props, boundary_conditions, loads)
    else:
        raise ValueError(f"unknown analysis_type: {analysis_type}")


# ---------------------------------------------------------------------------
# INP deck writers
# ---------------------------------------------------------------------------

def _write_nodes_and_elements(inp_lines: list, nodes, elements: list,
                               elem_type_map: dict) -> None:
    """Append *NODE and *ELEMENT blocks to inp_lines in-place."""
    inp_lines.append("*NODE")
    for i, pt in enumerate(nodes):
        inp_lines.append(f"{i + 1},{pt[0]:.10g},{pt[1]:.10g},{pt[2]:.10g}")

    # Group elements by type.
    by_type: dict = {}
    for (eid, etype, enodes) in elements:
        by_type.setdefault(etype, []).append((eid, enodes))

    for etype, egroup in by_type.items():
        ccx_type = elem_type_map.get(etype, "C3D4")
        inp_lines.append(f"*ELEMENT,TYPE={ccx_type},ELSET=Eall")
        for eid, enodes in egroup:
            inp_lines.append(f"{eid}," + ",".join(str(n) for n in enodes))


def _write_material(inp_lines: list, E: float, nu: float, rho: float) -> None:
    inp_lines.extend([
        "**",
        "*MATERIAL,NAME=MAT",
        "*ELASTIC",
        f"{E:.6g},{nu:.6g}",
        "*DENSITY",
        f"{rho:.6g}",
        "*SOLID SECTION,ELSET=Eall,MATERIAL=MAT",
        "",
    ])


def _write_fixed_bc(inp_lines: list, fixed_node_sets: list) -> None:
    """Write *BOUNDARY for each pre-defined node-set name."""
    for nset in fixed_node_sets:
        inp_lines.append("*BOUNDARY")
        inp_lines.append(f"{nset},1,3,0.0")


def _build_face_node_sets(nodes, elements: list, face_tags: list) -> dict:
    """
    CalculiX doesn't have Gmsh physical-group awareness. We approximate
    boundary-condition faces by partitioning boundary (surface-exposed) nodes
    by their spatial position.  For simple geometries the canonical Gmsh face
    ordering maps to: tag 1 → x=xmin face, tag 2 → x=xmax, etc.  We sort faces
    by their centroid coordinate and assign tags 1…N in that order.

    Returns {tag_int → set_name} and emits *NSET blocks into inp_lines.
    """
    import numpy as np

    pts = np.array(nodes)
    bounds = {
        "xmin": pts[:, 0].min(), "xmax": pts[:, 0].max(),
        "ymin": pts[:, 1].min(), "ymax": pts[:, 1].max(),
        "zmin": pts[:, 2].min(), "zmax": pts[:, 2].max(),
    }
    tol = max(
        bounds["xmax"] - bounds["xmin"],
        bounds["ymax"] - bounds["ymin"],
        bounds["zmax"] - bounds["zmin"],
    ) * 0.02  # 2% of bounding box

    # The 6 axis-aligned face planes, ordered by typical Gmsh tag assignment.
    planes = [
        ("xmin", 0, bounds["xmin"]),
        ("xmax", 0, bounds["xmax"]),
        ("ymin", 1, bounds["ymin"]),
        ("ymax", 1, bounds["ymax"]),
        ("zmin", 2, bounds["zmin"]),
        ("zmax", 2, bounds["zmax"]),
    ]

    tag_to_set = {}
    for tag in face_tags:
        idx = tag - 1  # convert 1-based tag to 0-based plane index
        if idx < 0 or idx >= len(planes):
            continue
        label, axis, coord = planes[idx]
        node_ids = [
            i + 1 for i, pt in enumerate(nodes)
            if abs(pt[axis] - coord) <= tol
        ]
        if not node_ids:
            continue
        set_name = f"BC{tag}"
        tag_to_set[tag] = (set_name, node_ids)

    return tag_to_set


def _msh_to_inp_static(mesh_path: str, material_props: dict,
                        boundary_conditions: list, loads: list) -> str:
    import meshio

    msh = meshio.read(mesh_path)
    nodes = msh.points

    elements = []
    elem_id = 1
    elem_type_map = {"tetra": "C3D4", "triangle": "CPS3"}
    for cell_block in msh.cells:
        if cell_block.type in elem_type_map:
            for row in cell_block.data:
                elem_nodes = [int(n) + 1 for n in row]
                elements.append((elem_id, cell_block.type, elem_nodes))
                elem_id += 1

    E = material_props["E"]
    nu = material_props["nu"]
    rho = material_props.get("rho", 7850.0)

    inp = []
    inp.append("*HEADING")
    inp.append("CalculiX static analysis")
    _write_nodes_and_elements(inp, nodes, elements, elem_type_map)
    _write_material(inp, E, nu, rho)

    # Collect all face_tags that appear in BCs.
    all_tags = []
    for bc in boundary_conditions:
        all_tags.extend(bc.get("face_tags", []))

    face_sets = _build_face_node_sets(nodes, elements, all_tags)
    for tag, (set_name, node_ids) in face_sets.items():
        inp.append(f"*NSET,NSET={set_name}")
        inp.append(",".join(str(n) for n in node_ids))

    inp.extend(["**", "*STEP,NAME=Static", "*STATIC"])
    inp.append("**")

    for bc in boundary_conditions:
        if bc["type"] == "fixed":
            for tag in bc.get("face_tags", []):
                if tag in face_sets:
                    set_name = face_sets[tag][0]
                    inp.append("*BOUNDARY")
                    inp.append(f"{set_name},1,3,0.0")

    for load in (loads or []):
        if load["type"] in ("pressure", "force"):
            inp.append("*CLOAD")
            node_id = 1  # fallback: apply to first node
            inp.append(f"{node_id},3,{load['value']}")

    inp.extend([
        "*NODE FILE",
        "U",
        "*EL FILE",
        "S",
        "*END STEP",
    ])
    return "\n".join(inp)


def _msh_to_inp_modal(mesh_path: str, material_props: dict,
                       boundary_conditions: list, num_modes: int = 10) -> str:
    import meshio

    msh = meshio.read(mesh_path)
    nodes = msh.points

    elements = []
    elem_id = 1
    elem_type_map = {"tetra": "C3D4", "triangle": "CPS3"}
    for cell_block in msh.cells:
        if cell_block.type in elem_type_map:
            for row in cell_block.data:
                elem_nodes = [int(n) + 1 for n in row]
                elements.append((elem_id, cell_block.type, elem_nodes))
                elem_id += 1

    E = material_props["E"]
    nu = material_props["nu"]
    rho = material_props.get("rho", 7850.0)

    inp = []
    inp.append("*HEADING")
    inp.append("CalculiX modal analysis")
    _write_nodes_and_elements(inp, nodes, elements, elem_type_map)
    _write_material(inp, E, nu, rho)

    all_tags = []
    for bc in boundary_conditions:
        all_tags.extend(bc.get("face_tags", []))

    face_sets = _build_face_node_sets(nodes, elements, all_tags)
    for tag, (set_name, node_ids) in face_sets.items():
        inp.append(f"*NSET,NSET={set_name}")
        inp.append(",".join(str(n) for n in node_ids))

    # Boundary conditions must go BEFORE the *STEP block in CalculiX modal.
    for bc in boundary_conditions:
        if bc["type"] == "fixed":
            for tag in bc.get("face_tags", []):
                if tag in face_sets:
                    set_name = face_sets[tag][0]
                    inp.append("*BOUNDARY")
                    inp.append(f"{set_name},1,3,0.0")

    inp.extend([
        "**",
        f"*STEP,NAME=Modal",
        f"*FREQUENCY,NMODES={num_modes}",
        "**",
        "*NODE FILE",
        "U",
        "*END STEP",
    ])
    return "\n".join(inp)


# ---------------------------------------------------------------------------
# .dat parser (eigenvalues for modal, displacements/stresses for static)
# ---------------------------------------------------------------------------

def _parse_dat_eigenvalues(content: str) -> list:
    """
    Extract eigenvalues (ω² in rad²/s²) from the CalculiX .dat file.

    CalculiX writes an eigenvalue table with a header like:
        E I G E N V A L U E S
         MODE   EIGENVALUE     ...
    followed by rows:  <mode_num>  <eigenvalue>  ...

    Returns list of frequencies in Hz: f = sqrt(eigenvalue) / (2π).
    """
    frequencies = []
    # Find the eigenvalue table — header is spaced out in CalculiX output.
    block_match = re.search(
        r"E\s*I\s*G\s*E\s*N\s*V\s*A\s*L\s*U\s*E\s*S(.*?)(?=\n\s*\n|\Z)",
        content, re.DOTALL | re.IGNORECASE
    )
    if not block_match:
        return frequencies

    for line in block_match.group(1).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            try:
                eigenvalue = float(parts[1])
                if eigenvalue > 0:
                    freq_hz = math.sqrt(eigenvalue) / (2.0 * math.pi)
                    frequencies.append(freq_hz)
            except ValueError:
                pass

    return frequencies


def _parse_dat_static(dat_path: Path) -> dict:
    if not dat_path.exists():
        return {"error": f"CalculiX .dat file not found: {dat_path}"}

    content = dat_path.read_text(errors="replace")
    displacements = []
    stresses = []

    disp_match = re.search(
        r"D\s*I\s*S\s*P\s*L\s*A\s*C\s*E\s*M\s*E\s*N\s*T\s*S(.*?)(?=\n\s*\n|\Z)",
        content, re.DOTALL | re.IGNORECASE
    )
    if disp_match:
        for line in disp_match.group(1).splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].isdigit():
                try:
                    ux, uy, uz = float(parts[1]), float(parts[2]), float(parts[3])
                    displacements.append([ux, uy, uz])
                except ValueError:
                    pass

    stress_match = re.search(
        r"S\s*T\s*R\s*E\s*S\s*S\s*E\s*S(.*?)(?=\n\s*\n|\Z)",
        content, re.DOTALL | re.IGNORECASE
    )
    if stress_match:
        for line in stress_match.group(1).splitlines():
            parts = line.split()
            if len(parts) >= 7 and parts[0].isdigit():
                try:
                    sx, sy, sz = float(parts[1]), float(parts[2]), float(parts[3])
                    txy, tyz, txz = float(parts[4]), float(parts[5]), float(parts[6])
                    vm = math.sqrt(0.5 * (
                        (sx - sy) ** 2 + (sy - sz) ** 2 + (sz - sx) ** 2
                        + 6 * (txy ** 2 + tyz ** 2 + txz ** 2)
                    ))
                    stresses.append({"von_mises": vm, "sx": sx, "sy": sy, "sz": sz})
                except ValueError:
                    pass

    return {"displacements": displacements, "stresses": stresses}


# ---------------------------------------------------------------------------
# .frd parser (mode shapes for modal analysis)
# ---------------------------------------------------------------------------

def _parse_frd_mode_shapes(frd_path: Path, num_modes: int) -> list:
    """
    Parse CalculiX .frd binary/ASCII results file for mode-shape displacements.

    The .frd file uses a fixed-format ASCII layout.  Each result block begins:
        -4  <set_name>  <n_dof>  <step>
    followed by component headers:
        -5  U1  ...
        -5  U2  ...
        -5  U3  ...
    and then node data lines:
        -1  <node_id>  <U1>  <U2>  <U3>
    followed by:
        -3   (end of block)

    For modal analysis CalculiX writes one block per mode.  We collect the
    first `num_modes` blocks that contain displacement (U) results.

    Returns list[list[{ux, uy, uz}]] — outer list is per mode, inner is per node.
    """
    if not frd_path.exists():
        logger.warning("CalculiX .frd not found: %s", frd_path)
        return []

    mode_shapes = []
    current_nodes = []
    in_displacement_block = False
    component_cols: list = []  # ordered component names in this block

    try:
        for raw_line in frd_path.read_text(errors="replace").splitlines():
            line = raw_line.rstrip()
            if len(line) < 3:
                continue

            record_type = line[:3].strip()

            if record_type == "-4":
                # Start of a new result block.
                # Check if it's a displacement (U) block.
                in_displacement_block = "DISP" in line.upper() or " U " in line.upper()
                component_cols = []
                current_nodes = []

            elif record_type == "-5" and in_displacement_block:
                # Component header: -5  U1  ...
                parts = line.split()
                if len(parts) >= 2:
                    component_cols.append(parts[1].upper())

            elif record_type == "-1" and in_displacement_block:
                # Node data line: -1  <id>  <v1>  <v2>  ...
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        vals = [float(v) for v in parts[1:]]
                        ux = vals[0] if len(vals) > 0 else 0.0
                        uy = vals[1] if len(vals) > 1 else 0.0
                        uz = vals[2] if len(vals) > 2 else 0.0
                        current_nodes.append({"ux": ux, "uy": uy, "uz": uz})
                    except ValueError:
                        pass

            elif record_type == "-3" and in_displacement_block:
                # End of block — save this mode shape.
                if current_nodes:
                    mode_shapes.append(current_nodes)
                current_nodes = []
                in_displacement_block = False
                if len(mode_shapes) >= num_modes:
                    break

    except Exception as e:
        logger.warning("frd parse error: %s", e)

    return mode_shapes


# ---------------------------------------------------------------------------
# Analysis runners
# ---------------------------------------------------------------------------

def _run_ccx(tmpdir: Path, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ccx", "analysis"],
        cwd=tmpdir,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_calculix_static(mesh_path: str, material_props: dict,
                          boundary_conditions: list, loads: list) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        inp_path = tmpdir / "analysis.inp"
        inp_path.write_text(_msh_to_inp_static(mesh_path, material_props,
                                                boundary_conditions, loads))

        proc = _run_ccx(tmpdir)
        if proc.returncode != 0:
            raise RuntimeError(f"CalculiX failed (code {proc.returncode}): {proc.stderr[:1000]}")

        dat_path = tmpdir / "analysis.dat"
        parsed = _parse_dat_static(dat_path)
        if "error" in parsed:
            raise RuntimeError(parsed["error"])

        displacements = parsed.get("displacements", [])
        stresses = parsed.get("stresses", [])

        max_disp = max(
            (math.sqrt(d[0]**2 + d[1]**2 + d[2]**2) for d in displacements),
            default=0.0,
        )
        max_stress = max((s["von_mises"] for s in stresses), default=0.0)
        yield_strength = material_props.get("yield_strength", 250e6)
        fos = yield_strength / max_stress if max_stress > 0 else float("inf")

        node_displacements = [
            {"ux": d[0], "uy": d[1], "uz": d[2],
             "mag": math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)}
            for d in displacements
        ]

        return {
            "max_vonmises_stress": max_stress,
            "max_displacement": max_disp,
            "fos": fos,
            "node_displacements": node_displacements,
            "displacements": [math.sqrt(d[0]**2 + d[1]**2 + d[2]**2) for d in displacements],
            "stresses": [s["von_mises"] for s in stresses],
            "warnings": [],
            "errors": [],
        }


def _run_calculix_modal(mesh_path: str, material_props: dict,
                         boundary_conditions: list) -> dict:
    num_modes = material_props.get("num_modes", 10)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        inp_path = tmpdir / "analysis.inp"
        inp_path.write_text(_msh_to_inp_modal(mesh_path, material_props,
                                               boundary_conditions, num_modes))

        proc = _run_ccx(tmpdir)
        if proc.returncode != 0:
            raise RuntimeError(f"CalculiX failed (code {proc.returncode}): {proc.stderr[:1000]}")

        dat_path = tmpdir / "analysis.dat"
        dat_content = dat_path.read_text(errors="replace") if dat_path.exists() else ""
        frequencies = _parse_dat_eigenvalues(dat_content)

        frd_path = tmpdir / "analysis.frd"
        mode_shapes = _parse_frd_mode_shapes(frd_path, num_modes)

        return {
            "frequencies": frequencies,
            "mode_shapes": mode_shapes,
            "warnings": [],
            "errors": [],
        }


def _run_calculix_thermal(mesh_path: str, material_props: dict,
                           boundary_conditions: list, loads: list) -> dict:
    """
    Run a CalculiX *HEAT TRANSFER analysis (steady-state or transient).

    The mesh is read via meshio and converted to DC-type thermal elements.
    BCs may specify prescribed temperatures (*BOUNDARY), convection (*FILM),
    or heat-flux (*CFLUX).

    Returns
    -------
    dict with keys: temperatures, heat_fluxes, warnings, errors.
    temperatures : list of {"node": int, "T": float}
    heat_fluxes  : list of {"elem": int, "HFL": float}
    """
    import meshio

    msh = meshio.read(mesh_path)
    nodes = msh.points

    elements = []
    elem_id = 1
    # Thermal element type map: DC prefix = diffusion/conduction
    thermal_elem_type_map = {"tetra": "DC3D4", "hexahedron": "DC3D8", "triangle": "DC2D3"}
    for cell_block in msh.cells:
        if cell_block.type in thermal_elem_type_map:
            for row in cell_block.data:
                elem_nodes = [int(n) + 1 for n in row]
                elements.append((elem_id, cell_block.type, elem_nodes))
                elem_id += 1

    analysis_type = material_props.get("analysis_type", "steady-state")
    dt = material_props.get("dt", 1.0)
    t_end = material_props.get("t_end", 1.0)
    initial_temp = material_props.get("initial_temp", 0.0)

    inp_text = generate_thermal_input(
        mesh={"nodes": nodes, "elements": elements},
        materials=material_props,
        boundary_conditions=boundary_conditions,
        analysis_type=analysis_type,
        dt=dt,
        t_end=t_end,
        initial_temp=initial_temp,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        inp_path = tmpdir / "analysis.inp"
        inp_path.write_text(inp_text)

        proc = _run_ccx(tmpdir)
        if proc.returncode != 0:
            raise RuntimeError(
                f"CalculiX thermal failed (code {proc.returncode}): {proc.stderr[:1000]}"
            )

        dat_path = tmpdir / "analysis.dat"
        parsed = _parse_dat_thermal(dat_path)
        if "error" in parsed:
            raise RuntimeError(parsed["error"])

    return {
        "temperatures": parsed.get("temperatures", []),
        "heat_fluxes": parsed.get("heat_fluxes", []),
        "warnings": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Thermal element type map (module-level constant for reuse)
# ---------------------------------------------------------------------------

#: Maps meshio cell-block type strings to CalculiX thermal (DC-prefix) element types.
#: Reference: CalculiX User Manual §6.2 — DC3D4 = 4-node tet, DC3D8 = 8-node hex.
_THERMAL_ELEM_MAP: dict = {
    "tetra": "DC3D4",
    "tetra10": "DC3D10",
    "hexahedron": "DC3D8",
    "hexahedron20": "DC3D20",
    "triangle": "DC2D3",
    "quad": "DC2D4",
}


def generate_thermal_input(
    mesh: dict,
    materials: dict,
    boundary_conditions: list,
    analysis_type: str = "steady-state",
    *,
    dt: float = 1.0,
    t_end: float = 1.0,
    initial_temp: float = 0.0,
) -> str:
    """
    Generate a CalculiX *HEAT TRANSFER INP deck for steady-state or transient
    thermal analysis including conduction, prescribed temperatures, convection
    (*FILM), and heat-flux (*CFLUX) boundary conditions.

    Follows CalculiX User Manual §6.9.30 (*HEAT TRANSFER step definition).

    Parameters
    ----------
    mesh : dict
        ``{"nodes": list_of_[x,y,z], "elements": list_of_(eid, etype_str, [node_ids])}``
    materials : dict
        Must contain ``"conductivity"`` (W/(m·K)).  For transient analysis also
        needs ``"density"`` (kg/m³) and ``"specific_heat"`` (J/(kg·K)).
        Optional ``"name"`` (default ``"THMAT"``).
    boundary_conditions : list of dicts
        Each dict has at least a ``"type"`` key:

        * ``{"type": "temperature", "node_ids": [...], "value": T}``
          → *BOUNDARY (prescribed nodal temperature, DOF 11)
        * ``{"type": "film", "node_ids": [...], "film_coeff": h, "sink_temp": T_inf}``
          → *FILM (convective BC, surface film condition)
        * ``{"type": "heat_flux", "node_ids": [...], "value": q}``
          → *CFLUX (concentrated nodal heat flux, DOF 11)
    analysis_type : str
        ``"steady-state"`` or ``"transient"``
    dt : float
        Initial/fixed time increment (transient only).
    t_end : float
        End time for transient analysis.
    initial_temp : float
        Initial temperature applied to all nodes via *INITIAL CONDITIONS.

    Returns
    -------
    str
        Complete CalculiX INP deck ready to write to ``analysis.inp``.
    """
    nodes = mesh["nodes"]
    elements = mesh["elements"]
    mat_name = materials.get("name", "THMAT")
    conductivity = float(materials.get("conductivity", 50.0))
    density = float(materials.get("density", 7850.0))
    specific_heat = float(materials.get("specific_heat", 500.0))

    inp: list = []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    inp.append("*HEADING")
    inp.append("Kerf thermal analysis")

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    inp.append("*NODE, NSET=Nall")
    for i, pt in enumerate(nodes):
        inp.append(f"{i + 1},{pt[0]:.10g},{pt[1]:.10g},{pt[2]:.10g}")

    # ------------------------------------------------------------------
    # Elements (thermal DC-type)
    # ------------------------------------------------------------------
    by_type: dict = {}
    for (eid, etype, enodes) in elements:
        by_type.setdefault(etype, []).append((eid, enodes))

    for etype, egroup in by_type.items():
        ccx_type = _THERMAL_ELEM_MAP.get(etype, "DC3D4")
        inp.append(f"*ELEMENT, TYPE={ccx_type}, ELSET=Eall")
        for eid, enodes in egroup:
            inp.append(f"{eid}," + ",".join(str(n) for n in enodes))

    # ------------------------------------------------------------------
    # Material
    # ------------------------------------------------------------------
    inp.append("**")
    inp.append(f"*MATERIAL, NAME={mat_name}")
    inp.append("*CONDUCTIVITY")
    inp.append(f"{conductivity:.6g}")
    inp.append("*DENSITY")
    inp.append(f"{density:.6g}")
    if analysis_type == "transient":
        inp.append("*SPECIFIC HEAT")
        inp.append(f"{specific_heat:.6g}")

    # Solid section assigns material to the element set
    inp.append(f"*SOLID SECTION, ELSET=Eall, MATERIAL={mat_name}")
    inp.append("")

    # ------------------------------------------------------------------
    # Initial conditions
    # ------------------------------------------------------------------
    inp.append("*INITIAL CONDITIONS, TYPE=TEMPERATURE")
    inp.append(f"Nall,{initial_temp:.6g}")

    # ------------------------------------------------------------------
    # Step definition
    # ------------------------------------------------------------------
    inp.append("**")
    inp.append("*STEP")
    if analysis_type == "transient":
        inp.append(f"*HEAT TRANSFER, {dt:.6g}, {t_end:.6g}")
    else:
        inp.append("*HEAT TRANSFER, STEADY STATE")
    inp.append("**")

    # ------------------------------------------------------------------
    # Boundary conditions inside the step
    # ------------------------------------------------------------------
    for bc in (boundary_conditions or []):
        bc_type = bc.get("type", "")

        if bc_type == "temperature":
            # Prescribed nodal temperature — DOF 11 in CalculiX thermal
            node_ids = bc.get("node_ids", [])
            value = float(bc.get("value", 0.0))
            if node_ids:
                nset_name = f"NtempBC{boundary_conditions.index(bc) + 1}"
                inp.append(f"*NSET, NSET={nset_name}")
                # Chunk to 16 per line per CalculiX convention
                for chunk_start in range(0, len(node_ids), 16):
                    chunk = node_ids[chunk_start:chunk_start + 16]
                    inp.append(",".join(str(n) for n in chunk))
                inp.append("*BOUNDARY")
                inp.append(f"{nset_name},11,11,{value:.6g}")

        elif bc_type == "film":
            # Convective boundary: *FILM
            # Syntax: node_id, FxNy, film_coeff, sink_temp
            # FxNy = film on face x of node set; we use individual nodes here.
            film_coeff = float(bc.get("film_coeff", 10.0))
            sink_temp = float(bc.get("sink_temp", 20.0))
            node_ids = bc.get("node_ids", [])
            for nid in node_ids:
                inp.append("*FILM")
                inp.append(f"{nid},F1,{film_coeff:.6g},{sink_temp:.6g}")

        elif bc_type == "heat_flux":
            # Concentrated heat flux: *CFLUX — DOF 11 = thermal DOF
            node_ids = bc.get("node_ids", [])
            value = float(bc.get("value", 0.0))
            for nid in node_ids:
                inp.append("*CFLUX")
                inp.append(f"{nid},11,{value:.6g}")

    # ------------------------------------------------------------------
    # Output requests
    # ------------------------------------------------------------------
    inp.append("*NODE FILE, NSET=Nall")
    inp.append("NT")
    inp.append("*EL FILE, ELSET=Eall")
    inp.append("HFL")
    inp.append("*END STEP")

    return "\n".join(inp)


def _parse_dat_thermal(dat_path: "Path") -> dict:
    """
    Parse CalculiX .dat output from a *HEAT TRANSFER run.

    Extracts:
      temperatures : list of {"node": int, "T": float}
      heat_fluxes  : list of {"elem": int, "HFL": float}

    The .dat file from a thermal run typically contains:
        TEMPERATURES
         <node>  <T>
    and optionally:
        HEAT FLUX
         <elem>  <HFLx>  <HFLy>  <HFLz>
    """
    if not dat_path.exists():
        return {"error": f"CalculiX .dat file not found: {dat_path}"}

    content = dat_path.read_text(errors="replace")
    temperatures = []
    heat_fluxes = []

    # Temperature block
    temp_match = re.search(
        r"T\s*E\s*M\s*P\s*E\s*R\s*A\s*T\s*U\s*R\s*E\s*S(.*?)(?=\n\s*\n|\Z)",
        content, re.DOTALL | re.IGNORECASE
    )
    if temp_match:
        for line in temp_match.group(1).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                try:
                    temperatures.append({"node": int(parts[0]), "T": float(parts[1])})
                except ValueError:
                    pass

    # Heat-flux block (HFL)
    hfl_match = re.search(
        r"H\s*E\s*A\s*T\s+F\s*L\s*U\s*X(.*?)(?=\n\s*\n|\Z)",
        content, re.DOTALL | re.IGNORECASE
    )
    if hfl_match:
        for line in hfl_match.group(1).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                try:
                    # Magnitude from vector components if available
                    if len(parts) >= 4:
                        hx, hy, hz = float(parts[1]), float(parts[2]), float(parts[3])
                        hfl_mag = math.sqrt(hx ** 2 + hy ** 2 + hz ** 2)
                    else:
                        hfl_mag = float(parts[1])
                    heat_fluxes.append({"elem": int(parts[0]), "HFL": hfl_mag})
                except ValueError:
                    pass

    return {"temperatures": temperatures, "heat_fluxes": heat_fluxes}


# ---------------------------------------------------------------------------
# Nonlinear plastic (J2 isotropic-hardening) deck writer
# ---------------------------------------------------------------------------

def _write_plastic(inp_lines: list, sigma_y0: float, hardening_pairs: list) -> None:
    """
    Append *PLASTIC block for J2 isotropic-hardening.

    hardening_pairs : list of (stress, plastic_strain) tuples that define the
                      hardening curve.  A bilinear curve is constructed from
                      sigma_y0 and the hardening modulus H.
    """
    inp_lines.extend([
        "*PLASTIC",
    ])
    for stress, eps_p in hardening_pairs:
        inp_lines.append(f"{stress:.6g},{eps_p:.6g}")


def build_nonlinear_plastic_inp(
    nodes: list,
    elements: list,
    material_props: dict,
    boundary_conditions: list,
    loads: list,
    *,
    n_increments: int = 10,
    time_period: float = 1.0,
    elem_type_map: dict | None = None,
) -> str:
    """
    Build a CalculiX *NLGEOM nonlinear-static INP deck for J2 isotropic-hardening
    plasticity.

    Parameters
    ----------
    nodes           : list of [x, y, z] node coordinates
    elements        : list of (eid, etype_str, [node_ids]) tuples
    material_props  : dict with keys E, nu, rho, sigma_y0, H, [yield_strength]
    boundary_conditions, loads : same schema as the linear-static path
    n_increments    : number of load increments for *STATIC
    time_period     : total pseudo-time (always 1.0 for proportional loading)
    elem_type_map   : override element type mapping (default tetra→C3D4)

    Returns
    -------
    INP deck as a string ready to be written to analysis.inp.
    """
    if elem_type_map is None:
        elem_type_map = {"tetra": "C3D4", "triangle": "CPS3"}

    E = material_props["E"]
    nu = material_props["nu"]
    rho = material_props.get("rho", 7850.0)
    sigma_y0 = material_props.get("sigma_y0", 250e6)
    H = material_props.get("H", 0.0)          # hardening modulus [Pa]

    # Bilinear hardening curve: (σ_y0, 0), (σ_y0 + H * ε_ref, ε_ref)
    # ε_ref = 0.1 gives a reasonably extended curve.  CalculiX interpolates linearly.
    eps_ref = 0.1
    hardening_pairs = [
        (sigma_y0, 0.0),
        (sigma_y0 + H * eps_ref, eps_ref),
    ]

    inp = []
    inp.append("*HEADING")
    inp.append("CalculiX nonlinear-plastic analysis (J2 isotropic hardening)")

    _write_nodes_and_elements(inp, nodes, elements, elem_type_map)

    # Material with plasticity
    inp.extend([
        "**",
        "*MATERIAL,NAME=MAT",
        "*ELASTIC",
        f"{E:.6g},{nu:.6g}",
        "*DENSITY",
        f"{rho:.6g}",
    ])
    _write_plastic(inp, sigma_y0, hardening_pairs)
    inp.extend([
        "*SOLID SECTION,ELSET=Eall,MATERIAL=MAT",
        "",
    ])

    # Build face node-sets from all referenced face tags in BCs
    all_tags = []
    for bc in boundary_conditions:
        all_tags.extend(bc.get("face_tags", []))
    face_sets = _build_face_node_sets(nodes, elements, all_tags)
    for tag, (set_name, node_ids) in face_sets.items():
        inp.append(f"*NSET,NSET={set_name}")
        inp.append(",".join(str(n) for n in node_ids))

    # NLGEOM step — nonlinear geometry + material nonlinearity
    dt_init = time_period / n_increments
    inp.extend([
        "**",
        "*STEP,NAME=NonlinearPlastic,NLGEOM",
        f"*STATIC,{dt_init:.6g},{time_period:.6g}",
        "**",
    ])

    # Boundary conditions (fixed DOFs)
    for bc in boundary_conditions:
        if bc["type"] == "fixed":
            for tag in bc.get("face_tags", []):
                if tag in face_sets:
                    set_name = face_sets[tag][0]
                    inp.append("*BOUNDARY")
                    inp.append(f"{set_name},1,3,0.0")

    # Loads
    for load in (loads or []):
        if load["type"] in ("pressure", "force"):
            inp.append("*CLOAD")
            node_id = 1
            inp.append(f"{node_id},3,{load['value']}")

    inp.extend([
        "*NODE FILE",
        "U",
        "*EL FILE",
        "S,PEEQ",
        "*END STEP",
    ])
    return "\n".join(inp)


def parse_nonlinear_plastic_dat(dat_path: Path) -> dict:
    """
    Parse CalculiX .dat output for a nonlinear-plastic run.

    Returns a dict with:
        displacements   : list of [ux, uy, uz] per node
        stresses        : list of {"von_mises", "sx", "sy", "sz", "peeq"} per element
    (PEEQ = equivalent plastic strain, written when *EL FILE includes PEEQ)
    """
    if not dat_path.exists():
        return {"error": f"CalculiX .dat file not found: {dat_path}"}

    content = dat_path.read_text(errors="replace")

    # Reuse the static parser for displacement / stress blocks
    base = _parse_dat_static(dat_path)
    displacements = base.get("displacements", [])
    stresses = base.get("stresses", [])

    # Parse PEEQ (equivalent plastic strain) if present in the .dat
    peeq_values: list[float] = []
    peeq_match = re.search(
        r"EQUIVALENT\s+PLASTIC\s+STRAIN(.*?)(?=\n\s*\n|\Z)",
        content, re.DOTALL | re.IGNORECASE
    )
    if peeq_match:
        for line in peeq_match.group(1).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                try:
                    peeq_values.append(float(parts[1]))
                except ValueError:
                    pass

    # Enrich stress dicts with PEEQ where available
    for i, s in enumerate(stresses):
        s["peeq"] = peeq_values[i] if i < len(peeq_values) else 0.0

    return {"displacements": displacements, "stresses": stresses}


def _run_calculix_nonlinear_plastic(mesh_path: str, material_props: dict,
                                    boundary_conditions: list, loads: list) -> dict:
    """
    Run a J2 isotropic-hardening nonlinear-plastic analysis via CalculiX.

    Returns the same schema as _run_calculix_static plus a `peeq_max` field
    (maximum equivalent plastic strain across all integration points).
    """
    import meshio

    msh = meshio.read(mesh_path)
    nodes = msh.points

    elements = []
    elem_id = 1
    elem_type_map = {"tetra": "C3D4", "triangle": "CPS3"}
    for cell_block in msh.cells:
        if cell_block.type in elem_type_map:
            for row in cell_block.data:
                elem_nodes = [int(n) + 1 for n in row]
                elements.append((elem_id, cell_block.type, elem_nodes))
                elem_id += 1

    inp_text = build_nonlinear_plastic_inp(
        nodes, elements, material_props, boundary_conditions, loads,
        elem_type_map=elem_type_map,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        inp_path = tmpdir / "analysis.inp"
        inp_path.write_text(inp_text)

        proc = _run_ccx(tmpdir)
        if proc.returncode != 0:
            raise RuntimeError(f"CalculiX failed (code {proc.returncode}): {proc.stderr[:1000]}")

        dat_path = tmpdir / "analysis.dat"
        parsed = parse_nonlinear_plastic_dat(dat_path)
        if "error" in parsed:
            raise RuntimeError(parsed["error"])

    displacements = parsed.get("displacements", [])
    stresses = parsed.get("stresses", [])

    max_disp = max(
        (math.sqrt(d[0]**2 + d[1]**2 + d[2]**2) for d in displacements),
        default=0.0,
    )
    max_stress = max((s["von_mises"] for s in stresses), default=0.0)
    peeq_max = max((s.get("peeq", 0.0) for s in stresses), default=0.0)
    yield_strength = material_props.get("yield_strength", material_props.get("sigma_y0", 250e6))
    fos = yield_strength / max_stress if max_stress > 0 else float("inf")

    node_displacements = [
        {"ux": d[0], "uy": d[1], "uz": d[2],
         "mag": math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)}
        for d in displacements
    ]

    return {
        "max_vonmises_stress": max_stress,
        "max_displacement": max_disp,
        "peeq_max": peeq_max,
        "fos": fos,
        "node_displacements": node_displacements,
        "displacements": [math.sqrt(d[0]**2 + d[1]**2 + d[2]**2) for d in displacements],
        "stresses": [s["von_mises"] for s in stresses],
        "warnings": [],
        "errors": [],
    }
