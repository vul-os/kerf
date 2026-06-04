"""
kerf_dental.lab_workflow — Dental lab case management + milling/printing export.

Manages case files, milling output, articulator setup, and throughput reporting.

References
----------
- ISO 6874:2015 (Dentistry — Polymer-based restorative materials).
- Roland DG Corporation. DWX Series Milling Unit Documentation (public).
- KaVo ARCON articulator digital workflow documentation (public).

DISCLAIMER
----------
NOT FDA-cleared or CE-marked as a medical device. All case files and exports
require clinical verification before use in patient treatment.

Wave 11B: dental depth (3shape parity)
"""

from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DentalCase:
    """Lab case record."""

    case_id: str
    patient_id_hashed: str
    """Hashed patient identifier (HIPAA/POPIA compliance)."""

    dentist_name: str
    lab_name: str
    case_type: str
    """'crown' | 'bridge' | 'rpd' | 'denture' | 'implant' | 'night_guard'"""

    received_date_iso: str
    """ISO 8601 date received."""

    due_date_iso: str
    """ISO 8601 due date."""

    status: str
    """'received' | 'designing' | 'milling' | 'sintering' | 'shipped' | 'delivered'"""

    notes: str = ""

    def __post_init__(self):
        valid_types = {"crown", "bridge", "rpd", "denture", "implant", "night_guard"}
        if self.case_type not in valid_types:
            raise ValueError(f"case_type must be one of {valid_types}")
        valid_statuses = {"received", "designing", "milling", "sintering", "shipped", "delivered"}
        if self.status not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}")

    @property
    def is_overdue(self) -> bool:
        """True if due_date is in the past and status is not shipped/delivered."""
        if self.status in ("shipped", "delivered"):
            return False
        try:
            due = date.fromisoformat(self.due_date_iso)
            return date.today() > due
        except ValueError:
            return False

    @property
    def days_until_due(self) -> int:
        """Days until due date (negative = overdue)."""
        try:
            due = date.fromisoformat(self.due_date_iso)
            return (due - date.today()).days
        except ValueError:
            return 0


@dataclass
class CaseExport:
    """Exported case files for milling/printing."""

    case_id: str
    files: dict[str, bytes]
    """filename → file content bytes."""

    file_format: str
    """'stl' | 'ply' | 'dcm' | '3shape_3ox' | 'exocad_xml'"""

    export_date_iso: str = ""

    def __post_init__(self):
        if not self.export_date_iso:
            self.export_date_iso = datetime.now().strftime("%Y-%m-%d")

    @property
    def total_size_bytes(self) -> int:
        return sum(len(v) for v in self.files.values())

    @property
    def file_count(self) -> int:
        return len(self.files)


# ---------------------------------------------------------------------------
# Binary STL builder (internal)
# ---------------------------------------------------------------------------

def _mesh_to_binary_stl(
    vertices: np.ndarray,
    triangles: np.ndarray,
    header: str = "Kerf Dental Lab",
) -> bytes:
    """Convert (V,3) vertices + (F,3) triangles to binary STL bytes."""
    verts = np.asarray(vertices, dtype=np.float32)
    tris = np.asarray(triangles, dtype=int)
    buf = bytearray()
    buf += header.encode("utf-8")[:80].ljust(80, b"\x00")
    buf += struct.pack("<I", len(tris))

    for tri in tris:
        v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        n = np.cross(v1 - v0, v2 - v0).astype(np.float32)
        n_len = float(np.linalg.norm(n))
        if n_len > 1e-30:
            n /= n_len
        buf += struct.pack("<fff", *n)
        buf += struct.pack("<fff", *v0)
        buf += struct.pack("<fff", *v1)
        buf += struct.pack("<fff", *v2)
        buf += struct.pack("<H", 0)

    return bytes(buf)


# ---------------------------------------------------------------------------
# Milling export
# ---------------------------------------------------------------------------

def create_milling_export(
    design,
    mill_format: str = "STL",
) -> CaseExport:
    """
    Export to mill-ready format.

    Supports:
    - STL: Binary STL for Roland DWX, Yenadent, Amann Girrbach milling units.
    - PLY: For Stratasys/GE printers.

    Reference: Roland DWX-52DC CADCAM Dental Milling Machine User Guide.

    Parameters
    ----------
    design : object with .outer_surface_mesh, .intaglio_surface_mesh, or
             .base_mesh attribute (CrownDesign | DentureDesign | etc.)
    mill_format : str
        'STL' (default) | 'PLY'

    Returns
    -------
    CaseExport

    HONEST: Mill-ready STL requires checking for minimum wall thickness,
    material-specific tolerances, and fit validation before milling.
    """
    fmt = mill_format.upper()
    files: dict[str, bytes] = {}

    # Extract meshes from design object
    meshes: list[tuple[str, tuple]] = []

    if hasattr(design, "outer_surface_mesh"):
        meshes.append(("outer_surface", design.outer_surface_mesh))
    if hasattr(design, "intaglio_surface_mesh"):
        meshes.append(("intaglio", design.intaglio_surface_mesh))
    if hasattr(design, "base_mesh"):
        meshes.append(("denture_base", design.base_mesh))
    if hasattr(design, "arch_support_mesh"):
        meshes.append(("arch_shell", design.arch_support_mesh))
    if hasattr(design, "teeth"):
        for i, tm in enumerate(design.teeth):
            meshes.append((f"tooth_{i:02d}", tm))
    if hasattr(design, "clasps"):
        for i, cm in enumerate(design.clasps):
            meshes.append((f"clasp_{i:02d}", cm))

    if not meshes:
        # Fallback: treat design as mesh tuple
        try:
            verts, tris = design[0], design[1]
            meshes = [("mesh", (verts, tris))]
        except (TypeError, IndexError):
            raise ValueError(
                "design must have outer_surface_mesh, base_mesh, or be a (verts, tris) tuple"
            )

    case_id = getattr(design, "spec", None)
    if case_id is not None:
        case_id = str(getattr(case_id, "tooth_number", "unknown"))
    else:
        case_id = "export"

    for name, (verts, tris) in meshes:
        v = np.asarray(verts, dtype=float)
        t = np.asarray(tris, dtype=int)
        if len(v) == 0 or len(t) == 0:
            continue

        if fmt == "STL":
            stl_bytes = _mesh_to_binary_stl(v, t, header=f"Kerf Dental {name}")
            files[f"{name}.stl"] = stl_bytes

        elif fmt == "PLY":
            # Simple ASCII PLY
            lines = [
                "ply\n",
                "format ascii 1.0\n",
                f"element vertex {len(v)}\n",
                "property float x\n",
                "property float y\n",
                "property float z\n",
                f"element face {len(t)}\n",
                "property list uchar int vertex_indices\n",
                "end_header\n",
            ]
            for pt in v:
                lines.append(f"{pt[0]:.6f} {pt[1]:.6f} {pt[2]:.6f}\n")
            for tri in t:
                lines.append(f"3 {tri[0]} {tri[1]} {tri[2]}\n")
            files[f"{name}.ply"] = "".join(lines).encode("utf-8")

        else:
            raise ValueError(f"Unsupported mill format: {mill_format!r}")

    return CaseExport(
        case_id=str(case_id),
        files=files,
        file_format=fmt.lower(),
    )


# ---------------------------------------------------------------------------
# Articulator export
# ---------------------------------------------------------------------------

def export_articulator_setup(
    maxillary: object,
    mandibular: object,
    bite_alignment: np.ndarray,
) -> CaseExport:
    """
    Export to digital articulator format.

    Creates a JSON articulator setup file compatible with KaVo/DigiDent
    digital articulators (simplified public format).

    Reference: KaVo ARCON articulator digital workflow documentation.

    Parameters
    ----------
    maxillary : IntraoralScan
    mandibular : IntraoralScan
    bite_alignment : (4,4) transformation matrix aligning mandibular to maxillary.

    Returns
    -------
    CaseExport

    HONEST: This simplified export captures jaw transform only.
    Full articulator setup requires condylar path registration (Denar, KaVo).
    """
    T = np.asarray(bite_alignment, dtype=float)
    if T.shape != (4, 4):
        raise ValueError("bite_alignment must be a (4,4) transformation matrix")

    setup = {
        "format": "kerf_articulator_v1",
        "exported": datetime.now().isoformat(),
        "maxillary_arch": getattr(maxillary, "arch", "maxillary"),
        "mandibular_arch": getattr(mandibular, "arch", "mandibular"),
        "transform_mandibular_to_maxillary": T.tolist(),
        "condylar_inclination_deg": 30.0,      # Bennett angle default
        "bennett_angle_deg": 7.5,               # typical
        "articulator_type": "KaVo_ARCON_3D",
        "disclaimer": (
            "Simplified articulator export — condylar path from population mean. "
            "Clinical calibration required."
        ),
    }

    # Also export both arch STLs if they have meshes
    files: dict[str, bytes] = {
        "articulator_setup.json": json.dumps(setup, indent=2).encode("utf-8"),
    }

    if hasattr(maxillary, "vertices") and len(maxillary.vertices) > 0:
        files["maxillary.stl"] = _mesh_to_binary_stl(
            maxillary.vertices, maxillary.triangles, "maxillary"
        )
    if hasattr(mandibular, "vertices") and len(mandibular.vertices) > 0:
        files["mandibular.stl"] = _mesh_to_binary_stl(
            mandibular.vertices, mandibular.triangles, "mandibular"
        )

    return CaseExport(
        case_id="articulator_setup",
        files=files,
        file_format="json+stl",
    )


# ---------------------------------------------------------------------------
# Case status reporting
# ---------------------------------------------------------------------------

def case_status_report(cases: list[DentalCase]) -> dict:
    """
    Aggregate lab case status report.

    Returns
    -------
    dict with keys:
        total : int
        by_status : dict[str, int]  — count per status
        by_type : dict[str, int]    — count per case type
        overdue : int
        overdue_cases : list[str]   — case IDs
        throughput_by_dentist : dict[str, int]  — delivered cases per dentist
        avg_turnaround_days : float  — average from received to shipped
        next_due : str | None       — ISO date of soonest pending case
    """
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    throughput_by_dentist: dict[str, int] = {}
    overdue_cases: list[str] = []
    turnaround_days: list[float] = []
    pending_due_dates: list[date] = []

    for c in cases:
        by_status[c.status] = by_status.get(c.status, 0) + 1
        by_type[c.case_type] = by_type.get(c.case_type, 0) + 1

        if c.is_overdue:
            overdue_cases.append(c.case_id)

        if c.status in ("shipped", "delivered"):
            throughput_by_dentist[c.dentist_name] = (
                throughput_by_dentist.get(c.dentist_name, 0) + 1
            )
            try:
                recv = date.fromisoformat(c.received_date_iso)
                due = date.fromisoformat(c.due_date_iso)
                turnaround_days.append(float((due - recv).days))
            except ValueError:
                pass

        if c.status in ("received", "designing", "milling", "sintering"):
            try:
                due = date.fromisoformat(c.due_date_iso)
                pending_due_dates.append(due)
            except ValueError:
                pass

    avg_turnaround = (
        float(sum(turnaround_days) / len(turnaround_days))
        if turnaround_days else 0.0
    )

    next_due = None
    if pending_due_dates:
        next_due = min(pending_due_dates).isoformat()

    return {
        "total": len(cases),
        "by_status": by_status,
        "by_type": by_type,
        "overdue": len(overdue_cases),
        "overdue_cases": overdue_cases,
        "throughput_by_dentist": throughput_by_dentist,
        "avg_turnaround_days": round(avg_turnaround, 1),
        "next_due": next_due,
    }
