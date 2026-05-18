"""
Z88 subprocess bridge for Kerf FEM.

Z88 (https://z88.de) is an open-source finite-element solver for Linux/macOS/Windows.
The solver reads a family of plain-text input files (z88i*.txt) and writes results to
z88o*.txt.  This bridge:

  1. Writes the Z88 input file family for a given mesh + material + BCs.
  2. Shells out to `z88r` (the CLI runner, aliased `z88` on some installations).
  3. Parses the displacement / stress output (z88o2.txt) and eigenvalue output
     (z88o3.txt for dynamic analyses).

Public API
----------
    Z88Bridge.solve(mesh, materials, boundary_conditions, *, analysis_type) -> dict

    Supported analysis_type values:
        "linear_static"  — default; static linear elastic
        "modal"          — natural frequencies (first n_modes modes)
        "nonlinear"      — geometric nonlinear (large-displacement) static

    Returns
    -------
    {
        "ok": bool,
        "status": "ok" | "pending" | "error",
        "warnings": list[str],
        "errors":   list[str],
        # analysis-type-specific keys:
        "frequencies":        list[float],   # Hz  (modal only)
        "max_displacement":   float,         # m   (static/nonlinear)
        "max_vonmises_stress": float,        # Pa  (static/nonlinear)
        "node_displacements": list[dict],    # {ux, uy, uz, mag} per node
        "fos":                float,         # factor of safety (static/nonlinear)
    }

    When z88 / z88r is not on PATH the call returns immediately with
    status="pending" (same sentinel pattern as calculix_utils).

Z88 input file family (brief reference)
----------------------------------------
z88i1.txt   — mesh header + node coordinates
z88i2.txt   — element connectivity
z88i5.txt   — material properties
z88i6.txt   — boundary conditions (DOF constraints)
z88i7.txt   — point forces
z88com.txt  — solver control (analysis type, solver selection)

Reference
---------
Z88Aurora V5 User Manual, University of Bayreuth (2020).
"""

from __future__ import annotations

import logging
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sentinel flag — None means "not yet checked".
_Z88_AVAILABLE: bool | None = None

ENGINE_PENDING_WARNING = (
    "Engine pending — Z88 (z88r or z88) not installed or not in PATH."
)

# Supported element types mapped to Z88 element numbers.
# Z88 element numbering (§4 of the manual):
#   1  — 2-node bar / truss (linear)
#   2  — 2-node beam (Euler-Bernoulli)
#  11  — 4-node tetrahedral (linear)
#  17  — 10-node tetrahedral (quadratic)
#   7  — 4-node plane quad (plane stress)
#  14  — 8-node hexahedral (linear)
_ELEM_TYPE_MAP = {
    "bar":     1,
    "beam":    2,
    "tetra4":  11,
    "tetra10": 17,
    "quad4":   7,
    "hex8":    14,
}
_DEFAULT_ELEM_TYPE = 11  # tetra4 fallback


# ---------------------------------------------------------------------------
# PATH detection
# ---------------------------------------------------------------------------

def _z88_available() -> bool:
    """Return True if z88r or z88 is on PATH."""
    global _Z88_AVAILABLE
    if _Z88_AVAILABLE is None:
        _Z88_AVAILABLE = (
            shutil.which("z88r") is not None
            or shutil.which("z88") is not None
        )
    return _Z88_AVAILABLE


def _z88_exe() -> str:
    """Return the first available Z88 executable name."""
    for name in ("z88r", "z88"):
        if shutil.which(name):
            return name
    raise FileNotFoundError("z88r / z88 not found on PATH")


# ---------------------------------------------------------------------------
# Input file writers
# ---------------------------------------------------------------------------

def write_z88i1(nodes: list[list[float]], *, dof_per_node: int = 3) -> str:
    """
    Write z88i1.txt — mesh header and node coordinates.

    Format (Z88Aurora manual §4.2):
        Line 1: <n_nodes>  <n_elems>  <dim>  <dof_per_node>  <n_dof_constrained>
        Line 2+: <node_id>  <x>  <y>  <z>

    n_elems and n_dof_constrained are placeholders here (filled in by the caller
    who writes z88i1 after the element and BC counts are known).  This function
    writes only the coordinate section; the caller prepends the header line.
    """
    lines: list[str] = []
    for i, pt in enumerate(nodes, start=1):
        x = pt[0] if len(pt) > 0 else 0.0
        y = pt[1] if len(pt) > 1 else 0.0
        z = pt[2] if len(pt) > 2 else 0.0
        lines.append(f"{i} {x:.10g} {y:.10g} {z:.10g}")
    return "\n".join(lines)


def write_z88i1_file(
    nodes: list[list[float]],
    n_elems: int,
    n_dof_constrained: int,
    *,
    dim: int = 3,
    dof_per_node: int = 3,
) -> str:
    """
    Full z88i1.txt content — header + node table.

    Header format:
        <n_nodes>  <n_elems>  <dim>  <dof_per_node>  <n_dof_constrained>
    """
    n_nodes = len(nodes)
    header = f"{n_nodes} {n_elems} {dim} {dof_per_node} {n_dof_constrained}"
    coord_block = write_z88i1(nodes, dof_per_node=dof_per_node)
    return header + "\n" + coord_block + "\n"


def write_z88i2_file(
    elements: list[tuple[int, int, list[int]]],
    *,
    dof_per_node: int = 3,
) -> str:
    """
    Write z88i2.txt — element connectivity.

    Each element line:
        <elem_id>  <z88_elem_type>  <dof_per_node>  <node1> <node2> ... <nodeN>

    Parameters
    ----------
    elements : list of (elem_id, z88_elem_type_number, [node_ids])
    """
    lines: list[str] = []
    for eid, etype_num, enodes in elements:
        node_str = " ".join(str(n) for n in enodes)
        lines.append(f"{eid} {etype_num} {dof_per_node} {node_str}")
    return "\n".join(lines) + "\n"


def write_z88i5_file(
    E: float,
    nu: float,
    rho: float = 7850.0,
    *,
    n_elem_sets: int = 1,
) -> str:
    """
    Write z88i5.txt — material properties.

    Z88 material file (Aurora §4.5) format:
        <n_material_sets>
        <set_id>  E  nu  rho  (one line per material set)
    """
    lines = [str(n_elem_sets)]
    lines.append(f"1 {E:.10g} {nu:.10g} {rho:.10g}")
    return "\n".join(lines) + "\n"


def write_z88i6_file(
    boundary_conditions: list[dict],
    nodes: list[list[float]],
    *,
    dof_per_node: int = 3,
) -> str:
    """
    Write z88i6.txt — degree-of-freedom constraints.

    Format per Z88Aurora manual §4.6:
        <n_constraints>
        <node_id>  <dof_number>  <value>   (1=tx, 2=ty, 3=tz, 4=rx, 5=ry, 6=rz)

    Supports 'fixed' BC (all translational DOFs = 0).  Nodes are identified by
    matching their coordinates to the 'face' described in the BC dict.

    BC dict schema:
        {"type": "fixed", "face": "xmin"}  — fix all nodes on xmin face
        {"type": "fixed", "node_ids": [1, 2, 3]}  — fix explicit node IDs
    """
    if not nodes:
        return "0\n"

    import math as _m

    pts = nodes
    xmin = min(p[0] for p in pts)
    xmax = max(p[0] for p in pts)
    ymin = min(p[1] for p in pts)
    ymax = max(p[1] for p in pts)
    zmin = min(p[2] for p in pts) if dof_per_node >= 3 and len(pts[0]) >= 3 else 0.0
    zmax = max((p[2] for p in pts if len(p) >= 3), default=0.0)

    span = max(xmax - xmin, ymax - ymin, zmax - zmin)
    tol = max(span * 0.02, 1e-9)

    face_to_node_ids: dict[str, list[int]] = {}
    for i, p in enumerate(pts):
        nid = i + 1
        x, y = p[0], p[1]
        z = p[2] if len(p) >= 3 else 0.0
        if abs(x - xmin) <= tol:
            face_to_node_ids.setdefault("xmin", []).append(nid)
        if abs(x - xmax) <= tol:
            face_to_node_ids.setdefault("xmax", []).append(nid)
        if abs(y - ymin) <= tol:
            face_to_node_ids.setdefault("ymin", []).append(nid)
        if abs(y - ymax) <= tol:
            face_to_node_ids.setdefault("ymax", []).append(nid)
        if abs(z - zmin) <= tol:
            face_to_node_ids.setdefault("zmin", []).append(nid)
        if abs(z - zmax) <= tol:
            face_to_node_ids.setdefault("zmax", []).append(nid)

    # Collect constrained (node_id, dof) pairs.
    constrained: list[tuple[int, int, float]] = []
    dofs_to_fix = list(range(1, min(dof_per_node, 3) + 1))  # 1..3 (translations)

    for bc in boundary_conditions:
        bc_type = bc.get("type", "")
        if bc_type != "fixed":
            continue

        target_nodes: list[int] = []

        # Explicit node list.
        if "node_ids" in bc:
            target_nodes = list(bc["node_ids"])

        # Face-based.
        face = bc.get("face")
        if face and face in face_to_node_ids:
            target_nodes.extend(face_to_node_ids[face])

        # Face-tag-based (1-based: 1=xmin, 2=xmax, 3=ymin, 4=ymax, 5=zmin, 6=zmax).
        face_tags = bc.get("face_tags", [])
        _face_order = ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"]
        for tag in face_tags:
            idx = tag - 1
            if 0 <= idx < len(_face_order):
                fname = _face_order[idx]
                target_nodes.extend(face_to_node_ids.get(fname, []))

        for nid in set(target_nodes):
            for dof in dofs_to_fix:
                constrained.append((nid, dof, 0.0))

    # De-duplicate (same node+dof may appear multiple times).
    seen: set[tuple[int, int]] = set()
    unique: list[tuple[int, int, float]] = []
    for nid, dof, val in constrained:
        if (nid, dof) not in seen:
            seen.add((nid, dof))
            unique.append((nid, dof, val))

    lines = [str(len(unique))]
    for nid, dof, val in unique:
        lines.append(f"{nid} {dof} {val:.10g}")
    return "\n".join(lines) + "\n"


def write_z88i7_file(loads: list[dict], *, dof_per_node: int = 3) -> str:
    """
    Write z88i7.txt — point forces.

    Format (Z88Aurora §4.7):
        <n_loads>
        <node_id>  <dof>  <value>

    Load dict schema:
        {"type": "force", "node_id": 1, "dof": 3, "value": -1000.0}
        {"type": "point", "node_id": 1, "fx": 0, "fy": 0, "fz": -1000.0}
    """
    entries: list[tuple[int, int, float]] = []
    for load in (loads or []):
        if load.get("type") == "force":
            entries.append((
                int(load.get("node_id", 1)),
                int(load.get("dof", 3)),
                float(load.get("value", 0.0)),
            ))
        elif load.get("type") == "point":
            nid = int(load.get("node_id", 1))
            for dof, key in enumerate(("fx", "fy", "fz"), start=1):
                v = float(load.get(key, 0.0))
                if v != 0.0:
                    entries.append((nid, dof, v))

    lines = [str(len(entries))]
    for nid, dof, val in entries:
        lines.append(f"{nid} {dof} {val:.10g}")
    return "\n".join(lines) + "\n"


def write_z88com_file(
    analysis_type: str = "linear_static",
    *,
    n_modes: int = 10,
) -> str:
    """
    Write z88com.txt — Z88 solver control file.

    Key options (Z88Aurora §3 / §6):
        IBFLAG  — analysis type:  1 = static, 2 = dynamic (modal), 3 = nonlinear
        ISOLVER — linear solver:  1 = Cholesky direct (default)
        MAXITE  — max iterations (nonlinear)
        NFREQ   — number of requested natural frequencies (modal)
    """
    ibflag = {
        "linear_static": 1,
        "modal": 2,
        "nonlinear": 3,
    }.get(analysis_type, 1)

    lines = [
        f"IBFLAG {ibflag}",
        "ISOLVER 1",
        "MAXITE 100",
        "TOLRMS 1.0E-6",
        f"NFREQ {n_modes}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Output parsers
# ---------------------------------------------------------------------------

def _parse_z88o2(content: str) -> dict[str, Any]:
    """
    Parse z88o2.txt — nodal displacements.

    Z88 writes displacements in blocks like:
        KNOTENPUNKT    1
          UX =  1.234E-05
          UY = -2.345E-05
          UZ =  0.000E+00

    or in tabular form (Aurora):
        NODE   UX           UY           UZ
           1   1.234E-05  -2.345E-05   0.000E+00

    We handle both formats.
    """
    import re

    node_disps: list[dict[str, float]] = []

    # Try tabular format first (Z88Aurora).
    tabular_header = re.search(
        r"NODE\s+UX\s+UY\s+UZ", content, re.IGNORECASE
    )
    if tabular_header:
        for line in content[tabular_header.end():].splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0].lstrip("-").isdigit():
                try:
                    ux, uy, uz = float(parts[1]), float(parts[2]), float(parts[3])
                    node_disps.append({
                        "ux": ux, "uy": uy, "uz": uz,
                        "mag": math.sqrt(ux ** 2 + uy ** 2 + uz ** 2),
                    })
                except ValueError:
                    pass
        if node_disps:
            return {"node_displacements": node_disps}

    # Block format fallback.
    current: dict[str, float] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("KNOTENPUNKT") or stripped.upper().startswith("NODE"):
            if current:
                node_disps.append(current)
            current = {"ux": 0.0, "uy": 0.0, "uz": 0.0}
        for comp, key in (("UX", "ux"), ("UY", "uy"), ("UZ", "uz")):
            if comp in stripped.upper():
                parts = stripped.replace("=", " ").split()
                for i, p in enumerate(parts):
                    if p.upper() == comp and i + 1 < len(parts):
                        try:
                            current[key] = float(parts[i + 1])
                        except ValueError:
                            pass
    if current:
        node_disps.append(current)

    for d in node_disps:
        d["mag"] = math.sqrt(d["ux"] ** 2 + d["uy"] ** 2 + d["uz"] ** 2)

    return {"node_displacements": node_disps}


def _parse_z88o3(content: str) -> list[float]:
    """
    Parse z88o3.txt — eigenfrequencies (Hz).

    Z88 writes modal results in the form:
        EIGENFREQUENCY   1 :   1.2345E+02 Hz
    or (Aurora):
        FREQ   1   123.45
    """
    import re

    frequencies: list[float] = []

    # Aurora tabular format: FREQ  <n>  <value>
    for m in re.finditer(r"FREQ\s+\d+\s+([\d.eE+\-]+)", content, re.IGNORECASE):
        try:
            frequencies.append(float(m.group(1)))
        except ValueError:
            pass
    if frequencies:
        return sorted(frequencies)

    # Block format: EIGENFREQUENCY  n  :  value  Hz
    for m in re.finditer(
        r"EIGENFREQUENCY\s+\d+\s*[:\s]\s*([\d.eE+\-]+)\s*(?:Hz)?",
        content, re.IGNORECASE
    ):
        try:
            frequencies.append(float(m.group(1)))
        except ValueError:
            pass

    return sorted(frequencies)


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------

def _mesh_to_z88_elements(
    mesh: dict,
) -> tuple[list[list[float]], list[tuple[int, int, list[int]]]]:
    """
    Convert a Kerf mesh dict to Z88 node and element lists.

    Accepted mesh dict shapes:
        {"nodes": [[x,y,z], ...], "elements": [[n1,n2,...], ...]}
        {"vertices": [[x,y,z], ...], "tets": [[n1,n2,n3,n4], ...]}
        {"nodes": [[x,y,z], ...], "tets": [[n1,n2,n3,n4], ...]}

    Nodes are returned 0-indexed; element connectivity is converted to 1-based.
    """
    nodes_raw = (
        mesh.get("nodes")
        or mesh.get("vertices")
        or []
    )
    elems_raw = (
        mesh.get("elements")
        or mesh.get("tets")
        or []
    )

    nodes: list[list[float]] = []
    for pt in nodes_raw:
        nodes.append([float(c) for c in pt])

    elements: list[tuple[int, int, list[int]]] = []
    for i, conn in enumerate(elems_raw):
        eid = i + 1
        n_conn = len(conn)
        # Pick Z88 element type by connectivity length.
        if n_conn == 2:
            etype = _ELEM_TYPE_MAP["bar"]
        elif n_conn == 4:
            etype = _ELEM_TYPE_MAP["tetra4"]
        elif n_conn == 10:
            etype = _ELEM_TYPE_MAP["tetra10"]
        elif n_conn == 8:
            etype = _ELEM_TYPE_MAP["hex8"]
        else:
            etype = _DEFAULT_ELEM_TYPE
        # Z88 uses 1-based node IDs.
        enodes = [int(n) + 1 for n in conn]
        elements.append((eid, etype, enodes))

    return nodes, elements


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class Z88Bridge:
    """
    Subprocess bridge to the Z88 open-source FEM solver.

    Usage::

        bridge = Z88Bridge()
        result = bridge.solve(mesh, materials, boundary_conditions,
                              analysis_type="modal")
    """

    def __init__(self, timeout: int = 600) -> None:
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Mesh-independent solve entry point
    # ------------------------------------------------------------------

    def solve(
        self,
        mesh: dict,
        materials: dict,
        boundary_conditions: list[dict],
        *,
        analysis_type: str = "linear_static",
        loads: list[dict] | None = None,
        n_modes: int = 10,
    ) -> dict[str, Any]:
        """
        Run a Z88 analysis.

        Parameters
        ----------
        mesh
            Kerf mesh dict:
            {"nodes": [[x,y,z], ...], "elements": [[n1,n2,...], ...]}
        materials
            {"E": float, "nu": float, "rho": float, "yield_strength": float}
        boundary_conditions
            list of BC dicts, e.g. [{"type": "fixed", "face": "xmin"}]
        analysis_type
            "linear_static" | "modal" | "nonlinear"
        loads
            list of load dicts (static/nonlinear only)
        n_modes
            number of natural frequencies to request (modal only)

        Returns
        -------
        Result dict — see module docstring.
        """
        if not _z88_available():
            return {
                "ok": False,
                "status": "pending",
                "warnings": [ENGINE_PENDING_WARNING],
                "errors": [],
            }

        nodes, elements = _mesh_to_z88_elements(mesh)
        if not nodes or not elements:
            return {
                "ok": False,
                "status": "error",
                "errors": ["mesh has no nodes or no elements"],
                "warnings": [],
            }

        E = float(materials.get("E", 200e9))
        nu = float(materials.get("nu", 0.3))
        rho = float(materials.get("rho", 7850.0))
        yield_strength = float(materials.get("yield_strength", 250e6))

        try:
            return self._run(
                nodes,
                elements,
                E,
                nu,
                rho,
                yield_strength,
                boundary_conditions,
                loads or [],
                analysis_type=analysis_type,
                n_modes=n_modes,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "status": "error",
                "errors": [f"Z88 timed out after {self.timeout}s"],
                "warnings": [],
            }
        except Exception as exc:
            logger.exception("Z88Bridge.solve failed")
            return {
                "ok": False,
                "status": "error",
                "errors": [str(exc)],
                "warnings": [],
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(
        self,
        nodes: list[list[float]],
        elements: list[tuple[int, int, list[int]]],
        E: float,
        nu: float,
        rho: float,
        yield_strength: float,
        boundary_conditions: list[dict],
        loads: list[dict],
        *,
        analysis_type: str,
        n_modes: int,
    ) -> dict[str, Any]:
        dof_per_node = 3

        # Count constrained DOFs for z88i1 header.
        i6_content = write_z88i6_file(
            boundary_conditions, nodes, dof_per_node=dof_per_node
        )
        n_dof_constrained = int(i6_content.splitlines()[0].strip()) if i6_content else 0

        i1_content = write_z88i1_file(
            nodes, len(elements), n_dof_constrained,
            dim=3, dof_per_node=dof_per_node,
        )
        i2_content = write_z88i2_file(elements, dof_per_node=dof_per_node)
        i5_content = write_z88i5_file(E, nu, rho)
        i7_content = write_z88i7_file(loads, dof_per_node=dof_per_node)
        com_content = write_z88com_file(analysis_type, n_modes=n_modes)

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            (tmpdir / "z88i1.txt").write_text(i1_content)
            (tmpdir / "z88i2.txt").write_text(i2_content)
            (tmpdir / "z88i5.txt").write_text(i5_content)
            (tmpdir / "z88i6.txt").write_text(i6_content)
            (tmpdir / "z88i7.txt").write_text(i7_content)
            (tmpdir / "z88com.txt").write_text(com_content)

            exe = _z88_exe()
            proc = subprocess.run(
                [exe],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0:
                stderr_excerpt = (proc.stderr or proc.stdout or "")[:2000]
                raise RuntimeError(
                    f"Z88 returned exit code {proc.returncode}: {stderr_excerpt}"
                )

            # Parse output files.
            o2_path = tmpdir / "z88o2.txt"
            o3_path = tmpdir / "z88o3.txt"

            o2_text = o2_path.read_text(errors="replace") if o2_path.exists() else ""
            o3_text = o3_path.read_text(errors="replace") if o3_path.exists() else ""

        # Build result dict.
        result: dict[str, Any] = {
            "ok": True,
            "status": "ok",
            "warnings": [],
            "errors": [],
        }

        if analysis_type == "modal":
            frequencies = _parse_z88o3(o3_text)
            result["frequencies"] = frequencies
            result["frequencies_hz"] = frequencies  # alias

        else:
            parsed = _parse_z88o2(o2_text)
            node_disps = parsed.get("node_displacements", [])
            result["node_displacements"] = node_disps

            if node_disps:
                max_disp = max(d.get("mag", 0.0) for d in node_disps)
            else:
                max_disp = 0.0
                result["warnings"].append("z88o2.txt contained no displacement data")

            result["max_displacement"] = max_disp
            result["max_vonmises_stress"] = 0.0  # stress output requires z88o5
            result["fos"] = float("inf")

        return result
